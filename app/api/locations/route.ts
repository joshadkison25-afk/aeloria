import { NextRequest, NextResponse } from 'next/server';
import path from 'path';
import fs from 'fs';

export const dynamic = 'force-dynamic';

export interface LocationPin {
  id: string;
  label: string;
  type: 'city' | 'settlement' | 'landmark' | 'faction_capital' | 'house_seat' | 'dungeon' | 'port';
  faction?: string;
  house?: string;
  /** Matches a key in world_state.json `regions` for live ownership tracking */
  regionId?: string;
  x: number;
  y: number;
  notes?: string;
  createdAt: string;
}

function dataFilePath(): string {
  return path.join(process.cwd(), 'public', 'data', 'locations.json');
}

function readPins(): LocationPin[] {
  try {
    const raw = fs.readFileSync(dataFilePath(), 'utf-8');
    return JSON.parse(raw) as LocationPin[];
  } catch {
    return [];
  }
}

function writePins(pins: LocationPin[]): void {
  fs.writeFileSync(dataFilePath(), JSON.stringify(pins, null, 2), 'utf-8');
}

export async function GET() {
  const pins = readPins();
  return NextResponse.json(pins);
}

export async function POST(request: NextRequest) {
  let body: Partial<LocationPin>;
  try {
    body = (await request.json()) as Partial<LocationPin>;
  } catch {
    return NextResponse.json({ error: 'Invalid JSON body' }, { status: 400 });
  }

  const { label, type, faction, house, regionId, x, y, notes } = body;
  if (!label || !type || x == null || y == null) {
    return NextResponse.json({ error: 'label, type, x and y are required' }, { status: 400 });
  }

  const newPin: LocationPin = {
    id: `loc_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
    label,
    type,
    ...(faction  ? { faction }  : {}),
    ...(house    ? { house }    : {}),
    ...(regionId ? { regionId } : {}),
    x,
    y,
    ...(notes ? { notes } : {}),
    createdAt: new Date().toISOString(),
  };

  const pins = readPins();
  pins.push(newPin);
  writePins(pins);

  return NextResponse.json(newPin, { status: 201 });
}

export async function PATCH(request: NextRequest) {
  let body: Partial<LocationPin> & { id: string };
  try {
    body = (await request.json()) as Partial<LocationPin> & { id: string };
  } catch {
    return NextResponse.json({ error: 'Invalid JSON body' }, { status: 400 });
  }

  if (!body.id) {
    return NextResponse.json({ error: 'id is required' }, { status: 400 });
  }

  const pins = readPins();
  const idx = pins.findIndex((p) => p.id === body.id);
  if (idx === -1) {
    return NextResponse.json({ error: 'Pin not found' }, { status: 404 });
  }

  const updated: LocationPin = {
    ...pins[idx],
    ...(body.label    != null      ? { label:    body.label }    : {}),
    ...(body.type     != null      ? { type:     body.type }     : {}),
    ...(body.faction  !== undefined ? { faction:  body.faction }  : {}),
    ...(body.house    !== undefined ? { house:    body.house }    : {}),
    ...(body.regionId !== undefined ? { regionId: body.regionId } : {}),
    ...(body.x        != null      ? { x:        body.x }        : {}),
    ...(body.y        != null      ? { y:        body.y }        : {}),
    ...(body.notes    !== undefined ? { notes:    body.notes }    : {}),
  };

  pins[idx] = updated;
  writePins(pins);

  return NextResponse.json(updated);
}

export async function DELETE(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const id = searchParams.get('id');
  if (!id) {
    return NextResponse.json({ error: 'id query param required' }, { status: 400 });
  }

  const pins = readPins();
  const next = pins.filter((p) => p.id !== id);
  if (next.length === pins.length) {
    return NextResponse.json({ error: 'Pin not found' }, { status: 404 });
  }

  writePins(next);
  return NextResponse.json({ ok: true });
}
