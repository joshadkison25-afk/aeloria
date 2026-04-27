#!/usr/bin/env node
/**
 * Builds public/data/map_data.json (GeoJSON) + public/data/houses.json from repo lore.
 * Run: node scripts/build-strategy-map-data.mjs
 */
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.join(import.meta.dirname, '..');
const REGIONS_JSON = path.join(ROOT, 'regions.json');
const OUT_GEO = path.join(ROOT, 'public', 'data', 'map_data.json');
const OUT_HOUSES = path.join(ROOT, 'public', 'data', 'houses.json');

const MAP_W = 1024;
const MAP_H = 682;

/** Local "lng/lat" for MapLibre (not real geography). */
function pxToLngLat(x, y) {
  const lng = (x / MAP_W) * 14;
  const lat = ((MAP_H - y) / MAP_H) * 9;
  return [Math.round(lng * 1e4) / 1e4, Math.round(lat * 1e4) / 1e4];
}

function ringPxToGeoJSON(ringPx) {
  const ring = ringPx.map(([x, y]) => pxToLngLat(x, y));
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) ring.push([...first]);
  return ring;
}

/** Macro map ids from data/regions.ts → Flask world region_id + display. */
const MACRO = [
  { id: 'frostvale', region_id: 'Wintermark', name: 'The Wintermark' },
  { id: 'faerwood', region_id: 'Faerwood', name: 'Shadow Court' },
  { id: 'glenhaven', region_id: 'Glenhaven', name: 'Glenhaven' },
  { id: 'lostfeld', region_id: 'Lostfeld', name: 'Lostfeld' },
  { id: 'stonebreak', region_id: 'Stonebreak', name: 'Stonebreak Monastery' },
  { id: 'eresteron', region_id: 'Eresteron', name: 'Eresteron' },
  { id: 'eldoria', region_id: 'Eldoria', name: 'Eldoria' },
  { id: 'groth', region_id: 'Groth', name: 'Groth' },
  { id: 'gilgeth', region_id: 'Gilgeth', name: 'Gilgeth' },
  { id: 'dur_khadur', region_id: 'Dur Khadur', name: 'Dur Khadur' },
  { id: 'tidefall', region_id: 'Tidefall', name: 'Tidefall' },
  { id: 'farrock', region_id: 'Varkuun', name: 'Varkuun' },
  { id: 'vilefin', region_id: 'Vilefin', name: 'Vilefin' },
  { id: 'dreadwind_isles', region_id: 'Dreadwind Isles', name: 'Dreadwind Isles' },
];

const COORDS = {
  frostvale: [
    [400, 24],
    [640, 20],
    [680, 200],
    [500, 220],
    [360, 140],
  ],
  faerwood: [
    [32, 96],
    [380, 72],
    [440, 300],
    [300, 440],
    [120, 400],
    [40, 260],
  ],
  glenhaven: [
    [16, 300],
    [220, 280],
    [280, 540],
    [72, 600],
    [20, 480],
  ],
  lostfeld: [
    [280, 300],
    [480, 280],
    [520, 480],
    [360, 520],
    [260, 420],
  ],
  stonebreak: [
    [320, 400],
    [420, 384],
    [448, 480],
    [360, 508],
    [300, 456],
  ],
  eresteron: [
    [480, 360],
    [620, 344],
    [656, 500],
    [520, 544],
    [448, 472],
  ],
  eldoria: [
    [620, 344],
    [800, 392],
    [824, 520],
    [700, 552],
    [636, 496],
  ],
  groth: [
    [680, 32],
    [1008, 48],
    [1016, 240],
    [800, 280],
    [700, 160],
  ],
  gilgeth: [
    [760, 280],
    [1000, 320],
    [980, 500],
    [800, 484],
    [748, 380],
  ],
  dur_khadur: [
    [700, 480],
    [900, 512],
    [880, 620],
    [700, 600],
    [660, 540],
  ],
  tidefall: [
    [360, 500],
    [580, 488],
    [700, 640],
    [480, 672],
    [360, 600],
  ],
  farrock: [
    [500, 520],
    [620, 500],
    [660, 620],
    [540, 656],
    [480, 580],
  ],
  vilefin: [
    [680, 540],
    [1008, 500],
    [1008, 660],
    [720, 676],
  ],
  dreadwind_isles: [
    [860, 180],
    [1000, 160],
    [1004, 400],
    [900, 420],
  ],
};

function hashColor(factionId) {
  let hash = 0;
  const s = String(factionId);
  for (let i = 0; i < s.length; i += 1) hash = s.charCodeAt(i) + ((hash << 5) - hash);
  const h = Math.abs(hash) % 360;
  return `hsl(${h}, 52%, 42%)`;
}

function main() {
  const regionsMeta = JSON.parse(fs.readFileSync(REGIONS_JSON, 'utf8')).regions;
  const factionColors = {};

  const features = MACRO.map((m) => {
    const row = regionsMeta[m.region_id];
    const faction_id = row?.canonical_faction || m.region_id;
    const default_fill = hashColor(faction_id);
    factionColors[faction_id] = factionColors[faction_id] || default_fill;

    return {
      type: 'Feature',
      properties: {
        region_id: m.region_id,
        name: m.name,
        faction_id,
        default_fill,
      },
      geometry: {
        type: 'Polygon',
        coordinates: [ringPxToGeoJSON(COORDS[m.id])],
      },
    };
  });

  for (const f of features) {
    const fid = f.properties.faction_id;
    factionColors[fid] = factionColors[fid] || f.properties.default_fill;
  }

  const geo = {
    type: 'FeatureCollection',
    features,
  };

  const houses = {
    version: 1,
    factionColors,
    houses: [
      { id: 'verlorn', name: 'House Verlorn', faction_id: 'Shadow Court', region_id: 'Faerwood' },
      { id: 'nightborn', name: 'House Nightborn', faction_id: 'Shadow Court', region_id: 'Faerwood' },
      { id: 'shadowveil', name: 'House Shadowveil', faction_id: 'Shadow Court', region_id: 'Faerwood' },
      { id: 'aurand', name: 'House Aurand', faction_id: 'Twin Cities', region_id: 'Eresteron' },
      { id: 'braafhart', name: 'House Braafhart', faction_id: 'Twin Cities', region_id: 'Eresteron' },
      { id: 'lefleur', name: 'House LeFleur', faction_id: 'Twin Cities', region_id: 'Eldoria' },
      { id: 'wood', name: 'House Wood', faction_id: 'Glenhaven', region_id: 'Glenhaven' },
      { id: 'darkleaf', name: 'House Darkleaf', faction_id: 'Glenhaven', region_id: 'Glenhaven' },
      { id: 'mistafae', name: 'House Mistafae', faction_id: 'Glenhaven', region_id: 'Glenhaven' },
      { id: 'ver-meer', name: 'House Ver Meer', faction_id: 'Tidefall', region_id: 'Tidefall' },
      { id: 'van-cleave', name: 'House Van Cleave', faction_id: 'Varkuun', region_id: 'Varkuun' },
      { id: 'gross', name: 'House Gross', faction_id: 'Dur Khadur', region_id: 'Dur Khadur' },
      { id: 'adkison', name: 'House Adkison', faction_id: 'The Wintermark', region_id: 'Wintermark' },
      { id: 'blacktide', name: 'House Blacktide', faction_id: 'Dreadwind Isles', region_id: 'Dreadwind Isles' },
      { id: 'goldfinger', name: 'Clan Goldfinger-Duke', faction_id: 'Lostfeld', region_id: 'Lostfeld' },
      { id: 'mijid', name: 'Clan Mijid', faction_id: 'Groth Clans', region_id: 'Groth' },
      { id: 'blackblood', name: 'Clan Blackblood', faction_id: 'Gilgeth Clans', region_id: 'Gilgeth' },
      { id: 'bloodware', name: 'Clan Bloodware', faction_id: 'Vilefin', region_id: 'Vilefin' },
    ],
  };

  fs.mkdirSync(path.dirname(OUT_GEO), { recursive: true });
  fs.writeFileSync(OUT_GEO, JSON.stringify(geo, null, 2), 'utf8');
  fs.writeFileSync(OUT_HOUSES, JSON.stringify(houses, null, 2), 'utf8');
  console.log('Wrote', path.relative(ROOT, OUT_GEO), '&', path.relative(ROOT, OUT_HOUSES));
}

main();
