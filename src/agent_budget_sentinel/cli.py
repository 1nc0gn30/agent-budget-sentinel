"""Command Line Interface for agent-budget-sentinel.

100% Python Standard Library — Zero External Dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import List, Optional

from .breaker import BudgetPolicy, CircuitBreaker
from .proxy import BudgetProxyServer
from .server import BudgetWebServer
from .storage import BudgetStorage


def _default_bind_host() -> str:
    """Bind address: localhost unless explicitly opted in via $ZOTH_BIND_HOST or
    $HOST (IP literal only; zsh sets HOST to the hostname) or --host."""
    import ipaddress, os
    for var in ("ZOTH_BIND_HOST", "HOST"):
        val = os.environ.get(var, "").strip()
        if val == "localhost":
            return "127.0.0.1"
        if val:
            try:
                ipaddress.ip_address(val)
                return val
            except ValueError:
                pass
    return "127.0.0.1"


# ANSI Formatting Tokens
C_GOLD = "\033[38;5;214m"
C_CYAN = "\033[38;5;51m"
C_GREEN = "\033[38;5;48m"
C_RED = "\033[38;5;196m"
C_WARN = "\033[38;5;208m"
C_DIM = "\033[2m"
C_BOLD = "\033[1m"
C_RESET = "\033[0m"


def print_banner() -> None:
    print(f"{C_GOLD}{C_BOLD}⚡ AGENT-BUDGET-SENTINEL v1.0.0{C_RESET}")
    print(f"{C_DIM}Autonomous Spending Guardrail & Token Circuit Breaker for AI Agents{C_RESET}")
    print(f"{C_DIM}Engineered by Neal Frazier Tech (@1nc0gn30) • NullAI Platform{C_RESET}\n")


def cmd_serve(args: argparse.Namespace) -> None:
    print_banner()
    
    repo_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    public_dir = os.path.join(repo_dir, "public")
    db_path = os.path.abspath(args.db)

    print(f"{C_CYAN}Initializing Storage:{C_RESET} {db_path}")
    storage = BudgetStorage(db_path)

    policy = BudgetPolicy(
        max_budget_usd=float(args.budget),
        warn_threshold_pct=0.80,
        velocity_limit_usd_per_min=float(args.velocity_limit)
    )
    breaker = CircuitBreaker(policy)

    # Listen to breaker events to record in storage
    def on_breaker_event(evt_type: str, data: dict):
        storage.record_event(evt_type, f"Circuit Breaker event: {evt_type.upper()}", data)
    breaker.add_listener(on_breaker_event)

    print(f"{C_GREEN}Active Budget Ceiling:{C_RESET} ${args.budget:.2f} USD")
    print(f"{C_GREEN}Velocity Guardrail:{C_RESET} ${args.velocity_limit:.2f}/min")

    proxy_server = BudgetProxyServer(
        host=args.host,
        port=args.proxy_port,
        breaker=breaker,
        storage=storage,
        upstream_base=args.upstream
    )
    
    web_server = BudgetWebServer(
        host=args.host,
        port=args.web_port,
        breaker=breaker,
        storage=storage,
        public_dir=public_dir,
        proxy_port=args.proxy_port
    )

    t_proxy = threading.Thread(target=proxy_server.serve_forever, daemon=True, name="BudgetProxy")
    t_web = threading.Thread(target=web_server.serve_forever, daemon=True, name="BudgetWebDeck")
    
    t_proxy.start()
    t_web.start()

    print(f"{C_GOLD}Web Cockpit & REST API:{C_RESET} http://{args.host}:{args.web_port}")
    print(f"{C_CYAN}Inline Breaker Proxy:{C_RESET}    http://{args.host}:{args.proxy_port}")
    print(f"\n{C_DIM}Circuit Breaker is CLOSED (Operational). Awaiting agent traffic... (Ctrl+C to stop){C_RESET}\n")

    def shutdown(sig, frame):
        print(f"\n{C_WARN}Shutting down servers gracefully...{C_RESET}")
        proxy_server.shutdown()
        web_server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Blocking sleep loop (0% CPU)
    while True:
        time.sleep(1.0)


def cmd_status(args: argparse.Namespace) -> None:
    url = f"http://{args.host}:{args.port}/api/stats"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"{C_RED}Error connecting to agent-budget-sentinel at {url}: {e}{C_RESET}")
        sys.exit(1)

    print_banner()
    state = data.get("state", "UNKNOWN")
    state_color = C_GREEN if state == "CLOSED" else (C_WARN if state == "WARN" else C_RED)

    print(f"  Circuit Breaker: {state_color}{C_BOLD}[{state}]{C_RESET}")
    print(f"  Spent / Limit:   {C_GOLD}${data.get('current_spend_usd', 0):.4f}{C_RESET} / ${data.get('max_budget_usd', 0):.2f} USD ({data.get('percentage_used', 0):.1f}%)")
    print(f"  Remaining:       ${data.get('remaining_budget_usd', 0):.4f} USD")
    print(f"  Velocity:        ${data.get('velocity_usd_per_min', 0):.4f}/min (Limit: ${data.get('velocity_limit_usd_per_min', 0):.2f}/min)")
    print(f"  Total Requests:  {data.get('total_requests', 0)} ({data.get('blocked_requests', 0)} blocked by breaker)")
    print(f"  Tokens In/Out:   {data.get('total_prompt_tokens', 0):,} prompt / {data.get('total_completion_tokens', 0):,} completion ({data.get('total_tokens', 0):,} total)")
    if data.get("trip_reason"):
        print(f"  {C_RED}Trip Reason:{C_RESET}     {data.get('trip_reason')}")
    print()


def cmd_trip(args: argparse.Namespace) -> None:
    url = f"http://{args.host}:{args.port}/api/trip"
    try:
        body = json.dumps({"reason": args.reason or "CLI operator emergency trip."}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        print(f"{C_RED}{C_BOLD}💥 CIRCUIT BREAKER TRIPPED SUCCESSFULLY!{C_RESET}")
        print(f"State: {data.get('breaker', {}).get('state')}")
    except Exception as e:
        print(f"{C_RED}Error: {e}{C_RESET}")
        sys.exit(1)


def cmd_reset(args: argparse.Namespace) -> None:
    url = f"http://{args.host}:{args.port}/api/reset"
    try:
        body = json.dumps({"reset_spend": args.clear}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        print(f"{C_GREEN}{C_BOLD}✓ Circuit Breaker RESET to CLOSED.{C_RESET}")
        if args.clear:
            print(f"Spend ledger purged.")
    except Exception as e:
        print(f"{C_RED}Error: {e}{C_RESET}")
        sys.exit(1)


def cmd_set_budget(args: argparse.Namespace) -> None:
    url = f"http://{args.host}:{args.port}/api/budget"
    try:
        body = json.dumps({"max_budget_usd": args.amount}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        print(f"{C_GREEN}✓ Budget updated to ${args.amount:.2f} USD.{C_RESET}")
    except Exception as e:
        print(f"{C_RED}Error: {e}{C_RESET}")
        sys.exit(1)


def cmd_run(args: argparse.Namespace, remaining_args: List[str]) -> None:
    """Run an agent command wrapped with budget proxy routing."""
    if not remaining_args:
        print(f"{C_RED}Error: No command specified to run. Usage: agent-budget run -- <command>{C_RESET}")
        sys.exit(1)

    proxy_port = args.proxy_port
    proxy_url = f"http://127.0.0.1:{proxy_port}"

    env = os.environ.copy()
    env["OPENAI_BASE_URL"] = f"{proxy_url}/v1"
    env["ANTHROPIC_BASE_URL"] = f"{proxy_url}"
    env["HTTP_PROXY"] = proxy_url
    env["HTTPS_PROXY"] = proxy_url

    print_banner()
    print(f"{C_CYAN}Spawning wrapped agent process with Circuit Breaker at {proxy_url}...{C_RESET}")
    print(f"{C_DIM}Command: {' '.join(remaining_args)}{C_RESET}\n")

    res = subprocess.run(remaining_args, env=env)
    sys.exit(res.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-budget",
        description="Autonomous spending guardrail and token cost circuit breaker for AI agents."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # serve
    p_serve = subparsers.add_parser("serve", help="Launch Web Deck and Inline Proxy")
    p_serve.add_argument("--host", default=_default_bind_host(), help="Host interface (default: 127.0.0.1 or $ZOTH_BIND_HOST; use 0.0.0.0 only on trusted networks)")
    p_serve.add_argument("--web-port", type=int, default=8110, help="Web Cockpit Port (default 8110)")
    p_serve.add_argument("--proxy-port", type=int, default=8111, help="Inline Proxy Port (default 8111)")
    p_serve.add_argument("--budget", type=float, default=5.00, help="Budget ceiling in USD (default 5.00)")
    p_serve.add_argument("--velocity-limit", type=float, default=2.00, help="Max spend rate in USD/min (default 2.00)")
    p_serve.add_argument("--db", default="budget.db", help="SQLite database path")
    p_serve.add_argument("--upstream", default=None, help="Default upstream LLM base URL")

    # status
    p_status = subparsers.add_parser("status", help="Display current budget telemetry")
    p_status.add_argument("--host", default="127.0.0.1")
    p_status.add_argument("--port", type=int, default=8110)

    # trip
    p_trip = subparsers.add_parser("trip", help="Manually trip the circuit breaker")
    p_trip.add_argument("--host", default="127.0.0.1")
    p_trip.add_argument("--port", type=int, default=8110)
    p_trip.add_argument("--reason", default=None, help="Reason for trip")

    # reset
    p_reset = subparsers.add_parser("reset", help="Reset circuit breaker to CLOSED")
    p_reset.add_argument("--host", default="127.0.0.1")
    p_reset.add_argument("--port", type=int, default=8110)
    p_reset.add_argument("--clear", action="store_true", help="Purge historical spend ledger")

    # set-budget
    p_set = subparsers.add_parser("set-budget", help="Set maximum budget ceiling")
    p_set.add_argument("amount", type=float, help="Ceiling in USD")
    p_set.add_argument("--host", default="127.0.0.1")
    p_set.add_argument("--port", type=int, default=8110)

    # run
    p_run = subparsers.add_parser("run", help="Execute an agent command wrapped with budget proxy")
    p_run.add_argument("--proxy-port", type=int, default=8111)

    args, remaining = parser.parse_known_args()

    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "trip":
        cmd_trip(args)
    elif args.command == "reset":
        cmd_reset(args)
    elif args.command == "set-budget":
        cmd_set_budget(args)
    elif args.command == "run":
        cmd_run(args, remaining)


if __name__ == "__main__":
    main()
