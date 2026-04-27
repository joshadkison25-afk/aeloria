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

export function worldStateKeyForRegion(r: RegionDefinition): string {
  if (REGION_ID_TO_WORLD_KEY[r.id]) return REGION_ID_TO_WORLD_KEY[r.id];
  return r.name;
}
