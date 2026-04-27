#!/usr/bin/env node
/**
 * Convert an Azgaar Fantasy Map Generator save (.map = JSON) into Aeloria `RegionDefinition[]`
 * pixel coordinates (MAP_WIDTH × MAP_HEIGHT, same convention as data/regions.ts).
 *
 * Workflow:
 * 1. Open https://azgaar.github.io/Fantasy-Map-Generator/ and generate a map.
 * 2. Use the in-app save/export that produces JSON (classic `.map` save **or** “Export” JSON like
 *    `Tidy Full ….json` from FMG ≥ ~1.11 with `info` + `pack.cells` as cell records).
 * 3. Run:
 *      node scripts/azgaar-map-to-aeloria-regions.mjs path/to/world.map
 *    Optional: --out data/regions.azgaar-generated.ts
 *
 * Notes:
 * - Regions follow Azgaar *states* (countries). State id 0 (wilderness / unassigned) is skipped.
 * - Polygons trace **shared Voronoi edges** between land cells of the state vs other states /
 *   water / map edge (uses pack.vertices + cells.v / cells.c). This follows FMG geometry so
 *   borders align with the exported map when your basemap matches the same export scale.
 * - Fallback: if a cell record has no v/c neighbor data, that state falls back to convex hull
 *   (a warning is printed).
 * - You still need lore: descriptions are placeholders. Merge into `data/regions.ts` or import
 *   this file from the map page while you iterate.
 *
 * License: Azgaar FMG is MIT; this script is for your repo only.
 */

import fs from 'node:fs';
import path from 'node:path';

const MAP_WIDTH = 1024;
const MAP_HEIGHT = 682;

function cross(o, a, b) {
  return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
}

/** Andrew's monotone chain — 2D convex hull. */
function convexHull(points) {
  const pts = [...points].sort((a, b) => (a[0] === b[0] ? a[1] - b[1] : a[0] - b[0]));
  if (pts.length < 3) return pts;
  const lower = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper = [];
  for (let i = pts.length - 1; i >= 0; i -= 1) {
    const p = pts[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  lower.pop();
  upper.pop();
  return lower.concat(upper);
}

function slug(s) {
  return String(s || 'region')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48) || 'region';
}

function deepFindPack(obj, depth = 0) {
  if (depth > 20 || !obj || typeof obj !== 'object') return null;
  const c = obj.cells;
  if (c && Array.isArray(c.p) && (Array.isArray(c.state) || c.state?.length != null) && obj.vertices) {
    return obj;
  }
  for (const k of Object.keys(obj)) {
    const hit = deepFindPack(obj[k], depth + 1);
    if (hit) return hit;
  }
  return null;
}

/** FMG ≥1.11 export: `pack.cells` is an array of { p, state, t, … } (or rarely a string-key map). */
function getModernCellList(pack) {
  const c = pack?.cells;
  if (Array.isArray(c)) return c.filter((x) => x && typeof x === 'object');
  if (!c || typeof c !== 'object' || Array.isArray(c.p)) return [];
  return Object.values(c).filter((x) => x && typeof x === 'object');
}

function isModernCellRecordExport(pack) {
  const list = getModernCellList(pack);
  if (list.length === 0) return false;
  const v0 = list[0];
  return typeof v0.state === 'number' && Array.isArray(v0.p) && v0.p.length >= 2;
}

function resolvePack(data) {
  if (data.pack?.cells && data.pack?.states && isModernCellRecordExport(data.pack)) {
    return data.pack;
  }
  return deepFindPack(data);
}

function findGraphSize(root, pack) {
  if (root.info?.width > 0 && root.info?.height > 0) {
    return { w: root.info.width, h: root.info.height };
  }
  const g =
    root.settings?.graph ||
    root.options?.graph ||
    root.map?.settings?.graph ||
    root.data?.settings?.graph;
  if (g?.width > 0 && g?.height > 0) return { w: g.width, h: g.height };
  let maxX = 0;
  let maxY = 0;
  const pts = pack?.cells?.p;
  if (Array.isArray(pts)) {
    for (const pt of pts) {
      if (pt && typeof pt[0] === 'number' && typeof pt[1] === 'number') {
        maxX = Math.max(maxX, pt[0]);
        maxY = Math.max(maxY, pt[1]);
      }
    }
  }
  if (maxX === 0 && isModernCellRecordExport(pack)) {
    for (const cell of getModernCellList(pack)) {
      if (cell?.p?.[0] != null && cell?.p?.[1] != null) {
        maxX = Math.max(maxX, cell.p[0]);
        maxY = Math.max(maxY, cell.p[1]);
      }
    }
  }
  if (maxX > 0 && maxY > 0) return { w: maxX, h: maxY };
  return { w: MAP_WIDTH, h: MAP_HEIGHT };
}

/** @param {number[]} arr */
function arrAt(arr, i) {
  if (!arr) return undefined;
  if (typeof arr[i] === 'number') return arr[i];
  return undefined;
}

function cellCenter(pack, idx) {
  const p = pack.cells.p?.[idx];
  if (p && typeof p[0] === 'number' && typeof p[1] === 'number') return [p[0], p[1]];
  const vs = pack.cells.v?.[idx];
  const vx = pack.vertices?.x;
  const vy = pack.vertices?.y;
  if (!vs || !vx || !vy) return null;
  let sx = 0;
  let sy = 0;
  let n = 0;
  for (const vi of vs) {
    const x = vx[vi];
    const y = vy[vi];
    if (typeof x === 'number' && typeof y === 'number') {
      sx += x;
      sy += y;
      n += 1;
    }
  }
  return n ? [sx / n, sy / n] : null;
}

/** Land heuristic: Azgaar uses distance field `t` — land > 0, water <= 0 when present. */
function isLandCell(pack, idx) {
  const t = arrAt(pack.cells.t, idx);
  if (t == null) return true;
  return t > 0;
}

function extractStateNames(pack) {
  const m = new Map();
  const raw = pack.states;
  if (!raw) return m;
  if (Array.isArray(raw)) {
    for (const s of raw) {
      if (!s || s.removed) continue;
      const id = s.i ?? s.state ?? s.id;
      if (id == null) continue;
      m.set(Number(id), String(s.name || `State ${id}`));
    }
    return m;
  }
  if (typeof raw === 'object') {
    for (const [k, s] of Object.entries(raw)) {
      if (!s || s.removed) continue;
      m.set(Number(k), String(s.name || k));
    }
  }
  return m;
}

function transformPoint(x, y, srcW, srcH) {
  const scale = Math.min(MAP_WIDTH / srcW, MAP_HEIGHT / srcH);
  const ox = (MAP_WIDTH - srcW * scale) / 2;
  const oy = (MAP_HEIGHT - srcH * scale) / 2;
  const mx = x * scale + ox;
  const my = y * scale + oy;
  return [Math.round(mx * 10) / 10, Math.round(my * 10) / 10];
}

/** Shoelace area (positive if CCW). */
function polygonArea(ring) {
  let a = 0;
  const n = ring.length;
  if (n < 3) return 0;
  for (let i = 0; i < n; i += 1) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[(i + 1) % n];
    a += x1 * y2 - x2 * y1;
  }
  return Math.abs(a) * 0.5;
}

/**
 * @param {number[]} ringVertIds
 * @param {number[]} vx
 * @param {number[]} vy
 * @param {number} srcW
 * @param {number} srcH
 * @returns {[number, number][]|null}
 */
function ringVertIdsToPolygon(ringVertIds, vx, vy, srcW, srcH) {
  const coords = [];
  const seen = new Set();
  for (const vid of ringVertIds) {
    if (typeof vid !== 'number' || vid < 0) continue;
    const x = vx[vid];
    const y = vy[vid];
    if (typeof x !== 'number' || typeof y !== 'number') continue;
    const [tx, ty] = transformPoint(x, y, srcW, srcH);
    const key = `${tx},${ty}`;
    if (seen.has(key)) continue;
    seen.add(key);
    coords.push([tx, ty]);
  }
  if (coords.length < 3) return null;
  return coords;
}

/** Parallel arrays or FMG object map `vertices[id] = { p:[x,y] }`. */
function extractVertexArrays(pack) {
  const vert = pack.vertices;
  if (!vert || typeof vert !== 'object') return null;
  if (Array.isArray(vert.x) && Array.isArray(vert.y) && vert.x.length === vert.y.length) {
    return { vx: vert.x, vy: vert.y };
  }
  const keys = Object.keys(vert).filter((k) => /^\d+$/.test(k));
  if (keys.length === 0) return null;
  const maxId = Math.max(...keys.map(Number));
  const vx = [];
  const vy = [];
  for (let i = 0; i <= maxId; i += 1) {
    const node = vert[String(i)];
    const p = node?.p;
    if (p && typeof p[0] === 'number' && typeof p[1] === 'number') {
      vx[i] = p[0];
      vy[i] = p[1];
    }
  }
  return { vx, vy };
}

/**
 * Classic pack: parallel arrays cells.v, cells.c, cells.state, cells.t
 * @returns {{ n: number, stateOf: (i:number)=>number, land: (i:number)=>boolean, verts: (i:number)=>number[]|null, neigh: (i:number)=>number[]|null }|null}
 */
function meshFromClassicPack(pack) {
  const n = pack.cells?.i?.length ?? pack.cells?.p?.length ?? pack.cells?.state?.length ?? 0;
  if (!n) return null;
  const xy = extractVertexArrays(pack);
  if (!xy) return null;
  const { vx, vy } = xy;
  const hasV = Array.isArray(pack.cells.v) && pack.cells.v.length >= n;
  const hasC = Array.isArray(pack.cells.c) && pack.cells.c.length >= n;
  if (!hasV || !hasC) return null;

  return {
    n,
    stateOf: (i) => Number(arrAt(pack.cells.state, i) ?? 0),
    land: (i) => isLandCell(pack, i),
    verts: (i) => {
      const row = pack.cells.v[i];
      return Array.isArray(row) ? row : null;
    },
    neigh: (i) => {
      const row = pack.cells.c[i];
      return Array.isArray(row) ? row : null;
    },
    vx,
    vy,
  };
}

/**
 * Modern: cells is array of { state, t, v, c, i?, p }
 */
function meshFromModernList(pack, modernList) {
  const xy = extractVertexArrays(pack);
  if (!xy) return null;
  const { vx, vy } = xy;
  const n = modernList.length;
  /** @type {Map<number, number>} */
  const byI = new Map();
  for (let idx = 0; idx < n; idx += 1) {
    const cell = modernList[idx];
    if (cell && typeof cell.i === 'number') byI.set(cell.i, idx);
  }
  const resolveNb = (nb) => {
    if (nb == null || nb < 0) return -1;
    if (byI.has(nb)) return byI.get(nb);
    if (nb < n && modernList[nb]) return nb;
    return -1;
  };

  /** FMG often stores `c` as neighbor cell ids without 1:1 edge order — match shared edge. */
  const edgeNeighbor = (cellIdx, v0, v1) => {
    const raw = modernList[cellIdx]?.c;
    if (!Array.isArray(raw)) return -1;
    for (const ref of raw) {
      const j = resolveNb(ref);
      if (j < 0 || j === cellIdx) continue;
      const nv = modernList[j]?.v;
      if (!Array.isArray(nv) || nv.length < 2) continue;
      const m = nv.length;
      for (let k = 0; k < m; k += 1) {
        const a = nv[k];
        const b = nv[(k + 1) % m];
        if ((a === v0 && b === v1) || (a === v1 && b === v0)) return j;
      }
    }
    return -1;
  };

  return {
    n,
    stateOf: (i) => Number(modernList[i]?.state ?? modernList[i]?.s ?? 0),
    land: (i) => {
      const t = modernList[i]?.t;
      if (t == null) return true;
      return t > 0;
    },
    verts: (i) => {
      const v = modernList[i]?.v;
      return Array.isArray(v) ? v : null;
    },
    neigh: (i) => {
      const c = modernList[i]?.c;
      if (!Array.isArray(c)) return null;
      return c.map(resolveNb);
    },
    edgeNeighbor,
    vx,
    vy,
  };
}

/** Neighbor cell index that shares directed edge (v0→v1) on Voronoi boundary, or -1. */
function neighborAcrossEdge(mesh, cellIdx, v0, v1) {
  if (mesh.edgeNeighbor) return mesh.edgeNeighbor(cellIdx, v0, v1);
  const c = mesh.neigh(cellIdx);
  const v = mesh.verts(cellIdx);
  if (!c || !v || c.length !== v.length) return -1;
  const vn = v.length;
  for (let k = 0; k < vn; k += 1) {
    if (v[k] === v0 && v[(k + 1) % vn] === v1) {
      const nb = c[k];
      return nb == null || nb < 0 ? -1 : nb;
    }
  }
  return -1;
}

/**
 * Collect boundary segments as undirected vertex-id pairs for all land cells in stateId.
 */
function boundarySegmentsForState(mesh, stateId) {
  const segments = [];
  let any = false;
  for (let i = 0; i < mesh.n; i += 1) {
    if (!mesh.land(i)) continue;
    if (mesh.stateOf(i) !== stateId) continue;
    const v = mesh.verts(i);
    if (!v || v.length < 3) continue;
    any = true;
    const vn = v.length;
    for (let k = 0; k < vn; k += 1) {
      const v0 = v[k];
      const v1 = v[(k + 1) % vn];
      if (typeof v0 !== 'number' || typeof v1 !== 'number') continue;
      const nb = neighborAcrossEdge(mesh, i, v0, v1);
      let boundary = false;
      if (nb < 0) boundary = true;
      else if (!mesh.land(nb)) boundary = true;
      else if (mesh.stateOf(nb) !== stateId) boundary = true;
      if (boundary) segments.push([v0, v1]);
    }
  }
  if (!any) return null;
  return segments;
}

/**
 * Trace polygons from segments; return largest polygon in pixel space.
 */
function largestPolygonFromSegments(segments, vx, vy, srcW, srcH) {
  /** @type {Map<number, number[]>} */
  const adj = new Map();
  const add = (a, b) => {
    if (!adj.has(a)) adj.set(a, []);
    adj.get(a).push(b);
  };
  for (const [a, b] of segments) {
    add(a, b);
    add(b, a);
  }
  const edgeKey = (a, b) => (a < b ? `${a}|${b}` : `${b}|${a}`);
  /** @type {Set<string>} */
  const used = new Set();
  const rings = [];

  for (const a of adj.keys()) {
    for (const b of adj.get(a)) {
      const k = edgeKey(a, b);
      if (used.has(k)) continue;
      const ring = [];
      let cur = a;
      let prev = -1;
      const start = a;
      for (let step = 0; step < segments.length * 6 + 20; step += 1) {
        ring.push(cur);
        const nexts = adj.get(cur) || [];
        let nx = null;
        for (const cand of nexts) {
          if (cand === prev) continue;
          const ck = edgeKey(cur, cand);
          if (!used.has(ck)) {
            nx = cand;
            break;
          }
        }
        if (nx == null) {
          ring.length = 0;
          break;
        }
        used.add(edgeKey(cur, nx));
        prev = cur;
        cur = nx;
        if (cur === start) break;
      }
      if (ring.length >= 3) rings.push(ring);
    }
  }

  let best = null;
  let bestArea = 0;
  for (const rv of rings) {
    const poly = ringVertIdsToPolygon(rv, vx, vy, srcW, srcH);
    if (!poly) continue;
    const a = polygonArea(poly);
    if (a > bestArea) {
      bestArea = a;
      best = poly;
    }
  }
  return best;
}

function polygonForState(mesh, stateId, hullFallbackPoints, srcW, srcH) {
  if (mesh) {
    const segs = boundarySegmentsForState(mesh, stateId);
    if (segs && segs.length >= 3) {
      const traced = largestPolygonFromSegments(segs, mesh.vx, mesh.vy, srcW, srcH);
      if (traced) return { coords: traced, method: 'voronoi' };
    }
  }
  if (hullFallbackPoints.length >= 3) {
    const hull = convexHull(hullFallbackPoints);
    if (hull.length >= 3) return { coords: hull.map(([x, y]) => [x, y]), method: 'hull' };
  }
  return null;
}

function main() {
  const argv = process.argv.slice(2);
  let outPath = path.join('data', 'regions.azgaar-generated.ts');
  const files = [];
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--out') {
      outPath = argv[i + 1];
      i += 1;
    } else if (!argv[i].startsWith('-')) {
      files.push(argv[i]);
    }
  }
  if (files.length === 0) {
    const def = path.join(process.cwd(), 'Tidy Full 2026-04-26-20-50.json');
    if (fs.existsSync(def)) {
      files.push(def);
      console.warn(`Using bundled Azgaar export: ${path.basename(def)}`);
    } else {
      console.error('Usage: node scripts/azgaar-map-to-aeloria-regions.mjs <file.json|.map> [--out path.ts]');
      process.exit(1);
    }
  }
  const inPath = files[0];
  const rawText = fs.readFileSync(inPath, 'utf8');
  let data;
  try {
    data = JSON.parse(rawText);
  } catch {
    console.error('Could not parse JSON. If this is a .gz file, decompress it first.');
    process.exit(1);
  }

  const pack = resolvePack(data);
  if (!pack) {
    console.error(
      'Could not find Azgaar pack. Need classic .map JSON or FMG export with top-level `pack` + cell records.',
    );
    process.exit(1);
  }

  const src = findGraphSize(data, pack);
  const stateNames = extractStateNames(pack);

  /** @type {Map<number, [number, number][]>} */
  const byState = new Map();

  if (isModernCellRecordExport(pack)) {
    for (const cell of getModernCellList(pack)) {
      const st = cell.state;
      if (st == null || st === 0) continue;
      const t = cell.t;
      if (t != null && t <= 0) continue;
      const p = cell.p;
      if (!p || typeof p[0] !== 'number' || typeof p[1] !== 'number') continue;
      const [tx, ty] = transformPoint(p[0], p[1], src.w, src.h);
      if (!byState.has(st)) byState.set(st, []);
      byState.get(st).push([tx, ty]);
    }
  } else {
    const n = pack.cells.i?.length ?? pack.cells.p?.length ?? pack.cells.state?.length ?? 0;
    if (!n) {
      console.error('No cells found in pack.');
      process.exit(1);
    }
    for (let idx = 0; idx < n; idx += 1) {
      const st = arrAt(pack.cells.state, idx);
      if (st == null || st === 0) continue;
      if (!isLandCell(pack, idx)) continue;
      const center = cellCenter(pack, idx);
      if (!center) continue;
      const [tx, ty] = transformPoint(center[0], center[1], src.w, src.h);
      if (!byState.has(st)) byState.set(st, []);
      byState.get(st).push([tx, ty]);
    }
  }

  if (byState.size === 0) {
    console.error('No state land cells found — check export or land mask (t > 0).');
    process.exit(1);
  }

  const modernList = isModernCellRecordExport(pack) ? getModernCellList(pack) : null;
  let mesh = modernList ? meshFromModernList(pack, modernList) : meshFromClassicPack(pack);
  if (!mesh) console.warn('No Voronoi mesh (vertices/neighbors); using convex hulls only.');

  let traced = 0;
  let hullUsed = 0;
  const regions = [];
  const usedIds = new Set();
  for (const [stateId, pts] of byState) {
    const poly = polygonForState(mesh, stateId, pts, src.w, src.h);
    if (!poly || poly.coords.length < 3) continue;
    if (poly.method === 'voronoi') traced += 1;
    else hullUsed += 1;
    const name = stateNames.get(stateId) || `Region ${stateId}`;
    let id = slug(name);
    let suffix = 0;
    while (usedIds.has(id)) {
      suffix += 1;
      id = `${slug(name)}-${suffix}`;
    }
    usedIds.add(id);
    regions.push({
      id,
      name,
      description: `(Generated from Azgaar state “${name}”. Replace with lore.)`,
      coordinates: poly.coords,
    });
  }

  if (mesh) console.warn(`Region outlines: ${traced} Voronoi-traced, ${hullUsed} convex-hull fallback.`);

  regions.sort((a, b) => a.name.localeCompare(b.name));

  const pretty = `/**
 * AUTO-GENERATED by scripts/azgaar-map-to-aeloria-regions.mjs from Azgaar FMG.
 * Source file: ${path.basename(inPath)}
 * — Merge into data/regions.ts or temporarily point the map at these regions.
 */
import type { RegionDefinition } from './regions';

export const regionsAzgaarGenerated: RegionDefinition[] = [
${regions
  .map((r) => {
    const coords = r.coordinates.map(([x, y]) => `[${x}, ${y}]`).join(',\n      ');
    return `  {
    id: ${JSON.stringify(r.id)},
    name: ${JSON.stringify(r.name)},
    description: ${JSON.stringify(r.description)},
    coordinates: [
      ${coords},
    ],
  }`;
  })
  .join(',\n')}
];
`;

  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, pretty, 'utf8');
  console.log(`Wrote ${regions.length} regions to ${outPath}`);
}

main();
