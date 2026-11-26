"""Zero-Dependency Stdio JSON-RPC 2.0 MCP Server for Agent Budget Sentinel.

Exposes live circuit-breaker inspection, guardrail controls, and local BPE cost estimation
to AI agents (Claude Code, Codex, AGY, Hermes) over Model Context Protocol (stdio).

100% Python Standard Library — Zero External Dependencies.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .calculator import CostCalculator
from .storage import BudgetStorage

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_VERSION = "2.6.0"

MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "budget_circuit_breaker_status",
        "description": (
            "Inspect live spending, remaining budget ceiling, velocity, and circuit breaker state "
            "(CLOSED | WARN | TRIPPED). Optionally performs trip, reset, or set-budget actions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "trip", "reset", "set-budget"],
                    "default": "status",
                    "description": "Circuit breaker operation to execute.",
                },
                "amount": {
                    "type": "number",
                    "description": "New hard budget ceiling in USD (used when action='set-budget').",
                },
                "reason": {
                    "type": "string",
                    "description": "Trip reason (used when action='trip').",
                },
                "clear": {
                    "type": "boolean",
                    "default": False,
                    "description": "Purge spend ledger when action='reset'.",
                },
            },
        },
    },
    {
        "name": "budget_set_ceiling",
        "description": "Update the live hard USD budget ceiling and optional per-minute velocity guardrail.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_budget_usd": {
                    "type": "number",
                    "description": "Hard spending cap in USD (> 0).",
                },
                "velocity_limit_usd_per_min": {
                    "type": "number",
                    "description": "Optional per-minute spend velocity cap in USD/min (>= 0).",
                },
            },
            "required": ["max_budget_usd"],
        },
    },
    {
        "name": "budget_trip",
        "description": "Engage the emergency circuit breaker kill switch immediately (HTTP 429 on :8111).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Human-readable reason for halting outbound LLM traffic.",
                }
            },
        },
    },
    {
        "name": "budget_reset",
        "description": "Reset the circuit breaker back to CLOSED state (optionally clearing historical spend).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reset_spend": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, resets cumulative spend and clears SQLite transaction history.",
                }
            },
        },
    },
    {
        "name": "budget_estimate_cost",
        "description": "Estimate BPE token count and exact USD cost for a model locally with zero network egress.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "default": "gpt-4o",
                    "description": "Model identifier (e.g., gpt-4.1, claude-sonnet-4, gemini-3.8-flash, ollama/qwen2.5-coder).",
                },
                "text": {
                    "type": "string",
                    "description": "Optional prompt text to count via pure-Python cl100k_base BPE tokenizer.",
                },
                "prompt_tokens": {
                    "type": "integer",
                    "description": "Explicit prompt token count (overrides text BPE count if provided).",
                },
                "completion_tokens": {
                    "type": "integer",
                    "default": 400,
                    "description": "Expected completion token count.",
                },
            },
        },
    },
]


def _http_json(
    host: str,
    port: int,
    path: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = f"http://{host}:{port}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _offline_db_status(db_path: Optional[str]) -> Dict[str, Any]:
    if db_path and os.path.exists(db_path):
        st = BudgetStorage(db_path)
        agg = st.get_aggregate_summary()
        saved_max = st.get_setting("max_budget_usd")
        max_b = float(saved_max) if saved_max is not None else 5.0
        spend = float(agg["total_spend_usd"])
        return {
            "online": False,
            "source": "sqlite_fallback",
            "state": "OFFLINE",
            "current_spend_usd": spend,
            "max_budget_usd": max_b,
            "remaining_budget_usd": max(0.0, round(max_b - spend, 6)),
            "total_requests": agg["total_requests"],
            "blocked_requests": agg["blocked_requests"],
            "total_tokens": agg["total_prompt_tokens"] + agg["total_completion_tokens"],
        }
    return {
        "online": False,
        "source": "none",
        "state": "OFFLINE",
        "error": "Daemon unreachable on local port and no SQLite ledger found.",
    }


def dispatch_tool_call(
    name: str,
    arguments: Optional[Dict[str, Any]],
    *,
    host: str = "127.0.0.1",
    port: int = 8110,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a single MCP tool call and return structured JSON payload."""
    args = arguments if isinstance(arguments, dict) else {}

    if name == "budget_estimate_cost":
        model = str(args.get("model") or "gpt-4o")
        text = args.get("text")
        if args.get("prompt_tokens") is not None:
            prompt_tokens = max(0, int(args["prompt_tokens"]))
        elif isinstance(text, str) and text:
            prompt_tokens = CostCalculator.estimate_text_tokens(text)
        else:
            prompt_tokens = 1000
        completion_tokens = max(0, int(args.get("completion_tokens", 400)))
        details = CostCalculator.calculate_cost(model, prompt_tokens, completion_tokens)
        pricing = CostCalculator.get_pricing(model)
        return {
            **dict(details),
            "resolved_model": pricing.model_id,
            "family": pricing.family,
            "local_zero_cost": pricing.input_rate == 0.0 and pricing.output_rate == 0.0,
        }

    if name == "budget_circuit_breaker_status":
        action = str(args.get("action") or "status").lower()
        if action == "trip":
            return dispatch_tool_call("budget_trip", args, host=host, port=port, db_path=db_path)
        if action == "reset":
            return dispatch_tool_call(
                "budget_reset",
                {"reset_spend": bool(args.get("clear", args.get("reset_spend", False)))},
                host=host,
                port=port,
                db_path=db_path,
            )
        if action == "set-budget":
            return dispatch_tool_call(
                "budget_set_ceiling",
                {"max_budget_usd": args.get("amount", args.get("max_budget_usd"))},
                host=host,
                port=port,
                db_path=db_path,
            )
        try:
            stats = _http_json(host, port, "/api/stats", method="GET")
            return {"online": True, "source": "live_daemon", **stats}
        except Exception:
            return _offline_db_status(db_path)

    if name == "budget_set_ceiling":
        amount = args.get("max_budget_usd")
        if amount is None:
            raise ValueError("max_budget_usd is required")
        payload: Dict[str, Any] = {"max_budget_usd": float(amount)}
        if args.get("velocity_limit_usd_per_min") is not None:
            payload["velocity_limit"] = float(args["velocity_limit_usd_per_min"])
        return _http_json(host, port, "/api/budget", method="POST", payload=payload)

    if name == "budget_trip":
        reason = str(args.get("reason") or "MCP agent emergency kill switch engaged.")
        return _http_json(host, port, "/api/trip", method="POST", payload={"reason": reason})

    if name == "budget_reset":
        reset_spend = bool(args.get("reset_spend", False))
        return _http_json(host, port, "/api/reset", method="POST", payload={"reset_spend": reset_spend})

    raise KeyError(f"Unknown MCP tool: {name}")


def handle_jsonrpc_message(
    msg: Dict[str, Any],
    *,
    host: str = "127.0.0.1",
    port: int = 8110,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Process one JSON-RPC 2.0 request object; returns response dict or None for notifications."""
    req_id = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params") or {}

    # JSON-RPC notification (no id) -> no response
    if req_id is None and method.startswith("notifications/"):
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "agent-budget-sentinel",
                    "version": SERVER_VERSION,
                },
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": MCP_TOOLS},
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments") or {}
        try:
            result_obj = dispatch_tool_call(
                tool_name, tool_args, host=host, port=port, db_path=db_path
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result_obj, indent=2)}],
                    "structuredContent": result_obj,
                    "isError": False,
                },
            }
        except KeyError as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": str(exc)},
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps({"error": str(exc)})}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def run_stdio_mcp(
    host: str = "127.0.0.1",
    port: int = 8110,
    db_path: Optional[str] = None,
) -> None:
    """Run line-delimited JSON-RPC 2.0 MCP server on stdin/stdout."""
    if db_path is None:
        repo_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        db_path = os.path.join(repo_dir, "budget.db")

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()
            continue

        resp = handle_jsonrpc_message(msg, host=host, port=port, db_path=db_path)
        if resp is not None:
            try:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
            except BrokenPipeError:
                return
