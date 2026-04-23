import dynamic from 'next/dynamic';

const FantasyMap = dynamic(() => import('@/components/Map'), {
  ssr: false,
  loading: () => (
    <div className="fantasy-map-loading">
      <div className="fantasy-map-loading__panel">
        <p className="fantasy-map-loading__eyebrow">Atlas Of Aeloria</p>
        <h1 className="fantasy-map-loading__title">Preparing The Map</h1>
        <p className="fantasy-map-loading__text">
          Drawing borders, setting wards, and unfurling the realm chart...
        </p>
      </div>
    </div>
  ),
});

export default function MapPage() {
  return <FantasyMap />;
}
