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
        is_stream = bool(payload.get("stream", False)) or "text/event-stream" in self.headers.get("Accept", "")
        completion_est = 1 if is_stream else 500
        projected_cost = CostCalculator.calculate_cost_usd(model, estimated_prompt_tokens, completion_tokens=completion_est)

        # 1. Circuit Breaker Evaluation
        allowed, state, reason = self.server.breaker.evaluate_request(projected_cost)
        
        client_ip = self.client_address[0] if self.client_address else "127.0.0.1"

        if not allowed:
            # CIRCUIT BREAKER TRIPPED — BLOCK CALL
            self._send_breaker_rejection(model, estimated_prompt_tokens, client_ip, reason)
            return

        # 2. Forward Upstream
        if is_stream:
            self._forward_streaming_upstream(body_bytes, payload, model, estimated_prompt_tokens, client_ip)
            return

        # 3. Forward Upstream (non-streaming)
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

    def _forward_streaming_upstream(
        self,
        body_bytes: bytes,
        payload: Dict[str, Any],
        model: str,
        estimated_prompt_tokens: int,
        client_ip: str
    ) -> None:
        """Stream SSE chunks in real time and enforce mid-flight budget / token limits."""
        target_url = self._resolve_upstream_url()
        t0 = time.time()

        req = urllib.request.Request(
            target_url,
            data=body_bytes if self.command == "POST" else None,
            method=self.command
        )

        for key, val in self.headers.items():
            k_lower = key.lower()
            if k_lower in ("host", "content-length", "x-target-url", "connection", "keep-alive"):
                continue
            req.add_header(key, val)

        parsed_target = urllib.parse.urlparse(target_url)
        req.add_header("Host", parsed_target.netloc)

        # Resolve query token budget from headers, payload, or policy
        query_token_budget: Optional[int] = None
        for h in ("X-Token-Budget", "x-token-budget", "X-Query-Budget", "x-query-budget", "X-Max-Tokens", "x-max-tokens"):
            if h in self.headers:
                try:
                    query_token_budget = int(self.headers[h])
                    break
                except (ValueError, TypeError):
                    pass

        if query_token_budget is None:
            for k in ("query_token_budget", "token_budget", "max_tokens", "max_completion_tokens"):
                if k in payload and payload[k] is not None:
                    try:
                        query_token_budget = int(payload[k])
                        break
                    except (ValueError, TypeError):
                        pass

        if query_token_budget is None and hasattr(self.server.breaker.policy, "query_token_budget"):
            query_token_budget = self.server.breaker.policy.query_token_budget

        upstream_status = 502
        resp = None

        try:
            resp = urllib.request.urlopen(req, timeout=30.0)
            upstream_status = resp.status
        except urllib.error.HTTPError as e:
            upstream_status = e.code
            resp_bytes = e.read()
            self.send_response(upstream_status)
            for h_key, h_val in e.headers.items():
                if h_key.lower() in ("content-length", "transfer-encoding", "connection", "content-encoding"):
                    continue
                self.send_header(h_key, h_val)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)
            return
        except Exception as e:
            err_obj = {
                "error": {
                    "message": f"agent-budget-sentinel proxy error forwarding upstream: {str(e)}",
                    "type": "proxy_error",
                    "code": "upstream_unreachable"
                }
            }
            resp_bytes = json.dumps(err_obj).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)
            return

        # Upstream succeeded. Forward SSE response headers.
        self.send_response(upstream_status)
        for h_key, h_val in resp.headers.items():
            if h_key.lower() in ("content-length", "transfer-encoding", "connection", "content-encoding"):
                continue
            self.send_header(h_key, h_val)

        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Budget-State", self.server.breaker.state.value)
        self.end_headers()
        self.close_connection = True

        accumulated_completion_tokens = 0
        tripped_mid_stream = False
        trip_reason = ""

        try:
            while True:
                line = resp.readline()
                if not line:
                    break

                if line.startswith(b"data:"):
                    data_payload = line[5:].strip()
                    if data_payload != b"[DONE]":
                        try:
                            chunk_obj = json.loads(data_payload.decode("utf-8", errors="replace"))
                            delta_text = ""
                            choices = chunk_obj.get("choices", [])
                            for ch in choices:
                                delta = ch.get("delta", {})
                                if "content" in delta and delta["content"]:
                                    delta_text += delta["content"]
                                elif "text" in ch and ch["text"]:
                                    delta_text += ch["text"]
                            if chunk_obj.get("type") == "content_block_delta":
                                d = chunk_obj.get("delta", {})
                                if d.get("type") == "text_delta" and "text" in d:
                                    delta_text += d["text"]

                            if delta_text:
                                chunk_tokens = CostCalculator.estimate_text_tokens(delta_text)
                                accumulated_completion_tokens += chunk_tokens
                        except Exception:
                            pass

                        # Evaluate mid-stream budget conditions:
                        token_budget_exceeded = False
                        if query_token_budget is not None and query_token_budget > 0:
                            if accumulated_completion_tokens >= query_token_budget:
                                token_budget_exceeded = True
                            elif query_token_budget > estimated_prompt_tokens and (estimated_prompt_tokens + accumulated_completion_tokens) >= query_token_budget:
                                token_budget_exceeded = True

                        current_cost = CostCalculator.calculate_cost_usd(
                            model, estimated_prompt_tokens, accumulated_completion_tokens
                        )
                        projected_total = self.server.breaker.total_spend_usd + current_cost
                        cost_budget_exceeded = projected_total >= self.server.breaker.policy.max_budget_usd

                        if token_budget_exceeded or cost_budget_exceeded:
                            tripped_mid_stream = True
                            trip_reason = "Budget limit exceeded mid-stream. Circuit breaker tripped."

                try:
                    self.wfile.write(line)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break

                if tripped_mid_stream:
                    break
        finally:
            # IMMEDIATELY sever upstream TCP connection
            try:
                if hasattr(resp, "fp") and resp.fp:
                    resp.fp.close()
                resp.close()
            except Exception:
                pass

        latency_ms = round((time.time() - t0) * 1000.0, 2)
        stream_cost = CostCalculator.calculate_cost_usd(
            model, estimated_prompt_tokens, accumulated_completion_tokens
        )

        if tripped_mid_stream:
            # 1. Record partial spend and trip circuit breaker state
            self.server.breaker.record_spend(
                stream_cost, estimated_prompt_tokens, accumulated_completion_tokens, model
            )
            self.server.breaker.trip(trip_reason)

            # 2. Emit terminal SSE error event
            terminal_event = (
                b"event: circuit_breaker_trip\n"
                b"data: {\"error\": \"Budget limit exceeded mid-stream. Circuit breaker tripped.\"}\n\n"
            )
            try:
                self.wfile.write(terminal_event)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

            # 3. Log transaction
            record = TransactionRecord(
                id=None,
                timestamp="",
                model=model,
                prompt_tokens=estimated_prompt_tokens,
                completion_tokens=accumulated_completion_tokens,
                cost_usd=stream_cost,
                latency_ms=latency_ms,
                status_code=429,
                path=self.path,
                source_ip=client_ip,
                tripped=True,
                reason=trip_reason
            )
            self.server.storage.record_transaction(record)
        else:
            if upstream_status < 400:
                self.server.breaker.record_spend(
                    stream_cost, estimated_prompt_tokens, accumulated_completion_tokens, model
                )

            record = TransactionRecord(
                id=None,
                timestamp="",
                model=model,
                prompt_tokens=estimated_prompt_tokens,
                completion_tokens=accumulated_completion_tokens,
                cost_usd=stream_cost,
                latency_ms=latency_ms,
                status_code=upstream_status,
                path=self.path,
                source_ip=client_ip,
                tripped=False,
                reason=None
            )
            self.server.storage.record_transaction(record)

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
