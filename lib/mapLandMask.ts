/**
 * Classifies atlas pixels as water vs land from the hand-painted basemap.
 * Tuned for typical fantasy “blue sea / green-brown land” palettes; if a new
 * base image misclassifies coasts, adjust thresholds or sample density here.
 */

export type MapHexForMask = { id: string; x: number; y: number };

const DEFAULT_HEX_W = 1.7;
const DEFAULT_HEX_H = 1.7;

function isWater(r: number, g: number, b: number, a: number): boolean {
  if (a < 12) return true;
  const sum = r + g + b;
  if (sum < 15) return true;

  // Bright snow / highland — not ocean
  if (r + g + b > 400 && r > 95 && g > 95) return false;
  // Forest / grass: green dominates
  if (g > 52 && g >= b - 20 && g >= r - 30) return false;
  // Tan / arid / rock
  if (r > 72 && g > 48 && b < g + 10 && b < r) return false;
  if (r > 65 && g > 50 && b < 85 && b < r) return false;

  // Open ocean: blue clearly ahead
  if (b > r + 22 && b > g + 14 && b > 58) return true;
  // Teal / deep shallows
  if (b > 78 && g > 50 && b > r + 12 && sum < 360) return true;
  // Murky / dark water
  if (sum < 95 && b >= r - 3 && b >= g - 2 && b > 38) return true;

  return false;
}

function waterScore(r: number, g: number, b: number): number {
  const blueLead = b - Math.max(r, g);
  const tealLead = b - r + (g - r) * 0.45;
  const darkness = Math.max(0, 120 - (r + g + b) / 3);
  let score = 0;
  score += blueLead * 0.9;
  score += tealLead * 0.28;
  score += darkness * 0.16;
  if (b > 72) score += 8;
  if (g > 68 && b > 88 && r < 95) score += 6;
  return score;
}

function landScore(r: number, g: number, b: number): number {
  const greenLead = g - b;
  const warmLead = r - b;
  const brightness = (r + g + b) / 3;
  let score = 0;
  score += greenLead * 0.7;
  score += warmLead * 0.26;
  score += Math.max(0, brightness - 70) * 0.14;
  if (r > 92 && g > 84 && b > 84) score += 22; // snow and bright mountain faces
  if (r > 90 && g > 66 && b < 105) score += 12; // rock / dirt / arid
  return score;
}

function sampleLandLikelihood(
  data: ImageData,
  w: number,
  h: number,
  u: number,
  v: number,
): number {
  const px = Math.min(w - 1, Math.max(0, Math.floor(u * w)));
  const py = Math.min(h - 1, Math.max(0, Math.floor(v * h)));
  const i = (py * w + px) * 4;
  const r = data.data[i];
  const g = data.data[i + 1];
  const b = data.data[i + 2];
  const a = data.data[i + 3];
  if (isWater(r, g, b, a)) return 0;
  const wScore = waterScore(r, g, b);
  const lScore = landScore(r, g, b);
  const spread = lScore - wScore;
  if (spread >= 18) return 1;
  if (spread <= -18) return 0;
  return Math.min(1, Math.max(0, 0.5 + spread / 48));
}

const SAMPLE_UV_CENTER_HEAVY: [number, number][] = [
  [0.5, 0.5],
  [0.5, 0.28],
  [0.5, 0.72],
  [0.32, 0.52],
  [0.68, 0.52],
  [0.28, 0.4],
  [0.72, 0.4],
  [0.5, 0.78],
  [0.2, 0.65],
  [0.8, 0.65],
  [0.36, 0.26],
  [0.64, 0.26],
  [0.36, 0.78],
  [0.64, 0.78],
];

function hexIsMostlyLand(
  data: ImageData,
  w: number,
  h: number,
  hex: MapHexForMask,
  hexW: number,
  hexH: number,
  viewW: number,
  viewH: number,
): boolean {
  let likelihoodSum = 0;
  let centerBias = 0;
  for (let i = 0; i < SAMPLE_UV_CENTER_HEAVY.length; i += 1) {
    const [tu, tv] = SAMPLE_UV_CENTER_HEAVY[i];
    const cx = hex.x + tu * hexW;
    const cy = hex.y + tv * hexH;
    const u = cx / viewW;
    const v = cy / viewH;
    const p = sampleLandLikelihood(data, w, h, u, v);
    likelihoodSum += p;
    if (i <= 4) centerBias += p;
  }
  const n = SAMPLE_UV_CENTER_HEAVY.length;
  const avg = likelihoodSum / n;
  const core = centerBias / 5;
  // Clean cut for coasts: only treat as land once confidence is clearly above water.
  if (avg >= 0.58) return true;
  if (avg <= 0.38) return false;
  // Ambiguous fringe pixels defer to center/core; helps islands survive while oceans stay clean.
  return core >= 0.6;
}

/**
 * Renders the image into a downscaled canvas and returns whether each hex center
 * (majority of subsamples) lies on “land” pixels.
 */
export async function buildHexLandMask(
  imageSrc: string,
  hexes: MapHexForMask[],
  viewW: number,
  viewH: number,
  opts?: { hexW?: number; hexH?: number; maxSampleWidth?: number },
): Promise<Record<string, boolean>> {
  const hexW = opts?.hexW ?? DEFAULT_HEX_W;
  const hexH = opts?.hexH ?? DEFAULT_HEX_H;
  const maxW = Math.max(256, Math.min(1024, opts?.maxSampleWidth ?? 768));

  const out: Record<string, boolean> = {};
  for (const h of hexes) out[h.id] = true;

  const img = new Image();
  img.crossOrigin = 'anonymous';
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve();
    img.onerror = () => reject(new Error(`Map land mask: failed to load ${imageSrc}`));
    img.src = imageSrc;
  });

  const nw = img.naturalWidth;
  const nh = img.naturalHeight;
  if (nw < 1 || nh < 1) return out;

  const tw = Math.min(maxW, nw);
  const th = Math.round((nh * tw) / nw);
  const canvas = document.createElement('canvas');
  canvas.width = tw;
  canvas.height = th;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) return out;
  ctx.drawImage(img, 0, 0, tw, th);
  const data = ctx.getImageData(0, 0, tw, th);

  for (const hex of hexes) {
    out[hex.id] = hexIsMostlyLand(data, tw, th, hex, hexW, hexH, viewW, viewH);
  }
  return out;
}
