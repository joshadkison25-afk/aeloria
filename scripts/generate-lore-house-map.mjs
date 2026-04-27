#!/usr/bin/env node
/**
 * Builds lore-aligned house/clan provinces from macro regions in data/regions.ts
 * and an unlabeled flat SVG basemap (no titles). Run:
 *   node scripts/generate-lore-house-map.mjs
 *
 * Outputs:
 *   - data/regions.lore-houses.ts
 *   - public/aeloria-lore-houses-basemap.svg
 *
 * Enable in Next: NEXT_PUBLIC_USE_LORE_HOUSE_MAP=1
 * Optional atlas: NEXT_PUBLIC_MAP_ATLAS_URL=/aeloria-lore-houses-basemap.svg
 */

import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.join(import.meta.dirname, '..');
const OUT_TS = path.join(ROOT, 'data', 'regions.lore-houses.ts');
const OUT_SVG = path.join(ROOT, 'public', 'aeloria-lore-houses-basemap.svg');

const REALM_LABEL = {
  frostvale: 'Wintermark',
  faerwood: 'Faerwood (Shadow Court)',
  glenhaven: 'Glenhaven',
  lostfeld: 'Lostfeld',
  stonebreak: 'Stonebreak',
  eresteron: 'Eresteron',
  eldoria: 'Eldoria',
  groth: 'Groth',
  gilgeth: 'Gilgeth',
  dur_khadur: 'Dur Khadur',
  tidefall: 'Tidefall',
  farrock: 'Varkuun',
  vilefin: 'Vilefin',
  dreadwind_isles: 'Dreadwind Isles',
};

/** Same polygons as data/regions.ts (pixel space 1024×682). */
const MACROS = [
  {
    id: 'frostvale',
    houses: [
      { slug: 'adkison', name: 'House Adkison' },
      { slug: 'mcintosh', name: 'House McIntosh' },
      { slug: 'holter', name: 'House Holter' },
      { slug: 'duval', name: 'House Duval' },
    ],
    coordinates: [
      [400, 24],
      [640, 20],
      [680, 200],
      [500, 220],
      [360, 140],
    ],
  },
  {
    id: 'faerwood',
    houses: [
      { slug: 'verlorn', name: 'House Verlorn' },
      { slug: 'nightborn', name: 'House Nightborn' },
      { slug: 'shadowveil', name: 'House Shadowveil' },
    ],
    coordinates: [
      [32, 96],
      [380, 72],
      [440, 300],
      [300, 440],
      [120, 400],
      [40, 260],
    ],
  },
  {
    id: 'glenhaven',
    houses: [
      { slug: 'wood', name: 'House Wood' },
      { slug: 'darkleaf', name: 'House Darkleaf' },
      { slug: 'mistafae', name: 'House Mistafae' },
    ],
    coordinates: [
      [16, 300],
      [220, 280],
      [280, 540],
      [72, 600],
      [20, 480],
    ],
  },
  {
    id: 'lostfeld',
    houses: [
      { slug: 'goldfinger-duke', name: 'Clan Goldfinger-Duke' },
      { slug: 'runewarden', name: 'Clan Runewarden' },
      { slug: 'ironmaul', name: 'Clan Ironmaul' },
    ],
    coordinates: [
      [280, 300],
      [480, 280],
      [520, 480],
      [360, 520],
      [260, 420],
    ],
  },
  {
    id: 'stonebreak',
    houses: [{ slug: 'monastery', name: 'Stonebreak Monastery' }],
    coordinates: [
      [320, 400],
      [420, 384],
      [448, 480],
      [360, 508],
      [300, 456],
    ],
  },
  {
    id: 'eresteron',
    houses: [
      { slug: 'aurand', name: 'House Aurand' },
      { slug: 'braafhart', name: 'House Braafhart' },
      { slug: 'bower', name: 'House Bower' },
    ],
    coordinates: [
      [480, 360],
      [620, 344],
      [656, 500],
      [520, 544],
      [448, 472],
    ],
  },
  {
    id: 'eldoria',
    houses: [
      { slug: 'lefleur', name: 'House LeFleur' },
      { slug: 'binx', name: 'House Binx' },
      { slug: 'dale', name: 'House Dale' },
    ],
    coordinates: [
      [620, 344],
      [800, 392],
      [824, 520],
      [700, 552],
      [636, 496],
    ],
  },
  {
    id: 'groth',
    houses: [
      { slug: 'mijid', name: 'Clan Mijid' },
      { slug: 'ashfang', name: 'Clan Ashfang' },
      { slug: 'syncar', name: 'Clan Syncar' },
    ],
    coordinates: [
      [680, 32],
      [1008, 48],
      [1016, 240],
      [800, 280],
      [700, 160],
    ],
  },
  {
    id: 'gilgeth',
    houses: [
      { slug: 'blackblood', name: 'Clan Blackblood' },
      { slug: 'ironhide', name: 'Clan Ironhide' },
      { slug: 'redtusk', name: 'Clan Redtusk' },
    ],
    coordinates: [
      [760, 280],
      [1000, 320],
      [980, 500],
      [800, 484],
      [748, 380],
    ],
  },
  {
    id: 'dur_khadur',
    houses: [
      { slug: 'gross', name: 'House Gross' },
      { slug: 'delonious', name: 'House Delonious' },
      { slug: 'galfazzar', name: 'House Galfazzar' },
      { slug: 'vercenti', name: 'House Vercenti' },
    ],
    coordinates: [
      [700, 480],
      [900, 512],
      [880, 620],
      [700, 600],
      [660, 540],
    ],
  },
  {
    id: 'tidefall',
    houses: [
      { slug: 'ver-meer', name: 'House Ver Meer' },
      { slug: 'highland-dusken', name: 'House Highland-Dusken' },
      { slug: 'fish', name: 'House Fish' },
      { slug: 'mcgowan', name: 'House McGowan' },
    ],
    coordinates: [
      [360, 500],
      [580, 488],
      [700, 640],
      [480, 672],
      [360, 600],
    ],
  },
  {
    id: 'farrock',
    houses: [{ slug: 'van-cleave', name: 'House Van Cleave' }],
    coordinates: [
      [500, 520],
      [620, 500],
      [660, 620],
      [540, 656],
      [480, 580],
    ],
  },
  {
    id: 'vilefin',
    houses: [
      { slug: 'bloodware', name: 'Clan Bloodware' },
      { slug: 'cogtooth', name: 'Clan Cogtooth' },
      { slug: 'rustfang', name: 'Clan Rustfang' },
    ],
    coordinates: [
      [680, 540],
      [1008, 500],
      [1008, 660],
      [720, 676],
    ],
  },
  {
    id: 'dreadwind_isles',
    houses: [{ slug: 'blacktide', name: 'House Blacktide' }],
    coordinates: [
      [860, 180],
      [1000, 160],
      [1004, 400],
      [900, 420],
    ],
  },
];

function polygonCentroid(coords) {
  let sx = 0;
  let sy = 0;
  for (const [x, y] of coords) {
    sx += x;
    sy += y;
  }
  const n = coords.length;
  return [sx / n, sy / n];
}

/** Star-shaped fan from centroid; good enough for gameplay provinces over hand-drawn macro shapes. */
function fanSubpolygons(coords, k) {
  if (k <= 1) return [coords];
  const [cx, cy] = polygonCentroid(coords);
  const indexed = coords.map(([x, y]) => ({ x, y, ang: Math.atan2(y - cy, x - cx) }));
  indexed.sort((a, b) => a.ang - b.ang);
  const n = indexed.length;
  const polys = [];
  for (let j = 0; j < k; j++) {
    const a = Math.floor((j * n) / k);
    const b = Math.floor(((j + 1) * n) / k);
    const pts = [[cx, cy]];
    for (let t = a; t < b; t++) pts.push([indexed[t].x, indexed[t].y]);
    if (pts.length >= 3) polys.push(pts);
  }
  return polys.length ? polys : [coords];
}

function pathD(coords) {
  if (!coords.length) return '';
  const [x0, y0] = coords[0];
  const rest = coords
    .slice(1)
    .map(([x, y]) => `L ${x.toFixed(2)} ${y.toFixed(2)}`)
    .join(' ');
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} ${rest} Z`;
}

function fillForId(id) {
  let h = 0;
  for (let i = 0; i < id.length; i += 1) h = id.charCodeAt(i) + ((h << 5) - h);
  const hue = Math.abs(h) % 360;
  return `hsl(${hue}, 32%, 38%)`;
}

function esc(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
}

function main() {
  const regions = [];
  const svgPaths = [];

  for (const macro of MACROS) {
    const k = macro.houses.length;
    const pieces = fanSubpolygons(macro.coordinates, k);
    for (let i = 0; i < k; i += 1) {
      const house = macro.houses[i];
      const coords = pieces[i] || macro.coordinates;
      const id = `${macro.id}__${house.slug}`;
      const realm = REALM_LABEL[macro.id] || macro.id.replace(/_/g, ' ');
      const desc = `${house.name} — holding within ${realm} (generated layout; replace with painted basemap when ready).`;
      regions.push({ id, name: house.name, description: desc, coordinates: coords });
      svgPaths.push(
        `<path id="${esc(id)}" fill="${fillForId(id)}" stroke="rgba(12,14,22,0.35)" stroke-width="0.6" d="${pathD(coords)}"/>`,
      );
    }
  }

  const tsFinal = `/**
 * AUTO-GENERATED by scripts/generate-lore-house-map.mjs — do not edit by hand.
 * Run: node scripts/generate-lore-house-map.mjs
 * One province per named house/clan from app.py _PERMANENT_HOUSES (+ Stonebreak hold).
 */
import type { RegionDefinition } from './regions';

export const regionsLoreHouses: RegionDefinition[] = ${JSON.stringify(regions, null, 2)};
`;

  const svg = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 682" width="1024" height="682" role="img" aria-label="Aeloria house provinces (unlabeled)">
  <rect width="1024" height="682" fill="#0a0c12"/>
  ${svgPaths.join('\n  ')}
</svg>
`;

  fs.writeFileSync(OUT_TS, tsFinal, 'utf8');
  fs.writeFileSync(OUT_SVG, svg, 'utf8');
  console.log(`Wrote ${regions.length} provinces → ${path.relative(ROOT, OUT_TS)}`);
  console.log(`Wrote ${path.relative(ROOT, OUT_SVG)}`);
}

main();
