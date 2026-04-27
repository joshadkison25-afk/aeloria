'use client';

import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

import { normalizeMapLibreColor } from '@/lib/strategyMapColors';
import {
  type RawTerrain,
  coastlinesToGeoJson,
  TERRAIN_LAYER_FILL,
  terrainFillsToGeoJson,
} from '@/lib/terrainToGeojson';

function readEmbedMode(): boolean {
  if (typeof window === 'undefined') return false;
  const v = new URLSearchParams(window.location.search).get('embed');
  if (v == null) return false;
  return ['1', 'true', 'yes', 'on'].includes(v.trim().toLowerCase());
}

/** Map only: no legend, HUD, hover popup, or zoom buttons (also implied by `embed=1`). */
function readBareMapMode(): boolean {
  if (typeof window === 'undefined') return false;
  const q = new URLSearchParams(window.location.search);
  for (const key of ['no_ui', 'bare', 'minimal']) {
    const v = q.get(key);
    if (v != null && ['1', 'true', 'yes', 'on'].includes(v.trim().toLowerCase())) return true;
  }
  return false;
}

/** Flask home.html removes the atlas veil when it receives this (see `homeAtlasEnterVeil`). */
function notifyParentMapReady() {
  requestAnimationFrame(() => {
    try {
      if (typeof window !== 'undefined' && window.parent !== window) {
        window.parent.postMessage({ type: 'aeloria-home-map-ready' }, '*');
      }
    } catch {
      /* ignore */
    }
  });
}

/** Prefix for `/data/*` when Next runs under a subpath (`NEXT_PUBLIC_BASE_PATH`). */
function dataUrl(file: string): string {
  const base =
    (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_BASE_PATH?.replace(/\/$/, '')) || '';
  return `${base}/data/${file.replace(/^\//, '')}`;
}

/** Map `realm_id` → Flask `world_state.regions` key when names differ. */
const REALM_WORLD_KEY: Record<string, string> = {
  Glenwood: 'Glenhaven',
  Farrock: 'Varkuun',
};

const SOURCE_ID = 'regions';
const TERRAIN_SOURCE = 'terrain';
const COAST_SOURCE = 'coastlines';
const TERRAIN_FILL_LAYER = 'terrain-base';
const COAST_LINE_LAYER = 'terrain-coast';
const FILL_LAYER = 'regions-fill';
const LINE_LAYER = 'regions-line';

type GeoJSONFeatureCollection = {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    id?: string | number;
    properties: Record<string, string | undefined | string[]>;
    geometry: { type: 'Polygon' | 'MultiPolygon'; coordinates: number[][][] | number[][][][] };
  }>;
};

type HousesJson = {
  factionColors?: Record<string, string>;
  houses?: Array<{ id: string; name: string; faction_id: string; region_id?: string }>;
};

type WorldRegionRow = {
  controller?: string | null;
  canonical_faction?: string | null;
};

type WorldStateResponse = {
  regions?: Record<string, WorldRegionRow>;
};

function controllerFaction(row: WorldRegionRow | undefined): string {
  if (!row) return 'Unclaimed';
  const c = row.controller;
  const cf = row.canonical_faction;
  if (typeof c === 'string' && c.trim()) return c.trim();
  if (typeof cf === 'string' && cf.trim()) return cf.trim();
  return 'Unclaimed';
}

function fillColorForFaction(
  faction: string,
  palette: Record<string, string> | undefined,
): string {
  return normalizeMapLibreColor(palette?.[faction], faction);
}

function forEachExteriorPoint(
  geom: GeoJSONFeatureCollection['features'][0]['geometry'],
  visit: (x: number, y: number) => void,
) {
  if (geom.type === 'Polygon') {
    for (const pt of geom.coordinates[0]) {
      if (pt.length >= 2) visit(pt[0], pt[1]);
    }
  } else {
    for (const poly of geom.coordinates) {
      for (const pt of poly[0]) {
        if (pt.length >= 2) visit(pt[0], pt[1]);
      }
    }
  }
}

function boundsFromGeoJSON(gj: GeoJSONFeatureCollection): maplibregl.LngLatBoundsLike {
  let minLng = Infinity,
    minLat = Infinity,
    maxLng = -Infinity,
    maxLat = -Infinity;
  for (const f of gj.features) {
    forEachExteriorPoint(f.geometry, (lng, lat) => {
      minLng = Math.min(minLng, lng);
      maxLng = Math.max(maxLng, lng);
      minLat = Math.min(minLat, lat);
      maxLat = Math.max(maxLat, lat);
    });
  }
  if (!Number.isFinite(minLng)) return [
    [0, 0],
    [1, 1],
  ];
  return [
    [minLng, minLat],
    [maxLng, maxLat],
  ];
}

function houseIdsForRegion(
  mapRegion: string,
  byRegion: Record<string, string[]>,
): string[] {
  return byRegion[mapRegion] ?? (mapRegion ? [mapRegion] : []);
}

function applyWorldFactionFills(
  map: maplibregl.Map,
  world: WorldStateResponse,
  palette: Record<string, string>,
  byRegion: Record<string, string[]>,
) {
  const regions = world.regions;
  if (!regions) return;
  for (const regionId of Object.keys(regions)) {
    const fac = controllerFaction(regions[regionId]);
    const fill = fillColorForFaction(fac, palette);
    for (const houseId of houseIdsForRegion(regionId, byRegion)) {
      try {
        map.setFeatureState({ source: SOURCE_ID, id: houseId }, { fill });
      } catch {
        /* no matching house feature */
      }
    }
  }
}

export default function StrategyMap() {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const hoverIdRef = useRef<string | null>(null);
  const selectedIdRef = useRef<string | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const housesPaletteRef = useRef<Record<string, string>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const embedReadyPostedRef = useRef(false);
  const housesByRegionRef = useRef<Record<string, string[]>>({});

  const [selectionHud, setSelectionHud] = useState<string | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const embedMode = typeof window !== 'undefined' && readEmbedMode();
  const minimalUi = typeof window !== 'undefined' && (readEmbedMode() || readBareMapMode());

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const minimalChrome = readEmbedMode() || readBareMapMode();

    const map = new maplibregl.Map({
      container,
      style: {
        version: 8,
        sources: {},
        layers: [
          {
            id: 'bg',
            type: 'background',
            paint: { 'background-color': '#070910' },
          },
        ],
      },
      center: [7, 4.5],
      zoom: 5.2,
      attributionControl: false,
    });

    mapRef.current = map;
    if (!minimalChrome) {
      popupRef.current = new maplibregl.Popup({
        closeButton: false,
        closeOnClick: false,
        offset: 12,
        className: 'strategy-map-popup',
      });
    }

    if (!minimalChrome) {
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    }

    const postEmbedReadyOnce = () => {
      if (!readEmbedMode() || embedReadyPostedRef.current) return;
      embedReadyPostedRef.current = true;
      notifyParentMapReady();
    };

    map.on('error', (ev) => {
      const errObj = (ev as { error?: { message?: string } }).error;
      const msg =
        (typeof errObj?.message === 'string' ? errObj.message : null) ||
        (ev as { error?: Error }).error?.message ||
        (typeof (ev as { message?: string }).message === 'string'
          ? (ev as { message: string }).message
          : null);
      setMapError(
        msg
          ? `Map engine: ${msg}`
          : 'Map engine error (often WebGL blocked or invalid layer). Check the browser console.',
      );
      postEmbedReadyOnce();
    });

    map.on('load', async () => {
      let geojson: GeoJSONFeatureCollection;
      try {
        const [housesRes, terrainRes] = await Promise.all([
          fetch(dataUrl('houses.json'), { cache: 'no-store' }),
          fetch(dataUrl('terrain_map.json'), { cache: 'no-store' }),
        ]);
        let geoRes = await fetch(dataUrl('map.geojson'), { cache: 'no-store' });
        if (!geoRes.ok) {
          geoRes = await fetch(dataUrl('map_geo.json'), { cache: 'no-store' });
        }
        if (!geoRes.ok) {
          setMapError(
            `Could not load map data (HTTP ${geoRes.status} for map.geojson / map_geo.json). ` +
              `Ensure Next is running from the repo root and commit includes public/data/map.geojson (run: npm run build:map-geojson). ` +
              `If the app uses a URL prefix, set NEXT_PUBLIC_BASE_PATH in .env.`,
          );
          postEmbedReadyOnce();
          return;
        }
        try {
          const raw = await geoRes.text();
          geojson = JSON.parse(raw) as GeoJSONFeatureCollection;
        } catch {
          setMapError(
            'Map file downloaded but is not valid JSON. Re-run: npm run build:map-geojson (or build:map-geo).',
          );
          postEmbedReadyOnce();
          return;
        }
        if (!Array.isArray(geojson.features) || geojson.features.length === 0) {
          setMapError('Map GeoJSON has no features.');
          postEmbedReadyOnce();
          return;
        }

        for (const f of geojson.features) {
          if (!f.properties) f.properties = {};
          const p = f.properties;
          if (p.house_id == null && f.id != null) p.house_id = String(f.id);
          if (p.house_id == null) {
            setMapError('Map GeoJSON has a feature without house_id (needed for parcel picking).');
            postEmbedReadyOnce();
            return;
          }
        }

        let houses: HousesJson = { factionColors: {} };
        if (housesRes.ok) {
          try {
            houses = (await housesRes.json()) as HousesJson;
          } catch {
            /* use empty palette below */
          }
        }
        const rawPalette = houses.factionColors || {};
        const palette: Record<string, string> = {};
        for (const [k, v] of Object.entries(rawPalette)) {
          palette[k] = normalizeMapLibreColor(v, k);
        }
        housesPaletteRef.current = palette;

        const byRegion: Record<string, string[]> = {};
        for (const f of geojson.features) {
          const fac = String(f.properties.faction_id || 'Unclaimed');
          f.properties.default_fill = normalizeMapLibreColor(
            f.properties.default_fill,
            fac,
          );
          const rid = String(f.properties.region_id || f.properties.realm_id || '');
          const hid = String(f.properties.house_id ?? f.id ?? '');
          if (rid && hid) {
            if (!byRegion[rid]) byRegion[rid] = [];
            byRegion[rid].push(hid);
            const worldKey = REALM_WORLD_KEY[rid];
            if (worldKey) {
              if (!byRegion[worldKey]) byRegion[worldKey] = [];
              byRegion[worldKey].push(hid);
            }
          }
        }
        housesByRegionRef.current = byRegion;

        if (terrainRes.ok) {
          try {
            const terrainJson = (await terrainRes.json()) as RawTerrain;
            const terrainFills = terrainFillsToGeoJson(terrainJson);
            if (terrainFills.features.length > 0) {
              map.addSource(TERRAIN_SOURCE, { type: 'geojson', data: terrainFills });
              map.addLayer({
                id: TERRAIN_FILL_LAYER,
                type: 'fill',
                source: TERRAIN_SOURCE,
                paint: {
                  'fill-color': [
                    'match',
                    ['get', 'kind'],
                    'plains',
                    TERRAIN_LAYER_FILL.plains,
                    'desert',
                    TERRAIN_LAYER_FILL.desert,
                    'forests',
                    TERRAIN_LAYER_FILL.forests,
                    'mountains',
                    TERRAIN_LAYER_FILL.mountains,
                    'coastal',
                    TERRAIN_LAYER_FILL.coastal,
                    TERRAIN_LAYER_FILL.plains,
                  ],
                  'fill-opacity': 1,
                },
              });
            }
            const coastGj = coastlinesToGeoJson(terrainJson);
            if (coastGj.features.length > 0) {
              map.addSource(COAST_SOURCE, { type: 'geojson', data: coastGj });
              map.addLayer({
                id: COAST_LINE_LAYER,
                type: 'line',
                source: COAST_SOURCE,
                paint: {
                  'line-color': '#1a2835',
                  'line-width': 1.1,
                  'line-opacity': 0.5,
                },
              });
            }
          } catch {
            /* Terrain is optional; bad JSON or MapLibre reject should not block the political map. */
          }
        }

        map.addSource(SOURCE_ID, {
          type: 'geojson',
          data: geojson,
          promoteId: 'house_id',
        });

        map.addLayer({
          id: FILL_LAYER,
          type: 'fill',
          source: SOURCE_ID,
          paint: {
            'fill-color': [
              'case',
              ['boolean', ['feature-state', 'selected'], false],
              '#e8d5a3',
              ['boolean', ['feature-state', 'hover'], false],
              '#c4a574',
              ['coalesce', ['feature-state', 'fill'], ['get', 'default_fill'], '#4a4d5c'],
            ],
            'fill-opacity': [
              'case',
              ['boolean', ['feature-state', 'selected'], false],
              0.92,
              ['boolean', ['feature-state', 'hover'], false],
              0.82,
              0.68,
            ],
          },
        });

        map.addLayer({
          id: LINE_LAYER,
          type: 'line',
          source: SOURCE_ID,
          paint: {
            /* Slightly lighter than the void background so borders read on #070910. */
            'line-color': '#3d3448',
            'line-opacity': 0.9,
            'line-width': [
              'case',
              ['boolean', ['feature-state', 'selected'], false],
              3,
              ['boolean', ['feature-state', 'hover'], false],
              2,
              1.2,
            ],
          },
        });

        map.fitBounds(boundsFromGeoJSON(geojson), { padding: 56, duration: 0, maxZoom: 9 });
        map.resize();
        requestAnimationFrame(() => {
          map.resize();
        });

        const clearHover = () => {
          const hid = hoverIdRef.current;
          if (hid) {
            try {
              map.setFeatureState({ source: SOURCE_ID, id: hid }, { hover: false });
            } catch {
              /* ignore */
            }
            hoverIdRef.current = null;
          }
          popupRef.current?.remove();
          map.getCanvas().style.cursor = '';
        };

        map.on('mousemove', FILL_LAYER, (e) => {
          const f = e.features?.[0];
          const id =
            f?.properties?.house_id != null
              ? String(f.properties.house_id)
              : f?.id != null
                ? String(f.id)
                : null;
          const name = f?.properties?.name != null ? String(f.properties.name) : id ?? '';
          const fac = f?.properties?.faction_id != null ? String(f.properties.faction_id) : '';
          const region = f?.properties?.region_id != null ? String(f.properties.region_id) : '';

          if (id !== hoverIdRef.current) {
            if (hoverIdRef.current) {
              try {
                map.setFeatureState({ source: SOURCE_ID, id: hoverIdRef.current }, { hover: false });
              } catch {
                /* ignore */
              }
            }
            hoverIdRef.current = id;
            if (id) {
              try {
                map.setFeatureState({ source: SOURCE_ID, id }, { hover: true });
              } catch {
                /* ignore */
              }
            }
          }
          map.getCanvas().style.cursor = id ? 'pointer' : '';

          if (!minimalChrome && id && popupRef.current) {
            const sub = region ? `${escapeHtml(region)} · ` : '';
            popupRef.current
              .setLngLat(e.lngLat)
              .setHTML(
                `<div class="strategy-map-tip"><strong>${escapeHtml(name)}</strong><br/><span>${sub}${escapeHtml(
                  fac,
                )}</span></div>`,
              )
              .addTo(map);
          }
        });

        map.on('mouseleave', FILL_LAYER, clearHover);

        map.on('click', FILL_LAYER, (e) => {
          const f = e.features?.[0];
          const id =
            f?.properties?.house_id != null
              ? String(f.properties.house_id)
              : f?.id != null
                ? String(f.id)
                : null;
          const name = f?.properties?.name != null ? String(f.properties.name) : id ?? '';
          if (!id) return;

          const prev = selectedIdRef.current;
          if (prev && prev !== id) {
            try {
              map.setFeatureState({ source: SOURCE_ID, id: prev }, { selected: false });
            } catch {
              /* ignore */
            }
          }
          selectedIdRef.current = id;
          try {
            map.setFeatureState({ source: SOURCE_ID, id }, { selected: true });
          } catch {
            /* ignore */
          }
          if (!minimalChrome) setSelectionHud(name || id);
        });

        map.on('click', (e) => {
          const hits = map.queryRenderedFeatures(e.point, { layers: [FILL_LAYER] });
          if (hits.length > 0) return;
          const prev = selectedIdRef.current;
          if (prev) {
            try {
              map.setFeatureState({ source: SOURCE_ID, id: prev }, { selected: false });
            } catch {
              /* ignore */
            }
          }
          selectedIdRef.current = null;
          if (!minimalChrome) setSelectionHud(null);
        });

        async function pullWorld() {
          try {
            const res = await fetch('/api/state?for_map=1', { cache: 'no-store' });
            if (!res.ok) return;
            const data = (await res.json()) as WorldStateResponse;
            applyWorldFactionFills(
              map,
              data,
              housesPaletteRef.current,
              housesByRegionRef.current,
            );
          } catch {
            /* offline */
          }
        }

        await pullWorld();
        pollRef.current = setInterval(pullWorld, 30_000);
        postEmbedReadyOnce();
      } catch (err) {
        setMapError(err instanceof Error ? err.message : 'Failed to load map data.');
        postEmbedReadyOnce();
      }
    });

    const ro = new ResizeObserver(() => map.resize());
    ro.observe(container);

    return () => {
      ro.disconnect();
      if (pollRef.current) clearInterval(pollRef.current);
      popupRef.current?.remove();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  return (
    <div
      suppressHydrationWarning
      className={`strategy-map-root${embedMode ? ' strategy-map-root--embed' : ''}${
        minimalUi ? ' strategy-map-root--minimal' : ''
      }`}
      role="region"
      aria-label="Aeloria strategy map: pan and zoom to view faction regions"
    >
      {!minimalUi && (
        <p className="strategy-map-legend">
          2D vector map: terrain and coast under faction parcels (MapLibre). No satellite tiles—pan and zoom to
          explore.
        </p>
      )}
      <div ref={containerRef} className="strategy-map-canvas" />
      {mapError != null && (
        <div className="strategy-map-error" role="alert">
          <p className="strategy-map-error__title">Atlas could not load</p>
          <p className="strategy-map-error__msg">{mapError}</p>
          <p className="strategy-map-error__hint">
            If this page is embedded from Flask, run <code>npm run dev</code> so Next serves{' '}
            <code>/map</code> on port 3000, and set <code>MAP_PUBLIC_URL</code> in{' '}
            <code>.env</code> to that URL (see <code>.env.example</code>).
          </p>
        </div>
      )}
      {!minimalUi && selectionHud != null && (
        <div className="strategy-map-hud" role="status">
          Selected: {selectionHud}
        </div>
      )}
    </div>
  );
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
