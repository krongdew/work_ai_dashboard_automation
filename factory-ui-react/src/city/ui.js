// ============================================================================
// UI overlay — HTML labels, tooltip, detail panel / bottom sheet, controls.
// All DOM here; 3D never writes text into the canvas.
// ============================================================================
import { STATIONS, byId, STATUS } from './config.js';

export function createUI(root, handlers) {
  root.innerHTML = TEMPLATE;
  const $ = (sel) => root.querySelector(sel);

  const el = {
    tooltip: $('#dfx-tooltip'),
    panel: $('#dfx-panel'),
    panelClose: $('#dfx-panel-close'),
    panelBadge: $('#dfx-panel-badge'),
    panelTitle: $('#dfx-panel-title'),
    panelTag: $('#dfx-panel-tag'),
    panelHeading: $('#dfx-panel-heading'),
    panelList: $('#dfx-panel-list'),
    panelStatus: $('#dfx-panel-status'),
    simCaption: $('#dfx-sim-caption'),
    simBar: $('#dfx-sim-bar > i'),
    legend: $('#dfx-legend'),
    btnPlay: $('#dfx-play'),
    btnPause: $('#dfx-pause'),
    btnRestart: $('#dfx-restart'),
    btnImprove: $('#dfx-improve'),
    btnHome: $('#dfx-home'),
    btnDebug: $('#dfx-debug'),
  };

  // legend chips
  el.legend.innerHTML = Object.entries(STATUS).map(([k, s]) =>
    `<span class="dfx-chip"><i style="background:${s.color}"></i>${s.icon} ${s.label}</span>`).join('');

  // buttons
  el.btnPlay.addEventListener('click', () => handlers.onPlay?.());
  el.btnPause.addEventListener('click', () => handlers.onPause?.());
  el.btnRestart.addEventListener('click', () => handlers.onRestart?.());
  el.btnImprove.addEventListener('click', () => handlers.onImprove?.());
  el.btnHome.addEventListener('click', () => handlers.onHome?.());
  el.btnDebug?.addEventListener('click', () => {
    const on = el.btnDebug.classList.toggle('active');
    handlers.onDebug?.(on);
  });
  el.panelClose.addEventListener('click', () => hidePanel());

  function showTooltip(id, x, y) {
    const s = byId[id];
    if (!s) return;
    el.tooltip.textContent = `${s.label} — ${s.details.heading}`;
    el.tooltip.style.left = `${x + 14}px`;
    el.tooltip.style.top = `${y + 14}px`;
    el.tooltip.classList.add('show');
  }
  function hideTooltip() { el.tooltip.classList.remove('show'); }

  function showPanel(id) {
    const s = byId[id];
    if (!s) return;
    el.panelBadge.textContent = s.badge;
    el.panelTitle.textContent = s.title;
    el.panelHeading.textContent = s.details.heading;
    el.panelList.innerHTML = s.details.bullets.map((b) => `<li>${escapeHtml(b)}</li>`).join('');
    if (s.details.tag) { el.panelTag.textContent = s.details.tag; el.panelTag.style.display = ''; }
    else { el.panelTag.style.display = 'none'; }
    el.panel.dataset.station = id;
    setPanelStatus(id, currentStatus[id] || 'idle');
    el.panel.classList.add('show');
  }
  function hidePanel() { el.panel.classList.remove('show'); el.panel.dataset.station = ''; handlers.onPanelClose?.(); }

  const currentStatus = {};
  function setPanelStatus(id, name) {
    currentStatus[id] = name;
    if (String(el.panel.dataset.station) !== String(id)) return;
    const s = STATUS[name];
    el.panelStatus.innerHTML = `<i style="background:${s.color}"></i>${s.icon} ${s.label}`;
  }

  function setSimCaption(text, step, total) {
    el.simCaption.textContent = text || 'พร้อมจำลอง Workflow';
    const pct = total ? Math.round((step / total) * 100) : 0;
    el.simBar.style.width = `${pct}%`;
  }

  function setPlaying(state) {
    root.querySelector('#dfx-controls').dataset.state = state;
  }

  return {
    showTooltip, hideTooltip, showPanel, hidePanel,
    setPanelStatus, setSimCaption, setPlaying,
    selectedStation: () => Number(el.panel.dataset.station) || null,
  };
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

const TEMPLATE = `
<div id="dfx-tooltip" class="dfx-tooltip"></div>

<header class="dfx-header">
  <div class="dfx-brand"><span class="dfx-logo">🏭</span> Dashboard Factory
    <span class="dfx-demo">โหมดสาธิต · ข้อมูลจำลอง</span>
  </div>
  <div id="dfx-legend" class="dfx-legend"></div>
</header>

<div id="dfx-controls" class="dfx-controls" data-state="idle">
  <button id="dfx-play"    class="dfx-btn primary">▶ จำลอง Workflow</button>
  <button id="dfx-pause"   class="dfx-btn">⏸ หยุดชั่วคราว</button>
  <button id="dfx-restart" class="dfx-btn">↻ เริ่มใหม่</button>
  <button id="dfx-improve" class="dfx-btn improve">✦ จำลอง Improve (6→4→5→6)</button>
  <button id="dfx-home"    class="dfx-btn ghost">⌂ คืนมุมกล้อง</button>
  <button id="dfx-debug"   class="dfx-btn ghost">⚙ Debug Nav</button>
</div>

<div class="dfx-simbar-wrap">
  <div id="dfx-sim-caption" class="dfx-sim-caption">พร้อมจำลอง Workflow</div>
  <div id="dfx-sim-bar" class="dfx-sim-bar"><i></i></div>
</div>

<aside id="dfx-panel" class="dfx-panel">
  <button id="dfx-panel-close" class="dfx-panel-close" aria-label="ปิด">✕</button>
  <div class="dfx-panel-head">
    <span id="dfx-panel-badge" class="dfx-panel-badge">1</span>
    <h2 id="dfx-panel-title">สถานี</h2>
    <span id="dfx-panel-tag" class="dfx-panel-tag"></span>
  </div>
  <div id="dfx-panel-status" class="dfx-panel-status"></div>
  <p id="dfx-panel-heading" class="dfx-panel-heading"></p>
  <ul id="dfx-panel-list" class="dfx-panel-list"></ul>
</aside>
`;

// ---------------------------------------------------------------------------
// Backend adapter — the ONLY seam to real endpoints later.
// Everything here is a clearly-labelled stub returning demo data. It does not
// call any endpoint and must not pretend real work happened. Replace each
// method's body when wiring the real Flask API.
// ---------------------------------------------------------------------------
export const BackendAdapter = {
  mode: 'demo',
  async listProjects() { return { demo: true, projects: [] }; },
  async getProfile(/* name */) { return { demo: true, profile: null }; },
  async getSpec(/* name */) { return { demo: true, spec: null }; },
  async runImprove(/* name, instruction */) { return { demo: true, note: 'stub — ไม่เรียก backend จริง' }; },
};
