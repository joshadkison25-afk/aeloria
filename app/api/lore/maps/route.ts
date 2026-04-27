import { NextRequest, NextResponse } from 'next/server';
import { promises as fs } from 'node:fs';
import path from 'node:path';

import { getMapSaveDirCandidates, writeLayoutToFirstWritableDir } from '@/lib/mapLayoutStorage';

type SavedMapLayout = {
  metadata: {
    speciesSet: string;
    configMode: string;
    version: number;
    savedAt: string;
  };
  ownership: Record<string, string | null>;
};

function safeFileName(fileName: string): string {
  return fileName.toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '');
}

export async function GET() {
  const names = new Set<string>();
  const errors: string[] = [];
  let firstOkDir = '';
  for (const mapsDir of getMapSaveDirCandidates()) {
    try {
      await fs.mkdir(mapsDir, { recursive: true });
      if (!firstOkDir) firstOkDir = mapsDir;
      const entries = await fs.readdir(mapsDir, { withFileTypes: true });
      for (const entry of entries) {
        if (entry.isFile() && entry.name.endsWith('.json')) names.add(entry.name);
      }
    } catch (err) {
      errors.push(`${mapsDir}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  if (names.size === 0 && errors.length >= getMapSaveDirCandidates().length) {
    return NextResponse.json(
      {
        error: 'Failed to list saved maps.',
        details: errors.join(' | '),
      },
      { status: 500 },
    );
  }
  return NextResponse.json({
    mapsPath: firstOkDir || path.join(process.cwd(), 'lore', 'maps'),
    files: Array.from(names).sort(),
  });
}

export async function POST(request: NextRequest) {
  try {
    const body = (await request.json()) as {
      fileName?: string;
      layout?: SavedMapLayout;
    };

    const requestedName = body.fileName || 'map_custom.json';
    const fileName = safeFileName(requestedName.endsWith('.json') ? requestedName : `${requestedName}.json`);
    if (!fileName) {
      return NextResponse.json({ error: 'fileName is required.' }, { status: 400 });
    }
    if (!body.layout || !body.layout.ownership || !body.layout.metadata) {
      return NextResponse.json({ error: 'layout with metadata and ownership is required.' }, { status: 400 });
    }

    const { filePath, mapsDir } = await writeLayoutToFirstWritableDir(fileName, body.layout);
    return NextResponse.json({ ok: true, fileName, path: filePath, mapsDir });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown map save error.';
    return NextResponse.json(
      {
        error: 'Failed to save map layout.',
        details: message,
      },
      { status: 500 },
    );
  }
}
