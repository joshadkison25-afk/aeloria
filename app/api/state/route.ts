import { proxyFlaskJson } from '../_utils/flaskProxy';

export const dynamic = 'force-dynamic';

/**
 * Proxies Flask `/api/state` (optionally `?for_map=1`) for MapLibre / strategy UI.
 */
export async function GET(request: Request) {
  const incoming = new URL(request.url);
  const qs = incoming.search || '';
  return proxyFlaskJson({ path: `/api/state${qs}` });
}
