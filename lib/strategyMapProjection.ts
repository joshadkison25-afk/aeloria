/**
 * Strategy data uses a flat 0..extent square (x east, y north). MapLibre expects
 * geographic lng/lat with |lat| ≤ 90, so we project game coords.
 *
 * Use the **same degree span** on both axes so a square game map stays **square**
 * in lng/lat. (A 360°×170° box is not square — realms looked horizontally stretched,
 * and Web Mercator added more distortion.)
 */
export const GAME_MAP_EXTENT = 1000;

/** Full map covers PLATE_SPAN_DEG × PLATE_SPAN_DEG degrees centered on 0,0. */
const PLATE_SPAN_DEG = 14;

/** Game [x,y] → MapLibre lng/lat (small patch — plate-like proportions). */
export function gameXYToLngLat(x: number, y: number): [number, number] {
  const t = GAME_MAP_EXTENT;
  const half = PLATE_SPAN_DEG / 2;
  const lng = ((x / t) * 2 - 1) * half;
  const lat = ((y / t) * 2 - 1) * half;
  return [lng, lat];
}

function projectRing(ring: number[][]): number[][] {
  return ring.map((p) => {
    const x = p[0];
    const y = p[1];
    const [lng, lat] = gameXYToLngLat(x, y);
    return [lng, lat];
  });
}

function projectPolygonCoords(coords: number[][][]): number[][][] {
  return coords.map((ring) => projectRing(ring));
}

type Geom =
  | { type: 'Polygon'; coordinates: number[][][] }
  | { type: 'MultiPolygon'; coordinates: number[][][][] }
  | { type: 'LineString'; coordinates: number[][] }
  | { type: 'MultiLineString'; coordinates: number[][][] };

function projectGeometry(g: Geom): Geom {
  if (g.type === 'Polygon') {
    return { type: 'Polygon', coordinates: projectPolygonCoords(g.coordinates) };
  }
  if (g.type === 'MultiPolygon') {
    return {
      type: 'MultiPolygon',
      coordinates: g.coordinates.map((poly) => projectPolygonCoords(poly)),
    };
  }
  if (g.type === 'LineString') {
    return { type: 'LineString', coordinates: projectRing(g.coordinates) };
  }
  if (g.type === 'MultiLineString') {
    return {
      type: 'MultiLineString',
      coordinates: g.coordinates.map((line) => projectRing(line)),
    };
  }
  return g;
}

type FC = {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    id?: string | number;
    properties: Record<string, unknown>;
    geometry: Geom;
  }>;
};

/** True when coordinates look like 0–1000 layout space (not already WGS84-sized). */
export function featureCollectionLooksLikeGameSpace(fc: FC): boolean {
  let maxAbs = 0;
  for (const f of fc.features) {
    walkCoords(f.geometry as Geom, (x, y) => {
      maxAbs = Math.max(maxAbs, Math.abs(x), Math.abs(y));
    });
  }
  return maxAbs > 90;
}

function walkCoords(g: Geom, visit: (x: number, y: number) => void): void {
  if (g.type === 'Polygon') {
    for (const pt of g.coordinates[0] ?? []) {
      if (pt.length >= 2) visit(pt[0], pt[1]);
    }
  } else if (g.type === 'MultiPolygon') {
    for (const poly of g.coordinates) {
      for (const pt of poly[0] ?? []) {
        if (pt.length >= 2) visit(pt[0], pt[1]);
      }
    }
  } else if (g.type === 'LineString') {
    for (const pt of g.coordinates) {
      if (pt.length >= 2) visit(pt[0], pt[1]);
    }
  } else if (g.type === 'MultiLineString') {
    for (const line of g.coordinates) {
      for (const pt of line) {
        if (pt.length >= 2) visit(pt[0], pt[1]);
      }
    }
  }
}

/** Clone features and project every supported geometry from game space to lng/lat. */
export function projectGameFeatureCollectionToMapLibre<T extends FC>(fc: T): T {
  return {
    ...fc,
    features: fc.features.map((f) => ({
      ...f,
      geometry: projectGeometry(f.geometry as Geom) as typeof f.geometry,
    })),
  } as T;
}
