'use client';

import { Component, type ErrorInfo, type ReactNode } from 'react';

type Kind = 'strategy' | 'builder';

const titles: Record<Kind, string> = {
  strategy: 'Strategy map hit an error',
  builder: 'Map builder hit an error',
};

export class MapErrorBoundary extends Component<
  { children: ReactNode; kind?: Kind },
  { message: string | null }
> {
  constructor(props: { children: ReactNode; kind?: Kind }) {
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
      const kind = this.props.kind ?? 'strategy';
      return (
        <div className="fantasy-map-loading">
          <div className="fantasy-map-loading__panel">
            <p className="fantasy-map-loading__eyebrow">Atlas Of Aeloria</p>
            <h1 className="fantasy-map-loading__title">{titles[kind]}</h1>
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
