"""Security, API contract, SSRF, CORS, hydration, CLI, and MCP tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from agent_budget_sentinel import VERSION
from agent_budget_sentinel.breaker import BreakerState, BudgetPolicy, CircuitBreaker
from agent_budget_sentinel.calculator import CostCalculator
from agent_budget_sentinel.mcp_server import handle_jsonrpc_message
from agent_budget_sentinel.net_guard import is_local_origin, validate_upstream_url
from agent_budget_sentinel.proxy import BudgetProxyServer
from agent_budget_sentinel.server import BudgetWebServer
from agent_budget_sentinel.storage import BudgetStorage, TransactionRecord


class TestSecurityAndContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp_dir.name, "sec_budget.db")
        cls.storage = BudgetStorage(cls.db_path)
        cls.breaker = CircuitBreaker(BudgetPolicy(max_budget_usd=5.00))

        cls.public_dir = os.path.join(cls.tmp_dir.name, "public")
        os.makedirs(cls.public_dir, exist_ok=True)
        with open(os.path.join(cls.public_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write("<html><body>Sentinel Test</body></html>")

        cls.web_server = BudgetWebServer(
            host="127.0.0.1",
            port=0,
            breaker=cls.breaker,
            storage=cls.storage,
            public_dir=cls.public_dir,
            proxy_port=0,
        )
        cls.web_port = cls.web_server.server_address[1]

        cls.proxy_server = BudgetProxyServer(
            host="127.0.0.1",
            port=0,
            breaker=cls.breaker,
            storage=cls.storage,
        )
        cls.proxy_port = cls.proxy_server.server_address[1]
        cls.web_server.proxy_port = cls.proxy_port

        cls.t_web = threading.Thread(target=cls.web_server.serve_forever, daemon=True)
        cls.t_proxy = threading.Thread(target=cls.proxy_server.serve_forever, daemon=True)
        cls.t_web.start()
        cls.t_proxy.start()
        time.sleep(0.15)

    @classmethod
    def tearDownClass(cls):
        cls.web_server.shutdown()
        cls.web_server.server_close()
        cls.proxy_server.shutdown()
        cls.proxy_server.server_close()
        cls.tmp_dir.cleanup()

    def setUp(self):
        self.breaker.set_budget(5.00)
        self.breaker.reset(reset_spend=True)

    # --- Origin / CORS Guard ---
    def test_origin_guard_blocks_hostname_spoofing(self):
        for bad in (
            "http://127.0.0.1:8110.evil.com",
            "http://127.0.0.1:8111.evil.com",
            "http://localhost:3000.evil.com",
            "http://127.0.0.1@evil.com",
            "https://evil.example.com",
            "null",
            "file:///etc/passwd",
        ):
            self.assertFalse(is_local_origin(bad), bad)

        for good in (
            None,
            "",
            "http://127.0.0.1:8110",
            "http://127.0.0.1:3000",
            "http://localhost:3000",
            "http://[::1]:8110",
        ):
            self.assertTrue(is_local_origin(good), str(good))

    def test_web_and_proxy_reject_spoofed_cors_with_403(self):
        spoofed_web = f"http://127.0.0.1:{self.web_port}.evil.com"
        spoofed_proxy = f"http://127.0.0.1:{self.proxy_port}.evil.com"

        for url, method, origin in (
            (f"http://127.0.0.1:{self.web_port}/api/stats", "GET", spoofed_web),
            (f"http://127.0.0.1:{self.web_port}/api/stats", "OPTIONS", spoofed_web),
            (f"http://127.0.0.1:{self.web_port}/api/stats", "OPTIONS", "https://evil.example.com"),
            (f"http://127.0.0.1:{self.web_port}/api/stream", "GET", "https://evil.example.com"),
            (f"http://127.0.0.1:{self.proxy_port}/health", "GET", spoofed_proxy),
            (f"http://127.0.0.1:{self.proxy_port}/health", "OPTIONS", spoofed_proxy),
        ):
            req = urllib.request.Request(url, method=method, headers={"Origin": origin})
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=3.0)
            self.assertEqual(ctx.exception.code, 403, f"Expected 403 for {method} {url} ({origin})")
            self.assertIsNone(ctx.exception.headers.get("Access-Control-Allow-Origin"))

        # Allowed OPTIONS returns 204 with matching Origin + Vary: Origin
        req_ok = urllib.request.Request(
            f"http://127.0.0.1:{self.web_port}/api/stats",
            method="OPTIONS",
            headers={"Origin": "http://127.0.0.1:3000"},
        )
        with urllib.request.urlopen(req_ok, timeout=3.0) as resp:
            self.assertEqual(resp.status, 204)
            self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "http://127.0.0.1:3000")
            self.assertEqual(resp.headers.get("Vary"), "Origin")
            self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")

    # --- Proxy SSRF & Breaker on GET ---
    def test_proxy_ssrf_blocks_loopback_private_imds_and_file(self):
        for target in (
            f"http://127.0.0.1:{self.web_port}",
            "http://169.254.169.254",
            "http://10.0.0.1",
            "file:///etc",
            "ftp://example.com",
        ):
            ok, _reason = validate_upstream_url(target + "/passwd")
            self.assertFalse(ok, f"net_guard should block {target}")

            req = urllib.request.Request(
                f"http://127.0.0.1:{self.proxy_port}/passwd",
                method="GET",
                headers={"X-Target-Url": target},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=3.0)
            self.assertEqual(ctx.exception.code, 403, f"Proxy GET should return 403 for {target}")

    def test_proxy_do_get_enforces_tripped_breaker(self):
        self.breaker.trip("Unit test trip")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.proxy_port}/v1/models",
            method="GET",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=3.0)
        self.assertEqual(ctx.exception.code, 429)
        self.assertEqual(ctx.exception.headers.get("X-Budget-State"), "TRIPPED")

    # --- API Input Validation & /api/health ---
    def test_api_health_and_unknown_api_404_json(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.web_port}/api/health", timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["version"], VERSION)

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"http://127.0.0.1:{self.web_port}/api/nonexistent_xyz", timeout=3.0)
        self.assertEqual(ctx.exception.code, 404)
        err = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("error", err)

    def test_transactions_limit_validation(self):
        for bad_q in ("limit=abc", "limit=-1", "limit=0"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.web_port}/api/transactions?{bad_q}", timeout=3.0)
            self.assertEqual(ctx.exception.code, 400, bad_q)

    def test_budget_validation_rejects_negative_nan_zero(self):
        for payload in (
            {"max_budget_usd": -5},
            {"max_budget_usd": 0},
            {"max_budget_usd": "NaN"},
            {"max_budget_usd": "Infinity"},
            {"max_budget_usd": True},
        ):
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.web_port}/api/budget",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=3.0)
            self.assertEqual(ctx.exception.code, 400, str(payload))

    # --- SQLite Restart Hydration & 2025/2026 + Local Pricing ---
    def test_sqlite_hydration_and_pricing_catalog(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "hydrate.db")
            st = BudgetStorage(db)
            st.set_setting("max_budget_usd", "12.50")
            st.record_transaction(TransactionRecord(
                id=None, timestamp="", model="gpt-4.1", prompt_tokens=1000, completion_tokens=500,
                cost_usd=0.25, latency_ms=10.0, status_code=200, path="/v1/chat/completions",
                source_ip="127.0.0.1", tripped=False,
            ))
            fresh_breaker = CircuitBreaker(BudgetPolicy(max_budget_usd=5.0))
            fresh_breaker.hydrate_from_storage(st)
            self.assertEqual(fresh_breaker.policy.max_budget_usd, 12.50)
            self.assertAlmostEqual(fresh_breaker.total_spend_usd, 0.25, places=6)
            self.assertEqual(fresh_breaker.total_requests, 1)
            self.assertEqual(fresh_breaker.total_prompt_tokens, 1000)

        # 2025/2026 & local $0.00 models
        self.assertEqual(CostCalculator.calculate_cost_usd("ollama/qwen2.5-coder", 50_000, 10_000), 0.0)
        self.assertEqual(CostCalculator.calculate_cost_usd("agy/local", 25_000, 5_000), 0.0)
        self.assertEqual(CostCalculator.calculate_cost_usd("hermes/local", 10_000, 2_000), 0.0)
        self.assertGreater(CostCalculator.calculate_cost_usd("gpt-5", 10_000, 2_000), 0.0)
        self.assertGreater(CostCalculator.calculate_cost_usd("claude-sonnet-4", 10_000, 2_000), 0.0)
        self.assertGreater(CostCalculator.calculate_cost_usd("gemini-3.8-flash", 10_000, 2_000), 0.0)

    # --- CLI run --max-budget -- cmd & Stdio MCP ---
    def test_cli_run_strips_double_dash_and_sets_base_urls(self):
        env = os.environ.copy()
        src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
        env["PYTHONPATH"] = src_dir
        res = subprocess.run(
            [
                sys.executable, "-m", "agent_budget_sentinel.cli",
                "run", "--max-budget", "2.50", "--port", str(self.web_port),
                "--proxy-port", str(self.proxy_port), "--",
                sys.executable, "-c",
                "import os; print(os.environ.get('OPENAI_BASE_URL',''), os.environ.get('HTTPS_PROXY','NONE'))",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"http://127.0.0.1:{self.proxy_port}/v1", res.stdout)
        self.assertIn("NONE", res.stdout)
        self.assertAlmostEqual(self.breaker.policy.max_budget_usd, 2.50, places=2)

    def test_mcp_stdio_tools_list_and_status(self):
        init_resp = handle_jsonrpc_message(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            port=self.web_port,
        )
        self.assertEqual(init_resp["result"]["serverInfo"]["version"], VERSION)

        list_resp = handle_jsonrpc_message(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            port=self.web_port,
        )
        names = [t["name"] for t in list_resp["result"]["tools"]]
        self.assertIn("budget_circuit_breaker_status", names)
        self.assertIn("budget_estimate_cost", names)

        status_resp = handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "budget_circuit_breaker_status", "arguments": {"action": "status"}},
            },
            port=self.web_port,
        )
        self.assertFalse(status_resp["result"]["isError"])
        sc = status_resp["result"]["structuredContent"]
        self.assertTrue(sc["online"])
        self.assertEqual(sc["state"], "CLOSED")


if __name__ == "__main__":
    unittest.main()
