import { promises as fs } from 'node:fs';
import path from 'node:path';

/** Ordered: explicit override → lore_docs/maps → repo lore/maps. */
export function getMapSaveDirCandidates(): string[] {
  const unique = new Set<string>();
  const add = (p: string | undefined) => {
    const t = p?.trim();
    if (t) unique.add(t);
  };
  add(process.env.AELORIA_MAPS_SAVE_DIR);
  const loreDocs = process.env.LORE_DOCS_PATH?.trim();
  if (loreDocs) add(path.join(loreDocs, 'maps'));
  add(path.join(process.cwd(), 'lore', 'maps'));
  return Array.from(unique);
}

export async function writeLayoutToFirstWritableDir(
  fileName: string,
  layout: unknown,
): Promise<{ filePath: string; mapsDir: string }> {
  const json = JSON.stringify(layout, null, 2);
  const errors: string[] = [];
  for (const mapsDir of getMapSaveDirCandidates()) {
    try {
      await fs.mkdir(mapsDir, { recursive: true });
      const filePath = path.join(mapsDir, fileName);
      await fs.writeFile(filePath, json, 'utf-8');
      return { filePath, mapsDir };
    } catch (err) {
      errors.push(`${mapsDir}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  throw new Error(`Could not save map (tried ${errors.length} location(s)): ${errors.join(' | ')}`);
}

export async function readMapLayoutJson(fileName: string): Promise<{ layout: unknown; filePath: string }> {
  const tried: string[] = [];
  for (const mapsDir of getMapSaveDirCandidates()) {
    const filePath = path.join(mapsDir, fileName);
    try {
      const content = await fs.readFile(filePath, 'utf-8');
      return { layout: JSON.parse(content), filePath };
    } catch {
      tried.push(filePath);
    }
  }
  throw new Error(`Map file not found. Tried:\n${tried.join('\n')}`);
}
