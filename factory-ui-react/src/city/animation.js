// ============================================================================
// Animation — render loop + hover easing + workflow simulation state machine.
// The simulation moves a cargo box along the configured routes and drives each
// station's status (idle → running → success/warning). It NEVER talks to a
// backend or claims real work succeeded; it is clearly a demo (see ui banner).
// ============================================================================
import * as THREE from 'three';
import { MAIN_ROUTE, IMPROVE_ROUTE, EDGES, SIM_CAPTIONS, IMPROVE_CAPTIONS, STATUS, byId } from './config.js';
import { findPath } from './navigation.js';

const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export function createAnimator(view, hooks = {}) {
  const { renderer, scene, camera, controls, buildings, buddies, cargo, edgePaths, anchors, graph } = view;
  const clock = new THREE.Clock();

  let hoverId = null;
  let selectedId = null;
  const raiseState = {}; // id -> current raise height

  // ============================================================================
  // Delivery lifecycle state machine (per the spec).
  // States: hiddenInside → (sender) walkToReceiver → knocking → openingToReceive
  //   → comingOut → receiving → enteringToWork → workingHidden → openingToDeliver
  //   → delivering → returning → hiddenInside
  // Visibility changes ONLY on state transitions. No straight-through fallback:
  // if the nav graph yields no path the character stops and debug reports it.
  // ============================================================================
  let sim = null;
  const SPEED = prefersReduced ? 9999 : 2.2;   // world units / second walking
  const DUR = { knock: 1.6, doorOpen: 0.7, handoff: 1.1, doorClose: 0.5, work: 1.4, pause: 0.3 };

  function setStatus(id, name) {
    const s = STATUS[name];
    buildings[id].setStatus(name, s.color);
    hooks.onStatus?.(id, name);
  }
  function hideBuddy(b) { b.root.visible = false; }
  function showBuddyAt(b, v) { b.root.position.copy(v); b.root.visible = true; }

  function resetStatuses() {
    for (const id of Object.keys(buildings)) { setStatus(Number(id), 'idle'); buildings[id].setDoor(0); }
    for (const id in buddies) {
      const b = buddies[id];
      b.root.position.copy(b.anchors.indoorPoint);
      b.root.rotation.y = 0;
      b.root.visible = false;     // all hidden inside
      b.pose('idle');
    }
  }

  function captionFor(kind, id) {
    return (kind === 'improve' ? IMPROVE_CAPTIONS[id] : SIM_CAPTIONS[id]) || '';
  }

  // Build the concrete waypoint list for a delivery: sender indoor → door →
  // approach → graph path → receiver knockPoint. Returns null if unroutable.
  function routeWaypoints(fromId, toId) {
    const sa = anchors[fromId], ra = anchors[toId];
    const graphPath = findPath(graph, `A${fromId}`, `K${toId}`);
    if (!graphPath) return null;
    return [sa.indoorPoint.clone(), sa.doorThreshold.clone(), sa.approach.clone(), ...graphPath];
  }

  function startSimulation(kind = 'main') {
    const route = kind === 'improve' ? IMPROVE_ROUTE.slice() : MAIN_ROUTE.slice();
    resetStatuses();
    cargo.visible = false;
    sim = { route, kind, i: 0, state: 'begin', t: 0, playing: true, done: false, error: null, path: null, seg: 0, segT: 0 };
    setStatus(route[0], 'running');
    hooks.onSimStep?.(route[0], captionFor(kind, route[0]), 0, route.length);
  }

  function pauseSimulation() { if (sim) sim.playing = false; hooks.onSimState?.('paused'); }
  function resumeSimulation() { if (sim && !sim.done) { sim.playing = true; hooks.onSimState?.('running'); } }
  function restartSimulation() { stopSimulation(); startSimulation('main'); hooks.onSimState?.('running'); }
  function stopSimulation() {
    sim = null; cargo.visible = false; resetStatuses();
    hooks.onSimState?.('idle'); hooks.onSimStep?.(null, '', 0, 0);
  }

  function statusDone(id) { return id === 5 ? 'warning' : 'success'; }

  // walk a buddy along sim.path; returns true when the end is reached
  function walkAlong(b, dt, pose = 'carry') {
    const path = sim.path;
    if (!path || sim.seg >= path.length - 1) return true;
    const a = path[sim.seg], c = path[sim.seg + 1];
    const segLen = a.distanceTo(c) || 1e-6;
    sim.segT += (dt * SPEED) / segLen;
    const p = a.clone().lerp(c, Math.min(sim.segT, 1));
    b.moveTo(p.x, p.z); b.faceTo(c.x, c.z);
    b.pose(pose, clock.elapsedTime);
    if (sim.segT >= 1) { sim.seg += 1; sim.segT = 0; }
    return sim.seg >= path.length - 1;
  }

  function advanceSim(dt) {
    if (!sim || !sim.playing || sim.done || sim.error) return;
    const { route } = sim;
    const from = route[sim.i], to = route[sim.i + 1];
    if (to == null) { finishSim(); return; }
    const sender = buddies[from], receiver = buddies[to];
    const sBldg = buildings[from], rBldg = buildings[to];
    const el = clock.elapsedTime;

    switch (sim.state) {
      case 'begin': {
        // sender leaves its own house: open door, appear at indoor, path out
        sim.path = routeWaypoints(from, to);
        if (!sim.path) { sim.error = `no route ${from}→${to}`; hooks.onSimState?.('error', sim.error); return; }
        sim.seg = 0; sim.segT = 0; sim.t = 0;
        sBldg.setDoor(1);
        showBuddyAt(sender, sender.anchors.indoorPoint);
        sim.state = 'walkToReceiver';
        break;
      }
      case 'walkToReceiver': {
        // close sender's own door once it has stepped out past the threshold
        if (sim.seg >= 2) sBldg.setDoor(0);
        const done = walkAlong(sender, dt, 'carry');
        if (done) { sender.faceTo(anchors[to].doorThreshold.x, anchors[to].doorThreshold.z); sim.state = 'knocking'; sim.t = 0; }
        break;
      }
      case 'knocking': {
        sim.t += dt; sender.pose('knock', sim.t);
        if (sim.t >= DUR.knock) { sim.state = 'pauseBeforeOpen'; sim.t = 0; }
        break;
      }
      case 'pauseBeforeOpen': {
        sim.t += dt; sender.pose('idle', el);
        if (sim.t >= DUR.pause) { sim.state = 'openingToReceive'; sim.t = 0; receiver.root.position.copy(receiver.anchors.indoorPoint); }
        break;
      }
      case 'openingToReceive': {
        sim.t += dt; rBldg.setDoor(Math.min(sim.t / DUR.doorOpen, 1));
        if (sim.t >= DUR.doorOpen) {
          sim.state = 'comingOut'; sim.t = 0;
          receiver.root.visible = true;                 // appear only now, at indoor
          sim.rPath = [receiver.anchors.indoorPoint.clone(), receiver.anchors.doorThreshold.clone(), receiver.anchors.receiverPoint.clone()];
          sim.rSeg = 0; sim.rSegT = 0;
        }
        break;
      }
      case 'comingOut': {
        const path = sim.rPath;
        const a = path[sim.rSeg], c = path[sim.rSeg + 1];
        const segLen = a.distanceTo(c) || 1e-6;
        sim.rSegT += (dt * SPEED) / segLen;
        const p = a.clone().lerp(c, Math.min(sim.rSegT, 1));
        receiver.moveTo(p.x, p.z); receiver.faceTo(c.x, c.z); receiver.pose('walk', el);
        if (sim.rSegT >= 1) { sim.rSeg += 1; sim.rSegT = 0; }
        if (sim.rSeg >= path.length - 1) {
          receiver.moveTo(receiver.anchors.receiverPoint.x, receiver.anchors.receiverPoint.z);
          receiver.faceTo(sender.root.position.x, sender.root.position.z);
          sender.faceTo(receiver.root.position.x, receiver.root.position.z);
          sim.state = 'receiving'; sim.t = 0;
        }
        break;
      }
      case 'receiving': {
        sim.t += dt; sender.pose('receive', sim.t); receiver.pose('receive', sim.t);
        if (sim.t >= DUR.handoff) {
          sim.state = 'enteringToWork'; sim.t = 0;
          sim.rPath = [receiver.anchors.receiverPoint.clone(), receiver.anchors.doorThreshold.clone(), receiver.anchors.indoorPoint.clone()];
          sim.rSeg = 0; sim.rSegT = 0;
          // sender starts walking home: reverse its path
          sim.path = [...sim.path].reverse(); sim.seg = 0; sim.segT = 0;
        }
        break;
      }
      case 'enteringToWork': {
        // receiver carries the item back inside; sender walks home concurrently
        const path = sim.rPath;
        const a = path[sim.rSeg], c = path[sim.rSeg + 1];
        const segLen = a.distanceTo(c) || 1e-6;
        sim.rSegT += (dt * SPEED) / segLen;
        const p = a.clone().lerp(c, Math.min(sim.rSegT, 1));
        receiver.moveTo(p.x, p.z); receiver.faceTo(c.x, c.z); receiver.pose('carry', el);
        if (sim.rSegT >= 1) { sim.rSeg += 1; sim.rSegT = 0; }
        // sender returning
        if (sim.path && sim.seg < sim.path.length - 1) walkAlong(sender, dt, 'walk');
        else { hideBuddy(sender); sBldg.setDoor(0); }
        if (sim.rSeg >= path.length - 1) {
          hideBuddy(receiver); rBldg.setDoor(0);   // receiver fully inside, hide + close
          setStatus(from, statusDone(from));
          sim.state = 'workingHidden'; sim.t = 0;
          hooks.onSimStep?.(to, captionFor(sim.kind, to), sim.i + 1, route.length);
        }
        break;
      }
      case 'workingHidden': {
        sim.t += dt; // working inside; building gem shows 'running'
        if (sim.t >= DUR.work) { sim.i += 1; sim.state = 'begin'; sim.t = 0; }
        break;
      }
      default: break;
    }
  }

  function finishSim() {
    const last = sim.route[sim.route.length - 1];
    setStatus(last, 'success');
    // final buddy briefly appears to celebrate, then hides
    const b = buddies[last];
    buildings[last].setDoor(1);
    showBuddyAt(b, b.anchors.receiverPoint); b.pose('success', clock.elapsedTime);
    sim.done = true; sim.playing = false;
    cargo.visible = false;
    hooks.onSimStep?.(last, captionFor(sim.kind, last), sim.route.length, sim.route.length);
    hooks.onSimState?.('done', sim.kind);
  }

  // ---- hover / selection --------------------------------------------------
  function setHover(id) { hoverId = id; }
  function setSelected(id) { selectedId = id; }

  // ---- main loop ----------------------------------------------------------
  let raf = 0;
  function frame() {
    const dt = Math.min(clock.getDelta(), 0.05);
    controls.update();

    // hover raise easing
    for (const id of Object.keys(buildings)) {
      const nid = Number(id);
      const target = (nid === hoverId ? 0.6 : 0) + (nid === selectedId ? 0.25 : 0);
      const cur = raiseState[nid] || 0;
      const next = prefersReduced ? target : cur + (target - cur) * Math.min(dt * 10, 1);
      raiseState[nid] = next;
      buildings[nid].raise(next);
    }

    // gentle bob of the active (running) building
    if (sim && sim.playing && !prefersReduced) {
      const active = sim.route[sim.i];
      const b = buildings[active];
      if (b) b.group.position.y = (raiseState[active] || 0) + Math.sin(clock.elapsedTime * 6) * 0.06;
    }

    advanceSim(dt);

    // buddy idle animations — only visible, non-active buddies idle;
    // the sim pose-drives the current sender/receiver.
    if (buddies && !prefersReduced) {
      const active = sim && sim.playing ? new Set([sim.route[sim.i], sim.route[sim.i + 1]]) : null;
      for (const id in buddies) {
        const b = buddies[id];
        if (!b.root.visible) continue;
        if (active && active.has(Number(id))) continue;
        b.update(dt);
      }
    }

    renderer.render(scene, camera);
    raf = requestAnimationFrame(frame);
  }
  function start() { if (!raf) frame(); }
  function stop() { if (raf) cancelAnimationFrame(raf); raf = 0; }

  return {
    start, stop, setHover, setSelected,
    startSimulation, pauseSimulation, resumeSimulation, restartSimulation, stopSimulation,
    startImprove: () => startSimulation('improve'),
    isPlaying: () => !!(sim && sim.playing),
    prefersReduced,
  };
}

// position along a polyline at normalized t (0..1 over whole length)
function polyline(points, t) {
  if (points.length === 1) return points[0].clone();
  let total = 0; const segs = [];
  for (let i = 0; i < points.length - 1; i++) { const l = points[i].distanceTo(points[i + 1]); segs.push(l); total += l; }
  let target = t * total;
  for (let i = 0; i < segs.length; i++) {
    if (target <= segs[i] || i === segs.length - 1) {
      const lt = segs[i] < 1e-6 ? 0 : target / segs[i];
      return points[i].clone().lerp(points[i + 1], Math.min(lt, 1));
    }
    target -= segs[i];
  }
  return points[points.length - 1].clone();
}
