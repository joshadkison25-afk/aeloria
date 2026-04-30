import { proxyFlaskJson } from '../_utils/flaskProxy';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  const url = new URL(request.url);
  const qs = url.searchParams.toString();
  return proxyFlaskJson({ path: `/api/explainability${qs ? `?${qs}` : ''}` });
}
