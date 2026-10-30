#!/usr/bin/env python3
"""Agent Budget Sentinel - Standalone Server Daemon.

Engineered by Neal Frazier Tech (@1nc0gn30) • NullAI Platform.
100% Python Standard Library — Zero External Dependencies.
"""

from __future__ import annotations

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(SCRIPT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from agent_budget_sentinel.cli import cmd_serve


def main():
    parser = argparse.ArgumentParser(description="Agent Budget Sentinel Server")
    parser.add_argument("--web-port", "--port", dest="web_port", type=int, default=8110, help="Web Cockpit Port (default 8110)")
    parser.add_argument("--proxy-port", type=int, default=8111, help="Inline Proxy Port (default 8111)")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default 127.0.0.1)")
    parser.add_argument("--budget", type=float, default=5.00, help="Budget ceiling in USD (default 5.00)")
    parser.add_argument("--velocity-limit", type=float, default=2.00, help="Max spend rate in USD/min (default 2.00)")
    parser.add_argument("--db", default=os.path.join(SCRIPT_DIR, "budget.db"), help="SQLite database path")
    parser.add_argument("--upstream", default=None, help="Default upstream LLM base URL")

    args = parser.parse_args()
    cmd_serve(args)


if __name__ == "__main__":
    main()
