/**
 * Proxies Flask static files (portraits, etc.) through Next so the map can use
 * same-origin URLs and avoid mixed-content / CORS issues.
 *
 * Example: GET /api/game-static/static/illustrations/characters/foo.png
 */
import { NextRequest, NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

const FLASK_BASE =
  process.env.PYTHON_BACKEND_URL?.replace(/\/+$/, '') || 'http://localhost:5000';

export async function GET(
  _req: NextRequest,
  context: { params: { path: string[] } },
) {
  const segments = context.params.path ?? [];
  if (!segments.length) {
    return NextResponse.json({ error: 'Missing path' }, { status: 400 });
  }

  const url = `${FLASK_BASE}/${segments.join('/')}`;
  try {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) {
      return NextResponse.json({ error: 'Upstream not found' }, { status: res.status });
    }
    const ct = res.headers.get('content-type') ?? 'application/octet-stream';
    const buf = await res.arrayBuffer();
    return new NextResponse(buf, {
      status: 200,
      headers: {
        'Content-Type': ct,
        'Cache-Control': 'public, max-age=3600',
      },
    });
  } catch {
    return NextResponse.json({ error: 'Flask unreachable' }, { status: 502 });
  }
}
