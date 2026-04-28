#!/usr/bin/env node
/**
 * CK3-style atlas generator.
 *
 * The map geometry is continent-first: a hand-authored Aeloria land silhouette is
 * tiled with hex cells, then every land hex is assigned to a house/clan seed from
 * public/data/realm_houses.json. House provinces are derived from those hexes.
 *
 * Outputs:
 *   - data/regions.lore-houses.ts
 *   - public/aeloria-data-basemap.svg
 *   - public/aeloria-lore-houses-basemap.svg (compat alias)
 */
import fs from 'node:fs';
import path from 'node:path';
import polygonClipping from 'polygon-clipping';

const ROOT = path.join(import.meta.dirname, '..');
const REALM_HOUSES = path.join(ROOT, 'public', 'data', 'realm_houses.json');
const MAP_LAYOUT = path.join(ROOT, 'public', 'data', 'map_layout.json');
const OUT_TS = path.join(ROOT, 'data', 'regions.lore-houses.ts');
const OUT_BASEMAP = path.join(ROOT, 'public', 'aeloria-data-basemap.svg');
const OUT_COMPAT_BASEMAP = path.join(ROOT, 'public', 'aeloria-lore-houses-basemap.svg');
const OUT_KINGDOM_PREVIEW = path.join(ROOT, 'public', 'aeloria-kingdom-preview.svg');
const OUT_HOUSE_PREVIEW = path.join(ROOT, 'public', 'aeloria-house-preview.svg');

const WIDTH = 1024;
const HEIGHT = 682;
const HEX_R = 5;
// Pointy-top hex grid: exact vertex sharing between neighbors.
// HEX_H = flat-to-flat diameter = R*√3
const HEX_H = Math.sqrt(3) * HEX_R;
// Same-row x spacing = R*√3 (one full flat-to-flat width)
const HEX_X_STEP = HEX_H;
// Row-to-row y spacing = R*1.5
const HEX_Y_STEP = HEX_R * 1.5;

// "The Shattered Crown" — epic redesign.
// Clockwise from NW. North = top (y≈0), South = bottom (y≈682).
// Designed to fill almost the entire 1024×682 viewport.
const MAIN_CONTINENT = [
  //  NW — west coast rising north
  [  48, 212],
  [  35, 162],
  [  62, 108],
  [ 118,  62],
  //  Frostvale fjord coast — four ragged peaks with deep bays between them
  [ 178,  32],
  [ 242,  10],  // peak 1
  [ 298,  40],
  [ 348,   8],  // peak 2 (absolute northernmost)
  [ 405,  36],
  [ 458,  10],  // peak 3
  [ 518,  32],
  [ 568,  10],  // peak 4
  [ 628,  42],
  //  Farrock headland — major NE cape jutting toward the Dreadwind channel
  [ 682,  56],
  [ 738,  86],
  [ 794, 134],  // headland tip
  [ 830, 198],
  //  East coast — widens at Tidefall, gentle concave near Glenwood
  [ 858, 275],
  [ 880, 355],
  [ 902, 405],  // widest east reach (Tidefall coastal zone)
  [ 890, 468],  // Glenwood coast
  [ 865, 535],
  //  Dur Khadur cape — southeastern peninsula jutting south
  [ 880, 605],
  [ 862, 650],  // cape tip
  //  South coast — broad sweep west
  [ 822, 662],
  [ 752, 658],
  [ 672, 652],
  [ 590, 648],
  [ 508, 644],
  [ 425, 638],
  [ 342, 625],
  [ 262, 610],
  //  Vilefin cliffs — rocky SW corner
  [ 192, 585],
  [ 135, 558],
  [  82, 520],
  [  55, 470],
  //  Faerwood west coast — one clear sheltered bay
  [  38, 415],
  [  42, 365],
  [  34, 308],
  [  52, 258],
  [  48, 218],
];

// Four-island chain running NE→SE, separated from the Farrock headland
// by the Dreadwind channel (open sea). Each island is larger and more
// dramatic than the old overlapping blobs.
const DREADWIND_ISLANDS = [
  // Island 1 — Northern (off Farrock headland, largest)
  [
    [ 920, 148],
    [ 995, 172],
    [1010, 248],
    [ 980, 295],
    [ 925, 280],
    [ 902, 208],
  ],
  // Island 2 — Mid-north
  [
    [ 935, 308],
    [ 998, 312],
    [1010, 368],
    [ 980, 400],
    [ 932, 386],
    [ 918, 332],
  ],
  // Island 3 — Central (second-largest)
  [
    [ 920, 412],
    [ 992, 396],
    [1015, 458],
    [ 998, 522],
    [ 935, 532],
    [ 910, 475],
  ],
  // Island 4 — Southern
  [
    [ 925, 545],
    [ 972, 538],
    [ 988, 582],
    [ 965, 618],
    [ 922, 608],
    [ 908, 565],
  ],
];

// Tidefall island — single warm-water island, south of the Dreadwind chain,
// home to the tide-fish clan.
const TIDEFALL_ISLANDS = [
  [
    [ 960, 632],
    [1005, 625],
    [1018, 658],
    [1000, 675],
    [ 962, 672],
    [ 944, 648],
  ],
];

const TIDEFALL_ISLAND_HOUSE_ID = 'tide-fish';

const LANDMASSES = [MAIN_CONTINENT, ...TIDEFALL_ISLANDS, ...DREADWIND_ISLANDS];

const REALM_ALIASES = {
  Glenwood: { displayName: 'Glenhaven' },
  Farrock: { displayName: 'Varkuun' },
};

const KINGDOM_COLORS = {
  Frostvale: '#aacfe0',
  Lostfeld: '#8799a8',
  Farrock: '#b05c2a',
  Eldoria: '#d4a052',
  Faerwood: '#3a7a3a',
  Gilgeth: '#7a6650',
  'Twin Cities': '#d4b830',
  Eresteron: '#c8a028',
  Groth: '#a83828',
  Vilefin: '#a09030',
  'Dur Khadur': '#c87830',
  Glenwood: '#4a8c40',
  Tidefall: '#4898b0',
  'Dreadwind Isles': '#4a6080',
};

function esc(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

function toIdName(id) {
  const name = String(id)
    .replace(/^(frostvale|faerwood|eldoria|twin|eresteron|farrock|gilgeth|groth|vilefin|lostfeld|dur|glen|tide|dreadwind)-/i, '')
    .replace(/-/g, ' ')
    .replace(/\b\w/g, (m) => m.toUpperCase());
  return name
    .replace(/\bLefleur\b/g, 'LeFleur')
    .replace(/\bVer Meer\b/g, 'Ver Meer')
    .replace(/\bMijid\b/g, 'Mijid');
}

function pointInPolygon(x, y, polygon) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const [xi, yi] = polygon[i];
    const [xj, yj] = polygon[j];
    const intersect = yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi + 1e-12) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

function isLandPoint(x, y) {
  return LANDMASSES.some((mass) => pointInPolygon(x, y, mass));
}

function isDreadwindPoint(x, y) {
  return DREADWIND_ISLANDS.some((island) => pointInPolygon(x, y, island));
}

function isTidefallIslandPoint(x, y) {
  return TIDEFALL_ISLANDS.some((island) => pointInPolygon(x, y, island));
}

function polygonCentroid(coords) {
  let area2 = 0;
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < coords.length; i += 1) {
    const [x0, y0] = coords[i];
    const [x1, y1] = coords[(i + 1) % coords.length];
    const cross = x0 * y1 - x1 * y0;
    area2 += cross;
    cx += (x0 + x1) * cross;
    cy += (y0 + y1) * cross;
  }
  if (Math.abs(area2) < 1e-9) {
    const sum = coords.reduce((acc, [x, y]) => [acc[0] + x, acc[1] + y], [0, 0]);
    return [sum[0] / coords.length, sum[1] / coords.length];
  }
  return [cx / (3 * area2), cy / (3 * area2)];
}

const MAIN_CENTER = polygonCentroid(MAIN_CONTINENT);

function nearestLandPoint(x, y) {
  if (isLandPoint(x, y)) return [x, y];
  let px = x;
  let py = y;
  for (let i = 0; i < 64; i += 1) {
    px = px * 0.88 + MAIN_CENTER[0] * 0.12;
    py = py * 0.88 + MAIN_CENTER[1] * 0.12;
    if (isLandPoint(px, py)) return [px, py];
  }
  return [MAIN_CENTER[0], MAIN_CENTER[1]];
}

function layoutToScreen(center) {
  return [
    (center.center_x / 1000) * WIDTH,
    ((1000 - center.center_y) / 1000) * HEIGHT,
  ];
}

function islandAnchor(islands) {
  return polygonCentroid(islands[0]);
}

function isSamePoint(a, b) {
  return Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9;
}

function distanceToSegment(point, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  if (Math.abs(dx) < 1e-9 && Math.abs(dy) < 1e-9) {
    return Math.hypot(point[0] - a[0], point[1] - a[1]);
  }
  const t = Math.max(0, Math.min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(point[0] - (a[0] + t * dx), point[1] - (a[1] + t * dy));
}

function simplifyOpenLine(points, tolerance) {
  if (points.length <= 2) return points;
  let maxDistance = 0;
  let index = 0;
  const first = points[0];
  const last = points[points.length - 1];
  for (let i = 1; i < points.length - 1; i += 1) {
    const distance = distanceToSegment(points[i], first, last);
    if (distance > maxDistance) {
      maxDistance = distance;
      index = i;
    }
  }
  if (maxDistance <= tolerance) return [first, last];
  const left = simplifyOpenLine(points.slice(0, index + 1), tolerance);
  const right = simplifyOpenLine(points.slice(index), tolerance);
  return left.slice(0, -1).concat(right);
}

function simplifyClosedRing(coords, tolerance = 7) {
  let ring = coords.slice();
  if (ring.length > 1 && isSamePoint(ring[0], ring[ring.length - 1])) {
    ring = ring.slice(0, -1);
  }
  if (ring.length < 8) return ring;
  const simplified = simplifyOpenLine([...ring, ring[0]], tolerance).slice(0, -1);
  return simplified.length >= 4 ? simplified : ring;
}

function smoothClosedRing(coords, iterations = 1) {
  let ring = simplifyClosedRing(coords);
  if (ring.length > 1 && isSamePoint(ring[0], ring[ring.length - 1])) {
    ring = ring.slice(0, -1);
  }
  if (ring.length < 4) return ring;
  for (let step = 0; step < iterations; step += 1) {
    const next = [];
    for (let i = 0; i < ring.length; i += 1) {
      const a = ring[i];
      const b = ring[(i + 1) % ring.length];
      next.push([a[0] * 0.88 + b[0] * 0.12, a[1] * 0.88 + b[1] * 0.12]);
      next.push([a[0] * 0.12 + b[0] * 0.88, a[1] * 0.12 + b[1] * 0.88]);
    }
    ring = next;
  }
  return ring;
}

function pathD(coords, { smooth = true } = {}) {
  const points = smooth ? smoothClosedRing(coords) : coords;
  const [first, ...rest] = points;
  return `M ${first[0].toFixed(2)} ${first[1].toFixed(2)} ${rest
    .map(([x, y]) => `L ${x.toFixed(2)} ${y.toFixed(2)}`)
    .join(' ')} Z`;
}

function multiPolygonPath(multiPolygon, options) {
  return multiPolygon
    .map((polygon) => polygon[0])
    .filter(Boolean)
    .map((ring) => pathD(ring, options))
    .join(' ');
}

function multiPolygonCentroid(multiPolygon) {
  let bestRing = null;
  let bestArea = -Infinity;
  for (const polygon of multiPolygon) {
    const ring = polygon[0];
    if (!ring) continue;
    const area = Math.abs(signedArea(ring));
    if (area > bestArea) {
      bestArea = area;
      bestRing = ring.slice(0, -1);
    }
  }
  return bestRing ? polygonCentroid(bestRing) : [WIDTH / 2, HEIGHT / 2];
}

// Pointy-top hexagon: vertices at 30°, 90°, 150°, 210°, 270°, 330°
// Adjacent hexes in the same row (x ± HEX_X_STEP) share V0/V5 and V2/V3 exactly.
// Adjacent hexes in neighboring rows share V1/V4 and V2/V3 exactly.
function hexPolygon(cx, cy) {
  const h = HEX_H / 2; // = R*√3/2
  const r = HEX_R;     // circumradius = R
  return [
    [cx + h, cy - r / 2], // V0: top-right
    [cx + h, cy + r / 2], // V1: bottom-right
    [cx, cy + r],         // V2: bottom
    [cx - h, cy + r / 2], // V3: bottom-left
    [cx - h, cy - r / 2], // V4: top-left
    [cx, cy - r],         // V5: top
    [cx + h, cy - r / 2], // V0 again to close
  ];
}

function buildHexes() {
  const hexes = [];
  let id = 0;
  for (let row = 0, cy = HEX_R; cy <= HEIGHT - HEX_R * 0.25; row += 1, cy += HEX_Y_STEP) {
    const offset = row % 2 === 0 ? 0 : HEX_X_STEP / 2;
    for (let cx = HEX_R + offset; cx <= WIDTH - HEX_R * 0.25; cx += HEX_X_STEP) {
      if (!isLandPoint(cx, cy)) continue;
      hexes.push({ id: `h${id}`, cx, cy, polygon: hexPolygon(cx, cy) });
      id += 1;
    }
  }
  return hexes;
}

function buildSeeds(realmHouses, layout) {
  const centers = new Map(layout.regions.map((region) => [region.region_id, region]));
  const seeds = [];
  for (const [realmId, houses] of Object.entries(realmHouses)) {
    const rawCenter = centers.get(realmId);
    if (!rawCenter) continue;
    const [realmX, realmY] = layoutToScreen(rawCenter);
    const realmPoint = nearestLandPoint(realmX, realmY);
    const radius = Math.max(22, Math.min(62, 20 + houses.length * 8));
    houses.forEach((house, i) => {
      const angle = -Math.PI / 2 + (i / houses.length) * Math.PI * 2;
      const wobble = (i % 2 === 0 ? 1 : 0.68) * radius;
      const [x, y] =
        house.house_id === TIDEFALL_ISLAND_HOUSE_ID
          ? islandAnchor(TIDEFALL_ISLANDS)
          : nearestLandPoint(
              realmPoint[0] + Math.cos(angle) * wobble,
              realmPoint[1] + Math.sin(angle) * wobble,
            );
      const displayRealm = REALM_ALIASES[realmId]?.displayName || realmId;
      seeds.push({
        houseId: house.house_id,
        houseName: toIdName(house.house_id),
        factionId: house.faction_id,
        realmId,
        displayRealm,
        x,
        y,
      });
    });
  }
  return seeds;
}

function assignHexes(hexes, seeds) {
  const byHouse = new Map(seeds.map((seed) => [seed.houseId, []]));
  const islandSeeds = seeds.filter((seed) => seed.realmId === 'Dreadwind Isles');
  const tidefallIslandSeed = seeds.find((seed) => seed.houseId === TIDEFALL_ISLAND_HOUSE_ID);
  const mainlandSeeds = seeds.filter(
    (seed) => seed.realmId !== 'Dreadwind Isles' && seed.houseId !== TIDEFALL_ISLAND_HOUSE_ID,
  );
  for (const hex of hexes) {
    const candidates = isDreadwindPoint(hex.cx, hex.cy)
      ? islandSeeds
      : isTidefallIslandPoint(hex.cx, hex.cy) && tidefallIslandSeed
        ? [tidefallIslandSeed]
        : mainlandSeeds;
    let best = candidates[0];
    let bestD = Infinity;
    for (const seed of candidates) {
      const d = (hex.cx - seed.x) ** 2 + (hex.cy - seed.y) ** 2;
      if (d < bestD) {
        bestD = d;
        best = seed;
      }
    }
    byHouse.get(best.houseId)?.push(hex);
  }
  return byHouse;
}

function largestExterior(multiPolygon) {
  let best = null;
  let bestArea = -Infinity;
  for (const polygon of multiPolygon) {
    const ring = polygon[0];
    if (!ring || ring.length < 4) continue;
    const area = Math.abs(signedArea(ring));
    if (area > bestArea) {
      bestArea = area;
      best = ring.slice(0, -1);
    }
  }
  return best;
}

function exteriorRings(multiPolygon) {
  return multiPolygon
    .map((polygon) => polygon[0])
    .filter((ring) => ring && ring.length >= 4)
    .map((ring) => ring.slice(0, -1))
    .sort((a, b) => Math.abs(signedArea(b)) - Math.abs(signedArea(a)));
}

function signedArea(ring) {
  let sum = 0;
  for (let i = 0; i < ring.length - 1; i += 1) {
    const [x0, y0] = ring[i];
    const [x1, y1] = ring[i + 1];
    sum += x0 * y1 - x1 * y0;
  }
  return sum / 2;
}

function unionHexes(hexes) {
  if (hexes.length === 0) return [];
  return polygonClipping.union(...hexes.map((hex) => [[hex.polygon]]));
}

function edgeKey(a, b) {
  const pa = `${a[0].toFixed(4)},${a[1].toFixed(4)}`;
  const pb = `${b[0].toFixed(4)},${b[1].toFixed(4)}`;
  return pa < pb ? `${pa}|${pb}` : `${pb}|${pa}`;
}

// Smooth an open polyline with Chaikin (preserves endpoints).
function smoothOpenLine(points, iterations = 4) {
  if (points.length < 2) return points;
  let line = points;
  for (let step = 0; step < iterations; step += 1) {
    const next = [line[0]];
    for (let i = 0; i < line.length - 1; i += 1) {
      const a = line[i];
      const b = line[i + 1];
      next.push([a[0] * 0.75 + b[0] * 0.25, a[1] * 0.75 + b[1] * 0.25]);
      next.push([a[0] * 0.25 + b[0] * 0.75, a[1] * 0.25 + b[1] * 0.75]);
    }
    next.push(line[line.length - 1]);
    line = next;
  }
  return line;
}

// Chain individual segments into connected polylines for smoother output.
function buildPolylines(segEdges) {
  // vertex key -> list of {toKey, point, edgeRef}
  const adj = new Map();
  const addAdj = (fromKey, toKey, point, edgeRef) => {
    if (!adj.has(fromKey)) adj.set(fromKey, []);
    adj.get(fromKey).push({ toKey, point, edgeRef });
  };
  for (const edge of segEdges) {
    const pa = `${edge.a[0].toFixed(4)},${edge.a[1].toFixed(4)}`;
    const pb = `${edge.b[0].toFixed(4)},${edge.b[1].toFixed(4)}`;
    addAdj(pa, pb, edge.b, edge);
    addAdj(pb, pa, edge.a, edge);
  }

  const usedEdges = new Set();
  const polylines = [];

  for (const edge of segEdges) {
    if (usedEdges.has(edge)) continue;
    usedEdges.add(edge);
    const line = [edge.a, edge.b];
    let curKey = `${edge.b[0].toFixed(4)},${edge.b[1].toFixed(4)}`;

    // extend forward
    for (;;) {
      const neighbors = adj.get(curKey) || [];
      const next = neighbors.find((n) => !usedEdges.has(n.edgeRef));
      if (!next) break;
      usedEdges.add(next.edgeRef);
      line.push(next.point);
      curKey = next.toKey;
    }

    polylines.push(line);
  }
  return polylines;
}

// Compute shared territory borders from raw hex edges (guaranteed exact vertex match).
// groupForSeed(seed) → string ID used to detect "different group" crossings.
function buildSharedBoundaryPath(houseShapes, groupForSeed, { crossRealmOnly = false } = {}) {
  const edges = new Map();
  for (const shape of houseShapes) {
    const groupId = groupForSeed(shape.seed);
    for (const hex of shape.hexes) {
      const verts = hex.polygon; // 7 pts, first === last
      for (let i = 0; i < verts.length - 1; i += 1) {
        const a = verts[i];
        const b = verts[i + 1];
        const key = edgeKey(a, b);
        const entry = edges.get(key);
        if (entry) {
          entry.groups.add(groupId);
          entry.realms.add(shape.seed.realmId);
          if (!isSamePoint(entry.a, a)) {
            // normalise to a consistent direction
            entry.a = a;
            entry.b = b;
          }
        } else {
          edges.set(key, { a, b, groups: new Set([groupId]), realms: new Set([shape.seed.realmId]) });
        }
      }
    }
  }

  // Keep only edges where two DIFFERENT groups meet.
  const borderEdges = Array.from(edges.values()).filter((e) => {
    if (e.groups.size < 2) return false;
    if (crossRealmOnly && e.realms.size < 2) return false;
    return true;
  });

  const polylines = buildPolylines(borderEdges);
  return polylines
    .map((line) => {
      const smoothed = smoothOpenLine(line);
      return `M ${smoothed.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(' L ')}`;
    })
    .join(' ');
}

function buildRegionsAndBasemap() {
  const realmHouses = JSON.parse(fs.readFileSync(REALM_HOUSES, 'utf-8'));
  const layout = JSON.parse(fs.readFileSync(MAP_LAYOUT, 'utf-8'));
  const hexes = buildHexes();
  const seeds = buildSeeds(realmHouses, layout);
  const byHouse = assignHexes(hexes, seeds);
  const regions = [];
  const houseShapes = [];

  for (const seed of seeds) {
    const ownedHexes = byHouse.get(seed.houseId) || [];
    const union = unionHexes(ownedHexes);
    const exteriors = exteriorRings(union);
    const exterior = exteriors[0] || largestExterior(union);
    if (!exterior) continue;
    regions.push({
      id: seed.houseId,
      name: seed.houseName,
      description: `${seed.houseName} — ${seed.displayRealm} house/clan province; realm=${seed.realmId}; faction=${seed.factionId}.`,
      coordinates: exterior,
      ...(exteriors.length > 1 ? { polygons: exteriors } : {}),
    });
    houseShapes.push({ seed, hexes: ownedHexes, union });
  }

  return { hexes, regions, houseShapes };
}

function renderSvg(hexes, houseShapes) {
  const landPath = multiPolygonPath(unionHexes(hexes));
  const provincePaths = houseShapes
    .map(({ seed, union }) => `<path class="province" d="${multiPolygonPath(union)}"><title>${esc(`${seed.houseName} / ${seed.displayRealm}`)}</title></path>`)
    .join('\n    ');

  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${WIDTH}" height="${HEIGHT}" viewBox="0 0 ${WIDTH} ${HEIGHT}" role="img" aria-label="Aeloria CK3-style house province map">
  <defs>
    <style>
      .coast {
        fill: #9a9368;
        stroke: rgba(37, 30, 17, 0.72);
        stroke-width: 3.1;
        vector-effect: non-scaling-stroke;
      }
      .province {
        fill: none;
        stroke: rgba(46, 37, 21, 0.3);
        stroke-width: 0.85;
        vector-effect: non-scaling-stroke;
      }
    </style>
  </defs>
  <rect width="100%" height="100%" fill="#143247"/>
  <path class="coast" d="${landPath}"/>
  <g class="provinces">
    ${provincePaths}
  </g>
</svg>
`;
}

function groupHouseShapesByKingdom(houseShapes) {
  const byKingdom = new Map();
  for (const shape of houseShapes) {
    const key = shape.seed.realmId;
    if (!byKingdom.has(key)) {
      byKingdom.set(key, {
        displayRealm: shape.seed.displayRealm,
        hexes: [],
      });
    }
    byKingdom.get(key).hexes.push(...shape.hexes);
  }
  return byKingdom;
}

function renderKingdomPreviewSvg(hexes, houseShapes) {
  const landPath = multiPolygonPath(unionHexes(hexes));
  const byKingdom = groupHouseShapesByKingdom(houseShapes);
  const kingdomPaths = [];
  for (const [realmId, group] of byKingdom.entries()) {
    const union = unionHexes(group.hexes);
    const color = KINGDOM_COLORS[realmId] || '#8f855d';
    kingdomPaths.push(
      `<path class="kingdom" d="${multiPolygonPath(union, { smooth: false })}" fill="${color}"><title>${esc(group.displayRealm)}</title></path>`,
    );
  }

  // Shared-edge kingdom borders: edges where two DIFFERENT realms touch.
  const kingdomBorderD = buildSharedBoundaryPath(
    houseShapes,
    (seed) => seed.realmId,
    { crossRealmOnly: false },
  );

  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${WIDTH}" height="${HEIGHT}" viewBox="0 0 ${WIDTH} ${HEIGHT}" role="img" aria-label="Aeloria kingdom preview map">
  <defs>
    <clipPath id="landClip"><path d="${landPath}"/></clipPath>
    <radialGradient id="ocean" cx="46%" cy="42%" r="78%">
      <stop offset="0%" stop-color="#2c5566"/>
      <stop offset="55%" stop-color="#14334a"/>
      <stop offset="100%" stop-color="#060f1a"/>
    </radialGradient>
    <linearGradient id="mapLight" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="rgba(255,238,188,0.20)"/>
      <stop offset="50%" stop-color="rgba(255,238,188,0)"/>
      <stop offset="100%" stop-color="rgba(0,0,0,0.30)"/>
    </linearGradient>
    <filter id="landShadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="0" dy="6" stdDeviation="7" flood-color="#010608" flood-opacity="0.55"/>
    </filter>
    <filter id="seamBlur" x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="linearRGB">
      <feGaussianBlur stdDeviation="1.0"/>
    </filter>
    <style>
      .coast-fill { fill: #8a8558; filter: url(#landShadow); }
      .coast-outline {
        fill: none;
        stroke: rgba(14,9,4,0.92);
        stroke-width: 4.0;
        vector-effect: non-scaling-stroke;
      }
      .kingdom { fill-opacity: 1; stroke: none; }
      .kingdom-seam {
        fill: none;
        stroke: rgba(3,1,0,0.88);
        stroke-width: 3.2;
        stroke-linecap: round;
        stroke-linejoin: round;
        filter: url(#seamBlur);
        vector-effect: non-scaling-stroke;
      }
      .cinematic-light {
        fill: url(#mapLight);
        mix-blend-mode: soft-light;
        pointer-events: none;
      }
    </style>
  </defs>
  <rect width="100%" height="100%" fill="url(#ocean)"/>
  <path class="coast-fill" d="${landPath}"/>
  <g clip-path="url(#landClip)">${kingdomPaths.join('\n    ')}</g>
  <path class="kingdom-seam" clip-path="url(#landClip)" d="${kingdomBorderD}"/>
  <path class="coast-outline" d="${landPath}"/>
  <rect class="cinematic-light" width="100%" height="100%"/>
</svg>
`;
}

function hexToRgb(hex) {
  const raw = hex.replace('#', '');
  return [
    Number.parseInt(raw.slice(0, 2), 16),
    Number.parseInt(raw.slice(2, 4), 16),
    Number.parseInt(raw.slice(4, 6), 16),
  ];
}

function rgbToHex([r, g, b]) {
  return `#${[r, g, b]
    .map((value) => Math.max(0, Math.min(255, Math.round(value))).toString(16).padStart(2, '0'))
    .join('')}`;
}

function mixColor(hex, target, amount) {
  const base = hexToRgb(hex);
  const dest = target === 'white' ? [255, 255, 255] : [0, 0, 0];
  return rgbToHex(base.map((value, i) => value + (dest[i] - value) * amount));
}

function kingdomShadeColor(realmId, houseId, houseIndex) {
  const base = KINGDOM_COLORS[realmId] || '#8f855d';
  let hash = 0;
  for (let i = 0; i < houseId.length; i += 1) hash = houseId.charCodeAt(i) + ((hash << 5) - hash);
  const shadeSteps = [-0.09, -0.045, 0, 0.05, 0.1];
  const shade = shadeSteps[Math.abs(hash + houseIndex) % shadeSteps.length];
  return shade < 0 ? mixColor(base, 'black', Math.abs(shade)) : mixColor(base, 'white', shade);
}

function renderHousePreviewSvg(hexes, houseShapes) {
  const landPath = multiPolygonPath(unionHexes(hexes));

  const housePaths = houseShapes.map(({ seed, union }, index) =>
    `<path class="house" d="${multiPolygonPath(union, { smooth: false })}" fill="${kingdomShadeColor(seed.realmId, seed.houseId, index)}"><title>${esc(`${seed.houseName} / ${seed.displayRealm}`)}</title></path>`,
  );

  // House borders: shared edges where two DIFFERENT houses touch (any kingdom).
  const houseBorderD = buildSharedBoundaryPath(
    houseShapes,
    (seed) => seed.houseId,
    { crossRealmOnly: false },
  );

  // Kingdom borders: shared edges where two DIFFERENT realms touch (drawn on top, thicker).
  const kingdomBorderD = buildSharedBoundaryPath(
    houseShapes,
    (seed) => seed.realmId,
    { crossRealmOnly: false },
  );

  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${WIDTH}" height="${HEIGHT}" viewBox="0 0 ${WIDTH} ${HEIGHT}" role="img" aria-label="Aeloria house and clan preview map">
  <defs>
    <clipPath id="landClip"><path d="${landPath}"/></clipPath>
    <radialGradient id="ocean" cx="46%" cy="42%" r="78%">
      <stop offset="0%" stop-color="#2c5566"/>
      <stop offset="55%" stop-color="#14334a"/>
      <stop offset="100%" stop-color="#060f1a"/>
    </radialGradient>
    <linearGradient id="mapLight" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="rgba(255,238,188,0.18)"/>
      <stop offset="54%" stop-color="rgba(255,238,188,0)"/>
      <stop offset="100%" stop-color="rgba(0,0,0,0.28)"/>
    </linearGradient>
    <filter id="landShadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="0" dy="6" stdDeviation="7" flood-color="#010608" flood-opacity="0.55"/>
    </filter>
    <filter id="houseSeamBlur" x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="linearRGB">
      <feGaussianBlur stdDeviation="0.6"/>
    </filter>
    <filter id="kingdomSeamBlur" x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="linearRGB">
      <feGaussianBlur stdDeviation="1.0"/>
    </filter>
    <style>
      .coast-fill { fill: #8a8558; filter: url(#landShadow); }
      .coast-outline {
        fill: none;
        stroke: rgba(14,9,4,0.92);
        stroke-width: 4.0;
        vector-effect: non-scaling-stroke;
      }
      .house { fill-opacity: 1; stroke: none; }
      .house-seam {
        fill: none;
        stroke: rgba(5,3,1,0.55);
        stroke-width: 1.4;
        stroke-linecap: round;
        stroke-linejoin: round;
        filter: url(#houseSeamBlur);
        vector-effect: non-scaling-stroke;
      }
      .kingdom-seam {
        fill: none;
        stroke: rgba(3,1,0,0.88);
        stroke-width: 3.2;
        stroke-linecap: round;
        stroke-linejoin: round;
        filter: url(#kingdomSeamBlur);
        vector-effect: non-scaling-stroke;
      }
      .cinematic-light {
        fill: url(#mapLight);
        mix-blend-mode: soft-light;
        pointer-events: none;
      }
    </style>
  </defs>
  <rect width="100%" height="100%" fill="url(#ocean)"/>
  <path class="coast-fill" d="${landPath}"/>
  <g clip-path="url(#landClip)">${housePaths.join('\n    ')}</g>
  <path class="house-seam" clip-path="url(#landClip)" d="${houseBorderD}"/>
  <path class="kingdom-seam" clip-path="url(#landClip)" d="${kingdomBorderD}"/>
  <path class="coast-outline" d="${landPath}"/>
  <rect class="cinematic-light" width="100%" height="100%"/>
</svg>
`;
}

function main() {
  const { hexes, regions, houseShapes } = buildRegionsAndBasemap();
  const tsFinal = `/**
 * AUTO-GENERATED by scripts/generate-lore-house-map.mjs — do not edit by hand.
 * CK3-style hex-derived house/clan provinces over the Aeloria continent.
 */
import type { RegionDefinition } from './regions';

export const regionsLoreHouses: RegionDefinition[] = ${JSON.stringify(regions, null, 2)};
`;
  const svg = renderSvg(hexes, houseShapes);
  const kingdomPreviewSvg = renderKingdomPreviewSvg(hexes, houseShapes);
  const housePreviewSvg = renderHousePreviewSvg(hexes, houseShapes);

  fs.mkdirSync(path.dirname(OUT_TS), { recursive: true });
  fs.mkdirSync(path.dirname(OUT_BASEMAP), { recursive: true });
  fs.writeFileSync(OUT_TS, tsFinal, 'utf8');
  fs.writeFileSync(OUT_BASEMAP, svg, 'utf8');
  fs.writeFileSync(OUT_COMPAT_BASEMAP, svg, 'utf8');
  fs.writeFileSync(OUT_KINGDOM_PREVIEW, kingdomPreviewSvg, 'utf8');
  fs.writeFileSync(OUT_HOUSE_PREVIEW, housePreviewSvg, 'utf8');
  console.log(`Wrote ${regions.length} house provinces from ${hexes.length} land hexes -> ${path.relative(ROOT, OUT_TS)}`);
  console.log(`Wrote ${path.relative(ROOT, OUT_BASEMAP)}`);
  console.log(`Wrote ${path.relative(ROOT, OUT_COMPAT_BASEMAP)}`);
  console.log(`Wrote ${path.relative(ROOT, OUT_KINGDOM_PREVIEW)}`);
  console.log(`Wrote ${path.relative(ROOT, OUT_HOUSE_PREVIEW)}`);
}

main();
