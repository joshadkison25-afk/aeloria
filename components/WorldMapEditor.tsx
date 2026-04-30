'use client';

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

// ============================================================================
// Types
// ============================================================================

export type PinType =
  | 'city'
  | 'settlement'
  | 'landmark'
  | 'faction_capital'
  | 'house_seat'
  | 'dungeon'
  | 'port';

export interface LocationPin {
  id: string;
  label: string;
  type: PinType;
  faction?: string;
  house?: string;   // house/clan id within the faction
  /** Region key in world_state.json for live ownership tracking (e.g. "Groth") */
  regionId?: string;
  x: number; // 0–100 % of image width
  y: number; // 0–100 % of image height
  notes?: string;
  createdAt: string;
}

// Live data from /api/map-state
interface LivePin extends LocationPin {
  liveFaction?:    string;
  conflictEvent?:  { name: string; severity: number; trend: string; summary?: string };
  leaderPortrait?: string;
}

interface FactionPowerEntry {
  faction: string;
  militaryPower: number;
  economicPower: number;
  politicalInfluence: number;
}

interface HistorySnapshot {
  tick: number;
  worldDate: string;
  filename: string;
  regionControl: Record<string, string | null>;
  activeEvents: { name: string; involved: string[]; severity: number; trend: string }[];
  primaryEvent: { name: string; severity: number; summary: string } | null;
}

interface DispatchToast {
  id: string;
  header: string;
  body: string;
  severity: number;
  color: string;
  expires: number; // ms timestamp
}

/** Live Seer position from `/api/map-state` (world `seer_journey` resolved to a map pin). */
interface SeerOnMap {
  x: number;
  y: number;
  matchedLabel: string;
  location: string;
  destination: string;
  status: string;
}

interface ClockState {
  paused: boolean;
  speed: number;
  current_tick: number;
  world_date: string;
  next_tick_eta: string;
  seconds_until_next_tick?: number | null;
  is_processing: boolean;
  last_error?: string;
}

type CouncilAdvisor = 'chancellor' | 'marshal' | 'steward' | 'spymaster' | 'chronicler';

interface CouncilItem {
  kind: string;
  title: string;
  summary: string;
  severity: number;
  faction?: string;
  source?: string;
}

interface CouncilWatchItem {
  faction: string;
  overall: number;
  dominant_pressure: string;
  summary?: string;
}

interface CouncilReport {
  tick: number;
  world_date: string;
  top_risks: CouncilItem[];
  watchlist: CouncilWatchItem[];
  advisor_briefings?: Record<CouncilAdvisor, {
    advisor: string;
    status: string;
    summary: string;
    focus: string;
    severity: number;
  }>;
  strategic_questions?: CouncilItem[];
  advisor_reports: Record<CouncilAdvisor, CouncilItem[]>;
}

interface ExplainabilityItem {
  id: string;
  tick: number;
  world_date: string;
  domain: string;
  actor: string;
  severity: number;
  confidence: number;
  public_status: string;
  affected: string[];
  source: string;
  pipeline: {
    pressure: string;
    belief: string;
    decision: string;
    outcome: string;
    hidden_outcome: string;
  };
  knowledge_spread: {
    known_by: string[];
    rumored_by: string[];
    suspected_by: string[];
    misread_by: string[];
  };
}

interface ExplainabilityReport {
  tick: number;
  world_date: string;
  domain_counts: Record<string, number>;
  explanations: ExplainabilityItem[];
}

interface FactionIntelRow {
  faction: string;
  overall_pressure: number;
  dominant_pressure: string;
  pressure_summary: string;
  pressure_domains: { domain: string; score: number; reasons: string[] }[];
  dominant_belief_summary: string;
  beliefs: { id?: string; claim: string; confidence: number; source: string; bias: string }[];
  knowledge_counts: Record<string, number>;
  knowledge: {
    known_facts: string[];
    rumors: string[];
    suspicions: string[];
    false_beliefs: string[];
    blind_spots: string[];
  };
}

interface FactionIntelReport {
  tick: number;
  world_date: string;
  selected_faction: string;
  factions: FactionIntelRow[];
}

interface AutopsyCauseRecord {
  id: string;
  tick: number;
  world_date?: string;
  domain: string;
  actor: string;
  pressure: string;
  belief: string;
  decision: string;
  outcome: string;
  affected: string[];
  hidden_outcome?: string;
  severity: number;
  confidence?: number;
  source?: string;
}

interface AutopsyPressure {
  faction: string;
  overall: number;
  dominant_pressure: string;
  summary?: string;
  domains?: Record<string, { score: number; reasons: string[] }>;
}

interface AutopsyBelief {
  faction: string;
  dominant_pressure: string;
  overall_pressure: number;
  beliefs: { id?: string; subject?: string; claim: string; confidence: number; source: string; bias: string }[];
}

interface AutopsyKnowledgeUpdate {
  cause_id: string;
  domain: string;
  actor: string;
  spread: {
    known_by: string[];
    rumored_by: string[];
    suspected_by: string[];
    misread_by: string[];
  };
}

interface AutopsySurfacedEvent {
  surface: string;
  name?: string;
  summary?: string;
  text?: string;
  action?: string;
  cause_id?: string;
  domain?: string;
  severity?: number;
  involved?: string[];
}

interface LastTickAutopsy {
  tick: number;
  world_date: string;
  pressures: AutopsyPressure[];
  beliefs: AutopsyBelief[];
  decisions: { source: string; faction: string; action: string; summary: string; meta?: Record<string, unknown> }[];
  outcomes: { cause_id: string; domain: string; actor: string; decision: string; outcome: string; severity: number; source: string }[];
  causality_records: AutopsyCauseRecord[];
  knowledge_updates: AutopsyKnowledgeUpdate[];
  surfaced_events: AutopsySurfacedEvent[];
}

interface LastTickAutopsyResponse {
  last_tick_autopsy: LastTickAutopsy | Record<string, never>;
  recent_causality_records: AutopsyCauseRecord[];
}

// ============================================================================
// Constants & lookup data
// ============================================================================

/** Basemap for pin layout (`public/data/locations.json`). Override with `NEXT_PUBLIC_WORLD_MAP_IMAGE`. */
const WORLD_MAP_IMAGE_SRC =
  process.env.NEXT_PUBLIC_WORLD_MAP_IMAGE || '/aeloria-worldmap.png';

export const FACTIONS: { id: string; label: string; color: string }[] = [
  { id: 'twin_cities',    label: 'Twin Cities (High Kingdom)',  color: '#d4a017' },
  { id: 'faerwood',       label: 'Faerwood / Shadow Court',     color: '#7c3aed' },
  { id: 'glenwood',       label: 'Glenwood / Glenhaven',        color: '#16a34a' },
  { id: 'groth_clans',    label: 'Groth Clans',                 color: '#ea580c' },
  { id: 'gilgeth_clans',  label: 'Gilgeth Clans',               color: '#6b7280' },
  { id: 'tidefall',       label: 'Tidefall',                    color: '#0d9488' },
  { id: 'varkuun',        label: 'Farrock / Varkuun',           color: '#2563eb' },
  { id: 'vilefin',        label: 'Vilefin',                     color: '#65a30d' },
  { id: 'frostvale',      label: 'Frostvale / Wintermark',      color: '#7dd3fc' },
  { id: 'lostfeld',       label: 'Lostfeld (Dwarven Holds)',    color: '#b45309' },
  { id: 'dur_khadur',     label: 'Dur Khadur',                  color: '#ca8a04' },
  { id: 'dreadwind',      label: 'Dreadwind Isles',             color: '#dc2626' },
  { id: 'stonebreak',     label: 'Stonebreak / Gloomspire',     color: '#4d7c0f' },
];

const FACTION_MAP: Record<string, (typeof FACTIONS)[0]> = Object.fromEntries(
  FACTIONS.map((f) => [f.id, f]),
);

function factionColor(id?: string): string {
  if (!id) return '#9ca3af';
  return FACTION_MAP[id]?.color ?? '#9ca3af';
}

export const PIN_TYPES: { id: PinType; label: string }[] = [
  { id: 'city',             label: 'City' },
  { id: 'settlement',       label: 'Settlement' },
  { id: 'landmark',         label: 'Landmark' },
  { id: 'faction_capital',  label: 'Faction Capital' },
  { id: 'house_seat',       label: 'House / Clan Seat' },
  { id: 'dungeon',          label: 'Dungeon / POI' },
  { id: 'port',             label: 'Port' },
];

// ── Houses & Clans per faction (from Aeloria lore) ──────────────────────────

export interface HouseEntry { id: string; label: string; }

export const FACTION_HOUSES: Record<string, HouseEntry[]> = {
  twin_cities: [
    { id: 'aurand',      label: 'House Aurand' },
    { id: 'braafhart',   label: 'House Braafhart' },
    { id: 'lefleur',     label: 'House LeFleur' },
  ],
  faerwood: [
    { id: 'verlorn',     label: 'House Verlorn' },
    { id: 'nightborn',   label: 'House Nightborn' },
    { id: 'shadowveil',  label: 'House Shadowveil' },
  ],
  glenwood: [
    { id: 'wood',        label: 'House Wood' },
    { id: 'darkleaf',    label: 'House Darkleaf' },
    { id: 'mistafae',    label: 'House Mistafae' },
  ],
  groth_clans: [
    { id: 'mijid',       label: 'Clan Mijid' },
    { id: 'ashfang',     label: 'Clan Ashfang' },
    { id: 'syncar',      label: 'Clan Syncar' },
  ],
  gilgeth_clans: [
    { id: 'blackblood',  label: 'House Blackblood' },
    { id: 'ironhide',    label: 'House Ironhide' },
    { id: 'redtusk',     label: 'House Redtusk' },
  ],
  tidefall: [
    { id: 'ver_meer',         label: 'House Ver Meer' },
    { id: 'highland_dusken',  label: 'House Highland-Dusken' },
    { id: 'fish',             label: 'House Fish' },
    { id: 'mcgowan',          label: 'House McGowan' },
  ],
  varkuun: [
    { id: 'van_cleave',  label: 'House Van Cleave' },
  ],
  vilefin: [
    { id: 'bloodware',   label: 'Clan Bloodware' },
    { id: 'cogtooth',    label: 'Clan Cogtooth' },
    { id: 'rustfang',    label: 'Clan Rustfang' },
  ],
  frostvale: [
    { id: 'adkison',    label: 'House Adkison' },
    { id: 'mcintosh',   label: 'House McIntosh' },
    { id: 'holter',     label: 'House Holter' },
    { id: 'duval',      label: 'House Duval' },
  ],
  lostfeld: [
    { id: 'goldfinger_duke', label: 'House Goldfinger-Duke' },
    { id: 'runewarden',      label: 'Clan Runewarden' },
    { id: 'ironmaul',        label: 'Clan Ironmaul' },
  ],
  dur_khadur: [
    { id: 'gross',      label: 'House Gross' },
    { id: 'delonious',  label: 'House Delonious' },
    { id: 'galfazzar',  label: 'House Galfazzar' },
    { id: 'vercenti',   label: 'House Vercenti' },
  ],
  dreadwind: [
    { id: 'blacktide',  label: 'House Blacktide' },
    { id: 'saltborn',   label: 'House Saltborn (Ousted)' },
  ],
  stonebreak: [
    { id: 'stonebreak_order', label: 'Stonebreak Order' },
    { id: 'gloomspire',       label: 'Gloomspire Syndicate' },
  ],
};

/** Flat map: houseId → HouseEntry for quick label lookup */
const HOUSE_MAP: Record<string, HouseEntry> = Object.fromEntries(
  Object.values(FACTION_HOUSES).flat().map((h) => [h.id, h]),
);

const GRID_SIZES = [
  { label: '10 × 10', cols: 10, rows: 10 },
  { label: '20 × 20', cols: 20, rows: 20 },
  { label: '40 × 40', cols: 40, rows: 40 },
];

/** Max zoom-in; min zoom is always "fit map in view" (depends on viewport). */
const ZOOM_MAX = 8;
const LABEL_ZOOM_THRESHOLD = 1.05; // show pin labels when zoom > this

/** Minimum zoom level before each pin type becomes visible. */
const PIN_ZOOM_THRESHOLD: Record<PinType, number> = {
  faction_capital: 0,    // always visible
  city:            0.65, // appear after a little zoom
  landmark:        0.65,
  port:            0.65,
  dungeon:         0.72,
  house_seat:      0.82, // require more zoom — they're subordinate detail
  settlement:      0.90,
};

// ============================================================================
// Helpers
// ============================================================================

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v));
}

/** Severity number → Roman numeral (capped at V) */
function severityRoman(n: number): string {
  if (n >= 18) return 'V';
  if (n >= 11) return 'IV';
  if (n >= 6)  return 'III';
  if (n >= 3)  return 'II';
  return 'I';
}

/** Excel-style column label: 1→A, 26→Z, 27→AA */
function colLabel(n: number): string {
  let result = '';
  while (n > 0) {
    const rem = (n - 1) % 26;
    result = String.fromCharCode(65 + rem) + result;
    n = Math.floor((n - 1) / 26);
  }
  return result;
}

// ============================================================================
// PinIcon – dark high-fantasy cinematic icons, 24×24 viewBox
// No SVG defs/gradients — all layered opacity shapes for zero ID collisions.
// External glow is applied via CSS drop-shadow on the parent button.
// ============================================================================

function PinIcon({ type, color, px }: { type: PinType; color: string; px: number }) {
  switch (type) {

    // ── Faction Capital ── ornate hanging diamond gem
    case 'faction_capital':
      return (
        <svg width={px} height={px} viewBox="0 0 24 24" overflow="visible" style={{ display: 'block' }}>
          {/* Deep dark base */}
          <polygon points="12,0.5 23.5,12 12,23.5 0.5,12" fill="#03050c" />
          {/* Faction color body */}
          <polygon points="12,0.5 23.5,12 12,23.5 0.5,12" fill={color} fillOpacity={0.42} />
          {/* Mid gem facet */}
          <polygon points="12,4.5 19.5,12 12,19.5 4.5,12" fill={color} fillOpacity={0.62} />
          {/* Inner bright core */}
          <polygon points="12,8.5 15.5,12 12,15.5 8.5,12" fill={color} fillOpacity={0.9} />
          {/* Hot centre point */}
          <circle cx={12} cy={12} r={2.2} fill="rgba(255,255,255,0.55)" />
          {/* Top facet highlight (glass) */}
          <polygon points="12,1.5 18,8.5 12,7 6,8.5" fill="rgba(255,255,255,0.07)" />
          {/* Outer rim: faction colour */}
          <polygon points="12,0.5 23.5,12 12,23.5 0.5,12" fill="none" stroke={color} strokeWidth={1.1} strokeOpacity={0.85} />
          {/* Outer rim: dark halo for definition */}
          <polygon points="12,0.5 23.5,12 12,23.5 0.5,12" fill="none" stroke="#000" strokeWidth={0.6} strokeOpacity={0.55} />
        </svg>
      );

    // ── City ── concentric glowing orb
    case 'city':
      return (
        <svg width={px} height={px} viewBox="0 0 24 24" overflow="visible" style={{ display: 'block' }}>
          <circle cx={12} cy={12} r={11} fill="#03050c" />
          <circle cx={12} cy={12} r={11} fill={color} fillOpacity={0.38} />
          <circle cx={12} cy={12} r={7.5} fill={color} fillOpacity={0.58} />
          <circle cx={12} cy={12} r={4.2} fill={color} fillOpacity={0.82} />
          <circle cx={12} cy={12} r={1.8} fill="rgba(255,255,255,0.55)" />
          {/* Specular highlight */}
          <ellipse cx={8.5} cy={8} rx={3} ry={2} fill="rgba(255,255,255,0.07)" />
          <circle cx={12} cy={12} r={11} fill="none" stroke={color} strokeWidth={1.1} strokeOpacity={0.75} />
          <circle cx={12} cy={12} r={11} fill="none" stroke="#000" strokeWidth={0.5} strokeOpacity={0.55} />
        </svg>
      );

    // ── Settlement ── smaller, dimmer orb
    case 'settlement':
      return (
        <svg width={px} height={px} viewBox="0 0 24 24" overflow="visible" style={{ display: 'block' }}>
          <circle cx={12} cy={12} r={8} fill="#03050c" />
          <circle cx={12} cy={12} r={8} fill={color} fillOpacity={0.3} />
          <circle cx={12} cy={12} r={5} fill={color} fillOpacity={0.5} />
          <circle cx={12} cy={12} r={2.5} fill={color} fillOpacity={0.75} />
          <circle cx={12} cy={12} r={1} fill="rgba(255,255,255,0.4)" />
          <circle cx={12} cy={12} r={8} fill="none" stroke={color} strokeWidth={1} strokeOpacity={0.55} />
          <circle cx={12} cy={12} r={8} fill="none" stroke="#000" strokeWidth={0.5} strokeOpacity={0.5} />
        </svg>
      );

    // ── Landmark ── mountain peak with glowing summit
    case 'landmark':
      return (
        <svg width={px} height={px} viewBox="0 0 24 24" overflow="visible" style={{ display: 'block' }}>
          {/* Mountain body */}
          <polygon points="12,1 23,22.5 1,22.5" fill="#03050c" />
          <polygon points="12,1 23,22.5 1,22.5" fill={color} fillOpacity={0.38} />
          {/* Upper peak glow */}
          <polygon points="12,1 17,12 7,12" fill={color} fillOpacity={0.65} />
          {/* Snow cap / hot tip */}
          <polygon points="12,1 14.5,7 9.5,7" fill="rgba(255,255,255,0.18)" />
          <circle cx={12} cy={3} r={1.5} fill={color} fillOpacity={0.9} />
          {/* Border */}
          <polygon points="12,1 23,22.5 1,22.5" fill="none" stroke={color} strokeWidth={1.1} strokeOpacity={0.7} />
          <polygon points="12,1 23,22.5 1,22.5" fill="none" stroke="#000" strokeWidth={0.5} strokeOpacity={0.5} />
        </svg>
      );

    // ── Dungeon / POI ── dark hexagon with ominous crossed runes
    case 'dungeon':
      return (
        <svg width={px} height={px} viewBox="0 0 24 24" overflow="visible" style={{ display: 'block' }}>
          {/* Hex body */}
          <polygon points="12,1.5 21.5,6.8 21.5,17.2 12,22.5 2.5,17.2 2.5,6.8" fill="#03050c" />
          <polygon points="12,1.5 21.5,6.8 21.5,17.2 12,22.5 2.5,17.2 2.5,6.8" fill={color} fillOpacity={0.35} />
          {/* Inner hex glow */}
          <polygon points="12,5 18,8.5 18,15.5 12,19 6,15.5 6,8.5" fill={color} fillOpacity={0.18} />
          {/* Crossed rune marks */}
          <line x1={8.5} y1={8.5} x2={15.5} y2={15.5} stroke={color} strokeWidth={1.8} strokeOpacity={0.88} strokeLinecap="round" />
          <line x1={15.5} y1={8.5} x2={8.5} y2={15.5} stroke={color} strokeWidth={1.8} strokeOpacity={0.88} strokeLinecap="round" />
          <circle cx={12} cy={12} r={2} fill={color} fillOpacity={0.75} />
          <circle cx={12} cy={12} r={0.9} fill="rgba(255,255,255,0.35)" />
          {/* Border */}
          <polygon points="12,1.5 21.5,6.8 21.5,17.2 12,22.5 2.5,17.2 2.5,6.8" fill="none" stroke={color} strokeWidth={1.1} strokeOpacity={0.7} />
          <polygon points="12,1.5 21.5,6.8 21.5,17.2 12,22.5 2.5,17.2 2.5,6.8" fill="none" stroke="#000" strokeWidth={0.5} strokeOpacity={0.5} />
        </svg>
      );

    // ── Port ── glowing orb with anchor
    case 'port':
      return (
        <svg width={px} height={px} viewBox="0 0 24 24" overflow="visible" style={{ display: 'block' }}>
          <circle cx={12} cy={12} r={11} fill="#03050c" />
          <circle cx={12} cy={12} r={11} fill={color} fillOpacity={0.3} />
          <circle cx={12} cy={12} r={7} fill={color} fillOpacity={0.18} />
          {/* Anchor */}
          <line x1={12} y1={5.5} x2={12} y2={18.5} stroke={color} strokeWidth={2} strokeOpacity={0.9} strokeLinecap="round" />
          <line x1={7.5} y1={8.2} x2={16.5} y2={8.2} stroke={color} strokeWidth={1.8} strokeOpacity={0.9} strokeLinecap="round" />
          <path d="M7,17 Q12,21.5 17,17" fill="none" stroke={color} strokeWidth={1.8} strokeOpacity={0.9} strokeLinecap="round" />
          <circle cx={12} cy={5.5} r={2.2} fill={color} fillOpacity={0.95} />
          <circle cx={12} cy={5.5} r={1} fill="rgba(255,255,255,0.4)" />
          {/* Border */}
          <circle cx={12} cy={12} r={11} fill="none" stroke={color} strokeWidth={1.1} strokeOpacity={0.7} />
          <circle cx={12} cy={12} r={11} fill="none" stroke="#000" strokeWidth={0.5} strokeOpacity={0.5} />
        </svg>
      );

    // ── House / Clan Seat ── heraldic shield, clearly subordinate to capital
    case 'house_seat':
      return (
        <svg width={px} height={px} viewBox="0 0 24 24" overflow="visible" style={{ display: 'block' }}>
          {/* Shield path: flat top, curved sides, pointed base */}
          <path d="M4,3 L20,3 L20,15 Q20,23 12,25 Q4,23 4,15 Z" fill="#03050c" />
          <path d="M4,3 L20,3 L20,15 Q20,23 12,25 Q4,23 4,15 Z" fill={color} fillOpacity={0.38} />
          {/* Inner shield glow */}
          <path d="M7,6 L17,6 L17,14 Q17,20 12,22 Q7,20 7,14 Z" fill={color} fillOpacity={0.58} />
          {/* Centre charge */}
          <path d="M9.5,9 L14.5,9 L14.5,14 Q14.5,17.5 12,18.5 Q9.5,17.5 9.5,14 Z" fill={color} fillOpacity={0.88} />
          {/* Hot point */}
          <circle cx={12} cy={14} r={1.6} fill="rgba(255,255,255,0.45)" />
          {/* Top bar divider (heraldic chief) */}
          <line x1={4} y1={7.5} x2={20} y2={7.5} stroke={color} strokeOpacity={0.35} strokeWidth={0.8} />
          {/* Specular highlight top-left */}
          <path d="M5,4 Q9,3.5 9,7 L5,7 Z" fill="rgba(255,255,255,0.07)" />
          {/* Border */}
          <path d="M4,3 L20,3 L20,15 Q20,23 12,25 Q4,23 4,15 Z" fill="none" stroke={color} strokeWidth={1} strokeOpacity={0.8} />
          <path d="M4,3 L20,3 L20,15 Q20,23 12,25 Q4,23 4,15 Z" fill="none" stroke="#000" strokeWidth={0.5} strokeOpacity={0.5} />
        </svg>
      );

    default:
      return (
        <svg width={px} height={px} viewBox="0 0 24 24" overflow="visible" style={{ display: 'block' }}>
          <circle cx={12} cy={12} r={11} fill="#03050c" />
          <circle cx={12} cy={12} r={11} fill={color} fillOpacity={0.4} />
          <circle cx={12} cy={12} r={6} fill={color} fillOpacity={0.7} />
          <circle cx={12} cy={12} r={2} fill="rgba(255,255,255,0.45)" />
          <circle cx={12} cy={12} r={11} fill="none" stroke={color} strokeWidth={1.1} strokeOpacity={0.75} />
        </svg>
      );
  }
}

/** Mystical eye — matches pin icon language; violet + gold for the Seer. */
function SeerIcon({ px }: { px: number }) {
  const iris = '#c4b5fd';
  const gold = '#d4a017';
  return (
    <svg width={px} height={px} viewBox="0 0 24 24" overflow="visible" style={{ display: 'block' }}>
      <ellipse cx={12} cy={12} rx={10} ry={7} fill="#03050c" />
      <ellipse cx={12} cy={12} rx={10} ry={7} fill={iris} fillOpacity={0.38} />
      <ellipse cx={12} cy={12} rx={7.5} ry={5.2} fill={gold} fillOpacity={0.22} />
      <ellipse cx={12} cy={12} rx={5.5} ry={4} fill="#0a0818" />
      <ellipse cx={12} cy={12} rx={4} ry={3.2} fill={iris} fillOpacity={0.92} />
      <ellipse cx={12} cy={12} rx={2.2} ry={2.8} fill="#1e1538" fillOpacity={0.55} />
      <circle cx={13.2} cy={10.8} r={1.15} fill="rgba(255,255,255,0.75)" />
      <ellipse cx={12} cy={12} rx={10} ry={7} fill="none" stroke={gold} strokeWidth={1.15} strokeOpacity={0.95} />
      <ellipse cx={12} cy={12} rx={10} ry={7} fill="none" stroke="#000" strokeWidth={0.45} strokeOpacity={0.5} />
    </svg>
  );
}

// ============================================================================
// GridOverlay — rendered inside stage (stage-pixel coordinate space)
// ============================================================================

function GridOverlay({
  cols, rows, imgW, imgH, zoom,
}: {
  cols: number; rows: number; imgW: number; imgH: number; zoom: number;
}) {
  const cellPxW = (imgW * zoom) / cols; // on-screen pixel width of a cell
  const showLabels = cellPxW > 52;
  const lsz = 11 / zoom; // label font-size: constant on screen

  return (
    <svg
      className="wme-grid"
      viewBox={`0 0 ${imgW} ${imgH}`}
      width={imgW}
      height={imgH}
      style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
      aria-hidden="true"
    >
      {/* Vertical lines */}
      {Array.from({ length: cols - 1 }, (_, i) => {
        const x = ((i + 1) / cols) * imgW;
        return (
          <line key={`cv${i}`} x1={x} y1={0} x2={x} y2={imgH}
            stroke="rgba(255,255,255,0.13)" strokeWidth={1 / zoom} />
        );
      })}
      {/* Horizontal lines */}
      {Array.from({ length: rows - 1 }, (_, i) => {
        const y = ((i + 1) / rows) * imgH;
        return (
          <line key={`rh${i}`} x1={0} y1={y} x2={imgW} y2={y}
            stroke="rgba(255,255,255,0.13)" strokeWidth={1 / zoom} />
        );
      })}
      {/* Column labels (A B C …) along top edge */}
      {showLabels && Array.from({ length: cols }, (_, i) => {
        const x = (i + 0.5) / cols * imgW;
        return (
          <text key={`cl${i}`} x={x} y={lsz + 3 / zoom}
            textAnchor="middle" fontSize={lsz}
            fill="rgba(240,230,180,0.55)" fontFamily="monospace" fontWeight="bold">
            {colLabel(i + 1)}
          </text>
        );
      })}
      {/* Row labels (1 2 3 …) along left edge */}
      {showLabels && Array.from({ length: rows }, (_, i) => {
        const y = (i + 0.5) / rows * imgH;
        return (
          <text key={`rl${i}`} x={lsz * 0.6 + 3 / zoom} y={y}
            dominantBaseline="middle" fontSize={lsz}
            fill="rgba(240,230,180,0.55)" fontFamily="monospace" fontWeight="bold">
            {i + 1}
          </text>
        );
      })}
      {/* Border */}
      <rect x={0} y={0} width={imgW} height={imgH}
        fill="none" stroke="rgba(255,255,255,0.2)" strokeWidth={2 / zoom} />
    </svg>
  );
}

// ============================================================================
// Compass Rose — decorative SVG, overlaid on wrapper (screen space)
// ============================================================================

function CompassRose() {
  return (
    <svg
      className="wme-compass"
      viewBox="0 0 80 80"
      width={72}
      height={72}
      aria-hidden="true"
    >
      <defs>
        <radialGradient id="cg" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#2a2340" stopOpacity={0.9} />
          <stop offset="100%" stopColor="#0e1018" stopOpacity={0.95} />
        </radialGradient>
      </defs>
      <circle cx={40} cy={40} r={38} fill="url(#cg)" stroke="#3a3448" strokeWidth={1.5} />
      {/* Cardinal spokes */}
      {[0, 90, 180, 270].map((deg) => {
        const r = (deg * Math.PI) / 180;
        const x1 = 40 + Math.sin(r) * 8;
        const y1 = 40 - Math.cos(r) * 8;
        const x2 = 40 + Math.sin(r) * 32;
        const y2 = 40 - Math.cos(r) * 32;
        return <line key={deg} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#4a4060" strokeWidth={1} />;
      })}
      {/* North arrow (gold) */}
      <polygon points="40,8 44,38 40,34 36,38" fill="#d4a017" opacity={0.95} />
      {/* South arrow (dark) */}
      <polygon points="40,72 44,42 40,46 36,42" fill="#4a4060" opacity={0.85} />
      {/* East/West arrows */}
      <polygon points="72,40 42,36 46,40 42,44" fill="#4a4060" opacity={0.7} />
      <polygon points="8,40 38,36 34,40 38,44"  fill="#4a4060" opacity={0.7} />
      {/* Centre disc */}
      <circle cx={40} cy={40} r={5} fill="#1a1530" stroke="#d4a017" strokeWidth={1.5} />
      <circle cx={40} cy={40} r={2} fill="#d4a017" />
      {/* N label */}
      <text x={40} y={6} textAnchor="middle" fontSize={8} fill="#d4a017" fontFamily="Georgia,serif" fontWeight="bold">N</text>
    </svg>
  );
}

// ============================================================================
// PlaceModal
// ============================================================================

interface PlaceModalProps {
  x: number;
  y: number;
  gridLabel: string;
  onSave: (pin: Omit<LocationPin, 'id' | 'createdAt'>) => void;
  onCancel: () => void;
  editing?: LocationPin | null;
}

function PlaceModal({ x, y, gridLabel, onSave, onCancel, editing }: PlaceModalProps) {
  const [label, setLabel]       = useState(editing?.label ?? '');
  const [type, setType]         = useState<PinType>(editing?.type ?? 'city');
  const [faction, setFaction]   = useState(editing?.faction ?? '');
  const [house, setHouse]       = useState(editing?.house ?? '');
  const [regionId, setRegionId] = useState(editing?.regionId ?? '');
  const [notes, setNotes]       = useState(editing?.notes ?? '');

  // When faction changes, clear house if it no longer belongs to the new faction
  useEffect(() => {
    const houses = faction ? (FACTION_HOUSES[faction] ?? []) : [];
    if (house && !houses.find((h) => h.id === house)) setHouse('');
  }, [faction, house]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onCancel]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!label.trim()) return;
    onSave({
      label:    label.trim(),
      type,
      faction:  faction  || undefined,
      house:    house    || undefined,
      regionId: regionId.trim() || undefined,
      x,
      y,
      notes:    notes.trim() || undefined,
    });
  }

  const previewColor = factionColor(faction || undefined);
  const availableHouses = faction ? (FACTION_HOUSES[faction] ?? []) : [];

  return (
    <div className="wme-modal-backdrop" onClick={onCancel}>
      <div className="wme-modal" onClick={(e) => e.stopPropagation()}>
        <div className="wme-modal__header">
          <span className="wme-modal__header-icon">
            <PinIcon type={type} color={previewColor} px={20} />
          </span>
          <h2 className="wme-modal__title">{editing ? 'Edit Location' : 'Place Location'}</h2>
          <button className="wme-modal__x" onClick={onCancel}>✕</button>
        </div>
        <p className="wme-modal__coords">
          Grid cell <strong style={{ color: '#d4a017' }}>{gridLabel}</strong>
          &ensp;·&ensp;{x.toFixed(1)}% × {y.toFixed(1)}%
        </p>
        <form onSubmit={handleSubmit} className="wme-modal__form">
          <label className="wme-modal__label">
            Name
            <input
              autoFocus
              className="wme-modal__input"
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Stonehaven Keep"
              required
            />
          </label>

          <div className="wme-modal__row">
            <label className="wme-modal__label" style={{ flex: 1 }}>
              Type
              <select
                className="wme-modal__select"
                value={type}
                onChange={(e) => setType(e.target.value as PinType)}
              >
                {PIN_TYPES.map((pt) => (
                  <option key={pt.id} value={pt.id}>{pt.label}</option>
                ))}
              </select>
            </label>

            <label className="wme-modal__label" style={{ flex: 1 }}>
              Faction <span className="wme-modal__opt">(optional)</span>
              <select
                className="wme-modal__select"
                value={faction}
                onChange={(e) => setFaction(e.target.value)}
                style={{ borderLeftColor: faction ? previewColor : undefined }}
              >
                <option value="">— Neutral —</option>
                {FACTIONS.map((f) => (
                  <option key={f.id} value={f.id}>{f.label}</option>
                ))}
              </select>
            </label>
          </div>

          {/* House / Clan picker — shown whenever a faction is chosen */}
          {availableHouses.length > 0 && (
            <label className="wme-modal__label">
              House / Clan <span className="wme-modal__opt">(optional)</span>
              <select
                className="wme-modal__select"
                value={house}
                onChange={(e) => setHouse(e.target.value)}
                style={{ borderLeftColor: house ? previewColor : undefined }}
              >
                <option value="">— None —</option>
                {availableHouses.map((h) => (
                  <option key={h.id} value={h.id}>{h.label}</option>
                ))}
              </select>
            </label>
          )}

          <label className="wme-modal__label">
            <span>
              Region ID <span className="wme-modal__opt">(optional — links to game engine)</span>
            </span>
            <input
              className="wme-modal__input"
              type="text"
              value={regionId}
              onChange={(e) => setRegionId(e.target.value)}
              placeholder='e.g. "Groth" or "Dur Khadur"'
            />
          </label>

          <label className="wme-modal__label">
            Notes <span className="wme-modal__opt">(optional)</span>
            <textarea
              className="wme-modal__textarea"
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Lore, description…"
            />
          </label>

          <div className="wme-modal__actions">
            <span className="wme-modal__hint">Esc to cancel</span>
            <button type="button" className="wme-modal__btn wme-modal__btn--cancel" onClick={onCancel}>
              Cancel
            </button>
            <button type="submit" className="wme-modal__btn wme-modal__btn--save">
              {editing ? 'Update' : 'Place Pin'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ============================================================================
// Sidebar
// ============================================================================

interface SidebarProps {
  pins: LocationPin[];
  filterType: string;
  filterFaction: string;
  onFilterType: (v: string) => void;
  onFilterFaction: (v: string) => void;
  onEdit: (pin: LocationPin) => void;
  onDelete: (id: string) => void;
  onHover: (id: string | null) => void;
  onClose: () => void;
  factionPower: FactionPowerEntry[];
  liveOwnership: Record<string, string>;
}

function Sidebar({
  pins, filterType, filterFaction,
  onFilterType, onFilterFaction,
  onEdit, onDelete, onHover, onClose,
  factionPower, liveOwnership,
}: SidebarProps) {
  const [search, setSearch] = useState('');
  const [showPower, setShowPower] = useState(true);

  const filtered = pins.filter((p) => {
    if (filterType && p.type !== filterType) return false;
    if (filterFaction && p.faction !== filterFaction) return false;
    if (search && !p.label.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  // Group by faction
  const grouped: Record<string, LocationPin[]> = {};
  for (const p of filtered) {
    const key = p.faction ?? '__neutral__';
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(p);
  }
  const groupKeys = Object.keys(grouped).sort((a, b) => {
    if (a === '__neutral__') return 1;
    if (b === '__neutral__') return -1;
    const la = FACTION_MAP[a]?.label ?? a;
    const lb = FACTION_MAP[b]?.label ?? b;
    return la.localeCompare(lb);
  });

  return (
    <aside className="wme-sidebar">
      <div className="wme-sidebar__header">
        <span className="wme-sidebar__title">Locations ({filtered.length}/{pins.length})</span>
        <button className="wme-sidebar__close" onClick={onClose} aria-label="Close sidebar">✕</button>
      </div>

      <div className="wme-sidebar__filters">
        <input
          className="wme-sidebar__search"
          type="text"
          placeholder="Search locations…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className="wme-sidebar__filter-row">
          <select className="wme-sidebar__filter-select" value={filterType} onChange={(e) => onFilterType(e.target.value)}>
            <option value="">All Types</option>
            {PIN_TYPES.map((pt) => <option key={pt.id} value={pt.id}>{pt.label}</option>)}
          </select>
          <select className="wme-sidebar__filter-select" value={filterFaction} onChange={(e) => onFilterFaction(e.target.value)}>
            <option value="">All Factions</option>
            {FACTIONS.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
          </select>
        </div>
      </div>

      <ul className="wme-sidebar__list">
        {filtered.length === 0 && (
          <li className="wme-sidebar__empty">No locations match.</li>
        )}
        {groupKeys.map((gk) => {
          const gPins = grouped[gk];
          const fac = gk === '__neutral__' ? null : FACTION_MAP[gk];
          const color = fac ? fac.color : '#6b7280';
          return (
            <li key={gk}>
              <div className="wme-sidebar__group-header" style={{ borderLeftColor: color }}>
                <span style={{ color }}>{fac ? fac.label : 'Neutral / Unknown'}</span>
                <span className="wme-sidebar__group-count">{gPins.length}</span>
              </div>
              <ul className="wme-sidebar__group-list">
                {gPins.map((pin) => {
                  const typeLabel = PIN_TYPES.find((t) => t.id === pin.type)?.label ?? pin.type;
                  const houseLabel = pin.house ? (HOUSE_MAP[pin.house]?.label ?? pin.house) : null;
                  return (
                    <li
                      key={pin.id}
                      className="wme-sidebar__item"
                      onMouseEnter={() => onHover(pin.id)}
                      onMouseLeave={() => onHover(null)}
                    >
                      <span className="wme-sidebar__item-dot" style={{ background: color }} />
                      <div className="wme-sidebar__item-body">
                        <span className="wme-sidebar__item-name">{pin.label}</span>
                        <span className="wme-sidebar__item-meta">
                          {typeLabel}{houseLabel ? ` · ${houseLabel}` : ''}
                        </span>
                      </div>
                      <div className="wme-sidebar__item-actions">
                        <button className="wme-sidebar__action" onClick={() => onEdit(pin)} title="Edit">✎</button>
                        <button className="wme-sidebar__action wme-sidebar__action--delete" onClick={() => onDelete(pin.id)} title="Delete">✕</button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </li>
          );
        })}
      </ul>

      {/* Faction Power Bars */}
      {factionPower.length > 0 && (
        <div className="wme-sidebar__power">
          <button
            className="wme-sidebar__power-toggle"
            onClick={() => setShowPower((v) => !v)}
          >
            {showPower ? '▾' : '▸'} Faction Power
          </button>
          {showPower && (
            <ul className="wme-sidebar__power-list">
              {factionPower
                .filter((fp) => FACTIONS.some((f) =>
                  f.label.toLowerCase().includes(fp.faction.toLowerCase()) ||
                  fp.faction.toLowerCase().includes(f.label.split(' ')[0].toLowerCase())
                ))
                .map((fp) => {
                  const fac = FACTIONS.find((f) =>
                    f.label.toLowerCase().includes(fp.faction.toLowerCase()) ||
                    fp.faction.toLowerCase().includes(f.label.split(' ')[0].toLowerCase())
                  );
                  const color = fac?.color ?? '#6b7280';
                  return (
                    <li key={fp.faction} className="wme-sidebar__power-item">
                      <span className="wme-sidebar__power-name" style={{ color }}>{fp.faction}</span>
                      {[
                        { key: 'MIL', val: fp.militaryPower },
                        { key: 'ECO', val: fp.economicPower },
                        { key: 'POL', val: fp.politicalInfluence },
                      ].map(({ key, val }) => (
                        <div key={key} className="wme-sidebar__power-row">
                          <span className="wme-sidebar__power-key">{key}</span>
                          <div className="wme-sidebar__power-track">
                            <div
                              className="wme-sidebar__power-bar"
                              style={{ width: `${Math.min(100, val ?? 0)}%`, background: color }}
                            />
                          </div>
                          <span className="wme-sidebar__power-val">{Math.round(val ?? 0)}</span>
                        </div>
                      ))}
                    </li>
                  );
                })}
            </ul>
          )}
        </div>
      )}
    </aside>
  );
}

// ============================================================================
// Main WorldMapEditor
// ============================================================================

/** True when running inside an iframe (e.g. Flask home). Do not use `?embed=` during SSR — it stays false after hydrate and never notifies the parent. */
function isEmbeddedInParent(): boolean {
  return typeof window !== 'undefined' && window.parent !== window;
}

interface PinMarkerProps {
  pin: LocationPin;
  left: number; top: number;
  color: string;
  isNew: boolean; isHov: boolean;
  hasConflict: boolean;
  portrait: string | undefined;
  pinPx: number; labelPx: number;
  showPinLabels: boolean;
  zoomDisplay: number;
  embedUI: boolean;
  onMouseEnter: (id: string, e: React.MouseEvent) => void;
  onMouseLeave: () => void;
  onEdit: (pin: LocationPin) => void;
  onDelete: (id: string) => void;
}

const PinMarker = React.memo(function PinMarker({
  pin, left, top, color, isNew, isHov, hasConflict, portrait,
  pinPx, labelPx, showPinLabels, zoomDisplay, embedUI,
  onMouseEnter, onMouseLeave, onEdit, onDelete,
}: PinMarkerProps) {
  return (
    <div
      className={`wme-pin${isNew ? ' wme-pin--new' : ''}${isHov ? ' wme-pin--hov' : ''}`}
      style={{ position: 'absolute', left, top, transform: 'translate(-50%, -100%)', zIndex: isHov ? 30 : 10, pointerEvents: 'auto' }}
      onMouseEnter={(e) => onMouseEnter(pin.id, e)}
      onMouseLeave={onMouseLeave}
    >
      {hasConflict && (
        <div className="wme-conflict-ring" style={{ width: pinPx + 10, height: pinPx + 10, borderColor: '#f59e0b' }} />
      )}
      <button
        type="button"
        className="wme-pin-btn"
        onClick={(e) => { e.stopPropagation(); if (!embedUI) onEdit(pin); }}
        onContextMenu={(e) => { e.preventDefault(); e.stopPropagation(); if (!embedUI) onDelete(pin.id); }}
        title={embedUI ? pin.label : `${pin.label} — right-click to delete`}
        style={{
          width: pinPx, height: pinPx,
          filter: [
            `drop-shadow(0 0 ${5 / zoomDisplay}px ${color}dd)`,
            `drop-shadow(0 0 ${10 / zoomDisplay}px ${color}55)`,
            `drop-shadow(0 ${2 / zoomDisplay}px ${5 / zoomDisplay}px rgba(0,0,0,0.95))`,
          ].join(' '),
          transition: 'filter 0.5s ease',
        }}
      >
        <PinIcon type={pin.type} color={color} px={pinPx} />
      </button>
      {portrait && zoomDisplay >= 1.2 && pin.type === 'faction_capital' && (
        <img
          src={`/api/game-static${portrait.startsWith('/') ? portrait : `/${portrait}`}`}
          alt=""
          className="wme-portrait"
          style={{ width: pinPx + 4, height: pinPx + 4, borderColor: color }}
        />
      )}
      {showPinLabels && (
        <span
          className="wme-pin-label"
          style={{
            color, fontSize: labelPx, marginTop: 2 / zoomDisplay,
            letterSpacing: `${0.06 / zoomDisplay}em`,
            textShadow: [
              `0 0 ${6 / zoomDisplay}px ${color}99`,
              `0 ${1 / zoomDisplay}px ${3 / zoomDisplay}px #000`,
              `0 0 ${12 / zoomDisplay}px rgba(0,0,0,0.9)`,
            ].join(', '),
            transition: 'color 0.5s ease',
          }}
        >
          {pin.label}
        </span>
      )}
    </div>
  );
});

import React from 'react';

export default function WorldMapEditor() {
  const embedReadyPostedRef = useRef(false);
  const flashTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cursorRafRef = useRef<number | null>(null);
  const showGridRef = useRef(true);
  /** Flask home iframe passes `?embed=1` — map only, no toolbar/sidebar/toasts, read-only pins. */
  const [embedUI, setEmbedUI] = useState(false);

  // --- Image & viewport ---
  const imgRef    = useRef<HTMLImageElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const stageRef  = useRef<HTMLDivElement>(null);
  const [imgSize, setImgSize] = useState<{ w: number; h: number } | null>(null);

  // zoom/pan via refs (imperative) for smooth 60fps updates
  const zoomRef = useRef(1);
  const panRef  = useRef({ x: 0, y: 0 });
  const [zoomDisplay, setZoomDisplay] = useState(1);

  // --- Drag state ---
  const dragRef = useRef<{
    startX: number; startY: number;
    panX: number;   panY: number;
    moved: boolean;
  } | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  // --- Cursor cell display ---
  const [cursorCell, setCursorCell] = useState<string | null>(null);
  const [cursorPct, setCursorPct]   = useState<{ x: number; y: number } | null>(null);

  // --- Pins ---
  const [pins, setPins]     = useState<LocationPin[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // --- Live game-engine state ---
  const [liveOwnership, setLiveOwnership]     = useState<Record<string, string>>({});   // pinId → factionId
  const [conflictEvents, setConflictEvents]   = useState<Record<string, LivePin['conflictEvent']>>({});  // pinId → event
  const [portraits, setPortraits]             = useState<Record<string, string>>({});   // pinId → img URL
  const [factionPower, setFactionPower]       = useState<FactionPowerEntry[]>([]);
  const [sseStatus, setSseStatus]             = useState<'connecting' | 'live' | 'offline'>('connecting');
  const [worldDate, setWorldDate]             = useState<string>('');
  const [tickNumber, setTickNumber]           = useState<number | null>(null);
  const [clock, setClock]                     = useState<ClockState | null>(null);
  const [clockBusy, setClockBusy]             = useState(false);
  const [council, setCouncil]                 = useState<CouncilReport | null>(null);
  const [showCouncil, setShowCouncil]         = useState(false);
  const [activeAdvisor, setActiveAdvisor]     = useState<CouncilAdvisor>('chancellor');
  const [explainability, setExplainability]   = useState<ExplainabilityReport | null>(null);
  const [showExplainability, setShowExplainability] = useState(false);
  const [selectedCauseId, setSelectedCauseId] = useState<string | null>(null);
  const [intel, setIntel]                     = useState<FactionIntelReport | null>(null);
  const [showIntel, setShowIntel]             = useState(false);
  const [selectedIntelFaction, setSelectedIntelFaction] = useState<string | null>(null);
  const [autopsy, setAutopsy]                 = useState<LastTickAutopsyResponse | null>(null);
  const [showAutopsy, setShowAutopsy]         = useState(false);
  const sseRef = useRef<EventSource | null>(null);

  // --- Historical playback ---
  const [history, setHistory]                 = useState<HistorySnapshot[]>([]);
  const [playbackMode, setPlaybackMode]       = useState(false);
  const [playbackTick, setPlaybackTick]       = useState(0);
  const [isPlaying, setIsPlaying]             = useState(false);
  const playIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [showPlayback, setShowPlayback]       = useState(false);

  // --- Event toasts ---
  const [toasts, setToasts]                   = useState<DispatchToast[]>([]);
  const prevActiveEventNamesRef = useRef<string[]>([]);

  // --- Modal / editing ---
  const [pendingClick, setPendingClick] = useState<{ x: number; y: number } | null>(null);
  const [editingPin, setEditingPin]     = useState<LocationPin | null>(null);
  const [flashPinId, setFlashPinId]     = useState<string | null>(null);

  // --- UI controls ---
  const [showGrid, setShowGrid]         = useState(true);
  const [gridSizeIdx, setGridSizeIdx]   = useState(1);
  const [snapToGrid, setSnapToGrid]     = useState(false);
  const [showSidebar, setShowSidebar]   = useState(false);
  const [filterType, setFilterType]     = useState('');
  const [filterFaction, setFilterFaction] = useState('');
  const [hoveredPin, setHoveredPin]     = useState<string | null>(null);
  const [tooltip, setTooltip]           = useState<{
    pin: LocationPin; px: number; py: number;
  } | null>(null);
  const [seerOnMap, setSeerOnMap]       = useState<SeerOnMap | null>(null);
  const [seerTooltip, setSeerTooltip]   = useState<{ px: number; py: number } | null>(null);

  // -------------------------------------------------------------------------
  // Playback helpers
  // -------------------------------------------------------------------------

  const FACTION_NAME_TO_ID: Record<string, string> = {
    'Twin Cities': 'twin_cities', 'High Kingdom': 'twin_cities',
    'Shadow Court': 'faerwood', 'Faerwood': 'faerwood',
    'Glenwood': 'glenwood', 'Glenhaven': 'glenwood',
    'Groth Clans': 'groth_clans', 'Gilgeth Clans': 'gilgeth_clans',
    'Tidefall': 'tidefall', 'Varkuun': 'varkuun', 'Farrock': 'varkuun',
    'Vilefin': 'vilefin', 'Frostvale': 'frostvale', 'Wintermark': 'frostvale',
    'Lostfeld': 'lostfeld', 'Dur Khadur': 'dur_khadur',
    'Dreadwind': 'dreadwind', 'Dreadwind Isles': 'dreadwind',
    'Stonebreak': 'stonebreak', 'Gloomspire': 'stonebreak',
  };

  function getPlaybackFaction(pin: LocationPin): string | undefined {
    const snap = history[playbackTick];
    if (!snap || !pin.regionId) return pin.faction;
    const controller = snap.regionControl[pin.regionId];
    if (!controller) return pin.faction;
    return FACTION_NAME_TO_ID[controller] ?? pin.faction;
  }

  // -------------------------------------------------------------------------
  // Helpers: transform
  // -------------------------------------------------------------------------
  function applyTransform() {
    if (stageRef.current) {
      stageRef.current.style.transform =
        `translate(${panRef.current.x}px, ${panRef.current.y}px) scale(${zoomRef.current})`;
    }
  }

  /** Keep zoom ≥ fit-scale and pan so the map always covers the viewport (no empty margin past map edges). */
  const clampViewportUsing = useCallback((iw: number, ih: number) => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    const ww = wrapper.clientWidth;
    const wh = wrapper.clientHeight;
    const fitZ = Math.min(ww / iw, wh / ih);
    let z = zoomRef.current;
    if (z < fitZ) z = fitZ;
    if (z > ZOOM_MAX) z = ZOOM_MAX;
    zoomRef.current = z;
    const sw = iw * z;
    const sh = ih * z;
    let px = panRef.current.x;
    let py = panRef.current.y;
    if (sw >= ww) px = Math.min(0, Math.max(px, ww - sw));
    else px = (ww - sw) / 2;
    if (sh >= wh) py = Math.min(0, Math.max(py, wh - sh));
    else py = (wh - sh) / 2;
    panRef.current = { x: px, y: py };
    applyTransform();
    setZoomDisplay(z);
  }, []);

  const clampViewport = useCallback(() => {
    if (!imgSize) return;
    clampViewportUsing(imgSize.w, imgSize.h);
  }, [imgSize, clampViewportUsing]);

  const initViewport = useCallback((w: number, h: number) => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    const ww = wrapper.clientWidth;
    const wh = wrapper.clientHeight;
    const fz = Math.min(ww / w, wh / h);
    zoomRef.current = fz;
    panRef.current  = { x: (ww - w * fz) / 2, y: (wh - h * fz) / 2 };
    clampViewportUsing(w, h);
  }, [clampViewportUsing]);

  function fitToScreen() {
    if (imgSize) initViewport(imgSize.w, imgSize.h);
  }

  function zoomBy(factor: number) {
    const wrapper = wrapperRef.current;
    if (!wrapper || !imgSize) return;
    const { width: ww, height: wh } = wrapper.getBoundingClientRect();
    const cx = ww / 2, cy = wh / 2;
    const oldZ = zoomRef.current;
    const fitZ = Math.min(ww / imgSize.w, wh / imgSize.h);
    const newZ = clamp(oldZ * factor, fitZ, ZOOM_MAX);
    const imgX = (cx - panRef.current.x) / oldZ;
    const imgY = (cy - panRef.current.y) / oldZ;
    panRef.current = { x: cx - imgX * newZ, y: cy - imgY * newZ };
    zoomRef.current = newZ;
    clampViewport();
  }

  // -------------------------------------------------------------------------
  // Image load → init
  // -------------------------------------------------------------------------
  function handleImageLoad() {
    const img = imgRef.current;
    if (!img) return;
    const w = img.naturalWidth;
    const h = img.naturalHeight;
    setImgSize({ w, h });
    initViewport(w, h);
  }

  // Flask home /enter: dismiss atlas veil when iframe map is painted (matches Map.tsx / StrategyMap.tsx).
  useEffect(() => {
    if (!isEmbeddedInParent()) return;
    if (!imgSize) return;
    if (embedReadyPostedRef.current) return;
    let cancelled = false;
    const id = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          if (cancelled || embedReadyPostedRef.current) return;
          embedReadyPostedRef.current = true;
          try {
            window.parent.postMessage({ type: 'aeloria-home-map-ready' }, '*');
          } catch {
            /* ignore */
          }
        });
      });
    });
    return () => {
      cancelled = true;
      cancelAnimationFrame(id);
    };
  }, [imgSize]);

  useLayoutEffect(() => {
    const q = new URLSearchParams(window.location.search).get('embed');
    setEmbedUI(q === '1' || q === 'true' || q === 'yes');
  }, []);

  useEffect(() => {
    if (embedUI) setShowGrid(false);
  }, [embedUI]);

  useEffect(() => { showGridRef.current = showGrid; }, [showGrid]);

  useEffect(() => {
    return () => { if (flashTimeoutRef.current) clearTimeout(flashTimeoutRef.current); };
  }, []);

  // -------------------------------------------------------------------------
  // Window resize
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!imgSize) return;
    const onResize = () => clampViewportUsing(imgSize.w, imgSize.h);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [imgSize, clampViewportUsing]);

  // -------------------------------------------------------------------------
  // Wheel zoom
  // -------------------------------------------------------------------------
  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper || !imgSize) return;
    const { w: iw, h: ih } = imgSize;
    function onWheel(e: WheelEvent) {
      e.preventDefault();
      const el = wrapperRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const oldZ = zoomRef.current;
      const fitZ = Math.min(rect.width / iw, rect.height / ih);
      const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      const newZ = clamp(oldZ * factor, fitZ, ZOOM_MAX);
      const imgX = (mx - panRef.current.x) / oldZ;
      const imgY = (my - panRef.current.y) / oldZ;
      panRef.current = { x: mx - imgX * newZ, y: my - imgY * newZ };
      zoomRef.current = newZ;
      clampViewportUsing(iw, ih);
    }
    wrapper.addEventListener('wheel', onWheel, { passive: false });
    return () => wrapper.removeEventListener('wheel', onWheel);
  }, [imgSize, clampViewportUsing]);

  // -------------------------------------------------------------------------
  // Load pins
  // -------------------------------------------------------------------------
  useEffect(() => {
    fetch('/api/locations')
      .then((r) => r.json())
      .then((data: LocationPin[]) => { setPins(data); setLoading(false); })
      .catch((err: unknown) => {
        setLoadError(err instanceof Error ? err.message : 'Failed to load');
        setLoading(false);
      });
  }, []);

  // -------------------------------------------------------------------------
  // Live map-state refresh
  // -------------------------------------------------------------------------
  const embedUIRef = useRef(embedUI);
  useEffect(() => { embedUIRef.current = embedUI; }, [embedUI]);

  const refreshMapState = useCallback(async () => {
    try {
      const res = await fetch('/api/map-state');
      if (!res.ok) { setSseStatus('offline'); return; }
      const data = await res.json() as {
        pins: LivePin[];
        factionPower: FactionPowerEntry[];
        tick: number;
        worldDate: string;
        activeEvents: { name: string; involved: string[]; severity: number; trend: string; summary?: string }[];
        primaryEvent: { name: string; severity: number; summary: string } | null;
        seerMap: SeerOnMap | null;
      };

      if (!Array.isArray(data.pins)) return;

      // Sync pins from locations.json (server) — strip live-only fields
      setPins(
        data.pins.map((lp) => {
          const { liveFaction: _lf, conflictEvent: _ce, leaderPortrait: _lp, ...rest } = lp;
          return rest as LocationPin;
        }),
      );

      const ownership: Record<string, string> = {};
      const conflicts: Record<string, LivePin['conflictEvent']> = {};
      const pvts:      Record<string, string> = {};
      for (const lp of data.pins) {
        if (lp.liveFaction)    ownership[lp.id] = lp.liveFaction;
        if (lp.conflictEvent)  conflicts[lp.id] = lp.conflictEvent;
        if (lp.leaderPortrait) pvts[lp.id]      = lp.leaderPortrait;
      }
      setLiveOwnership(ownership);
      setConflictEvents(conflicts);
      setPortraits(pvts);
      setFactionPower(data.factionPower ?? []);
      setTickNumber(data.tick ?? null);
      setWorldDate(data.worldDate ?? '');

      const sm = data.seerMap;
      if (
        sm &&
        typeof sm.x === 'number' &&
        typeof sm.y === 'number' &&
        Number.isFinite(sm.x) &&
        Number.isFinite(sm.y)
      ) {
        setSeerOnMap(sm);
      } else {
        setSeerOnMap(null);
      }

      if (!embedUIRef.current) {
        const namesNow = (data.activeEvents ?? []).map((e) => e.name as string);
        const prevNames = prevActiveEventNamesRef.current;
        if (prevNames.length > 0) {
          const now = Date.now();
          const newToasts: DispatchToast[] = (data.activeEvents ?? [])
            .filter((e) => e.name && !prevNames.includes(e.name))
            .slice(0, 3)
            .map((e): DispatchToast => {
              const involved = e.involved ?? [];
              const faction  = involved[0] ?? '';
              const fac      = FACTIONS.find((f) => f.label.toLowerCase().includes(faction.toLowerCase()));
              return {
                id:       `toast_${now}_${Math.random().toString(36).slice(2)}`,
                header:   `${severityRoman(e.severity)} — ${e.trend?.toUpperCase() ?? 'EMERGING'}`,
                body:     e.name,
                severity: e.severity ?? 1,
                color:    fac?.color ?? '#d4a017',
                expires:  now + 8000,
              };
            });
          if (newToasts.length) {
            setToasts((prev) => [...prev, ...newToasts].slice(-4));
          }
        }
        prevActiveEventNamesRef.current = namesNow;
      } else {
        prevActiveEventNamesRef.current = (data.activeEvents ?? []).map((e) => e.name as string);
      }
    } catch { setSseStatus('offline'); }
  }, []);

  const refreshClock = useCallback(async () => {
    try {
      const res = await fetch('/api/clock', { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json() as ClockState;
      setClock(data);
      if (typeof data.current_tick === 'number') setTickNumber(data.current_tick);
      if (data.world_date) setWorldDate(data.world_date);
    } catch {
      // Clock state is secondary to the map itself; SSE status handles backend availability.
    }
  }, []);

  const postClock = useCallback(async (path: string, body?: unknown) => {
    setClockBusy(true);
    try {
      const res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const data = await res.json().catch(() => null) as ClockState | { clock?: ClockState } | null;
      if (res.ok && data) {
        const nextClock = 'clock' in data && data.clock ? data.clock : data as ClockState;
        setClock(nextClock);
        if (nextClock.current_tick != null) setTickNumber(nextClock.current_tick);
        if (nextClock.world_date) setWorldDate(nextClock.world_date);
        if (path.endsWith('/step')) refreshMapState();
      }
    } catch {
      setSseStatus('offline');
    } finally {
      setClockBusy(false);
    }
  }, [refreshMapState]);

  const toggleClockPaused = useCallback(() => {
    if (!clock || clockBusy) return;
    postClock(clock.paused ? '/api/clock/resume' : '/api/clock/pause');
  }, [clock, clockBusy, postClock]);

  const setClockSpeed = useCallback((speed: number) => {
    if (clockBusy) return;
    postClock('/api/clock/speed', { speed });
  }, [clockBusy, postClock]);

  const stepClock = useCallback(() => {
    if (clockBusy || clock?.is_processing) return;
    postClock('/api/clock/step');
  }, [clock, clockBusy, postClock]);

  const refreshCouncil = useCallback(async () => {
    try {
      const res = await fetch('/api/council', { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json() as CouncilReport;
      setCouncil(data);
    } catch {
      // Council is an intelligence surface; the live map can continue without it.
    }
  }, []);

  const refreshExplainability = useCallback(async () => {
    try {
      const res = await fetch('/api/explainability?limit=18', { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json() as ExplainabilityReport;
      setExplainability(data);
      setSelectedCauseId((current) => {
        if (current && data.explanations.some((item) => item.id === current)) return current;
        return data.explanations[0]?.id ?? null;
      });
    } catch {
      // Explainability is an overlay; the map remains usable without it.
    }
  }, []);

  const refreshIntel = useCallback(async () => {
    try {
      const res = await fetch('/api/faction-intel?limit=18', { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json() as FactionIntelReport;
      setIntel(data);
      setSelectedIntelFaction((current) => {
        if (current && data.factions.some((row) => row.faction === current)) return current;
        return data.factions[0]?.faction ?? null;
      });
    } catch {
      // Intel is a read-only overlay; the map can run without it.
    }
  }, []);

  const refreshAutopsy = useCallback(async () => {
    try {
      const res = await fetch('/api/axiom/last-tick', { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json() as LastTickAutopsyResponse;
      setAutopsy(data);
    } catch {
      // Autopsy is a debug surface; the map remains usable without it.
    }
  }, []);

  // SSE subscription
  useEffect(() => {
    refreshMapState();
    refreshClock();
    refreshCouncil();
    refreshExplainability();
    refreshIntel();
    refreshAutopsy();

    let retryMs = 1000;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      const es = new EventSource('/api/map-events');
      sseRef.current = es;

      es.onopen = () => { setSseStatus('live'); retryMs = 1000; };

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as { type: string; tick?: number; world_date?: string; clock?: ClockState };
          if (data.type === 'offline') { setSseStatus('offline'); return; }
          if (data.clock) {
            setClock(data.clock);
            if (typeof data.clock.current_tick === 'number') setTickNumber(data.clock.current_tick);
            if (data.clock.world_date) setWorldDate(data.clock.world_date);
          }
          if (typeof data.tick === 'number') setTickNumber(data.tick);
          if (data.world_date) setWorldDate(data.world_date);
          if (
            data.type === 'tick' ||
            data.type === 'tick_completed' ||
            data.type === 'tick_started' ||
            data.type === 'tick_failed' ||
            data.type === 'clock' ||
            data.type === 'connected'
          ) {
            setSseStatus('live');
            if (data.type === 'tick' || data.type === 'tick_completed') {
              refreshMapState();
              refreshCouncil();
              refreshExplainability();
              refreshIntel();
              refreshAutopsy();
            }
          }
        } catch { /* ignore bad frames */ }
      };

      es.onerror = () => {
        setSseStatus('offline');
        es.close();
        sseRef.current = null;
        retryTimer = setTimeout(() => { retryMs = Math.min(retryMs * 2, 30000); connect(); }, retryMs);
      };
    }

    connect();
    return () => {
      sseRef.current?.close();
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [refreshAutopsy, refreshClock, refreshCouncil, refreshExplainability, refreshIntel, refreshMapState]);

  // Load history snapshots
  useEffect(() => {
    fetch('/api/map-history')
      .then((r) => r.json())
      .then((data: HistorySnapshot[]) => setHistory(data))
      .catch(() => {});
  }, []);

  // Toast cleanup
  useEffect(() => {
    if (!toasts.length) return;
    const timer = setTimeout(() => {
      const now = Date.now();
      setToasts((prev) => prev.filter((t) => t.expires > now));
    }, 500);
    return () => clearTimeout(timer);
  }, [toasts]);

  // Playback auto-advance
  useEffect(() => {
    if (!isPlaying || !playbackMode) {
      if (playIntervalRef.current) clearInterval(playIntervalRef.current);
      return;
    }
    playIntervalRef.current = setInterval(() => {
      setPlaybackTick((t) => {
        if (t >= history.length - 1) { setIsPlaying(false); return t; }
        return t + 1;
      });
    }, 2000);
    return () => { if (playIntervalRef.current) clearInterval(playIntervalRef.current); };
  }, [isPlaying, playbackMode, history.length]);

  useEffect(() => {
    if (playbackMode) setSeerTooltip(null);
  }, [playbackMode]);

  // -------------------------------------------------------------------------
  // Keyboard
  // -------------------------------------------------------------------------
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { setPendingClick(null); setEditingPin(null); }
      if (e.key === 'f' && !pendingClick) fitToScreen();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [pendingClick, fitToScreen]);

  // -------------------------------------------------------------------------
  // Mouse: drag-to-pan + click-to-place
  // -------------------------------------------------------------------------
  function getCellLabel(pctX: number, pctY: number) {
    const g = GRID_SIZES[gridSizeIdx];
    const col = clamp(Math.floor(pctX / 100 * g.cols), 0, g.cols - 1);
    const row = clamp(Math.floor(pctY / 100 * g.rows), 0, g.rows - 1);
    return `${colLabel(col + 1)}${row + 1}`;
  }

  function screenToImgPct(clientX: number, clientY: number) {
    const wrapper = wrapperRef.current;
    if (!wrapper || !imgSize) return null;
    const rect = wrapper.getBoundingClientRect();
    const imgX = (clientX - rect.left - panRef.current.x) / zoomRef.current;
    const imgY = (clientY - rect.top  - panRef.current.y) / zoomRef.current;
    const pctX = (imgX / imgSize.w) * 100;
    const pctY = (imgY / imgSize.h) * 100;
    if (pctX < 0 || pctX > 100 || pctY < 0 || pctY > 100) return null;
    return { x: pctX, y: pctY };
  }

  function handleMouseDown(e: React.MouseEvent) {
    if (e.button !== 0) return;
    dragRef.current = {
      startX: e.clientX, startY: e.clientY,
      panX: panRef.current.x, panY: panRef.current.y,
      moved: false,
    };
  }

  function handleMouseMove(e: React.MouseEvent) {
    const drag = dragRef.current;
    if (drag) {
      const dx = e.clientX - drag.startX;
      const dy = e.clientY - drag.startY;
      if (!drag.moved && Math.hypot(dx, dy) > 4) {
        drag.moved = true;
        setIsDragging(true);
      }
      if (drag.moved) {
        panRef.current = { x: drag.panX + dx, y: drag.panY + dy };
        applyTransform();
        if (imgSize) clampViewportUsing(imgSize.w, imgSize.h);
      }
    }

    // Cursor cell indicator — throttled to one state update per animation frame
    const cx = e.clientX;
    const cy = e.clientY;
    if (!cursorRafRef.current) {
      cursorRafRef.current = requestAnimationFrame(() => {
        cursorRafRef.current = null;
        const pos = screenToImgPct(cx, cy);
        if (pos) {
          setCursorPct(pos);
          setCursorCell(showGridRef.current ? getCellLabel(pos.x, pos.y) : null);
        } else {
          setCursorPct(null);
          setCursorCell(null);
        }
      });
    }
  }

  function handleMouseUp(e: React.MouseEvent) {
    const drag = dragRef.current;
    dragRef.current = null;
    setIsDragging(false);
    if (!drag || drag.moved) return;
    if ((e.target as HTMLElement).closest('.wme-pin-btn')) return;
    if ((e.target as HTMLElement).closest('.wme-seer')) return;
    if (embedUI) return;

    const pos = screenToImgPct(e.clientX, e.clientY);
    if (!pos) return;

    let { x, y } = pos;
    if (snapToGrid) {
      const g = GRID_SIZES[gridSizeIdx];
      const col = Math.floor(x / 100 * g.cols);
      const row = Math.floor(y / 100 * g.rows);
      x = (col + 0.5) / g.cols * 100;
      y = (row + 0.5) / g.rows * 100;
    }
    setPendingClick({ x, y });
  }

  // -------------------------------------------------------------------------
  // CRUD
  // -------------------------------------------------------------------------
  const handleSave = useCallback(
    async (partial: Omit<LocationPin, 'id' | 'createdAt'>) => {
      const _errToast = (msg: string) => {
        const now = Date.now();
        setToasts((prev) => [...prev, {
          id: `toast_err_${now}`, header: 'ERROR', body: msg,
          severity: 5, color: '#e05c5c', expires: now + 5000,
        }].slice(-4));
      };
      if (editingPin) {
        const res = await fetch('/api/locations', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: editingPin.id, ...partial }),
        });
        if (res.ok) {
          const updated: LocationPin = await res.json();
          setPins((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
        } else {
          _errToast('Failed to save pin');
          return;
        }
      } else {
        const res = await fetch('/api/locations', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(partial),
        });
        if (res.ok) {
          const created: LocationPin = await res.json();
          setPins((prev) => [...prev, created]);
          setFlashPinId(created.id);
          flashTimeoutRef.current = setTimeout(() => setFlashPinId(null), 900);
        } else {
          _errToast('Failed to create pin');
          return;
        }
      }
      setPendingClick(null);
      setEditingPin(null);
    },
    [editingPin],
  );

  const handleDelete = useCallback(async (id: string) => {
    const res = await fetch(`/api/locations?id=${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (!res.ok) {
      const now = Date.now();
      setToasts((prev) => [...prev, {
        id: `toast_err_${now}`, header: 'ERROR', body: 'Failed to delete pin',
        severity: 5, color: '#e05c5c', expires: now + 5000,
      }].slice(-4));
      return;
    }
    setPins((prev) => prev.filter((p) => p.id !== id));
  }, []);

  const handleEdit = useCallback((pin: LocationPin) => {
    setEditingPin(pin);
    setPendingClick({ x: pin.x, y: pin.y });
    setShowSidebar(false);
  }, []);

  const handlePinMouseEnter = useCallback((id: string, e: React.MouseEvent) => {
    setHoveredPin(id);
    const wr = wrapperRef.current?.getBoundingClientRect();
    if (wr) {
      const pin = pinsRef.current.find((p) => p.id === id);
      if (pin) setTooltip({ pin, px: e.clientX - wr.left, py: e.clientY - wr.top });
    }
  }, []);
  const handlePinMouseLeave = useCallback(() => { setHoveredPin(null); setTooltip(null); }, []);

  // Keep a ref to pins so the hover callback can look up the pin without being in its deps
  const pinsRef = useRef<LocationPin[]>([]);
  useEffect(() => { pinsRef.current = pins; }, [pins]);

  // -------------------------------------------------------------------------
  // Derived
  // -------------------------------------------------------------------------
  const displayedPins = useMemo(() => pins.filter((p) => {
    if (filterType    && p.type    !== filterType)    return false;
    if (filterFaction && p.faction !== filterFaction) return false;
    if (zoomDisplay < (PIN_ZOOM_THRESHOLD[p.type] ?? 0))  return false;
    return true;
  }), [pins, filterType, filterFaction, zoomDisplay]);

  const gridSize = GRID_SIZES[gridSizeIdx];
  const pendingCellLabel = pendingClick
    ? getCellLabel(pendingClick.x, pendingClick.y)
    : '';

  // Pin size stays ~24px on screen regardless of zoom
  const PIN_PX = 24 / zoomDisplay;
  const SEER_PX = 30 / zoomDisplay;
  // Label font stays ~11px on screen
  const LABEL_PX = 11 / zoomDisplay;
  const showPinLabels = zoomDisplay > LABEL_ZOOM_THRESHOLD;
  const advisorTabs: { id: CouncilAdvisor; label: string }[] = [
    { id: 'chancellor', label: 'Chancellor' },
    { id: 'marshal', label: 'Marshal' },
    { id: 'steward', label: 'Steward' },
    { id: 'spymaster', label: 'Spymaster' },
    { id: 'chronicler', label: 'Chronicler' },
  ];
  const activeCouncilItems = council?.advisor_reports?.[activeAdvisor] ?? [];
  const topCouncilRisk = council?.top_risks?.[0];
  const activeCouncilBriefing = council?.advisor_briefings?.[activeAdvisor];
  const topExplanation = explainability?.explanations?.[0];
  const selectedCause =
    explainability?.explanations.find((item) => item.id === selectedCauseId)
    ?? topExplanation
    ?? null;
  const explanationDomains = explainability
    ? Object.entries(explainability.domain_counts).sort((a, b) => b[1] - a[1])
    : [];
  const selectedIntel =
    intel?.factions.find((item) => item.faction === selectedIntelFaction)
    ?? intel?.factions[0]
    ?? null;
  const topIntel = intel?.factions[0] ?? null;
  const lastAutopsy =
    autopsy?.last_tick_autopsy && 'tick' in autopsy.last_tick_autopsy
      ? autopsy.last_tick_autopsy as LastTickAutopsy
      : null;
  const recentAutopsyRecords = autopsy?.recent_causality_records ?? [];
  const topAutopsyCause =
    lastAutopsy?.causality_records?.[0]
    ?? recentAutopsyRecords[recentAutopsyRecords.length - 1]
    ?? null;
  const topAutopsyPressure = lastAutopsy?.pressures?.[0] ?? null;
  const topAutopsyBelief =
    topAutopsyCause && lastAutopsy
      ? lastAutopsy.beliefs.find((row) => row.faction === topAutopsyCause.actor)?.beliefs?.[0] ?? null
      : lastAutopsy?.beliefs?.[0]?.beliefs?.[0] ?? null;
  const topAutopsySurface =
    topAutopsyCause && lastAutopsy
      ? lastAutopsy.surfaced_events.find((event) => event.cause_id === topAutopsyCause.id) ?? null
      : lastAutopsy?.surfaced_events?.[0] ?? null;

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  return (
    <div className={`wme-root${embedUI ? ' wme-root--embed' : ''}`}>

      {/* ================================================================== */}
      {/* Toolbar                                                             */}
      {/* ================================================================== */}
      {!embedUI && (
      <header className="wme-toolbar">
        <div className="wme-toolbar__brand">
          <svg width={14} height={14} viewBox="0 0 14 14" style={{ marginRight: 6, flexShrink: 0 }}>
            <circle cx={7} cy={7} r={6} fill="none" stroke="#d4a017" strokeWidth={1.2} />
            <line x1={7} y1={1} x2={7} y2={13} stroke="#d4a017" strokeWidth={1} />
            <line x1={1} y1={7} x2={13} y2={7} stroke="#d4a017" strokeWidth={1} />
          </svg>
          Aeloria World Map
        </div>

        {/* Zoom controls */}
        <div className="wme-toolbar__group">
          <button className="wme-toolbar__icon-btn" onClick={() => zoomBy(1.25)} title="Zoom in">+</button>
          <button className="wme-toolbar__zoom-pct" onClick={fitToScreen} title="Click to fit screen (F)">
            {Math.round(zoomDisplay * 100)}%
          </button>
          <button className="wme-toolbar__icon-btn" onClick={() => zoomBy(1 / 1.25)} title="Zoom out">−</button>
          <button className="wme-toolbar__btn" onClick={fitToScreen} title="Fit to screen (F)">⊙ Fit</button>
        </div>

        {/* Grid */}
        <div className="wme-toolbar__group">
          <button
            className={`wme-toolbar__btn${showGrid ? ' wme-toolbar__btn--active' : ''}`}
            onClick={() => setShowGrid((v) => !v)}
          >
            ⊞ Grid
          </button>
          {showGrid && (
            <select
              className="wme-toolbar__select"
              value={gridSizeIdx}
              onChange={(e) => setGridSizeIdx(Number(e.target.value))}
            >
              {GRID_SIZES.map((g, i) => <option key={g.label} value={i}>{g.label}</option>)}
            </select>
          )}
          {showGrid && (
            <button
              className={`wme-toolbar__btn${snapToGrid ? ' wme-toolbar__btn--active' : ''}`}
              onClick={() => setSnapToGrid((v) => !v)}
              title="Snap clicks to nearest grid cell center"
            >
              ⌖ Snap
            </button>
          )}
        </div>

        {/* Filters */}
        <div className="wme-toolbar__group">
          <select className="wme-toolbar__select" value={filterType} onChange={(e) => setFilterType(e.target.value)}>
            <option value="">All Types</option>
            {PIN_TYPES.map((pt) => <option key={pt.id} value={pt.id}>{pt.label}</option>)}
          </select>
          <select className="wme-toolbar__select" value={filterFaction} onChange={(e) => setFilterFaction(e.target.value)}>
            <option value="">All Factions</option>
            {FACTIONS.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
          </select>
        </div>

        <button
          className={`wme-toolbar__btn${showSidebar ? ' wme-toolbar__btn--active' : ''}`}
          onClick={() => setShowSidebar((v) => !v)}
        >
          ☰ {pins.length}
        </button>
      </header>
      )}

      {/* ================================================================== */}
      {/* Body                                                                */}
      {/* ================================================================== */}
      <div className="wme-body">

        {/* Map wrapper — overflow:hidden, captures all mouse events */}
        <div
          ref={wrapperRef}
          className="wme-wrapper"
          style={{
            cursor: embedUI
              ? (isDragging ? 'grabbing' : 'grab')
              : (isDragging ? 'grabbing' : 'crosshair'),
          }}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={() => {
            dragRef.current = null;
            setIsDragging(false);
            setCursorCell(null);
            setCursorPct(null);
          }}
          onDoubleClick={fitToScreen}
        >
          {loading && <div className="wme-status">Loading locations…</div>}
          {loadError && <div className="wme-status wme-status--error">{loadError}</div>}

          {/* Stage — natural image dimensions, scaled via CSS transform */}
          <div
            ref={stageRef}
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: imgSize?.w ?? 0,
              height: imgSize?.h ?? 0,
              transformOrigin: '0 0',
            }}
          >
            {/* Layer 1: map image */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              ref={imgRef}
              src={WORLD_MAP_IMAGE_SRC}
              alt="Aeloria world map"
              style={{ display: 'block', width: '100%', height: '100%', userSelect: 'none' }}
              draggable={false}
              onLoad={handleImageLoad}
              onError={() => {
                setLoadError(
                  `Map image failed to load (${WORLD_MAP_IMAGE_SRC}). Add the file under public/ or set NEXT_PUBLIC_WORLD_MAP_IMAGE.`,
                );
                setLoading(false);
                if (isEmbeddedInParent() && !embedReadyPostedRef.current) {
                  embedReadyPostedRef.current = true;
                  try {
                    window.parent.postMessage({ type: 'aeloria-home-map-ready' }, '*');
                  } catch {
                    /* ignore */
                  }
                }
              }}
            />

            {/* Layer 2: grid */}
            {showGrid && imgSize && (
              <GridOverlay
                cols={gridSize.cols}
                rows={gridSize.rows}
                imgW={imgSize.w}
                imgH={imgSize.h}
                zoom={zoomDisplay}
              />
            )}

            {/* Layer 3: house-seat → faction-capital connection lines */}
            {imgSize && (
              <svg
                style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'visible' }}
                width={imgSize.w}
                height={imgSize.h}
                aria-hidden="true"
              >
                {displayedPins
                  .filter((p) => p.type === 'house_seat')
                  .map((hPin) => {
                    // Draw lines to every faction_capital of the same faction
                    const capitals = pins.filter(
                      (p) => p.type === 'faction_capital' && p.faction === hPin.faction,
                    );
                    if (!capitals.length) return null;
                    const color = factionColor(hPin.faction);
                    const x1 = (hPin.x / 100) * imgSize.w;
                    const y1 = (hPin.y / 100) * imgSize.h;
                    return capitals.map((cap) => (
                      <line
                        key={`link-${hPin.id}-${cap.id}`}
                        x1={x1} y1={y1}
                        x2={(cap.x / 100) * imgSize.w}
                        y2={(cap.y / 100) * imgSize.h}
                        stroke={color}
                        strokeOpacity={0.28}
                        strokeWidth={0.8 / zoomDisplay}
                        strokeDasharray={`${5 / zoomDisplay},${4 / zoomDisplay}`}
                        strokeLinecap="round"
                      />
                    ));
                  })}
              </svg>
            )}

            {/* Layer 4: pins */}
            {imgSize && displayedPins.map((pin) => {
              const effectiveFaction = playbackMode
                ? getPlaybackFaction(pin)
                : (liveOwnership[pin.id] ?? pin.faction);
              return (
                <PinMarker
                  key={pin.id}
                  pin={pin}
                  left={(pin.x / 100) * imgSize.w}
                  top={(pin.y / 100) * imgSize.h}
                  color={factionColor(effectiveFaction)}
                  isNew={pin.id === flashPinId}
                  isHov={pin.id === hoveredPin}
                  hasConflict={!playbackMode && !!conflictEvents[pin.id]}
                  portrait={!playbackMode ? portraits[pin.id] : undefined}
                  pinPx={PIN_PX}
                  labelPx={LABEL_PX}
                  showPinLabels={showPinLabels}
                  zoomDisplay={zoomDisplay}
                  embedUI={embedUI}
                  onMouseEnter={handlePinMouseEnter}
                  onMouseLeave={handlePinMouseLeave}
                  onEdit={handleEdit}
                  onDelete={handleDelete}
                />
              );
            })}

            {/* Layer 5: Seer (live journey → map pin); hidden during history playback */}
            {imgSize && seerOnMap && !playbackMode && (
              <div
                className="wme-seer"
                style={{
                  position: 'absolute',
                  left: (seerOnMap.x / 100) * imgSize.w,
                  top: (seerOnMap.y / 100) * imgSize.h,
                  transform: 'translate(-50%, -100%)',
                  zIndex: 45,
                  pointerEvents: 'auto',
                }}
                onMouseEnter={(e) => {
                  const wr = wrapperRef.current?.getBoundingClientRect();
                  if (wr) setSeerTooltip({ px: e.clientX - wr.left, py: e.clientY - wr.top });
                }}
                onMouseLeave={() => setSeerTooltip(null)}
              >
                <div
                  className="wme-seer__icon"
                  style={{
                    filter: [
                      `drop-shadow(0 0 ${6 / zoomDisplay}px #c4b5fdcc)`,
                      `drop-shadow(0 0 ${14 / zoomDisplay}px #d4a01766)`,
                      `drop-shadow(0 ${2 / zoomDisplay}px ${5 / zoomDisplay}px rgba(0,0,0,0.95))`,
                    ].join(' '),
                  }}
                >
                  <SeerIcon px={SEER_PX} />
                </div>
                {showPinLabels && (
                  <span
                    className="wme-pin-label"
                    style={{
                      color: '#d4a017',
                      fontSize: LABEL_PX,
                      marginTop: 2 / zoomDisplay,
                      letterSpacing: `${0.06 / zoomDisplay}em`,
                      textShadow: [
                        `0 0 ${6 / zoomDisplay}px #c4b5fd99`,
                        `0 ${1 / zoomDisplay}px ${3 / zoomDisplay}px #000`,
                        `0 0 ${12 / zoomDisplay}px rgba(0,0,0,0.9)`,
                      ].join(', '),
                    }}
                  >
                    The Seer
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Tooltip — in wrapper space (not scaled by stage zoom) */}
          {tooltip && (() => {
            const { pin, px, py } = tooltip;
            const effFaction = playbackMode
              ? getPlaybackFaction(pin)
              : (liveOwnership[pin.id] ?? pin.faction);
            const color      = factionColor(effFaction);
            const typeLabel  = PIN_TYPES.find((t) => t.id === pin.type)?.label ?? pin.type;
            const facLabel   = effFaction ? (FACTION_MAP[effFaction]?.label ?? effFaction) : null;
            const houseLabel = pin.house ? (HOUSE_MAP[pin.house]?.label ?? pin.house) : null;
            const ce         = !playbackMode ? conflictEvents[pin.id] : undefined;
            return (
              <div
                className="wme-tooltip"
                style={{ left: px + 16, top: py - 12 }}
              >
                <div className="wme-tooltip__name">
                  <PinIcon type={pin.type} color={color} px={14} />
                  <strong>{pin.label}</strong>
                </div>
                <span className="wme-tooltip__type">{typeLabel}</span>
                {facLabel && <span className="wme-tooltip__faction" style={{ color }}>{facLabel}</span>}
                {houseLabel && <span className="wme-tooltip__faction" style={{ color, opacity: 0.75 }}>⬡ {houseLabel}</span>}
                {ce && (
                  <span className="wme-tooltip__conflict" style={{ color: '#f59e0b' }}>
                    ⚔ {String(ce.name)}
                  </span>
                )}
                {pin.notes && <span className="wme-tooltip__notes">{pin.notes}</span>}
                {!embedUI && (
                  <span className="wme-tooltip__hint">click to edit · right-click to delete</span>
                )}
              </div>
            );
          })()}

          {seerTooltip && seerOnMap && !playbackMode && (
            <div
              className="wme-tooltip"
              style={{ left: seerTooltip.px + 16, top: seerTooltip.py - 12 }}
            >
              <div className="wme-tooltip__name">
                <SeerIcon px={14} />
                <strong>The Seer</strong>
              </div>
              <span className="wme-tooltip__type">Map: {seerOnMap.matchedLabel}</span>
              {seerOnMap.location && (
                <span className="wme-tooltip__faction" style={{ color: '#c4b5fd' }}>
                  At: {seerOnMap.location}
                </span>
              )}
              {seerOnMap.destination && (
                <span className="wme-tooltip__notes">→ {seerOnMap.destination}</span>
              )}
              <span className="wme-tooltip__hint" style={{ textTransform: 'capitalize' }}>
                {seerOnMap.status}
              </span>
            </div>
          )}

          {!embedUI && (
            <>
              <div className="wme-compass-wrap">
                <CompassRose />
              </div>
              <div className="wme-vignette" aria-hidden="true" />
            </>
          )}
        </div>

        {/* Sidebar */}
        {showSidebar && !embedUI && (
          <Sidebar
            pins={pins}
            filterType={filterType}
            filterFaction={filterFaction}
            onFilterType={setFilterType}
            onFilterFaction={setFilterFaction}
            onEdit={handleEdit}
            onDelete={handleDelete}
            onHover={setHoveredPin}
            onClose={() => setShowSidebar(false)}
            factionPower={factionPower}
            liveOwnership={liveOwnership}
          />
        )}
      </div>

      {/* ================================================================== */}
      {/* Playback toolbar                                                    */}
      {/* ================================================================== */}
      {!embedUI && showPlayback && history.length > 0 && (
        <div className="wme-playback">
          <button
            className="wme-playback__btn"
            onClick={() => { setPlaybackMode(false); setIsPlaying(false); setSseStatus('connecting'); refreshMapState(); }}
            title="Return to live"
          >
            ⊙ LIVE
          </button>
          <button
            className="wme-playback__btn"
            onClick={() => setPlaybackTick((t) => Math.max(0, t - 1))}
            disabled={playbackTick === 0}
          >
            ‹
          </button>
          <button
            className="wme-playback__btn"
            onClick={() => { setPlaybackMode(true); setIsPlaying((v) => !v); }}
          >
            {isPlaying ? '⏸' : '▶'}
          </button>
          <button
            className="wme-playback__btn"
            onClick={() => setPlaybackTick((t) => Math.min(history.length - 1, t + 1))}
            disabled={playbackTick >= history.length - 1}
          >
            ›
          </button>
          <input
            type="range"
            className="wme-playback__scrubber"
            min={0}
            max={history.length - 1}
            value={playbackTick}
            onChange={(e) => { setPlaybackMode(true); setPlaybackTick(Number(e.target.value)); }}
          />
          <span className="wme-playback__label">
            {playbackMode
              ? `${history[playbackTick]?.worldDate ?? ''} (Tick ${history[playbackTick]?.tick ?? ''})`
              : 'Live'}
          </span>
        </div>
      )}

      {/* ================================================================== */}
      {/* Status bar                                                          */}
      {/* ================================================================== */}
      {!embedUI && (
      <footer className="wme-statusbar">
        <span className="wme-statusbar__item">
          <span className="wme-statusbar__dim">zoom</span> {Math.round(zoomDisplay * 100)}%
        </span>
        {cursorCell && (
          <span className="wme-statusbar__item">
            <span className="wme-statusbar__dim">cell</span>{' '}
            <strong style={{ color: '#d4a017' }}>{cursorCell}</strong>
          </span>
        )}
        {cursorPct && (
          <span className="wme-statusbar__item">
            <span className="wme-statusbar__dim">pos</span>{' '}
            {cursorPct.x.toFixed(1)}% × {cursorPct.y.toFixed(1)}%
          </span>
        )}
        {tickNumber != null && (
          <span className="wme-statusbar__item">
            <span className="wme-statusbar__dim">{playbackMode ? 'playback' : 'tick'}</span>{' '}
            <strong style={{ color: '#d4a017' }}>
              {playbackMode ? history[playbackTick]?.tick : tickNumber}
            </strong>
            {worldDate && !playbackMode && <span style={{ marginLeft: 4, color: '#6b7280' }}>{worldDate}</span>}
          </span>
        )}
        {clock && !playbackMode && (
          <span className="wme-statusbar__item wme-clock">
            <button
              type="button"
              className="wme-clock__btn wme-clock__btn--main"
              onClick={toggleClockPaused}
              disabled={clockBusy}
              title={clock.paused ? 'Resume Axiom clock' : 'Pause Axiom clock'}
            >
              {clock.paused ? 'Play' : 'Pause'}
            </button>
            {[1, 2, 3, 4, 5].map((speed) => (
              <button
                key={speed}
                type="button"
                className={`wme-clock__btn ${clock.speed === speed ? 'wme-clock__btn--active' : ''}`}
                onClick={() => setClockSpeed(speed)}
                disabled={clockBusy}
                title={`Set Axiom speed ${speed}`}
              >
                {speed}
              </button>
            ))}
            <button
              type="button"
              className="wme-clock__btn"
              onClick={stepClock}
              disabled={clockBusy || clock.is_processing}
              title="Run one Axiom tick"
            >
              Step
            </button>
            <span className="wme-clock__state">
              {clock.is_processing
                ? 'processing'
                : clock.paused
                  ? 'paused'
                  : `next ${clock.seconds_until_next_tick ?? 0}s`}
            </span>
          </span>
        )}
        {council && !playbackMode && (
          <span className="wme-statusbar__item wme-council-status">
            <button
              type="button"
              className={`wme-council-status__btn ${showCouncil ? 'wme-council-status__btn--active' : ''}`}
              onClick={() => setShowCouncil((v) => !v)}
              title={topCouncilRisk ? topCouncilRisk.summary : 'Open council report'}
            >
              Council
            </button>
            <span className="wme-council-status__risk">
              {topCouncilRisk ? `${topCouncilRisk.severity.toFixed(0)} ${topCouncilRisk.title}` : 'clear'}
            </span>
          </span>
        )}
        {explainability && !playbackMode && (
          <span className="wme-statusbar__item wme-council-status">
            <button
              type="button"
              className={`wme-council-status__btn ${showExplainability ? 'wme-council-status__btn--active' : ''}`}
              onClick={() => setShowExplainability((v) => !v)}
              title={topExplanation ? topExplanation.pipeline.outcome : 'Open causality inspector'}
            >
              Why
            </button>
            <span className="wme-council-status__risk">
              {topExplanation ? `${topExplanation.severity} ${topExplanation.domain}` : 'no causes'}
            </span>
          </span>
        )}
        {intel && !playbackMode && (
          <span className="wme-statusbar__item wme-council-status">
            <button
              type="button"
              className={`wme-council-status__btn ${showIntel ? 'wme-council-status__btn--active' : ''}`}
              onClick={() => setShowIntel((v) => !v)}
              title={topIntel ? topIntel.pressure_summary : 'Open faction intel'}
            >
              Intel
            </button>
            <span className="wme-council-status__risk">
              {topIntel ? `${topIntel.overall_pressure.toFixed(0)} ${topIntel.faction}` : 'quiet'}
            </span>
          </span>
        )}
        {lastAutopsy && !playbackMode && (
          <span className="wme-statusbar__item wme-council-status">
            <button
              type="button"
              className={`wme-council-status__btn ${showAutopsy ? 'wme-council-status__btn--active' : ''}`}
              onClick={() => setShowAutopsy((v) => !v)}
              title={topAutopsyCause ? topAutopsyCause.outcome : 'Open latest tick autopsy'}
            >
              Autopsy
            </button>
            <span className="wme-council-status__risk">
              {topAutopsyCause ? `${topAutopsyCause.severity} ${topAutopsyCause.decision}` : `tick ${lastAutopsy.tick}`}
            </span>
          </span>
        )}
        <span className="wme-statusbar__spacer" />
        <span className="wme-statusbar__item">
          {displayedPins.length !== pins.length
            ? `${displayedPins.length} / ${pins.length} locations`
            : `${pins.length} location${pins.length !== 1 ? 's' : ''}`}
        </span>
        {/* SSE status + playback toggle */}
        <span
          className={`wme-statusbar__item wme-statusbar__sse wme-statusbar__sse--${sseStatus}`}
          title={sseStatus === 'live' ? 'Connected to game engine' : sseStatus === 'offline' ? 'Game engine offline' : 'Connecting…'}
          onClick={() => setShowPlayback((v) => !v)}
          style={{ cursor: 'pointer' }}
        >
          {sseStatus === 'live'        ? '● LIVE'
           : sseStatus === 'offline'   ? '○ OFFLINE'
           : '◌ …'}
          {history.length > 0 && <span style={{ marginLeft: 6, color: '#3d4048' }}>⏮ History</span>}
        </span>
      </footer>
      )}

      {/* ================================================================== */}
      {/* Council / intel drawer                                              */}
      {/* ================================================================== */}
      {!embedUI && showCouncil && council && (
        <aside className="wme-council" aria-label="Council report">
          <div className="wme-council__header">
            <div>
              <div className="wme-council__kicker">Axiom Council</div>
              <strong>Tick {council.tick}</strong>
              {council.world_date && <span className="wme-council__date">{council.world_date}</span>}
            </div>
            <button className="wme-council__close" type="button" onClick={() => setShowCouncil(false)}>
              Close
            </button>
          </div>

          <div className="wme-council__section">
            <div className="wme-council__section-title">Top Risks</div>
            {council.top_risks.length ? council.top_risks.slice(0, 4).map((item, idx) => (
              <div className="wme-council__risk" key={`${item.title}-${idx}`}>
                <span className="wme-council__sev">{item.severity.toFixed(0)}</span>
                <div>
                  <strong>{item.title}</strong>
                  <p>{item.summary}</p>
                </div>
              </div>
            )) : (
              <div className="wme-council__empty">No urgent risks reported.</div>
            )}
          </div>

          {council.strategic_questions && council.strategic_questions.length > 0 && (
            <div className="wme-council__section">
              <div className="wme-council__section-title">Strategic Questions</div>
              {council.strategic_questions.slice(0, 3).map((item, idx) => (
                <div className="wme-council__question" key={`${item.title}-${idx}`}>
                  <strong>{item.title}</strong>
                  <p>{item.summary}</p>
                </div>
              ))}
            </div>
          )}

          <div className="wme-council__tabs">
            {advisorTabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                className={`wme-council__tab ${activeAdvisor === tab.id ? 'wme-council__tab--active' : ''}`}
                onClick={() => setActiveAdvisor(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {activeCouncilBriefing && (
            <div className={`wme-council__brief wme-council__brief--${activeCouncilBriefing.status}`}>
              <div>
                <span>{activeCouncilBriefing.status}</span>
                <strong>{activeCouncilBriefing.focus || activeAdvisor}</strong>
              </div>
              <p>{activeCouncilBriefing.summary}</p>
            </div>
          )}

          <div className="wme-council__section wme-council__scroll">
            {activeCouncilItems.length ? activeCouncilItems.map((item, idx) => (
              <div className="wme-council__item" key={`${activeAdvisor}-${item.title}-${idx}`}>
                <div className="wme-council__item-head">
                  <strong>{item.title}</strong>
                  <span>{item.severity.toFixed(1)}</span>
                </div>
                {item.faction && <div className="wme-council__meta">{item.faction}</div>}
                <p>{item.summary}</p>
                {item.source && <div className="wme-council__source">{item.source}</div>}
              </div>
            )) : (
              <div className="wme-council__empty">No active notes for this advisor.</div>
            )}
          </div>

          {council.watchlist.length > 0 && (
            <div className="wme-council__section">
              <div className="wme-council__section-title">Watchlist</div>
              <div className="wme-council__watchlist">
                {council.watchlist.slice(0, 5).map((item) => (
                  <div className="wme-council__watch" key={item.faction}>
                    <strong>{item.faction}</strong>
                    <span>{item.overall.toFixed(1)} / {item.dominant_pressure}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </aside>
      )}

      {!embedUI && showExplainability && explainability && (
        <aside className="wme-council wme-why" aria-label="Causality inspector">
          <div className="wme-council__header">
            <div>
              <div className="wme-council__kicker">Axiom Why</div>
              <strong>Tick {explainability.tick}</strong>
              {explainability.world_date && <span className="wme-council__date">{explainability.world_date}</span>}
            </div>
            <button className="wme-council__close" type="button" onClick={() => setShowExplainability(false)}>
              Close
            </button>
          </div>

          <div className="wme-council__section">
            <div className="wme-council__section-title">Cause Domains</div>
            <div className="wme-why__domains">
              {explanationDomains.length ? explanationDomains.map(([domain, count]) => (
                <span className="wme-why__chip" key={domain}>{domain} {count}</span>
              )) : (
                <span className="wme-why__chip">no records</span>
              )}
            </div>
          </div>

          <div className="wme-council__section wme-council__scroll">
            {explainability.explanations.length ? explainability.explanations.map((item) => (
              <button
                type="button"
                className={`wme-why__cause ${selectedCause?.id === item.id ? 'wme-why__cause--active' : ''}`}
                key={item.id}
                onClick={() => setSelectedCauseId(item.id)}
              >
                <span className="wme-council__sev">{item.severity}</span>
                <span>
                  <strong>{item.actor}</strong>
                  <small>{item.domain} / {item.public_status}</small>
                  <span>{item.pipeline.decision}</span>
                </span>
              </button>
            )) : (
              <div className="wme-council__empty">No cause records for this tick.</div>
            )}
          </div>

          {selectedCause && (
            <div className="wme-council__section wme-why__detail">
              <div className="wme-council__section-title">Pipeline</div>
              <div className="wme-why__row"><span>Pressure</span><p>{selectedCause.pipeline.pressure || 'Unspecified'}</p></div>
              <div className="wme-why__row"><span>Belief</span><p>{selectedCause.pipeline.belief || 'No dominant belief recorded'}</p></div>
              <div className="wme-why__row"><span>Decision</span><p>{selectedCause.pipeline.decision || 'No decision label'}</p></div>
              <div className="wme-why__row"><span>Outcome</span><p>{selectedCause.pipeline.outcome || 'No outcome text'}</p></div>
              {selectedCause.pipeline.hidden_outcome && (
                <div className="wme-why__row"><span>Hidden</span><p>{selectedCause.pipeline.hidden_outcome}</p></div>
              )}
              <div className="wme-why__row">
                <span>Knowledge</span>
                <p>
                  Known {selectedCause.knowledge_spread.known_by.length} /
                  Rumored {selectedCause.knowledge_spread.rumored_by.length} /
                  Suspected {selectedCause.knowledge_spread.suspected_by.length}
                </p>
              </div>
              {selectedCause.affected.length > 0 && (
                <div className="wme-why__affected">
                  {selectedCause.affected.slice(0, 6).map((name) => <span key={name}>{name}</span>)}
                </div>
              )}
            </div>
          )}
        </aside>
      )}

      {!embedUI && showIntel && intel && (
        <aside className="wme-council wme-intel" aria-label="Faction intel inspector">
          <div className="wme-council__header">
            <div>
              <div className="wme-council__kicker">Faction Intel</div>
              <strong>Tick {intel.tick}</strong>
              {intel.world_date && <span className="wme-council__date">{intel.world_date}</span>}
            </div>
            <button className="wme-council__close" type="button" onClick={() => setShowIntel(false)}>
              Close
            </button>
          </div>

          <div className="wme-council__section wme-intel__factions">
            {intel.factions.length ? intel.factions.map((row) => (
              <button
                type="button"
                key={row.faction}
                className={`wme-intel__faction ${selectedIntel?.faction === row.faction ? 'wme-intel__faction--active' : ''}`}
                onClick={() => setSelectedIntelFaction(row.faction)}
              >
                <strong>{row.faction}</strong>
                <span>{row.overall_pressure.toFixed(1)} / {row.dominant_pressure}</span>
              </button>
            )) : (
              <div className="wme-council__empty">No faction intel available.</div>
            )}
          </div>

          {selectedIntel && (
            <div className="wme-council__section wme-council__scroll">
              <div className="wme-intel__hero">
                <strong>{selectedIntel.faction}</strong>
                <span>{selectedIntel.pressure_summary || 'No dominant pressure recorded'}</span>
              </div>

              <div className="wme-council__section-title">Pressure</div>
              {selectedIntel.pressure_domains.slice(0, 4).map((domain) => (
                <div className="wme-intel__domain" key={domain.domain}>
                  <div><strong>{domain.domain}</strong><span>{domain.score.toFixed(1)}</span></div>
                  {domain.reasons.length > 0 && <p>{domain.reasons.join(', ')}</p>}
                </div>
              ))}

              <div className="wme-council__section-title">Dominant Belief</div>
              <div className="wme-intel__belief">
                {selectedIntel.dominant_belief_summary || 'No belief has risen above the noise.'}
              </div>

              <div className="wme-council__section-title">Beliefs</div>
              {selectedIntel.beliefs.length ? selectedIntel.beliefs.slice(0, 5).map((belief, idx) => (
                <div className="wme-intel__belief" key={belief.id || `${belief.claim}-${idx}`}>
                  <span>{belief.source} {belief.confidence.toFixed(2)} / {belief.bias}</span>
                  <p>{belief.claim}</p>
                </div>
              )) : (
                <div className="wme-council__empty">No current beliefs recorded.</div>
              )}

              <div className="wme-council__section-title">Knowledge</div>
              {([
                ['known_facts', 'Known'],
                ['suspicions', 'Suspicions'],
                ['rumors', 'Rumors'],
                ['false_beliefs', 'False Beliefs'],
                ['blind_spots', 'Blind Spots'],
              ] as const).map(([key, label]) => {
                const values = selectedIntel.knowledge[key] ?? [];
                return (
                  <div className="wme-intel__knowledge" key={key}>
                    <strong>{label} <span>{selectedIntel.knowledge_counts[key] ?? values.length}</span></strong>
                    {values.length ? values.slice(0, 4).map((text) => <p key={text}>{text}</p>) : <p>None recorded.</p>}
                  </div>
                );
              })}
            </div>
          )}
        </aside>
      )}

      {!embedUI && showAutopsy && lastAutopsy && (
        <aside className="wme-council wme-autopsy" aria-label="Latest tick autopsy">
          <div className="wme-council__header">
            <div>
              <div className="wme-council__kicker">Axiom Autopsy</div>
              <strong>Tick {lastAutopsy.tick}</strong>
              {lastAutopsy.world_date && <span className="wme-council__date">{lastAutopsy.world_date}</span>}
            </div>
            <button className="wme-council__close" type="button" onClick={() => setShowAutopsy(false)}>
              Close
            </button>
          </div>

          <div className="wme-council__section">
            <div className="wme-council__section-title">Primary Chain</div>
            <div className="wme-autopsy__chain">
              <div className="wme-autopsy__node">
                <span>Pressure</span>
                <strong>{topAutopsyPressure?.faction ?? topAutopsyCause?.actor ?? 'No pressure'}</strong>
                <p>{topAutopsyPressure?.summary ?? topAutopsyCause?.pressure ?? 'No pressure recorded.'}</p>
              </div>
              <div className="wme-autopsy__node">
                <span>Belief</span>
                <strong>{topAutopsyBelief?.subject ?? topAutopsyCause?.actor ?? 'No belief'}</strong>
                <p>{topAutopsyBelief?.claim ?? topAutopsyCause?.belief ?? 'No belief recorded.'}</p>
              </div>
              <div className="wme-autopsy__node">
                <span>Decision</span>
                <strong>{topAutopsyCause?.actor ?? 'No actor'}</strong>
                <p>{topAutopsyCause?.decision ?? 'No decision recorded.'}</p>
              </div>
              <div className="wme-autopsy__node">
                <span>Outcome</span>
                <strong>{topAutopsyCause?.domain ?? 'No domain'}</strong>
                <p>{topAutopsyCause?.outcome ?? 'No outcome recorded.'}</p>
              </div>
              <div className="wme-autopsy__node">
                <span>Surfaced</span>
                <strong>{topAutopsySurface?.surface ?? 'Not surfaced'}</strong>
                <p>{topAutopsySurface?.summary ?? topAutopsySurface?.text ?? topAutopsySurface?.action ?? 'No surfaced event matched this cause.'}</p>
              </div>
            </div>
          </div>

          <div className="wme-council__section wme-autopsy__metrics">
            <div className="wme-autopsy__metric">
              <strong>{lastAutopsy.pressures.length}</strong>
              <span>pressures</span>
            </div>
            <div className="wme-autopsy__metric">
              <strong>{lastAutopsy.beliefs.length}</strong>
              <span>belief states</span>
            </div>
            <div className="wme-autopsy__metric">
              <strong>{lastAutopsy.decisions.length}</strong>
              <span>decisions</span>
            </div>
            <div className="wme-autopsy__metric">
              <strong>{lastAutopsy.causality_records.length}</strong>
              <span>causes</span>
            </div>
          </div>

          <div className="wme-council__section wme-council__scroll">
            <div className="wme-council__section-title">Causality Records</div>
            {lastAutopsy.causality_records.length ? lastAutopsy.causality_records.slice(0, 8).map((cause) => {
              const update = lastAutopsy.knowledge_updates.find((row) => row.cause_id === cause.id);
              const surfaced = lastAutopsy.surfaced_events.find((event) => event.cause_id === cause.id);
              return (
                <div className="wme-autopsy__record" key={cause.id}>
                  <div className="wme-council__item-head">
                    <strong>{cause.actor}</strong>
                    <span>{cause.severity}</span>
                  </div>
                  <div className="wme-council__meta">{cause.domain} / {cause.decision} / {cause.id}</div>
                  <p>{cause.outcome}</p>
                  {cause.belief && <p><span>Belief:</span> {cause.belief}</p>}
                  {update && (
                    <div className="wme-autopsy__spread">
                      <span>known {update.spread.known_by.length}</span>
                      <span>rumored {update.spread.rumored_by.length}</span>
                      <span>suspected {update.spread.suspected_by.length}</span>
                    </div>
                  )}
                  {surfaced && <div className="wme-council__source">surfaced as {surfaced.surface}</div>}
                </div>
              );
            }) : (
              <div className="wme-council__empty">No causality records in the latest tick.</div>
            )}
          </div>
        </aside>
      )}

      {/* ================================================================== */}
      {/* Event dispatch toasts                                               */}
      {/* ================================================================== */}
      {!embedUI && (
      <div className="wme-toasts">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className="wme-toast"
            style={{ borderColor: toast.color }}
            onClick={() => setToasts((prev) => prev.filter((t) => t.id !== toast.id))}
          >
            <div className="wme-toast__header" style={{ color: toast.color }}>
              {toast.header}
            </div>
            <div className="wme-toast__body">{toast.body}</div>
            <div className="wme-toast__dismiss">click to dismiss</div>
          </div>
        ))}
      </div>
      )}

      {/* ================================================================== */}
      {/* PlaceModal                                                          */}
      {/* ================================================================== */}
      {pendingClick && !embedUI && (
        <PlaceModal
          x={pendingClick.x}
          y={pendingClick.y}
          gridLabel={pendingCellLabel}
          editing={editingPin}
          onSave={handleSave}
          onCancel={() => { setPendingClick(null); setEditingPin(null); }}
        />
      )}

      {/* ================================================================== */}
      {/* Styles                                                              */}
      {/* ================================================================== */}
      <style>{`
        /* ---------- root ---------- */
        .wme-root {
          display: flex;
          flex-direction: column;
          height: 100vh;
          background: #07090e;
          color: #ddd8cc;
          font-family: 'Georgia', serif;
          overflow: hidden;
        }
        .wme-root--embed {
          height: 100%;
          min-height: 100vh;
        }
        .wme-root--embed .wme-body {
          flex: 1;
          min-height: 0;
        }

        /* ---------- toolbar ---------- */
        .wme-toolbar {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 7px 14px;
          background: linear-gradient(180deg, #1a1830 0%, #11131c 100%);
          border-bottom: 1px solid #2d2a40;
          flex-shrink: 0;
          flex-wrap: wrap;
          box-shadow: 0 2px 12px rgba(0,0,0,0.5);
          z-index: 40;
          position: relative;
        }
        .wme-toolbar__brand {
          display: flex;
          align-items: center;
          font-size: 0.92rem;
          font-weight: bold;
          letter-spacing: 0.07em;
          color: #d4a017;
          text-shadow: 0 0 12px rgba(212,160,23,0.4);
          margin-right: 6px;
          white-space: nowrap;
        }
        .wme-toolbar__group {
          display: flex;
          align-items: center;
          gap: 5px;
        }
        .wme-toolbar__btn {
          padding: 4px 10px;
          background: #1e1f2e;
          border: 1px solid #35324a;
          border-radius: 4px;
          color: #b8b4c8;
          cursor: pointer;
          font-size: 0.78rem;
          font-family: inherit;
          letter-spacing: 0.03em;
          transition: background 0.15s, color 0.15s, border-color 0.15s;
          white-space: nowrap;
        }
        .wme-toolbar__btn:hover { background: #282840; color: #fff; border-color: #5a4d7a; }
        .wme-toolbar__btn--active {
          background: #2e1f5e;
          border-color: #7c3aed;
          color: #c4b5fd;
        }
        .wme-toolbar__icon-btn {
          width: 26px;
          height: 26px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: #1e1f2e;
          border: 1px solid #35324a;
          border-radius: 4px;
          color: #b8b4c8;
          cursor: pointer;
          font-size: 1rem;
          font-family: inherit;
          transition: background 0.15s, color 0.15s;
        }
        .wme-toolbar__icon-btn:hover { background: #282840; color: #fff; }
        .wme-toolbar__zoom-pct {
          min-width: 44px;
          padding: 4px 6px;
          background: #0f1018;
          border: 1px solid #2d2a40;
          border-radius: 4px;
          color: #9ca3af;
          cursor: pointer;
          font-size: 0.75rem;
          font-family: 'Courier New', monospace;
          text-align: center;
          transition: color 0.1s;
        }
        .wme-toolbar__zoom-pct:hover { color: #d4a017; }
        .wme-toolbar__select {
          padding: 4px 7px;
          background: #1e1f2e;
          border: 1px solid #35324a;
          border-radius: 4px;
          color: #b8b4c8;
          font-size: 0.78rem;
          font-family: inherit;
          cursor: pointer;
          appearance: auto;
        }
        .wme-toolbar__select:focus { outline: none; border-color: #7c3aed; }

        /* ---------- body ---------- */
        .wme-body {
          display: flex;
          flex: 1;
          overflow: hidden;
        }

        /* ---------- wrapper ---------- */
        .wme-wrapper {
          flex: 1;
          overflow: hidden;
          position: relative;
          background: #07090e;
        }

        /* ---------- grid SVG (inside stage) ---------- */
        .wme-grid {
          display: block;
          pointer-events: none;
        }

        /* ---------- pin ---------- */
        .wme-pin {
          display: flex;
          flex-direction: column;
          align-items: center;
          pointer-events: auto;
        }
        .wme-pin--new {
          animation: wme-pop 0.35s cubic-bezier(0.17, 0.89, 0.32, 1.28) both;
        }
        @keyframes wme-pop {
          from { transform: translate(-50%, -100%) scale(0.2); opacity: 0; }
          to   { transform: translate(-50%, -100%) scale(1);   opacity: 1; }
        }
        /* Hovered pin: parent div gets brightness boost — amplifies the inline glow too */
        .wme-pin--hov { filter: brightness(1.4) saturate(1.2); }
        .wme-pin-btn {
          background: none;
          border: none;
          padding: 0;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          /* No static shadow here — each pin gets a faction-colored drop-shadow inline */
          transition: transform 0.14s cubic-bezier(0.34,1.56,0.64,1), filter 0.14s;
        }
        .wme-pin-btn:hover {
          transform: scale(1.4) translateY(-2px);
        }
        .wme-pin-label {
          display: block;
          font-weight: bold;
          font-family: 'Georgia', serif;
          text-transform: uppercase;
          white-space: nowrap;
          pointer-events: none;
          line-height: 1;
          /* color, fontSize, textShadow, letterSpacing set inline per-pin */
        }

        /* ---------- Seer (live position) ---------- */
        .wme-seer {
          display: flex;
          flex-direction: column;
          align-items: center;
        }
        .wme-seer__icon {
          animation: wme-seer-pulse 2.4s ease-in-out infinite;
        }
        @keyframes wme-seer-pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.92; transform: scale(1.04); }
        }

        /* ---------- tooltip ---------- */
        .wme-tooltip {
          position: absolute;
          background: rgba(10, 10, 20, 0.95);
          border: 1px solid #3a3548;
          border-radius: 7px;
          padding: 9px 13px;
          display: flex;
          flex-direction: column;
          gap: 4px;
          font-size: 0.8rem;
          pointer-events: none;
          z-index: 60;
          max-width: 230px;
          backdrop-filter: blur(6px);
          box-shadow: 0 8px 24px rgba(0,0,0,0.6);
        }
        .wme-tooltip__name {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.9rem;
        }
        .wme-tooltip__name strong { color: #f0ece0; }
        .wme-tooltip__type  { color: #9ca3af; font-size: 0.75rem; }
        .wme-tooltip__faction { font-size: 0.77rem; }
        .wme-tooltip__notes { color: #6b7280; font-style: italic; font-size: 0.75rem; }
        .wme-tooltip__hint  { color: #3d4048; font-size: 0.7rem; margin-top: 2px; }

        /* ---------- compass ---------- */
        .wme-compass-wrap {
          position: absolute;
          bottom: 16px;
          right: 16px;
          pointer-events: none;
          opacity: 0.85;
          z-index: 20;
          filter: drop-shadow(0 2px 8px rgba(0,0,0,0.7));
        }

        /* ---------- vignette ---------- */
        .wme-vignette {
          position: absolute;
          inset: 0;
          pointer-events: none;
          box-shadow: inset 0 0 80px rgba(0,0,0,0.45);
          z-index: 5;
        }

        /* ---------- status ---------- */
        .wme-status {
          position: absolute;
          top: 50%;
          left: 50%;
          transform: translate(-50%, -50%);
          color: #6b7280;
          font-size: 0.88rem;
          z-index: 10;
        }
        .wme-status--error { color: #ef4444; }

        /* ---------- status bar ---------- */
        .wme-statusbar {
          display: flex;
          align-items: center;
          gap: 0;
          padding: 4px 14px;
          background: #0d0f1a;
          border-top: 1px solid #1e2030;
          font-size: 0.72rem;
          color: #6b7280;
          flex-shrink: 0;
          font-family: 'Courier New', monospace;
          user-select: none;
        }
        .wme-statusbar__item {
          padding: 0 10px;
          border-right: 1px solid #1e2030;
          white-space: nowrap;
        }
        .wme-statusbar__item:first-child { padding-left: 0; }
        .wme-statusbar__item:last-child  { border-right: none; }
        .wme-statusbar__dim  { color: #3d4048; margin-right: 4px; }
        .wme-statusbar__spacer { flex: 1; }
        .wme-clock {
          display: inline-flex;
          align-items: center;
          gap: 4px;
        }
        .wme-clock__btn {
          height: 22px;
          min-width: 22px;
          padding: 0 6px;
          border: 1px solid #292d3f;
          border-radius: 4px;
          background: #141722;
          color: #8d94a8;
          font-size: 0.66rem;
          font-family: inherit;
          cursor: pointer;
          line-height: 1;
        }
        .wme-clock__btn:hover:not(:disabled) {
          border-color: #d4a017;
          color: #f5d36d;
        }
        .wme-clock__btn:disabled {
          opacity: 0.45;
          cursor: default;
        }
        .wme-clock__btn--main {
          min-width: 48px;
          color: #d4a017;
        }
        .wme-clock__btn--active {
          background: #2c2414;
          border-color: #d4a017;
          color: #f5d36d;
        }
        .wme-clock__state {
          margin-left: 4px;
          color: #6b7280;
        }
        .wme-council-status {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          max-width: 360px;
        }
        .wme-council-status__btn {
          height: 22px;
          padding: 0 8px;
          border: 1px solid #292d3f;
          border-radius: 4px;
          background: #141722;
          color: #d4a017;
          font-size: 0.66rem;
          font-family: inherit;
          cursor: pointer;
        }
        .wme-council-status__btn:hover,
        .wme-council-status__btn--active {
          border-color: #d4a017;
          background: #2c2414;
          color: #f5d36d;
        }
        .wme-council-status__risk {
          overflow: hidden;
          text-overflow: ellipsis;
          color: #7f8796;
        }

        /* ---------- council drawer ---------- */
        .wme-council {
          position: fixed;
          right: 14px;
          top: 62px;
          bottom: 42px;
          width: min(420px, calc(100vw - 28px));
          z-index: 90;
          display: flex;
          flex-direction: column;
          gap: 10px;
          padding: 12px;
          background: rgba(10, 12, 20, 0.96);
          border: 1px solid #292d3f;
          box-shadow: 0 18px 40px rgba(0,0,0,0.45);
          color: #c8ccd6;
          font-size: 0.78rem;
          font-family: 'Courier New', monospace;
        }
        .wme-council__header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 12px;
          padding-bottom: 8px;
          border-bottom: 1px solid #1f2334;
        }
        .wme-council__kicker {
          color: #d4a017;
          font-size: 0.66rem;
          text-transform: uppercase;
          letter-spacing: 0.08em;
        }
        .wme-council__date {
          margin-left: 8px;
          color: #6b7280;
        }
        .wme-council__close,
        .wme-council__tab {
          border: 1px solid #292d3f;
          border-radius: 4px;
          background: #141722;
          color: #9ca3af;
          font-family: inherit;
          font-size: 0.7rem;
          cursor: pointer;
        }
        .wme-council__close {
          padding: 4px 8px;
        }
        .wme-council__close:hover,
        .wme-council__tab:hover,
        .wme-council__tab--active {
          border-color: #d4a017;
          color: #f5d36d;
        }
        .wme-council__tabs {
          display: grid;
          grid-template-columns: repeat(5, minmax(0, 1fr));
          gap: 4px;
        }
        .wme-council__tab {
          min-width: 0;
          padding: 5px 3px;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .wme-council__section {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .wme-council__section-title {
          color: #6b7280;
          font-size: 0.68rem;
          text-transform: uppercase;
          letter-spacing: 0.08em;
        }
        .wme-council__scroll {
          min-height: 0;
          overflow-y: auto;
          padding-right: 2px;
        }
        .wme-council__risk,
        .wme-council__item,
        .wme-council__watch,
        .wme-council__question,
        .wme-council__brief {
          border: 1px solid #1f2334;
          background: #0f1320;
          border-radius: 6px;
        }
        .wme-council__risk {
          display: grid;
          grid-template-columns: 30px minmax(0, 1fr);
          gap: 8px;
          padding: 8px;
        }
        .wme-council__sev {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 26px;
          height: 26px;
          border-radius: 50%;
          background: #2c2414;
          color: #f5d36d;
          font-weight: bold;
        }
        .wme-council__risk strong,
        .wme-council__item strong,
        .wme-council__watch strong,
        .wme-council__question strong,
        .wme-council__brief strong {
          color: #e5e7eb;
        }
        .wme-council__risk p,
        .wme-council__item p,
        .wme-council__question p,
        .wme-council__brief p {
          margin: 4px 0 0;
          color: #9ca3af;
          line-height: 1.35;
          white-space: normal;
        }
        .wme-council__item {
          padding: 8px;
        }
        .wme-council__item-head,
        .wme-council__watch {
          display: flex;
          justify-content: space-between;
          gap: 8px;
        }
        .wme-council__item-head span {
          color: #d4a017;
        }
        .wme-council__meta,
        .wme-council__source {
          margin-top: 4px;
          color: #6b7280;
          font-size: 0.68rem;
        }
        .wme-council__empty {
          padding: 10px;
          border: 1px dashed #292d3f;
          color: #6b7280;
        }
        .wme-council__watchlist {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .wme-council__watch {
          padding: 6px 8px;
          color: #7f8796;
        }
        .wme-council__question,
        .wme-council__brief {
          padding: 8px;
        }
        .wme-council__brief {
          border-color: #292d3f;
        }
        .wme-council__brief--watch {
          border-color: #7c5f1d;
          background: #17140e;
        }
        .wme-council__brief--critical {
          border-color: #7f1d1d;
          background: #1a1012;
        }
        .wme-council__brief div {
          display: flex;
          justify-content: space-between;
          gap: 8px;
        }
        .wme-council__brief span {
          color: #d4a017;
          text-transform: uppercase;
          font-size: 0.66rem;
          letter-spacing: 0.08em;
        }
        .wme-why {
          right: auto;
          left: 14px;
        }
        .wme-why__domains,
        .wme-why__affected {
          display: flex;
          flex-wrap: wrap;
          gap: 4px;
        }
        .wme-why__chip,
        .wme-why__affected span {
          display: inline-flex;
          align-items: center;
          min-height: 20px;
          padding: 2px 6px;
          border: 1px solid #292d3f;
          border-radius: 4px;
          background: #111827;
          color: #9ca3af;
          font-size: 0.66rem;
        }
        .wme-why__cause {
          display: grid;
          grid-template-columns: 30px minmax(0, 1fr);
          gap: 8px;
          width: 100%;
          padding: 8px;
          border: 1px solid #1f2334;
          border-radius: 6px;
          background: #0f1320;
          color: #c8ccd6;
          font-family: inherit;
          text-align: left;
          cursor: pointer;
        }
        .wme-why__cause:hover,
        .wme-why__cause--active {
          border-color: #d4a017;
          background: #151723;
        }
        .wme-why__cause strong,
        .wme-why__cause small,
        .wme-why__cause span span {
          display: block;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .wme-why__cause strong {
          color: #e5e7eb;
        }
        .wme-why__cause small {
          margin: 2px 0;
          color: #6b7280;
          font-size: 0.66rem;
        }
        .wme-why__detail {
          max-height: 46%;
          overflow-y: auto;
          padding-top: 8px;
          border-top: 1px solid #1f2334;
        }
        .wme-why__row {
          border: 1px solid #1f2334;
          border-radius: 6px;
          padding: 7px;
          background: #0f1320;
        }
        .wme-why__row span {
          display: block;
          margin-bottom: 3px;
          color: #d4a017;
          font-size: 0.66rem;
          text-transform: uppercase;
          letter-spacing: 0.07em;
        }
        .wme-why__row p {
          margin: 0;
          color: #aeb4c0;
          line-height: 1.35;
          white-space: normal;
        }
        @media (max-width: 900px) {
          .wme-why {
            left: 14px;
            right: 14px;
            width: auto;
          }
        }
        .wme-intel {
          right: 14px;
          left: auto;
        }
        .wme-intel__factions {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 5px;
        }
        .wme-intel__faction {
          min-width: 0;
          padding: 7px;
          border: 1px solid #1f2334;
          border-radius: 6px;
          background: #0f1320;
          color: #9ca3af;
          font-family: inherit;
          text-align: left;
          cursor: pointer;
        }
        .wme-intel__faction:hover,
        .wme-intel__faction--active {
          border-color: #d4a017;
          color: #f5d36d;
          background: #151723;
        }
        .wme-intel__faction strong,
        .wme-intel__faction span {
          display: block;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .wme-intel__faction span {
          margin-top: 3px;
          color: #6b7280;
          font-size: 0.66rem;
        }
        .wme-intel__hero,
        .wme-intel__domain,
        .wme-intel__belief,
        .wme-intel__knowledge {
          border: 1px solid #1f2334;
          border-radius: 6px;
          background: #0f1320;
          padding: 8px;
        }
        .wme-intel__hero strong {
          display: block;
          color: #e5e7eb;
        }
        .wme-intel__hero span {
          display: block;
          margin-top: 4px;
          color: #9ca3af;
          white-space: normal;
        }
        .wme-intel__domain div,
        .wme-intel__knowledge strong {
          display: flex;
          justify-content: space-between;
          gap: 8px;
          color: #e5e7eb;
        }
        .wme-intel__domain span,
        .wme-intel__knowledge span,
        .wme-intel__belief span {
          color: #d4a017;
        }
        .wme-intel__domain p,
        .wme-intel__belief p,
        .wme-intel__knowledge p {
          margin: 5px 0 0;
          color: #aeb4c0;
          line-height: 1.35;
          white-space: normal;
        }
        .wme-intel__belief {
          color: #aeb4c0;
          white-space: normal;
        }
        @media (max-width: 900px) {
          .wme-intel {
            left: 14px;
            right: 14px;
            width: auto;
          }
          .wme-intel__factions {
            grid-template-columns: 1fr;
          }
        }
        .wme-autopsy {
          left: 50%;
          right: auto;
          transform: translateX(-50%);
          width: min(520px, calc(100vw - 28px));
        }
        .wme-autopsy__chain {
          display: grid;
          grid-template-columns: 1fr;
          gap: 6px;
        }
        .wme-autopsy__node,
        .wme-autopsy__record,
        .wme-autopsy__metric {
          border: 1px solid #1f2334;
          border-radius: 6px;
          background: #0f1320;
        }
        .wme-autopsy__node {
          padding: 8px;
        }
        .wme-autopsy__node span,
        .wme-autopsy__record p span {
          display: block;
          margin-bottom: 3px;
          color: #d4a017;
          font-size: 0.66rem;
          text-transform: uppercase;
          letter-spacing: 0.07em;
        }
        .wme-autopsy__node strong {
          display: block;
          color: #e5e7eb;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .wme-autopsy__node p,
        .wme-autopsy__record p {
          margin: 4px 0 0;
          color: #aeb4c0;
          line-height: 1.35;
          white-space: normal;
        }
        .wme-autopsy__metrics {
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 6px;
        }
        .wme-autopsy__metric {
          min-width: 0;
          padding: 8px 6px;
          text-align: center;
        }
        .wme-autopsy__metric strong,
        .wme-autopsy__metric span {
          display: block;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .wme-autopsy__metric strong {
          color: #f5d36d;
          font-size: 1rem;
        }
        .wme-autopsy__metric span {
          margin-top: 3px;
          color: #6b7280;
          font-size: 0.65rem;
        }
        .wme-autopsy__record {
          padding: 8px;
        }
        .wme-autopsy__spread {
          display: flex;
          flex-wrap: wrap;
          gap: 4px;
          margin-top: 6px;
        }
        .wme-autopsy__spread span {
          display: inline-flex;
          align-items: center;
          min-height: 20px;
          padding: 2px 6px;
          border: 1px solid #292d3f;
          border-radius: 4px;
          background: #111827;
          color: #9ca3af;
          font-size: 0.66rem;
        }
        @media (max-width: 900px) {
          .wme-autopsy {
            left: 14px;
            right: 14px;
            transform: none;
            width: auto;
          }
          .wme-autopsy__metrics {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
        }

        /* ---------- modal backdrop ---------- */
        .wme-modal-backdrop {
          position: fixed;
          inset: 0;
          background: rgba(0,0,0,0.65);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 100;
          backdrop-filter: blur(3px);
        }
        .wme-modal {
          background: linear-gradient(160deg, #181628 0%, #101018 100%);
          border: 1px solid #3a3448;
          border-radius: 12px;
          padding: 24px 28px;
          width: 100%;
          max-width: 440px;
          box-shadow: 0 24px 64px rgba(0,0,0,0.75), inset 0 1px 0 rgba(255,255,255,0.05);
        }
        .wme-modal__header {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-bottom: 4px;
        }
        .wme-modal__header-icon { display: flex; align-items: center; }
        .wme-modal__title {
          flex: 1;
          font-size: 1.05rem;
          font-weight: bold;
          margin: 0;
          color: #d4a017;
        }
        .wme-modal__x {
          background: none;
          border: none;
          color: #4b5563;
          cursor: pointer;
          font-size: 1rem;
          padding: 0 2px;
          line-height: 1;
        }
        .wme-modal__x:hover { color: #9ca3af; }
        .wme-modal__coords {
          font-size: 0.72rem;
          color: #4b5563;
          margin: 0 0 16px;
          font-family: 'Courier New', monospace;
        }
        .wme-modal__form {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .wme-modal__row {
          display: flex;
          gap: 10px;
        }
        .wme-modal__label {
          display: flex;
          flex-direction: column;
          gap: 5px;
          font-size: 0.78rem;
          color: #7c8090;
          letter-spacing: 0.04em;
        }
        .wme-modal__opt { color: #3d4048; }
        .wme-modal__input,
        .wme-modal__select,
        .wme-modal__textarea {
          background: #0d0f1a;
          border: 1px solid #2d2a40;
          border-radius: 5px;
          color: #ddd8cc;
          padding: 7px 10px;
          font-size: 0.86rem;
          font-family: inherit;
          width: 100%;
          box-sizing: border-box;
          transition: border-color 0.15s, box-shadow 0.15s;
        }
        .wme-modal__input:focus,
        .wme-modal__select:focus,
        .wme-modal__textarea:focus {
          outline: none;
          border-color: #7c3aed;
          box-shadow: 0 0 0 2px rgba(124,58,237,0.15);
        }
        .wme-modal__textarea { resize: vertical; }
        .wme-modal__actions {
          display: flex;
          align-items: center;
          justify-content: flex-end;
          gap: 8px;
          margin-top: 4px;
        }
        .wme-modal__hint { color: #2d2a40; font-size: 0.7rem; margin-right: auto; font-family: monospace; }
        .wme-modal__btn {
          padding: 7px 18px;
          border-radius: 5px;
          border: 1px solid transparent;
          cursor: pointer;
          font-size: 0.82rem;
          font-family: inherit;
          transition: background 0.15s, color 0.15s, box-shadow 0.15s;
        }
        .wme-modal__btn--cancel {
          background: #1a1b28;
          border-color: #2d2a40;
          color: #7c8090;
        }
        .wme-modal__btn--cancel:hover { background: #232438; color: #ddd8cc; }
        .wme-modal__btn--save {
          background: #5b21b6;
          border-color: #7c3aed;
          color: #ede9fe;
          box-shadow: 0 2px 8px rgba(91,33,182,0.4);
        }
        .wme-modal__btn--save:hover { background: #6d28d9; box-shadow: 0 4px 16px rgba(109,40,217,0.5); }

        /* ---------- sidebar ---------- */
        .wme-sidebar {
          width: 300px;
          flex-shrink: 0;
          background: #0c0e18;
          border-left: 1px solid #1e2030;
          display: flex;
          flex-direction: column;
          overflow: hidden;
          box-shadow: -4px 0 20px rgba(0,0,0,0.4);
        }
        .wme-sidebar__header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 11px 14px;
          border-bottom: 1px solid #1e2030;
          flex-shrink: 0;
        }
        .wme-sidebar__title { font-size: 0.82rem; font-weight: bold; color: #d4a017; letter-spacing: 0.05em; }
        .wme-sidebar__close {
          background: none; border: none; color: #4b5563; cursor: pointer; font-size: 0.9rem; padding: 1px 4px;
        }
        .wme-sidebar__close:hover { color: #ddd8cc; }
        .wme-sidebar__filters {
          display: flex;
          flex-direction: column;
          gap: 6px;
          padding: 10px 12px;
          border-bottom: 1px solid #1e2030;
          flex-shrink: 0;
        }
        .wme-sidebar__search {
          background: #0d0f1a;
          border: 1px solid #2d2a40;
          border-radius: 4px;
          color: #ddd8cc;
          padding: 6px 10px;
          font-size: 0.78rem;
          font-family: inherit;
          width: 100%;
          box-sizing: border-box;
        }
        .wme-sidebar__search:focus { outline: none; border-color: #7c3aed; }
        .wme-sidebar__filter-row { display: flex; gap: 6px; }
        .wme-sidebar__filter-select {
          flex: 1;
          background: #0d0f1a;
          border: 1px solid #2d2a40;
          border-radius: 4px;
          color: #7c8090;
          padding: 5px 7px;
          font-size: 0.73rem;
          font-family: inherit;
          appearance: auto;
        }
        .wme-sidebar__list {
          list-style: none;
          margin: 0;
          padding: 6px 0;
          overflow-y: auto;
          flex: 1;
          scrollbar-width: thin;
          scrollbar-color: #2d2a40 transparent;
        }
        .wme-sidebar__empty {
          padding: 16px;
          color: #3d4048;
          font-size: 0.8rem;
          text-align: center;
        }
        .wme-sidebar__group-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 6px 12px 4px;
          border-left: 3px solid;
          margin: 8px 0 2px;
          font-size: 0.72rem;
          font-weight: bold;
          letter-spacing: 0.05em;
        }
        .wme-sidebar__group-count {
          background: #1a1b28;
          border-radius: 10px;
          padding: 1px 7px;
          font-size: 0.68rem;
          color: #4b5563;
        }
        .wme-sidebar__group-list { list-style: none; margin: 0; padding: 0; }
        .wme-sidebar__item {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 6px 14px;
          transition: background 0.1s;
          cursor: default;
        }
        .wme-sidebar__item:hover { background: #141624; }
        .wme-sidebar__item-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          flex-shrink: 0;
        }
        .wme-sidebar__item-body { flex: 1; display: flex; flex-direction: column; gap: 1px; min-width: 0; }
        .wme-sidebar__item-name {
          font-size: 0.82rem;
          color: #ddd8cc;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .wme-sidebar__item-meta {
          font-size: 0.68rem;
          color: #4b5563;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .wme-sidebar__item-actions { display: flex; gap: 3px; flex-shrink: 0; }
        .wme-sidebar__action {
          background: none;
          border: none;
          color: #3d4048;
          cursor: pointer;
          font-size: 0.8rem;
          padding: 2px 5px;
          border-radius: 3px;
          transition: color 0.1s, background 0.1s;
        }
        .wme-sidebar__action:hover { color: #ddd8cc; background: #1e2030; }
        .wme-sidebar__action--delete:hover { color: #ef4444; background: #1f1010; }

        /* ---------- faction power bars ---------- */
        .wme-sidebar__power {
          border-top: 1px solid #1e2030;
          flex-shrink: 0;
        }
        .wme-sidebar__power-toggle {
          width: 100%;
          padding: 8px 14px;
          background: none;
          border: none;
          color: #7c8090;
          font-size: 0.75rem;
          font-family: inherit;
          text-align: left;
          cursor: pointer;
          letter-spacing: 0.06em;
        }
        .wme-sidebar__power-toggle:hover { color: #d4a017; }
        .wme-sidebar__power-list {
          list-style: none;
          margin: 0;
          padding: 0 12px 10px;
          display: flex;
          flex-direction: column;
          gap: 10px;
          max-height: 240px;
          overflow-y: auto;
        }
        .wme-sidebar__power-item { display: flex; flex-direction: column; gap: 4px; }
        .wme-sidebar__power-name { font-size: 0.72rem; font-weight: bold; letter-spacing: 0.04em; }
        .wme-sidebar__power-row { display: flex; align-items: center; gap: 6px; }
        .wme-sidebar__power-key { font-size: 0.65rem; color: #4b5563; width: 24px; flex-shrink: 0; font-family: monospace; }
        .wme-sidebar__power-track {
          flex: 1;
          height: 4px;
          background: #1e2030;
          border-radius: 2px;
          overflow: hidden;
        }
        .wme-sidebar__power-bar {
          height: 100%;
          border-radius: 2px;
          transition: width 0.6s ease;
        }
        .wme-sidebar__power-val { font-size: 0.65rem; color: #4b5563; width: 22px; text-align: right; font-family: monospace; }

        /* ---------- conflict ring ---------- */
        .wme-conflict-ring {
          position: absolute;
          top: 50%;
          left: 50%;
          transform: translate(-50%, -50%);
          border: 2px solid;
          border-radius: 50%;
          pointer-events: none;
          animation: wme-pulse 1.4s ease-in-out infinite;
          z-index: 5;
        }
        @keyframes wme-pulse {
          0%, 100% { opacity: 0.9; transform: translate(-50%, -50%) scale(1); }
          50%       { opacity: 0.4; transform: translate(-50%, -50%) scale(1.25); }
        }

        /* ---------- leader portrait ---------- */
        .wme-portrait {
          position: absolute;
          bottom: calc(100% + 2px);
          left: 50%;
          transform: translateX(-50%);
          border-radius: 50%;
          border: 1.5px solid;
          object-fit: cover;
          pointer-events: none;
          background: #07090e;
          z-index: 15;
        }

        /* ---------- SSE status ---------- */
        .wme-statusbar__sse { font-size: 0.68rem; font-weight: bold; }
        .wme-statusbar__sse--live       { color: #22c55e; }
        .wme-statusbar__sse--offline    { color: #ef4444; }
        .wme-statusbar__sse--connecting { color: #6b7280; }

        /* ---------- playback toolbar ---------- */
        .wme-playback {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 5px 14px;
          background: #0a0c14;
          border-top: 1px solid #1e2030;
          flex-shrink: 0;
          font-size: 0.72rem;
          color: #9ca3af;
        }
        .wme-playback__btn {
          padding: 3px 8px;
          background: #1e1f2e;
          border: 1px solid #35324a;
          border-radius: 4px;
          color: #b8b4c8;
          cursor: pointer;
          font-size: 0.75rem;
          font-family: inherit;
          white-space: nowrap;
        }
        .wme-playback__btn:hover:not(:disabled) { background: #282840; color: #fff; }
        .wme-playback__btn:disabled { opacity: 0.35; cursor: default; }
        .wme-playback__scrubber {
          flex: 1;
          accent-color: #d4a017;
          cursor: pointer;
          min-width: 80px;
        }
        .wme-playback__label { color: #d4a017; font-family: monospace; white-space: nowrap; font-size: 0.7rem; }

        /* ---------- event toasts ---------- */
        .wme-toasts {
          position: fixed;
          right: 20px;
          bottom: 48px;
          display: flex;
          flex-direction: column;
          gap: 8px;
          z-index: 200;
          pointer-events: none;
        }
        .wme-toast {
          pointer-events: auto;
          width: 280px;
          background: rgba(8, 6, 18, 0.94);
          border: 1px solid;
          border-radius: 6px;
          padding: 10px 14px;
          cursor: pointer;
          animation: wme-toast-in 0.3s ease both;
          backdrop-filter: blur(6px);
        }
        @keyframes wme-toast-in {
          from { transform: translateX(110%); opacity: 0; }
          to   { transform: translateX(0);    opacity: 1; }
        }
        .wme-toast__header {
          font-size: 0.68rem;
          font-weight: bold;
          letter-spacing: 0.1em;
          text-transform: uppercase;
          margin-bottom: 4px;
          font-family: 'Georgia', serif;
        }
        .wme-toast__body {
          font-size: 0.8rem;
          color: #ddd8cc;
          font-family: 'Georgia', serif;
          line-height: 1.3;
        }
        .wme-toast__dismiss { font-size: 0.62rem; color: #3d4048; margin-top: 5px; }
      `}</style>
    </div>
  );
}
