import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { proxyFlaskJson } from '../_utils/flaskProxy';

export const dynamic = 'force-dynamic';

/**
 * Serves the live sim from Flask when available. If the Python backend is not
 * running (typical: only `next dev`), fall back to `world_state.json` in the
 * repo root so the map and faction pickers still populate.
 */
export async function GET() {
  const res = await proxyFlaskJson({
    path: '/api/state',
    method: 'GET',
  });
  if (res.status === 200) return res;
  try {
    const p = path.join(process.cwd(), 'world_state.json');
    const raw = await readFile(p, 'utf-8');
    const data = JSON.parse(raw) as unknown;
    return new Response(JSON.stringify(data), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  } catch {
    return res;
  }
}
