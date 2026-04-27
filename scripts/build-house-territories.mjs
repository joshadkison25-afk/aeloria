/**
 * Partitions 0–1000 space into major regions (Voronoi of map_layout centers),
 * then slices each major cell into house/clan subregions (wedge + clip).
 * Output: public/data/map_data.json (array) + public/data/territory_parcels.geojson (for MapLibre).
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { Delaunay } from 'd3-delaunay';
import polyclip from 'polygon-clipping';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
const OUT_DIR = join(ROOT, 'public', 'data');

const layout = JSON.parse(readFileSync(join(ROOT, 'public', 'data', 'map_layout.json'), 'utf8'));
const majorRegions = layout.regions;

/** Subregions: major `region_id` -> list of { house_id, faction_id? } (unique house_id) */
const SUBS = {
  Frostvale: [
    { house_id: 'frostvale-adkison', faction_id: 'The Wintermark' },
    { house_id: 'frostvale-mcintosh', faction_id: 'The Wintermark' },
    { house_id: 'frostvale-holter', faction_id: 'The Wintermark' },
    { house_id: 'frostvale-duval', faction_id: 'The Wintermark' },
  ],
  Faerwood: [
    { house_id: 'faerwood-verlorn', faction_id: 'Shadow Court' },
    { house_id: 'faerwood-nightborn', faction_id: 'Shadow Court' },
    { house_id: 'faerwood-shadowveil', faction_id: 'Shadow Court' },
  ],
  Eldoria: [
    { house_id: 'eldoria-lefleur', faction_id: 'Twin Cities' },
    { house_id: 'eldoria-vaelith', faction_id: 'Twin Cities' },
    { house_id: 'eldoria-duskcourt', faction_id: 'Twin Cities' },
  ],
  'Twin Cities': [
    { house_id: 'twin-bower', faction_id: 'Twin Cities' },
    { house_id: 'twin-binx', faction_id: 'Twin Cities' },
    { house_id: 'twin-dale', faction_id: 'Twin Cities' },
  ],
  Eresteron: [
    { house_id: 'eresteron-aurand', faction_id: 'Twin Cities' },
    { house_id: 'eresteron-braafhart', faction_id: 'Twin Cities' },
    { house_id: 'eresteron-goldvale', faction_id: 'Twin Cities' },
  ],
  Farrock: [
    { house_id: 'farrock-ember', faction_id: 'Varkuun' },
    { house_id: 'farrock-ironmarch', faction_id: 'Varkuun' },
    { house_id: 'farrock-vanward', faction_id: 'Varkuun' },
  ],
  Gilgeth: [
    { house_id: 'gilgeth-blackblood', faction_id: 'Gilgeth Clans' },
    { house_id: 'gilgeth-ironhide', faction_id: 'Gilgeth Clans' },
    { house_id: 'gilgeth-redtusk', faction_id: 'Gilgeth Clans' },
  ],
  Groth: [
    { house_id: 'groth-mijid', faction_id: 'Groth Clans' },
    { house_id: 'groth-ashfang', faction_id: 'Groth Clans' },
    { house_id: 'groth-syncar', faction_id: 'Groth Clans' },
  ],
  Vilefin: [
    { house_id: 'vilefin-bloodware', faction_id: 'Vilefin' },
    { house_id: 'vilefin-cogtooth', faction_id: 'Vilefin' },
    { house_id: 'vilefin-rustfang', faction_id: 'Vilefin' },
  ],
  Lostfeld: [
    { house_id: 'lostfeld-goldfinger', faction_id: 'Lostfeld' },
    { house_id: 'lostfeld-runewarden', faction_id: 'Lostfeld' },
    { house_id: 'lostfeld-ironmaul', faction_id: 'Lostfeld' },
  ],
  'Dur Khadur': [
    { house_id: 'dur-gross', faction_id: 'Dur Khadur' },
    { house_id: 'dur-galfazzar', faction_id: 'Dur Khadur' },
    { house_id: 'dur-vercenti', faction_id: 'Dur Khadur' },
  ],
  Glenwood: [
    { house_id: 'glen-wood', faction_id: 'Glenhaven' },
    { house_id: 'glen-darkleaf', faction_id: 'Glenhaven' },
    { house_id: 'glen-mistafae', faction_id: 'Glenhaven' },
  ],
  Tidefall: [
    { house_id: 'tide-ver-meer', faction_id: 'Tidefall' },
    { house_id: 'tide-highland-dusken', faction_id: 'Tidefall' },
    { house_id: 'tide-fish', faction_id: 'Tidefall' },
    { house_id: 'tide-mcgowan', faction_id: 'Tidefall' },
  ],
  'Dreadwind Isles': [
    { house_id: 'dreadwind-blacktide', faction_id: 'Dreadwind Isles' },
    { house_id: 'dreadwind-stormward', faction_id: 'Dreadwind Isles' },
    { house_id: 'dreadwind-reef', faction_id: 'Dreadwind Isles' },
  ],
};

function toClip(poly) {
  if (!poly || poly.length < 3) return null;
  const ring = poly.map((p) => [round6(p[0]), round6(p[1])]);
  if (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) {
    ring.push([...ring[0]]);
  }
  return [ring];
}

function round6(x) {
  return Math.round(x * 1e6) / 1e6;
}

function ringArea(ring) {
  let a = 0;
  for (let i = 0; i < ring.length - 1; i += 1) {
    a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
  }
  return a / 2;
}

/** Ensure positive area (CCW) for polyclip */
function ensureOrientation(ring) {
  const r = ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1] ? ring.slice(0, -1) : ring.slice();
  if (r.length < 3) return ring;
  let a = 0;
  for (let i = 0, n = r.length; i < n; i += 1) {
    const j = (i + 1) % n;
    a += r[i][0] * r[j][1] - r[j][0] * r[i][1];
  }
  if (a < 0) {
    r.reverse();
  }
  r.push(r[0]);
  return r;
}

function centroid(ring) {
  const r =
    ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1]
      ? ring.slice(0, -1)
      : ring.slice();
  let cx = 0;
  let cy = 0;
  let a = 0;
  for (let i = 0, n = r.length; i < n; i += 1) {
    const j = (i + 1) % n;
    const c = r[i][0] * r[j][1] - r[j][0] * r[i][1];
    a += c;
    cx += (r[i][0] + r[j][0]) * c;
    cy += (r[i][1] + r[j][1]) * c;
  }
  a *= 0.5;
  if (Math.abs(a) < 1e-6) {
    return [r.reduce((s, p) => s + p[0], 0) / n, r.reduce((s, p) => s + p[1], 0) / n];
  }
  return [cx / (6 * a), cy / (6 * a)];
}

function triWedge(cx, cy, t0, t1) {
  const R = 5000;
  return [
    [cx, cy],
    [cx + R * Math.cos(t0), cy + R * Math.sin(t0)],
    [cx + R * Math.cos(t1), cy + R * Math.sin(t1)],
    [cx, cy],
  ];
}

function polyclipIntersect(a, b) {
  const out = polyclip.intersection(a, b);
  if (!out || out.length === 0) return null;
  let best = out[0][0];
  let bestA = Math.abs(ringArea(best));
  for (const mp of out) {
    for (const ring of mp) {
      const ar = Math.abs(ringArea(ring));
      if (ar > bestA) {
        bestA = ar;
        best = ring;
      }
    }
  }
  return [ensureOrientation(best)];
}

function resampleToOrganic(ring, minP, maxP) {
  const r =
    ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1]
      ? ring.slice(0, -1)
      : ring.slice();
  if (r.length < 3) return ring;
  let target = minP + ((r.length * 7) % (maxP - minP + 1));
  target = Math.max(minP, Math.min(maxP, target));

  /** Douglas–Peucker light */
  function distPointLine(px, py, x1, y1, x2, y2) {
    const l2 = (x2 - x1) ** 2 + (y2 - y1) ** 2;
    if (l2 < 1e-9) return Math.hypot(px - x1, py - y1);
    let t = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2;
    t = Math.max(0, Math.min(1, t));
    const nx = x1 + t * (x2 - x1);
    const ny = y1 + t * (y2 - y1);
    return Math.hypot(px - nx, py - ny);
  }
  function rdps(pts, eps) {
    if (pts.length <= 2) return pts;
    let dmax = 0;
    let idx = 0;
    const end = pts.length - 1;
    for (let i = 1; i < end; i += 1) {
      const d = distPointLine(pts[i][0], pts[i][1], pts[0][0], pts[0][1], pts[end][0], pts[end][1]);
      if (d > dmax) {
        dmax = d;
        idx = i;
      }
    }
    if (dmax > eps) {
      const l = rdps(pts.slice(0, idx + 1), eps);
      const r2 = rdps(pts.slice(idx), eps);
      return l.slice(0, -1).concat(r2);
    }
    return [pts[0], pts[end]];
  }

  const closed = r[0][0] === r[r.length - 1][0] && r[0][1] === r[r.length - 1][1] ? r : [...r, r[0]];
  const eps = 1.2;
  let simplified = closed.length < 5 ? closed : rdps(closed, eps);
  if (simplified[0] !== simplified[simplified.length - 1]) simplified = [...simplified, simplified[0]];

  const flat = simplified.slice(0, -1);
  if (flat.length === target) {
    return flat;
  }
  if (flat.length < target) {
    const out = [flat[0]];
    for (let i = 0; i < flat.length - 1; i += 1) {
      const p0 = flat[i];
      const p1 = flat[i + 1];
      const need = target - (flat.length - (i + 1) + out.length);
      const nExtra = i === flat.length - 2 ? target - out.length - 1 : 0;
      for (let k = 1; k <= nExtra; k += 1) {
        const t = k / (nExtra + 1);
        const ox = (Math.sin((i + k) * 1.7) * 0.4 + (Math.random() - 0.5) * 0.2) * 0.1;
        const oy = (Math.cos((i + k) * 1.3) * 0.4 + (Math.random() - 0.5) * 0.2) * 0.1;
        out.push([p0[0] + t * (p1[0] - p0[0]) + ox, p0[1] + t * (p1[1] - p0[1]) + oy]);
      }
    }
    out.push(flat[flat.length - 1]);
    while (out.length < target) {
      const m = out.length;
      out.splice(m, 0, [out[0][0] * 0.5 + out[1][0] * 0.5, out[0][1] * 0.5 + out[1][1] * 0.5]);
    }
  } else {
    const step = (flat.length - 1) / (target - 1);
    const out = [];
    for (let k = 0; k < target; k += 1) {
      const t = k * step;
      const j = Math.floor(t);
      const f = t - j;
      const a = flat[j % flat.length];
      const b = flat[(j + 1) % flat.length];
      out.push([a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])]);
    }
  }

  return out.slice(0, target);
}

const EPS = 1.5;

function segKey(a, b) {
  const s = round6((a[0] + b[0]) * 0.5);
  const t = round6((a[1] + b[1]) * 0.5);
  const p1 = `${round6(a[0])},${round6(a[1])}`;
  const p2 = `${round6(b[0])},${round6(b[1])}`;
  return p1 < p2 ? `${p1}|${p2}` : `${p2}|${p1}`;
}

function buildEdgeMap(territories) {
  const map = new Map();
  for (const t of territories) {
    const ring = t.polygon;
    for (let i = 0; i < ring.length; i += 1) {
      const a = ring[i];
      const b = ring[(i + 1) % ring.length];
      const k = segKey(a, b);
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(t.house_id);
    }
  }
  return map;
}

function addNeighbors(territories) {
  const em = buildEdgeMap(territories);
  for (const t of territories) {
    t.neighbors = [];
  }
  for (const [, ids] of em) {
    if (ids.length < 2) continue;
    const u = [...new Set(ids)];
    for (let i = 0; i < u.length; i += 1) {
      for (let j = i + 1; j < u.length; j += 1) {
        const a = territories.find((x) => x.house_id === u[i]);
        const b = territories.find((x) => x.house_id === u[j]);
        if (a && b && !a.neighbors.includes(b.house_id)) a.neighbors.push(b.house_id);
        if (a && b && !b.neighbors.includes(a.house_id)) b.neighbors.push(a.house_id);
      }
    }
  }
}

// --------- main ----------
const sites = majorRegions.map((r) => [r.center_x, r.center_y]);
const delaunay = Delaunay.from(sites);
const voronoi = delaunay.voronoi([0, 0, 1000, 1000]);
const out = [];
const TOL = 1.2;
for (let i = 0; i < majorRegions.length; i += 1) {
  const mr = majorRegions[i];
  const list = SUBS[mr.region_id];
  if (!list) {
    throw new Error(`No SUBS for ${mr.region_id}`);
  }
  let cell = voronoi.cellPolygon(i);
  if (!cell) throw new Error(`No Voronoi cell for index ${i} ${mr.region_id}`);
  let parentRing = cell.map((p) => [p[0], p[1]]);
  parentRing = ensureOrientation(parentRing);
  const P = toClip([parentRing]);
  const [ccx, ccy] = centroid(parentRing);
  const n = list.length;
  for (let k = 0; k < n; k += 1) {
    const j = k;
    const j0 = 2.2 * (j * 13) * 0.0001;
    const t0 = (2 * Math.PI * k) / n + 0.04 * Math.sin(j) + j0;
    const t1 = (2 * Math.PI * (k + 1)) / n + 0.04 * Math.sin(k + 1) + j0;
    const w = triWedge(ccx, ccy, t0, t1);
    const W = toClip([w]);
    let piece = polyclipIntersect(P, W);
    if (!piece) {
      const w2 = triWedge(ccx, ccy, t0, t1);
      const W2 = toClip([w2]);
      piece = polyclipIntersect(P, W2);
    }
    if (!piece) {
      throw new Error(`empty slice ${mr.region_id} ${k}`);
    }
    let ring0 = ensureOrientation(piece[0][0]);
    if (ring0[0][0] !== ring0[ring0.length - 1][0] || ring0[0][1] !== ring0[ring0.length - 1][1]) {
      ring0 = [...ring0, ring0[0]];
    }
    const unclosed = ring0.length > 1 && ring0[0] === ring0[ring0.length - 1] ? ring0.slice(0, -1) : ring0;
    const poly = resampleToOrganic(unclosed, 5, 8);
    const meta = list[k];
    out.push({
      house_id: meta.house_id,
      region_id: mr.region_id,
      terrain_type: mr.terrain_type,
      faction_id: meta.faction_id,
      polygon: poly.map((p) => [round6(p[0]), round6(p[1])]),
      neighbors: [],
    });
  }
}
addNeighbors(out);

// serialize without neighbors filled twice - addNeighbors set in place
const exportArr = out.map((t) => ({
  house_id: t.house_id,
  region_id: t.region_id,
  terrain_type: t.terrain_type,
  faction_id: t.faction_id,
  polygon: t.polygon,
  neighbors: [...new Set(t.neighbors)].sort(),
}));

const geo = {
  type: 'FeatureCollection',
  features: out.map((t) => {
    const coords = t.polygon.map((p) => [p[0], p[1]]);
    if (coords[0][0] !== coords[coords.length - 1][0] || coords[0][1] !== coords[coords.length - 1][1]) {
      coords.push([...coords[0]]);
    }
    return {
      type: 'Feature',
      id: t.house_id,
      properties: {
        house_id: t.house_id,
        region_id: t.region_id,
        name: t.house_id,
        terrain_type: t.terrain_type,
        faction_id: t.faction_id,
        neighbors: t.neighbors,
      },
      geometry: { type: 'Polygon', coordinates: [coords] },
    };
  }),
};

mkdirSync(OUT_DIR, { recursive: true });
writeFileSync(join(OUT_DIR, 'map_data.json'), JSON.stringify(exportArr, null, 2), 'utf8');
writeFileSync(join(OUT_DIR, 'territory_parcels.geojson'), JSON.stringify(geo, null, 2), 'utf8');
console.log('Wrote', exportArr.length, 'territories to public/data/map_data.json and territory_parcels.geojson');
