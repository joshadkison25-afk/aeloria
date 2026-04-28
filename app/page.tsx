import { redirect } from 'next/navigation';

/** Next home redirects to the strategy map; Flask home iframe uses `/worldmap` (see HOME_MAP_IFRAME_URL in app.py). */
export default function Home() {
  redirect('/map');
}
