import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { proxyFlaskJson } from '../_utils/flaskProxy';

export const dynamic = 'force-dynamic';

/** Must match `_MAP_STATE_KEYS` in Flask `app.py` (map embed only needs political/UI fields). */
const MAP_WORLD_KEYS = [
  'tick',
  'world_date',
  'regions',
  'region_control',
  'faction_identities',
  'faction_power_state',
  'leadership_state',
] as const;

function slimWorldForMap(data: unknown): unknown {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return data;
  const o = data as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const k of MAP_WORLD_KEYS) {
    if (k in o) out[k] = o[k];
  }
  return out;
}

/**
 * Serves the live sim from Flask when available. If the Python backend is not
 * running (typical: only `next dev`), fall back to `world_state.json` in the
 * repo root so the map and faction pickers still populate.
 */
export async function GET(request: Request) {
  const incoming = new URL(request.url);
  const forMap = incoming.searchParams.get('for_map');
  const wantMap = forMap === '1' || forMap === 'true' || forMap === 'yes';
  const qs = wantMap ? '?for_map=1' : '';
  const res = await proxyFlaskJson({
    path: `/api/state${qs}`,
    method: 'GET',
  });
  if (res.status === 200) return res;
  try {
    const p = path.join(process.cwd(), 'world_state.json');
    const raw = await readFile(p, 'utf-8');
    const data = JSON.parse(raw) as unknown;
    const payload = wantMap ? slimWorldForMap(data) : data;
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  } catch {
    return res;
  }
}
