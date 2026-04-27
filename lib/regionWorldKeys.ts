import type { RegionDefinition } from '@/data/regions';

/**
 * `world_state.regions` keys do not always match `data/regions` id/name (e.g. farrock → Varkuun).
 */
const REGION_ID_TO_WORLD_KEY: Record<string, string> = {
  faerwood: 'Faerwood', // display name on map: Shadow Court; sim region key: Faerwood
  farrock: 'Varkuun',
  stonebreak: 'Stonebreak',
  dreadwind_isles: 'Dreadwind Isles',
  dur_khadur: 'Dur Khadur',
  frostvale: 'Wintermark',
};

/** Macro realm id (before `__`) → Flask `regions.json` key. */
const MACRO_ID_TO_WORLD_KEY: Record<string, string> = {
  frostvale: 'Wintermark',
  faerwood: 'Faerwood',
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

export function worldStateKeyForRegion(r: RegionDefinition): string {
  const macro = r.id.includes('__') ? r.id.split('__')[0] : r.id;
  if (MACRO_ID_TO_WORLD_KEY[macro]) return MACRO_ID_TO_WORLD_KEY[macro];
  if (REGION_ID_TO_WORLD_KEY[r.id]) return REGION_ID_TO_WORLD_KEY[r.id];
  return r.name;
}
