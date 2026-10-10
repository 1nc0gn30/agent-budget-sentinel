"""Unit and integration tests for Pure-Python BPE Tokenizer and Mid-Flight SSE Guillotine.

100% Python Standard Library — Zero External Dependencies.
"""

from __future__ import annotations

import http.server
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from agent_budget_sentinel.bpe_tokenizer import BPETokenizer, count_tokens, estimate_payload_tokens, get_vocabulary
from agent_budget_sentinel.breaker import BreakerState, BudgetPolicy, CircuitBreaker
from agent_budget_sentinel.calculator import CostCalculator
from agent_budget_sentinel.storage import BudgetStorage
from agent_budget_sentinel.proxy import BudgetProxyServer


class TestBPETokenizer(unittest.TestCase):
    """Test suite for Pure-Python Zero-Dependency Minimal BPE Tokenizer."""

    def test_vocabulary_loaded(self):
        vocab = get_vocabulary()
        self.assertIsInstance(vocab, set)
        self.assertGreaterEqual(len(vocab), 100000)

    def test_tokenizer_class_interface(self):
        tokenizer = BPETokenizer()
        self.assertIsNotNone(tokenizer.vocabulary)
        self.assertEqual(tokenizer.count_tokens("Hello world"), 2)

    def test_exact_known_token_counts(self):
        # Known ground-truth token counts in cl100k_base
        samples = [
            ("Hello world!", 3),
            ("The quick brown fox jumps over the lazy dog.", 10),
            ("1234567890", 4),
            ("def foo(x):\n    return x * 2\n", 11),
            ("", 0),
        ]
        for text, expected in samples:
            tokens = count_tokens(text)
            self.assertEqual(
                tokens,
                expected,
                f"Token count mismatch for {text!r}: expected {expected}, got {tokens}",
            )

    def test_sub_millisecond_execution(self):
        sample = (
            "You are an autonomous AI coding assistant running on a sovereign platform. "
            "Please analyze the cost calculations, verify BPE token boundaries, "
            "and ensure zero runaway expenditure loops."
        )
        # Warmup
        count_tokens(sample)

        # Benchmark 100 iterations
        t0 = time.perf_counter()
        iterations = 100
        for _ in range(iterations):
            count_tokens(sample)
        elapsed_total_ms = (time.perf_counter() - t0) * 1000.0
        avg_ms = elapsed_total_ms / iterations

        self.assertLess(
            avg_ms,
            1.0,
            f"Execution time {avg_ms:.4f} ms exceeds sub-millisecond requirement (< 1.0 ms)",
        )

    def test_accuracy_against_official_tiktoken(self):
        """Verify >= 98% accuracy against official tiktoken tokenizer."""
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            self.skipTest("tiktoken not installed in current test environment")

        corpus = [
            "Hello world! This is an autonomous agent testing token estimation.",
            "def calculate_cost(model_name: str, prompt_tokens: int, completion_tokens: int = 0) -> CostResult:\n    pricing = cls.get_pricing(model_name)\n    return round(in_cost, 6)",
            "The quick brown fox jumps over the lazy dog. 1234567890 !@#$%^&*()",
            'JSON payload: {"model": "gpt-4o", "messages": [{"role": "user", "content": "Explain quantum computing."}]}',
            "System prompt: You are Vulcan-Core, the Senior Systems Kernel Engineer for Neal Frazier Tech.",
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.",
            'SELECT u.id, u.name, COUNT(o.id) FROM users u LEFT JOIN orders o ON u.id = o.user_id WHERE u.created_at >= "2024-01-01" GROUP BY u.id;',
            'curl -X POST https://api.openai.com/v1/chat/completions -H "Authorization: Bearer sk-123" -H "Content-Type: application/json"',
            "Short text",
            "Résumé, naïve, façade, café, über, señor",
            "1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20",
            "Multi-line\n\n    Indented 4 spaces\n        Indented 8 spaces\n\tTab\n",
            "你好世界！这是一个关于人工智能代理的测试。",
            "🚀 ⭐ 🤖 🔥 💡 💻 🛡️ ⚡ 💰 📊",
        ]

        total_official = 0
        total_our = 0
        for text in corpus:
            c_official = len(enc.encode(text))
            c_our = count_tokens(text)
            total_official += c_official
            total_our += c_our

        accuracy = (1.0 - (abs(total_official - total_our) / total_official)) * 100.0
        self.assertGreaterEqual(
            accuracy,
            98.0,
            f"Overall BPE accuracy {accuracy:.2f}% is below 98.0% requirement (official: {total_official}, our: {total_our})",
        )

    def test_cost_calculator_integration(self):
        text = "Hello world! This is an autonomous agent testing token estimation."
        calc_tokens = CostCalculator.estimate_text_tokens(text)
        direct_tokens = count_tokens(text)
        self.assertEqual(calc_tokens, direct_tokens)
        self.assertEqual(calc_tokens, 12)

        # Payload estimation with BPE
        payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Write a 5-line poem about space."}
            ]
        }
        tokens = CostCalculator.estimate_payload_tokens(payload)
        self.assertGreaterEqual(tokens, 20)
        self.assertLessEqual(tokens, 35)

    def test_standard_library_compliance(self):
        """Ensure bpe_tokenizer uses zero non-stdlib packages."""
        import agent_budget_sentinel.bpe_tokenizer as mod
        allowed_modules = {
            "base64", "json", "lzma", "os", "re", "threading", "typing", "__future__",
            "agent_budget_sentinel", "_frozen_importlib", "_frozen_importlib_external",
            "_thread",
        }
        for name in dir(mod):
            obj = getattr(mod, name)
            if hasattr(obj, "__module__") and obj.__module__:
                top_module = obj.__module__.split(".")[0]
                if top_module not in sys.builtin_module_names and top_module not in allowed_modules:
                    self.fail(f"Non-standard library dependency detected: {top_module}")


class MockStreamingLLM(http.server.BaseHTTPRequestHandler):
    """Mock LLM server streaming SSE chunks."""

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        # Read body to prevent broken pipe
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len > 0 else b""
        payload = {}
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            pass

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()

        # Send chunks
        words = ["Token0", " Token1", " Token2", " Token3", " Token4", " Token5", " Token6", " Token7", " Token8", " Token9"]
        for w in words:
            chunk = {
                "id": "chatcmpl-mock",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"content": w}, "finish_reason": None}]
            }
            msg = f"data: {json.dumps(chunk)}\n\n"
            try:
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            time.sleep(0.01)

        try:
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True


class MockAnthropicStreamingLLM(http.server.BaseHTTPRequestHandler):
    """Mock LLM streaming Anthropic format SSE chunks."""

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len > 0:
            self.rfile.read(content_len)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()

        words = ["Word0", " Word1", " Word2", " Word3", " Word4", " Word5"]
        for w in words:
            chunk = {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": w}
            }
            msg = f"data: {json.dumps(chunk)}\n\n"
            try:
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            time.sleep(0.01)

        try:
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True


class TestStreamingGuillotine(unittest.TestCase):
    """Integration test suite for Mid-Flight Streaming SSE Guillotine."""

    @classmethod
    def setUpClass(cls):
        cls.mock_port = 19181
        cls.proxy_port = 19182
        cls.anthropic_mock_port = 19183

        cls.mock_server = http.server.HTTPServer(("127.0.0.1", cls.mock_port), MockStreamingLLM)
        cls.anthropic_mock_server = http.server.HTTPServer(("127.0.0.1", cls.anthropic_mock_port), MockAnthropicStreamingLLM)

        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.storage = BudgetStorage(os.path.join(cls.tmp_dir.name, "stream_test.db"))
        cls.breaker = CircuitBreaker(BudgetPolicy(max_budget_usd=10.00))

        cls.proxy_server = BudgetProxyServer(
            host="127.0.0.1",
            port=cls.proxy_port,
            breaker=cls.breaker,
            storage=cls.storage,
            upstream_base=f"http://127.0.0.1:{cls.mock_port}"
        )

        cls.t_mock = threading.Thread(target=cls.mock_server.serve_forever, daemon=True)
        cls.t_anthropic = threading.Thread(target=cls.anthropic_mock_server.serve_forever, daemon=True)
        cls.t_proxy = threading.Thread(target=cls.proxy_server.serve_forever, daemon=True)

        cls.t_mock.start()
        cls.t_anthropic.start()
        cls.t_proxy.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proxy_server.shutdown()
        cls.proxy_server.server_close()
        cls.mock_server.shutdown()
        cls.mock_server.server_close()
        cls.anthropic_mock_server.shutdown()
        cls.anthropic_mock_server.server_close()
        cls.tmp_dir.cleanup()

    def setUp(self):
        self.breaker.set_budget(10.00)
        self.breaker.reset(reset_spend=True)

    def test_streaming_normal_completion(self):
        """Stream within budget completes fully and keeps circuit CLOSED."""
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.proxy_port}/v1/chat/completions",
            data=json.dumps({
                "model": "gpt-4o",
                "stream": True,
                "messages": [{"role": "user", "content": "hello"}]
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        lines = []
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/event-stream", resp.headers.get("Content-Type", ""))
            while True:
                line = resp.readline()
                if not line:
                    break
                lines.append(line.decode("utf-8"))

        # Verify all 10 tokens and [DONE] received
        all_text = "".join(lines)
        self.assertIn("Token0", all_text)
        self.assertIn("Token9", all_text)
        self.assertIn("[DONE]", all_text)
        self.assertNotIn("circuit_breaker_trip", all_text)
        self.assertEqual(self.breaker.state, BreakerState.CLOSED)
        self.assertGreater(self.breaker.total_spend_usd, 0.0)

    def test_streaming_guillotine_on_query_token_budget(self):
        """Mid-flight query token budget breach drops guillotine and emits terminal SSE event."""
        # Set query token budget to 3 tokens
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.proxy_port}/v1/chat/completions",
            data=json.dumps({
                "model": "gpt-4o",
                "stream": True,
                "query_token_budget": 3,
                "messages": [{"role": "user", "content": "test"}]
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        lines = []
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            while True:
                line = resp.readline()
                if not line:
                    break
                lines.append(line.decode("utf-8"))

        full_stream = "".join(lines)
        # Verify initial chunks received before guillotine
        self.assertIn("Token0", full_stream)
        # Verify later tokens were NOT received (severed)
        self.assertNotIn("Token8", full_stream)
        self.assertNotIn("Token9", full_stream)
        self.assertNotIn("[DONE]", full_stream)

        # Verify terminal SSE event exactly matches specification:
        # event: circuit_breaker_trip
        # data: {"error": "Budget limit exceeded mid-stream. Circuit breaker tripped."}
        self.assertIn("event: circuit_breaker_trip", full_stream)
        self.assertIn(
            'data: {"error": "Budget limit exceeded mid-stream. Circuit breaker tripped."}',
            full_stream,
        )

        # Verify breaker state transitioned to TRIPPED
        self.assertEqual(self.breaker.state, BreakerState.TRIPPED)
        self.assertEqual(self.breaker.trip_count, 1)

        # Verify subsequent request is immediately blocked with HTTP 429
        req_blocked = urllib.request.Request(
            f"http://127.0.0.1:{self.proxy_port}/v1/chat/completions",
            data=json.dumps({"model": "gpt-4o", "messages": [{"role": "user", "content": "next"}]}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req_blocked, timeout=3.0) as r:
                self.fail("Expected HTTP 429 on subsequent call after tripped circuit")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 429)
            self.assertEqual(e.headers.get("X-Budget-State"), "TRIPPED")

    def test_streaming_guillotine_on_cumulative_cost(self):
        """Cumulative dollar budget ceiling breach drops mid-stream guillotine."""
        # Set max budget to $0.000030 (low threshold breached after ~3 tokens of gpt-4o)
        self.breaker.set_budget(0.000030)
        self.breaker.reset(reset_spend=True)

        req = urllib.request.Request(
            f"http://127.0.0.1:{self.proxy_port}/v1/chat/completions",
            data=json.dumps({
                "model": "gpt-4o",
                "stream": True,
                "messages": [{"role": "user", "content": "trigger ceiling"}]
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        lines = []
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            while True:
                line = resp.readline()
                if not line:
                    break
                lines.append(line.decode("utf-8"))

        full_stream = "".join(lines)
        self.assertIn("event: circuit_breaker_trip", full_stream)
        self.assertIn(
            'data: {"error": "Budget limit exceeded mid-stream. Circuit breaker tripped."}',
            full_stream,
        )
        self.assertEqual(self.breaker.state, BreakerState.TRIPPED)

    def test_streaming_anthropic_format(self):
        """Verify mid-flight streaming guillotine handles Anthropic format SSE."""
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.proxy_port}/v1/messages",
            data=json.dumps({
                "model": "claude-3-5-sonnet",
                "stream": True,
                "query_token_budget": 2,
                "messages": [{"role": "user", "content": "hello"}]
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Target-Url": f"http://127.0.0.1:{self.anthropic_mock_port}"
            }
        )

        lines = []
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            while True:
                line = resp.readline()
                if not line:
                    break
                lines.append(line.decode("utf-8"))

        full_stream = "".join(lines)
        self.assertIn("Word0", full_stream)
        self.assertNotIn("Word5", full_stream)
        self.assertIn("event: circuit_breaker_trip", full_stream)
        self.assertEqual(self.breaker.state, BreakerState.TRIPPED)


if __name__ == "__main__":
    unittest.main()
