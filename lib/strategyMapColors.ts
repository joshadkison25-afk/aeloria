function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  h /= 360;
  s /= 100;
  l /= 100;
  if (s === 0) {
    const v = Math.round(l * 255);
    return [v, v, v];
  }
  const hue2rgb = (p: number, q: number, t: number) => {
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const r = hue2rgb(p, q, h + 1 / 3);
  const g = hue2rgb(p, q, h);
  const b = hue2rgb(p, q, h - 1 / 3);
  return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
}

function rgbToHex(r: number, g: number, b: number): string {
  return (
    '#' +
    [r, g, b]
      .map((x) => Math.max(0, Math.min(255, x)).toString(16).padStart(2, '0'))
      .join('')
  );
}

/** Deterministic faction tint (HSL string — fine for CSS / SVG). */
export function colorForFactionId(factionId: string): string {
  let hash = 0;
  const s = String(factionId);
  for (let i = 0; i < s.length; i += 1) hash = s.charCodeAt(i) + ((hash << 5) - hash);
  const h = Math.abs(hash) % 360;
  return `hsl(${h}, 58%, 48%)`;
}

/** Same hash as `colorForFactionId`, as `#rrggbb` for MapLibre paint. */
export function hexColorForFactionId(factionId: string): string {
  let hash = 0;
  const s = String(factionId);
  for (let i = 0; i < s.length; i += 1) hash = s.charCodeAt(i) + ((hash << 5) - hash);
  const h = Math.abs(hash) % 360;
  const [r, g, b] = hslToRgb(h, 58, 48);
  return rgbToHex(r, g, b);
}

/**
 * MapLibre data-driven `fill-color` is unreliable with `hsl(...)` feature strings.
 * Accept `#rrggbb` / `#rrggbbaa` or `hsl(h, s%, l%)` and emit hex.
 */
export function normalizeMapLibreColor(
  value: string | undefined,
  fallbackFaction: string,
): string {
  const v = (value ?? '').trim();
  if (/^#[0-9a-fA-F]{6}$/.test(v)) return v.toLowerCase();
  if (/^#[0-9a-fA-F]{8}$/.test(v)) return v.toLowerCase();
  const hsl = v.match(/^hsl\(\s*([\d.]+)\s*,\s*([\d.]+)%\s*,\s*([\d.]+)%\s*\)$/i);
  if (hsl) {
    const [r, g, b] = hslToRgb(Number(hsl[1]), Number(hsl[2]), Number(hsl[3]));
    return rgbToHex(r, g, b);
  }
  return hexColorForFactionId(fallbackFaction);
}
