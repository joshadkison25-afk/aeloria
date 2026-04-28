import fs from 'fs';
import path from 'path';
import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

const FLASK_URL = process.env.PYTHON_BACKEND_URL ?? 'http://localhost:5000';

// ── Faction name (game engine) → faction ID (WorldMapEditor) ────────────────
const FACTION_NAME_TO_ID: Record<string, string> = {
  'Twin Cities':        'twin_cities',
  'High Kingdom':       'twin_cities',
  'Shadow Court':       'faerwood',
  'Faerwood':           'faerwood',
  'Glenwood':           'glenwood',
  'Glenhaven':          'glenwood',
  'Groth Clans':        'groth_clans',
  'Gilgeth Clans':      'gilgeth_clans',
  'Tidefall':           'tidefall',
  'Varkuun':            'varkuun',
  'Farrock':            'varkuun',
  'Vilefin':            'vilefin',
  'Frostvale':          'frostvale',
  'Wintermark':         'frostvale',
  'Lostfeld':           'lostfeld',
  'Dur Khadur':         'dur_khadur',
  'Dreadwind':          'dreadwind',
  'Dreadwind Isles':    'dreadwind',
  'Stonebreak':         'stonebreak',
  'Gloomspire':         'stonebreak',
};

function nameToId(name: string): string | undefined {
  if (FACTION_NAME_TO_ID[name]) return FACTION_NAME_TO_ID[name];
  // Fallback: lowercase + underscores
  const slug = name.toLowerCase().replace(/[\s/]+/g, '_').replace(/[^a-z0-9_]/g, '');
  return slug || undefined;
}

// ── Seer journey → map pin coordinates (matches public/data/locations.json labels) ──
type LocPinLite = { label: string; x: number; y: number; regionId?: string };

const SEER_PLACE_SYNONYMS: Record<string, string> = {
  'twin cities': 'Eldoria',
  'high kingdom': 'Eldoria',
  'shadow court': 'Mythralen',
  faerwood: 'Mythralen',
  glenhaven: 'Lethyra Vale',
  glenwood: 'Lethyra Vale',
  varkuun: 'Farrock',
  farrock: 'Farrock',
  'dreadwind isles': 'Widows Bay',
  dreadwind: 'Widows Bay',
  wintermark: 'Frostvale',
  'gilgeth clans': 'Gilgeth',
  'groth clans': 'Groth',
  lostfeld: 'Lostfeld',
  stonebreak: 'Stonebreak',
  tidefall: 'Tidefall',
  vilefin: 'Vilefin',
  frostvale: 'Frostvale',
  eldoria: 'Eldoria',
  eresteron: 'Eresteron',
  groth: 'Groth',
  gilgeth: 'Gilgeth',
};

function normalizeSeerLocation(raw: string): string {
  return raw.trim().toLowerCase().replace(/\s+/g, ' ');
}

function resolveSeerOnMap(rawLocation: string, pins: LocPinLite[]): { x: number; y: number; matchedLabel: string } | null {
  if (!rawLocation?.trim()) return null;
  const n = normalizeSeerLocation(rawLocation);
  if (!n || n === 'unknown road' || n === 'unknown' || n === 'none') return null;

  const syn = SEER_PLACE_SYNONYMS[n];
  if (syn) {
    const hit = pins.find((p) => p.label.toLowerCase() === syn.toLowerCase());
    if (hit) return { x: hit.x, y: hit.y, matchedLabel: hit.label };
  }

  let best: { pin: LocPinLite; score: number } | null = null;
  for (const p of pins) {
    const pl = p.label.toLowerCase();
    const rid = p.regionId?.toLowerCase() ?? '';
    let score = 0;
    if (pl === n) score = 100;
    else if (n.includes(pl) || pl.includes(n)) score = 88;
    else if (rid && (n.includes(rid) || rid.includes(n))) score = 82;
    else {
      const nw = n.split(' ').filter((w) => w.length > 2);
      if (nw.some((w) => pl.includes(w) || w.includes(pl))) score = 68;
    }
    if (score > (best?.score ?? 0)) best = { pin: p, score };
  }
  if (best && best.score >= 68) {
    return { x: best.pin.x, y: best.pin.y, matchedLabel: best.pin.label };
  }
  return null;
}

// ── Load world state (file → Flask fallback) ────────────────────────────────
async function loadWorldState(): Promise<Record<string, unknown>> {
  // Try reading directly from disk first (same process, always fresh)
  try {
    const wsPath = path.join(process.cwd(), 'world_state.json');
    return JSON.parse(fs.readFileSync(wsPath, 'utf-8')) as Record<string, unknown>;
  } catch { /* fall through */ }

  // Fallback: ask Flask
  try {
    const res = await fetch(`${FLASK_URL}/api/state`, { next: { revalidate: 0 } });
    if (res.ok) return (await res.json()) as Record<string, unknown>;
  } catch { /* fall through */ }

  return {};
}

// ── Route ────────────────────────────────────────────────────────────────────
export async function GET() {
  // 1. Read static pin data
  let pins: Record<string, unknown>[] = [];
  try {
    const locPath = path.join(process.cwd(), 'public', 'data', 'locations.json');
    pins = JSON.parse(fs.readFileSync(locPath, 'utf-8')) as Record<string, unknown>[];
  } catch { /* no pins yet */ }

  // 2. Load world state
  const ws = await loadWorldState();

  const regions        = (ws.regions        ?? {}) as Record<string, Record<string, unknown>>;
  const activeEvents   = (ws.active_events   ?? []) as Record<string, unknown>[];
  const supportingEvts = (ws.supporting_events ?? []) as Record<string, unknown>[];
  const portraitCache  = (ws.portrait_cache  ?? {}) as Record<string, string>;
  const leadershipSt   = (ws.leadership_state ?? []) as Record<string, unknown>[];
  const factionPower   = (ws.faction_power_state ?? []) as Record<string, unknown>[];
  const tick           = (ws.tick ?? 0) as number;
  const worldDate      = (ws.world_date ?? '') as string;
  const primaryEvent   = ws.primary_event as Record<string, unknown> | undefined;

  // 3. faction → portrait_image from leadership_state
  const factionPortrait: Record<string, string> = {};
  for (const entry of leadershipSt) {
    const faction = entry.faction as string | undefined;
    const ruler   = entry.currentRuler as Record<string, unknown> | undefined;
    const img     = ruler?.portrait_image as string | undefined;
    if (faction && img) {
      const fid = nameToId(faction);
      if (fid) factionPortrait[fid] = img;
    }
  }

  // Also fill from portrait_cache keyed by character name — map via leadership
  for (const entry of leadershipSt) {
    const faction = entry.faction as string | undefined;
    const ruler   = entry.currentRuler as Record<string, unknown> | undefined;
    const name    = ruler?.name as string | undefined;
    if (faction && name && portraitCache[name]) {
      const fid = nameToId(faction);
      if (fid && !factionPortrait[fid]) factionPortrait[fid] = portraitCache[name];
    }
  }

  // 4. Build event index: location label → event metadata
  const allEvents = [...activeEvents, ...supportingEvts];
  if (primaryEvent) allEvents.push(primaryEvent);

  const eventByLabel: Record<string, Record<string, unknown>> = {};
  for (const evt of allEvents) {
    const involved = (evt.involved ?? []) as string[];
    for (const loc of involved) {
      if (!eventByLabel[loc]) {
        eventByLabel[loc] = {
          name:     evt.name,
          severity: evt.severity,
          trend:    evt.trend,
          stage:    evt.stage,
          summary:  evt.summary,
        };
      }
    }
  }

  // 5. Enrich pins
  const enriched = pins.map((pin) => {
    const out = { ...pin } as Record<string, unknown>;
    const label = pin.label as string | undefined;

    // Live faction from region controller
    const regionId = pin.regionId as string | undefined;
    if (regionId && regions[regionId]) {
      const controller = regions[regionId].controller as string | null;
      if (controller) {
        const fid = nameToId(controller);
        if (fid) out.liveFaction = fid;
      }
    }

    // Conflict event — match by pin label against event involved list
    if (label && eventByLabel[label]) {
      out.conflictEvent = eventByLabel[label];
    }

    // Leader portrait — only for faction capitals
    if (pin.type === 'faction_capital' && pin.faction) {
      const portrait = factionPortrait[pin.faction as string];
      if (portrait) out.leaderPortrait = portrait;
    }

    return out;
  });

  const seerJourney = (ws.seer_journey ?? {}) as Record<string, unknown>;
  const locRaw = String(
    seerJourney.current_location ?? seerJourney.location ?? ws.seer_location ?? '',
  ).trim();
  const destRaw = String(seerJourney.destination ?? '').trim();
  const seerStatus = String(seerJourney.status ?? 'stationary').trim();

  const locPinsLite: LocPinLite[] = pins.map((p) => ({
    label: String(p.label ?? ''),
    x: Number(p.x),
    y: Number(p.y),
    regionId: p.regionId != null ? String(p.regionId) : undefined,
  }));

  const resolved = locRaw ? resolveSeerOnMap(locRaw, locPinsLite) : null;
  const seerMap = resolved
    ? {
        x: resolved.x,
        y: resolved.y,
        matchedLabel: resolved.matchedLabel,
        location: locRaw,
        destination: destRaw,
        status: seerStatus,
      }
    : null;

  return NextResponse.json({
    pins: enriched,
    factionPower,
    tick,
    worldDate,
    activeEvents,
    primaryEvent: primaryEvent ?? null,
    seerMap,
  });
}
