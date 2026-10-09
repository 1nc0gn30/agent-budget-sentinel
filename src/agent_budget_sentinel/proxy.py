"""Inline Spending Circuit Breaker Proxy Server.

100% Python Standard Library — Zero External Dependencies.
"""

from __future__ import annotations

import http.server
import json
import logging
import socketserver
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

from .breaker import BreakerState, CircuitBreaker
from .calculator import CostCalculator
from .storage import BudgetStorage, TransactionRecord

logger = logging.getLogger("agent_budget_sentinel.proxy")


class BudgetProxyHandler(http.server.BaseHTTPRequestHandler):
    """Intercepts LLM API calls, evaluates token budgets, trips circuit breaker, or tallies cost."""

    server: BudgetProxyServer

    def log_message(self, format: str, *args: Any) -> None:
        # Keep terminal clean and quiet
        pass

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self) -> None:
        """Health and proxy info endpoint."""
        if self.path in ("/health", "/", "/status"):
            status = self.server.breaker.get_status()
            resp = json.dumps({
                "service": "agent-budget-sentinel-proxy",
                "status": "healthy",
                "port": self.server.server_port,
                "circuit_breaker": status
            }, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        self._handle_forward()

    def do_POST(self) -> None:
        """Evaluate budget, trip circuit if breached, or proxy upstream."""
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""

        # Attempt to parse body as JSON
        payload: Dict[str, Any] = {}
        try:
            if body_bytes:
                payload = json.loads(body_bytes.decode("utf-8", errors="replace"))
        except Exception:
            payload = {}

        model = payload.get("model", "unknown")
        # Estimate prompt tokens and projected cost
        estimated_prompt_tokens = CostCalculator.estimate_payload_tokens(payload)
        # Conservative upper bound estimate assuming ~500 completion tokens
        projected_cost = CostCalculator.calculate_cost_usd(model, estimated_prompt_tokens, completion_tokens=500)

        # 1. Circuit Breaker Evaluation
        allowed, state, reason = self.server.breaker.evaluate_request(projected_cost)
        
        client_ip = self.client_address[0] if self.client_address else "127.0.0.1"

        if not allowed:
            # CIRCUIT BREAKER TRIPPED — BLOCK CALL
            self._send_breaker_rejection(model, estimated_prompt_tokens, client_ip, reason)
            return

        # 2. Forward Upstream
        self._forward_upstream(body_bytes, payload, model, estimated_prompt_tokens, client_ip)

    def _send_breaker_rejection(
        self,
        model: str,
        estimated_tokens: int,
        client_ip: str,
        reason: str
    ) -> None:
        """Reject request with HTTP 429 Too Many Requests."""
        status = self.server.breaker.get_status()
        
        # Log to SQLite
        record = TransactionRecord(
            id=None,
            timestamp="",
            model=model,
            prompt_tokens=estimated_tokens,
            completion_tokens=0,
            cost_usd=0.0,
            latency_ms=1.2,
            status_code=429,
            path=self.path,
            source_ip=client_ip,
            tripped=True,
            reason=reason
        )
        self.server.storage.record_transaction(record)

        err_body = {
            "error": {
                "message": f"agent-budget-sentinel: Circuit breaker is TRIPPED. Spending halted: {reason}",
                "type": "budget_exceeded_error",
                "param": None,
                "code": "budget_circuit_tripped",
                "current_spend_usd": status["current_spend_usd"],
                "max_budget_usd": status["max_budget_usd"],
                "trip_reason": reason,
            }
        }
        resp_bytes = json.dumps(err_body, indent=2).encode("utf-8")

        self.send_response(429)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Budget-State", "TRIPPED")
        self.send_header("X-Budget-Spend", f"{status['current_spend_usd']:.6f}")
        self.send_header("X-Budget-Limit", f"{status['max_budget_usd']:.2f}")
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.end_headers()
        self.wfile.write(resp_bytes)

    def _resolve_upstream_url(self) -> str:
        """Determine destination URL."""
        # 1. Custom override header
        custom_target = self.headers.get("X-Target-Url") or self.headers.get("x-target-url")
        if custom_target:
            return custom_target.rstrip("/") + self.path

        # 2. Check server configured upstream base
        if self.server.upstream_base:
            return self.server.upstream_base.rstrip("/") + self.path

        # 3. Default fallback based on path
        if "anthropic" in self.path or "messages" in self.path:
            return "https://api.anthropic.com" + self.path
        return "https://api.openai.com" + self.path

    def _forward_upstream(
        self,
        body_bytes: bytes,
        payload: Dict[str, Any],
        model: str,
        estimated_prompt_tokens: int,
        client_ip: str
    ) -> None:
        target_url = self._resolve_upstream_url()
        t0 = time.time()

        # Build forward request
        req = urllib.request.Request(target_url, data=body_bytes if self.command == "POST" else None, method=self.command)
        
        # Copy headers (excluding hop-by-hop headers)
        for key, val in self.headers.items():
            k_lower = key.lower()
            if k_lower in ("host", "content-length", "x-target-url", "connection", "keep-alive"):
                continue
            req.add_header(key, val)

        # Set default host header
        parsed_target = urllib.parse.urlparse(target_url)
        req.add_header("Host", parsed_target.netloc)

        upstream_status = 502
        resp_bytes = b""
        resp_headers = {}

        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                upstream_status = resp.status
                resp_bytes = resp.read()
                resp_headers = dict(resp.headers)
        except urllib.error.HTTPError as e:
            upstream_status = e.code
            resp_bytes = e.read()
            resp_headers = dict(e.headers)
        except Exception as e:
            upstream_status = 502
            err_obj = {
                "error": {
                    "message": f"agent-budget-sentinel proxy error forwarding upstream: {str(e)}",
                    "type": "proxy_error",
                    "code": "upstream_unreachable"
                }
            }
            resp_bytes = json.dumps(err_obj).encode("utf-8")

        latency_ms = round((time.time() - t0) * 1000.0, 2)

        # Parse actual usage if available
        prompt_tokens = estimated_prompt_tokens
        completion_tokens = 0
        try:
            resp_json = json.loads(resp_bytes.decode("utf-8", errors="replace"))
            actual_usage = CostCalculator.extract_actual_usage(resp_json)
            if actual_usage:
                prompt_tokens, completion_tokens = actual_usage
            elif upstream_status == 200:
                # Estimate completion tokens from response text
                text_content = ""
                choices = resp_json.get("choices", [])
                for ch in choices:
                    if "message" in ch and "content" in ch["message"]:
                        text_content += ch["message"]["content"] or ""
                    elif "text" in ch:
                        text_content += ch["text"] or ""
                completion_tokens = CostCalculator.estimate_text_tokens(text_content)
        except Exception:
            pass

        # Calculate exact cost
        cost_usd = CostCalculator.calculate_cost_usd(model, prompt_tokens, completion_tokens)
        
        # Record spend in Circuit Breaker
        if upstream_status < 400:
            new_state = self.server.breaker.record_spend(cost_usd, prompt_tokens, completion_tokens, model)
        else:
            new_state = self.server.breaker.state

        # Log transaction
        record = TransactionRecord(
            id=None,
            timestamp="",
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            status_code=upstream_status,
            path=self.path,
            source_ip=client_ip,
            tripped=False,
            reason=None
        )
        self.server.storage.record_transaction(record)

        status_snap = self.server.breaker.get_status()

        # Send response back to client
        self.send_response(upstream_status)
        for h_key, h_val in resp_headers.items():
            if h_key.lower() in ("content-length", "transfer-encoding", "connection", "content-encoding"):
                continue
            self.send_header(h_key, h_val)

        # Budget Sentinel Telemetry Headers
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Budget-State", new_state.value)
        self.send_header("X-Budget-Cost-USD", f"{cost_usd:.6f}")
        self.send_header("X-Budget-Spend-USD", f"{status_snap['current_spend_usd']:.6f}")
        self.send_header("X-Budget-Limit-USD", f"{status_snap['max_budget_usd']:.2f}")
        self.send_header("X-Budget-Tokens-Prompt", str(prompt_tokens))
        self.send_header("X-Budget-Tokens-Completion", str(completion_tokens))
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.end_headers()
        self.wfile.write(resp_bytes)

    def _handle_forward(self) -> None:
        """Handle GET forwards if requested."""
        self._forward_upstream(b"", {}, "unknown", 0, self.client_address[0] if self.client_address else "127.0.0.1")


class BudgetProxyServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Threaded HTTP Server for inline budget enforcement proxy."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        host: str,
        port: int,
        breaker: CircuitBreaker,
        storage: BudgetStorage,
        upstream_base: Optional[str] = None
    ):
        self.breaker = breaker
        self.storage = storage
        self.upstream_base = upstream_base
        super().__init__((host, port), BudgetProxyHandler)
