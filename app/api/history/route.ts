import { proxyFlaskJson } from '../_utils/flaskProxy';

export async function GET() {
  return proxyFlaskJson({
    path: '/api/history',
    method: 'GET',
  });
}
