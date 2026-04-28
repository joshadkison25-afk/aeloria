import type { Metadata } from 'next';
import type { ReactNode } from 'react';

export const metadata: Metadata = {
  title: 'Aeloria — World Map',
  description: 'Interactive fantasy world map location editor for Aeloria.',
};

export default function WorldMapLayout({ children }: { children: ReactNode }) {
  return children;
}
