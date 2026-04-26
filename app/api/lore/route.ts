import { NextResponse } from 'next/server';
import { promises as fs } from 'node:fs';
import path from 'node:path';

type SpeciesRow = {
  id: string;
  name: string;
};

type LocationRow = {
  id: string;
  species: SpeciesRow[];
};

const MAX_SPECIES_PER_LOCATION = 5;
const ALLOWED_EXTENSIONS = new Set(['.md', '.txt', '.json']);
const MASTER_LORE_FILE = 'master_lore.md';

function toId(value: string): string {
  return value
    .toLowerCase()
    .replace(/\.[^/.]+$/, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function uniqueById(rows: SpeciesRow[]): SpeciesRow[] {
  const seen = new Set<string>();
  const output: SpeciesRow[] = [];
  for (const row of rows) {
    if (!row.id || seen.has(row.id)) continue;
    seen.add(row.id);
    output.push(row);
  }
  return output;
}

function cleanSpeciesName(raw: string): string {
  const cleaned = raw
    .replace(/[^\p{L}\s\-']/gu, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (cleaned.length < 3) return '';
  if (!/[A-Za-z]/.test(cleaned)) return '';
  return cleaned;
}

function fromNames(names: string[]): SpeciesRow[] {
  const results: SpeciesRow[] = [];
  for (const name of names) {
    const cleaned = cleanSpeciesName(name);
    if (!cleaned) continue;
    results.push({ id: toId(cleaned), name: cleaned });
  }
  return uniqueById(results).slice(0, MAX_SPECIES_PER_LOCATION);
}

function extractSpeciesFromText(text: string): SpeciesRow[] {
  const names: string[] = [];
  const lines = text.split(/\r?\n/);
  const sectionHeader = /^(?:#{1,6}\s*)?(Species|Races|Inhabitants|MAP_SPECIES)\s*:?\s*$/i;
  const bulletLine = /^\s*[-*•]\s+(.+?)\s*$/;

  for (let i = 0; i < lines.length; i += 1) {
    if (!sectionHeader.test(lines[i])) continue;
    for (let j = i + 1; j < lines.length; j += 1) {
      const line = lines[j];
      if (/^(?:#{1,6}\s*)?[A-Za-z][\w\s'-]{1,40}\s*:?\s*$/.test(line) && !bulletLine.test(line)) break;
      if (line.trim() === '') continue;
      const bulletMatch = line.match(bulletLine);
      if (!bulletMatch?.[1]) {
        if (names.length > 0) break;
        continue;
      }
      names.push(bulletMatch[1]);
      if (names.length >= MAX_SPECIES_PER_LOCATION) break;
    }
    if (names.length >= MAX_SPECIES_PER_LOCATION) break;
  }
  return fromNames(names);
}

function extractLocationsFromMasterText(text: string): LocationRow[] {
  const locations: LocationRow[] = [];
  const lines = text.split(/\r?\n/);
  const locationHeader = /^\s*#{1,6}\s*LOCATION\s*:\s*(.+?)\s*$/i;

  let currentLocationName = '';
  let currentBlock: string[] = [];

  const flush = () => {
    if (!currentLocationName) return;
    const species = extractSpeciesFromText(currentBlock.join('\n'));
    const locationId = toId(currentLocationName);
    locations.push({ id: locationId, species });
    console.log(
      `[api/lore] location=${locationId} extractedSpecies=${species.length} names=${species.map((s) => s.name).join('|') || '(none)'}`,
    );
  };

  for (const line of lines) {
    const match = line.match(locationHeader);
    if (match?.[1]) {
      flush();
      currentLocationName = match[1].trim();
      currentBlock = [];
      continue;
    }
    if (currentLocationName) currentBlock.push(line);
  }

  flush();
  return locations;
}

function extractSpeciesFromJson(rawJson: string): SpeciesRow[] {
  try {
    const parsed = JSON.parse(rawJson) as unknown;
    const candidates: string[] = [];

    const collect = (value: unknown) => {
      if (!value || typeof value !== 'object') return;
      if (Array.isArray(value)) {
        for (const item of value) collect(item);
        return;
      }
      const record = value as Record<string, unknown>;
      const species = record.species;
      if (Array.isArray(species)) {
        for (const entry of species) {
          if (!entry || typeof entry !== 'object') continue;
          const row = entry as Record<string, unknown>;
          if (typeof row.name === 'string') candidates.push(row.name);
        }
      }
      for (const child of Object.values(record)) collect(child);
    }
    collect(parsed);

    return fromNames(candidates);
  } catch {
    return [];
  }
}

export async function GET() {
  const projectRoot = process.cwd();
  const configuredLorePath = process.env.LORE_DOCS_PATH?.trim() || 'C:\\Users\\Josh\\Desktop\\lore_docs';
  const loreDocsPath = configuredLorePath || path.resolve(projectRoot, 'lore_docs');
  console.log(`[api/lore] projectRoot=${projectRoot}`);
  console.log(`[api/lore] configuredLorePath=${configuredLorePath || '(not set)'}`);
  console.log(`[api/lore] resolvedLoreDocsPath=${loreDocsPath}`);

  try {
    const stat = await fs.stat(loreDocsPath);
    if (!stat.isDirectory()) {
      return NextResponse.json(
        {
          error: 'Lore folder exists but is not a directory.',
          folder: loreDocsPath,
        },
        { status: 500 },
      );
    }
  } catch {
    console.log('[api/lore] filesFound=0 (lore_docs missing)');
    return NextResponse.json(
      {
        error: 'Lore folder not found.',
        folder: loreDocsPath,
      },
      { status: 404 },
    );
  }

  try {
    const entries = await fs.readdir(loreDocsPath, { withFileTypes: true });
    const files = entries.filter((entry) => entry.isFile());
    console.log(`[api/lore] filesFound=${files.length}`);
    const locations: LocationRow[] = [];
    const masterPath = path.join(loreDocsPath, MASTER_LORE_FILE);
    let masterContent = '';
    try {
      masterContent = await fs.readFile(masterPath, 'utf-8');
    } catch {
      console.log(`[api/lore] skippedFile=${MASTER_LORE_FILE} reason=missing_or_unreadable`);
      return NextResponse.json({ locations: [] });
    }

    const masterLocations = extractLocationsFromMasterText(masterContent);
    if (masterLocations.length > 0) {
      locations.push(...masterLocations);
    } else {
      const extension = path.extname(MASTER_LORE_FILE).toLowerCase();
      if (!ALLOWED_EXTENSIONS.has(extension)) {
        console.log(`[api/lore] skippedFile=${MASTER_LORE_FILE} reason=unsupported_extension`);
      } else {
        const locationId = toId(MASTER_LORE_FILE.replace(/\.[^/.]+$/, ''));
        const species = extension === '.json' ? extractSpeciesFromJson(masterContent) : extractSpeciesFromText(masterContent);
        console.log(`[api/lore] location=${locationId} extractedSpecies=${species.length} names=${species.map((s) => s.name).join('|') || '(none)'}`);
        locations.push({ id: locationId, species });
      }
    }

    const uniqueLocations = new Map<string, SpeciesRow[]>();
    for (const row of locations) {
      const existing = uniqueLocations.get(row.id) || [];
      uniqueLocations.set(row.id, uniqueById([...existing, ...row.species]).slice(0, MAX_SPECIES_PER_LOCATION));
    }
    const normalizedLocations: LocationRow[] = Array.from(uniqueLocations.entries()).map(([id, species]) => ({ id, species }));

    return NextResponse.json({ locations: normalizedLocations });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error reading lore files.';
    return NextResponse.json(
      {
        error: 'Failed to read lore files.',
        details: message,
      },
      { status: 500 },
    );
  }
}
