import { MapErrorBoundary } from '@/components/MapErrorBoundary';
import StrategyMap from '@/components/StrategyMap';

export default function MapPage() {
  return (
    <MapErrorBoundary kind="strategy">
      <StrategyMap />
    </MapErrorBoundary>
  );
}
