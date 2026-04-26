import { proxyFlaskJson } from '../_utils/flaskProxy';

export async function POST() {
  return proxyFlaskJson({
    path: '/api/tick',
    method: 'POST',
  });
}
