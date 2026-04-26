import { NextResponse } from 'next/server';
import { promises as fs } from 'node:fs';
import path from 'node:path';

type LoreFaction = {
  id: string;
  name: string;
  identity: {
    sourceFile: string;
    sourcePath: string;
  };
};

type LoreSpecies = {
  id: string;
  name: string;
  factions: LoreFaction[];
};

function toId(value: string): string {
  return value
    .toLowerCase()
    .replace(/\.[^/.]+$/, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

export async function GET() {
  const configuredPath = process.env.LORE_DOCS_PATH?.trim();
  const lorePath = configuredPath || path.resolve(process.cwd(), 'lore');

  try {
    const dirEntries = await fs.readdir(lorePath, { withFileTypes: true });
    const supportedFiles = dirEntries.filter(
      (entry) =>
        entry.isFile() &&
        (entry.name.toLowerCase().endsWith('.pdf') ||
          entry.name.toLowerCase().endsWith('.md') ||
          entry.name.toLowerCase().endsWith('.txt')),
    );

    const species: LoreSpecies[] = supportedFiles.map((entry) => {
      const baseName = entry.name.replace(/\.[^/.]+$/, '');
      const speciesId = toId(baseName);
      const faction: LoreFaction = {
        id: speciesId,
        name: baseName,
        identity: {
          sourceFile: entry.name,
          sourcePath: path.join(lorePath, entry.name),
        },
      };

      return {
        id: speciesId,
        name: baseName,
        factions: [faction],
      };
    });

    return NextResponse.json({
      sourcePath: lorePath,
      species,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error while reading lore docs.';
    return NextResponse.json(
      {
        error: 'Failed to load lore species definitions.',
        details: message,
      },
      { status: 500 },
    );
  }
}
