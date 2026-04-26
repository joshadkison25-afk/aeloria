import { NextRequest, NextResponse } from 'next/server';
import { promises as fs } from 'node:fs';
import path from 'node:path';

function getMapsDir(): string {
  const configuredPath = process.env.LORE_DOCS_PATH?.trim();
  const lorePath = configuredPath || path.resolve(process.cwd(), 'lore');
  return path.join(lorePath, 'maps');
}

function safeFileName(fileName: string): string {
  return fileName.toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '');
}

export async function GET(_request: NextRequest, context: { params: { fileName: string } }) {
  const mapsDir = getMapsDir();
  const rawName = context.params.fileName;
  const fileName = safeFileName(rawName.endsWith('.json') ? rawName : `${rawName}.json`);

  if (!fileName) {
    return NextResponse.json({ error: 'Invalid map file name.' }, { status: 400 });
  }

  try {
    const filePath = path.join(mapsDir, fileName);
    const content = await fs.readFile(filePath, 'utf-8');
    return NextResponse.json({
      fileName,
      layout: JSON.parse(content),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown map load error.';
    return NextResponse.json(
      {
        error: 'Failed to load map layout.',
        details: message,
      },
      { status: 404 },
    );
  }
}
