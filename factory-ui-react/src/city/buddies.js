// ============================================================================
// Factory Buddies — one shared rig, re-skinned per character.
// Spec dimensions (units match the 30x20 city): total height ~1.5 incl. hat.
// Rig parts exposed for animation: root, head, torso, leftArm, rightArm,
// leftLeg, rightLeg, handSocket (right hand) — so clips can be shared and a
// held tool can be re-parented between characters during hand-off.
// ============================================================================
import * as THREE from 'three';

const BODY = '#FFF8EA';   // cream body (all buddies)
const FACE = '#344451';   // eyes + mouth

const col = (hex) => new THREE.Color(hex);
const _geos = [];
const _mats = [];
const g = (geom) => { _geos.push(geom); return geom; };
const matte = (hex, extra = {}) => { const m = new THREE.MeshStandardMaterial({ color: col(hex), roughness: 0.85, metalness: 0, flatShading: false, ...extra }); _mats.push(m); return m; };

// rounded box helper (bevelled extrude is heavy; use a Box with slight scale and
// soft normals via a small sphere-ish segment count is enough for toy look)
function roundedBox(w, h, d) { return g(new THREE.BoxGeometry(w, h, d, 2, 2, 2)); }

// ---- the character ---------------------------------------------------------
export function makeBuddy(spec) {
  const color = spec.color || '#8EAFD3';
  const buddy = spec.buddy || {};
  const bodyMat = matte(BODY);
  const accMat = matte(color);
  const faceMat = matte(FACE, { roughness: 0.6 });

  const root = new THREE.Group();
  root.name = `buddy-${spec.id}`;

  // torso (0.48 x 0.43 x 0.34), sits above legs
  const torso = new THREE.Group();
  const torsoMesh = new THREE.Mesh(roundedBox(0.48, 0.43, 0.34), bodyMat);
  torsoMesh.castShadow = true; torso.add(torsoMesh);
  torso.position.y = 0.52;
  root.add(torso);

  // chest badge
  if (buddy.badge) torso.add(makeBadge(buddy.badge, color));

  // head (0.72 x 0.58 x 0.60) on a neck pivot
  const head = new THREE.Group();
  const headMesh = new THREE.Mesh(roundedBox(0.72, 0.58, 0.60), bodyMat);
  headMesh.castShadow = true; head.add(headMesh);
  head.position.y = 0.43 / 2 + 0.58 / 2 + 0.02; // on top of torso
  torso.add(head);

  // face: two oval eyes + small smile on +Z
  const eyeGeo = g(new THREE.SphereGeometry(0.06, 14, 12));
  for (const dx of [-0.15, 0.15]) {
    const eye = new THREE.Mesh(eyeGeo, faceMat);
    eye.scale.set(1, 1.35, 0.6); eye.position.set(dx, 0.02, 0.31); head.add(eye);
  }
  const mouth = new THREE.Mesh(g(new THREE.TorusGeometry(0.08, 0.018, 8, 16, Math.PI)), faceMat);
  mouth.rotation.z = Math.PI; mouth.position.set(0, -0.12, 0.31); head.add(mouth);

  // side "ears"/headphones in accent color
  const earGeo = g(new THREE.SphereGeometry(0.1, 14, 12));
  for (const dx of [-0.38, 0.38]) {
    const ear = new THREE.Mesh(earGeo, accMat);
    ear.scale.set(0.7, 1.1, 0.9); ear.position.set(dx, -0.02, 0); head.add(ear);
  }

  // hat / headgear per character
  const hat = makeHat(buddy.hat, color, accMat);
  if (hat) head.add(hat);

  // arms: pivot at shoulder, cylinder down to a ball hand
  const leftArm = makeArm(accMat); leftArm.position.set(-0.28, 0.12, 0); torso.add(leftArm);
  const rightArm = makeArm(accMat); rightArm.position.set(0.28, 0.12, 0); torso.add(rightArm);
  leftArm.rotation.z = 0.25; rightArm.rotation.z = -0.25; // slight A-pose

  // handSocket at the right hand tip — tools attach here
  const handSocket = new THREE.Group();
  handSocket.position.set(0, -0.36, 0.02);
  rightArm.add(handSocket);
  const tool = makeTool(buddy.tool, color);
  if (tool) handSocket.add(tool);

  // legs: pivot at hip, short cylinder + flat foot
  const leftLeg = makeLeg(accMat); leftLeg.position.set(-0.12, 0.3, 0); root.add(leftLeg);
  const rightLeg = makeLeg(accMat); rightLeg.position.set(0.12, 0.3, 0); root.add(rightLeg);

  // scale whole rig so total height ≈ 1.5
  root.scale.setScalar(1.0);

  const api = {
    root, head, torso, leftArm, rightArm, leftLeg, rightLeg, handSocket,
    color, name: buddy.name, tool,
    home: new THREE.Vector3(),        // set by scene after placement
    _t: Math.random() * 10,
    _restArmL: 0.25, _restArmR: -0.25,
    faceTo(x, z) {
      const dx = x - root.position.x, dz = z - root.position.z;
      if (dx * dx + dz * dz > 1e-4) root.rotation.y = Math.atan2(dx, dz);
    },
    moveTo(x, z) { root.position.x = x; root.position.z = z; },
    // pose(name, t) — t is 0..1 phase for one-shots, or elapsed seconds for loops
    pose(name, t = 0) {
      // reset to rest each call, then apply the pose
      leftArm.rotation.set(0, 0, this._restArmL);
      rightArm.rotation.set(0, 0, this._restArmR);
      leftLeg.rotation.x = 0; rightLeg.rotation.x = 0;
      head.rotation.set(0, 0, 0);
      switch (name) {
        case 'walk': {
          const s = Math.sin(t * Math.PI * 2 * 1.25); // ~0.8s cycle
          leftLeg.rotation.x = s * 0.35; rightLeg.rotation.x = -s * 0.35;
          leftArm.rotation.x = -s * 0.5; rightArm.rotation.x = s * 0.5;
          torso.position.y = 0.52 + Math.abs(Math.sin(t * Math.PI * 2 * 2.5)) * 0.035;
          break;
        }
        case 'carry': {
          // both arms forward holding the item in front of torso
          leftArm.rotation.set(-1.2, 0, 0.1);
          rightArm.rotation.set(-1.2, 0, -0.1);
          break;
        }
        case 'knock': {
          const k = Math.sin(t * Math.PI * 6); // 3 knocks
          rightArm.rotation.set(-1.4 + Math.abs(k) * 0.5, 0, -0.1);
          break;
        }
        case 'receive': {
          leftArm.rotation.set(-1.0, 0, 0.2);
          rightArm.rotation.set(-1.0, 0, -0.2);
          break;
        }
        case 'work': {
          const w = Math.sin(t * 3);
          rightArm.rotation.set(-1.1 + w * 0.2, 0, -0.1);
          head.rotation.z = w * 0.08;
          break;
        }
        case 'success': {
          rightArm.rotation.set(-2.4, 0, -0.3); // arm up
          torso.position.y = 0.52 + Math.abs(Math.sin(t * Math.PI)) * 0.12;
          head.rotation.x = -0.1;
          break;
        }
        case 'warning': {
          head.rotation.z = 0.18;
          rightArm.rotation.set(-0.8, 0, -0.1);
          break;
        }
        default: break; // idle handled by update()
      }
    },
    update(dt) {
      this._t += dt;
      // idle: gentle torso bob (<=0.025) + slight head tilt + occasional blink
      torso.position.y = 0.52 + Math.sin(this._t * 1.6) * 0.025;
      head.rotation.z = Math.sin(this._t * 0.8) * 0.05;
      const blink = (Math.sin(this._t * 0.6) > 0.985) ? 0.15 : 1;
      head.children.forEach((c) => { if (c.geometry === eyeGeo) c.scale.y = 1.35 * blink; });
    },
  };
  return api;
}

function makeArm(mat) {
  const pivot = new THREE.Group();
  const upper = new THREE.Mesh(g(new THREE.CylinderGeometry(0.075, 0.075, 0.36, 10)), mat);
  upper.position.y = -0.18; upper.castShadow = true; pivot.add(upper);
  const hand = new THREE.Mesh(g(new THREE.SphereGeometry(0.1, 12, 10)), mat);
  hand.position.y = -0.38; pivot.add(hand);
  return pivot;
}

function makeLeg(mat) {
  const pivot = new THREE.Group();
  const leg = new THREE.Mesh(g(new THREE.CylinderGeometry(0.08, 0.08, 0.22, 10)), mat);
  leg.position.y = -0.11; leg.castShadow = true; pivot.add(leg);
  const foot = new THREE.Mesh(roundedBox(0.2, 0.1, 0.28), mat);
  foot.position.set(0, -0.25, 0.05); pivot.add(foot);
  return pivot;
}

// ---- hats ------------------------------------------------------------------
function makeHat(kind, color, accMat) {
  const grp = new THREE.Group();
  grp.position.y = 0.3;
  switch (kind) {
    case 'cap': {
      const crown = new THREE.Mesh(g(new THREE.SphereGeometry(0.34, 16, 12, 0, Math.PI * 2, 0, Math.PI / 2)), accMat);
      crown.scale.set(1, 0.8, 1); grp.add(crown);
      const brim = new THREE.Mesh(g(new THREE.CircleGeometry(0.26, 18, 0, Math.PI)), accMat);
      brim.rotation.x = -Math.PI / 2; brim.position.set(0, 0.01, 0.26); grp.add(brim);
      break;
    }
    case 'helmet': {
      const dome = new THREE.Mesh(g(new THREE.SphereGeometry(0.37, 16, 12, 0, Math.PI * 2, 0, Math.PI / 2)), accMat);
      dome.scale.set(1, 0.72, 1); grp.add(dome);
      const ridge = new THREE.Mesh(g(new THREE.BoxGeometry(0.06, 0.1, 0.6)), accMat);
      ridge.position.y = 0.12; grp.add(ridge);
      break;
    }
    case 'antenna': {
      const rod = new THREE.Mesh(g(new THREE.CylinderGeometry(0.02, 0.02, 0.26, 8)), accMat);
      rod.position.y = 0.16; grp.add(rod);
      const ball = new THREE.Mesh(g(new THREE.SphereGeometry(0.07, 12, 10)), accMat);
      ball.position.y = 0.32; grp.add(ball);
      break;
    }
    case 'bow': {
      for (const dx of [-0.09, 0.09]) {
        const wing = new THREE.Mesh(g(new THREE.ConeGeometry(0.1, 0.16, 4)), accMat);
        wing.rotation.z = dx > 0 ? -Math.PI / 2 : Math.PI / 2; wing.position.set(dx, 0.08, 0.2); grp.add(wing);
      }
      const knot = new THREE.Mesh(g(new THREE.SphereGeometry(0.05, 10, 8)), accMat);
      knot.position.set(0, 0.08, 0.2); grp.add(knot);
      break;
    }
    case 'ears': // Scout — accent ears already on head; add nothing extra
    default:
      return null;
  }
  return grp;
}

// ---- chest badges ----------------------------------------------------------
function makeBadge(kind, color) {
  const grp = new THREE.Group();
  grp.position.set(0, 0.02, 0.18);
  const mat = matte(color);
  const white = matte('#FFFFFF');
  switch (kind) {
    case 'shield': {
      const s = new THREE.Mesh(g(new THREE.CylinderGeometry(0.1, 0.07, 0.03, 5)), mat);
      s.rotation.x = Math.PI / 2; grp.add(s); break;
    }
    case 'folder': {
      const f = new THREE.Mesh(g(new THREE.BoxGeometry(0.16, 0.12, 0.03)), mat); grp.add(f); break;
    }
    case 'grid': {
      const f = new THREE.Mesh(g(new THREE.BoxGeometry(0.16, 0.13, 0.03)), white); grp.add(f);
      for (let i = 0; i < 2; i++) { const l = new THREE.Mesh(g(new THREE.BoxGeometry(0.16, 0.012, 0.035)), mat); l.position.y = -0.03 + i * 0.045; grp.add(l); }
      break;
    }
    case 'gear': {
      const ge = new THREE.Mesh(g(new THREE.CylinderGeometry(0.09, 0.09, 0.03, 8)), mat); ge.rotation.x = Math.PI / 2; grp.add(ge);
      const hole = new THREE.Mesh(g(new THREE.CylinderGeometry(0.035, 0.035, 0.04, 10)), white); hole.rotation.x = Math.PI / 2; hole.position.z = 0.005; grp.add(hole);
      break;
    }
    case 'download': {
      const arrow = new THREE.Mesh(g(new THREE.ConeGeometry(0.08, 0.12, 4)), mat); arrow.rotation.x = Math.PI; arrow.position.y = -0.01; grp.add(arrow);
      const bar = new THREE.Mesh(g(new THREE.BoxGeometry(0.16, 0.025, 0.03)), mat); bar.position.y = -0.09; grp.add(bar);
      break;
    }
    default: break;
  }
  return grp;
}

// ---- held tools (attach to handSocket) ------------------------------------
function makeTool(kind, color) {
  const grp = new THREE.Group();
  const mat = matte(color);
  const dark = matte('#344451');
  const white = matte('#FFFFFF');
  switch (kind) {
    case 'key': {
      const ring = new THREE.Mesh(g(new THREE.TorusGeometry(0.07, 0.022, 8, 16)), matte('#EDC16A'));
      grp.add(ring);
      const stem = new THREE.Mesh(g(new THREE.BoxGeometry(0.03, 0.18, 0.03)), matte('#EDC16A'));
      stem.position.y = -0.12; grp.add(stem);
      break;
    }
    case 'box': {
      const b = new THREE.Mesh(g(new THREE.BoxGeometry(0.34, 0.3, 0.3)), matte('#D9C3A3'));
      b.castShadow = true; grp.add(b);
      const tape = new THREE.Mesh(g(new THREE.BoxGeometry(0.35, 0.05, 0.31)), matte('#C8AE86')); grp.add(tape);
      break;
    }
    case 'magnifier': {
      const ring = new THREE.Mesh(g(new THREE.TorusGeometry(0.11, 0.028, 10, 20)), dark); grp.add(ring);
      const glass = new THREE.Mesh(g(new THREE.CircleGeometry(0.1, 18)), matte('#BBDCE6')); grp.add(glass);
      const handle = new THREE.Mesh(g(new THREE.CylinderGeometry(0.02, 0.02, 0.16, 8)), dark);
      handle.position.set(0.1, -0.14, 0); handle.rotation.z = -0.7; grp.add(handle);
      break;
    }
    case 'tablet-plan': case 'tablet-qa': case 'tablet-chart': {
      const frame = new THREE.Mesh(g(new THREE.BoxGeometry(0.46, 0.34, 0.04)), dark);
      frame.castShadow = true; grp.add(frame);
      const screen = new THREE.Mesh(g(new THREE.PlaneGeometry(0.4, 0.28)), screenTexMat(kind, color));
      screen.position.z = 0.025; grp.add(screen);
      grp.rotation.set(-0.15, 0, 0);
      break;
    }
    default: break;
  }
  // position the tool in front of the hand
  grp.position.set(0.0, -0.04, 0.08);
  return grp;
}

// tablet screen drawn on a small canvas (plan layout / QA check / chart)
function screenTexMat(kind, color) {
  const cv = document.createElement('canvas'); cv.width = 256; cv.height = 180;
  const c = cv.getContext('2d');
  c.fillStyle = '#F4F7FA'; c.fillRect(0, 0, 256, 180);
  c.strokeStyle = color; c.lineWidth = 6;
  if (kind === 'tablet-plan') {
    c.strokeRect(24, 20, 90, 50); c.strokeRect(140, 20, 90, 50); c.strokeRect(24, 100, 206, 56);
  } else if (kind === 'tablet-qa') {
    c.fillStyle = color; c.beginPath(); c.arc(128, 90, 54, 0, Math.PI * 2); c.fill();
    c.strokeStyle = '#FFFFFF'; c.lineWidth = 14; c.beginPath(); c.moveTo(100, 92); c.lineTo(122, 116); c.lineTo(158, 68); c.stroke();
  } else { // chart
    c.fillStyle = color;
    [[40, 60], [96, 100], [152, 76], [208, 120]].forEach(([x, h]) => c.fillRect(x, 160 - h, 34, h));
  }
  const tex = new THREE.CanvasTexture(cv); tex.anisotropy = 4;
  const m = new THREE.MeshBasicMaterial({ map: tex }); m.userData = { tex }; _mats.push(m);
  return m;
}

export function disposeBuddies() {
  for (const geom of _geos) { try { geom.dispose(); } catch {} }
  for (const m of _mats) { try { if (m.map) m.map.dispose(); m.dispose(); } catch {} }
  _geos.length = 0; _mats.length = 0;
}
