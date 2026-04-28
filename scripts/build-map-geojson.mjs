/**
 * Builds public/data/map.geojson from:
 *   - public/data/map_layout.json (realm centers + lore geography from design_principles)
 *   - public/data/realm_houses.json (house_id, faction_id per realm — same source as territory build)
 *
 * One bounded Voronoi cell per house: non-overlapping polygons tiling [0,1000]², shared borders, no gaps.
 * Spatial layout follows the reference “AI readable” faction map and map_layout neighbor logic (y = north).
 *
 * Note: lore_docs/maps/map_core.json is a separate hex editor save (ownership TBD); authoritative layout text
 * lives in map_layout.json in this repo.
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { Delaunay } from 'd3-delaunay';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
const OUT = join(ROOT, 'public', 'data', 'map.geojson');

const R = 1000;

function mulberry32(a) {
  return function () {
    let t = (a += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const rand = mulberry32(0xa0107a);

function round6(n) {
  return Math.round(n * 1e6) / 1e6;
}

/** CCW, closed ring for GeoJSON exteriors. */
function ensureOrientation(ring) {
  if (!ring || ring.length < 3) return ring;
  const r =
    ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1]
      ? ring.slice(0, -1)
      : ring.slice();
  if (r.length < 3) {
    r.push(r[0]);
    return r;
  }
  let a = 0;
  for (let i = 0, n = r.length; i < n; i += 1) {
    const j = (i + 1) % n;
    a += r[i][0] * r[j][1] - r[j][0] * r[i][1];
  }
  if (a < 0) r.reverse();
  r.push(r[0]);
  return r;
}

/** n house seed points around realm center (organic cluster). */
function clusterSites(cx, cy, n, rng) {
  const out = [];
  const base = rng() * Math.PI * 2;
  const radBase = n >= 4 ? 26 : 20;
  for (let k = 0; k < n; k += 1) {
    const t = (2 * Math.PI * k) / n + base * 0.12 + (rng() - 0.5) * 0.38;
    const rad = radBase + rng() * 24 + (k % 2) * 7;
    let x = cx + Math.cos(t) * rad;
    let y = cy + Math.sin(t) * rad;
    x = Math.min(R - 6, Math.max(6, x));
    y = Math.min(R - 6, Math.max(6, y));
    out.push([x, y]);
  }
  return out;
}

const layout = JSON.parse(readFileSync(join(ROOT, 'public', 'data', 'map_layout.json'), 'utf8'));
const realmHouses = JSON.parse(readFileSync(join(ROOT, 'public', 'data', 'realm_houses.json'), 'utf8'));

const sites = [];
const meta = [];

for (const reg of layout.regions) {
  const rid = reg.region_id;
  const list = realmHouses[rid];
  if (!list?.length) {
    throw new Error(`realm_houses.json missing entries for ${rid}`);
  }
  const cs = clusterSites(reg.center_x, reg.center_y, list.length, rand);
  for (let k = 0; k < list.length; k += 1) {
    sites.push([cs[k][0], cs[k][1]]);
    meta.push({
      house_id: list[k].house_id,
      realm_id: rid,
      faction_id: list[k].faction_id,
    });
  }
}

const delaunay = Delaunay.from(sites);
const voronoi = delaunay.voronoi([0, 0, R, R]);

const features = [];
for (let i = 0; i < sites.length; i += 1) {
  const poly = voronoi.cellPolygon(i);
  if (!poly) throw new Error(`missing Voronoi cell ${i}`);
  const ring = ensureOrientation(poly.map((p) => [round6(p[0]), round6(p[1])]));
  if (ring.length < 4) throw new Error(`degenerate cell ${i}`);
  features.push({
    type: 'Feature',
    id: meta[i].house_id,
    properties: {
      house_id: meta[i].house_id,
      realm_id: meta[i].realm_id,
      faction_id: meta[i].faction_id,
    },
    geometry: { type: 'Polygon', coordinates: [ring] },
  });
}

const fc = { type: 'FeatureCollection', features };

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, JSON.stringify(fc, null, 2), 'utf8');
const totalHouses = Object.values(realmHouses).reduce((s, h) => s + h.length, 0);
console.log(`Wrote ${OUT} — ${features.length} features (${totalHouses} houses in realm_houses.json)`);
