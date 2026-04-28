import { redirect } from 'next/navigation';

/** Next `/` → pin/city world map. `/map` also redirects here. */
export default function Home() {
  redirect('/worldmap');
}
