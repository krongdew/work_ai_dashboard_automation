import { useEffect, useRef } from 'react';

// The 3D engine (plain ES modules, Three.js from CDN) lives in ./city/.
// CityPage owns its React lifecycle: build on mount, dispose on unmount.
import { createScene } from '../city/scene.js';
import { createAnimator } from '../city/animation.js';
import { createUI } from '../city/ui.js';

export default function CityPage() {
  const stageRef = useRef(null);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return undefined;

    const canvas = stage.querySelector('#dfx-canvas');
    const overlay = stage.querySelector('#dfx-overlay');

    const view = createScene(canvas);

    const ui = createUI(overlay, {
      onPlay: () => { animator.startSimulation('main'); ui.setPlaying('running'); },
      onPause: () => {
        if (animator.isPlaying()) { animator.pauseSimulation(); ui.setPlaying('paused'); }
        else { animator.resumeSimulation(); ui.setPlaying('running'); }
      },
      onRestart: () => { animator.restartSimulation(); ui.setPlaying('running'); },
      onImprove: () => { animator.startImprove(); ui.setPlaying('running'); },
      onHome: () => view.resetCamera(),
      onDebug: (on) => view.setDebug(on),
      onPanelClose: () => animator.setSelected(null),
    });

    const animator = createAnimator(view, {
      onStatus: (id, name) => ui.setPanelStatus(id, name),
      onSimStep: (id, caption, step, total) => ui.setSimCaption(caption, step, total),
      onSimState: (state) => {
        if (state === 'idle') ui.setSimCaption('', 0, 0);
        if (state === 'done') ui.setPlaying('done');
      },
    });

    // ---- pointer handling ----
    let lastHover = null;
    const onMove = (e) => {
      const id = view.pick(e.clientX, e.clientY);
      if (id !== lastHover) { lastHover = id; animator.setHover(id); canvas.style.cursor = id ? 'pointer' : 'grab'; }
      if (id) ui.showTooltip(id, e.clientX, e.clientY); else ui.hideTooltip();
    };
    const onLeave = () => { lastHover = null; animator.setHover(null); ui.hideTooltip(); };
    let down = null;
    const onDown = (e) => { down = { x: e.clientX, y: e.clientY, t: performance.now() }; };
    const onUp = (e) => {
      if (!down) return;
      const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
      const quick = performance.now() - down.t < 500;
      down = null;
      if (moved > 6 || !quick) return;
      const id = view.pick(e.clientX, e.clientY);
      if (id) { animator.setSelected(id); ui.showPanel(id); }
      else { ui.hidePanel(); animator.setSelected(null); }
    };

    canvas.addEventListener('pointermove', onMove, { passive: true });
    canvas.addEventListener('pointerleave', onLeave, { passive: true });
    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointerup', onUp);

    const ro = new ResizeObserver(() => view.resize());
    ro.observe(canvas);

    animator.start();

    return () => {
      ro.disconnect();
      canvas.removeEventListener('pointermove', onMove);
      canvas.removeEventListener('pointerleave', onLeave);
      canvas.removeEventListener('pointerdown', onDown);
      canvas.removeEventListener('pointerup', onUp);
      animator.stop();
      view.dispose();
    };
  }, []);

  return (
    <div ref={stageRef} className="dfx-root">
      <style>{OVERLAY_CSS}</style>
      <div id="dfx-stage"><canvas id="dfx-canvas" /></div>
      <div id="dfx-overlay" />
    </div>
  );
}

// Overlay CSS, scoped under .dfx-root so it does not leak into the AntD app.
// The 3D stage fills the content area (not fixed) so the SPA header/sidebar stay.
const OVERLAY_CSS = `
.dfx-root{position:relative;width:100%;height:calc(100vh - 160px);min-height:520px;
  border-radius:16px;overflow:hidden;background:#F7F3E8;
  --cream:#F7F3E8;--ink:#3A3A4A;--muted:#6B6B7A;--mint:#9FD9C4;--teal:#7FC8C0;
  --peach:#F2B79A;--lav:#C3B6E6;--lav-deep:#9B86D6;--surface:#FFF;--surface-soft:#FBF8F0;
  --border:#E6E0CF;--shadow:0 10px 30px rgba(80,80,100,.14);--radius:16px}
.dfx-root #dfx-stage{position:absolute;inset:0}
.dfx-root #dfx-canvas{display:block;width:100%;height:100%;cursor:grab}
.dfx-root #dfx-canvas:active{cursor:grabbing}
.dfx-root #dfx-overlay{position:absolute;inset:0;pointer-events:none}
.dfx-root #dfx-overlay>*{pointer-events:auto}
.dfx-root .dfx-header{position:absolute;top:0;left:0;right:0;display:flex;align-items:center;
  justify-content:space-between;gap:12px;padding:12px 14px;flex-wrap:wrap}
.dfx-root .dfx-brand{display:flex;align-items:center;gap:10px;font-weight:800;font-size:1rem;
  background:var(--surface);border:1px solid var(--border);border-radius:999px;padding:7px 14px;box-shadow:var(--shadow)}
.dfx-root .dfx-logo{font-size:1.1rem}
.dfx-root .dfx-demo{font-size:.64rem;font-weight:700;color:#8a6d00;background:#FFF2C9;
  border:1px solid #F3DF9B;border-radius:999px;padding:3px 8px;margin-left:4px}
.dfx-root .dfx-legend{display:flex;gap:8px;flex-wrap:wrap;background:var(--surface);
  border:1px solid var(--border);border-radius:999px;padding:6px 11px;box-shadow:var(--shadow)}
.dfx-root .dfx-chip{display:inline-flex;align-items:center;gap:5px;font-size:.7rem;color:var(--muted);font-weight:600}
.dfx-root .dfx-chip i{width:9px;height:9px;border-radius:50%;display:inline-block}
.dfx-root .dfx-controls{position:absolute;left:14px;bottom:60px;display:flex;gap:8px;flex-wrap:wrap;max-width:62%}
.dfx-root .dfx-btn{font:inherit;font-weight:700;font-size:.8rem;border:1px solid var(--border);
  background:var(--surface);color:var(--ink);border-radius:12px;padding:8px 13px;cursor:pointer;
  box-shadow:var(--shadow);transition:transform .12s ease,background .12s ease}
.dfx-root .dfx-btn:hover{transform:translateY(-2px)}
.dfx-root .dfx-btn.primary{background:var(--mint);border-color:#7cc7ae}
.dfx-root .dfx-btn.improve{background:var(--lav);border-color:var(--lav-deep);color:#3a2f5e}
.dfx-root .dfx-btn.ghost{background:var(--surface-soft)}
.dfx-root .dfx-controls[data-state="idle"] #dfx-pause{opacity:.5}
.dfx-root .dfx-controls[data-state="paused"] #dfx-pause{background:var(--peach);border-color:#e39b78}
.dfx-root .dfx-simbar-wrap{position:absolute;left:14px;right:14px;bottom:16px;display:flex;align-items:center;gap:12px}
.dfx-root .dfx-sim-caption{font-size:.8rem;font-weight:700;color:var(--ink);background:var(--surface);
  border:1px solid var(--border);border-radius:999px;padding:6px 13px;box-shadow:var(--shadow);white-space:nowrap}
.dfx-root .dfx-sim-bar{flex:1;height:8px;background:var(--surface);border:1px solid var(--border);
  border-radius:999px;overflow:hidden;box-shadow:var(--shadow)}
.dfx-root .dfx-sim-bar>i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--mint),var(--teal));transition:width .4s ease}
.dfx-root .dfx-panel{position:absolute;top:60px;right:14px;width:min(360px,80%);max-height:calc(100% - 150px);
  overflow:auto;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:20px;transform:translateX(120%);opacity:0;
  transition:transform .32s cubic-bezier(.2,.8,.2,1),opacity .32s ease}
.dfx-root .dfx-panel.show{transform:translateX(0);opacity:1}
.dfx-root .dfx-panel-close{position:absolute;top:12px;right:12px;border:none;background:var(--surface-soft);
  width:30px;height:30px;border-radius:50%;cursor:pointer;font-size:.9rem;color:var(--muted)}
.dfx-root .dfx-panel-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding-right:32px}
.dfx-root .dfx-panel-badge{display:grid;place-items:center;width:30px;height:30px;border-radius:9px;background:var(--lav);color:#3a2f5e;font-weight:800}
.dfx-root .dfx-panel-head h2{margin:0;font-size:1.1rem}
.dfx-root .dfx-panel-tag{font-size:.62rem;font-weight:800;letter-spacing:.04em;background:#EEF6F1;color:#2f7d66;border:1px solid #Bfe3d4;border-radius:999px;padding:3px 8px}
.dfx-root .dfx-panel-status{display:inline-flex;align-items:center;gap:7px;margin:12px 0 2px;font-weight:700;font-size:.82rem}
.dfx-root .dfx-panel-status i{width:11px;height:11px;border-radius:50%;display:inline-block}
.dfx-root .dfx-panel-heading{margin:10px 0 8px;font-weight:700;color:var(--ink)}
.dfx-root .dfx-panel-list{margin:0;padding-left:18px;color:var(--muted);line-height:1.6;font-size:.85rem}
.dfx-root .dfx-panel-list li{margin:4px 0}
.dfx-root .dfx-tooltip{position:fixed;z-index:1200;pointer-events:none;background:var(--ink);color:#fff;
  font-size:.74rem;font-weight:600;padding:6px 10px;border-radius:8px;max-width:280px;opacity:0;transform:translateY(4px);transition:opacity .12s ease}
.dfx-root .dfx-tooltip.show{opacity:.96;transform:none}
@media (max-width:720px){
  .dfx-root{height:calc(100vh - 150px)}
  .dfx-root .dfx-legend{display:none}
  .dfx-root .dfx-controls{left:8px;right:8px;bottom:10px;max-width:none;justify-content:center}
  .dfx-root .dfx-btn{font-size:.74rem;padding:7px 10px}
  .dfx-root .dfx-simbar-wrap{display:none}
  .dfx-root .dfx-panel{top:auto;left:0;right:0;bottom:0;width:100%;max-height:60%;border-radius:18px 18px 0 0;transform:translateY(110%)}
  .dfx-root .dfx-panel.show{transform:translateY(0)}
}
@media (prefers-reduced-motion:reduce){
  .dfx-root .dfx-btn,.dfx-root .dfx-panel,.dfx-root .dfx-sim-bar>i,.dfx-root .dfx-tooltip{transition:none !important}
}
`;
