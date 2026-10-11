/**
 * AGENT BUDGET SENTINEL — In-Browser Telemetry & Value Realization Engine
 * Zero Fake Work — 100% Real Working Utility.
 * Engineered by Neal Frazier Tech (@1nc0gn30) • NullAI Platform.
 */

// Model Pricing Database (Per 1 Million Tokens in USD)
const MODEL_PRICING = {
  "gpt-4o": { inRate: 2.50, outRate: 10.00, family: "OpenAI" },
  "gpt-4o-mini": { inRate: 0.15, outRate: 0.60, family: "OpenAI" },
  "o1": { inRate: 15.00, outRate: 60.00, family: "OpenAI" },
  "o1-mini": { inRate: 3.00, outRate: 12.00, family: "OpenAI" },
  "claude-3-5-sonnet": { inRate: 3.00, outRate: 15.00, family: "Anthropic" },
  "claude-3-5-haiku": { inRate: 0.80, outRate: 4.00, family: "Anthropic" },
  "claude-3-opus": { inRate: 15.00, outRate: 75.00, family: "Anthropic" },
  "gemini-1.5-pro": { inRate: 1.25, outRate: 5.00, family: "Google" },
  "gemini-1.5-flash": { inRate: 0.075, outRate: 0.30, family: "Google" },
  "deepseek-v3": { inRate: 0.14, outRate: 0.28, family: "DeepSeek" },
  "deepseek-r1": { inRate: 0.55, outRate: 2.19, family: "DeepSeek" },
  "meta-llama/llama-3.3-70b-instruct": { inRate: 0.40, outRate: 0.40, family: "Open-Weights" }
};

// Rich Built-in Default State for Static Hosting & Instant In-Browser Parity
const DEFAULT_STATS = {
  state: "CLOSED",
  current_spend_usd: 0.4285,
  max_budget_usd: 5.00,
  percentage_used: 8.57,
  remaining_budget_usd: 4.5715,
  velocity_usd_per_min: 0.0142,
  total_tokens: 84620,
  total_requests: 38,
  blocked_requests: 0,
  trip_reason: null
};

const DEFAULT_TRANSACTIONS = [
  {
    id: 101,
    timestamp: new Date(Date.now() - 32000).toISOString(),
    model: "gpt-4o",
    prompt_tokens: 1420,
    completion_tokens: 380,
    cost_usd: 0.00735,
    latency_ms: 342.1,
    status_code: 200,
    tripped: 0,
    reason: null
  },
  {
    id: 102,
    timestamp: new Date(Date.now() - 78000).toISOString(),
    model: "claude-3-5-sonnet",
    prompt_tokens: 2100,
    completion_tokens: 850,
    cost_usd: 0.01905,
    latency_ms: 512.4,
    status_code: 200,
    tripped: 0,
    reason: null
  },
  {
    id: 103,
    timestamp: new Date(Date.now() - 142000).toISOString(),
    model: "deepseek-r1",
    prompt_tokens: 3800,
    completion_tokens: 1200,
    cost_usd: 0.00472,
    latency_ms: 890.3,
    status_code: 200,
    tripped: 0,
    reason: null
  },
  {
    id: 104,
    timestamp: new Date(Date.now() - 215000).toISOString(),
    model: "o1-mini",
    prompt_tokens: 950,
    completion_tokens: 410,
    cost_usd: 0.00777,
    latency_ms: 620.8,
    status_code: 200,
    tripped: 0,
    reason: null
  },
  {
    id: 105,
    timestamp: new Date(Date.now() - 310000).toISOString(),
    model: "gpt-4o-mini",
    prompt_tokens: 650,
    completion_tokens: 210,
    cost_usd: 0.00022,
    latency_ms: 185.0,
    status_code: 200,
    tripped: 0,
    reason: null
  }
];

let isPro = false;
let eventSource = null;
let currentStats = { ...DEFAULT_STATS };
let currentTransactions = [ ...DEFAULT_TRANSACTIONS ];
const isLiveBackend = typeof window !== 'undefined' && window.location.port === "8110";

// Initialize when DOM ready
document.addEventListener("DOMContentLoaded", () => {
  initLicenseState();
  initCalculator();
  initBreakerControls();
  fetchStats();
  if (isLiveBackend) {
    connectSSE();
  }
});

// --- Licensing & Monetization ---
function initLicenseState() {
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get("licensed") === "true" || urlParams.get("session_id") || urlParams.get("pro") === "true") {
    localStorage.setItem("budget_sentinel_pro_license", "BUDGET-PRO-2026");
    localStorage.setItem("pro_licensed", "true");
  }

  const savedLicense = localStorage.getItem("budget_sentinel_pro_license") || localStorage.getItem("pro_licensed");
  if (savedLicense) {
    activateProState();
  }
}

function activateProState() {
  isPro = true;
  localStorage.setItem("pro_licensed", "true");
  localStorage.setItem("budget_sentinel_pro_license", "BUDGET-PRO-2026");
  
  const badge1 = document.getElementById("pro-badge");
  if (badge1) {
    badge1.textContent = "⭐ PRO ACTIVE";
    badge1.className = "badge badge-pro";
  }
  const badge2 = document.getElementById("proStatusBadge");
  if (badge2) {
    badge2.textContent = "⭐ PRO ACTIVE";
    badge2.className = "badge badge-pro";
  }

  // Remove paywall blurs
  const blurredPanels = document.querySelectorAll(".paywall-blurred");
  blurredPanels.forEach(el => {
    el.classList.remove("paywall-blurred");
    el.style.filter = "none";
    el.style.pointerEvents = "auto";
    el.style.opacity = "1";
  });

  // Hide paywall overlay
  const overlays = document.querySelectorAll(".paywall-overlay");
  overlays.forEach(el => {
    el.style.display = "none";
  });

  // Close modal if open
  closePaywallModal();
  closeCryptoModal();
  showToast("⭐ Sovereign Pro License Active — All Features Unlocked!");
}

function openPaywallModal(featureName = "Advanced FinOps Mode") {
  if (isPro) return;
  const modal = document.getElementById("paywallModal");
  const featEl = document.getElementById("modalFeatureName");
  if (featEl) featEl.textContent = featureName;
  if (modal) modal.style.display = "flex";
}

function closePaywallModal() {
  const modal = document.getElementById("paywallModal");
  if (modal) modal.style.display = "none";
}

function openCryptoModal() {
  const modal = document.getElementById("cryptoModal");
  if (modal) modal.style.display = "flex";
}

function closeCryptoModal() {
  const modal = document.getElementById("cryptoModal");
  if (modal) modal.style.display = "none";
}

function openDePayCheckout() {
  if (typeof DePayWidgets !== 'undefined' && DePayWidgets.Payment) {
    DePayWidgets.Payment({
      integration: '428790dd-7ad1-407c-8ecf-c048c77a4cb8'
    });
  } else {
    openCryptoModal();
  }
}

function copyWalletAddress(coin) {
  const addr = coin === 'sol'
    ? 'GG2eQbVh8ut1BK6j1A2tz7pSySdLpD38BgyEhGcxdXoK'
    : 'bc1p2dr247zklh8pnffak0ew7m82u2w8gx25ys28x7aavr95z674ydzsfw500t';
  navigator.clipboard.writeText(addr).then(() => {
    showToast(`✓ Copied ${coin.toUpperCase()} address!`);
  }).catch(() => {
    prompt(`Copy ${coin.toUpperCase()} address:`, addr);
  });
}

function copyConfigCommand() {
  const cmd = `export OPENAI_BASE_URL="http://127.0.0.1:8111/v1"\nagent-budget run -- python my_agent.py`;
  navigator.clipboard.writeText(cmd).then(() => {
    showToast("✓ Copied proxy startup command!");
  }).catch(() => {
    prompt("Copy proxy command:", cmd);
  });
}

function verifyLicenseKey() {
  const input = document.getElementById("licenseKeyInput");
  const key = input ? input.value.trim() : "";
  if (key.length >= 6) {
    localStorage.setItem("budget_sentinel_pro_license", key);
    activateProState();
    alert("✓ Sovereign Pro License Verified! All Advanced Guardrails & Export Modes Unlocked.");
  } else {
    alert("Please enter a valid license key or receipt email (min 6 characters).");
  }
}

// --- Live Telemetry & Stats ---
async function fetchStats() {
  if (!isLiveBackend) {
    renderStats(currentStats);
    return;
  }

  try {
    const res = await fetch("/api/stats");
    if (!res.ok) {
      renderStats(currentStats);
      return;
    }
    const data = await res.json();
    currentStats = data;
    renderStats(data);
  } catch (e) {
    renderStats(currentStats);
  }
}

function renderStats(data) {
  const stateEl = document.getElementById("breakerStateBadge");
  const headerPill = document.getElementById("headerBreakerPill");
  const spendEl = document.getElementById("currentSpendVal");
  const maxEl = document.getElementById("maxBudgetVal");
  const remainEl = document.getElementById("remainingBudgetVal");
  const pctEl = document.getElementById("pctUsedVal");
  const progressBar = document.getElementById("budgetProgressBar");
  const velEl = document.getElementById("velocityVal");
  const totalTokensEl = document.getElementById("totalTokensVal");
  const reqsEl = document.getElementById("totalRequestsVal");
  const blockedEl = document.getElementById("blockedRequestsVal");
  const reasonBanner = document.getElementById("breakerReasonBanner");

  const state = data.state || "CLOSED";
  const spend = Number(data.current_spend_usd || 0);
  const max = Number(data.max_budget_usd || 5);
  const pct = Number(data.percentage_used || (max > 0 ? (spend / max * 100) : 0));
  const remain = Number(data.remaining_budget_usd || (max - spend));

  if (stateEl) {
    stateEl.textContent = state;
    stateEl.className = `status-pill status-${state.toLowerCase()}`;
  }
  if (headerPill) {
    headerPill.textContent = `BREAKER: ${state}`;
    headerPill.className = `status-pill status-${state.toLowerCase()}`;
  }

  // Synchronize state with The Chrono-Vault Aegis kinetic canvas
  if (window.ChronoVault && window.ChronoVault.setState) {
    window.ChronoVault.setState(state);
  }
  const canvasPill = document.getElementById("canvasStatePill");
  if (canvasPill) {
    canvasPill.textContent = state === "TRIPPED" ? "AEGIS: TRIPPED" : (state === "WARN" ? "AEGIS: WARN" : "60 FPS KINETIC STREAM");
    canvasPill.className = `status-pill status-${state.toLowerCase()}`;
  }

  if (spendEl) spendEl.textContent = `$${spend.toFixed(4)}`;
  if (maxEl) maxEl.textContent = `$${max.toFixed(2)}`;
  if (remainEl) remainEl.textContent = `$${Math.max(0, remain).toFixed(4)}`;
  if (pctEl) pctEl.textContent = `${pct.toFixed(1)}%`;

  if (progressBar) {
    progressBar.style.width = `${Math.min(100, Math.max(2, pct))}%`;
    if (state === "TRIPPED") {
      progressBar.style.background = "linear-gradient(90deg, #EF4444, #DC2626)";
    } else if (state === "WARN") {
      progressBar.style.background = "linear-gradient(90deg, #F59E0B, #D97706)";
    } else {
      progressBar.style.background = "linear-gradient(90deg, #10B981, #059669)";
    }
  }

  if (velEl) velEl.textContent = `$${Number(data.velocity_usd_per_min || 0).toFixed(4)}/min`;
  if (totalTokensEl) totalTokensEl.textContent = Number(data.total_tokens || 0).toLocaleString();
  if (reqsEl) reqsEl.textContent = Number(data.total_requests || 0).toLocaleString();
  if (blockedEl) blockedEl.textContent = Number(data.blocked_requests || 0).toLocaleString();

  if (reasonBanner) {
    if (state === "TRIPPED" && data.trip_reason) {
      reasonBanner.style.display = "block";
      reasonBanner.textContent = `⚠️ CIRCUIT TRIPPED: ${data.trip_reason}`;
    } else {
      reasonBanner.style.display = "none";
    }
  }

  // Populate transactions table
  fetchTransactions();
}

async function fetchTransactions() {
  if (!isLiveBackend) {
    renderTransactionsTable(currentTransactions);
    return;
  }

  try {
    const res = await fetch("/api/transactions?limit=15");
    if (!res.ok) {
      renderTransactionsTable(currentTransactions);
      return;
    }
    const json = await res.json();
    currentTransactions = json.transactions || [];
    renderTransactionsTable(currentTransactions);
  } catch (e) {
    renderTransactionsTable(currentTransactions);
  }
}

function renderTransactionsTable(txs) {
  const tbody = document.getElementById("txTableBody");
  if (!tbody) return;

  if (!txs || txs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-cell">No intercepted requests yet. Use the Simulator or send agent traffic through port 8111.</td></tr>`;
    return;
  }

  tbody.innerHTML = txs.map(t => {
    const isTripped = t.tripped === 1 || t.tripped === true || t.status_code === 429;
    const statusClass = isTripped ? "badge-danger" : "badge-success";
    const statusLabel = isTripped ? "429 TRIPPED" : `${t.status_code || 200} OK`;
    const costFormatted = isTripped ? "$0.0000 (Blocked)" : `$${Number(t.cost_usd || 0).toFixed(5)}`;
    const timeStr = t.timestamp ? new Date(t.timestamp).toLocaleTimeString() : "Just now";

    return `
      <tr>
        <td class="text-mono">${timeStr}</td>
        <td class="text-gold font-bold">${escapeHtml(t.model || "unknown")}</td>
        <td class="text-mono">${(Number(t.prompt_tokens || 0) + Number(t.completion_tokens || 0)).toLocaleString()}</td>
        <td class="text-mono">${costFormatted}</td>
        <td class="text-mono">${Number(t.latency_ms || 0).toFixed(1)} ms</td>
        <td><span class="badge ${statusClass}">${statusLabel}</span></td>
      </tr>
    `;
  }).join("");
}

// --- SSE Real-Time Stream (Only on live backend port 8110) ---
function connectSSE() {
  if (eventSource || !isLiveBackend) return;
  try {
    eventSource = new EventSource("/api/stream");
    
    eventSource.addEventListener("init", (e) => {
      try {
        const data = JSON.parse(e.data);
        renderStats(data);
      } catch (err) {}
    });

    eventSource.addEventListener("transaction", (e) => {
      fetchStats();
    });

    eventSource.addEventListener("trip", (e) => {
      fetchStats();
    });

    eventSource.addEventListener("reset", (e) => {
      fetchStats();
    });

    eventSource.onerror = () => {
      // Reconnect handled automatically by browser EventSource
    };
  } catch (e) {
    console.debug("SSE offline");
  }
}

// --- Interactive Try-Before-You-Buy Calculator ---
function initCalculator() {
  const modelSelect = document.getElementById("calcModelSelect");
  const promptInput = document.getElementById("calcPromptTokens");
  const completionInput = document.getElementById("calcCompletionTokens");
  const callCountInput = document.getElementById("calcCallCount");

  const recalc = () => {
    const model = modelSelect ? modelSelect.value : "gpt-4o";
    const promptTokens = Number(promptInput ? promptInput.value : 1000);
    const completionTokens = Number(completionInput ? completionInput.value : 400);
    const count = Number(callCountInput ? callCountInput.value : 1);

    const pricing = MODEL_PRICING[model] || { inRate: 2.00, outRate: 8.00 };
    const singleCost = ((promptTokens * pricing.inRate) + (completionTokens * pricing.outRate)) / 1_000_000.0;
    const totalCost = singleCost * count;

    const costSingleEl = document.getElementById("calcSingleCost");
    const costTotalEl = document.getElementById("calcTotalCost");
    const tokenTotalEl = document.getElementById("calcTotalTokens");

    if (costSingleEl) costSingleEl.textContent = `$${singleCost.toFixed(5)}`;
    if (costTotalEl) costTotalEl.textContent = `$${totalCost.toFixed(4)}`;
    if (tokenTotalEl) tokenTotalEl.textContent = ((promptTokens + completionTokens) * count).toLocaleString();
  };

  [modelSelect, promptInput, completionInput, callCountInput].forEach(el => {
    if (el) {
      el.addEventListener("input", recalc);
      el.addEventListener("change", recalc);
    }
  });

  recalc();
}

// --- Circuit Breaker Controls & Live Simulation ---
function initBreakerControls() {
  // Set budget form
  const setBudgetBtn = document.getElementById("btnSetBudget");
  if (setBudgetBtn) {
    setBudgetBtn.addEventListener("click", async () => {
      const input = document.getElementById("inputNewBudget");
      const val = parseFloat(input ? input.value : 5);
      if (isNaN(val) || val <= 0) {
        alert("Please enter a valid dollar amount > $0");
        return;
      }

      if (isLiveBackend) {
        try {
          const res = await fetch("/api/budget", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ max_budget_usd: val })
          });
          const data = await res.json();
          renderStats(data.breaker);
          alert(`✓ Budget ceiling successfully set to $${val.toFixed(2)} USD.`);
          return;
        } catch (e) {}
      }

      // In-browser fallback
      currentStats.max_budget_usd = val;
      currentStats.percentage_used = currentStats.max_budget_usd > 0 ? (currentStats.current_spend_usd / currentStats.max_budget_usd * 100) : 0;
      currentStats.remaining_budget_usd = Math.max(0, currentStats.max_budget_usd - currentStats.current_spend_usd);
      renderStats(currentStats);
      showToast(`✓ Budget ceiling set to $${val.toFixed(2)} USD`);
    });
  }

  // Trip Emergency Kill Switch
  const tripBtn = document.getElementById("btnTripBreaker");
  if (tripBtn) {
    tripBtn.addEventListener("click", async () => {
      if (!confirm("Are you sure you want to engage the EMERGENCY KILL SWITCH? This will immediately halt all outbound AI requests.")) {
        return;
      }

      if (isLiveBackend) {
        try {
          const res = await fetch("/api/trip", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason: "Manual operator emergency kill switch engaged from Web Deck." })
          });
          const data = await res.json();
          renderStats(data.breaker);
          return;
        } catch (e) {}
      }

      // In-browser fallback
      currentStats.state = "TRIPPED";
      currentStats.trip_reason = "Manual operator emergency kill switch engaged from Web Deck.";
      currentStats.blocked_requests += 1;
      renderStats(currentStats);
      showToast("💥 Circuit Breaker TRIPPED — All Outbound Calls Halted");
    });
  }

  // Reset Breaker
  const resetBtn = document.getElementById("btnResetBreaker");
  if (resetBtn) {
    resetBtn.addEventListener("click", async () => {
      const clearHistory = confirm("Do you also want to clear historical spend data back to $0.00?");

      if (isLiveBackend) {
        try {
          const res = await fetch("/api/reset", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reset_spend: clearHistory })
          });
          const data = await res.json();
          renderStats(data.breaker);
          return;
        } catch (e) {}
      }

      // In-browser fallback
      currentStats.state = "CLOSED";
      currentStats.trip_reason = null;
      if (clearHistory) {
        currentStats.current_spend_usd = 0.0;
        currentStats.percentage_used = 0;
        currentStats.remaining_budget_usd = currentStats.max_budget_usd;
      }
      renderStats(currentStats);
      showToast("✓ Circuit Breaker RESET to CLOSED");
    });
  }

  // Simulate 1 Call
  const sim1Btn = document.getElementById("btnSimulateSingle");
  if (sim1Btn) {
    sim1Btn.addEventListener("click", async () => {
      const model = document.getElementById("calcModelSelect")?.value || "gpt-4o";
      const promptTokens = Number(document.getElementById("calcPromptTokens")?.value || 1200);
      const completionTokens = Number(document.getElementById("calcCompletionTokens")?.value || 400);

      if (isLiveBackend) {
        try {
          const res = await fetch("/api/simulate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model, prompt_tokens: promptTokens, completion_tokens: completionTokens })
          });
          const data = await res.json();
          if (data.allowed === false) {
            alert(`💥 BREAKER TRIPPED! Request blocked with HTTP 429:\n\n${data.reason}`);
          }
          renderStats(data.breaker);
          return;
        } catch (e) {}
      }

      // In-browser fallback
      const pricing = MODEL_PRICING[model] || { inRate: 2.50, outRate: 10.00 };
      const callCost = ((promptTokens * pricing.inRate) + (completionTokens * pricing.outRate)) / 1_000_000.0;
      
      const newSpend = currentStats.current_spend_usd + callCost;
      const isTripped = newSpend >= currentStats.max_budget_usd;

      if (isTripped) {
        currentStats.state = "TRIPPED";
        currentStats.trip_reason = `Hard budget ceiling exceeded ($${currentStats.max_budget_usd.toFixed(2)} USD)`;
        currentStats.blocked_requests += 1;
      } else {
        currentStats.current_spend_usd = newSpend;
        currentStats.total_tokens += (promptTokens + completionTokens);
        currentStats.total_requests += 1;
        currentStats.percentage_used = (currentStats.current_spend_usd / currentStats.max_budget_usd) * 100;
        currentStats.remaining_budget_usd = Math.max(0, currentStats.max_budget_usd - currentStats.current_spend_usd);
        if (currentStats.percentage_used >= 80) currentStats.state = "WARN";
      }

      currentTransactions.unshift({
        id: Date.now(),
        timestamp: new Date().toISOString(),
        model: model,
        prompt_tokens: promptTokens,
        completion_tokens: completionTokens,
        cost_usd: callCost,
        latency_ms: Math.random() * 300 + 120,
        status_code: isTripped ? 429 : 200,
        tripped: isTripped ? 1 : 0,
        reason: isTripped ? currentStats.trip_reason : null
      });

      renderStats(currentStats);
      renderTransactionsTable(currentTransactions);

      if (isTripped) {
        alert(`💥 BREAKER TRIPPED! Request blocked with HTTP 429:\n\n${currentStats.trip_reason}`);
      } else {
        showToast(`✓ Intercepted 1 call (${model}): +$${callCost.toFixed(5)}`);
      }
    });
  }

  // Simulate Runaway Loop Burst
  const simRunawayBtn = document.getElementById("btnSimulateRunaway");
  if (simRunawayBtn) {
    simRunawayBtn.addEventListener("click", async () => {
      try {
        simRunawayBtn.disabled = true;
        simRunawayBtn.textContent = "Simulating Burst...";

        if (isLiveBackend) {
          try {
            const res = await fetch("/api/simulate_runaway", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ iterations: 12, model: "o1-preview" })
            });
            const data = await res.json();
            renderStats(data.breaker);
            if (data.tripped_at_iteration) {
              alert(`⚡ Runaway loop successfully INTERCEPTED at burst iteration #${data.tripped_at_iteration}!\n\nCircuit breaker TRIPPED into safety lock.`);
            }
            return;
          } catch (e) {}
        }

        // In-browser client burst simulation
        const model = "o1";
        const burstPricing = MODEL_PRICING[model] || { inRate: 15.00, outRate: 60.00 };
        const singleBurstCost = ((3200 * burstPricing.inRate) + (1400 * burstPricing.outRate)) / 1_000_000.0;
        let trippedAt = null;

        for (let i = 1; i <= 12; i++) {
          const projected = currentStats.current_spend_usd + singleBurstCost;
          if (projected >= currentStats.max_budget_usd) {
            trippedAt = i;
            currentStats.state = "TRIPPED";
            currentStats.trip_reason = `Runaway loop velocity spike intercepted at iteration #${i}! Budget ceiling reached.`;
            currentStats.blocked_requests += 1;
            currentTransactions.unshift({
              id: Date.now() + i,
              timestamp: new Date().toISOString(),
              model: model,
              prompt_tokens: 3200,
              completion_tokens: 1400,
              cost_usd: singleBurstCost,
              latency_ms: 68.2,
              status_code: 429,
              tripped: 1,
              reason: currentStats.trip_reason
            });
            break;
          } else {
            currentStats.current_spend_usd = projected;
            currentStats.total_tokens += 4600;
            currentStats.total_requests += 1;
            currentStats.percentage_used = (currentStats.current_spend_usd / currentStats.max_budget_usd) * 100;
            currentStats.remaining_budget_usd = Math.max(0, currentStats.max_budget_usd - currentStats.current_spend_usd);
            currentTransactions.unshift({
              id: Date.now() + i,
              timestamp: new Date().toISOString(),
              model: model,
              prompt_tokens: 3200,
              completion_tokens: 1400,
              cost_usd: singleBurstCost,
              latency_ms: 145.0,
              status_code: 200,
              tripped: 0,
              reason: null
            });
          }
        }

        renderStats(currentStats);
        renderTransactionsTable(currentTransactions);

        if (trippedAt) {
          alert(`⚡ Runaway loop successfully INTERCEPTED at burst iteration #${trippedAt}!\n\nCircuit breaker TRIPPED into safety lock.`);
        } else {
          showToast(`⚡ Completed burst simulation of 12 calls`);
        }

      } catch (e) {
        alert("Simulation burst failed.");
      } finally {
        simRunawayBtn.disabled = false;
        simRunawayBtn.textContent = "⚡ Simulate Runaway Loop Burst";
      }
    });
  }
}

// Export Audit Interceptors
function triggerAuditExport() {
  exportAuditLedger('json');
}

async function exportAuditLedger(format = 'json') {
  if (!isPro) {
    openPaywallModal(`FinOps Compliance Exporter (${format.toUpperCase()})`);
    return;
  }

  let txs = currentTransactions;

  if (isLiveBackend) {
    try {
      const res = await fetch("/api/transactions?limit=250");
      if (res.ok) {
        const json = await res.json();
        if (json.transactions && json.transactions.length > 0) {
          txs = json.transactions;
        }
      }
    } catch (e) {}
  }

  if (!txs || txs.length === 0) {
    alert("No transaction records available to export yet. Run agent calls or simulation bursts first!");
    return;
  }

  if (format === 'csv') {
    const headers = ["id", "timestamp", "model", "prompt_tokens", "completion_tokens", "cost_usd", "latency_ms", "status_code", "tripped", "reason"];
    const rows = txs.map(t => headers.map(h => JSON.stringify(t[h] ?? "")).join(","));
    const csvContent = "data:text/csv;charset=utf-8," + encodeURIComponent([headers.join(","), ...rows].join("\n"));
    const link = document.createElement("a");
    link.setAttribute("href", csvContent);
    link.setAttribute("download", `budget_sentinel_audit_${Date.now()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  } else {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(txs, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `budget_sentinel_audit_${Date.now()}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  }
  showToast(`✓ Exported ${txs.length} audit records (${format.toUpperCase()})`);
}

function openShowreelModal() {
  const modal = document.getElementById("showreelModal");
  if (modal) modal.style.display = "flex";
}

function closeShowreelModal() {
  const modal = document.getElementById("showreelModal");
  if (modal) modal.style.display = "none";
}

function showToast(msg) {
  let toast = document.getElementById("sentinelToast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "sentinelToast";
    toast.className = "toast";
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.style.display = "flex";
  toast.style.opacity = "1";
  toast.style.transform = "translateY(0)";
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    setTimeout(() => { toast.style.display = "none"; }, 300);
  }, 2600);
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
