/**
 * Single import surface for the atlas: house-level provinces, macro realms, or Azgaar.
 *
 * - Default: `data/regions.lore-houses.ts` (one selectable province per house/clan).
 * - Macro realms: `NEXT_PUBLIC_USE_MACRO_REALMS=1` for broad realm polygons.
 * - Azgaar: `npm run map:from-azgaar -- your.map` + `NEXT_PUBLIC_USE_AZGAAR_REGIONS=1`.
 */
import { regions as canonicalRegions } from './regions';
import { regionsAzgaarGenerated } from './regions.azgaar-generated';
import { regionsLoreHouses } from './regions.lore-houses';
import type { RegionDefinition } from './regions';

const useAzgaar =
  typeof process !== 'undefined' && process.env.NEXT_PUBLIC_USE_AZGAAR_REGIONS === '1';

const useMacroRealms =
  typeof process !== 'undefined' && process.env.NEXT_PUBLIC_USE_MACRO_REALMS === '1';

export const mapRegions: RegionDefinition[] =
  useAzgaar && regionsAzgaarGenerated.length > 0
    ? regionsAzgaarGenerated
    : useMacroRealms || regionsLoreHouses.length === 0
      ? canonicalRegions
      : regionsLoreHouses;
