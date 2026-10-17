// ============================================================================
// Building components — spec-aligned low-poly pieces.
// Each building is sized from station.size = [w, d, h] (roof excluded).
// Materials are matte (roughness 0.85, metalness 0). Geometries created per
// building are tracked in _geos and disposed by disposeShared().
// ============================================================================
import * as THREE from 'three';
import { PALETTE, MAT, CITY } from './config.js';

const col = (hex) => new THREE.Color(hex);
const _geos = [];
const _mats = [];

// darken a hex color by factor (0..1) for roof-edge trims
function darken(hex, f) {
  const c = new THREE.Color(hex);
  c.multiplyScalar(f);
  return '#' + c.getHexString();
}

function flat(color, opts = {}) {
  const m = new THREE.MeshStandardMaterial({ color: col(color), ...MAT, flatShading: true, ...opts });
  _mats.push(m);
  return m;
}
function trackGeo(g) { _geos.push(g); return g; }

// shared material cache by color (walls/frames/roofs reuse)
const _matCache = {};
function matOf(color) {
  if (!_matCache[color]) _matCache[color] = flat(color);
  return _matCache[color];
}

// Triangular-prism roof sized to a building footprint.
function makePrismRoof(width, height, depth) {
  const shape = new THREE.Shape();
  shape.moveTo(-width / 2, 0);
  shape.lineTo(width / 2, 0);
  shape.lineTo(0, height);
  shape.closePath();
  const g = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false });
  g.translate(0, 0, -depth / 2);
  g.computeVertexNormals();
  return trackGeo(g);
}

// ---- rooftop symbols (kept simple; scale to building) ---------------------
function makeSymbol(kind) {
  const group = new THREE.Group();
  const add = (m) => { group.add(m); return m; };
  const plate = () => trackGeo(new THREE.BoxGeometry(1.0, 0.62, 0.1));
  const thin = () => trackGeo(new THREE.BoxGeometry(0.42, 0.42, 0.08));
  const tiny = () => trackGeo(new THREE.BoxGeometry(0.16, 0.4, 0.16));
  const box = () => trackGeo(new THREE.BoxGeometry(0.72, 0.72, 0.72));
  switch (kind) {
    case 'shield': {
      const s = add(new THREE.Mesh(plate(), matOf(PALETTE.running))); s.scale.set(0.8, 1.0, 1); s.position.y = 0.2;
      const key = add(new THREE.Mesh(tiny(), matOf(PALETTE.white))); key.scale.set(0.6, 0.9, 0.6); key.position.set(0, 0.18, 0.08);
      break;
    }
    case 'folders': {
      [PALETTE.improve, PALETTE.roofDefault, PALETTE.frame].forEach((c, i) => {
        const f = add(new THREE.Mesh(box(), matOf(c))); f.scale.set(0.9, 0.6, 0.55); f.position.set((i - 1) * 0.62, 0, 0);
      });
      break;
    }
    case 'magnifier': {
      const ring = add(new THREE.Mesh(trackGeo(new THREE.TorusGeometry(0.3, 0.08, 10, 20)), matOf(PALETTE.running)));
      ring.position.y = 0.25; ring.rotation.x = Math.PI / 2.2;
      const h = add(new THREE.Mesh(tiny(), matOf(PALETTE.running))); h.scale.set(0.5, 1.1, 0.5); h.position.set(0.28, -0.05, 0); h.rotation.z = -0.8;
      break;
    }
    case 'blueprint': {
      const p = add(new THREE.Mesh(plate(), matOf(PALETTE.white))); p.position.y = 0.2; p.rotation.x = -0.15;
      [[-0.22, 0.28, PALETTE.roofAiplan], [0, 0.18, PALETTE.roofDefault], [0.22, 0.34, PALETTE.improve]].forEach(([x, hh, c]) => {
        const b = add(new THREE.Mesh(thin(), matOf(c))); b.scale.set(0.5, hh * 2, 1); b.position.set(x, 0.1 + hh / 2, 0.08);
      });
      break;
    }
    case 'chart': {
      add(new THREE.Mesh(plate(), matOf(PALETTE.white))).position.y = 0.2;
      [[-0.26, 0.2, PALETTE.roofDefault], [0, 0.4, PALETTE.improve], [0.26, 0.3, PALETTE.warn]].forEach(([x, hh, c]) => {
        const b = add(new THREE.Mesh(thin(), matOf(c))); b.scale.set(0.55, hh * 2.4, 1); b.position.set(x, 0.05 + hh, 0.08);
      });
      break;
    }
    case 'screen': {
      const scr = add(new THREE.Mesh(plate(), matOf(PALETTE.glass))); scr.scale.set(1.25, 1.0, 1); scr.position.y = 0.26;
      const bar = add(new THREE.Mesh(thin(), matOf(PALETTE.roofAiplan))); bar.scale.set(0.5, 1.0, 1); bar.position.set(-0.22, 0.24, 0.08);
      const pie = add(new THREE.Mesh(trackGeo(new THREE.CircleGeometry(0.17, 18)), matOf(PALETTE.warn))); pie.position.set(0.26, 0.26, 0.08);
      break;
    }
    default: break;
  }
  return group;
}

// ---- billboard sign (spec: Canvas 1024x224, number circle, name/sub) ------
function makeSign(station) {
  const g = new THREE.Group();
  const small = !!station.signSmall;
  const W = 1024, H = 224;
  const canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d');

  // board face + border
  roundRect(ctx, 6, 6, W - 12, H - 12, 34);
  ctx.fillStyle = PALETTE.signBg; ctx.fill();
  ctx.lineWidth = 10; ctx.strokeStyle = PALETTE.signEdge; ctx.stroke();

  // step-number circle (diameter 112 -> r 56) centred X=90 Y=112 — character color
  const circleColor = station.color ? darken(station.color, 0.85) : PALETTE.numCircle;
  ctx.beginPath(); ctx.arc(90, 112, 56, 0, Math.PI * 2);
  ctx.fillStyle = circleColor; ctx.fill();
  ctx.fillStyle = '#FFFFFF';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.font = '700 60px "Prompt","Noto Sans Thai",sans-serif';
  ctx.fillText(String(station.badge), 90, 112);

  // name (+ optional sub) centred in text area X 170-970, centre X=570
  ctx.fillStyle = PALETTE.text;
  const nameSize = station.signLong ? 48 : 56;
  if (station.signSub) {
    ctx.font = `700 ${nameSize}px "Prompt","Noto Sans Thai",sans-serif`;
    ctx.fillText(station.signName, 570, 88);
    ctx.font = '500 28px "Prompt","Noto Sans Thai",sans-serif';
    ctx.fillStyle = circleColor;
    ctx.fillText(station.signSub, 570, 153);
  } else {
    ctx.font = `700 ${nameSize}px "Prompt","Noto Sans Thai",sans-serif`;
    ctx.fillText(station.signName, 570, 112);
  }

  const tex = new THREE.CanvasTexture(canvas);
  tex.anisotropy = 4; tex.needsUpdate = true;
  const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true });
  mat.userData = { tex };
  _mats.push(mat);

  // board dims (spec): general 4.4 x 0.95 x 0.12, Login 2.8 x 0.85
  const bw = small ? 2.8 : 4.4;
  const bh = small ? 0.85 : 0.95;
  const boardGeo = trackGeo(new THREE.BoxGeometry(bw, bh, 0.12));
  const faceGeo = trackGeo(new THREE.PlaneGeometry(bw * 0.96, bh * 0.9));
  const board = new THREE.Mesh(boardGeo, matOf(PALETTE.signBg));
  const face = new THREE.Mesh(faceGeo, mat);
  face.position.z = 0.061;
  g.add(board); g.add(face);
  g.userData.boardWidth = bw;
  return g;
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

// ---- a single building ----------------------------------------------------
export function makeBuilding(station) {
  const group = new THREE.Group();
  group.name = `building-${station.id}`;
  const [w, d, h] = station.size;

  const roofColor = station.color || (station.roofKind === 'aiplan' ? PALETTE.roofAiplan : PALETTE.roofDefault);
  const roofEdge = darken(roofColor, 0.82);

  // walls (floor top at Y 0 -> body centre at h/2)
  const body = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(w, h, d)), matOf(PALETTE.wall));
  body.position.y = h / 2; body.castShadow = true; body.receiveShadow = true;
  group.add(body);

  // roof: prism + a thin edge trim strip
  const roofH = Math.max(1.0, h * 0.42);
  const roof = new THREE.Mesh(makePrismRoof(w + 0.5, roofH, d + 0.5), flat(roofColor));
  roof.position.y = h; roof.castShadow = true; group.add(roof);
  const trim = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(w + 0.6, 0.18, d + 0.6)), matOf(roofEdge));
  trim.position.y = h + 0.02; group.add(trim);

  const FRONT = d / 2; // front face at +Z

  // door with frame, centred-left — door on a hinge pivot so it can swing open
  const doorW = Math.min(1.6, w * 0.34), doorH = Math.min(h * 0.7, 2.4);
  const doorX = -w * 0.22;
  const frame = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(doorW + 0.22, doorH + 0.18, 0.14)), matOf(PALETTE.frame));
  frame.position.set(doorX, doorH / 2, FRONT + 0.01); group.add(frame);
  const hinge = new THREE.Group();
  hinge.position.set(doorX - doorW / 2, doorH / 2, FRONT + 0.05); // hinge at the door's left edge
  const doorMesh = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(doorW, doorH, 0.1)), matOf(PALETTE.screen));
  doorMesh.position.set(doorW / 2, 0, 0); // offset so it swings around the hinge
  hinge.add(doorMesh); group.add(hinge);

  // two framed windows with glass, right of the door
  const winS = Math.min(0.9, w * 0.16);
  for (const dx of [w * 0.12, w * 0.32]) {
    const wf = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(winS + 0.16, winS + 0.16, 0.12)), matOf(PALETTE.frame));
    wf.position.set(dx, h * 0.6, FRONT + 0.01); group.add(wf);
    const gl = new THREE.Mesh(trackGeo(new THREE.PlaneGeometry(winS, winS)), matOf(PALETTE.glass));
    gl.position.set(dx, h * 0.6, FRONT + 0.08); group.add(gl);
  }

  // ---- billboard sign: centred on front wall, under the eaves, facing +Z --
  const sign = makeSign(station);
  const signY = station.signSmall ? 2.8 : 3.15;   // spec centre heights
  sign.position.set(0, signY, FRONT + 0.10);       // spec: z + depth/2 + 0.10
  group.add(sign);

  // ---- front entry path + steps -----------------------------------------
  const walk = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(doorW + 0.6, 0.1, 2.2)), matOf(PALETTE.frame));
  walk.position.set(-w * 0.22, 0.05, FRONT + 1.3); walk.receiveShadow = true; group.add(walk);
  for (let i = 0; i < 2; i++) {
    const step = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(doorW + 0.8, 0.16, 0.45)), matOf(PALETTE.frame));
    step.position.set(-w * 0.22, 0.1 + i * 0.14, FRONT + 0.25 + i * 0.45); step.receiveShadow = true; group.add(step);
  }

  // rooftop symbol
  const symbolGroup = makeSymbol(station.symbol);
  symbolGroup.position.y = h + roofH + 0.25;
  symbolGroup.scale.setScalar(1.3);
  group.add(symbolGroup);

  // status gem above the ridge
  const gemMat = new THREE.MeshStandardMaterial({ color: col(PALETTE.idle), roughness: 0.5, flatShading: true, emissive: col('#000') });
  _mats.push(gemMat);
  const gem = new THREE.Mesh(trackGeo(new THREE.OctahedronGeometry(0.42, 0)), gemMat);
  gem.position.set(-w * 0.35, h + roofH + 0.6, 0); group.add(gem);

  group.position.set(station.pos[0], 0, station.pos[1]);
  let doorOpen = 0;
  return {
    group, symbolGroup, gem, body, hinge,
    raise(t) { group.position.y = t; },
    setStatus(name, color) {
      const c = col(color);
      gemMat.color.copy(c);
      gemMat.emissive.copy(c).multiplyScalar(name === 'idle' ? 0 : 0.35);
    },
    setDoor(open01) { doorOpen = open01; hinge.rotation.y = -open01 * (Math.PI * 80 / 180); }, // swing out ~80°
    doorIsOpen() { return doorOpen > 0.9; },
  };
}

// ---- city front sign: "DASHBOARD FACTORY" -------------------------------
export function makeCitySign() {
  const g = new THREE.Group();
  const W = 1600, H = 176;
  const canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d');
  roundRect(ctx, 6, 6, W - 12, H - 12, 24);
  ctx.fillStyle = PALETTE.signBg; ctx.fill();
  ctx.lineWidth = 10; ctx.strokeStyle = PALETTE.signEdge; ctx.stroke();
  ctx.fillStyle = PALETTE.text; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.font = '700 72px "Prompt","Noto Sans Thai",sans-serif';
  ctx.fillText(CITY.sign.text, W / 2, H / 2 + 2);

  const tex = new THREE.CanvasTexture(canvas); tex.anisotropy = 4; tex.needsUpdate = true;
  const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true }); mat.userData = { tex }; _mats.push(mat);
  const [sw, sh, sd] = CITY.sign.size;
  const board = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(sw, sh, sd)), matOf(PALETTE.signBg));
  const face = new THREE.Mesh(trackGeo(new THREE.PlaneGeometry(sw * 0.97, sh * 0.8)), mat); face.position.z = sd / 2 + 0.01;
  g.add(board); g.add(face);
  g.position.set(CITY.sign.pos[0], CITY.sign.pos[1], CITY.sign.pos[2]);
  return g;
}

// ---- decorations ----------------------------------------------------------
export function makeTree() {
  const g = new THREE.Group();
  const trunk = new THREE.Mesh(trackGeo(new THREE.CylinderGeometry(0.12, 0.16, 0.6, 8)), matOf(PALETTE.treeTrunk));
  trunk.position.y = 0.3; g.add(trunk);
  const top = new THREE.Mesh(trackGeo(new THREE.SphereGeometry(0.7, 16, 12)), matOf(PALETTE.tree));
  top.position.y = 0.95; top.castShadow = true; g.add(top);
  return g;
}

export function makeRobot() {
  const g = new THREE.Group();
  const bodyMat = matOf(PALETTE.robot);
  const jointMat = matOf(PALETTE.robotJoint);
  const box = trackGeo(new THREE.BoxGeometry(0.72, 0.72, 0.72));
  const sph = trackGeo(new THREE.SphereGeometry(0.5, 20, 16));
  const tiny = trackGeo(new THREE.BoxGeometry(0.16, 0.4, 0.16));
  const torso = new THREE.Mesh(box, bodyMat); torso.scale.set(0.8, 1.0, 0.6); torso.position.y = 0.7; g.add(torso);
  const head = new THREE.Mesh(sph, bodyMat); head.scale.setScalar(0.62); head.position.y = 1.35; g.add(head);
  const ant = new THREE.Mesh(tiny, jointMat); ant.scale.set(0.3, 0.7, 0.3); ant.position.y = 1.85; g.add(ant);
  for (const dx of [-0.42, 0.42]) {
    const arm = new THREE.Mesh(tiny, jointMat); arm.scale.set(0.5, 1.0, 0.5); arm.position.set(dx, 0.75, 0); g.add(arm);
    const leg = new THREE.Mesh(tiny, jointMat); leg.scale.set(0.6, 1.0, 0.6); leg.position.set(dx * 0.5, 0.15, 0); g.add(leg);
  }
  return g;
}

export function makeCargo() {
  const mat2 = new THREE.MeshStandardMaterial({ color: col(PALETTE.warn), ...MAT, flatShading: true, emissive: col('#000') });
  _mats.push(mat2);
  const m = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.72, 0.72, 0.72)), mat2);
  m.castShadow = true; m.userData.mat = mat2;
  return m;
}

export function disposeShared() {
  for (const g of _geos) { try { g.dispose(); } catch {} }
  for (const m of _mats) { try { if (m.map) m.map.dispose(); m.dispose(); } catch {} }
  _geos.length = 0; _mats.length = 0;
  for (const k of Object.keys(_matCache)) delete _matCache[k];
}
