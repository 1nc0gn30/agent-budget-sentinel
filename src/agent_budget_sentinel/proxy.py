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

from .breaker import CircuitBreaker
from .calculator import CostCalculator
from .net_guard import is_local_origin, validate_upstream_url
from .storage import BudgetStorage, TransactionRecord

PROXY_VERSION = "2.6.0"


def _is_local_origin(origin: Optional[str]) -> bool:
    """Strict loopback Origin check (delegates to net_guard.is_local_origin)."""
    return is_local_origin(origin)


def _cors_origin(handler: http.server.BaseHTTPRequestHandler) -> Optional[str]:
    origin = handler.headers.get("Origin")
    if origin and _is_local_origin(origin):
        return origin.strip()
    return None


logger = logging.getLogger("agent_budget_sentinel.proxy")


class BudgetProxyHandler(http.server.BaseHTTPRequestHandler):
    """Intercepts LLM API calls, enforces SSRF/CORS/budget guardrails, trips breaker, or tallies cost."""

    server: BudgetProxyServer

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send_security_headers(self, *, include_cors: bool = True) -> None:
        self.send_header("Vary", "Origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        if include_cors:
            allowed_origin = _cors_origin(self)
            if allowed_origin:
                self.send_header("Access-Control-Allow-Origin", allowed_origin)

    def _send_json_error(self, status: int, code: str, message: str, *, include_cors: bool = True) -> None:
        body = json.dumps({"error": {"code": code, "message": message}}, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._send_security_headers(include_cors=include_cors)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reject_foreign_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if origin and not _is_local_origin(origin):
            self._send_json_error(403, "cross_origin_blocked", "cross-origin request blocked", include_cors=False)
            return True
        return False

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight requests strictly."""
        if self._reject_foreign_origin():
            return
        self.send_response(204)
        self._send_security_headers(include_cors=True)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Target-Url, X-Token-Budget, x-api-key")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:
        """Health endpoint or circuit-breaker + SSRF guarded GET forward."""
        if self._reject_foreign_origin():
            return

        if self.path in ("/health", "/", "/status"):
            status = self.server.breaker.get_status()
            resp = json.dumps({
                "service": "agent-budget-sentinel-proxy",
                "version": PROXY_VERSION,
                "status": "healthy",
                "port": self.server.server_port,
                "circuit_breaker": status,
            }, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_security_headers(include_cors=True)
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        client_ip = self.client_address[0] if self.client_address else "127.0.0.1"
        allowed, _state, reason = self.server.breaker.evaluate_request(0.0)
        if not allowed:
            self._send_breaker_rejection("unknown", 0, client_ip, reason)
            return

        self._handle_forward()

    def do_POST(self) -> None:
        """Evaluate origin, budget, SSRF guard, trip circuit if breached, or proxy upstream."""
        if self._reject_foreign_origin():
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_json_error(400, "invalid_content_length", "Invalid Content-Length header.")
            return
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""

        payload: Dict[str, Any] = {}
        try:
            if body_bytes:
                parsed_json = json.loads(body_bytes.decode("utf-8", errors="replace"))
                if isinstance(parsed_json, dict):
                    payload = parsed_json
        except Exception:
            payload = {}

        model = str(payload.get("model") or "unknown")
        estimated_prompt_tokens = CostCalculator.estimate_payload_tokens(payload)
        is_stream = bool(payload.get("stream", False)) or "text/event-stream" in self.headers.get("Accept", "")
        completion_est = 1 if is_stream else 500
        projected_cost = CostCalculator.calculate_cost_usd(model, estimated_prompt_tokens, completion_tokens=completion_est)

        client_ip = self.client_address[0] if self.client_address else "127.0.0.1"

        # 1. Circuit Breaker Evaluation
        allowed, _state, reason = self.server.breaker.evaluate_request(projected_cost)
        if not allowed:
            self._send_breaker_rejection(model, estimated_prompt_tokens, client_ip, reason)
            return

        # 2. Forward Upstream
        if is_stream:
            self._forward_streaming_upstream(body_bytes, payload, model, estimated_prompt_tokens, client_ip)
            return

        self._forward_upstream(body_bytes, payload, model, estimated_prompt_tokens, client_ip)

    def _send_breaker_rejection(
        self,
        model: str,
        estimated_tokens: int,
        client_ip: str,
        reason: str,
    ) -> None:
        """Reject request with HTTP 429 Too Many Requests."""
        status = self.server.breaker.get_status()

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
            reason=reason,
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
        self._send_security_headers(include_cors=True)
        self.send_header("X-Budget-State", "TRIPPED")
        self.send_header("X-Budget-Spend", f"{status['current_spend_usd']:.6f}")
        self.send_header("X-Budget-Limit", f"{status['max_budget_usd']:.2f}")
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.end_headers()
        self.wfile.write(resp_bytes)

    def _resolve_upstream_url(self) -> Tuple[str, bool]:
        """Determine destination URL and whether it came from operator-configured upstream_base."""
        custom_target = self.headers.get("X-Target-Url") or self.headers.get("x-target-url")
        if custom_target:
            return custom_target.strip().rstrip("/") + self.path, False

        if self.server.upstream_base:
            return self.server.upstream_base.strip().rstrip("/") + self.path, True

        if "anthropic" in self.path or "messages" in self.path:
            return "https://api.anthropic.com" + self.path, False
        return "https://api.openai.com" + self.path, False

    def _resolve_and_guard_upstream(self) -> Optional[str]:
        target_url, is_configured = self._resolve_upstream_url()
        ok, reason = validate_upstream_url(target_url, allow_configured_local=is_configured)
        if not ok:
            self._send_json_error(403, "upstream_ssrf_blocked", f"Blocked upstream URL: {reason}")
            return None
        return target_url

    def _forward_upstream(
        self,
        body_bytes: bytes,
        payload: Dict[str, Any],
        model: str,
        estimated_prompt_tokens: int,
        client_ip: str,
    ) -> None:
        target_url = self._resolve_and_guard_upstream()
        if target_url is None:
            return

        t0 = time.time()
        req = urllib.request.Request(
            target_url,
            data=body_bytes if self.command == "POST" else None,
            method=self.command,
        )

        for key, val in self.headers.items():
            k_lower = key.lower()
            if k_lower in ("host", "content-length", "x-target-url", "connection", "keep-alive"):
                continue
            req.add_header(key, val)

        parsed_target = urllib.parse.urlparse(target_url)
        req.add_header("Host", parsed_target.netloc)

        upstream_status = 502
        resp_bytes = b""
        resp_headers: Dict[str, str] = {}

        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                upstream_status = int(resp.status) if resp.status is not None else 502
                resp_bytes = resp.read()
                resp_headers = dict(resp.headers)
        except urllib.error.HTTPError as e:
            upstream_status = int(e.code) if e.code is not None else 502
            resp_bytes = e.read()
            resp_headers = dict(e.headers)
        except Exception as e:
            upstream_status = 502
            err_obj = {
                "error": {
                    "message": f"agent-budget-sentinel proxy error forwarding upstream: {str(e)}",
                    "type": "proxy_error",
                    "code": "upstream_unreachable",
                }
            }
            resp_bytes = json.dumps(err_obj).encode("utf-8")

        latency_ms = round((time.time() - t0) * 1000.0, 2)

        prompt_tokens = estimated_prompt_tokens
        completion_tokens = 0
        try:
            resp_json = json.loads(resp_bytes.decode("utf-8", errors="replace"))
            actual_usage = CostCalculator.extract_actual_usage(resp_json)
            if actual_usage:
                prompt_tokens, completion_tokens = actual_usage
            elif upstream_status == 200:
                text_content = ""
                for ch in resp_json.get("choices", []):
                    if "message" in ch and "content" in ch["message"]:
                        text_content += ch["message"]["content"] or ""
                    elif "text" in ch:
                        text_content += ch["text"] or ""
                completion_tokens = CostCalculator.estimate_text_tokens(text_content)
        except Exception:
            pass

        cost_usd = CostCalculator.calculate_cost_usd(model, prompt_tokens, completion_tokens)

        if upstream_status < 400:
            new_state = self.server.breaker.record_spend(cost_usd, prompt_tokens, completion_tokens, model)
        else:
            new_state = self.server.breaker.state

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
            reason=None,
        )
        self.server.storage.record_transaction(record)

        status_snap = self.server.breaker.get_status()

        self.send_response(upstream_status)
        for h_key, h_val in resp_headers.items():
            if h_key.lower() in (
                "content-length", "transfer-encoding", "connection",
                "content-encoding", "access-control-allow-origin",
            ):
                continue
            self.send_header(h_key, h_val)

        self._send_security_headers(include_cors=True)
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
        client_ip: str,
    ) -> None:
        """Stream SSE chunks in real time and enforce mid-flight budget / token limits."""
        target_url = self._resolve_and_guard_upstream()
        if target_url is None:
            return

        t0 = time.time()
        req = urllib.request.Request(
            target_url,
            data=body_bytes if self.command == "POST" else None,
            method=self.command,
        )

        for key, val in self.headers.items():
            k_lower = key.lower()
            if k_lower in ("host", "content-length", "x-target-url", "connection", "keep-alive"):
                continue
            req.add_header(key, val)

        parsed_target = urllib.parse.urlparse(target_url)
        req.add_header("Host", parsed_target.netloc)

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
            upstream_status = int(resp.status) if resp.status is not None else 502
        except urllib.error.HTTPError as e:
            upstream_status = int(e.code) if e.code is not None else 502
            resp_bytes = e.read()
            self.send_response(upstream_status)
            for h_key, h_val in e.headers.items():
                if h_key.lower() in (
                    "content-length", "transfer-encoding", "connection",
                    "content-encoding", "access-control-allow-origin",
                ):
                    continue
                self.send_header(h_key, h_val)
            self._send_security_headers(include_cors=True)
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)
            return
        except Exception as e:
            self._send_json_error(
                502,
                "upstream_unreachable",
                f"agent-budget-sentinel proxy error forwarding upstream: {str(e)}",
            )
            return

        self.send_response(upstream_status)
        for h_key, h_val in resp.headers.items():
            if h_key.lower() in (
                "content-length", "transfer-encoding", "connection",
                "content-encoding", "access-control-allow-origin",
            ):
                continue
            self.send_header(h_key, h_val)

        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self._send_security_headers(include_cors=True)
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
                            for ch in chunk_obj.get("choices", []):
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

                        token_budget_exceeded = False
                        if query_token_budget is not None and query_token_budget > 0:
                            if accumulated_completion_tokens >= query_token_budget:
                                token_budget_exceeded = True
                            elif query_token_budget > estimated_prompt_tokens and (
                                estimated_prompt_tokens + accumulated_completion_tokens
                            ) >= query_token_budget:
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
            self.server.breaker.record_spend(
                stream_cost, estimated_prompt_tokens, accumulated_completion_tokens, model
            )
            self.server.breaker.trip(trip_reason)

            terminal_event = (
                b"event: circuit_breaker_trip\n"
                b'data: {"error": "Budget limit exceeded mid-stream. Circuit breaker tripped."}\n\n'
            )
            try:
                self.wfile.write(terminal_event)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

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
                reason=trip_reason,
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
                reason=None,
            )
            self.server.storage.record_transaction(record)

    def _handle_forward(self) -> None:
        """Handle GET forwards with SSRF & circuit-breaker protection."""
        self._forward_upstream(
            b"", {}, "unknown", 0, self.client_address[0] if self.client_address else "127.0.0.1"
        )


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
        upstream_base: Optional[str] = None,
    ):
        self.breaker = breaker
        self.storage = storage
        self.upstream_base = upstream_base
        super().__init__((host, port), BudgetProxyHandler)
