export type TerrainKind = 'plains' | 'desert' | 'forests' | 'mountains' | 'coastal';

/** Subset of `terrain_map.json` read by the client. */
export type RawTerrain = {
  mountains?: number[][][];
  forests?: number[][][];
  plains?: number[][][];
  desert?: number[][][];
  coastal_zones?: number[][][];
  coastlines?: number[][][];
};

type GeoPolygon = { type: 'Polygon'; coordinates: number[][][] };
type GeoLine = { type: 'LineString'; coordinates: number[][] };

type TerrainFeature = { type: 'Feature'; id: string; properties: { kind: TerrainKind }; geometry: GeoPolygon };
type CoastFeature = { type: 'Feature'; id: string; properties: { kind: 'coast' }; geometry: GeoLine };

function closeRing(ring: number[][]): number[][] {
  if (ring.length < 2) return ring;
  const a = ring[0];
  const b = ring[ring.length - 1];
  if (a[0] === b[0] && a[1] === b[1]) return ring;
  return [...ring, [a[0], a[1]]];
}

/**
 * Aeloria `terrain_map.json` uses arrays of closed rings in layout coordinates.
 */
function ringsToFeatures(
  kind: TerrainKind,
  rings: number[][][] | undefined,
  idKey: string,
): TerrainFeature[] {
  if (!rings?.length) return [];
  return rings.map((raw, i) => {
    const ring = closeRing(raw.map((p) => [p[0], p[1]]));
    return {
      type: 'Feature',
      id: `${idKey}-${i}`,
      properties: { kind },
      geometry: { type: 'Polygon', coordinates: [ring] },
    };
  });
}

/**
 * Fills: one feature per ring so `match` on `kind` is straightforward.
 */
export function terrainFillsToGeoJson(raw: RawTerrain): { type: 'FeatureCollection'; features: TerrainFeature[] } {
  const features: TerrainFeature[] = [
    ...ringsToFeatures('plains', raw.plains, 'plains'),
    ...ringsToFeatures('desert', raw.desert, 'desert'),
    ...ringsToFeatures('forests', raw.forests, 'forests'),
    ...ringsToFeatures('mountains', raw.mountains, 'mountains'),
    ...ringsToFeatures('coastal', raw.coastal_zones, 'coastal'),
  ];
  return { type: 'FeatureCollection', features };
}

export function coastlinesToGeoJson(raw: RawTerrain): { type: 'FeatureCollection'; features: CoastFeature[] } {
  const lines = raw.coastlines;
  if (!lines?.length) {
    return { type: 'FeatureCollection', features: [] };
  }
  const features: CoastFeature[] = lines.map((coords, i) => ({
    type: 'Feature',
    id: `coastline-${i}`,
    properties: { kind: 'coast' as const },
    geometry: { type: 'LineString', coordinates: coords.map((p) => [p[0], p[1]]) },
  }));
  return { type: 'FeatureCollection', features };
}

/** Muted, readable on #070910; under semi-transparent polity fill. */
export const TERRAIN_LAYER_FILL: Record<TerrainKind, string> = {
  plains: '#3a3d32',
  desert: '#6e5a42',
  forests: '#2a4034',
  mountains: '#454e5e',
  coastal: '#2a3545',
};
