// ============================================================================
// Scene — renderer, isometric ortho camera, lights, ground, roads, picking.
// Reads layout from config.js and builds pieces from buildings.js.
// ============================================================================
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { PALETTE, STATIONS, EDGES, byId } from './config.js';
import { makeBuilding, makeTree, makeCargo, makeCitySign, disposeShared } from './buildings.js';
import { makeBuddy, disposeBuddies } from './buddies.js';
import { buildAnchors, buildGraph, footprints } from './navigation.js';

export function createScene(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)); // cap pixel ratio
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;      // correct, vivid color
  renderer.toneMapping = THREE.ACESFilmicToneMapping;    // soft highlight roll-off
  renderer.toneMappingExposure = 1.21;                   // lift overall brightness
  renderer.setClearColor(new THREE.Color(PALETTE.cream), 1);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(PALETTE.cream);

  // ---- isometric orthographic camera -------------------------------------
  const frustum = 17;
  let aspect = canvas.clientWidth / Math.max(canvas.clientHeight, 1);
  const camera = new THREE.OrthographicCamera(
    -frustum * aspect, frustum * aspect, frustum, -frustum, 0.1, 200,
  );
  camera.position.set(24, 22, 24);
  camera.lookAt(0, 0, 0);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.enablePan = false;
  controls.minPolarAngle = Math.PI * 0.18;   // limit how low the camera dips
  controls.maxPolarAngle = Math.PI * 0.42;   // and how flat it goes
  controls.minZoom = 0.6;
  controls.maxZoom = 2.2;
  controls.target.set(0, 1.5, 0);
  const HOME = { pos: camera.position.clone(), zoom: camera.zoom, target: controls.target.clone() };

  // ---- lights (bright, cheerful toy lighting) ----------------------------
  scene.add(new THREE.HemisphereLight(0xffffff, 0xeef3ea, 1.15));
  scene.add(new THREE.AmbientLight(0xffffff, 0.35));
  const key = new THREE.DirectionalLight(0xffffff, 1.5);
  key.position.set(16, 28, 13);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  const d = 24;
  key.shadow.camera.left = -d; key.shadow.camera.right = d;
  key.shadow.camera.top = d; key.shadow.camera.bottom = -d;
  key.shadow.camera.near = 1; key.shadow.camera.far = 80;
  key.shadow.bias = -0.0004;
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xffffff, 0.5);
  fill.position.set(-16, 14, -10);
  scene.add(fill);

  const disposables = { geo: [], mat: [] };
  const track = (o) => { if (o.geometry) disposables.geo.push(o.geometry); if (o.material) disposables.mat.push(o.material); return o; };

  // ---- city base (rounded-rect mint slab on a cream world) ---------------
  const baseShape = roundedRectShape(31, 21, 2.0);
  const baseGeo = new THREE.ExtrudeGeometry(baseShape, { depth: 0.6, bevelEnabled: true, bevelThickness: 0.12, bevelSize: 0.12, bevelSegments: 2 });
  baseGeo.rotateX(-Math.PI / 2);
  baseGeo.translate(0, -0.6, 0);
  disposables.geo.push(baseGeo);
  const baseMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(PALETTE.base), roughness: 0.95, flatShading: true });
  disposables.mat.push(baseMat);
  const base = new THREE.Mesh(baseGeo, baseMat);
  base.receiveShadow = true;
  scene.add(base);

  // ---- roads (main grey + improve lavender) + direction arrows -----------
  const roadGroup = new THREE.Group();
  const arrowGroup = new THREE.Group();
  const edgePaths = {}; // id "from-to" -> array of Vector3 waypoints at y≈0.02
  scene.add(roadGroup); scene.add(arrowGroup);

  const roadMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(PALETTE.road), roughness: 0.98, flatShading: true });
  const improveMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(PALETTE.improve), roughness: 0.9, flatShading: true });
  disposables.mat.push(roadMat, improveMat);

  for (const edge of EDGES) {
    const pa = byId[edge.from].pos, pb = byId[edge.to].pos;
    const a = new THREE.Vector3(pa[0], 0, pa[1]);
    const b = new THREE.Vector3(pb[0], 0, pb[1]);
    const mat = edge.kind === 'improve' ? improveMat : roadMat;
    const pts = edge.kind === 'improve'
      ? improveWaypoints(a, b)       // routed to the far-right edge, no crossings
      : orthoWaypoints(a, b);        // L-shaped grey road
    edgePaths[`${edge.from}-${edge.to}`] = pts.map((p) => p.clone().setY(0.25));
    buildRoadRibbon(pts, mat, edge.kind === 'improve' ? 0.9 : 1.3, roadGroup, disposables);
    buildArrows(pts, edge.kind, arrowGroup, disposables);
  }

  // ---- buildings ----------------------------------------------------------
  const buildings = {};        // id -> building api
  const pickTargets = [];      // meshes used for raycasting -> station id
  for (const station of STATIONS) {
    const b = makeBuilding(station);
    scene.add(b.group);
    buildings[station.id] = b;
    b.group.traverse((o) => { if (o.isMesh) { o.userData.stationId = station.id; pickTargets.push(o); } });
  }

  // ---- decorations (trees + a greeter robot), kept clear of roads --------
  const decor = new THREE.Group(); scene.add(decor);
  const treeSpots = [
    [-13.5, 0, 0], [-5, 0, 0.5], [5, 0, -0.5], [13.5, 0, 0],
    [-13.5, 0, -8.5], [13.5, 0, -8.5], [-13.5, 0, 8.5], [13.5, 0, 8.5],
    [-5, 0, -8.5], [5, 0, 8.5],
  ];
  for (const [x, , z] of treeSpots) {
    const t = makeTree(); t.position.set(x, 0, z); t.rotation.y = Math.random() * Math.PI; decor.add(t);
  }

  // ---- navigation anchors + road graph (per-door, world space) -----------
  const anchors = buildAnchors();
  const graph = buildGraph(anchors);

  // ---- Factory Buddies: start HIDDEN inside each house (indoorPoint) ------
  // Spec: no character waits in front of a house; each appears only when its
  // door opens during the workflow. All doors start closed.
  const buddies = {};
  for (const station of STATIONS) {
    const b = makeBuddy(station);
    const a = anchors[station.id];
    b.anchors = a;
    b.home = a.indoorPoint.clone();
    b.root.position.copy(a.indoorPoint);
    b.root.rotation.y = 0;
    b.root.visible = false;                 // hidden inside until summoned
    scene.add(b.root);
    buddies[station.id] = b;
    buildings[station.id].setDoor(0);       // door closed
  }

  // ---- city front sign "DASHBOARD FACTORY" -------------------------------
  scene.add(makeCitySign());

  // ---- travelling cargo (used by animation during simulation) ------------
  const cargo = makeCargo(); cargo.visible = false; cargo.position.y = 1.2; scene.add(cargo); 

  // ---- raycasting ---------------------------------------------------------
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  function pick(clientX, clientY) {
    const r = canvas.getBoundingClientRect();
    ndc.x = ((clientX - r.left) / r.width) * 2 - 1;
    ndc.y = -((clientY - r.top) / r.height) * 2 + 1;
    raycaster.setFromCamera(ndc, camera);
    const hit = raycaster.intersectObjects(pickTargets, false)[0];
    return hit ? hit.object.userData.stationId : null;
  }

  // ---- resize -------------------------------------------------------------
  function resize() {
    const w = canvas.clientWidth, h = Math.max(canvas.clientHeight, 1);
    aspect = w / h;
    camera.left = -frustum * aspect; camera.right = frustum * aspect;
    camera.top = frustum; camera.bottom = -frustum;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h, false);
  }
  resize();

  // ---- debug navigation overlay (hidden by default) ----------------------
  const debugGroup = new THREE.Group(); debugGroup.visible = false; scene.add(debugGroup);
  (function buildDebug() {
    const lineMat = new THREE.LineBasicMaterial({ color: 0x3355cc });
    const dotGeo = new THREE.SphereGeometry(0.12, 8, 6); disposables.geo.push(dotGeo);
    disposables.mat.push(lineMat);
    // graph edges
    const seen = new Set();
    for (const a in graph.adj) {
      for (const { to } of graph.adj[a]) {
        const key = [a, to].sort().join('|'); if (seen.has(key)) continue; seen.add(key);
        const g = new THREE.BufferGeometry().setFromPoints([graph.nodes[a].clone().setY(0.1), graph.nodes[to].clone().setY(0.1)]);
        disposables.geo.push(g); debugGroup.add(new THREE.Line(g, lineMat));
      }
    }
    // anchor dots (colored per type) + doorFacing arrows
    const dotMat = (c) => { const m = new THREE.MeshBasicMaterial({ color: c }); disposables.mat.push(m); return m; };
    const kinds = { knockPoint: 0xe8503a, receiverPoint: 0x2fbf7f, doorThreshold: 0xf5a623, indoorPoint: 0x7c5fe0, approach: 0x3e9bf0, roadAnchor: 0x888888, queuePoint: 0xaaaaaa };
    for (const id in anchors) {
      const a = anchors[id];
      for (const k in kinds) {
        const dot = new THREE.Mesh(dotGeo, dotMat(kinds[k])); dot.position.copy(a[k]).setY(0.12); debugGroup.add(dot);
      }
      const dir = a.doorThreshold.clone().add(a.doorFacing.clone().multiplyScalar(1.2)).setY(0.12);
      const g = new THREE.BufferGeometry().setFromPoints([a.doorThreshold.clone().setY(0.12), dir]);
      disposables.geo.push(g); debugGroup.add(new THREE.Line(g, dotMat(0xff00ff)));
    }
    // expanded footprints
    for (const f of footprints()) {
      const w = f.max[0] - f.min[0], d = f.max[1] - f.min[1];
      const g = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(f.min[0], 0.08, f.min[1]), new THREE.Vector3(f.max[0], 0.08, f.min[1]),
        new THREE.Vector3(f.max[0], 0.08, f.max[1]), new THREE.Vector3(f.min[0], 0.08, f.max[1]),
        new THREE.Vector3(f.min[0], 0.08, f.min[1]),
      ]);
      disposables.geo.push(g); debugGroup.add(new THREE.Line(g, dotMat(0xff8800)));
    }
  })();

  function resetCamera() {
    camera.position.copy(HOME.pos);
    camera.zoom = HOME.zoom; camera.updateProjectionMatrix();
    controls.target.copy(HOME.target);
    controls.update();
  }

  function dispose() {
    controls.dispose();
    for (const g of disposables.geo) { try { g.dispose(); } catch {} }
    for (const m of disposables.mat) { try { m.dispose(); } catch {} }
    disposeShared();
    disposeBuddies();
    renderer.dispose();
  }

  return {
    renderer, scene, camera, controls,
    buildings, buddies, cargo, edgePaths, arrowGroup, roadGroup,
    anchors, graph, debugGroup,
    setDebug: (on) => { debugGroup.visible = !!on; },
    pick, resize, resetCamera, dispose,
    worldPos: (id) => { const p = byId[id].pos; return new THREE.Vector3(p[0], 0, p[1]); },
  };
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------
function roundedRectShape(w, h, r) {
  const s = new THREE.Shape();
  const x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y);
  s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
  return s;
}

// L-shaped path between two stations: move along X first (via a mid lane),
// then along Z. Keeps roads axis-aligned so they never cross diagonally.
function orthoWaypoints(a, b) {
  const midZ = (a.z + b.z) / 2;
  if (Math.abs(a.z - b.z) < 0.1) return [a.clone(), b.clone()];             // same row
  // route via a shared lane to avoid diagonal crossings
  return [a.clone(), new THREE.Vector3(a.x, 0, midZ), new THREE.Vector3(b.x, 0, midZ), b.clone()];
}

// Improve path hugs the far-right edge so it never overlaps the main belts.
function improveWaypoints(a, b) {
  const edgeX = 14;
  return [
    a.clone(),
    new THREE.Vector3(edgeX, 0, a.z),
    new THREE.Vector3(edgeX, 0, b.z),
    b.clone(),
  ];
}

// Build a flat ribbon (series of boxes) following waypoints on the ground.
function buildRoadRibbon(points, material, width, parent, disposables) {
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i], p1 = points[i + 1];
    const seg = new THREE.Vector3().subVectors(p1, p0);
    const len = seg.length();
    if (len < 0.01) continue;
    const g = new THREE.BoxGeometry(len + width, 0.08, width);
    disposables.geo.push(g);
    const mesh = new THREE.Mesh(g, material);
    mesh.position.copy(p0).add(p1).multiplyScalar(0.5).setY(0.04);
    mesh.rotation.y = Math.atan2(-seg.z, seg.x);
    mesh.receiveShadow = true;
    parent.add(mesh);
  }
}

// Direction arrows (small chevrons) along a path.
function buildArrows(points, kind, parent, disposables) {
  const color = kind === 'improve' ? PALETTE.improveArrow : PALETTE.roadLine;
  const mat = new THREE.MeshStandardMaterial({ color: new THREE.Color(color), roughness: 0.8, flatShading: true });
  disposables.mat.push(mat);
  const shape = new THREE.Shape();
  shape.moveTo(-0.22, -0.28); shape.lineTo(0.3, 0); shape.lineTo(-0.22, 0.28); shape.lineTo(-0.05, 0); shape.closePath();
  const geo = new THREE.ShapeGeometry(shape);
  disposables.geo.push(geo);
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i], p1 = points[i + 1];
    const seg = new THREE.Vector3().subVectors(p1, p0);
    const len = seg.length();
    if (len < 1.2) continue;
    const count = Math.max(1, Math.floor(len / 3.2));
    for (let k = 1; k <= count; k++) {
      const t = k / (count + 1);
      const arrow = new THREE.Mesh(geo, mat);
      arrow.position.copy(p0).lerp(p1, t).setY(0.1);
      arrow.rotation.x = -Math.PI / 2;
      arrow.rotation.z = -Math.atan2(-seg.z, seg.x);
      arrow.scale.setScalar(kind === 'improve' ? 1.1 : 1.0);
      parent.add(arrow);
    }
  }
}
