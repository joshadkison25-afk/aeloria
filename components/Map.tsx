'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

type RegionOverlay = {
  id: string;
  name: string;
  position: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
};

type WorldState = {
  tick?: number;
  world_date?: string;
  regions?: Record<string, { controller?: string }>;
  region_control?: Array<{ region?: string; controller?: string }>;
};

const REGION_OVERLAYS: RegionOverlay[] = [
  { id: 'faerwood', name: 'Faerwood', position: { x: 22, y: 26, width: 16, height: 16 } },
  { id: 'twin-cities', name: 'Twin Cities', position: { x: 36, y: 52, width: 14, height: 10 } },
  { id: 'tidefall', name: 'Tidefall', position: { x: 53, y: 55, width: 13, height: 10 } },
  { id: 'lostfeld', name: 'Lostfeld', position: { x: 25, y: 48, width: 12, height: 10 } },
  { id: 'glenhaven', name: 'Glenhaven', position: { x: 36, y: 62, width: 18, height: 12 } },
  { id: 'gilgeth-and-groth', name: 'Gilgeth and Groth', position: { x: 57, y: 67, width: 14, height: 13 } },
  { id: 'rock-plains', name: 'Rock Plains', position: { x: 38, y: 70, width: 14, height: 12 } },
  { id: 'dreadwind-isles', name: 'Dreadwind Isles', position: { x: 58, y: 12, width: 14, height: 14 } },
  { id: 'dur-khadur', name: 'Dur Khadur', position: { x: 16, y: 77, width: 13, height: 10 } },
  { id: 'stonebreak', name: 'Stonebreak', position: { x: 45, y: 67, width: 10, height: 9 } },
  { id: 'gloomspire', name: 'Gloomspire', position: { x: 47, y: 43, width: 10, height: 8 } },
  { id: 'dragonscar-peaks', name: 'Dragonscar Peaks', position: { x: 20, y: 36, width: 12, height: 12 } },
];

function normalizeKey(input: string): string {
  return input.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

function colorForFaction(faction: string): string {
  if (!faction) return 'rgba(128, 128, 128, 0.28)';
  let hash = 0;
  for (let i = 0; i < faction.length; i += 1) {
    hash = faction.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash) % 360;
  return `hsla(${hue}, 70%, 52%, 0.35)`;
}

export default function FantasyMap() {
  const [world, setWorld] = useState<WorldState | null>(null);
  const [loading, setLoading] = useState(true);
  const [tickLoading, setTickLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hoveredRegionId, setHoveredRegionId] = useState<string | null>(null);

  const loadWorld = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/world', { cache: 'no-store' });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload?.error || 'Failed to fetch world data.');
      }
      setWorld(payload as WorldState);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch world data.';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadWorld();
  }, [loadWorld]);

  const controllerByRegion = useMemo(() => {
    const map = new Map<string, string>();
    if (!world) return map;

    if (world.regions && typeof world.regions === 'object') {
      Object.entries(world.regions).forEach(([name, value]) => {
        map.set(normalizeKey(name), value?.controller || 'Unclaimed');
      });
    }

    if (Array.isArray(world.region_control)) {
      world.region_control.forEach((entry) => {
        if (!entry?.region) return;
        map.set(normalizeKey(entry.region), entry.controller || 'Unclaimed');
      });
    }

    return map;
  }, [world]);

  const hoveredRegion = REGION_OVERLAYS.find((region) => region.id === hoveredRegionId) || null;

  async function runTick() {
    setTickLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/tick', { method: 'POST' });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload?.error || 'Tick failed.');
      }
      await loadWorld();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Tick failed.';
      setError(message);
    } finally {
      setTickLoading(false);
    }
  }

  return (
    <div style={{ minHeight: '100vh', background: '#0b0b0f', color: '#f3f3f7', padding: '16px' }}>
      <div style={{ maxWidth: '1100px', margin: '0 auto', display: 'grid', gap: '12px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: '1.45rem' }}>Aeloria Interactive Map</h1>
            <p style={{ margin: '4px 0 0 0', opacity: 0.85 }}>
              {loading ? 'Loading world...' : `Tick ${world?.tick ?? '?'} • ${world?.world_date ?? 'Unknown date'}`}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void runTick()}
            disabled={tickLoading}
            style={{
              background: tickLoading ? '#525252' : '#2f5dea',
              color: '#fff',
              border: 0,
              borderRadius: '8px',
              padding: '10px 14px',
              cursor: tickLoading ? 'not-allowed' : 'pointer',
              fontWeight: 600,
            }}
          >
            {tickLoading ? 'Running Tick...' : 'Run Tick'}
          </button>
        </div>

        {error && (
          <div
            style={{
              background: 'rgba(180, 31, 31, 0.2)',
              border: '1px solid rgba(255, 90, 90, 0.6)',
              borderRadius: '8px',
              padding: '10px 12px',
            }}
          >
            {error}
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 260px', gap: '12px' }}>
          <div
            style={{
              position: 'relative',
              borderRadius: '10px',
              overflow: 'hidden',
              border: '1px solid #2b2b35',
              background: '#111',
            }}
          >
            <img
              src="/aeloria-lore-map-labeled.png"
              alt="Aeloria map"
              style={{ width: '100%', display: 'block', userSelect: 'none' }}
            />

            {REGION_OVERLAYS.map((region) => {
              const controller = controllerByRegion.get(region.id) || 'Unclaimed';
              return (
                <button
                  key={region.id}
                  type="button"
                  onMouseEnter={() => setHoveredRegionId(region.id)}
                  onMouseLeave={() => setHoveredRegionId(null)}
                  onClick={() => {
                    // Simple interaction requested: emit region data on click.
                    // eslint-disable-next-line no-console
                    console.log({
                      id: region.id,
                      name: region.name,
                      position: region.position,
                      controller,
                    });
                  }}
                  style={{
                    position: 'absolute',
                    left: `${region.position.x}%`,
                    top: `${region.position.y}%`,
                    width: `${region.position.width}%`,
                    height: `${region.position.height}%`,
                    border: `2px solid ${hoveredRegionId === region.id ? '#ffffff' : 'rgba(255,255,255,0.45)'}`,
                    background: colorForFaction(controller),
                    borderRadius: '6px',
                    cursor: 'pointer',
                  }}
                  aria-label={`${region.name}, controlled by ${controller}`}
                  title={`${region.name}: ${controller}`}
                />
              );
            })}

            {hoveredRegion && (
              <div
                style={{
                  position: 'absolute',
                  left: 12,
                  bottom: 12,
                  padding: '10px 12px',
                  borderRadius: '8px',
                  background: 'rgba(0, 0, 0, 0.78)',
                  border: '1px solid rgba(255,255,255,0.22)',
                  pointerEvents: 'none',
                }}
              >
                <div style={{ fontWeight: 700 }}>{hoveredRegion.name}</div>
                <div style={{ fontSize: '0.9rem', opacity: 0.9 }}>
                  {controllerByRegion.get(hoveredRegion.id) || 'Unclaimed'}
                </div>
              </div>
            )}
          </div>

          <div
            style={{
              border: '1px solid #2b2b35',
              borderRadius: '10px',
              padding: '10px',
              background: '#111217',
              maxHeight: '70vh',
              overflow: 'auto',
            }}
          >
            <h2 style={{ marginTop: 0, fontSize: '1rem' }}>Region Control</h2>
            <div style={{ display: 'grid', gap: '8px' }}>
              {REGION_OVERLAYS.map((region) => {
                const controller = controllerByRegion.get(region.id) || 'Unclaimed';
                return (
                  <div
                    key={region.id}
                    style={{
                      border: '1px solid #2f3341',
                      borderRadius: '6px',
                      padding: '8px',
                      background: 'rgba(255,255,255,0.02)',
                    }}
                  >
                    <div style={{ fontWeight: 700 }}>{region.name}</div>
                    <div style={{ fontSize: '0.9rem', opacity: 0.9 }}>{controller}</div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
