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

  return NextResponse.json({
    pins: enriched,
    factionPower,
    tick,
    worldDate,
    activeEvents,
    primaryEvent: primaryEvent ?? null,
  });
}
