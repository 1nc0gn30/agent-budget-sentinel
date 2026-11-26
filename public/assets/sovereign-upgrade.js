/**
 * Agent Budget Sentinel — XSS-Safe Presets, Live Probe & MCP Quick Drawer
 * Pure DOM API (createElement + textContent) — Zero innerHTML sinks, zero 404 videos, >= 44px touch targets.
 * Engineered by Neal Frazier Tech (@1nc0gn30) • NullAI Platform.
 */
(function () {
  'use strict';
  if (window.__SENTINEL_UTILITY_DRAWER_LOADED__) return;
  window.__SENTINEL_UTILITY_DRAWER_LOADED__ = true;

  function el(tag, attrs, text) {
    const node = document.createElement(tag);
    if (attrs) {
      Object.entries(attrs).forEach(([k, v]) => {
        if (k === 'className') node.className = v;
        else if (k === 'style') node.style.cssText = v;
        else node.setAttribute(k, v);
      });
    }
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function mountBar() {
    if (document.body.classList.contains('embed-mode')) return;
    const old = document.getElementById('zoth-sovereign-a100-bar');
    if (old) old.remove();

    const bar = el('div', {
      id: 'zoth-sovereign-a100-bar',
      style:
        'position:relative;margin:18px auto 0 auto;display:flex;align-items:center;justify-content:center;' +
        'gap:10px;padding:12px 16px;border-radius:14px;background:var(--bg-card);' +
        'border:1px solid var(--border-card);font-family:var(--font-mono);font-size:12px;' +
        'color:var(--text-main);flex-wrap:wrap;max-width:100%;box-sizing:border-box;'
    });

    const title = el('span', { style: 'font-weight:700;color:var(--gold);letter-spacing:0.04em;' }, '⚡ DIAGNOSTICS & MCP');
    const btnPresets = el('button', { type: 'button', className: 'btn btn-outline' }, '⚡ Domain Presets & Live Probe');
    const btnMcp = el('button', { type: 'button', className: 'btn btn-outline' }, '🔌 MCP Stdio Config');

    btnPresets.addEventListener('click', () => openDrawer('presets'));
    btnMcp.addEventListener('click', () => openDrawer('mcp'));

    bar.append(title, btnPresets, btnMcp);

    const footer = document.querySelector('footer');
    if (footer && footer.parentNode) {
      footer.parentNode.insertBefore(bar, footer);
    } else {
      document.body.appendChild(bar);
    }
  }

  async function openDrawer(tab) {
    const existing = document.getElementById('sentinel-utility-modal');
    if (existing) existing.remove();

    const overlay = el('div', {
      id: 'sentinel-utility-modal',
      className: 'modal-backdrop',
      role: 'dialog',
      'aria-modal': 'true',
      style: 'display:flex;'
    });

    const card = el('div', { className: 'modal-card', style: 'max-width:780px;max-height:86vh;overflow-y:auto;' });

    const header = el('div', {
      style: 'display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid var(--border-subtle);'
    });
    const tabs = el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;' });
    const tPresets = el('button', {
      type: 'button',
      className: tab === 'presets' ? 'btn btn-primary' : 'btn btn-outline'
    }, '⚡ Presets & Probe');
    const tMcp = el('button', {
      type: 'button',
      className: tab === 'mcp' ? 'btn btn-primary' : 'btn btn-outline'
    }, '🔌 MCP Stdio Server');
    const closeBtn = el('button', {
      type: 'button',
      className: 'btn btn-outline',
      'aria-label': 'Close diagnostics dialog'
    }, '✕ Close');

    tPresets.addEventListener('click', () => openDrawer('presets'));
    tMcp.addEventListener('click', () => openDrawer('mcp'));
    closeBtn.addEventListener('click', () => overlay.remove());
    overlay.addEventListener('click', (ev) => { if (ev.target === overlay) overlay.remove(); });

    tabs.append(tPresets, tMcp);
    header.append(tabs, closeBtn);
    card.appendChild(header);

    if (tab === 'mcp') {
      card.appendChild(el('p', { style: 'font-size:0.86rem;color:var(--text-muted);margin-bottom:10px;' },
        'Connect Claude Code, Codex, AGY, or Hermes directly to Agent Budget Sentinel over zero-dependency stdio JSON-RPC 2.0:'));
      const pre = el('pre', { className: 'code-snippet', style: 'white-space:pre-wrap;' }, JSON.stringify({
        mcpServers: {
          'agent-budget-sentinel': {
            command: 'agent-budget',
            args: ['mcp', '--host', '127.0.0.1', '--port', '8110']
          }
        }
      }, null, 2));
      const toolsNote = el('p', { style: 'font-size:0.82rem;color:var(--text-muted);margin-top:12px;' },
        'Exposed MCP tools: budget_circuit_breaker_status, budget_set_ceiling, budget_trip, budget_reset, budget_estimate_cost.');
      card.append(pre, toolsNote);
    } else {
      const t0 = performance.now();
      let healthText = 'Offline — static client mode';
      try {
        const r = await fetch('/api/health', { cache: 'no-store' });
        if (r.ok) {
          const h = await r.json();
          healthText = `ONLINE v${h.version || '2.6.0'} · state=${h.breaker_state || 'CLOSED'} · :${h.web_port || 8110}/:${h.proxy_port || 8111}`;
        }
      } catch (_e) {}
      const rtt = (performance.now() - t0).toFixed(2);

      const probeBox = el('div', {
        style: 'background:var(--bg-card-subtle);border:1px solid var(--border-subtle);border-radius:10px;padding:12px 14px;margin-bottom:14px;'
      });
      probeBox.append(
        el('div', { style: 'font-size:11px;color:var(--text-dim);font-family:var(--font-mono);' }, 'LIVE /api/health PROBE'),
        el('div', { style: 'font-size:18px;font-weight:800;color:var(--gold);font-family:var(--font-mono);margin:2px 0;' }, `${rtt} ms`),
        el('div', { style: 'font-size:12px;color:var(--emerald);font-family:var(--font-mono);' }, healthText)
      );
      card.appendChild(probeBox);

      let presets = [];
      try {
        const pr = await fetch('/assets/gpu-domain-presets.json', { cache: 'no-store' });
        if (pr.ok) {
          const data = await pr.json();
          presets = Array.isArray(data.presets) ? data.presets : [];
        }
      } catch (_e) {}

      const list = el('div', { style: 'display:grid;gap:10px;' });
      if (presets.length === 0) {
        list.appendChild(el('div', { style: 'font-size:12px;color:var(--text-muted);' }, 'No domain preset vectors found.'));
      } else {
        presets.forEach((p, idx) => {
          const item = el('div', {
            style: 'background:var(--bg-card-subtle);padding:12px;border-radius:10px;border:1px solid var(--border-subtle);'
          });
          const top = el('div', { style: 'display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap;' });
          top.append(
            el('strong', { style: 'color:var(--text-strong);font-size:13px;' }, `${idx + 1}. ${p.name || 'Domain Preset'}`),
            el('span', { style: 'font-size:11px;color:var(--gold);font-family:var(--font-mono);' }, p.expected_metric || '')
          );
          const desc = el('div', { style: 'font-size:12px;color:var(--text-muted);margin-bottom:8px;' }, p.description || '');
          const code = el('code', {
            style: 'display:block;background:var(--bg-code);padding:8px 10px;border-radius:6px;color:var(--emerald);font-size:11px;overflow-x:auto;font-family:var(--font-mono);'
          }, p.payload || '');
          item.append(top, desc, code);
          list.appendChild(item);
        });
      }
      card.appendChild(list);
    }

    overlay.appendChild(card);
    document.body.appendChild(overlay);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mountBar);
  } else {
    mountBar();
  }
})();
