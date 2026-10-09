"""Comprehensive tests for agent-budget-sentinel.

100% Python Standard Library — Zero External Dependencies.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error

from agent_budget_sentinel.breaker import BreakerState, BudgetPolicy, CircuitBreaker
from agent_budget_sentinel.calculator import CostCalculator, MODEL_PRICING
from agent_budget_sentinel.storage import BudgetStorage, TransactionRecord
from agent_budget_sentinel.server import BudgetWebServer
from agent_budget_sentinel.proxy import BudgetProxyServer


class TestCostCalculator(unittest.TestCase):
    def test_pricing_lookup(self):
        pricing_4o = CostCalculator.get_pricing("gpt-4o")
        self.assertEqual(pricing_4o.input_rate, 2.50)
        self.assertEqual(pricing_4o.output_rate, 10.00)

        pricing_sonnet = CostCalculator.get_pricing("claude-3-5-sonnet-20241022")
        self.assertEqual(pricing_sonnet.input_rate, 3.00)
        self.assertEqual(pricing_sonnet.output_rate, 15.00)

        pricing_r1 = CostCalculator.get_pricing("deepseek-reasoner")
        self.assertEqual(pricing_r1.input_rate, 0.55)

        # Fallback default
        pricing_unknown = CostCalculator.get_pricing("unknown-neural-matrix")
        self.assertEqual(pricing_unknown.input_rate, 2.00)

    def test_token_estimation(self):
        text = "Hello world! This is an autonomous agent testing token estimation."
        tokens = CostCalculator.estimate_text_tokens(text)
        self.assertGreater(tokens, 5)
        self.assertLess(tokens, 25)

        # Payload estimation
        payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Write a 5-line poem about space."}
            ]
        }
        prompt_tokens = CostCalculator.estimate_payload_tokens(payload)
        self.assertGreater(prompt_tokens, 10)

    def test_cost_calculation(self):
        # 1M prompt tokens of gpt-4o = $2.50, 1M completion = $10.00
        cost_usd = CostCalculator.calculate_cost_usd("gpt-4o", 1_000_000, 1_000_000)
        self.assertEqual(cost_usd, 12.50)

        # Rich dict
        cost_dict = CostCalculator.calculate_cost_details("gpt-4o", 1_000_000, 1_000_000)
        self.assertEqual(cost_dict["total_cost"], 12.50)

        # 1000 prompt tokens of gpt-4o-mini = (1000 * 0.15) / 1M = $0.00015
        cost_mini = CostCalculator.calculate_cost_usd("gpt-4o-mini", 1000, 1000)
        self.assertEqual(cost_mini, 0.00075)

    def test_extract_actual_usage(self):
        # OpenAI style
        resp_openai = {
            "id": "chatcmpl-123",
            "usage": {
                "prompt_tokens": 150,
                "completion_tokens": 42,
                "total_tokens": 192
            }
        }
        res = CostCalculator.extract_actual_usage(resp_openai)
        self.assertIsNotNone(res)
        self.assertEqual(res, (150, 42))

        # Anthropic style
        resp_anthropic = {
            "id": "msg_123",
            "input_tokens": 200,
            "output_tokens": 80
        }
        res_a = CostCalculator.extract_actual_usage(resp_anthropic)
        self.assertEqual(res_a, (200, 80))


class TestCircuitBreaker(unittest.TestCase):
    def test_breaker_lifecycle(self):
        policy = BudgetPolicy(max_budget_usd=1.00, warn_threshold_pct=0.80)
        breaker = CircuitBreaker(policy)

        self.assertEqual(breaker.state, BreakerState.CLOSED)

        # 1. Allowed request well within budget
        allowed, state, _ = breaker.evaluate_request(estimated_cost=0.10)
        self.assertTrue(allowed)
        self.assertEqual(state, BreakerState.CLOSED)

        # 2. Spend 0.50 -> Still CLOSED
        breaker.record_spend(cost=0.50, prompt_tokens=1000, completion_tokens=200, model_name="gpt-4o")
        self.assertEqual(breaker.state, BreakerState.CLOSED)

        # 3. Spend 0.35 -> Total 0.85 -> Enters WARN (>= 0.80)
        breaker.record_spend(cost=0.35, prompt_tokens=800, completion_tokens=150, model_name="gpt-4o")
        self.assertEqual(breaker.state, BreakerState.WARN)

        # 4. Projected spend exceeds limit of 1.00 (0.85 + 0.20 = 1.05) -> Auto Trips!
        allowed, state, reason = breaker.evaluate_request(estimated_cost=0.20)
        self.assertFalse(allowed)
        self.assertEqual(state, BreakerState.TRIPPED)
        self.assertIn("Cumulative budget breached", reason)

        # 5. Reset restores CLOSED
        breaker.reset(reset_spend=True)
        self.assertEqual(breaker.state, BreakerState.CLOSED)
        self.assertEqual(breaker.total_spend_usd, 0.0)

    def test_manual_trip_and_status(self):
        breaker = CircuitBreaker(BudgetPolicy(max_budget_usd=5.00))
        breaker.trip("Operator manual intervention.")
        self.assertEqual(breaker.state, BreakerState.TRIPPED)
        self.assertEqual(breaker.trip_count, 1)

        status = breaker.get_status()
        self.assertEqual(status["state"], "TRIPPED")
        self.assertEqual(status["trip_reason"], "Operator manual intervention.")

        # Rejects incoming request
        allowed, state, reason = breaker.evaluate_request(0.01)
        self.assertFalse(allowed)
        self.assertEqual(state, BreakerState.TRIPPED)


class TestBudgetStorage(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_budget.db")
        self.storage = BudgetStorage(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_transaction_logging_and_stats(self):
        record = TransactionRecord(
            id=None,
            timestamp="",
            model="claude-3-5-sonnet",
            prompt_tokens=500,
            completion_tokens=100,
            cost_usd=0.003,
            latency_ms=120.5,
            status_code=200,
            path="/v1/messages",
            source_ip="127.0.0.1",
            tripped=False
        )
        tx_id = self.storage.record_transaction(record)
        self.assertGreater(tx_id, 0)

        txs = self.storage.get_recent_transactions(limit=10)
        self.assertEqual(len(txs), 1)
        self.assertEqual(txs[0]["model"], "claude-3-5-sonnet")
        self.assertEqual(txs[0]["cost_usd"], 0.003)

        breakdown = self.storage.get_model_breakdown()
        self.assertEqual(len(breakdown), 1)
        self.assertEqual(breakdown[0]["model"], "claude-3-5-sonnet")


class TestServersIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp_dir.name, "int_test_budget.db")
        cls.storage = BudgetStorage(cls.db_path)
        cls.breaker = CircuitBreaker(BudgetPolicy(max_budget_usd=0.05))

        cls.web_port = 18110
        cls.proxy_port = 18111

        cls.public_dir = os.path.join(cls.tmp_dir.name, "public")
        os.makedirs(cls.public_dir, exist_ok=True)
        with open(os.path.join(cls.public_dir, "index.html"), "w") as f:
            f.write("<html><body>Budget Sentinel Mock UI</body></html>")

        cls.web_server = BudgetWebServer(
            host="127.0.0.1",
            port=cls.web_port,
            breaker=cls.breaker,
            storage=cls.storage,
            public_dir=cls.public_dir,
            proxy_port=cls.proxy_port
        )
        cls.proxy_server = BudgetProxyServer(
            host="127.0.0.1",
            port=cls.proxy_port,
            breaker=cls.breaker,
            storage=cls.storage
        )

        cls.t_web = threading.Thread(target=cls.web_server.serve_forever, daemon=True)
        cls.t_proxy = threading.Thread(target=cls.proxy_server.serve_forever, daemon=True)
        cls.t_web.start()
        cls.t_proxy.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.web_server.shutdown()
        cls.web_server.server_close()
        cls.proxy_server.shutdown()
        cls.proxy_server.server_close()
        cls.tmp_dir.cleanup()

    def setUp(self):
        self.breaker.reset(reset_spend=True)

    def test_web_health_and_stats(self):
        url = f"http://127.0.0.1:{self.web_port}/health"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["service"], "agent-budget-sentinel")

        url_stats = f"http://127.0.0.1:{self.web_port}/api/stats"
        with urllib.request.urlopen(urllib.request.Request(url_stats), timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["state"], "CLOSED")
            self.assertEqual(data["max_budget_usd"], 0.05)

    def test_simulation_and_auto_trip(self):
        # Simulate request that costs $0.04
        url_sim = f"http://127.0.0.1:{self.web_port}/api/simulate"
        body = json.dumps({
            "model": "gpt-4o",
            "prompt_tokens": 10000,
            "completion_tokens": 1500
        }).encode("utf-8")
        req = urllib.request.Request(url_sim, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["allowed"])

        # Second simulation breaches ceiling of $0.05 -> should return 429
        body2 = json.dumps({
            "model": "gpt-4o",
            "prompt_tokens": 15000,
            "completion_tokens": 2000
        }).encode("utf-8")
        req2 = urllib.request.Request(url_sim, data=body2, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req2, timeout=3.0) as resp:
                self.fail("Expected HTTP 429 on budget breach")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 429)
            err_data = json.loads(e.read().decode("utf-8"))
            self.assertFalse(err_data["allowed"])
            self.assertEqual(err_data["state"], "TRIPPED")

        # Now test that proxy on port 18111 also immediately returns 429
        proxy_url = f"http://127.0.0.1:{self.proxy_port}/v1/chat/completions"
        proxy_body = json.dumps({
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Runaway iteration"}]
        }).encode("utf-8")
        req_proxy = urllib.request.Request(proxy_url, data=proxy_body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req_proxy, timeout=3.0) as resp:
                self.fail("Expected HTTP 429 from tripped proxy")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 429)
            self.assertEqual(e.headers.get("X-Budget-State"), "TRIPPED")
            body_json = json.loads(e.read().decode("utf-8"))
            self.assertEqual(body_json["error"]["code"], "budget_circuit_tripped")


if __name__ == "__main__":
    unittest.main()
