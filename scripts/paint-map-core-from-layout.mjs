/**
 * Paints atlas hex ownership + location labels from design layout + realm houses.
 * Uses the same grid geometry as components/Map.tsx (VIEWBOX 100, HEX_SIZE must match Map.tsx).
 *
 * Writes:
 *   - lore/maps/map_core.json (repo)
 *   - $LORE_DOCS_PATH/maps/map_core.json when LORE_DOCS_PATH is set
 *
 * Usage: node scripts/paint-map-core-from-layout.mjs
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');

const VIEWBOX_WIDTH = 100;
const VIEWBOX_HEIGHT = 100;
const HEX_SIZE = 1.5;
const HEX_WIDTH = HEX_SIZE;
const HEX_HEIGHT = HEX_SIZE;
const HEX_HORIZONTAL_STEP = HEX_WIDTH * 0.75;
const HEX_VERTICAL_STEP = HEX_HEIGHT * 0.866;

/** map_layout region_id → MAP_LOCATIONS id (location paint). */
const REGION_TO_LOCATION = {
  Frostvale: 'frostvale',
  Lostfeld: 'lostfeld',
  Farrock: 'farrock',
  Eldoria: 'twin-cities',
  Faerwood: 'faerwood',
  Gilgeth: 'orc-dominion',
  'Twin Cities': 'twin-cities',
  Eresteron: 'twin-cities',
  Groth: 'orc-dominion',
  Vilefin: 'vilefin',
  'Dur Khadur': 'tidefall',
  Glenwood: 'glenhaven',
  Tidefall: 'tidefall',
  'Dreadwind Isles': 'tidefall',
};

function buildHexGrid() {
  const tiles = [];
  let index = 0;
  for (let row = 0; ; row += 1) {
    const y = row * HEX_VERTICAL_STEP;
    if (y > VIEWBOX_HEIGHT + 2 * HEX_HEIGHT) break;
    const rowOffset = row % 2 === 0 ? 0 : HEX_WIDTH * 0.5;
    for (let col = 0; ; col += 1) {
      const x = col * HEX_HORIZONTAL_STEP + rowOffset;
      if (x > VIEWBOX_WIDTH + HEX_WIDTH) break;
      tiles.push({ id: `hex-${index}`, x, y, row, col });
      index += 1;
    }
  }
  for (let row = 0; ; row += 1) {
    const y = row * HEX_VERTICAL_STEP;
    if (y > VIEWBOX_HEIGHT + 2 * HEX_HEIGHT) break;
    if (row % 2 === 0) continue;
    const col = -1;
    const rowOffset = HEX_WIDTH * 0.5;
    const x = col * HEX_HORIZONTAL_STEP + rowOffset;
    if (x + HEX_WIDTH <= 0 || x >= VIEWBOX_WIDTH) continue;
    tiles.push({ id: `hex-${index}`, x, y, row, col });
    index += 1;
  }
  return tiles;
}

/** Viewbox (x right, y down) → map_layout space (x east, y north, 0–1000). */
function viewToLayout(vx, vy) {
  return {
    lx: (vx / VIEWBOX_WIDTH) * 1000,
    ly: (1 - vy / VIEWBOX_HEIGHT) * 1000,
  };
}

function nearestRegion(lx, ly, regions) {
  let best = null;
  let bestD = Infinity;
  for (const r of regions) {
    const dx = lx - r.center_x;
    const dy = ly - r.center_y;
    const d = dx * dx + dy * dy;
    if (d < bestD) {
      bestD = d;
      best = r;
    }
  }
  return best;
}

function main() {
  const layoutPath = join(ROOT, 'public', 'data', 'map_layout.json');
  const housesPath = join(ROOT, 'public', 'data', 'realm_houses.json');
  const layout = JSON.parse(readFileSync(layoutPath, 'utf-8'));
  const realmHouses = JSON.parse(readFileSync(housesPath, 'utf-8'));
  const regions = layout.regions || [];

  const factionByRegion = {};
  for (const r of regions) {
    const key = r.region_id;
    const houses = realmHouses[key];
    if (!houses?.length) {
      console.warn(`No houses for region "${key}" — hexes there will get null faction.`);
      factionByRegion[key] = null;
    } else {
      factionByRegion[key] = houses[0].faction_id;
    }
  }

  const hexTiles = buildHexGrid();
  const ownership = {};
  const locationByHex = {};

  for (const h of hexTiles) {
    const cx = h.x + HEX_WIDTH * 0.5;
    const cy = h.y + HEX_HEIGHT * 0.5;
    const { lx, ly } = viewToLayout(cx, cy);
    const reg = nearestRegion(lx, ly, regions);
    const rid = reg.region_id;
    ownership[h.id] = factionByRegion[rid] ?? null;
    locationByHex[h.id] = REGION_TO_LOCATION[rid] || 'twin-cities';
  }

  const savedAt = new Date().toISOString();
  const payload = {
    metadata: {
      speciesSet: 'all',
      configMode: 'core',
      version: 5,
      savedAt,
      mapGrid: { viewBox: [VIEWBOX_WIDTH, VIEWBOX_HEIGHT], hexSize: HEX_SIZE },
      cartographyMode: 'hex',
    },
    ownership,
    locationByHex,
  };

  const targets = [join(ROOT, 'lore', 'maps', 'map_core.json')];
  const loreDocs = process.env.LORE_DOCS_PATH?.trim();
  if (loreDocs) targets.push(join(loreDocs, 'maps', 'map_core.json'));

  for (const dest of targets) {
    mkdirSync(dirname(dest), { recursive: true });
    writeFileSync(dest, JSON.stringify(payload, null, 2), 'utf-8');
    console.log('Wrote', dest, `(${hexTiles.length} hexes)`);
  }

  if (!loreDocs) {
    console.log('Tip: set LORE_DOCS_PATH to also write your Desktop lore_docs/maps copy.');
  }
}

main();
