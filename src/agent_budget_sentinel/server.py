"""Web Cockpit and Telemetry REST API Server.

100% Python Standard Library — Zero External Dependencies.
"""

from __future__ import annotations

import http.server
import json
import mimetypes
import os
import queue
import socketserver
import time
import urllib.parse
from typing import Any, Dict, Optional

from .breaker import BreakerState, CircuitBreaker
from .calculator import MODEL_PRICING, CostCalculator
from .storage import BudgetStorage, TransactionRecord


def _is_local_origin(origin) -> bool:
    """Browser Origin check. No Origin header = non-browser client (CLI/agent): allowed.
    Otherwise only http(s)://localhost / 127.0.0.1 / [::1] pages may call this API, so a
    random website can't drive the local server from the user's browser (CSRF)."""
    if not origin:
        return True
    from urllib.parse import urlparse
    try:
        u = urlparse(origin)
    except ValueError:
        return False
    return u.scheme in ("http", "https") and u.hostname in ("localhost", "127.0.0.1", "::1")


def _cors_origin(handler) -> str:
    origin = handler.headers.get("Origin")
    return origin if origin and _is_local_origin(origin) else "http://127.0.0.1"



class WebDeckHandler(http.server.BaseHTTPRequestHandler):
    """Serves the avant-garde Web Deck and telemetry API."""

    server: BudgetWebServer

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", _cors_origin(self))
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # 1. Health check
        if path == "/health":
            self._send_json({
                "status": "ok",
                "service": "agent-budget-sentinel",
                "version": "1.0.0",
                "web_port": self.server.server_port,
                "proxy_port": self.server.proxy_port,
                "breaker_state": self.server.breaker.state.value
            })
            return

        # 2. Stats endpoint
        if path == "/api/stats":
            stats = self.server.breaker.get_status()
            stats["models"] = self.server.storage.get_model_breakdown()
            stats["hourly"] = self.server.storage.get_hourly_spend(24)
            self._send_json(stats)
            return

        # 3. Transactions endpoint
        if path == "/api/transactions":
            query = urllib.parse.parse_qs(parsed.query)
            limit = int(query.get("limit", [50])[0])
            txs = self.server.storage.get_recent_transactions(limit=limit)
            self._send_json({"transactions": txs, "count": len(txs)})
            return

        # 4. Model Pricing Directory
        if path == "/api/pricing":
            pricing_data = {
                k: {
                    "model_id": v.model_id,
                    "input_rate": v.input_rate,
                    "output_rate": v.output_rate,
                    "family": v.family
                }
                for k, v in MODEL_PRICING.items()
            }
            self._send_json({"pricing": pricing_data})
            return

        # 5. SSE Live Stream
        if path in ("/api/stream", "/api/events"):
            self._handle_sse()
            return

        # 6. Static files
        self._serve_static(path)

    def do_POST(self) -> None:
        if not _is_local_origin(self.headers.get("Origin")):
            _body = b'{"error": "cross-origin request blocked"}'
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(_body)))
            self.end_headers()
            self.wfile.write(_body)
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""
        payload = {}
        if body_bytes:
            try:
                payload = json.loads(body_bytes.decode("utf-8", errors="replace"))
            except Exception:
                payload = {}

        # 1. Set budget
        if path == "/api/budget":
            if "max_budget_usd" in payload:
                new_budget = float(payload["max_budget_usd"])
                self.server.breaker.set_budget(new_budget)
                self.server.storage.record_event(
                    "config_change",
                    f"Budget ceiling updated to ${new_budget:.2f}",
                    {"max_budget_usd": new_budget}
                )
            if "velocity_limit" in payload:
                new_vel = float(payload["velocity_limit"])
                self.server.breaker.policy.velocity_limit_usd_per_min = new_vel
            self._send_json({"status": "updated", "breaker": self.server.breaker.get_status()})
            return

        # 2. Trip breaker (kill switch)
        if path == "/api/trip":
            reason = payload.get("reason", "Operator emergency kill switch engaged.")
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
                self.server.breaker.get_status()
            )
            self._send_json({"status": "reset", "breaker": self.server.breaker.get_status()})
            return

        # 4. Simulation endpoint (Interactive Test Tool)
        if path == "/api/simulate":
            model = payload.get("model", "gpt-4o")
            prompt_tokens = int(payload.get("prompt_tokens", 1200))
            completion_tokens = int(payload.get("completion_tokens", 450))
            
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
                    reason=reason
                )
                self.server.storage.record_transaction(rec)
                self._send_json({
                    "allowed": False,
                    "status_code": 429,
                    "state": state.value,
                    "reason": reason,
                    "breaker": self.server.breaker.get_status()
                }, status=429)
                return

            # Allowed - record spend
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
                reason=None
            )
            self.server.storage.record_transaction(rec)
            self._send_json({
                "allowed": True,
                "status_code": 200,
                "cost_usd": projected_cost,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "state": self.server.breaker.state.value,
                "breaker": self.server.breaker.get_status()
            })
            return

        # 5. Runaway loop burst simulation (Trips breaker)
        if path == "/api/simulate_runaway":
            iterations = min(50, int(payload.get("iterations", 15)))
            model = payload.get("model", "o1-preview")
            results = []
            tripped_at_iter = None
            
            for i in range(iterations):
                p_cost = CostCalculator.calculate_cost(model, 3000, 1000)
                allowed, state, reason = self.server.breaker.evaluate_request(p_cost)
                if not allowed:
                    tripped_at_iter = i + 1
                    rec = TransactionRecord(
                        id=None, timestamp="", model=model, prompt_tokens=3000,
                        completion_tokens=0, cost_usd=0.0, latency_ms=1.1,
                        status_code=429, path="/v1/chat/completions (burst)",
                        source_ip="127.0.0.1", tripped=True, reason=reason
                    )
                    self.server.storage.record_transaction(rec)
                    results.append({"iteration": i + 1, "allowed": False, "status": 429, "reason": reason})
                    break
                
                self.server.breaker.record_spend(p_cost, 3000, 1000, model)
                rec = TransactionRecord(
                    id=None, timestamp="", model=model, prompt_tokens=3000,
                    completion_tokens=1000, cost_usd=p_cost, latency_ms=25.0,
                    status_code=200, path="/v1/chat/completions (burst)",
                    source_ip="127.0.0.1", tripped=False
                )
                self.server.storage.record_transaction(rec)
                results.append({"iteration": i + 1, "allowed": True, "cost_usd": p_cost})

            self._send_json({
                "status": "complete",
                "tripped_at_iteration": tripped_at_iter,
                "iterations_run": len(results),
                "breaker": self.server.breaker.get_status()
            })
            return

        self._send_json({"error": "Endpoint not found"}, status=404)

    def _handle_sse(self) -> None:
        """Stream real-time spending events to dashboard."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", _cors_origin(self))
        self.end_headers()

        q = self.server.storage.subscribe_sse()
        # Send initial status
        init_event = f"event: init\ndata: {json.dumps(self.server.breaker.get_status())}\n\n"
        try:
            self.wfile.write(init_event.encode("utf-8"))
            self.wfile.flush()
            
            while True:
                try:
                    # Non-busy wait with 10s heartbeat
                    msg = q.get(timeout=10.0)
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    # Heartbeat comment to keep connection alive
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.server.storage.unsubscribe_sse(q)

    def _serve_static(self, path: str) -> None:
        """Serve public static directory assets."""
        clean_path = path.lstrip("/")
        if not clean_path or clean_path == "":
            clean_path = "index.html"

        file_path = os.path.join(self.server.public_dir, clean_path)
        if not os.path.exists(file_path) or os.path.isdir(file_path):
            file_path = os.path.join(self.server.public_dir, "index.html")

        if not os.path.exists(file_path):
            self.send_response(404)
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
            self.send_header("Access-Control-Allow-Origin", _cors_origin(self))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", _cors_origin(self))
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
        proxy_port: int = 8111
    ):
        self.breaker = breaker
        self.storage = storage
        self.public_dir = public_dir
        self.proxy_port = proxy_port
        super().__init__((host, port), WebDeckHandler)
