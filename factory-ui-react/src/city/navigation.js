// ============================================================================
// navigation.js — door anchors, road graph, and Dijkstra pathfinding.
// All anchors derive from the REAL door (local x = -w*0.22, z = +d/2, facing +Z)
// so a buddy walks to the door, never to the building centre or a near wall.
// Buildings face +Z and are not rotated, so world = pos + localOffset.
// ============================================================================
import * as THREE from 'three';
import { STATIONS, byId } from './config.js';

const CHAR_RADIUS = 0.35;
const CLEARANCE = 0.10;

// Main-road lane Z values (buildings sit at z = ±9 in city units... actually
// spec pos: top row z=-4.5, bottom row z=+5). Lanes run between the rows.
const LANE_FRONT = 2.2;   // lane serving the bottom row (+Z) fronts — in front of them
const LANE_MID = 0.0;     // central corridor between rows
const EDGE_X = 14;        // improve path outer lane (matches scene edgeX)

// Build per-building anchors in WORLD space (buildings are axis-aligned +Z).
export function buildAnchors() {
  const anchors = {};
  for (const s of STATIONS) {
    const [bx, bz] = s.pos;
    const [w, d] = s.size;
    const doorX = bx - w * 0.22;          // door local x offset
    const frontZ = bz + d / 2;            // front face (+Z)
    const facing = new THREE.Vector3(0, 0, 1); // doorFacing: out of the front, +Z

    const doorThreshold = new THREE.Vector3(doorX, 0, frontZ);
    const knockPoint = new THREE.Vector3(doorX, 0, frontZ + 0.95);
    const receiverPoint = new THREE.Vector3(doorX + 0.55, 0, frontZ + 0.85);
    const queuePoint = new THREE.Vector3(doorX, 0, frontZ + 2.0);
    const indoorPoint = new THREE.Vector3(doorX, 0, frontZ - 1.1); // inside the house
    const approach = new THREE.Vector3(doorX, 0, frontZ + 2.4);    // end of the front path
    const roadAnchor = new THREE.Vector3(doorX, 0, laneZForRow(bz));

    anchors[s.id] = {
      id: s.id, doorFacing: facing,
      doorThreshold, knockPoint, receiverPoint, queuePoint,
      indoorPoint, approach, roadAnchor,
    };
  }
  return anchors;
}

// Which main lane serves a building, by its row.
function laneZForRow(bz) {
  return bz < 0 ? bz + 4.2 : bz - 4.2;  // a lane just in front of each row's doors
}

// ---- road / navigation graph ----------------------------------------------
// Nodes: each building's roadAnchor + approach + corridor junctions.
// Edges connect approach↔roadAnchor, roadAnchor↔corridor, and along corridors.
export function buildGraph(anchors) {
  const nodes = {};   // id -> Vector3
  const adj = {};     // id -> [{to, w}]
  const add = (id, v) => { nodes[id] = v; adj[id] = adj[id] || []; };
  const link = (a, b) => {
    const w = nodes[a].distanceTo(nodes[b]);
    adj[a].push({ to: b, w }); adj[b].push({ to: a, w });
  };

  // corridor spine: a few junctions along mid lane + the two row lanes
  // derive x-range from buildings
  const xs = STATIONS.map((s) => s.pos[0]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const topLane = -4.5 + 4.2, botLane = 5 - 4.2; // = -0.3 and 0.8 ; use row-front lanes
  const lanes = { top: laneZForRow(-4.5), bot: laneZForRow(5) };

  // junction nodes at each building x on its row lane, plus connectors between lanes at minX/maxX
  for (const s of STATIONS) {
    const [bx, bz] = s.pos;
    const jId = `J${s.id}`;
    add(jId, new THREE.Vector3(bx - s.size[0] * 0.22, 0, laneZForRow(bz)));
    // building approach + roadAnchor
    add(`A${s.id}`, anchors[s.id].approach.clone());
    add(`R${s.id}`, anchors[s.id].roadAnchor.clone());
    add(`K${s.id}`, anchors[s.id].knockPoint.clone());
    link(`A${s.id}`, `K${s.id}`);
    link(`R${s.id}`, `A${s.id}`);
    link(`R${s.id}`, jId);
  }

  // connect junctions along each lane (sorted by x)
  const byRow = { top: [], bot: [] };
  for (const s of STATIONS) (s.pos[1] < 0 ? byRow.top : byRow.bot).push(s);
  for (const row of ['top', 'bot']) {
    const sorted = byRow[row].sort((a, b) => a.pos[0] - b.pos[0]);
    for (let i = 0; i < sorted.length - 1; i++) link(`J${sorted[i].id}`, `J${sorted[i + 1].id}`);
  }

  // vertical connectors between the two lanes at the far-left and far-right columns
  const leftTop = byRow.top.reduce((m, s) => s.pos[0] < m.pos[0] ? s : m, byRow.top[0]);
  const leftBot = byRow.bot.reduce((m, s) => s.pos[0] < m.pos[0] ? s : m, byRow.bot[0]);
  const rightTop = byRow.top.reduce((m, s) => s.pos[0] > m.pos[0] ? s : m, byRow.top[0]);
  const rightBot = byRow.bot.reduce((m, s) => s.pos[0] > m.pos[0] ? s : m, byRow.bot[0]);
  link(`J${leftTop.id}`, `J${leftBot.id}`);
  link(`J${rightTop.id}`, `J${rightBot.id}`);
  // mid column connector (centre buildings 3 top & 6 bottom)
  const midTop = byRow.top.find((s) => Math.abs(s.pos[0]) < 1);
  const midBot = byRow.bot.find((s) => Math.abs(s.pos[0]) < 1);
  if (midTop && midBot) link(`J${midTop.id}`, `J${midBot.id}`);

  return { nodes, adj };
}

// Dijkstra shortest path between two node ids. Returns array of Vector3 or null.
export function findPath(graph, startId, goalId) {
  const { nodes, adj } = graph;
  const dist = {}, prev = {}, seen = {};
  for (const id in nodes) dist[id] = Infinity;
  dist[startId] = 0;
  const pq = [[0, startId]];
  while (pq.length) {
    pq.sort((a, b) => a[0] - b[0]);
    const [d, u] = pq.shift();
    if (seen[u]) continue; seen[u] = true;
    if (u === goalId) break;
    for (const { to, w } of (adj[u] || [])) {
      if (dist[u] + w < dist[to]) { dist[to] = dist[u] + w; prev[to] = u; pq.push([dist[to], to]); }
    }
  }
  if (dist[goalId] === Infinity) return null;
  const path = []; let c = goalId;
  while (c != null) { path.unshift(nodes[c].clone()); c = prev[c]; }
  return path;
}

// Full delivery route node ids: indoor→door→approach→road→...graph...→knock(receiver)
export function deliveryNodeIds(graph, fromId, toId) {
  // walk from sender's approach to receiver's knock through the graph
  return findPath(graph, `A${fromId}`, `K${toId}`);
}

// expanded building footprints for obstacle debug (not used to block the fixed
// graph, which is already routed around buildings, but exposed for Debug view)
export function footprints() {
  return STATIONS.map((s) => {
    const [bx, bz] = s.pos; const [w, d] = s.size;
    const pad = CHAR_RADIUS + CLEARANCE;
    return { id: s.id, min: [bx - w / 2 - pad, bz - d / 2 - pad], max: [bx + w / 2 + pad, bz + d / 2 + pad] };
  });
}
