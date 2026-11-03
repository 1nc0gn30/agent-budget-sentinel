<div align="center">
  <img src="assets/hero-banner.svg" alt="Agent Budget Sentinel — Sovereign Architecture Banner" width="100%" />
</div>

<br />

# ⚡ Agent Budget Sentinel

> ⚡ **Live Web Application**: [https://agent-budget-sentinel.nullai.tech](https://agent-budget-sentinel.nullai.tech)  
> ✦ **100% Free & Open-Access Sovereign Developer Tool**: Zero paywalls, zero license keys, zero gatekeepers.  
> ☕ **Buy Us a Coffee**: **[Support via Stripe](https://buy.stripe.com/3cIfZg27PdKo2D64Ocfw40X)** | **Solana Tip**: `GG2eQbVh8ut1BK6j1A2tz7pSySdLpD38BgyEhGcxdXoK`  

**Autonomous LLM Token Cost Circuit Breaker & Inline Spending Guardrail for AI Agents**  
*Engineered by 1nc0gn30 • NullAI ([@1nc0gn30](https://github.com/1nc0gn30)) • NullAI Platform*

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-gold.svg)](https://www.python.org/downloads/)
[![Zero External Dependencies](https://img.shields.io/badge/dependencies-zero_pip-emerald.svg)](#architecture)
[![Port 8110 / 8111](https://img.shields.io/badge/mesh_ports-8110_|_8111-cyan.svg)](#ports)
[![Sovereign Standard](https://img.shields.io/badge/standard-1nc0gn30_nullai-blue.svg)](https://nullai.tech)

---

## 🎯 What is Agent Budget Sentinel?

Autonomous AI agents running recursive tool loops, multi-agent debates, and self-refinement chains are notoriously prone to **infinite loop burnouts**—generating runaway cloud bills in minutes.

`agent-budget-sentinel` is an autonomous, **zero-dependency** inline HTTP proxy and spending guardrail. It sits transparently between your AI agents and upstream LLM providers (OpenAI, Anthropic, Gemini, DeepSeek, or local twins). When token consumption breaches your designated spending ceiling or trips an emergency velocity spike, it immediately activates its **Circuit Breaker**, cutting off outbound calls with `HTTP 429 Too Many Requests` and saving your treasury from financial ruin.

---

## 🛡 Sovereign Architectural Highlights

1. **Zero External Pip Dependencies**:
   - 100% Python standard library (`http.server`, `socket`, `sqlite3`, `json`, `urllib.parse`, `threading`, `dataclasses`).
   - Whisper-quiet, event-driven blocking I/O with 0% CPU burn when idle.
2. **Inline Circuit Breaker State Machine**:
   - `CLOSED`: Normal operation (<80% of budget limit).
   - `WARN`: Spending between 80% and 99% of limit (dispatches telemetry warning events).
   - `TRIPPED`: Spending >= 100% or manual kill switch active. Halts requests immediately.
3. **Comprehensive Pricing Matrix**:
   - Built-in real-time rates for GPT-4o, GPT-4o-mini, o1, Claude 3.5 Sonnet, Claude 3.5 Haiku, Gemini 1.5 Pro, DeepSeek V3/R1, and Llama 3.3.
4. **Avant-Garde Web Deck (:8110)**:
   - Real-time Server-Sent Events (SSE) telemetry radar.
   - Interactive Try-Before-You-Buy token cost calculator.
   - Emergency operator kill switch and burst test simulation harness.
5. **100% Free & Open-Access Architecture (Zero Paywalls)**:
   - 100% unlocked tools, export utilities, and multi-agent quota fences.
   - Voluntary community support via **Stripe Buy Us a Coffee** (`https://buy.stripe.com/3cIfZg27PdKo2D64Ocfw40X`) and **Solana Tip Address** (`GG2eQbVh8ut1BK6j1A2tz7pSySdLpD38BgyEhGcxdXoK`).

---

## 🚀 Quickstart & Installation

```bash
# Clone the repository
git clone https://github.com/1nc0gn30/agent-budget-sentinel.git
cd agent-budget-sentinel

# Make CLI executable
chmod +x bin/agent-budget

# Launch the Web Deck (:8110) and Inline Proxy (:8111) with a $5.00 emergency ceiling
./bin/agent-budget serve --budget 5.00
```

### Route Your Agents Through the Circuit Breaker

```bash
# Option 1: Using OpenAI environment variable
export OPENAI_BASE_URL="http://127.0.0.1:8110 (Web Deck) & 127.0.0.1:8111 (Proxy)/v1"
python my_agent.py

# Option 2: Automatic wrapper
./bin/agent-budget run -- python my_agent.py
```

---

## 📡 REST API & Integration

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Health check & circuit breaker status |
| `GET` | `/api/stats` | Comprehensive spending telemetry, token counts, and breaker state |
| `GET` | `/api/transactions` | Intercepted API calls ledger |
| `GET` | `/api/stream` | Server-Sent Events (SSE) live push stream |
| `POST` | `/api/budget` | Dynamically update budget ceiling (`{"max_budget_usd": 10.0}`) |
| `POST` | `/api/trip` | Emergency operator kill switch (`{"reason": "Manual trip"}`) |
| `POST` | `/api/reset` | Reset circuit breaker to `CLOSED` (`{"reset_spend": false}`) |
| `POST` | `/api/simulate` | Test token estimation and breaker response safely |

---

## 🧪 Automated Test Suite

```bash
python3 -m pytest -v
```

All tests execute with 100% standard library compliance and sub-second execution.

---

## 📜 License & Sovereign Attribution

Engineered by **1nc0gn30 • NullAI** ([@1nc0gn30](https://github.com/1nc0gn30)) • [NullAI Platform](https://nullai.tech).  
Licensed under the MIT License.

## Network exposure

The server binds to `127.0.0.1` by default. To reach it from other devices,
opt in explicitly with `--host 0.0.0.0` (or set `ZOTH_BIND_HOST=0.0.0.0`; an IP
in `HOST` is also honoured, a plain hostname is ignored) and only on a trusted
network.

Browser requests are only accepted from `localhost` / `127.0.0.1` pages:
cross-site POSTs get `403` and CORS never answers `*`, so a website you visit
can't drive this local server. CLI and agent clients are unaffected.

---

## 🏛️ ZothOS v3.4, Zoth Studio v2 & Obsidian Second Brain Ecosystem

```mermaid
flowchart LR
    subgraph ZothOS["🐧 ZothOS v3.4 CLI & Braille TUI"]
        CLI["agent-budget-sentinel --help / --json"]
        TUI["agent-budget-sentinel-tui<br/>Unicode U+2800 2x4 Braille"]
    end

    subgraph Workstation["⚡ Sovereign Workstation"]
        WEB["http://127.0.0.1:8110<br/>REST API & /health"]
    end

    subgraph Studio["🌌 Zoth Studio v2 & ZothOS-Lite"]
        GODMODE["http://127.0.0.1:3000/tools/agent-budget-sentinel<br/>God-Mode Workstation"]
        LITE["http://127.0.0.1:8145<br/>ZothOS-Lite Web Desktop"]
    end

    subgraph SecondBrain["💎 Obsidian Second Brain & STDP"]
        TRACKER["http://127.0.0.1:8151<br/>Zoth Obsidian Tracker"]
        NEURO["http://127.0.0.1:8094<br/>Neuro-Memory STDP Cortex"]
        NOTE["Studio/Tools/Studio agent-budget-sentinel.md"]
    end

    CLI --> WEB
    TUI --> WEB
    WEB <--> GODMODE
    WEB <--> LITE
    WEB --> TRACKER
    TRACKER <--> NOTE
    NOTE <--> NEURO
```

### Cross-Surface Integration Matrix

| Surface | Endpoint / Binary | Capabilities |
| :--- | :--- | :--- |
| **Standalone Workstation** | `http://127.0.0.1:8110` | 100% Free & Open-Access Web Deck, live `/health` & REST telemetry |
| **Zoth Studio v2 Route** | `http://127.0.0.1:3000/tools/agent-budget-sentinel` | Interactive God-Mode component inside Zoth Studio (`https://zoth.nullai.tech`) |
| **ZothOS v3.4 CLI & TUI** | `agent-budget-sentinel` / `agent-budget-sentinel-tui` | Global binary in `/usr/local/bin/` with Unicode `U+2800` Braille TUI & `--json` output |
| **ZothOS-Lite Web Desktop** | `http://127.0.0.1:8145` | Browser-native KDE-style window manager & terminal launcher |
| **Zoth Obsidian Tracker** | `http://127.0.0.1:8151` | Interactive Obsidian Second Brain vault explorer (`~/Documents/Obsidian Vault/Studio/Tools/Studio agent-budget-sentinel.md`) |
| **Neuro-Memory STDP Cortex** | `http://127.0.0.1:8094` | 3-Factor STDP synaptic memory daemon & 21-tool MCP server |

```bash
# Inspect CLI & Unicode U+2800 Braille TUI on ZothOS v3.4
agent-budget-sentinel --help
agent-budget-sentinel-tui --status
agent-budget-sentinel-tui --json

# Verify Second Brain Vault & 12-Step Verification Gallery on :8151
zoth-obsidian-tracker --verify
```

