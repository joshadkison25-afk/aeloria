/**
 * Converts public/data/map_data.json into public/data/map_geo.json:
 * - MapLibre-ready GeoJSON FeatureCollection (RFC 7946)
 * - Properties: house_id, region_id, faction_id (initial owner)
 * - Simplifies rings (Douglas–Peucker), drops duplicate points, closed rings, valid CCW exteriors
 *
 * Input shapes:
 *   A) Array of { house_id, region_id, faction_id, polygon, neighbors?, terrain_type? }
 *   B) GeoJSON FeatureCollection (legacy) — house_id backfilled from id or region_id
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
const MAP_DATA = join(ROOT, 'public', 'data', 'map_data.json');
const HOUSES = join(ROOT, 'public', 'data', 'houses.json');
const OUT = join(ROOT, 'public', 'data', 'map_geo.json');

const DP_EPS = 0.35; /* 0–1000 map space; ~0.03% of span */
const MIN_POINT_DIST = 0.02;

function round6(n) {
  return Math.round(n * 1e6) / 1e6;
}

/** Signed area * 0.5; positive => CCW in y-up? For GeoJSON, exterior must be counter-clockwise (RFC 7952 / common libs). */
function ringSignedAreaClosed(ring) {
  const r = ring.length > 0 && samePt(ring[0], ring[ring.length - 1]) ? ring.slice(0, -1) : ring;
  if (r.length < 3) return 0;
  let a = 0;
  for (let i = 0, n = r.length; i < n; i += 1) {
    const j = (i + 1) % n;
    a += r[i][0] * r[j][1] - r[j][0] * r[i][1];
  }
  return a / 2;
}

function samePt(a, b) {
  return a[0] === b[0] && a[1] === b[1];
}

/** Ensure first ring of Polygon is counter-clockwise (GeoJSON / MapLibre expectation). */
function rewindExteriorRing(ring) {
  const closed =
    ring.length > 0 && !samePt(ring[0], ring[ring.length - 1]) ? [...ring, ring[0]] : ring;
  if (closed.length < 4) return closed;
  const area = ringSignedAreaClosed(closed);
  if (area < 0) {
    const inner = closed.slice(0, -1).reverse();
    return [...inner, inner[0]];
  }
  return closed;
}

function dedupeConsecutive(pts) {
  const o = [pts[0]];
  for (let i = 1; i < pts.length; i += 1) {
    if (Math.hypot(pts[i][0] - o[o.length - 1][0], pts[i][1] - o[o.length - 1][1]) >= MIN_POINT_DIST) {
      o.push(pts[i]);
    }
  }
  if (o.length > 1 && samePt(o[0], o[o.length - 1])) o.pop();
  return o;
}

function distToSeg(px, py, x1, y1, x2, y2) {
  const l2 = (x2 - x1) ** 2 + (y2 - y1) ** 2;
  if (l2 < 1e-12) return Math.hypot(px - x1, py - y1);
  let t = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (x1 + t * (x2 - x1)), py - (y1 + t * (y2 - y1)));
}

function douglasPeucker(pts, eps) {
  if (pts.length < 3) return pts;
  let dmax = 0;
  let idx = 0;
  const a = pts[0];
  const b = pts[pts.length - 1];
  for (let i = 1; i < pts.length - 1; i += 1) {
    const d = distToSeg(pts[i][0], pts[i][1], a[0], a[1], b[0], b[1]);
    if (d > dmax) {
      dmax = d;
      idx = i;
    }
  }
  if (dmax > eps) {
    const l = douglasPeucker(pts.slice(0, idx + 1), eps);
    const r = douglasPeucker(pts.slice(idx), eps);
    return l.slice(0, -1).concat(r);
  }
  return [a, b];
}

function simplifyRing(raw) {
  const deduped = dedupeConsecutive(raw);
  if (deduped.length < 3) return null;
  let simp = douglasPeucker(deduped, DP_EPS);
  if (simp.length < 3) simp = deduped;
  simp = dedupeConsecutive(simp);
  if (!samePt(simp[0], simp[simp.length - 1])) simp = [...simp, simp[0]];
  return rewindExteriorRing(simp);
}

function normalizePolygonCoords(coordinates) {
  if (!Array.isArray(coordinates) || coordinates.length === 0) return null;
  const firstRing = coordinates[0];
  const cleaned = [];
  for (const ring0 of [firstRing]) {
    if (!Array.isArray(ring0) || ring0.length < 3) return null;
    const asPairs = ring0.map((p) => [round6(p[0]), round6(p[1])]);
    const r = simplifyRing(asPairs);
    if (r) cleaned.push(r);
  }
  return cleaned.length ? cleaned : null;
}

function fromParcelArray(arr) {
  const features = [];
  for (const row of arr) {
    if (!row || !row.polygon) continue;
    const ring = row.polygon.map((p) => [round6(p[0]), round6(p[1])]);
    const norm = normalizePolygonCoords([ring]);
    if (!norm) continue;
    const houseId = String(row.house_id);
    const fac = String(row.faction_id ?? 'Unclaimed');
    features.push({
      type: 'Feature',
      id: houseId,
      properties: {
        house_id: houseId,
        region_id: String(row.region_id),
        faction_id: fac,
        terrain_type: row.terrain_type != null ? String(row.terrain_type) : undefined,
        neighbors: Array.isArray(row.neighbors) ? row.neighbors : undefined,
        name: String(row.house_id),
      },
      geometry: { type: 'Polygon', coordinates: norm },
    });
  }
  return { type: 'FeatureCollection', features };
}

function fromFeatureCollection(fc) {
  const features = [];
  for (const f of fc.features || []) {
    if (!f || f.type !== 'Feature') continue;
    const g = f.geometry;
    if (!g || (g.type !== 'Polygon' && g.type !== 'MultiPolygon')) continue;
    const p = f.properties || {};
    const houseId = String(
      p.house_id != null
        ? p.house_id
        : f.id != null
          ? f.id
          : p.region_id != null
            ? p.region_id
            : `feature-${features.length}`,
    );
    const regionId = String(p.region_id != null ? p.region_id : houseId);
    const faction = String(p.faction_id != null ? p.faction_id : 'Unclaimed');
    const ringSource =
      g.type === 'Polygon' ? g.coordinates : g.type === 'MultiPolygon' && g.coordinates[0] ? g.coordinates[0] : null;
    if (!ringSource) continue;
    const norm = normalizePolygonCoords(ringSource);
    if (!norm) continue;
    features.push({
      type: 'Feature',
      id: houseId,
      properties: {
        house_id: houseId,
        region_id: regionId,
        faction_id: faction,
        name: p.name != null ? String(p.name) : houseId,
        default_fill: p.default_fill,
        terrain_type: p.terrain_type,
        neighbors: p.neighbors,
      },
      geometry: { type: 'Polygon', coordinates: norm },
    });
  }
  return { type: 'FeatureCollection', features };
}

function attachDefaultFills(gj, factionColors) {
  for (const f of gj.features) {
    const fac = f.properties.faction_id;
    if (fac && !f.properties.default_fill && factionColors[fac]) {
      f.properties.default_fill = factionColors[fac];
    }
  }
  return gj;
}

function main() {
  const raw = JSON.parse(readFileSync(MAP_DATA, 'utf8'));
  let fc;
  if (Array.isArray(raw)) {
    fc = fromParcelArray(raw);
  } else if (raw && raw.type === 'FeatureCollection') {
    fc = fromFeatureCollection(raw);
  } else {
    throw new Error('map_data.json must be a parcel array or a GeoJSON FeatureCollection');
  }
  const houses = JSON.parse(readFileSync(HOUSES, 'utf8'));
  const factionColors = houses.factionColors || {};
  attachDefaultFills(fc, factionColors);
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, JSON.stringify(fc, null, 2), 'utf8');
  console.log('Wrote', OUT, 'features:', fc.features.length);
}

main();
