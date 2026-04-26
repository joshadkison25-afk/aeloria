'use client';

import { useEffect, useMemo, useState } from 'react';

type HexTile = { id: string; x: number; y: number; row: number; col: number };
type ConfigMode = 'core' | 'optional' | 'custom';
type LoreSpeciesOption = { id: string; name: string };
type LoreLocation = { id: string; species: LoreSpeciesOption[] };
type LoreResponse = { locations?: LoreLocation[] };
type WorldResponse = {
  regions?: Record<string, { controller?: string; factionId?: string; owner?: string }>;
  region_control?:
    | Array<{ hexId?: string; id?: string; factionId?: string; controller?: string; owner?: string }>
    | Record<string, { factionId?: string; controller?: string; owner?: string }>;
};
type SavedMapLayout = {
  metadata: { speciesSet: string; configMode: string; version: number; savedAt: string };
  ownership: Record<string, string | null>;
};
type MapLocation = { id: string; name: string; centerX: number; centerY: number; radius: number };
type LocationOption = { id: string; name: string };
type LocationAssignment = string | null;

const VIEWBOX_WIDTH = 100;
const VIEWBOX_HEIGHT = 100;
const HEX_WIDTH = 3.2;
const HEX_HEIGHT = 3.2;
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
    if (y > VIEWBOX_HEIGHT + HEX_HEIGHT) break;
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
  if (world.region_control && typeof world.region_control === 'object') {
    for (const [hexId, row] of Object.entries(world.region_control)) map[hexId] = row?.factionId || row?.controller || row?.owner || null;
    return map;
  }
  if (world.regions && typeof world.regions === 'object') {
    for (const [hexId, row] of Object.entries(world.regions)) map[hexId] = row?.factionId || row?.controller || row?.owner || null;
  }
  return map;
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

export default function FantasyMap() {
  const hexTiles = useMemo(() => buildHexGrid(), []);
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

  const hoveredHex = hoveredHexId ? hexTiles.find((hex) => hex.id === hoveredHexId) || null : null;
  const selectedHex = selectedHexId ? hexTiles.find((hex) => hex.id === selectedHexId) || null : null;

  const backendOwnership = useMemo(() => deriveHexOwnership(world), [world]);
  const configKey = useMemo(() => `lore::${configMode}`, [configMode]);

  const allLoreFactions = useMemo(() => loreLocations.flatMap((location) => location.species || []), [loreLocations]);
  const factionNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const faction of allLoreFactions) map.set(faction.id, faction.name);
    return map;
  }, [allLoreFactions]);

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

  const locationFactionOptions = useMemo(() => {
    if (!activeLocationId) return [];
    return speciesByLocation.get(normalizeKey(activeLocationId)) || [];
  }, [activeLocationId, speciesByLocation]);

  useEffect(() => {
    // eslint-disable-next-line no-console
    console.log('[MapDebug] selected hex locationId:', activeLocationId || null);
    // eslint-disable-next-line no-console
    console.log('[MapDebug] species options for location:', locationFactionOptions);
  }, [activeLocationId, locationFactionOptions]);

  useEffect(() => {
    // Auto-select a location species only when nothing is selected.
    // Do not override explicit "All Species" selections.
    if (!selectedFactionId) {
      setSelectedFactionId(locationFactionOptions[0]?.id || '');
    }
  }, [locationFactionOptions, selectedFactionId]);

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
      for (const hex of hexTiles) seeded[hex.id] = backendOwnership?.[hex.id] ?? null;
      return { ...prev, [configKey]: seeded };
    });
  }, [backendOwnership, configKey, hexTiles]);

  const effectiveOwnership = useMemo(() => {
    const layout = layoutsByConfig[configKey];
    if (layout) return layout;
    const seeded: Record<string, string | null> = {};
    for (const hex of hexTiles) seeded[hex.id] = backendOwnership?.[hex.id] ?? null;
    return seeded;
  }, [backendOwnership, configKey, hexTiles, layoutsByConfig]);
  const factionByHex = effectiveOwnership;

  function updateActiveLayout(mutator: (current: Record<string, string | null>) => Record<string, string | null>) {
    setLayoutsByConfig((prev) => {
      const current = prev[configKey] || effectiveOwnership;
      return { ...prev, [configKey]: mutator(current) };
    });
  }

  function setFactionByHex(mutator: (current: Record<string, string | null>) => Record<string, string | null>) {
    updateActiveLayout(mutator);
  }

  function handleHexPaintClick(hex: HexTile) {
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
        if (hasManualLocation && manualLocation === '') return;
        // Explicit blank assignment disables geometric fallback for this hex.
        setLocationByHex((prev) => ({ ...prev, [hex.id]: '' }));
        return;
      }
      const locationId = resolvedLocationId || 'unassigned';
      if (locationByHex[hex.id] === locationId) return;
      setLocationByHex((prev) => ({ ...prev, [hex.id]: locationId }));
      return;
    }

    if (isFactionModeActive) {
      if (isEraseMode) {
        if ((factionByHex[hex.id] ?? null) === null) return;
        setFactionByHex((prev) => ({ ...prev, [hex.id]: null }));
        return;
      }
      const speciesForLocation = resolvedLocationId ? speciesByLocation.get(normalizeKey(resolvedLocationId)) || [] : [];
      const factionId = selectedFactionId || speciesForLocation[0]?.id || 'unclaimed';
      if (!selectedFactionId && factionId) setSelectedFactionId(factionId);
      if (factionByHex[hex.id] === factionId) return;
      setFactionByHex((prev) => ({ ...prev, [hex.id]: factionId }));
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
      // eslint-disable-next-line no-console
      console.log('[MapDebug] lore API response:', payload);
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
      metadata: { speciesSet: activeLocationId || 'all', configMode, version: 1, savedAt: new Date().toISOString() },
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

  return (
    <div style={{ minHeight: '100vh', background: '#0b0b0f', color: '#f3f3f7', padding: '16px' }}>
      <div style={{ maxWidth: '1200px', margin: '0 auto', display: 'grid', gap: '12px' }}>
        <div style={{ border: '1px solid #2b2b35', borderRadius: 10, padding: '10px 12px', background: '#111217' }}>
          <h1 style={{ margin: 0, fontSize: '1.45rem' }}>Aeloria Map Builder</h1>
          <p style={{ margin: '4px 0 0 0', opacity: 0.85 }}>
            Active species: <strong>{selectedFactionId || 'None'}</strong> • Config: <strong>{configMode}</strong> • Location:{' '}
            <strong>{activeLocationName || 'None selected'}</strong>
          </p>
          <p style={{ margin: '6px 0 0 0', opacity: 0.95 }}>
            Current mode:{' '}
            <strong>{isLocationPaintMode ? 'Location Paint: ON' : 'Faction Paint: ON'}</strong>
          </p>
          <div
            style={{
              marginTop: 8,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 10,
              padding: '4px 8px',
              borderRadius: 999,
              border: '1px solid #3a4155',
              background: '#1a1c22',
              fontSize: '0.78rem',
            }}
          >
            <span>
              Mode: <strong>{isLocationPaintMode ? 'Location' : 'Faction'}</strong>
            </span>
            <span style={{ opacity: 0.7 }}>|</span>
            <span>
              Tool: <strong>{isEraseMode ? 'Erase' : 'Paint'}</strong>
            </span>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
          <div style={{ border: '1px solid #2b2b35', borderRadius: 10, padding: '10px 12px', background: '#111217' }}>
            <strong style={{ fontSize: '0.95rem' }}>Species Selector</strong>
            <div style={{ marginTop: 8, display: 'grid', gap: 8 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                Config
                <select value={configMode} onChange={(e) => setConfigMode(e.target.value as ConfigMode)} style={{ border: '1px solid #3a4155', borderRadius: 8, padding: '8px 10px', background: '#1a1c22', color: '#fff' }}>
                  <option value="core">Core factions</option>
                  <option value="optional">Optional factions</option>
                  <option value="custom">Custom combinations</option>
                </select>
              </label>
              <button type="button" onClick={() => void loadLoreData()} style={{ border: '1px solid #3a4155', borderRadius: 8, padding: '8px 10px', background: '#1a1c22', color: '#fff', cursor: 'pointer' }}>
                Reload Lore
              </button>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                Paint Location
                <select value={selectedLocationId} onChange={(e) => setSelectedLocationId(e.target.value)} style={{ border: '1px solid #3a4155', borderRadius: 8, padding: '8px 10px', background: '#1a1c22', color: '#fff' }}>
                  {locationOptions.length === 0 && <option value="">No locations loaded</option>}
                  {locationOptions.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}
                </select>
              </label>
            </div>
          </div>

          <div style={{ border: '1px solid #2b2b35', borderRadius: 10, padding: '10px 12px', background: '#111217' }}>
            <strong style={{ fontSize: '0.95rem' }}>Location Species (Lore-Driven)</strong>
            <div style={{ marginTop: 8, display: 'grid', gap: 8 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                Paint Faction
                <select value={selectedFactionId} onChange={(e) => setSelectedFactionId(e.target.value)} disabled={!isEditMode} style={{ border: '1px solid #3a4155', borderRadius: 8, padding: '6px 8px', background: '#1a1c22', color: '#fff' }}>
                  {locationFactionOptions.length === 0 && <option value="">No species for location</option>}
                  {locationFactionOptions.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
                </select>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                All Species
                <select value={selectedFactionId} onChange={(e) => setSelectedFactionId(e.target.value)} style={{ border: '1px solid #3a4155', borderRadius: 8, padding: '6px 8px', background: '#1a1c22', color: '#fff' }}>
                  {allSpeciesOptions.length === 0 && <option value="">No species loaded</option>}
                  {allSpeciesOptions.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
                </select>
              </label>
              <div style={{ display: 'grid', gap: 6, maxHeight: 140, overflow: 'auto' }}>
                {locationFactionOptions.map((f) => <div key={f.id} style={{ fontSize: '0.9rem', opacity: 0.9 }}><code>{f.id}</code> — {f.name}</div>)}
                {locationFactionOptions.length === 0 && <div style={{ fontSize: '0.9rem', opacity: 0.7 }}>Hover or click a hex to resolve location species options.</div>}
              </div>
            </div>
          </div>

          <div style={{ border: '1px solid #2b2b35', borderRadius: 10, padding: '10px 12px', background: '#111217' }}>
            <strong style={{ fontSize: '0.95rem' }}>Save / Load Map</strong>
            <div style={{ marginTop: 8, display: 'grid', gap: 8 }}>
              <button type="button" onClick={() => {
                setIsLocationPaintMode(false);
                setIsEditMode(true);
              }} style={{ border: '1px solid #3a4155', borderRadius: 8, padding: '8px 10px', background: isEditMode ? '#2f5dea' : '#1a1c22', color: '#fff', cursor: 'pointer' }}>
                Faction Paint: {isEditMode ? 'ON' : 'OFF'}
              </button>
              <button type="button" onClick={() => {
                setIsLocationPaintMode(true);
                setIsEditMode(false);
              }} style={{ border: '1px solid #3a4155', borderRadius: 8, padding: '8px 10px', background: isLocationPaintMode ? '#7c3aed' : '#1a1c22', color: '#fff', cursor: 'pointer' }}>
                Location Paint: {isLocationPaintMode ? 'ON' : 'OFF'}
              </button>
              <button type="button" onClick={() => setIsEraseMode((v) => !v)} style={{ border: '1px solid #3a4155', borderRadius: 8, padding: '8px 10px', background: isEraseMode ? '#b91c1c' : '#1a1c22', color: '#fff', cursor: 'pointer' }}>
                Erase: {isEraseMode ? 'ON' : 'OFF'}
              </button>
              <button type="button" onClick={() => void loadWorld()} style={{ border: '1px solid #3a4155', borderRadius: 8, padding: '8px 10px', background: '#1a1c22', color: '#fff', cursor: 'pointer' }}>
                Load From World
              </button>
              <button type="button" onClick={clearLayout} style={{ border: '1px solid #3a4155', borderRadius: 8, padding: '8px 10px', background: '#1a1c22', color: '#fff', cursor: 'pointer' }}>
                Clear Layout
              </button>
              <button type="button" onClick={clearAllPaint} style={{ border: '1px solid #3a4155', borderRadius: 8, padding: '8px 10px', background: '#1a1c22', color: '#fff', cursor: 'pointer' }}>
                Clear All
              </button>
              <button type="button" onClick={resetLayoutToBackend} style={{ border: '1px solid #3a4155', borderRadius: 8, padding: '8px 10px', background: '#1a1c22', color: '#fff', cursor: 'pointer' }}>
                Reset Layout
              </button>
              <button type="button" onClick={() => void saveCurrentLayout()} style={{ border: '1px solid #3a4155', borderRadius: 8, padding: '8px 10px', background: '#1a1c22', color: '#fff', cursor: 'pointer' }}>
                Save Layout
              </button>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                Saved Maps
                <select value={selectedMapFile} onChange={(e) => setSelectedMapFile(e.target.value)} style={{ border: '1px solid #3a4155', borderRadius: 8, padding: '8px 10px', background: '#1a1c22', color: '#fff' }}>
                  {savedMapFiles.length === 0 && <option value="">No saved maps</option>}
                  {savedMapFiles.map((file) => <option key={file} value={file}>{file}</option>)}
                </select>
              </label>
              <button type="button" onClick={() => void loadSelectedLayout()} style={{ border: '1px solid #3a4155', borderRadius: 8, padding: '8px 10px', background: '#1a1c22', color: '#fff', cursor: 'pointer' }}>
                Load Layout
              </button>
            </div>
          </div>
        </div>

        <div style={{ border: '1px dashed #3a4155', borderRadius: 10, padding: '10px 12px', background: '#0f1015' }}>
          <strong style={{ fontSize: '0.92rem' }}>Debug Lore Flow (temporary)</strong>
          <div style={{ marginTop: 6, fontSize: '0.9rem', opacity: 0.9 }}>
            Current locationId: <code>{activeLocationId || 'none'}</code> | Lore locations loaded: <code>{loreLocations.length}</code>
          </div>
          <div style={{ marginTop: 6, display: 'grid', gap: 4, maxHeight: 120, overflow: 'auto' }}>
            {locationFactionOptions.length === 0 && <div style={{ opacity: 0.75 }}>No species options for current location.</div>}
            {locationFactionOptions.map((item) => (
              <div key={item.id}>
                <code>{item.id}</code> - {item.name}
              </div>
            ))}
          </div>
        </div>

        <div style={{ position: 'relative', borderRadius: '10px', overflow: 'hidden', border: '1px solid #2b2b35', background: '#111', width: '100%', maxWidth: '1100px' }}>
          <img src="/aeloria-lore-map-labeled.png" alt="Aeloria map" style={{ width: '100%', display: 'block', userSelect: 'none' }} />
          <svg
            viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
            preserveAspectRatio="none"
            style={{ position: 'absolute', inset: 0, zIndex: 10, width: '100%', height: '100%' }}
            onMouseDown={() => setIsMouseDown(true)}
            onMouseUp={() => setIsMouseDown(false)}
            onMouseLeave={() => setIsMouseDown(false)}
          >
            {hexTiles.map((hex) => {
              const isHovered = hoveredHexId === hex.id;
              const factionId = factionByHex?.[hex.id] ?? null;
              const hasManualLocation = Object.prototype.hasOwnProperty.call(locationByHex, hex.id);
              const manualLocation = hasManualLocation ? locationByHex[hex.id] : null;
              const resolvedLocationId =
                manualLocation === ''
                  ? null
                  : manualLocation || locationForHex(hex.x, hex.y)?.id || null;
              const factionFill = factionId ? colorForFaction(factionId) : null;
              const locationFill = resolvedLocationId ? (locationColors[resolvedLocationId] || colorForFaction(`location-${resolvedLocationId}`)) : null;
              const fill = factionFill ? factionFill : locationFill ? locationFill : '#222';
              const fillOpacity = factionFill ? 1 : locationFill ? 0.6 : 0.3;
              return (
                <polygon
                  key={hex.id}
                  points={hexPoints(hex.x, hex.y, HEX_WIDTH, HEX_HEIGHT)}
                  fill={fill}
                  fillOpacity={isHovered ? Math.min(fillOpacity + 0.12, 1) : fillOpacity}
                  stroke={isHovered ? 'rgba(188, 240, 255, 0.95)' : 'rgba(220, 232, 255, 0.65)'}
                  strokeWidth={0.15}
                  style={{ cursor: 'pointer' }}
                  onMouseEnter={() => {
                    setHoveredHexId(hex.id);
                    if (isMouseDown) handleHexPaintClick(hex);
                  }}
                  onMouseLeave={() => setHoveredHexId(null)}
                  onClick={() => {
                    setSelectedHexId(hex.id);
                    handleHexPaintClick(hex);
                    console.log('Hex clicked:', {
                      id: hex.id,
                      row: hex.row,
                      col: hex.col,
                      location: activeLocationName || 'Unclaimed',
                      factionId: factionId ?? null,
                      factionName: (factionId ? factionNameById.get(factionId) : null) || factionId || 'Unclaimed',
                    });
                  }}
                />
              );
            })}
          </svg>

          {hoveredHexId && (
            <div style={{ position: 'absolute', left: 12, bottom: 12, padding: '8px 10px', borderRadius: '8px', background: 'rgba(0, 0, 0, 0.75)', border: '1px solid rgba(255,255,255,0.24)' }}>
              Hovered: <strong>{hoveredHexId}</strong>
              {hoveredHex && (
                <span style={{ marginLeft: 8, opacity: 0.8 }}>
                  ({hoveredHex.x.toFixed(1)}, {hoveredHex.y.toFixed(1)}) •{' '}
                  {Object.prototype.hasOwnProperty.call(locationByHex, hoveredHex.id)
                    ? (locationByHex[hoveredHex.id] === '' ? 'Unclaimed' : locationByHex[hoveredHex.id])
                    : (locationForHex(hoveredHex.x, hoveredHex.y)?.id || 'Unclaimed')}{' '}
                  •{' '}
                  {(() => {
                    const factionId = factionByHex?.[hoveredHex.id] ?? null;
                    const factionName = factionId ? factionNameById.get(factionId) : null;
                    return factionName || factionId || 'Unclaimed';
                  })()}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
