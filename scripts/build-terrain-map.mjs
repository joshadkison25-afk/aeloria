/**
 * Builds terrain_map.json from map_layout.json:
 * - Voronoi(14 sites) → major region cells
 * - Union cells per terrain class (mountains, forests, plains, desert, coastal)
 * - Coastlines = polylines on the south/east "sea" margin of maritime regions
 * - Per-region movement / war / economy multipliers (0.35–1.25) from terrain + lore
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { Delaunay } from 'd3-delaunay';
import polyclip from 'polygon-clipping';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
const OUT = join(ROOT, 'public', 'data', 'terrain_map.json');

const layout = JSON.parse(readFileSync(join(ROOT, 'public', 'data', 'map_layout.json'), 'utf8'));
const regions = layout.regions;
const R = 1000;

const LORE = {
  mountains: ['Frostvale', 'Lostfeld', 'Gilgeth'],
  forests: ['Faerwood', 'Glenwood'],
  // Open land: heartland, marches, badlands (Groth = arid open war front)
  plains: ['Eldoria', 'Twin Cities', 'Eresteron', 'Farrock', 'Groth'],
  desert: ['Dur Khadur', 'Vilefin'],
  // Maritime: coastal ports + isles
  coastal: ['Tidefall', 'Dreadwind Isles'],
};

const sites = regions.map((r) => [r.center_x, r.center_y]);
const byId = Object.fromEntries(regions.map((r) => [r.region_id, r]));
const indexOf = (id) => regions.findIndex((r) => r.region_id === id);

const delaunay = Delaunay.from(sites);
const voronoi = delaunay.voronoi([0, 0, R, R]);

function ensureOrientation(ring) {
  const r = ring[0] === ring[ring.length - 1] ? ring.slice(0, -1) : ring.slice();
  if (r.length < 3) return ring;
  let a = 0;
  for (let i = 0, n = r.length; i < n; i += 1) {
    const j = (i + 1) % n;
    a += r[i][0] * r[j][1] - r[j][0] * r[i][1];
  }
  if (a < 0) r.reverse();
  r.push(r[0]);
  return r;
}

function toClip(ring) {
  return [[ring.map((p) => [round6(p[0]), round6(p[1])])]];
}

function round6(x) {
  return Math.round(x * 1e6) / 1e6;
}

function cellPoly(i) {
  const c = voronoi.cellPolygon(i);
  if (!c) return null;
  return toClip(ensureOrientation(c.map((p) => [p[0], p[1]])));
}

function unionGroup(ids) {
  const polys = [];
  for (const id of ids) {
    const i = indexOf(id);
    if (i < 0) continue;
    const p = cellPoly(i);
    if (p) polys.push(p);
  }
  if (polys.length === 0) return [];
  let acc = polys[0];
  for (let k = 1; k < polys.length; k += 1) {
    acc = polyclip.union(acc, polys[k]);
  }
  // flatten to list of linear rings for output
  const out = [];
  for (const mp of acc) for (const ring of mp) out.push(simplifyRing(ring, 6, 20));
  return out;
}

function simplifyRing(ring, minN, maxN) {
  const r = ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1] ? ring.slice(0, -1) : ring.slice();
  if (r.length <= maxN) return r.map((p) => [round6(p[0]), round6(p[1])]);
  const step = (r.length - 1) / (maxN - 1);
  const o = [];
  for (let k = 0; k < maxN; k += 1) {
    const t = k * step;
    const j = Math.floor(t) % r.length;
    const f = t - Math.floor(t);
    const a = r[j % r.length];
    const b = r[(j + 1) % r.length];
    o.push([round6(a[0] + f * (b[0] - a[0])), round6(a[1] + f * (b[1] - a[1]))]);
  }
  return o;
}

function coastPolylines() {
  // Eastern/southern margin: shelf where Tidefall + Dreadwind meet the map edge (lore: gulf, isles)
  return [
    [
      [R, 200],
      [R, 520],
      [880, 580],
      [780, R],
      [620, R],
    ],
    [
      [920, 100],
      [R, 120],
      [R, 240],
    ],
  ];
}

/** Multipliers: movement (higher = easier march), war (higher = advantage defender or attack in open), economy (trade/agri) */
const INFLUENCE = {
  Frostvale: {
    movement: 0.4,
    war: 0.75,
    economy: 0.38,
    note: 'Glacial passes; defense in depth; little surplus',
  },
  Lostfeld: { movement: 0.45, war: 0.68, economy: 0.82, note: 'Mining wealth; defensible vales' },
  Gilgeth: { movement: 0.46, war: 0.78, economy: 0.48, note: 'Fortified orc highlands' },
  Faerwood: { movement: 0.5, war: 0.72, economy: 0.42, note: 'Cover, ambush, no mass logistics' },
  Glenwood: { movement: 0.52, war: 0.7, economy: 0.48, note: 'Dense wood; elven home ground' },
  Eldoria: { movement: 0.88, war: 0.55, economy: 0.9, note: 'Noble roads; wealth and statecraft' },
  'Twin Cities': { movement: 0.95, war: 0.5, economy: 0.95, note: 'Hub; vulnerable if besieged' },
  Eresteron: { movement: 0.92, war: 0.52, economy: 1.05, note: 'Breadbasket; open battlefields' },
  Farrock: { movement: 0.9, war: 0.88, economy: 0.62, note: 'Legions; clear lines of attack' },
  Groth: { movement: 0.72, war: 0.82, economy: 0.35, note: 'Badlands; raid economy, harsh supply' },
  Vilefin: { movement: 0.62, war: 0.58, economy: 0.4, note: 'Rock plains; scrap and traps' },
  'Dur Khadur': { movement: 0.58, war: 0.48, economy: 0.95, note: 'Caravans; oasis trade' },
  Tidefall: { movement: 0.82, war: 0.45, economy: 1.12, note: 'Ports; naval mobility (off-map sea)' },
  'Dreadwind Isles': { movement: 0.75, war: 0.6, economy: 0.55, note: 'Isles; raiding, smuggling' },
};

const terrain_map = {
  version: 1,
  name: 'Aeloria terrain layers (derived from map_layout + lore)',
  coordinate_space: layout.coordinate_space,
  influence_legend: {
    movement: '1.0 = easy march (open plains, roads); <0.55 = very slow (ice, deep forest, desert sand)',
    war: '1.0 = strong positional advantage (defensive mountains) or open pitched battle; interpret per scenario',
    economy: '1.0 = baseline; >1.0 = trade / agriculture / mining bonus',
  },
  region_influence: {},
  /** Polygons in 0–1000, each array is a closed ring [x,y] (optional closing point de-duped) */
  mountains: unionGroup(LORE.mountains),
  forests: unionGroup(LORE.forests),
  plains: unionGroup(LORE.plains),
  desert: unionGroup(LORE.desert),
  /** Coastal + archipelago Voronoi union (land facing sea) */
  coastal_zones: unionGroup(LORE.coastal),
  /**
   * Polylines (open rings) for shore / deep-water boundary stylization
   * @type { number[][][] }
   */
  coastlines: coastPolylines().map((line) => line.map(([x, y]) => [round6(x), round6(y)])),
};

for (const r of regions) {
  const id = r.region_id;
  let kind = 'plains';
  if (LORE.mountains.includes(id)) kind = 'mountains';
  else if (LORE.forests.includes(id)) kind = 'forests';
  else if (LORE.plains.includes(id)) kind = 'plains';
  else if (LORE.desert.includes(id)) kind = 'desert';
  else if (LORE.coastal.includes(id)) kind = 'coastal';
  const inf = INFLUENCE[id] || { movement: 0.8, war: 0.55, economy: 0.7, note: 'default' };
  terrain_map.region_influence[id] = {
    layout_terrain: r.terrain_type,
    terrain_class: kind,
    movement: inf.movement,
    war: inf.war,
    economy: inf.economy,
    note: inf.note,
  };
}

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, JSON.stringify(terrain_map, null, 2), 'utf8');
console.log('Wrote', OUT);
