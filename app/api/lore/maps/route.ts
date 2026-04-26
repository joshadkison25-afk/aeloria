import { NextRequest, NextResponse } from 'next/server';
import { promises as fs } from 'node:fs';
import path from 'node:path';

type SavedMapLayout = {
  metadata: {
    speciesSet: string;
    configMode: string;
    version: number;
    savedAt: string;
  };
  ownership: Record<string, string | null>;
};

function getMapsDir(): string {
  const configuredPath = process.env.LORE_DOCS_PATH?.trim();
  const lorePath = configuredPath || path.resolve(process.cwd(), 'lore');
  return path.join(lorePath, 'maps');
}

function safeFileName(fileName: string): string {
  return fileName.toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '');
}

export async function GET() {
  const mapsDir = getMapsDir();
  try {
    await fs.mkdir(mapsDir, { recursive: true });
    const entries = await fs.readdir(mapsDir, { withFileTypes: true });
    const files = entries.filter((entry) => entry.isFile() && entry.name.endsWith('.json')).map((entry) => entry.name);
    return NextResponse.json({
      mapsPath: mapsDir,
      files: files.sort(),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown maps listing error.';
    return NextResponse.json(
      {
        error: 'Failed to list saved maps.',
        details: message,
      },
      { status: 500 },
    );
  }
}

export async function POST(request: NextRequest) {
  const mapsDir = getMapsDir();
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

    await fs.mkdir(mapsDir, { recursive: true });
    const filePath = path.join(mapsDir, fileName);
    await fs.writeFile(filePath, JSON.stringify(body.layout, null, 2), 'utf-8');
    return NextResponse.json({ ok: true, fileName, path: filePath });
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
