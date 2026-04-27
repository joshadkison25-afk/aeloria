import { redirect } from 'next/navigation';

/** Next is used for `/map` and API proxies; the playable game UI is Flask (`/` on port 5000). */
export default function Home() {
  redirect('/map');
}
