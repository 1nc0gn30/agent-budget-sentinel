/**
 * AGENT BUDGET SENTINEL v2.6.0 — Live Telemetry & BPE Estimator Engine
 * Zero fabricated spend • Zero obsolete license keys • Zero innerHTML XSS sinks.
 * Engineered by Neal Frazier Tech (@1nc0gn30) • NullAI Platform.
 */

'use strict';

const SOLANA_TIP_ADDRESS = 'GG2eQbVh8ut1BK6j1A2tz7pSySdLpD38BgyEhGcxdXoK';

// Model Pricing Catalog (Per 1 Million Tokens in USD) — Synced with calculator.py
const MODEL_PRICING = {
  'gpt-5': { inRate: 1.25, outRate: 10.00, family: 'OpenAI' },
  'gpt-5-mini': { inRate: 0.25, outRate: 2.00, family: 'OpenAI' },
  'gpt-4.1': { inRate: 2.00, outRate: 8.00, family: 'OpenAI' },
  'gpt-4.1-mini': { inRate: 0.40, outRate: 1.60, family: 'OpenAI' },
  'gpt-4o': { inRate: 2.50, outRate: 10.00, family: 'OpenAI' },
  'gpt-4o-mini': { inRate: 0.15, outRate: 0.60, family: 'OpenAI' },
  'o3': { inRate: 2.00, outRate: 8.00, family: 'OpenAI' },
  'o4-mini': { inRate: 1.10, outRate: 4.40, family: 'OpenAI' },
  'o1': { inRate: 15.00, outRate: 60.00, family: 'OpenAI' },
  'o1-preview': { inRate: 15.00, outRate: 60.00, family: 'OpenAI' },
  'o1-mini': { inRate: 3.00, outRate: 12.00, family: 'OpenAI' },
  'claude-opus-5.5': { inRate: 15.00, outRate: 75.00, family: 'Anthropic' },
  'claude-sonnet-5.5': { inRate: 3.00, outRate: 15.00, family: 'Anthropic' },
  'claude-opus-4': { inRate: 15.00, outRate: 75.00, family: 'Anthropic' },
  'claude-sonnet-4': { inRate: 3.00, outRate: 15.00, family: 'Anthropic' },
  'claude-haiku-4': { inRate: 0.80, outRate: 4.00, family: 'Anthropic' },
  'claude-3-5-sonnet': { inRate: 3.00, outRate: 15.00, family: 'Anthropic' },
  'claude-3-5-haiku': { inRate: 0.80, outRate: 4.00, family: 'Anthropic' },
  'gemini-4-neon': { inRate: 1.25, outRate: 10.00, family: 'Google' },
  'gemini-3.8-flash': { inRate: 0.15, outRate: 0.60, family: 'Google' },
  'gemini-2.5-pro': { inRate: 1.25, outRate: 10.00, family: 'Google' },
  'gemini-2.5-flash': { inRate: 0.15, outRate: 0.60, family: 'Google' },
  'gemini-1.5-pro': { inRate: 1.25, outRate: 5.00, family: 'Google' },
  'deepseek-r1': { inRate: 0.55, outRate: 2.19, family: 'DeepSeek' },
  'deepseek-v3': { inRate: 0.14, outRate: 0.28, family: 'DeepSeek' },
  'meta-llama/llama-3.3-70b-instruct': { inRate: 0.40, outRate: 0.40, family: 'Open-Weights' },
  'ollama/qwen2.5-coder': { inRate: 0.00, outRate: 0.00, family: 'Local Sovereign' },
  'ollama/llama3.3': { inRate: 0.00, outRate: 0.00, family: 'Local Sovereign' },
  'agy/local': { inRate: 0.00, outRate: 0.00, family: 'Local Sovereign' },
  'hermes/local': { inRate: 0.00, outRate: 0.00, family: 'Local Sovereign' },
  'azoth/local': { inRate: 0.00, outRate: 0.00, family: 'Local Sovereign' },
  'deepseek-r1-local': { inRate: 0.00, outRate: 0.00, family: 'Local Sovereign' }
};

// Honest zeroed initial state (never fabricated spend/transactions)
const EMPTY_STATS = {
  state: 'CLOSED',
  current_spend_usd: 0.0,
  max_budget_usd: 5.0,
  percentage_used: 0.0,
  remaining_budget_usd: 5.0,
  velocity_usd_per_min: 0.0,
  total_tokens: 0,
  total_requests: 0,
  blocked_requests: 0,
  trip_reason: null
};

let isLiveBackend = false;
let eventSource = null;
let currentStats = { ...EMPTY_STATS };
let currentTransactions = [];

document.addEventListener('DOMContentLoaded', async () => {
  purgeLegacyLicenseKeys();
  initThemeToggle();
  initCalculator();
  initBreakerControls();
  await probeAndConnect();
});

function purgeLegacyLicenseKeys() {
  try {
    ['pro_licensed', 'budget_sentinel_pro_license', 'agent_budget_pro', 'zoth_budget_licensed'].forEach((k) => {
      localStorage.removeItem(k);
    });
  } catch (_e) {}
}

// --- Dual-Theme Sync (Obsidian Dark & Editorial Ivory Light) ---
function applyTheme(theme) {
  const normalized = theme === 'light' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', normalized);
  try {
    localStorage.setItem('sentinel_theme', normalized);
  } catch (_e) {}
  const btn = document.getElementById('btnThemeToggle');
  if (btn) {
    btn.textContent = normalized === 'light' ? '☾ Obsidian' : '☀ Ivory';
  }
}

function initThemeToggle() {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  applyTheme(current);
  const btn = document.getElementById('btnThemeToggle');
  if (btn) {
    btn.addEventListener('click', () => {
      const cur = document.documentElement.getAttribute('data-theme') || 'dark';
      applyTheme(cur === 'light' ? 'dark' : 'light');
    });
  }
  window.addEventListener('message', (ev) => {
    if (ev && ev.data && ev.data.type === 'zoth-theme' && (ev.data.theme === 'light' || ev.data.theme === 'dark')) {
      applyTheme(ev.data.theme);
    }
  });
}

// --- Dynamic Same-Origin /api/health Probe (No Hardcoded Port 8110 Check) ---
async function probeAndConnect() {
  const badge = document.getElementById('daemonModeBadge');
  try {
    const res = await fetch('/api/health', { cache: 'no-store' });
    if (res.ok) {
      const health = await res.json();
      if (health && health.status === 'ok') {
        isLiveBackend = true;
        if (badge) {
          badge.textContent = `ONLINE :${health.web_port || window.location.port || '8110'}`;
          badge.className = 'badge badge-success';
        }
        await fetchStats();
        connectSSE();
        return;
      }
    }
  } catch (_e) {}

  isLiveBackend = false;
  if (badge) {
    badge.textContent = 'OFFLINE · CLIENT ESTIMATOR';
    badge.className = 'badge badge-gold';
  }
  renderStats(EMPTY_STATS);
  renderTransactionsTable([]);
}

function copySolanaTip(ev) {
  if (ev) ev.preventDefault();
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(SOLANA_TIP_ADDRESS)
      .then(() => showToast('✓ Copied Solana tip address (GG2eQb...dXoK)'))
      .catch(() => showToast(`Solana: ${SOLANA_TIP_ADDRESS}`));
  } else {
    showToast(`Solana: ${SOLANA_TIP_ADDRESS}`);
  }
}

function copyConfigCommand() {
  const cmd = 'export OPENAI_BASE_URL="http://127.0.0.1:8111/v1"\nagent-budget run --max-budget 2.50 -- python3 my_agent.py';
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(cmd)
      .then(() => showToast('✓ Copied proxy startup command'))
      .catch(() => showToast('Proxy URL: http://127.0.0.1:8111/v1'));
  } else {
    showToast('Proxy URL: http://127.0.0.1:8111/v1');
  }
}

// --- Live Telemetry & Stats ---
async function fetchStats() {
  if (!isLiveBackend) {
    renderStats(currentStats);
    return;
  }
  try {
    const res = await fetch('/api/stats', { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    currentStats = data;
    renderStats(data);
    await fetchTransactions();
  } catch (_e) {}
}

function renderStats(data) {
  if (!data) return;
  currentStats = { ...currentStats, ...data };
  const stateEl = document.getElementById('breakerStateBadge');
  const headerPill = document.getElementById('headerBreakerPill');
  const spendEl = document.getElementById('currentSpendVal');
  const maxEl = document.getElementById('maxBudgetVal');
  const remainEl = document.getElementById('remainingBudgetVal');
  const pctEl = document.getElementById('pctUsedVal');
  const progressBar = document.getElementById('budgetProgressBar');
  const velEl = document.getElementById('velocityVal');
  const totalTokensEl = document.getElementById('totalTokensVal');
  const reqsEl = document.getElementById('totalRequestsVal');
  const blockedEl = document.getElementById('blockedRequestsVal');
  const reasonBanner = document.getElementById('breakerReasonBanner');
  const ceilingInput = document.getElementById('inputNewBudget');

  const state = data.state || 'CLOSED';
  const spend = Number(data.current_spend_usd || 0);
  const max = Number(data.max_budget_usd || 5);
  const pct = Number(data.percentage_used ?? (max > 0 ? (spend / max) * 100 : 0));
  const remain = Number(data.remaining_budget_usd ?? Math.max(0, max - spend));

  if (stateEl) {
    stateEl.textContent = state;
    stateEl.className = `status-pill status-${state.toLowerCase()}`;
  }
  if (headerPill) {
    headerPill.textContent = `BREAKER: ${state}`;
    headerPill.className = `status-pill status-${state.toLowerCase()}`;
  }

  if (window.ChronoVault && window.ChronoVault.setState) {
    window.ChronoVault.setState(state);
  }
  const canvasPill = document.getElementById('canvasStatePill');
  if (canvasPill) {
    canvasPill.textContent = state === 'TRIPPED' ? 'AEGIS: TRIPPED' : (state === 'WARN' ? 'AEGIS: WARN' : '60 FPS STREAM');
    canvasPill.className = `status-pill status-${state.toLowerCase()}`;
  }

  if (spendEl) spendEl.textContent = `$${spend.toFixed(4)}`;
  if (maxEl) maxEl.textContent = `$${max.toFixed(2)}`;
  if (remainEl) remainEl.textContent = `$${Math.max(0, remain).toFixed(4)}`;
  if (pctEl) pctEl.textContent = `${pct.toFixed(1)}%`;
  if (ceilingInput && document.activeElement !== ceilingInput) {
    ceilingInput.value = max.toFixed(2);
  }

  if (progressBar) {
    progressBar.style.width = `${Math.min(100, Math.max(2, pct))}%`;
    if (state === 'TRIPPED') {
      progressBar.style.background = 'linear-gradient(90deg, #EF4444, #DC2626)';
    } else if (state === 'WARN') {
      progressBar.style.background = 'linear-gradient(90deg, #F59E0B, #D97706)';
    } else {
      progressBar.style.background = 'linear-gradient(90deg, #10B981, #059669)';
    }
    const barContainer = progressBar.parentElement;
    if (barContainer) barContainer.setAttribute('aria-valuenow', String(Math.round(pct)));
  }

  if (velEl) velEl.textContent = `$${Number(data.velocity_usd_per_min || 0).toFixed(4)}/min`;
  if (totalTokensEl) totalTokensEl.textContent = Number(data.total_tokens || 0).toLocaleString();
  if (reqsEl) reqsEl.textContent = Number(data.total_requests || 0).toLocaleString();
  if (blockedEl) blockedEl.textContent = Number(data.blocked_requests || 0).toLocaleString();

  if (reasonBanner) {
    if (state === 'TRIPPED' && data.trip_reason) {
      reasonBanner.style.display = 'block';
      reasonBanner.textContent = `CIRCUIT TRIPPED: ${data.trip_reason}`;
    } else {
      reasonBanner.style.display = 'none';
      reasonBanner.textContent = '';
    }
  }
}

async function fetchTransactions() {
  if (!isLiveBackend) {
    renderTransactionsTable(currentTransactions);
    return;
  }
  try {
    const res = await fetch('/api/transactions?limit=25', { cache: 'no-store' });
    if (!res.ok) return;
    const json = await res.json();
    currentTransactions = json.transactions || [];
    renderTransactionsTable(currentTransactions);
  } catch (_e) {}
}

function renderTransactionsTable(txs) {
  const tbody = document.getElementById('txTableBody');
  if (!tbody) return;
  tbody.textContent = '';

  if (!txs || txs.length === 0) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 6;
    td.className = 'empty-cell';
    td.textContent = isLiveBackend
      ? 'No intercepted transactions recorded yet. Send traffic through :8111 or click Simulate.'
      : 'Local daemon offline. Start `agent-budget serve --web-port 8110 --proxy-port 8111` for live telemetry.';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  txs.forEach((t) => {
    const tr = document.createElement('tr');
    const isTripped = t.tripped === 1 || t.tripped === true || t.status_code === 429;
    const timeStr = t.timestamp ? new Date(t.timestamp).toLocaleTimeString() : 'Just now';
    const totalToks = (Number(t.prompt_tokens || 0) + Number(t.completion_tokens || 0)).toLocaleString();
    const costFormatted = isTripped ? '$0.0000 (Blocked)' : `$${Number(t.cost_usd || 0).toFixed(5)}`;
    const latStr = `${Number(t.latency_ms || 0).toFixed(1)} ms`;

    const tdTime = document.createElement('td');
    tdTime.className = 'text-mono';
    tdTime.textContent = timeStr;

    const tdModel = document.createElement('td');
    tdModel.className = 'text-gold font-bold';
    tdModel.textContent = String(t.model || 'unknown');

    const tdToks = document.createElement('td');
    tdToks.className = 'text-mono';
    tdToks.textContent = totalToks;

    const tdCost = document.createElement('td');
    tdCost.className = 'text-mono';
    tdCost.textContent = costFormatted;

    const tdLat = document.createElement('td');
    tdLat.className = 'text-mono';
    tdLat.textContent = latStr;

    const tdStatus = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = `badge ${isTripped ? 'badge-danger' : 'badge-success'}`;
    badge.textContent = isTripped ? '429 TRIPPED' : `${t.status_code || 200} OK`;
    tdStatus.appendChild(badge);

    tr.append(tdTime, tdModel, tdToks, tdCost, tdLat, tdStatus);
    tbody.appendChild(tr);
  });
}

// --- SSE Real-Time Stream ---
function connectSSE() {
  if (eventSource || !isLiveBackend) return;
  try {
    eventSource = new EventSource('/api/stream');
    eventSource.addEventListener('init', (e) => {
      try {
        renderStats(JSON.parse(e.data));
      } catch (_err) {}
    });
    ['transaction', 'trip', 'reset', 'config_change'].forEach((evt) => {
      eventSource.addEventListener(evt, () => fetchStats());
    });
  } catch (_e) {}
}

// --- Interactive Client-Side Token Cost Calculator ---
function initCalculator() {
  const modelSelect = document.getElementById('calcModelSelect');
  const promptInput = document.getElementById('calcPromptTokens');
  const completionInput = document.getElementById('calcCompletionTokens');
  const callCountInput = document.getElementById('calcCallCount');

  const recalc = () => {
    const model = modelSelect ? modelSelect.value : 'gpt-4o';
    const promptTokens = Math.max(0, Number(promptInput ? promptInput.value : 1200));
    const completionTokens = Math.max(0, Number(completionInput ? completionInput.value : 450));
    const count = Math.max(1, Number(callCountInput ? callCountInput.value : 1));

    const pricing = MODEL_PRICING[model] || { inRate: 2.00, outRate: 8.00 };
    const singleCost = ((promptTokens * pricing.inRate) + (completionTokens * pricing.outRate)) / 1_000_000.0;
    const totalCost = singleCost * count;

    const costSingleEl = document.getElementById('calcSingleCost');
    const costTotalEl = document.getElementById('calcTotalCost');
    if (costSingleEl) costSingleEl.textContent = `$${singleCost.toFixed(5)}`;
    if (costTotalEl) costTotalEl.textContent = `$${totalCost.toFixed(4)}`;
  };

  [modelSelect, promptInput, completionInput, callCountInput].forEach((el) => {
    if (el) {
      el.addEventListener('input', recalc);
      el.addEventListener('change', recalc);
    }
  });
  recalc();
}

// --- Circuit Breaker Controls & Live Simulation ---
function initBreakerControls() {
  const setBudgetBtn = document.getElementById('btnSetBudget');
  if (setBudgetBtn) {
    setBudgetBtn.addEventListener('click', async () => {
      const input = document.getElementById('inputNewBudget');
      const val = parseFloat(input ? input.value : '5');
      if (!Number.isFinite(val) || val <= 0) {
        showToast('Enter a valid dollar ceiling > $0');
        return;
      }
      if (!isLiveBackend) {
        showToast('Daemon offline — start `agent-budget serve` to update live ceiling');
        return;
      }
      try {
        const res = await fetch('/api/budget', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ max_budget_usd: val })
        });
        const data = await res.json();
        if (!res.ok) {
          showToast(data.error || 'Failed to update ceiling');
          return;
        }
        renderStats(data.breaker);
        showToast(`✓ Budget ceiling persisted at $${val.toFixed(2)} USD`);
      } catch (_e) {
        showToast('Error reaching /api/budget');
      }
    });
  }

  const tripBtn = document.getElementById('btnTripBreaker');
  if (tripBtn) {
    tripBtn.addEventListener('click', async () => {
      if (!isLiveBackend) {
        showToast('Daemon offline — start `agent-budget serve` to control live breaker');
        return;
      }
      try {
        const res = await fetch('/api/trip', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: 'Manual operator kill switch engaged from Web Deck.' })
        });
        const data = await res.json();
        renderStats(data.breaker);
        showToast('Circuit Breaker TRIPPED — :8111 returning HTTP 429');
      } catch (_e) {
        showToast('Error reaching /api/trip');
      }
    });
  }

  const resetBtn = document.getElementById('btnResetBreaker');
  if (resetBtn) {
    resetBtn.addEventListener('click', async () => {
      if (!isLiveBackend) {
        showToast('Daemon offline — start `agent-budget serve` to reset live breaker');
        return;
      }
      try {
        const res = await fetch('/api/reset', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reset_spend: false })
        });
        const data = await res.json();
        renderStats(data.breaker);
        showToast('✓ Circuit Breaker RESET to CLOSED');
      } catch (_e) {
        showToast('Error reaching /api/reset');
      }
    });
  }

  const sim1Btn = document.getElementById('btnSimulateSingle');
  if (sim1Btn) {
    sim1Btn.addEventListener('click', async () => {
      if (!isLiveBackend) {
        showToast('Daemon offline — start `agent-budget serve` to run live simulations');
        return;
      }
      const model = document.getElementById('calcModelSelect')?.value || 'gpt-4o';
      const promptTokens = Number(document.getElementById('calcPromptTokens')?.value || 1200);
      const completionTokens = Number(document.getElementById('calcCompletionTokens')?.value || 450);
      try {
        const res = await fetch('/api/simulate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model, prompt_tokens: promptTokens, completion_tokens: completionTokens })
        });
        const data = await res.json();
        if (data.breaker) renderStats(data.breaker);
        await fetchTransactions();
        if (data.allowed === false) {
          showToast(`BREAKER TRIPPED (429): ${data.reason}`);
        } else {
          showToast(`✓ Simulated ${model}: +$${Number(data.cost_usd || 0).toFixed(5)}`);
        }
      } catch (_e) {
        showToast('Simulation request failed');
      }
    });
  }

  const simRunawayBtn = document.getElementById('btnSimulateRunaway');
  if (simRunawayBtn) {
    simRunawayBtn.addEventListener('click', async () => {
      if (!isLiveBackend) {
        showToast('Daemon offline — start `agent-budget serve` to run burst simulations');
        return;
      }
      try {
        simRunawayBtn.disabled = true;
        simRunawayBtn.textContent = 'Simulating Burst...';
        const res = await fetch('/api/simulate_runaway', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ iterations: 12, model: 'o1-preview' })
        });
        const data = await res.json();
        if (data.breaker) renderStats(data.breaker);
        await fetchTransactions();
        if (data.tripped_at_iteration) {
          showToast(`⚡ Runaway loop halted at iteration #${data.tripped_at_iteration}`);
        } else {
          showToast(`Completed ${data.iterations_run} simulated calls`);
        }
      } catch (_e) {
        showToast('Burst simulation failed');
      } finally {
        simRunawayBtn.disabled = false;
        simRunawayBtn.textContent = '⚡ Simulate Runaway Loop Burst';
      }
    });
  }
}

// --- Audit Exports ---
function triggerAuditExport() {
  exportAuditLedger('json');
}

async function exportAuditLedger(format = 'json') {
  let txs = currentTransactions;
  if (isLiveBackend) {
    try {
      const res = await fetch('/api/transactions?limit=250', { cache: 'no-store' });
      if (res.ok) {
        const json = await res.json();
        if (json.transactions) txs = json.transactions;
      }
    } catch (_e) {}
  }

  if (!txs || txs.length === 0) {
    showToast('No transaction records available to export yet.');
    return;
  }

  const link = document.createElement('a');
  if (format === 'csv') {
    const headers = ['id', 'timestamp', 'model', 'prompt_tokens', 'completion_tokens', 'cost_usd', 'latency_ms', 'status_code', 'tripped', 'reason'];
    const rows = txs.map((t) => headers.map((h) => JSON.stringify(t[h] ?? '')).join(','));
    link.href = 'data:text/csv;charset=utf-8,' + encodeURIComponent([headers.join(','), ...rows].join('\n'));
    link.download = `budget_sentinel_audit_${Date.now()}.csv`;
  } else {
    link.href = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(txs, null, 2));
    link.download = `budget_sentinel_audit_${Date.now()}.json`;
  }
  document.body.appendChild(link);
  link.click();
  link.remove();
  showToast(`✓ Exported ${txs.length} audit records (${format.toUpperCase()})`);
}

function openShowreelModal() {
  const modal = document.getElementById('showreelModal');
  if (modal) modal.style.display = 'flex';
}

function closeShowreelModal() {
  const modal = document.getElementById('showreelModal');
  if (modal) modal.style.display = 'none';
}

function showToast(msg) {
  let toast = document.getElementById('sentinelToast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'sentinelToast';
    toast.className = 'toast';
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.style.display = 'flex';
  toast.style.opacity = '1';
  toast.style.transform = 'translateY(0)';
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    setTimeout(() => { toast.style.display = 'none'; }, 280);
  }, 2600);
}
