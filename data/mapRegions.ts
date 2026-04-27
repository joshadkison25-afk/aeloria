/**
 * Single import surface for the atlas: canonical lore regions, house-level provinces, or Azgaar.
 *
 * - Default: `data/regions.ts` (hand-tuned macro realms).
 * - One province per named house: `NEXT_PUBLIC_USE_LORE_HOUSE_MAP=1` (see `npm run generate:lore-houses-map`).
 * - Azgaar: `npm run map:from-azgaar -- your.map` + `NEXT_PUBLIC_USE_AZGAAR_REGIONS=1`.
 */
import { regions as canonicalRegions } from './regions';
import { regionsAzgaarGenerated } from './regions.azgaar-generated';
import { regionsLoreHouses } from './regions.lore-houses';
import type { RegionDefinition } from './regions';

const useLoreHouses =
  typeof process !== 'undefined' && process.env.NEXT_PUBLIC_USE_LORE_HOUSE_MAP === '1';

const useAzgaar =
  typeof process !== 'undefined' && process.env.NEXT_PUBLIC_USE_AZGAAR_REGIONS === '1';

export const mapRegions: RegionDefinition[] =
  useLoreHouses && regionsLoreHouses.length > 0
    ? regionsLoreHouses
    : useAzgaar && regionsAzgaarGenerated.length > 0
      ? regionsAzgaarGenerated
      : canonicalRegions;
