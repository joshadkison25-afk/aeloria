import { NextRequest, NextResponse } from 'next/server';

import { readMapLayoutJson } from '@/lib/mapLayoutStorage';

function safeFileName(fileName: string): string {
  return fileName.toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '');
}

export async function GET(_request: NextRequest, context: { params: { fileName: string } }) {
  const rawName = context.params.fileName;
  const fileName = safeFileName(rawName.endsWith('.json') ? rawName : `${rawName}.json`);

  if (!fileName) {
    return NextResponse.json({ error: 'Invalid map file name.' }, { status: 400 });
  }

  try {
    const { layout, filePath } = await readMapLayoutJson(fileName);
    return NextResponse.json({
      fileName,
      path: filePath,
      layout,
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
