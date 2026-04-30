import { proxyFlaskJson } from '../_utils/flaskProxy';

export const dynamic = 'force-dynamic';

export async function GET() {
  return proxyFlaskJson({ path: '/api/council' });
}
