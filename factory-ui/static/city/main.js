// ============================================================================
// Entry — wire scene + animation + UI together and own the event lifecycle.
// ============================================================================
import { createScene } from './scene.js';
import { createAnimator } from './animation.js';
import { createUI } from './ui.js';

const canvas = document.getElementById('dfx-canvas');
const overlay = document.getElementById('dfx-overlay');

const view = createScene(canvas);

const ui = createUI(overlay, {
  onPlay: () => { animator.startSimulation('main'); ui.setPlaying('running'); },
  onPause: () => { if (animator.isPlaying()) { animator.pauseSimulation(); ui.setPlaying('paused'); } else { animator.resumeSimulation(); ui.setPlaying('running'); } },
  onRestart: () => { animator.restartSimulation(); ui.setPlaying('running'); },
  onImprove: () => { animator.startImprove(); ui.setPlaying('running'); },
  onHome: () => view.resetCamera(),
  onDebug: (on) => view.setDebug(on),
  onPanelClose: () => { animator.setSelected(null); },
});

const animator = createAnimator(view, {
  onStatus: (id, name) => ui.setPanelStatus(id, name),
  onSimStep: (id, caption, step, total) => ui.setSimCaption(caption, step, total),
  onSimState: (state) => { if (state === 'idle') ui.setSimCaption('', 0, 0); if (state === 'done') ui.setPlaying('done'); },
});

// ---- pointer handling -------------------------------------------------------
let lastHover = null;
function onPointerMove(e) {
  const id = view.pick(e.clientX, e.clientY);
  if (id !== lastHover) {
    lastHover = id;
    animator.setHover(id);
    canvas.style.cursor = id ? 'pointer' : 'grab';
  }
  if (id) ui.showTooltip(id, e.clientX, e.clientY); else ui.hideTooltip();
}
function onPointerLeave() { lastHover = null; animator.setHover(null); ui.hideTooltip(); }

// distinguish click from drag (orbit)
let down = null;
function onPointerDown(e) { down = { x: e.clientX, y: e.clientY, t: performance.now() }; }
function onPointerUp(e) {
  if (!down) return;
  const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
  const quick = performance.now() - down.t < 500;
  down = null;
  if (moved > 6 || !quick) return; // was an orbit drag
  const id = view.pick(e.clientX, e.clientY);
  if (id) { animator.setSelected(id); ui.showPanel(id); }
  else { ui.hidePanel(); animator.setSelected(null); }
}

canvas.addEventListener('pointermove', onPointerMove, { passive: true });
canvas.addEventListener('pointerleave', onPointerLeave, { passive: true });
canvas.addEventListener('pointerdown', onPointerDown);
canvas.addEventListener('pointerup', onPointerUp);

// ---- resize -----------------------------------------------------------------
const ro = new ResizeObserver(() => view.resize());
ro.observe(canvas);
window.addEventListener('resize', () => view.resize());

// ---- start ------------------------------------------------------------------
animator.start();

// ---- teardown (dispose geometries/materials/controls/loop) -----------------
function teardown() {
  ro.disconnect();
  canvas.removeEventListener('pointermove', onPointerMove);
  canvas.removeEventListener('pointerleave', onPointerLeave);
  canvas.removeEventListener('pointerdown', onPointerDown);
  canvas.removeEventListener('pointerup', onPointerUp);
  animator.stop();
  view.dispose();
}
window.addEventListener('pagehide', teardown, { once: true });
window.addEventListener('beforeunload', teardown, { once: true });

// expose for debugging / future embedding
window.DashboardFactory = { view, animator, ui, teardown };
