'use client';

import WorldMapEditor from '@/components/WorldMapEditor';

/**
 * Client-only page (no dynamic() wrapper) so the map always mounts reliably.
 * Metadata lives in ./layout.tsx.
 */
export default function WorldMapPage() {
  return <WorldMapEditor />;
}
