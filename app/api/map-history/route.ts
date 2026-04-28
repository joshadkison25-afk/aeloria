import fs from 'fs';
import path from 'path';
import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export interface HistorySnapshot {
  tick: number;
  worldDate: string;
  filename: string;
  /** regionName → controlling faction name (raw game string) */
  regionControl: Record<string, string | null>;
  /** active_events slim list */
  activeEvents: { name: string; involved: string[]; severity: number; trend: string }[];
  primaryEvent: { name: string; severity: number; summary: string } | null;
}

export async function GET() {
  const historyDir = path.join(process.cwd(), 'history');

  let files: string[] = [];
  try {
    files = fs.readdirSync(historyDir).filter((f) => f.endsWith('.json'));
  } catch {
    return NextResponse.json([]);
  }

  const snapshots: HistorySnapshot[] = [];

  for (const file of files) {
    try {
      const raw = fs.readFileSync(path.join(historyDir, file), 'utf-8');
      const data = JSON.parse(raw) as Record<string, unknown>;

      const tick       = (data.tick      ?? 0) as number;
      const worldDate  = (data.world_date ?? `Tick ${tick}`) as string;
      const regions    = (data.regions    ?? {}) as Record<string, Record<string, unknown>>;
      const activeEvts = (data.active_events ?? []) as Record<string, unknown>[];
      const primary    = data.primary_event as Record<string, unknown> | undefined;

      const regionControl: Record<string, string | null> = {};
      for (const [name, region] of Object.entries(regions)) {
        regionControl[name] = (region.controller as string | null) ?? null;
      }

      const activeEvents = activeEvts.map((e) => ({
        name:     (e.name     ?? '') as string,
        involved: (e.involved ?? []) as string[],
        severity: (e.severity ?? 0)  as number,
        trend:    (e.trend    ?? '') as string,
      }));

      snapshots.push({
        tick,
        worldDate,
        filename: file,
        regionControl,
        activeEvents,
        primaryEvent: primary
          ? {
              name:     (primary.name     ?? '') as string,
              severity: (primary.severity ?? 0)  as number,
              summary:  (primary.summary  ?? '') as string,
            }
          : null,
      });
    } catch {
      // skip corrupt files
    }
  }

  // Sort ascending by tick
  snapshots.sort((a, b) => a.tick - b.tick);

  return NextResponse.json(snapshots);
}
