import { redirect } from 'next/navigation';

/** Product map is the city-pin atlas (`/worldmap`) only. */
export default function MapPage() {
  redirect('/worldmap');
}
