/**
 * SSE proxy: streams Flask /api/events to the browser.
 * Uses the edge runtime for efficient streaming without buffering.
 */
export const runtime = 'edge';
export const dynamic = 'force-dynamic';

const FLASK_URL = process.env.PYTHON_BACKEND_URL ?? 'http://localhost:5000';

export async function GET() {
  let flaskRes: Response;
  try {
    flaskRes = await fetch(`${FLASK_URL}/api/events`, {
      headers: { Accept: 'text/event-stream' },
      cache: 'no-store',
    });
  } catch {
    // Flask not running — return a single "offline" event so the client knows
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode('data: {"type":"offline"}\n\n'),
        );
        controller.close();
      },
    });
    return new Response(body, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
      },
    });
  }

  if (!flaskRes.ok || !flaskRes.body) {
    return new Response('data: {"type":"offline"}\n\n', {
      headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
    });
  }

  return new Response(flaskRes.body, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      'X-Accel-Buffering': 'no',
    },
  });
}
