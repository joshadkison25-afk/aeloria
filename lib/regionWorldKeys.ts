import type { RegionDefinition } from '@/data/regions';

/**
 * `world_state.regions` keys do not always match `data/regions` id/name (e.g. farrock → Varkuun).
 */
const REGION_ID_TO_WORLD_KEY: Record<string, string> = {
  faerwood: 'Faerwood',
  farrock: 'Varkuun',
  dreadwind_isles: 'Dreadwind Isles',
  dur_khadur: 'Dur Khadur',
  frostvale: 'Wintermark',
};

/** Macro realm id (before `__`) → Flask `regions.json` key. */
const MACRO_ID_TO_WORLD_KEY: Record<string, string> = {
  frostvale: 'Wintermark',
  faerwood: 'Faerwood',
  // Glenwood kingdom → faction id "Glenhaven" in world state
  glenwood: 'Glenhaven',
  glenhaven: 'Glenhaven',
  lostfeld: 'Lostfeld',
  eresteron: 'Eresteron',
  eldoria: 'Eldoria',
  groth: 'Groth',
  gilgeth: 'Gilgeth',
  dur_khadur: 'Dur Khadur',
  tidefall: 'Tidefall',
  farrock: 'Varkuun',
  vilefin: 'Vilefin',
  dreadwind_isles: 'Dreadwind Isles',
  twin_cities: 'Twin Cities',
};

/**
 * Realm name (as it appears in generated province descriptions "realm=X") → world state key.
 * Used as a fallback for lore house provinces whose ids are plain house_ids with no `__` separator.
 */
const REALM_NAME_TO_WORLD_KEY: Record<string, string> = {
  Frostvale: 'Wintermark',
  Faerwood: 'Faerwood',
  Eldoria: 'Eldoria',
  'Twin Cities': 'Twin Cities',
  Eresteron: 'Eresteron',
  Farrock: 'Varkuun',
  Gilgeth: 'Gilgeth',
  Groth: 'Groth',
  Vilefin: 'Vilefin',
  Lostfeld: 'Lostfeld',
  'Dur Khadur': 'Dur Khadur',
  Glenwood: 'Glenhaven',
  Tidefall: 'Tidefall',
  'Dreadwind Isles': 'Dreadwind Isles',
};

export function worldStateKeyForRegion(r: RegionDefinition): string {
  const macro = r.id.includes('__') ? r.id.split('__')[0] : r.id;
  if (MACRO_ID_TO_WORLD_KEY[macro]) return MACRO_ID_TO_WORLD_KEY[macro];
  if (REGION_ID_TO_WORLD_KEY[r.id]) return REGION_ID_TO_WORLD_KEY[r.id];

  // Lore house provinces use plain house_ids (e.g. "frostvale-adkison", "glen-wood").
  // Their description embeds "realm=RealmName" — parse that to find the world state key.
  if (r.description) {
    const match = r.description.match(/realm=([^;.\n]+)/);
    if (match) {
      const realmName = match[1].trim();
      if (REALM_NAME_TO_WORLD_KEY[realmName]) return REALM_NAME_TO_WORLD_KEY[realmName];
    }
  }

  return r.name;
}
