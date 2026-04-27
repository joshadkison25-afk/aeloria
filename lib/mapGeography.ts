import type { RegionCoordinate, RegionDefinition } from '@/data/regions';

import { regions } from '@/data/regions';

import { worldStateKeyForRegion } from '@/lib/regionWorldKeys';

export { worldStateKeyForRegion };

export type MapBounds = {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
};

const PADDING = 0.01;

export function getDataBounds(data: RegionDefinition[] = regions): MapBounds {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = 0;
  let maxY = 0;
  for (const r of data) {
    for (const [x, y] of r.coordinates) {
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  }
  if (!Number.isFinite(minX)) {
    return { minX: 0, minY: 0, maxX: 1, maxY: 1 };
  }
  return { minX, minY, maxX, maxY };
}

export function toViewBox(
  x: number,
  y: number,
  bounds: MapBounds,
  viewW: number,
  viewH: number,
): { vx: number; vy: number } {
  const rw = Math.max(1e-6, bounds.maxX - bounds.minX);
  const rh = Math.max(1e-6, bounds.maxY - bounds.minY);
  const padX = rw * PADDING;
  const padY = rh * PADDING;
  const vx = ((x - bounds.minX + padX) / (rw + 2 * padX)) * viewW;
  const vy = ((y - bounds.minY + padY) / (rh + 2 * padY)) * viewH;
  return { vx, vy };
}

export function regionPathD(r: RegionDefinition, bounds: MapBounds, viewW: number, viewH: number): string {
  if (r.coordinates.length === 0) return '';
  const first = toViewBox(r.coordinates[0][0], r.coordinates[0][1], bounds, viewW, viewH);
  const rest = r.coordinates
    .slice(1)
    .map(([x, y]) => {
      const p = toViewBox(x, y, bounds, viewW, viewH);
      return `L ${p.vx} ${p.vy}`;
    })
    .join(' ');
  return `M ${first.vx} ${first.vy} ${rest} Z`;
}

export function pointInPolygon(
  x: number,
  y: number,
  poly: RegionCoordinate[],
  bounds: MapBounds,
  viewW: number,
  viewH: number,
): boolean {
  if (poly.length < 3) return false;
  const tf = (cx: number, cy: number) => toViewBox(cx, cy, bounds, viewW, viewH);
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i, i += 1) {
    const a = tf(poly[i][0], poly[i][1]);
    const b = tf(poly[j][0], poly[j][1]);
    const cross = (a.vy > y) !== (b.vy > y);
    if (cross && x < ((b.vx - a.vx) * (y - a.vy)) / (b.vy - a.vy + 1e-12) + a.vx) inside = !inside;
  }
  return inside;
}

export function findRegionAtViewPoint(
  vx: number,
  vy: number,
  data: RegionDefinition[] = regions,
  bounds: MapBounds = getDataBounds(data),
  viewW: number,
  viewH: number,
): RegionDefinition | null {
  for (let i = data.length - 1; i >= 0; i -= 1) {
    const r = data[i];
    if (pointInPolygon(vx, vy, r.coordinates, bounds, viewW, viewH)) return r;
  }
  return null;
}
