/**
 * Single import surface for the atlas: canonical lore regions or Azgaar-generated polygons.
 *
 * - Default: `data/regions.ts` (hand-tuned, sim keys, descriptions).
 * - Azgaar: run `npm run map:from-azgaar -- your.map` then set `NEXT_PUBLIC_USE_AZGAAR_REGIONS=1`.
 */
import { regions as canonicalRegions } from './regions';
import { regionsAzgaarGenerated } from './regions.azgaar-generated';
import type { RegionDefinition } from './regions';

const useAzgaar =
  typeof process !== 'undefined' && process.env.NEXT_PUBLIC_USE_AZGAAR_REGIONS === '1';

export const mapRegions: RegionDefinition[] =
  useAzgaar && regionsAzgaarGenerated.length > 0 ? regionsAzgaarGenerated : canonicalRegions;
