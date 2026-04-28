import type { RegionCoordinate, RegionDefinition } from '@/data/regions';

import { mapRegions } from '@/data/mapRegions';

import { worldStateKeyForRegion } from '@/lib/regionWorldKeys';

export { worldStateKeyForRegion };

export type MapBounds = {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
};

const PADDING = 0.01;

function regionRings(r: RegionDefinition): RegionCoordinate[][] {
  return r.polygons?.length ? r.polygons : [r.coordinates];
}

export function getDataBounds(data: RegionDefinition[] = mapRegions): MapBounds {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = 0;
  let maxY = 0;
  for (const r of data) {
    for (const ring of regionRings(r)) {
      for (const [x, y] of ring) {
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
      }
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

function isSamePoint(a: RegionCoordinate, b: RegionCoordinate): boolean {
  return Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9;
}

function smoothClosedRing(coords: RegionCoordinate[], iterations = 2): RegionCoordinate[] {
  let ring = coords.slice();
  if (ring.length > 1 && isSamePoint(ring[0], ring[ring.length - 1])) {
    ring = ring.slice(0, -1);
  }
  if (ring.length < 4) return ring;
  for (let step = 0; step < iterations; step += 1) {
    const next: RegionCoordinate[] = [];
    for (let i = 0; i < ring.length; i += 1) {
      const a = ring[i];
      const b = ring[(i + 1) % ring.length];
      next.push([a[0] * 0.75 + b[0] * 0.25, a[1] * 0.75 + b[1] * 0.25]);
      next.push([a[0] * 0.25 + b[0] * 0.75, a[1] * 0.25 + b[1] * 0.75]);
    }
    ring = next;
  }
  return ring;
}

export function regionPathD(r: RegionDefinition, bounds: MapBounds, viewW: number, viewH: number): string {
  return regionRings(r)
    .map((ring) => {
      const smoothedRing = smoothClosedRing(ring);
      if (smoothedRing.length === 0) return '';
      const first = toViewBox(smoothedRing[0][0], smoothedRing[0][1], bounds, viewW, viewH);
      const rest = smoothedRing
        .slice(1)
        .map(([x, y]) => {
          const p = toViewBox(x, y, bounds, viewW, viewH);
          return `L ${p.vx} ${p.vy}`;
        })
        .join(' ');
      return `M ${first.vx} ${first.vy} ${rest} Z`;
    })
    .filter(Boolean)
    .join(' ');
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

export function pointInRegion(
  x: number,
  y: number,
  r: RegionDefinition,
  bounds: MapBounds,
  viewW: number,
  viewH: number,
): boolean {
  return regionRings(r).some((ring) => pointInPolygon(x, y, ring, bounds, viewW, viewH));
}

export function findRegionAtViewPoint(
  vx: number,
  vy: number,
  data: RegionDefinition[] = mapRegions,
  bounds: MapBounds = getDataBounds(data),
  viewW: number,
  viewH: number,
): RegionDefinition | null {
  for (let i = data.length - 1; i >= 0; i -= 1) {
    const r = data[i];
    if (pointInRegion(vx, vy, r, bounds, viewW, viewH)) return r;
  }
  return null;
}
