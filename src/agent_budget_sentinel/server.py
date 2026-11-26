"""Web Cockpit and Telemetry REST API Server.

100% Python Standard Library — Zero External Dependencies.
"""

from __future__ import annotations

import http.server
import json
import math
import mimetypes
import os
import queue
import socketserver
import urllib.parse
from typing import Any, Dict, Optional

from .breaker import CircuitBreaker
from .calculator import MODEL_PRICING, CostCalculator
from .net_guard import is_local_origin
from .storage import BudgetStorage, TransactionRecord

SERVICE_VERSION = "2.6.0"
_FRAME_ANCESTORS = "frame-ancestors 'self' http://127.0.0.1:3000 http://localhost:3000 http://127.0.0.1:8110"


def _safe_rel(raw: str) -> str:
    """Request path -> safe relative path inside a static dir; '' (index) if it
    tries to climb out with '..' or is absolute. Raw request paths are not normalised."""
    from urllib.parse import unquote
    rel = unquote(str(raw or "")).replace("\\", "/").lstrip("/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts) or ":" in (parts[0] if parts else ""):
        return ""
    return "/".join(parts)


def _is_local_origin(origin: Optional[str]) -> bool:
    """Strict loopback browser Origin check (delegates to net_guard.is_local_origin)."""
    return is_local_origin(origin)


def _cors_origin(handler: http.server.BaseHTTPRequestHandler) -> Optional[str]:
    """Return the validated loopback Origin if present, otherwise None."""
    origin = handler.headers.get("Origin")
    if origin and _is_local_origin(origin):
        return origin.strip()
    return None


def _parse_positive_finite(raw: Any, *, allow_zero: bool = False) -> Optional[float]:
    if isinstance(raw, bool):
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(val):
        return None
    if allow_zero:
        return val if val >= 0.0 else None
    return val if val > 0.0 else None


class WebDeckHandler(http.server.BaseHTTPRequestHandler):
    """Serves the Web Deck and hardened telemetry REST/SSE API."""

    server: BudgetWebServer

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send_security_headers(self, *, include_cors: bool = True) -> None:
        self.send_header("Vary", "Origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", _FRAME_ANCESTORS)
        if include_cors:
            allowed_origin = _cors_origin(self)
            if allowed_origin:
                self.send_header("Access-Control-Allow-Origin", allowed_origin)

    def _reject_foreign_origin(self) -> bool:
        """Return True and send HTTP 403 if Origin header is present and non-loopback."""
        origin = self.headers.get("Origin")
        if origin and not _is_local_origin(origin):
            body = json.dumps({"error": "cross-origin request blocked"}).encode("utf-8")
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self._send_security_headers(include_cors=False)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        return False

    def do_OPTIONS(self) -> None:
        if self._reject_foreign_origin():
            return
        self.send_response(204)
        self._send_security_headers(include_cors=True)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Target-Url")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Health endpoints (allowed from loopback origins & local CLI)
        if path in ("/health", "/api/health"):
            if self._reject_foreign_origin():
                return
            self._send_json({
                "status": "ok",
                "service": "agent-budget-sentinel",
                "version": SERVICE_VERSION,
                "web_port": self.server.server_port,
                "proxy_port": self.server.proxy_port,
                "breaker_state": self.server.breaker.state.value,
            })
            return

        # All /api/* endpoints enforce strict loopback Origin check
        if path.startswith("/api/"):
            if self._reject_foreign_origin():
                return

            if path == "/api/stats":
                stats = self.server.breaker.get_status()
                stats["version"] = SERVICE_VERSION
                stats["models"] = self.server.storage.get_model_breakdown()
                stats["hourly"] = self.server.storage.get_hourly_spend(24)
                self._send_json(stats)
                return

            if path == "/api/transactions":
                query = urllib.parse.parse_qs(parsed.query)
                raw_limit = query.get("limit", ["50"])[0]
                try:
                    limit_val = int(raw_limit)
                except (TypeError, ValueError):
                    self._send_json({"error": "Invalid 'limit' query parameter; must be a positive integer."}, status=400)
                    return
                if limit_val <= 0:
                    self._send_json({"error": "Invalid 'limit' query parameter; must be >= 1."}, status=400)
                    return
                limit_val = min(500, limit_val)
                txs = self.server.storage.get_recent_transactions(limit=limit_val)
                self._send_json({"transactions": txs, "count": len(txs), "limit": limit_val})
                return

            if path == "/api/pricing":
                pricing_data = {
                    k: {
                        "model_id": v.model_id,
                        "input_rate": v.input_rate,
                        "output_rate": v.output_rate,
                        "family": v.family,
                    }
                    for k, v in MODEL_PRICING.items()
                }
                self._send_json({"pricing": pricing_data})
                return

            if path in ("/api/stream", "/api/events"):
                self._handle_sse()
                return

            self._send_json({"error": "Endpoint not found"}, status=404)
            return

        # Static files
        self._serve_static(path)

    def do_POST(self) -> None:
        if self._reject_foreign_origin():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_json({"error": "Invalid Content-Length header"}, status=400)
            return
        if content_length < 0 or content_length > 2_000_000:
            self._send_json({"error": "Request body too large or invalid"}, status=400)
            return

        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""
        payload: Dict[str, Any] = {}
        if body_bytes:
            try:
                decoded = json.loads(body_bytes.decode("utf-8", errors="replace"))
                if not isinstance(decoded, dict):
                    self._send_json({"error": "JSON body must be an object"}, status=400)
                    return
                payload = decoded
            except json.JSONDecodeError:
                self._send_json({"error": "Malformed JSON payload"}, status=400)
                return

        # 1. Set budget
        if path == "/api/budget":
            if "max_budget_usd" not in payload and "velocity_limit" not in payload:
                self._send_json({"error": "Provide 'max_budget_usd' or 'velocity_limit'."}, status=400)
                return

            if "max_budget_usd" in payload:
                new_budget = _parse_positive_finite(payload["max_budget_usd"], allow_zero=False)
                if new_budget is None:
                    self._send_json({"error": "max_budget_usd must be a finite number > 0"}, status=400)
                    return
                self.server.breaker.set_budget(new_budget)
                self.server.storage.set_setting("max_budget_usd", f"{new_budget:.6f}")
                self.server.storage.record_event(
                    "config_change",
                    f"Budget ceiling updated to ${new_budget:.2f}",
                    {"max_budget_usd": new_budget},
                )

            if "velocity_limit" in payload:
                new_vel = _parse_positive_finite(payload["velocity_limit"], allow_zero=True)
                if new_vel is None:
                    self._send_json({"error": "velocity_limit must be a finite number >= 0"}, status=400)
                    return
                self.server.breaker.policy.velocity_limit_usd_per_min = new_vel
                self.server.storage.set_setting("velocity_limit_usd_per_min", f"{new_vel:.6f}")

            self._send_json({"status": "updated", "breaker": self.server.breaker.get_status()})
            return

        # 2. Trip breaker (kill switch)
        if path == "/api/trip":
            reason = str(payload.get("reason") or "Operator emergency kill switch engaged.")
            self.server.breaker.trip(reason)
            self.server.storage.record_event("trip", reason, self.server.breaker.get_status())
            self._send_json({"status": "tripped", "breaker": self.server.breaker.get_status()})
            return

        # 3. Reset breaker
        if path == "/api/reset":
            reset_spend = bool(payload.get("reset_spend", False))
            self.server.breaker.reset(reset_spend=reset_spend)
            if reset_spend:
                self.server.storage.clear_history()
            self.server.storage.record_event(
                "reset",
                "Circuit breaker reset to CLOSED state" + (" and spend cleared" if reset_spend else ""),
                self.server.breaker.get_status(),
            )
            self._send_json({"status": "reset", "breaker": self.server.breaker.get_status()})
            return

        # 4. Simulation endpoint (Interactive Test Tool)
        if path == "/api/simulate":
            model = str(payload.get("model") or "gpt-4o")
            try:
                prompt_tokens = int(payload.get("prompt_tokens", 1200))
                completion_tokens = int(payload.get("completion_tokens", 450))
            except (TypeError, ValueError):
                self._send_json({"error": "prompt_tokens and completion_tokens must be integers"}, status=400)
                return
            if prompt_tokens < 0 or completion_tokens < 0:
                self._send_json({"error": "Token counts must be >= 0"}, status=400)
                return

            projected_cost = CostCalculator.calculate_cost_usd(model, prompt_tokens, completion_tokens)
            allowed, state, reason = self.server.breaker.evaluate_request(projected_cost)

            if not allowed:
                rec = TransactionRecord(
                    id=None,
                    timestamp="",
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=0,
                    cost_usd=0.0,
                    latency_ms=1.5,
                    status_code=429,
                    path="/v1/chat/completions (simulated)",
                    source_ip="127.0.0.1",
                    tripped=True,
                    reason=reason,
                )
                self.server.storage.record_transaction(rec)
                self._send_json({
                    "allowed": False,
                    "status_code": 429,
                    "state": state.value,
                    "reason": reason,
                    "breaker": self.server.breaker.get_status(),
                }, status=429)
                return

            self.server.breaker.record_spend(projected_cost, prompt_tokens, completion_tokens, model)
            rec = TransactionRecord(
                id=None,
                timestamp="",
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=projected_cost,
                latency_ms=35.0,
                status_code=200,
                path="/v1/chat/completions (simulated)",
                source_ip="127.0.0.1",
                tripped=False,
                reason=None,
            )
            self.server.storage.record_transaction(rec)
            self._send_json({
                "allowed": True,
                "status_code": 200,
                "cost_usd": projected_cost,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "state": self.server.breaker.state.value,
                "breaker": self.server.breaker.get_status(),
            })
            return

        # 5. Runaway loop burst simulation (Trips breaker)
        if path == "/api/simulate_runaway":
            try:
                iterations = max(1, min(50, int(payload.get("iterations", 15))))
            except (TypeError, ValueError):
                self._send_json({"error": "iterations must be an integer"}, status=400)
                return
            model = str(payload.get("model") or "o1-preview")
            results = []
            tripped_at_iter = None

            for i in range(iterations):
                p_cost = CostCalculator.calculate_cost_usd(model, 3000, 1000)
                allowed, state, reason = self.server.breaker.evaluate_request(p_cost)
                if not allowed:
                    tripped_at_iter = i + 1
                    rec = TransactionRecord(
                        id=None, timestamp="", model=model, prompt_tokens=3000,
                        completion_tokens=0, cost_usd=0.0, latency_ms=1.1,
                        status_code=429, path="/v1/chat/completions (burst)",
                        source_ip="127.0.0.1", tripped=True, reason=reason,
                    )
                    self.server.storage.record_transaction(rec)
                    results.append({"iteration": i + 1, "allowed": False, "status": 429, "reason": reason})
                    break

                self.server.breaker.record_spend(p_cost, 3000, 1000, model)
                rec = TransactionRecord(
                    id=None, timestamp="", model=model, prompt_tokens=3000,
                    completion_tokens=1000, cost_usd=p_cost, latency_ms=25.0,
                    status_code=200, path="/v1/chat/completions (burst)",
                    source_ip="127.0.0.1", tripped=False,
                )
                self.server.storage.record_transaction(rec)
                results.append({"iteration": i + 1, "allowed": True, "cost_usd": p_cost})

            self._send_json({
                "status": "complete",
                "tripped_at_iteration": tripped_at_iter,
                "iterations_run": len(results),
                "breaker": self.server.breaker.get_status(),
            })
            return

        self._send_json({"error": "Endpoint not found"}, status=404)

    def _handle_sse(self) -> None:
        """Stream real-time spending events to dashboard."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._send_security_headers(include_cors=True)
        self.end_headers()

        q = self.server.storage.subscribe_sse()
        init_event = f"event: init\ndata: {json.dumps(self.server.breaker.get_status())}\n\n"
        try:
            self.wfile.write(init_event.encode("utf-8"))
            self.wfile.flush()

            while True:
                try:
                    msg = q.get(timeout=10.0)
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.server.storage.unsubscribe_sse(q)

    def _serve_static(self, path: str) -> None:
        """Serve public static directory assets."""
        clean_path = _safe_rel(path)
        if not clean_path:
            clean_path = "index.html"

        public_real = os.path.realpath(self.server.public_dir)
        file_path = os.path.realpath(os.path.join(public_real, clean_path))
        if not (file_path == public_real or file_path.startswith(public_real + os.sep)):
            file_path = os.path.join(public_real, "index.html")
        elif not os.path.exists(file_path) or os.path.isdir(file_path):
            file_path = os.path.join(public_real, "index.html")

        if not os.path.exists(file_path):
            self.send_response(404)
            self._send_security_headers(include_cors=True)
            self.end_headers()
            self.wfile.write(b"404 Not Found")
            return

        content_type, _ = mimetypes.guess_type(file_path)
        content_type = content_type or "application/octet-stream"

        try:
            with open(file_path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self._send_security_headers(include_cors=True)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_response(500)
            self._send_security_headers(include_cors=False)
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._send_security_headers(include_cors=True)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class BudgetWebServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Threaded HTTP Server for Web Deck & REST API."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        host: str,
        port: int,
        breaker: CircuitBreaker,
        storage: BudgetStorage,
        public_dir: str,
        proxy_port: int = 8111,
    ):
        self.breaker = breaker
        self.storage = storage
        self.public_dir = public_dir
        self.proxy_port = proxy_port
        super().__init__((host, port), WebDeckHandler)
