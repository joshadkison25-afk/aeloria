import { NextRequest } from 'next/server';
import { proxyFlaskJson } from '../_utils/flaskProxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  return proxyFlaskJson({ path: '/api/player-action', method: 'POST', body });
}

export async function GET() {
  return proxyFlaskJson({ path: '/api/player-actions/pending' });
}
