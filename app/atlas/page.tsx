import FantasyMap from '@/components/Map';
import { MapErrorBoundary } from '@/components/MapErrorBoundary';

/**
 * Read-only atlas for the generated Aeloria territory map.
 */
export default function AtlasPage() {
  return (
    <MapErrorBoundary kind="builder">
      <FantasyMap />
    </MapErrorBoundary>
  );
}
