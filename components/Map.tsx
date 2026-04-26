'use client';

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

import { regions } from '@/data/regions';
import type { RegionDefinition } from '@/data/regions';
import { getDataBounds, regionPathD, findRegionAtViewPoint, worldStateKeyForRegion } from '@/lib/mapGeography';
import { buildHexLandMask } from '@/lib/mapLandMask';

type HexTile = { id: string; x: number; y: number; row: number; col: number };
type ConfigMode = 'core' | 'optional' | 'custom';
type LoreSpeciesOption = { id: string; name: string };
type LoreLocation = { id: string; species: LoreSpeciesOption[] };
type LoreResponse = { locations?: LoreLocation[] };
type WorldRegionRow = {
  name?: string;
  controller?: string;
  canonical_faction?: string;
  factionId?: string;
  owner?: string;
};

type WorldResponse = {
  regions?: Record<string, WorldRegionRow>;
  /** Explicit hex id → owner (rare) */
  region_control?:
    | Array<{ hexId?: string; id?: string; factionId?: string; controller?: string; owner?: string }>
    | Record<string, { factionId?: string; controller?: string; owner?: string }>;
  faction_identities?: Record<string, { race?: string; type?: string } | unknown>;
  /** Object map (typical) or list rows from some sim versions */
  faction_power_state?: Record<string, number> | Array<{ faction?: string; militaryPower?: number } | string>;
  leadership_state?: Array<{ faction?: string }>;
};
type SavedMapLayout = {
  metadata: {
    speciesSet: string;
    configMode: string;
    version: number;
    savedAt: string;
    mapGrid?: { viewBox: [number, number]; hexSize: number };
  };
  ownership: Record<string, string | null>;
};
type MapLocation = { id: string; name: string; centerX: number; centerY: number; radius: number };
type LocationOption = { id: string; name: string };
type LocationAssignment = string | null;

const VIEWBOX_WIDTH = 100;
const VIEWBOX_HEIGHT = 100;
/** Flat/pointy-hex “width”. Smaller = denser territory cells (CK3-style). */
const HEX_SIZE = 1.2;
const HEX_WIDTH = HEX_SIZE;
const HEX_HEIGHT = HEX_SIZE;
const HEX_HORIZONTAL_STEP = HEX_WIDTH * 0.75;
const HEX_VERTICAL_STEP = HEX_HEIGHT * 0.866;

const MAP_LOCATIONS: MapLocation[] = [
  { id: 'faerwood', name: 'Faerwood', centerX: 20, centerY: 28, radius: 16 },
  { id: 'frostvale', name: 'Frostvale', centerX: 50, centerY: 16, radius: 13 },
  { id: 'farrock', name: 'Farrock', centerX: 79, centerY: 28, radius: 16 },
  { id: 'glenhaven', name: 'Glenhaven', centerX: 50, centerY: 42, radius: 16 },
  { id: 'twin-cities', name: 'Twin Cities', centerX: 52, centerY: 44, radius: 8 },
  { id: 'lostfeld', name: 'Lostfeld', centerX: 20, centerY: 72, radius: 16 },
  { id: 'vilefin', name: 'Vilefin', centerX: 58, centerY: 70, radius: 14 },
  { id: 'tidefall', name: 'Tidefall', centerX: 82, centerY: 68, radius: 15 },
  { id: 'orc-dominion', name: 'Orc Dominion', centerX: 88, centerY: 48, radius: 12 },
];

const locationColors: Record<string, string> = {
  'twin-cities': '#facc15',
  faerwood: '#166534',
  frostvale: '#93c5fd',
  farrock: '#92400e',
  lostfeld: '#6b7280',
  tidefall: '#0ea5e9',
  vilefin: '#4ade80',
  'orc-dominion': '#7c2d12',
};

function normalizeKey(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

function colorForFaction(factionId: string): string {
  let hash = 0;
  for (let i = 0; i < factionId.length; i += 1) hash = factionId.charCodeAt(i) + ((hash << 5) - hash);
  return `hsl(${Math.abs(hash) % 360}, 72%, 56%)`;
}

function hexPoints(x: number, y: number, width: number, height: number): string {
  const x0 = x + width * 0.5;
  const y0 = y;
  const x1 = x + width;
  const y1 = y + height * 0.25;
  const x2 = x + width;
  const y2 = y + height * 0.75;
  const x3 = x + width * 0.5;
  const y3 = y + height;
  const x4 = x;
  const y4 = y + height * 0.75;
  const x5 = x;
  const y5 = y + height * 0.25;
  return `${x0},${y0} ${x1},${y1} ${x2},${y2} ${x3},${y3} ${x4},${y4} ${x5},${y5}`;
}

function buildHexGrid(): HexTile[] {
  const tiles: HexTile[] = [];
  let index = 0;
  for (let row = 0; ; row += 1) {
    const y = row * HEX_VERTICAL_STEP;
    // Extra vertical extent so the bottom of the art (incl. ocean) gets full coverage without shifting old hex indices
    if (y > VIEWBOX_HEIGHT + 2 * HEX_HEIGHT) break;
    const rowOffset = row % 2 === 0 ? 0 : HEX_WIDTH * 0.5;
    for (let col = 0; ; col += 1) {
      const x = col * HEX_HORIZONTAL_STEP + rowOffset;
      if (x > VIEWBOX_WIDTH + HEX_WIDTH) break;
      tiles.push({ id: `hex-${index}`, x, y, row, col });
      index += 1;
    }
  }
  return tiles;
}

function deriveHexOwnership(world: WorldResponse | null): Record<string, string | null> {
  if (!world) return {};
  const map: Record<string, string | null> = {};
  if (Array.isArray(world.region_control)) {
    for (const row of world.region_control) {
      const hexId = row?.hexId || row?.id;
      if (hexId) map[hexId] = row?.factionId || row?.controller || row?.owner || null;
    }
    return map;
  }
  if (world.region_control && typeof world.region_control === 'object' && !Array.isArray(world.region_control)) {
    for (const [hexId, row] of Object.entries(world.region_control)) {
      map[hexId] = row?.factionId || row?.controller || row?.owner || null;
    }
    return map;
  }
  return map;
}

/**
 * Map-space anchor (0–100 viewbox) for each *sim* region, tuned to match the isle layout.
 * Each sim region becomes a Voronoi site: every hex is painted by the *nearest* site's controller
 * (so all factions with a region get territory; borders follow geography sensibly).
 */
const SIM_REGION_SEEDS: Record<string, { x: number; y: number }> = {
  faerwood: { x: 20, y: 28 },
  glenhaven: { x: 50, y: 40 },
  tidefall: { x: 82, y: 66 },
  eresteron: { x: 50, y: 48 },
  eldoria: { x: 44, y: 36 },
  wintermark: { x: 50, y: 15 },
  lostfeld: { x: 20, y: 70 },
  groth: { x: 12, y: 52 },
  gilgeth: { x: 22, y: 60 },
  vilefin: { x: 58, y: 70 },
  varkuun: { x: 70, y: 56 },
  'dur-khadur': { x: 32, y: 66 },
  'dreadwind-isles': { x: 90, y: 78 },
  stonebreak: { x: 40, y: 36 },
  // Common alternates from builders / name drift
  farrock: { x: 78, y: 28 },
  'orc-dominion': { x: 16, y: 46 },
  frostvale: { x: 50, y: 16 },
  erester: { x: 49, y: 47 },
  eldor: { x: 43, y: 35 },
};

const ORPHAN_FACTION_LANDMARKS: { x: number; y: number }[] = [
  { x: 8, y: 18 },
  { x: 91, y: 22 },
  { x: 92, y: 48 },
  { x: 10, y: 78 },
  { x: 50, y: 88 },
  { x: 6, y: 50 },
  { x: 94, y: 66 },
  { x: 30, y: 12 },
  { x: 72, y: 14 },
  { x: 48, y: 26 },
  { x: 62, y: 32 },
  { x: 36, y: 52 },
  { x: 78, y: 40 },
  { x: 14, y: 64 },
  { x: 86, y: 90 },
  { x: 52, y: 58 },
];

function simRegionPoint(norm: string): { x: number; y: number } {
  if (SIM_REGION_SEEDS[norm]) return SIM_REGION_SEEDS[norm];
  // Match partial: e.g. "winter" -> wintermark
  if (norm.includes('winter') || norm === 'frostvale') {
    return SIM_REGION_SEEDS.wintermark || SIM_REGION_SEEDS.frostvale;
  }
  if (norm.includes('gilgeth')) return SIM_REGION_SEEDS.gilgeth;
  if (norm.includes('groth')) return SIM_REGION_SEEDS.groth;
  if (norm.includes('orc')) return SIM_REGION_SEEDS['orc-dominion'];
  if (norm.includes('eresteron')) return SIM_REGION_SEEDS.eresteron;
  if (norm.includes('eldoria')) return SIM_REGION_SEEDS.eldoria;
  if (norm.includes('dreadwind')) return SIM_REGION_SEEDS['dreadwind-isles'];
  if (norm.includes('stonebreak') || norm.includes('monastery')) return SIM_REGION_SEEDS.stonebreak;
  for (const loc of MAP_LOCATIONS) {
    if (loc.id.length >= 3 && (norm === loc.id || norm.includes(loc.id) || loc.id.includes(norm))) {
      return { x: loc.centerX, y: loc.centerY };
    }
  }
  // Hash to a stable interior point
  let h = 0;
  for (let i = 0; i < norm.length; i += 1) h = norm.charCodeAt(i) + ((h << 5) - h);
  const t = (Math.abs(h) % 100) / 100;
  return { x: 22 + t * 56, y: 22 + (1 - t) * 52 };
}

/**
 * For each *sim* region we place a site; every hex is owned by the *nearest* site's faction (Voronoi in map space).
 * Factions in the sim that control no region get extra sites around the map edge so they still appear.
 */
function buildHexOwnershipFromWorld(world: WorldResponse, hexTiles: HexTile[]): Record<string, string | null> {
  const out: Record<string, string | null> = {};
  for (const h of hexTiles) out[h.id] = null;
  if (!hexTiles.length) return out;

  const seeds: Array<{ x: number; y: number; controller: string }> = [];
  const representedControllers = new Set<string>();

  if (world.regions && typeof world.regions === 'object') {
    for (const [key, row] of Object.entries(world.regions)) {
      const r = row as WorldRegionRow;
      const ctrl = r.controller || r.factionId || r.owner;
      if (!ctrl) continue;
      const n = normalizeKey((r.name && String(r.name)) || key);
      const p = simRegionPoint(n) ?? { x: 50, y: 50 };
      const c = String(ctrl).trim();
      seeds.push({ x: p.x, y: p.y, controller: c });
      representedControllers.add(c);
    }
  }

  const allFactions = extractWorldFactions(world);
  let orphanI = 0;
  for (const f of allFactions) {
    if (representedControllers.has(f.id)) continue;
    const spot = ORPHAN_FACTION_LANDMARKS[orphanI % ORPHAN_FACTION_LANDMARKS.length];
    orphanI += 1;
    seeds.push({ x: spot.x, y: spot.y, controller: f.id });
  }

  if (seeds.length === 0) return out;

  for (const hex of hexTiles) {
    let bestD = Number.POSITIVE_INFINITY;
    let best: string | null = null;
    for (const s of seeds) {
      const d = (hex.x - s.x) ** 2 + (hex.y - s.y) ** 2;
      if (d < bestD) {
        bestD = d;
        best = s.controller;
      }
    }
    out[hex.id] = best;
  }
  return out;
}

/** Factions currently in the sim (display names, used as paint ids to match `regions.controller`). */
function extractWorldFactions(w: WorldResponse | null): { id: string; name: string }[] {
  if (!w) return [];
  const seen = new Set<string>();
  const add = (s: string | undefined) => {
    const t = (s || '').trim();
    if (t) seen.add(t);
  };
  if (w.faction_identities) for (const k of Object.keys(w.faction_identities)) add(k);
  const fps = w.faction_power_state;
  if (fps) {
    if (Array.isArray(fps)) {
      for (const row of fps) {
        if (row && typeof row === 'object' && 'faction' in (row as object)) {
          add((row as { faction?: string }).faction);
        } else if (typeof row === 'string') {
          add(row);
        }
      }
    } else {
      for (const k of Object.keys(fps as Record<string, unknown>)) add(k);
    }
  }
  if (w.leadership_state) for (const row of w.leadership_state) add(row.faction);
  if (w.regions) for (const row of Object.values(w.regions)) add((row as WorldRegionRow).controller);
  return Array.from(seen)
    .map((name) => ({ id: name, name }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

function locationForHex(x: number, y: number): MapLocation | null {
  let nearest: MapLocation | null = null;
  let nearestNorm = Number.POSITIVE_INFINITY;
  let insideBest: MapLocation | null = null;
  let insideBestNorm = Number.POSITIVE_INFINITY;

  for (const location of MAP_LOCATIONS) {
    const dx = x - location.centerX;
    const dy = y - location.centerY;
    const norm = Math.sqrt(dx * dx + dy * dy) / location.radius;
    if (norm < nearestNorm) {
      nearest = location;
      nearestNorm = norm;
    }
    if (norm <= 1 && norm < insideBestNorm) {
      insideBest = location;
      insideBestNorm = norm;
    }
  }
  return insideBest || nearest;
}

/**
 * Basemap in `public/`. Default: your paint reference (`aeloria-basemap-paint.png`). Override with
 * `NEXT_PUBLIC_MAP_ATLAS_URL` (e.g. `/aeloria-basemap-isometric.png` or OpenAI output).
 */
const MAP_ATLAS_SRC = process.env.NEXT_PUBLIC_MAP_ATLAS_URL || '/aeloria-basemap-paint.png';

type MapView = { x: number; y: number; k: number };

const MAX_K = 3.4;
const WHEEL_ZOOM = 1.12;

/**
 * Keep pan/zoom so the image never leaves “empty” past its edges: no panning outside the
 * map, and the minimum scale is the “fit full map in view” level (min(W/Cw, H/Ch)).
 * Transform matches `translate(x,y) scale(k)` with origin 0,0: screen = k*local + (x,y) on the top-left.
 */
function clampView(
  v: MapView,
  W: number,
  H: number,
  Cw: number,
  Ch: number,
): MapView {
  if (W < 1 || H < 1 || Cw < 1 || Ch < 1) return { ...v, k: Math.min(MAX_K, v.k) };
  const kMinFit = Math.min(W / Cw, H / Ch);
  const k2 = Math.min(MAX_K, Math.max(kMinFit, v.k));
  const sw = k2 * Cw;
  const sh = k2 * Ch;
  let tx = v.x;
  let ty = v.y;
  if (sw >= W) {
    tx = Math.min(0, Math.max(W - sw, tx));
  } else {
    tx = (W - sw) / 2;
  }
  if (sh >= H) {
    ty = Math.min(0, Math.max(H - sh, ty));
  } else {
    ty = (H - sh) / 2;
  }
  return { x: tx, y: ty, k: k2 };
}

function getViewportContentDims(
  vp: HTMLDivElement | null,
  content: HTMLDivElement | null,
): { W: number; H: number; Cw: number; Ch: number } | null {
  if (!vp || !content) return null;
  const W = vp.clientWidth;
  const H = vp.clientHeight;
  const Cw = content.offsetWidth;
  const Ch = content.offsetHeight;
  if (W < 1 || H < 1 || Cw < 1 || Ch < 1) return null;
  return { W, H, Cw, Ch };
}

/** Clamp a requested zoom to [fit, MAX_K] before applying zoom-toward-point math. */
function clampZoomK(rawK: number, dims: { W: number; H: number; Cw: number; Ch: number } | null): number {
  if (!dims) return Math.min(MAX_K, Math.max(0.02, rawK));
  const kMinFit = Math.min(dims.W / dims.Cw, dims.H / dims.Ch);
  return Math.min(MAX_K, Math.max(kMinFit, rawK));
}

function useMapViewport() {
  const ref = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<MapView>({ x: 0, y: 0, k: 1 });
  const [view, setView] = useState<MapView>({ x: 0, y: 0, k: 1 });
  const [isMiddleDrag, setIsMiddleDrag] = useState(false);
  const panning = useRef(false);
  const panStart = useRef({ scrX: 0, scrY: 0, x: 0, y: 0 });
  viewRef.current = view;

  const setViewClamped = useCallback((next: MapView) => {
    setView(() => {
      const dims = getViewportContentDims(ref.current, contentRef.current);
      if (!dims) {
        return { x: next.x, y: next.y, k: Math.min(MAX_K, next.k) };
      }
      return clampView(next, dims.W, dims.H, dims.Cw, dims.Ch);
    });
  }, []);

  const reapplyBounds = useCallback(() => {
    const dims = getViewportContentDims(ref.current, contentRef.current);
    if (!dims) return;
    setView((v) => clampView(v, dims.W, dims.H, dims.Cw, dims.Ch));
  }, []);

  useLayoutEffect(() => {
    const vp = ref.current;
    if (!vp) return;
    const ro = new ResizeObserver(reapplyBounds);
    ro.observe(vp);
    const co = contentRef.current;
    if (co) {
      ro.observe(co);
    } else {
      requestAnimationFrame(() => {
        const c2 = contentRef.current;
        if (c2) ro.observe(c2);
        reapplyBounds();
      });
    }
    requestAnimationFrame(reapplyBounds);
    return () => ro.disconnect();
  }, [reapplyBounds]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const { x: px, y: py, k: prevK } = viewRef.current;
      if (prevK < 1e-6) return;
      const rect = el.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const factor = e.deltaY > 0 ? 1 / WHEEL_ZOOM : WHEEL_ZOOM;
      const rawK = prevK * factor;
      const dims = getViewportContentDims(ref.current, contentRef.current);
      const k1 = clampZoomK(rawK, dims);
      if (Math.abs(k1 - prevK) < 1e-6) return;
      const cx = (mx - px) / prevK;
      const cy = (my - py) / prevK;
      setViewClamped({ x: mx - cx * k1, y: my - cy * k1, k: k1 });
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [setViewClamped]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement) return;
      if (e.metaKey || e.ctrlKey) return;
      const step = 40;
      const { x, y, k } = viewRef.current;
      if (e.key === 'ArrowLeft' || e.key === 'a' || e.key === 'A') {
        e.preventDefault();
        setViewClamped({ x: x + step, y, k });
      } else if (e.key === 'ArrowRight' || e.key === 'd' || e.key === 'D') {
        e.preventDefault();
        setViewClamped({ x: x - step, y, k });
      } else if (e.key === 'ArrowUp' || e.key === 'w' || e.key === 'W') {
        e.preventDefault();
        setViewClamped({ x, y: y + step, k });
      } else if (e.key === 'ArrowDown' || e.key === 's' || e.key === 'S') {
        e.preventDefault();
        setViewClamped({ x, y: y - step, k });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setViewClamped]);

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (e.button !== 1) return;
      e.preventDefault();
      e.stopPropagation();
      panning.current = true;
      setIsMiddleDrag(true);
      const { x, y } = viewRef.current;
      panStart.current = { scrX: e.clientX, scrY: e.clientY, x, y };
      try {
        (e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId);
      } catch {
        // ignore
      }
    },
    [],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!panning.current) return;
      e.preventDefault();
      const s = panStart.current;
      const { k } = viewRef.current;
      const x = s.x + (e.clientX - s.scrX);
      const y = s.y + (e.clientY - s.scrY);
      setViewClamped({ x, y, k });
    },
    [setViewClamped],
  );

  const endPan = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!panning.current) return;
    if (e.type !== 'pointercancel' && e.button !== 1) return;
    panning.current = false;
    setIsMiddleDrag(false);
    try {
      (e.currentTarget as HTMLDivElement).releasePointerCapture(e.pointerId);
    } catch {
      // ignore
    }
  }, []);

  const nudgeZoom = useCallback(
    (direction: 1 | -1) => {
      const el = ref.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const mx = rect.width * 0.5;
      const my = rect.height * 0.5;
      const { x: px, y: py, k: prevK } = viewRef.current;
      if (prevK < 1e-6) return;
      const rawK = prevK * (direction > 0 ? WHEEL_ZOOM : 1 / WHEEL_ZOOM);
      const dims = getViewportContentDims(ref.current, contentRef.current);
      const k1 = clampZoomK(rawK, dims);
      if (Math.abs(k1 - prevK) < 1e-6) return;
      const cx = (mx - px) / prevK;
      const cy = (my - py) / prevK;
      setViewClamped({ x: mx - cx * k1, y: my - cy * k1, k: k1 });
    },
    [setViewClamped],
  );

  const reset = useCallback(() => setViewClamped({ x: 0, y: 0, k: 1 }), [setViewClamped]);

  return {
    ref,
    contentRef,
    reapplyBounds,
    view,
    isMiddleDrag,
    onPointerDown,
    onPointerMove,
    onPointerUp: endPan,
    onPointerCancel: endPan,
    nudgeZoom,
    reset,
  };
}

function regionControllerLabel(world: WorldResponse | null, r: RegionDefinition): string {
  if (!world?.regions) return '—';
  const key = worldStateKeyForRegion(r);
  const row = world.regions[key] as WorldRegionRow | undefined;
  if (!row) return '—';
  return String(row.controller || row.canonical_faction || '—');
}

export default function FantasyMap() {
  const hexTiles = useMemo(() => buildHexGrid(), []);
  const dataBounds = useMemo(() => getDataBounds(regions), []);
  /** On by default so the hex layer covers land + water for painting. */
  const [showStrategicHex, setShowStrategicHex] = useState(true);
  /** When false, lore region shapes are for hit-test / hover only — no sim faction wash. */
  const [showPoliticalTints, setShowPoliticalTints] = useState(false);
  const [hoveredRegion, setHoveredRegion] = useState<RegionDefinition | null>(null);
  const [selectedRegion, setSelectedRegion] = useState<RegionDefinition | null>(null);
  const [world, setWorld] = useState<WorldResponse | null>(null);
  const [loreLocations, setLoreLocations] = useState<LoreLocation[]>([]);
  const [configMode, setConfigMode] = useState<ConfigMode>('core');
  const [layoutsByConfig, setLayoutsByConfig] = useState<Record<string, Record<string, string | null>>>({});
  const [savedMapFiles, setSavedMapFiles] = useState<string[]>([]);
  const [selectedMapFile, setSelectedMapFile] = useState('');
  const [isEditMode, setIsEditMode] = useState(true);
  const [isLocationPaintMode, setIsLocationPaintMode] = useState(false);
  const [isEraseMode, setIsEraseMode] = useState(false);
  const [locationByHex, setLocationByHex] = useState<Record<string, LocationAssignment>>({});
  const [selectedLocationId, setSelectedLocationId] = useState('');
  const [selectedFactionId, setSelectedFactionId] = useState('');
  const [isMouseDown, setIsMouseDown] = useState(false);
  const [hoveredHexId, setHoveredHexId] = useState<string | null>(null);
  const [selectedHexId, setSelectedHexId] = useState<string | null>(null);
  const [brushRadius, setBrushRadius] = useState<0 | 1 | 2>(1);
  const [landByHex, setLandByHex] = useState<Record<string, boolean> | null>(null);
  const [landMaskStatus, setLandMaskStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('loading');

  const hoveredHex = hoveredHexId ? hexTiles.find((hex) => hex.id === hoveredHexId) || null : null;
  const selectedHex = selectedHexId ? hexTiles.find((hex) => hex.id === selectedHexId) || null : null;

  const backendOwnership = useMemo(() => {
    const fromControl = deriveHexOwnership(world);
    if (Object.keys(fromControl).length > 0) return fromControl;
    if (world?.regions && typeof world.regions === 'object' && Object.keys(world.regions).length > 0) {
      return buildHexOwnershipFromWorld(world, hexTiles);
    }
    return {};
  }, [world, hexTiles]);
  const configKey = useMemo(() => `lore::${configMode}`, [configMode]);

  const allLoreFactions = useMemo(() => loreLocations.flatMap((location) => location.species || []), [loreLocations]);
  const worldFactions = useMemo(() => extractWorldFactions(world), [world]);
  const allSpeciesOptions = useMemo(() => {
    const unique = new Map<string, string>();
    for (const location of loreLocations) {
      for (const species of location.species || []) {
        if (!species?.id) continue;
        if (!unique.has(species.id)) unique.set(species.id, species.name || species.id);
      }
    }
    return Array.from(unique.entries()).map(([id, name]) => ({ id, name }));
  }, [loreLocations]);
  /** Lore species + current sim factions (for painting and labels). */
  const allPaintFactionOptions = useMemo(() => {
    const m = new Map<string, { id: string; name: string }>();
    for (const w of worldFactions) m.set(w.id, w);
    for (const s of allSpeciesOptions) {
      if (!m.has(s.id)) m.set(s.id, s);
    }
    return Array.from(m.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [worldFactions, allSpeciesOptions]);
  const factionNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const faction of allLoreFactions) map.set(faction.id, faction.name);
    for (const w of worldFactions) {
      map.set(w.id, w.name);
    }
    return map;
  }, [allLoreFactions, worldFactions]);

  const locationOptions = useMemo<LocationOption[]>(
    () => loreLocations.map((item) => ({ id: item.id, name: item.id.replace(/-/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase()) })),
    [loreLocations],
  );

  const activeLocationId = useMemo(() => {
    const source = selectedHex || hoveredHex;
    if (!source) return null;
    if (Object.prototype.hasOwnProperty.call(locationByHex, source.id)) {
      const assigned = locationByHex[source.id];
      return assigned === '' ? null : assigned;
    }
    return locationForHex(source.x, source.y)?.id || null;
  }, [selectedHex, hoveredHex, locationByHex]);

  const activeLocationName = useMemo(() => {
    if (!activeLocationId) return null;
    return locationOptions.find((item) => item.id === activeLocationId)?.name || activeLocationId;
  }, [activeLocationId, locationOptions]);

  const speciesByLocation = useMemo(() => {
    const byLocation = new Map<string, Array<{ id: string; name: string }>>();
    for (const location of loreLocations) byLocation.set(normalizeKey(location.id), (location.species || []).slice(0, 5));
    return byLocation;
  }, [loreLocations]);

  const locationFactionOptions = useMemo(() => {
    if (!activeLocationId) return [];
    return speciesByLocation.get(normalizeKey(activeLocationId)) || [];
  }, [activeLocationId, speciesByLocation]);

  useEffect(() => {
    // Auto-select a paint faction when nothing is selected (lore for this location, else any).
    if (!selectedFactionId) {
      setSelectedFactionId(locationFactionOptions[0]?.id || allPaintFactionOptions[0]?.id || '');
    }
  }, [locationFactionOptions, allPaintFactionOptions, selectedFactionId]);

  useEffect(() => {
    if (!selectedLocationId && locationOptions.length > 0) {
      setSelectedLocationId(locationOptions[0].id);
    }
  }, [locationOptions, selectedLocationId]);

  useEffect(() => {
    // Keep painting modes mutually exclusive and never both off.
    if (isLocationPaintMode && isEditMode) {
      setIsEditMode(false);
      return;
    }
    if (!isLocationPaintMode && !isEditMode) {
      setIsEditMode(true);
    }
  }, [isLocationPaintMode, isEditMode]);

  useEffect(() => {
    setLayoutsByConfig((prev) => {
      if (prev[configKey]) return prev;
      const seeded: Record<string, string | null> = {};
      for (const hex of hexTiles) seeded[hex.id] = null;
      return { ...prev, [configKey]: seeded };
    });
  }, [configKey, hexTiles]);

  const effectiveOwnership = useMemo(() => {
    const layout = layoutsByConfig[configKey];
    if (layout) return layout;
    const seeded: Record<string, string | null> = {};
    for (const hex of hexTiles) seeded[hex.id] = null;
    return seeded;
  }, [configKey, hexTiles, layoutsByConfig]);
  const factionByHex = effectiveOwnership;

  const mapViewport = useMapViewport();
  const pointsByHexId = useMemo(() => {
    const m = new Map<string, string>();
    for (const h of hexTiles) m.set(h.id, hexPoints(h.x, h.y, HEX_WIDTH, HEX_HEIGHT));
    return m;
  }, [hexTiles]);
  const hexCenterById = useMemo(() => {
    const m = new Map<string, { cx: number; cy: number }>();
    for (const h of hexTiles) {
      m.set(h.id, { cx: h.x + HEX_WIDTH * 0.5, cy: h.y + HEX_HEIGHT * 0.5 });
    }
    return m;
  }, [hexTiles]);
  function updateActiveLayout(mutator: (current: Record<string, string | null>) => Record<string, string | null>) {
    setLayoutsByConfig((prev) => {
      const current = prev[configKey] || effectiveOwnership;
      return { ...prev, [configKey]: mutator(current) };
    });
  }

  function setFactionByHex(mutator: (current: Record<string, string | null>) => Record<string, string | null>) {
    updateActiveLayout(mutator);
  }

  function brushTargets(origin: HexTile): HexTile[] {
    if (brushRadius === 0) return [origin];
    const o = hexCenterById.get(origin.id);
    if (!o) return [origin];
    const maxDist = (brushRadius + 0.22) * HEX_SIZE * 1.65;
    const out: HexTile[] = [];
    for (const h of hexTiles) {
      const p = hexCenterById.get(h.id);
      if (!p) continue;
      const dx = p.cx - o.cx;
      const dy = p.cy - o.cy;
      if (Math.hypot(dx, dy) <= maxDist) out.push(h);
    }
    return out;
  }

  function handleHexPaintClick(hex: HexTile) {
    const targets = brushTargets(hex);
    const isLocationModeActive = isLocationPaintMode;
    const isFactionModeActive = !isLocationModeActive && isEditMode;
    const geometryLocationId = locationForHex(hex.x, hex.y)?.id || null;
    const hasManualLocation = Object.prototype.hasOwnProperty.call(locationByHex, hex.id);
    const manualLocation = hasManualLocation ? locationByHex[hex.id] : null;
    const resolvedLocationId =
      manualLocation === ''
        ? null
        : manualLocation || selectedLocationId || geometryLocationId || locationOptions[0]?.id || null;

    if (isLocationModeActive) {
      if (isEraseMode) {
        setLocationByHex((prev) => {
          const next = { ...prev };
          for (const t of targets) next[t.id] = '';
          return next;
        });
        return;
      }
      const locationId = resolvedLocationId || 'unassigned';
      setLocationByHex((prev) => {
        const next = { ...prev };
        for (const t of targets) next[t.id] = locationId;
        return next;
      });
      return;
    }

    if (isFactionModeActive) {
      if (isEraseMode) {
        setFactionByHex((prev) => {
          const next = { ...prev };
          for (const t of targets) next[t.id] = null;
          return next;
        });
        return;
      }
      const speciesForLocation = resolvedLocationId ? speciesByLocation.get(normalizeKey(resolvedLocationId)) || [] : [];
      const factionId =
        selectedFactionId || speciesForLocation[0]?.id || allPaintFactionOptions[0]?.id || 'unclaimed';
      if (!selectedFactionId && factionId) setSelectedFactionId(factionId);
      setFactionByHex((prev) => {
        const next = { ...prev };
        for (const t of targets) next[t.id] = factionId;
        return next;
      });
    }
  }

  useEffect(() => {
    const stopDrag = () => setIsMouseDown(false);
    window.addEventListener('mouseup', stopDrag);
    return () => window.removeEventListener('mouseup', stopDrag);
  }, []);

  function clearLayout() {
    updateActiveLayout((current) => {
      const next = { ...current };
      for (const id of Object.keys(next)) next[id] = null;
      return next;
    });
  }

  function clearAllPaint() {
    const clearedLocations: Record<string, LocationAssignment> = {};
    for (const hex of hexTiles) clearedLocations[hex.id] = '';
    setLocationByHex(clearedLocations);
    clearLayout();
  }

  function resetLayoutToBackend() {
    updateActiveLayout(() => {
      const next: Record<string, string | null> = {};
      for (const hex of hexTiles) next[hex.id] = backendOwnership?.[hex.id] ?? null;
      return next;
    });
  }

  async function loadWorld() {
    try {
      const response = await fetch('/api/world', { cache: 'no-store' });
      if (!response.ok) throw new Error('Failed to load world.');
      setWorld((await response.json()) as WorldResponse);
    } catch (error) {
      console.error('Could not load /api/world:', error);
    }
  }

  async function loadLoreData() {
    try {
      const response = await fetch('/api/lore', { cache: 'no-store' });
      if (!response.ok) throw new Error('Failed to load lore data.');
      const payload = (await response.json()) as LoreResponse;
      const locations = payload.locations || [];
      setLoreLocations(locations);
    } catch (error) {
      console.error('Could not load lore data:', error);
    }
  }

  async function listSavedMaps() {
    try {
      const response = await fetch('/api/lore/maps', { cache: 'no-store' });
      if (!response.ok) throw new Error('Failed to list saved maps.');
      const payload = (await response.json()) as { files?: string[] };
      const files = payload.files || [];
      setSavedMapFiles(files);
      if (files.length > 0 && !selectedMapFile) setSelectedMapFile(files[0]);
    } catch (error) {
      console.error('Could not list saved maps:', error);
    }
  }

  async function saveCurrentLayout() {
    const baseName = configMode === 'custom' ? 'map_custom' : `map_${configMode}`;
    const payload: SavedMapLayout = {
      metadata: {
        speciesSet: activeLocationId || 'all',
        configMode,
        version: 2,
        savedAt: new Date().toISOString(),
        mapGrid: { viewBox: [VIEWBOX_WIDTH, VIEWBOX_HEIGHT] as [number, number], hexSize: HEX_SIZE },
      },
      ownership: effectiveOwnership,
    };
    try {
      const response = await fetch('/api/lore/maps', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fileName: `${baseName}.json`, layout: payload }),
      });
      if (!response.ok) throw new Error('Failed to save map layout.');
      const saved = (await response.json()) as { fileName?: string };
      if (saved.fileName) setSelectedMapFile(saved.fileName);
      await listSavedMaps();
    } catch (error) {
      console.error('Could not save map layout:', error);
    }
  }

  async function loadSelectedLayout() {
    if (!selectedMapFile) return;
    try {
      const response = await fetch(`/api/lore/maps/${encodeURIComponent(selectedMapFile)}`, { cache: 'no-store' });
      if (!response.ok) throw new Error('Failed to load selected map layout.');
      const payload = (await response.json()) as { layout?: SavedMapLayout };
      if (!payload.layout?.ownership) return;
      const next: Record<string, string | null> = {};
      for (const hex of hexTiles) next[hex.id] = payload.layout.ownership[hex.id] ?? null;
      setLayoutsByConfig((prev) => ({ ...prev, [configKey]: next }));
    } catch (error) {
      console.error('Could not load selected map layout:', error);
    }
  }

  useEffect(() => {
    void loadWorld();
    void loadLoreData();
    void listSavedMaps();
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLandMaskStatus('loading');
    void (async () => {
      try {
        const map = await buildHexLandMask(MAP_ATLAS_SRC, hexTiles, VIEWBOX_WIDTH, VIEWBOX_HEIGHT, {
          hexW: HEX_WIDTH,
          hexH: HEX_HEIGHT,
          maxSampleWidth: 860,
        });
        if (cancelled) return;
        setLandByHex(map);
        setLandMaskStatus('ready');
      } catch (e) {
        // eslint-disable-next-line no-console
        console.error('Coast / land mask failed, painting full grid:', e);
        if (cancelled) return;
        const allLand: Record<string, boolean> = {};
        for (const h of hexTiles) allLand[h.id] = true;
        setLandByHex(allLand);
        setLandMaskStatus('error');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [hexTiles]);

  const {
    ref: mapViewportRef,
    contentRef: mapContentRef,
    reapplyBounds: reapplyMapBounds,
    view: mapView,
    isMiddleDrag,
    onPointerDown: onMapPointerDown,
    onPointerMove: onMapPointerMove,
    onPointerUp: onMapPointerUp,
    onPointerCancel: onMapPointerCancel,
    nudgeZoom,
    reset: resetMapView,
  } = mapViewport;

  const polSvgRef = useRef<SVGSVGElement | null>(null);

  const updatePoliticalHover = useCallback((clientX: number, clientY: number, svg: SVGSVGElement) => {
    const rect = svg.getBoundingClientRect();
    const x = ((clientX - rect.left) / Math.max(1, rect.width)) * VIEWBOX_WIDTH;
    const y = ((clientY - rect.top) / Math.max(1, rect.height)) * VIEWBOX_HEIGHT;
    setHoveredRegion(findRegionAtViewPoint(x, y, regions, dataBounds, VIEWBOX_WIDTH, VIEWBOX_HEIGHT));
  }, [dataBounds]);

  const politicalFill = useCallback(
    (r: RegionDefinition) => {
      const id = (() => {
        if (!world?.regions) return null;
        const key = worldStateKeyForRegion(r);
        const row = world.regions[key] as WorldRegionRow | undefined;
        if (!row) return null;
        return row.controller || row.canonical_faction || null;
      })();
      if (id) return colorForFaction(String(id));
      return 'rgba(55, 55, 62, 0.38)';
    },
    [world],
  );

  return (
    <div className="fantasy-map-shell">
      <aside className="fantasy-map-sidebar">
        <div className="fantasy-map-sidebar__inner" style={{ maxHeight: '100vh', overflowY: 'auto' }}>
          <p className="fantasy-map-sidebar__eyebrow">Strategic cartography</p>
          <h2 className="fantasy-map-sidebar__title" style={{ fontSize: '1.5rem' }}>
            Realm map
          </h2>
          <p className="fantasy-map-sidebar__description" style={{ fontSize: '0.88rem' }}>
            Map loads with a <strong>blank</strong> canvas: paint on the hex layer, or turn on tints. Scroll to
            zoom, middle-drag to pan, WASD to move.
          </p>

          <div className="fantasy-map-sidebar__card" style={{ marginTop: 8 }}>
            <label
              className="fantasy-map-sidebar__item"
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}
            >
              <span>Sim political tints (regions)</span>
              <input
                type="checkbox"
                checked={showPoliticalTints}
                onChange={(e) => setShowPoliticalTints(e.target.checked)}
              />
            </label>
            <label
              className="fantasy-map-sidebar__item"
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginTop: 6 }}
            >
              <span>Strategic hex grid (paint)</span>
              <input
                type="checkbox"
                checked={showStrategicHex}
                onChange={(e) => setShowStrategicHex(e.target.checked)}
              />
            </label>
            {selectedRegion && (
              <div style={{ marginTop: 10, fontSize: '0.85rem', lineHeight: 1.5 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                  <strong>{selectedRegion.name}</strong>
                  <button
                    type="button"
                    className="fantasy-map-sidebar__item"
                    style={{ fontSize: '0.75rem', padding: '4px 8px' }}
                    onClick={() => setSelectedRegion(null)}
                  >
                    Clear
                  </button>
                </div>
                <div style={{ marginTop: 6, color: 'rgba(246,235,209,0.75)' }}>{selectedRegion.description}</div>
                <div style={{ marginTop: 8 }}>
                  <span style={{ color: 'rgba(246,235,209,0.6)' }}>Controller: </span>
                  {regionControllerLabel(world, selectedRegion)}
                </div>
              </div>
            )}
            {hoveredRegion && !selectedRegion && (
              <p style={{ marginTop: 8, fontSize: '0.8rem', opacity: 0.75 }}>Hover: {hoveredRegion.name}</p>
            )}
          </div>

          <div className="fantasy-map-sidebar__card" style={{ marginTop: 8 }}>
            <h3 className="fantasy-map-sidebar__label" style={{ marginTop: 0 }}>
              At a glance
            </h3>
            <p className="fantasy-map-sidebar__empty" style={{ fontSize: '0.9rem' }}>
              Species: <strong>{selectedFactionId || 'None'}</strong> · Config: <strong>{configMode}</strong> · Location: <strong>{activeLocationName || 'None'}</strong>
            </p>
            <p className="fantasy-map-sidebar__empty" style={{ fontSize: '0.9rem' }}>
              Mode: <strong>{isLocationPaintMode ? 'Location' : 'Faction'}</strong> · Tool: <strong>{isEraseMode ? 'Erase' : 'Paint'}</strong>
            </p>
            <p className="fantasy-map-sidebar__empty" style={{ fontSize: '0.82rem' }}>
              Coastline:{' '}
              <strong>
                {landMaskStatus === 'loading' && 'Tracing from atlas…'}
                {landMaskStatus === 'ready' && 'Territory on land only'}
                {landMaskStatus === 'error' && 'Could not read sea — full grid paint'}
                {landMaskStatus === 'idle' && '—'}
              </strong>
            </p>
          </div>

          <div className="fantasy-map-sidebar__card">
            <h3 className="fantasy-map-sidebar__label">Color key</h3>
            <p className="fantasy-map-sidebar__empty" style={{ fontSize: '0.8rem', marginBottom: 6 }}>
              Faction paint (hash colors) and named locations. Same palette as the hex map.
            </p>
            <div className="fantasy-map-legend" style={{ maxHeight: 160, overflow: 'auto' }}>
              {allPaintFactionOptions.slice(0, 36).map((f) => (
                <div key={f.id} className="fantasy-map-legend__row">
                  <span className="fantasy-map-legend__swatch" style={{ background: colorForFaction(f.id) }} title={f.id} />
                  <span className="fantasy-map-legend__name">{f.name}</span>
                </div>
              ))}
              {allPaintFactionOptions.length > 36 && (
                <p style={{ fontSize: '0.75rem', opacity: 0.7, margin: '6px 0 0' }}>+{allPaintFactionOptions.length - 36} more in paint lists.</p>
              )}
            </div>
          </div>

          <div className="fantasy-map-sidebar__card">
            <h3 className="fantasy-map-sidebar__label">Current sim (world)</h3>
            <p className="fantasy-map-sidebar__empty" style={{ fontSize: '0.86rem', marginBottom: 8 }}>
              Factions: <strong>{worldFactions.length}</strong> · Territories: each <code>sim region</code> has a point on
              the map; every hex is painted by the <strong>nearest</strong> region’s controller (so all factions with
              regions show up, with natural borders). Factions with no region get a small claim near the map edge. Run{' '}
              <strong>Load from world</strong> to refresh.
            </p>
            {worldFactions.length > 0 && (
              <div
                className="fantasy-map-sidebar__list"
                style={{ maxHeight: 140, overflow: 'auto', fontSize: '0.8rem', gap: 4 }}
              >
                {worldFactions.map((f) => (
                  <div key={f.id} className="fantasy-map-sidebar__item" style={{ padding: '0.35rem 0.5rem', cursor: 'default' }}>
                    <span style={{ color: 'rgba(246,235,209,0.9)' }}>{f.name}</span>
                    <span style={{ color: 'rgba(214, 177, 109, 0.55)', fontSize: '0.7rem' }}>sim</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="fantasy-map-sidebar__card">
            <h3 className="fantasy-map-sidebar__label">Species selector</h3>
            <div style={{ display: 'grid', gap: 8 }}>
              <label style={{ display: 'grid', gap: 4, color: 'rgba(246,235,209,0.9)', fontSize: '0.86rem' }}>
                Config
                <select
                  value={configMode}
                  onChange={(e) => setConfigMode(e.target.value as ConfigMode)}
                  style={{ border: '1px solid rgba(250,233,197,0.2)', borderRadius: 6, padding: '8px 10px', background: 'rgba(20,17,26,0.9)', color: '#f6ebd1' }}
                >
                  <option value="core">Core factions</option>
                  <option value="optional">Optional factions</option>
                  <option value="custom">Custom combinations</option>
                </select>
              </label>
              <button type="button" onClick={() => void loadLoreData()} className="fantasy-map-sidebar__item" style={{ padding: '0.6rem' }}>
                Reload Lore
              </button>
              <label style={{ display: 'grid', gap: 4, color: 'rgba(246,235,209,0.9)', fontSize: '0.86rem' }}>
                Paint location
                <select
                  value={selectedLocationId}
                  onChange={(e) => setSelectedLocationId(e.target.value)}
                  style={{ border: '1px solid rgba(250,233,197,0.2)', borderRadius: 6, padding: '8px 10px', background: 'rgba(20,17,26,0.9)', color: '#f6ebd1' }}
                >
                  {locationOptions.length === 0 && <option value="">No locations loaded</option>}
                  {locationOptions.map((location) => (
                    <option key={location.id} value={location.id}>
                      {location.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          <div className="fantasy-map-sidebar__card">
            <h3 className="fantasy-map-sidebar__label">Location species (lore)</h3>
            <div style={{ display: 'grid', gap: 8 }}>
              <label style={{ display: 'grid', gap: 4, color: 'rgba(246,235,209,0.9)', fontSize: '0.86rem' }}>
                Paint faction
                <select
                  value={selectedFactionId}
                  onChange={(e) => setSelectedFactionId(e.target.value)}
                  disabled={!isEditMode}
                  style={{ border: '1px solid rgba(250,233,197,0.2)', borderRadius: 6, padding: '6px 8px', background: 'rgba(20,17,26,0.9)', color: '#f6ebd1' }}
                >
                  {locationFactionOptions.length === 0 && allPaintFactionOptions.length === 0 && <option value="">Load lore or world</option>}
                  {locationFactionOptions.length > 0
                    ? locationFactionOptions.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.name}
                        </option>
                      ))
                    : allPaintFactionOptions.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.name}
                        </option>
                      ))}
                </select>
              </label>
              <label style={{ display: 'grid', gap: 4, color: 'rgba(246,235,209,0.9)', fontSize: '0.86rem' }}>
                All (lore + sim)
                <select
                  value={selectedFactionId}
                  onChange={(e) => setSelectedFactionId(e.target.value)}
                  style={{ border: '1px solid rgba(250,233,197,0.2)', borderRadius: 6, padding: '6px 8px', background: 'rgba(20,17,26,0.9)', color: '#f6ebd1' }}
                >
                  {allPaintFactionOptions.length === 0 && <option value="">No factions — run Load from world + lore</option>}
                  {allPaintFactionOptions.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name}
                    </option>
                  ))}
                </select>
              </label>
              <div style={{ display: 'grid', gap: 6, maxHeight: 120, overflow: 'auto' }}>
                {locationFactionOptions.map((f) => (
                  <div key={f.id} style={{ fontSize: '0.86rem' }}>
                    <code>{f.id}</code> — {f.name}
                  </div>
                ))}
                {locationFactionOptions.length === 0 && <div style={{ fontSize: '0.86rem', opacity: 0.7 }}>Hover a hex to resolve species for this area.</div>}
              </div>
            </div>
          </div>

          <div className="fantasy-map-sidebar__card">
            <h3 className="fantasy-map-sidebar__label">Save / load</h3>
            <p className="fantasy-map-sidebar__empty" style={{ fontSize: '0.8rem', marginBottom: 8 }}>
              Manual paint: hold left mouse and drag. Brush controls how many neighboring hexes paint at once.
            </p>
            <label style={{ display: 'grid', gap: 4, color: 'rgba(246,235,209,0.9)', fontSize: '0.8rem', marginBottom: 8 }}>
              Brush
              <select
                value={brushRadius}
                onChange={(e) => setBrushRadius(Number(e.target.value) as 0 | 1 | 2)}
                style={{ border: '1px solid rgba(250,233,197,0.2)', borderRadius: 6, padding: '8px 10px', background: 'rgba(20,17,26,0.9)', color: '#f6ebd1' }}
              >
                <option value={0}>Fine (1 hex)</option>
                <option value={1}>Small (around 7 hexes)</option>
                <option value={2}>Medium (around 19 hexes)</option>
              </select>
            </label>
            <div className="fantasy-map-sidebar__list">
              <button
                type="button"
                onClick={() => {
                  setIsLocationPaintMode(false);
                  setIsEditMode(true);
                }}
                className="fantasy-map-sidebar__item"
                style={{ borderColor: isEditMode ? 'rgba(99, 107, 255, 0.5)' : undefined }}
              >
                <span>Faction paint</span>
                <span>{isEditMode ? 'on' : 'off'}</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  setIsLocationPaintMode(true);
                  setIsEditMode(false);
                }}
                className="fantasy-map-sidebar__item"
                style={{ borderColor: isLocationPaintMode ? 'rgba(180, 80, 255, 0.5)' : undefined }}
              >
                <span>Location paint</span>
                <span>{isLocationPaintMode ? 'on' : 'off'}</span>
              </button>
              <button type="button" onClick={() => setIsEraseMode((v) => !v)} className="fantasy-map-sidebar__item">
                <span>Erase</span>
                <span>{isEraseMode ? 'on' : 'off'}</span>
              </button>
              <button type="button" onClick={() => void loadWorld()} className="fantasy-map-sidebar__item">
                <span>Load from world</span>
                <span>↻</span>
              </button>
              <button type="button" onClick={clearLayout} className="fantasy-map-sidebar__item">
                <span>Clear layout</span>
                <span />
              </button>
              <button type="button" onClick={clearAllPaint} className="fantasy-map-sidebar__item">
                <span>Clear all</span>
                <span />
              </button>
              <button type="button" onClick={resetLayoutToBackend} className="fantasy-map-sidebar__item">
                <span>Reset to world</span>
                <span />
              </button>
              <button type="button" onClick={() => void saveCurrentLayout()} className="fantasy-map-sidebar__item">
                <span>Save layout</span>
                <span>✓</span>
              </button>
              <label style={{ display: 'grid', gap: 4, color: 'rgba(246,235,209,0.9)', fontSize: '0.8rem' }}>
                Saved maps
                <select
                  value={selectedMapFile}
                  onChange={(e) => setSelectedMapFile(e.target.value)}
                  style={{ border: '1px solid rgba(250,233,197,0.2)', borderRadius: 6, padding: '8px 10px', background: 'rgba(20,17,26,0.9)', color: '#f6ebd1' }}
                >
                  {savedMapFiles.length === 0 && <option value="">No saved maps</option>}
                  {savedMapFiles.map((file) => (
                    <option key={file} value={file}>
                      {file}
                    </option>
                  ))}
                </select>
              </label>
              <button type="button" onClick={() => void loadSelectedLayout()} className="fantasy-map-sidebar__item">
                <span>Load layout</span>
                <span>↑</span>
              </button>
            </div>
          </div>

          <div className="fantasy-map-sidebar__card" style={{ borderStyle: 'dashed', borderColor: 'rgba(250,233,197,0.2)' }}>
            <h3 className="fantasy-map-sidebar__label">Debug (lore)</h3>
            <p className="fantasy-map-sidebar__empty" style={{ fontSize: '0.8rem' }}>
              locationId: <code>{activeLocationId || 'none'}</code> · locations loaded: {loreLocations.length}
            </p>
            <div style={{ display: 'grid', gap: 4, maxHeight: 100, overflow: 'auto' }}>
              {locationFactionOptions.length === 0 && <div style={{ opacity: 0.7 }}>No species for current region.</div>}
              {locationFactionOptions.map((item) => (
                <div key={item.id} style={{ fontSize: '0.8rem' }}>
                  <code>{item.id}</code> — {item.name}
                </div>
              ))}
            </div>
          </div>
        </div>
      </aside>

      <section className="fantasy-map-stage fantasy-map-stage--atlas" style={{ minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <div className="fantasy-map-frame fantasy-map-frame--atlas" style={{ flex: 1, minHeight: 0, height: '100%' }}>
          <div
            ref={mapViewportRef}
            className={isMiddleDrag ? 'fantasy-map-viewport is-panning' : 'fantasy-map-viewport'}
            onPointerDown={onMapPointerDown}
            onPointerMove={onMapPointerMove}
            onPointerUp={onMapPointerUp}
            onPointerCancel={onMapPointerCancel}
            onAuxClick={(e) => e.button === 1 && e.preventDefault()}
            tabIndex={0}
            role="application"
            aria-label="Realm map, scroll to zoom, middle-drag to pan"
            style={{ outline: 'none' }}
          >
            <div
              className="fantasy-map-world"
              style={{ transform: `translate(${mapView.x}px, ${mapView.y}px) scale(${mapView.k})` }}
            >
              <div className="fantasy-map-canvas" ref={mapContentRef}>
                <div className="fantasy-map-atlas-mood" aria-hidden>
                  <div className="fantasy-map-atlas-mood__vignette" />
                </div>
                <img
                  src={MAP_ATLAS_SRC}
                  alt="Aeloria territory map, top down"
                  className="fantasy-map-terrain"
                  draggable={false}
                  onDragStart={(e) => e.preventDefault()}
                  onLoad={reapplyMapBounds}
                />
                <svg
                  ref={polSvgRef}
                  viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
                  preserveAspectRatio="none"
                  className="fantasy-map-political"
                  onPointerMove={(e) => {
                    if (showStrategicHex) return;
                    updatePoliticalHover(e.clientX, e.clientY, e.currentTarget);
                  }}
                  onPointerLeave={() => {
                    if (!showStrategicHex) setHoveredRegion(null);
                  }}
                  onClick={(e) => {
                    if (showStrategicHex) return;
                    const el = e.currentTarget;
                    const rect = el.getBoundingClientRect();
                    const x = ((e.clientX - rect.left) / Math.max(1, rect.width)) * VIEWBOX_WIDTH;
                    const y = ((e.clientY - rect.top) / Math.max(1, rect.height)) * VIEWBOX_HEIGHT;
                    setSelectedRegion(
                      findRegionAtViewPoint(x, y, regions, dataBounds, VIEWBOX_WIDTH, VIEWBOX_HEIGHT),
                    );
                  }}
                  style={{ pointerEvents: showStrategicHex ? 'none' : 'auto' }}
                >
                  {regions.map((r) => {
                    const d = regionPathD(r, dataBounds, VIEWBOX_WIDTH, VIEWBOX_HEIGHT);
                    const isH = hoveredRegion?.id === r.id;
                    const isS = selectedRegion?.id === r.id;
                    const simFill = politicalFill(r);
                    const fill = showPoliticalTints ? simFill : 'transparent';
                    const fillOpacity = showPoliticalTints
                      ? isS
                        ? 0.55
                        : isH
                          ? 0.5
                          : 0.34
                      : 0;
                    const stroke = showPoliticalTints
                      ? isS
                        ? 'rgba(255,250,220,0.85)'
                        : isH
                          ? 'rgba(200,220,255,0.75)'
                          : 'rgba(0,0,0,0.35)'
                      : isS
                        ? 'rgba(255,250,220,0.9)'
                        : isH
                          ? 'rgba(200,220,255,0.55)'
                          : 'transparent';
                    return (
                      <path
                        key={r.id}
                        d={d}
                        fill={fill}
                        fillOpacity={fillOpacity}
                        stroke={stroke}
                        strokeWidth={showPoliticalTints && !isH && !isS ? 0.28 : isH || isS || showPoliticalTints ? 0.4 : 0}
                        vectorEffect="non-scaling-stroke"
                        style={{ transition: 'fill-opacity 0.12s, stroke 0.12s' }}
                      />
                    );
                  })}
                </svg>
                <svg
                  viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
                  preserveAspectRatio="none"
                  className="fantasy-map-hexes"
                  onMouseDown={() => setIsMouseDown(true)}
                  onMouseUp={() => setIsMouseDown(false)}
                  onMouseLeave={() => setIsMouseDown(false)}
                  style={{ pointerEvents: showStrategicHex ? 'auto' : 'none' }}
                >
                  {hexTiles.map((hex) => {
                    const isSea = landByHex != null && landByHex[hex.id] === false;
                    const isHovered = hoveredHexId === hex.id;
                    const factionId = factionByHex?.[hex.id] ?? null;
                    const hasManualLocation = Object.prototype.hasOwnProperty.call(locationByHex, hex.id);
                    const manualLocation = hasManualLocation ? locationByHex[hex.id] : null;
                    const geometryLocationId = locationForHex(hex.x, hex.y)?.id || null;
                    const resolvedLocationId =
                      manualLocation === ''
                        ? null
                        : manualLocation || (isLocationPaintMode ? geometryLocationId : null);
                    const factionFill = factionId ? colorForFaction(factionId) : null;
                    const locationFill = resolvedLocationId
                      ? locationColors[resolvedLocationId] || colorForFaction(`location-${resolvedLocationId}`)
                      : null;
                    const hasPaint = Boolean(factionFill || (resolvedLocationId && hasManualLocation));
                    const fill = isSea
                      ? 'transparent'
                      : factionFill
                        ? factionFill
                        : locationFill
                          ? locationFill
                          : 'transparent';
                    const baseOp = isSea
                      ? 0
                      : factionFill
                        ? 1
                        : locationFill
                          ? 0.5
                          : 0;
                    const fillOpacity = hasPaint || (locationFill && !isSea) ? baseOp : 0;
                    const isEmpty = fillOpacity === 0;
                    const stroke = (() => {
                      if (isHovered) {
                        return isSea ? 'rgba(160, 210, 255, 0.7)' : 'rgba(188, 240, 255, 0.9)';
                      }
                      if (isEmpty) {
                        // Land + water: same grid weight so ocean isn’t a dead zone
                        return isSea
                          ? 'rgba(200, 220, 255, 0.34)'
                          : 'rgba(210, 218, 240, 0.36)';
                      }
                      if (isSea) return 'rgba(150, 195, 240, 0.45)';
                      return 'rgba(200, 215, 255, 0.38)';
                    })();
                    return (
                      <polygon
                        key={hex.id}
                        points={pointsByHexId.get(hex.id) ?? ''}
                        fill={fill}
                        fillOpacity={isHovered ? Math.min(fillOpacity + 0.12, 1) : fillOpacity}
                        stroke={stroke}
                        strokeWidth={0.07}
                        vectorEffect="non-scaling-stroke"
                        style={{ cursor: 'pointer', pointerEvents: 'auto' }}
                        onMouseEnter={() => {
                          setHoveredHexId(hex.id);
                          if (isMouseDown) handleHexPaintClick(hex);
                        }}
                        onMouseLeave={() => setHoveredHexId(null)}
                        onClick={() => {
                          setSelectedHexId(hex.id);
                          handleHexPaintClick(hex);
                        }}
                      />
                    );
                  })}
                </svg>
              </div>
            </div>

            <p className="fantasy-map-atlas-crown" aria-hidden>
              <span className="fantasy-map-atlas-crown__title">Aeloria</span>
              <span className="fantasy-map-atlas-crown__sub">Living atlas</span>
            </p>
            <div className="fantasy-map-compass" aria-hidden title="North">
              <span className="fantasy-map-compass__n">N</span>
            </div>

            {hoveredHexId && (
              <div
                className="fantasy-map-hex-hud"
                style={{
                  left: 12,
                  bottom: 12,
                }}
              >
                <span className="fantasy-map-hex-hud__id">{hoveredHexId}</span>
                {hoveredHex && (
                  <span>
                    {hoveredHex.x.toFixed(1)}, {hoveredHex.y.toFixed(1)} ·{' '}
                    {Object.prototype.hasOwnProperty.call(locationByHex, hoveredHex.id)
                      ? locationByHex[hoveredHex.id] === ''
                        ? 'Unclaimed'
                        : locationByHex[hoveredHex.id]
                      : locationForHex(hoveredHex.x, hoveredHex.y)?.id || 'Unclaimed'}{' '}
                    · {(() => {
                      const fid = factionByHex?.[hoveredHex.id] ?? null;
                      return (fid ? factionNameById.get(fid) : null) || fid || 'Unclaimed';
                    })()}
                  </span>
                )}
              </div>
            )}

            <div className="fantasy-map-zoom-bar" aria-label="Map zoom and reset">
              <button type="button" onClick={() => nudgeZoom(1)} title="Zoom in">
                +
              </button>
              <button type="button" onClick={() => nudgeZoom(-1)} title="Zoom out">
                −
              </button>
              <button type="button" onClick={resetMapView} title="Reset view">
                ⌂
              </button>
            </div>
            <p className="fantasy-map-nav-hint">Scroll · mid-drag pan · wasd</p>
          </div>
        </div>
      </section>
    </div>
  );
}
