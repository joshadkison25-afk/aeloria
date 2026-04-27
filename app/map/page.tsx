'use client';

import dynamic from 'next/dynamic';
import { Component, type ErrorInfo, type ReactNode } from 'react';

class MapErrorBoundary extends Component<{ children: ReactNode }, { message: string | null }> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { message: null };
  }

  static getDerivedStateFromError(err: unknown): { message: string } {
    return { message: err instanceof Error ? err.message : 'Unknown error' };
  }

  componentDidCatch(err: Error, info: ErrorInfo) {
    console.error('Map error boundary:', err, info.componentStack);
  }

  render() {
    if (this.state.message) {
      return (
        <div className="fantasy-map-loading">
          <div className="fantasy-map-loading__panel">
            <p className="fantasy-map-loading__eyebrow">Atlas Of Aeloria</p>
            <h1 className="fantasy-map-loading__title">Map builder hit an error</h1>
            <p className="fantasy-map-loading__text" style={{ whiteSpace: 'pre-wrap' }}>
              {this.state.message}
            </p>
            <p className="fantasy-map-loading__text" style={{ marginTop: '1rem', opacity: 0.85 }}>
              If you were on <code>next dev</code>: stop all dev servers, run <code>npm run dev:clean</code>, then
              hard-refresh the browser (Ctrl+Shift+R). Stale <code>.next</code> chunks often cause “missing module”
              errors after pulls or branch switches.
            </p>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const FantasyMap = dynamic(
  () =>
    import('@/components/Map').catch((err) => {
      console.error('Failed to load Map chunk:', err);
      const msg = err instanceof Error ? err.message : String(err);
      return {
        default: function MapLoadFailed() {
          return (
            <div className="fantasy-map-loading">
              <div className="fantasy-map-loading__panel">
                <p className="fantasy-map-loading__eyebrow">Atlas Of Aeloria</p>
                <h1 className="fantasy-map-loading__title">Could not load map module</h1>
                <p className="fantasy-map-loading__text" style={{ whiteSpace: 'pre-wrap' }}>
                  {msg}
                </p>
                <p className="fantasy-map-loading__text" style={{ marginTop: '1rem', opacity: 0.85 }}>
                  Run <code>npm run dev:clean</code> and try again.
                </p>
              </div>
            </div>
          );
        },
      };
    }),
  {
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
  },
);

export default function MapPage() {
  return (
    <MapErrorBoundary>
      <FantasyMap />
    </MapErrorBoundary>
  );
}
