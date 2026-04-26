import { NextResponse } from 'next/server';

const FLASK_BASE_URL =
  process.env.PYTHON_BACKEND_URL?.replace(/\/+$/, '') || 'http://localhost:5000';

type ProxyRequestOptions = {
  path: string;
  method?: 'GET' | 'POST';
  body?: unknown;
};

export async function proxyFlaskJson(options: ProxyRequestOptions) {
  const { path, method = 'GET', body } = options;
  const targetUrl = `${FLASK_BASE_URL}${path}`;

  try {
    const response = await fetch(targetUrl, {
      method,
      headers: {
        'Content-Type': 'application/json',
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
    });

    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = { error: 'Backend returned non-JSON response.' };
    }

    if (!response.ok) {
      return NextResponse.json(
        {
          error: 'Python backend request failed.',
          backendStatus: response.status,
          details: payload,
        },
        { status: response.status },
      );
    }

    return NextResponse.json(payload, { status: 200 });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : 'Unknown proxy error while contacting backend.';

    return NextResponse.json(
      {
        error: 'Unable to reach Python backend.',
        details: message,
      },
      { status: 502 },
    );
  }
}
