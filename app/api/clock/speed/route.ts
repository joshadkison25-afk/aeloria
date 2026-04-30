import { proxyFlaskJson } from '../../_utils/flaskProxy';

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));
  return proxyFlaskJson({ path: '/api/clock/speed', method: 'POST', body });
}
