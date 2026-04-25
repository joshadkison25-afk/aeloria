"""Generate SVG heraldic coat of arms for races and houses/clans (no API required)."""
import math
from pathlib import Path

RACE_DIR  = Path(__file__).parent / "static" / "illustrations" / "races"
HOUSE_DIR = Path(__file__).parent / "static" / "illustrations" / "houses"
RACE_DIR.mkdir(parents=True, exist_ok=True)
HOUSE_DIR.mkdir(parents=True, exist_ok=True)

W, H   = 200, 240
CX, CY = 100, 116

SHIELD = "M10,10 L190,10 L190,148 Q190,208 100,232 Q10,208 10,148 Z"
LINER  = "M26,26 L174,26 L174,146 Q174,196 100,218 Q26,196 26,146 Z"


# ── SVG wrapper ─────────────────────────────────────────────────────────────
def make_svg(bg, border, accent, symbol):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}">
  <defs>
    <filter id="sh">
      <feDropShadow dx="0" dy="4" stdDeviation="5" flood-color="#000" flood-opacity="0.6"/>
    </filter>
    <radialGradient id="bg" cx="50%" cy="35%" r="65%">
      <stop offset="0%" stop-color="{_lighten(bg, 0.25)}"/>
      <stop offset="100%" stop-color="{bg}"/>
    </radialGradient>
  </defs>
  <path d="{SHIELD}" fill="url(#bg)" stroke="{border}" stroke-width="3.5" filter="url(#sh)"/>
  <path d="{LINER}"  fill="none"     stroke="{accent}" stroke-width="1.2" opacity="0.45"/>
  {symbol}
</svg>"""


def _lighten(hex_col, amount=0.2):
    hex_col = hex_col.lstrip('#')
    r, g, b = int(hex_col[0:2],16), int(hex_col[2:4],16), int(hex_col[4:6],16)
    r = min(255, int(r + (255-r)*amount))
    g = min(255, int(g + (255-g)*amount))
    b = min(255, int(b + (255-b)*amount))
    return f"#{r:02x}{g:02x}{b:02x}"


# ── Symbol helpers ───────────────────────────────────────────────────────────
def star5(cx, cy, r, color, r2=None):
    if r2 is None: r2 = r * 0.42
    pts = []
    for i in range(10):
        a = math.radians(i * 36 - 90)
        rad = r if i % 2 == 0 else r2
        pts.append(f"{cx + rad*math.cos(a):.1f},{cy + rad*math.sin(a):.1f}")
    return f'<polygon points="{" ".join(pts)}" fill="{color}"/>'


def circle_path(x, y, r):
    return f"M{x},{y-r:.2f} A{r:.2f},{r:.2f} 0 1 0 {x},{y+r:.2f} A{r:.2f},{r:.2f} 0 1 0 {x},{y-r:.2f} Z"


def crescent(cx, cy, size, color):
    r  = size * 0.42
    r2 = r * 0.70
    off = r * 0.38
    outer = circle_path(cx, cy, r)
    inner = circle_path(cx + off, cy, r2)
    return f'<path d="{outer} {inner}" fill="{color}" fill-rule="evenodd"/>'


def cross(cx, cy, size, color, thick=0.28):
    t = size * thick; s = size
    return (f'<rect x="{cx-t/2:.1f}" y="{cy-s/2:.1f}" width="{t:.1f}" height="{s:.1f}" rx="3" fill="{color}"/>'
            f'<rect x="{cx-s/2:.1f}" y="{cy-t/2:.1f}" width="{s:.1f}" height="{t:.1f}" rx="3" fill="{color}"/>')


def crown(cx, cy, size, color):
    s = size; w = s * 1.1; h = s * 0.82
    x0 = cx - w/2; y0 = cy - h/2
    pts = (f"{x0:.1f},{y0+h:.1f} {x0:.1f},{y0+h*0.45:.1f} "
           f"{x0+w*0.1:.1f},{y0+h*0.45:.1f} {x0+w*0.18:.1f},{y0:.1f} {x0+w*0.26:.1f},{y0+h*0.45:.1f} "
           f"{x0+w*0.38:.1f},{y0+h*0.18:.1f} "
           f"{x0+w*0.5:.1f},{y0-h*0.08:.1f} "
           f"{x0+w*0.62:.1f},{y0+h*0.18:.1f} "
           f"{x0+w*0.74:.1f},{y0+h*0.45:.1f} {x0+w*0.82:.1f},{y0:.1f} {x0+w*0.9:.1f},{y0+h*0.45:.1f} "
           f"{x0+w:.1f},{y0+h*0.45:.1f} {x0+w:.1f},{y0+h:.1f}")
    # base band
    base = f'<rect x="{x0:.1f}" y="{y0+h*0.55:.1f}" width="{w:.1f}" height="{h*0.45:.1f}" fill="{color}"/>'
    return base + f'<polygon points="{pts}" fill="{color}"/>'


def tower(cx, cy, size, color):
    s = size; w = s * 0.72; h = s * 0.88
    x0 = cx-w/2; y0 = cy-h/2; cw = w/5; ch = s*0.13
    body     = f'<rect x="{x0:.1f}" y="{y0+ch:.1f}" width="{w:.1f}" height="{h-ch:.1f}" fill="{color}"/>'
    merlons  = ''.join(f'<rect x="{x0+i*cw:.1f}" y="{y0:.1f}" width="{cw*0.65:.1f}" height="{ch*1.4:.1f}" fill="{color}"/>' for i in range(3))
    doorway  = f'<rect x="{cx-s*0.1:.1f}" y="{y0+h*0.55:.1f}" width="{s*0.2:.1f}" height="{h*0.45:.1f}" rx="3" fill="#000" opacity="0.35"/>'
    slit     = f'<rect x="{cx-s*0.04:.1f}" y="{y0+h*0.22:.1f}" width="{s*0.08:.1f}" height="{s*0.22:.1f}" fill="#000" opacity="0.35"/>'
    return body + merlons + doorway + slit


def anchor(cx, cy, size, color):
    s = size; sw = max(4, s*0.11)
    ring  = f'<circle cx="{cx}" cy="{cy-s*0.36:.1f}" r="{s*0.18:.1f}" fill="none" stroke="{color}" stroke-width="{sw:.1f}"/>'
    shaft = f'<line x1="{cx}" y1="{cy-s*0.18:.1f}" x2="{cx}" y2="{cy+s*0.5:.1f}" stroke="{color}" stroke-width="{sw:.1f}" stroke-linecap="round"/>'
    cross_bar = f'<line x1="{cx-s*0.32:.1f}" y1="{cy-s*0.1:.1f}" x2="{cx+s*0.32:.1f}" y2="{cy-s*0.1:.1f}" stroke="{color}" stroke-width="{sw:.1f}" stroke-linecap="round"/>'
    flukes= f'<path d="M{cx-s*0.38:.1f},{cy+s*0.12:.1f} Q{cx-s*0.45:.1f},{cy+s*0.5:.1f} {cx:.1f},{cy+s*0.5:.1f} Q{cx+s*0.45:.1f},{cy+s*0.5:.1f} {cx+s*0.38:.1f},{cy+s*0.12:.1f}" fill="none" stroke="{color}" stroke-width="{sw:.1f}"/>'
    return ring + shaft + cross_bar + flukes


def trident(cx, cy, size, color):
    s = size; sw = max(4, s*0.1)
    shaft = f'<line x1="{cx}" y1="{cy-s*0.5:.1f}" x2="{cx}" y2="{cy+s*0.5:.1f}" stroke="{color}" stroke-width="{sw:.1f}" stroke-linecap="round"/>'
    prongs = (f'<line x1="{cx}" y1="{cy-s*0.5:.1f}" x2="{cx-s*0.32:.1f}" y2="{cy-s*0.18:.1f}" stroke="{color}" stroke-width="{sw:.1f}" stroke-linecap="round"/>'
              f'<line x1="{cx}" y1="{cy-s*0.5:.1f}" x2="{cx+s*0.32:.1f}" y2="{cy-s*0.18:.1f}" stroke="{color}" stroke-width="{sw:.1f}" stroke-linecap="round"/>')
    tips  = (f'<line x1="{cx-s*0.32:.1f}" y1="{cy-s*0.18:.1f}" x2="{cx-s*0.32:.1f}" y2="{cy-s*0.42:.1f}" stroke="{color}" stroke-width="{sw:.1f}" stroke-linecap="round"/>'
             f'<line x1="{cx+s*0.32:.1f}" y1="{cy-s*0.18:.1f}" x2="{cx+s*0.32:.1f}" y2="{cy-s*0.42:.1f}" stroke="{color}" stroke-width="{sw:.1f}" stroke-linecap="round"/>')
    return shaft + prongs + tips


def hammer(cx, cy, size, color):
    s = size; sw = s*0.14
    handle = f'<rect x="{cx-sw/2:.1f}" y="{cy-s*0.08:.1f}" width="{sw:.1f}" height="{s*0.58:.1f}" rx="3" fill="{color}"/>'
    head   = f'<rect x="{cx-s*0.32:.1f}" y="{cy-s*0.46:.1f}" width="{s*0.64:.1f}" height="{s*0.3:.1f}" rx="4" fill="{color}"/>'
    return handle + head


def crossed_hammers(cx, cy, size, color):
    s = size; sw = s*0.08
    def _hammer_svg(angle):
        hw = s*0.58; hh = s*0.26; hs = s*0.12
        handle = f'<line x1="{cx-s*0.28:.1f}" y1="{cy+s*0.38:.1f}" x2="{cx+s*0.22:.1f}" y2="{cy-s*0.28:.1f}" stroke="{color}" stroke-width="{hs*2:.1f}" stroke-linecap="round"/>'
        head   = f'<rect x="{cx+s*0.04:.1f}" y="{cy-s*0.44:.1f}" width="{s*0.44:.1f}" height="{s*0.22:.1f}" rx="3" fill="{color}" transform="rotate({angle} {cx} {cy})"/>'
        return handle + head
    # Two mirrored hammers
    h1 = f'<line x1="{cx-s*0.3:.1f}" y1="{cy+s*0.42:.1f}" x2="{cx+s*0.24:.1f}" y2="{cy-s*0.3:.1f}" stroke="{color}" stroke-width="{sw*2:.1f}" stroke-linecap="round"/>'
    h2 = f'<line x1="{cx+s*0.3:.1f}" y1="{cy+s*0.42:.1f}" x2="{cx-s*0.24:.1f}" y2="{cy-s*0.3:.1f}" stroke="{color}" stroke-width="{sw*2:.1f}" stroke-linecap="round"/>'
    head1 = f'<rect x="{cx+s*0.06:.1f}" y="{cy-s*0.46:.1f}" width="{s*0.42:.1f}" height="{s*0.22:.1f}" rx="3" fill="{color}" transform="rotate(-42 {cx:.1f} {cy:.1f})"/>'
    head2 = f'<rect x="{cx-s*0.48:.1f}" y="{cy-s*0.46:.1f}" width="{s*0.42:.1f}" height="{s*0.22:.1f}" rx="3" fill="{color}" transform="rotate(42 {cx:.1f} {cy:.1f})"/>'
    return h1 + h2 + head1 + head2


def skull(cx, cy, size, color):
    s = size
    cranium = f'<ellipse cx="{cx}" cy="{cy-s*0.1:.1f}" rx="{s*0.34:.1f}" ry="{s*0.32:.1f}" fill="{color}"/>'
    jaw     = f'<rect x="{cx-s*0.22:.1f}" y="{cy+s*0.18:.1f}" width="{s*0.44:.1f}" height="{s*0.17:.1f}" rx="5" fill="{color}"/>'
    e1 = f'<circle cx="{cx-s*0.12:.1f}" cy="{cy-s*0.12:.1f}" r="{s*0.09:.1f}" fill="#000" opacity="0.45"/>'
    e2 = f'<circle cx="{cx+s*0.12:.1f}" cy="{cy-s*0.12:.1f}" r="{s*0.09:.1f}" fill="#000" opacity="0.45"/>'
    n  = f'<rect x="{cx-s*0.04:.1f}" y="{cy+s*0.02:.1f}" width="{s*0.08:.1f}" height="{s*0.1:.1f}" fill="#000" opacity="0.35"/>'
    teeth = ''.join(f'<rect x="{cx-s*0.18+i*s*0.12:.1f}" y="{cy+s*0.16:.1f}" width="{s*0.09:.1f}" height="{s*0.1:.1f}" fill="#000" opacity="0.35"/>' for i in range(4))
    return cranium + jaw + e1 + e2 + n + teeth


def lightning(cx, cy, size, color):
    s = size
    return (f'<polygon points="'
            f'{cx-s*0.08:.1f},{cy-s*0.5:.1f} {cx+s*0.32:.1f},{cy-s*0.5:.1f} '
            f'{cx-s*0.04:.1f},{cy+s*0.02:.1f} {cx+s*0.28:.1f},{cy+s*0.02:.1f} '
            f'{cx-s*0.32:.1f},{cy+s*0.5:.1f} {cx+s*0.02:.1f},{cy+s*0.02:.1f} '
            f'{cx-s*0.22:.1f},{cy+s*0.02:.1f}" fill="{color}"/>')


def scales(cx, cy, size, color):
    s = size; sw = 4
    beam = f'<line x1="{cx-s*0.42:.1f}" y1="{cy-s*0.06:.1f}" x2="{cx+s*0.42:.1f}" y2="{cy-s*0.06:.1f}" stroke="{color}" stroke-width="{sw}"/>'
    post = f'<line x1="{cx}" y1="{cy-s*0.42:.1f}" x2="{cx}" y2="{cy+s*0.42:.1f}" stroke="{color}" stroke-width="{sw}"/>'
    top  = f'<circle cx="{cx}" cy="{cy-s*0.44:.1f}" r="5" fill="{color}"/>'
    cl   = f'<line x1="{cx-s*0.42:.1f}" y1="{cy-s*0.06:.1f}" x2="{cx-s*0.42:.1f}" y2="{cy+s*0.18:.1f}" stroke="{color}" stroke-width="2"/>'
    cr   = f'<line x1="{cx+s*0.42:.1f}" y1="{cy-s*0.06:.1f}" x2="{cx+s*0.42:.1f}" y2="{cy+s*0.18:.1f}" stroke="{color}" stroke-width="2"/>'
    p1   = f'<ellipse cx="{cx-s*0.42:.1f}" cy="{cy+s*0.22:.1f}" rx="{s*0.22:.1f}" ry="{s*0.06:.1f}" fill="{color}"/>'
    p2   = f'<ellipse cx="{cx+s*0.42:.1f}" cy="{cy+s*0.22:.1f}" rx="{s*0.22:.1f}" ry="{s*0.06:.1f}" fill="{color}"/>'
    return beam + post + top + cl + cr + p1 + p2


def leaf(cx, cy, size, color):
    s = size
    body = f'<path d="M{cx},{cy-s*0.5:.1f} C{cx+s*0.55:.1f},{cy-s*0.38:.1f} {cx+s*0.55:.1f},{cy+s*0.18:.1f} {cx},{cy+s*0.5:.1f} C{cx-s*0.55:.1f},{cy+s*0.18:.1f} {cx-s*0.55:.1f},{cy-s*0.38:.1f} {cx},{cy-s*0.5:.1f} Z" fill="{color}"/>'
    vein = f'<line x1="{cx}" y1="{cy-s*0.46:.1f}" x2="{cx}" y2="{cy+s*0.46:.1f}" stroke="#000" stroke-width="1.8" opacity="0.28"/>'
    return body + vein


def wheat(cx, cy, size, color):
    s = size; sw = s*0.08
    stem = f'<line x1="{cx}" y1="{cy-s*0.5:.1f}" x2="{cx}" y2="{cy+s*0.5:.1f}" stroke="{color}" stroke-width="{sw:.1f}" stroke-linecap="round"/>'
    grains = ''
    for side, yd in [(-1,-0.42),(1,-0.28),(-1,-0.14),(1,0),(−1,0.14),(1,0.28)]:
        gx = cx + side*s*0.24; gy = cy + yd*s
        rot = -side*30
        grains += f'<ellipse cx="{gx:.1f}" cy="{gy:.1f}" rx="{s*0.1:.1f}" ry="{s*0.17:.1f}" fill="{color}" transform="rotate({rot:.0f} {gx:.1f} {gy:.1f})"/>'
    return stem + grains


def stag(cx, cy, size, color):
    s = size
    body  = f'<ellipse cx="{cx}" cy="{cy+s*0.18:.1f}" rx="{s*0.28:.1f}" ry="{s*0.22:.1f}" fill="{color}"/>'
    neck  = f'<ellipse cx="{cx}" cy="{cy-s*0.05:.1f}" rx="{s*0.11:.1f}" ry="{s*0.2:.1f}" fill="{color}"/>'
    head  = f'<ellipse cx="{cx}" cy="{cy-s*0.3:.1f}" rx="{s*0.14:.1f}" ry="{s*0.16:.1f}" fill="{color}"/>'
    al = (f'<line x1="{cx-s*0.1:.1f}" y1="{cy-s*0.42:.1f}" x2="{cx-s*0.38:.1f}" y2="{cy-s*0.5:.1f}" stroke="{color}" stroke-width="5" stroke-linecap="round"/>'
          f'<line x1="{cx-s*0.28:.1f}" y1="{cy-s*0.47:.1f}" x2="{cx-s*0.22:.1f}" y2="{cy-s*0.34:.1f}" stroke="{color}" stroke-width="3" stroke-linecap="round"/>')
    ar = (f'<line x1="{cx+s*0.1:.1f}" y1="{cy-s*0.42:.1f}" x2="{cx+s*0.38:.1f}" y2="{cy-s*0.5:.1f}" stroke="{color}" stroke-width="5" stroke-linecap="round"/>'
          f'<line x1="{cx+s*0.28:.1f}" y1="{cy-s*0.47:.1f}" x2="{cx+s*0.22:.1f}" y2="{cy-s*0.34:.1f}" stroke="{color}" stroke-width="3" stroke-linecap="round"/>')
    return al + ar + body + neck + head


def fist(cx, cy, size, color):
    s = size; fw = s*0.17
    fingers = ''.join(f'<rect x="{cx-s*0.34+i*fw:.1f}" y="{cy-s*0.46:.1f}" width="{fw*0.82:.1f}" height="{s*0.32:.1f}" rx="4" fill="{color}"/>' for i in range(4))
    palm    = f'<rect x="{cx-s*0.34:.1f}" y="{cy-s*0.16:.1f}" width="{s*0.68:.1f}" height="{s*0.5:.1f}" rx="5" fill="{color}"/>'
    thumb   = f'<ellipse cx="{cx-s*0.42:.1f}" cy="{cy+s*0.06:.1f}" rx="{s*0.12:.1f}" ry="{s*0.2:.1f}" fill="{color}" transform="rotate(-18 {cx-s*0.42:.1f} {cy+s*0.06:.1f})"/>'
    return fingers + palm + thumb


def fang(cx, cy, size, color):
    s = size
    return f'<path d="M{cx},{cy-s*0.5:.1f} L{cx+s*0.26:.1f},{cy+s*0.5:.1f} L{cx},{cy+s*0.22:.1f} L{cx-s*0.26:.1f},{cy+s*0.5:.1f} Z" fill="{color}"/>'


def tusk(cx, cy, size, color):
    s = size
    return f'<path d="M{cx-s*0.1:.1f},{cy-s*0.5:.1f} C{cx+s*0.6:.1f},{cy-s*0.2:.1f} {cx+s*0.55:.1f},{cy+s*0.3:.1f} {cx+s*0.15:.1f},{cy+s*0.5:.1f} C{cx+s*0.05:.1f},{cy+s*0.1:.1f} {cx-s*0.1:.1f},{cy-s*0.5:.1f} {cx-s*0.1:.1f},{cy-s*0.5:.1f} Z" fill="{color}"/>'


def diamond(cx, cy, size, color):
    s = size
    return f'<polygon points="{cx},{cy-s*0.5:.1f} {cx+s*0.42:.1f},{cy} {cx},{cy+s*0.5:.1f} {cx-s*0.42:.1f},{cy}" fill="{color}"/>'


def gear(cx, cy, size, color, teeth=8):
    r_out = size*0.44; r_in = size*0.3; r_hole = size*0.13
    pts = []
    for i in range(teeth*2):
        a = math.radians(i*180/teeth - 90)
        r = r_out if i%2==0 else r_in
        pts.append(f"{cx+r*math.cos(a):.1f},{cy+r*math.sin(a):.1f}")
    g = f'<polygon points="{" ".join(pts)}" fill="{color}"/>'
    h = f'<circle cx="{cx}" cy="{cy}" r="{r_hole:.1f}" fill="#000" opacity="0.4"/>'
    return g + h


def rune_circle(cx, cy, size, color):
    r_out = size*0.44; r_in = size*0.22
    outer = f'<circle cx="{cx}" cy="{cy}" r="{r_out:.1f}" fill="none" stroke="{color}" stroke-width="4.5"/>'
    inner = f'<circle cx="{cx}" cy="{cy}" r="{r_in:.1f}" fill="none" stroke="{color}" stroke-width="2.5"/>'
    spokes = ''
    for i in range(6):
        a = math.radians(i*60)
        spokes += f'<line x1="{cx+r_in*math.cos(a):.1f}" y1="{cy+r_in*math.sin(a):.1f}" x2="{cx+r_out*math.cos(a):.1f}" y2="{cy+r_out*math.sin(a):.1f}" stroke="{color}" stroke-width="3"/>'
    dot = f'<circle cx="{cx}" cy="{cy}" r="{size*0.07:.1f}" fill="{color}"/>'
    return outer + inner + spokes + dot


def spider(cx, cy, size, color):
    s = size
    body = f'<ellipse cx="{cx}" cy="{cy+s*0.1:.1f}" rx="{s*0.2:.1f}" ry="{s*0.26:.1f}" fill="{color}"/>'
    head = f'<circle cx="{cx}" cy="{cy-s*0.2:.1f}" r="{s*0.14:.1f}" fill="{color}"/>'
    legs = ''
    angles = [-155,-120,-60,-25, 25,60,120,155]
    for a in angles:
        rad = math.radians(a)
        x1 = cx + s*0.18*math.cos(rad); y1 = cy + s*0.08 + s*0.05*math.sin(rad)
        x2 = cx + s*0.5*math.cos(rad);  y2 = cy + s*0.08 + s*0.5*math.sin(rad)
        legs += f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="2.8" stroke-linecap="round"/>'
    return legs + body + head


def coil(cx, cy, size, color):
    s = size
    rings = ''
    for r_f, dash, gap in [(0.44, 1.8, 0.9), (0.26, 1.0, 0.5)]:
        r = s*r_f; circ = 2*math.pi*r
        rings += f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="none" stroke="{color}" stroke-width="{s*0.12:.1f}" stroke-dasharray="{circ*0.65:.1f} {circ*0.35:.1f}" stroke-linecap="round"/>'
    rings += f'<circle cx="{cx}" cy="{cy}" r="{s*0.08:.1f}" fill="{color}"/>'
    return rings


def eye_pair(cx, cy, size, color):
    s = size
    e1 = f'<ellipse cx="{cx-s*0.22:.1f}" cy="{cy}" rx="{s*0.21:.1f}" ry="{s*0.14:.1f}" fill="{color}"/>'
    e2 = f'<ellipse cx="{cx+s*0.22:.1f}" cy="{cy}" rx="{s*0.21:.1f}" ry="{s*0.14:.1f}" fill="{color}"/>'
    p1 = f'<circle cx="{cx-s*0.22:.1f}" cy="{cy}" r="{s*0.07:.1f}" fill="#000" opacity="0.55"/>'
    p2 = f'<circle cx="{cx+s*0.22:.1f}" cy="{cy}" r="{s*0.07:.1f}" fill="#000" opacity="0.55"/>'
    return e1 + e2 + p1 + p2


def wave(cx, cy, size, color):
    s = size; sw = s*0.12
    w1 = f'<path d="M{cx-s*0.46:.1f},{cy-s*0.16:.1f} Q{cx-s*0.23:.1f},{cy-s*0.42:.1f} {cx},{cy-s*0.16:.1f} Q{cx+s*0.23:.1f},{cy+s*0.1:.1f} {cx+s*0.46:.1f},{cy-s*0.16:.1f}" fill="none" stroke="{color}" stroke-width="{sw:.1f}" stroke-linecap="round"/>'
    w2 = f'<path d="M{cx-s*0.46:.1f},{cy+s*0.2:.1f} Q{cx-s*0.23:.1f},{cy-s*0.06:.1f} {cx},{cy+s*0.2:.1f} Q{cx+s*0.23:.1f},{cy+s*0.46:.1f} {cx+s*0.46:.1f},{cy+s*0.2:.1f}" fill="none" stroke="{color}" stroke-width="{sw:.1f}" stroke-linecap="round"/>'
    return w1 + w2


def fish(cx, cy, size, color):
    s = size
    body = f'<ellipse cx="{cx-s*0.05:.1f}" cy="{cy}" rx="{s*0.38:.1f}" ry="{s*0.2:.1f}" fill="{color}"/>'
    tail = f'<polygon points="{cx+s*0.3:.1f},{cy} {cx+s*0.52:.1f},{cy-s*0.28:.1f} {cx+s*0.52:.1f},{cy+s*0.28:.1f}" fill="{color}"/>'
    eye  = f'<circle cx="{cx-s*0.22:.1f}" cy="{cy-s*0.04:.1f}" r="{s*0.05:.1f}" fill="#000" opacity="0.45"/>'
    return tail + body + eye


def ring_gem(cx, cy, size, color):
    s = size; r = s*0.34
    ring_svg = f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="none" stroke="{color}" stroke-width="{s*0.14:.1f}"/>'
    gem = f'<polygon points="{cx},{cy-r*1.38:.1f} {cx+r*0.42:.1f},{cy-r*0.82:.1f} {cx+r*0.42:.1f},{cy-r*0.38:.1f} {cx},{cy-r*0.18:.1f} {cx-r*0.42:.1f},{cy-r*0.38:.1f} {cx-r*0.42:.1f},{cy-r*0.82:.1f}" fill="{color}"/>'
    shine = f'<polygon points="{cx},{cy-r*1.38:.1f} {cx+r*0.42:.1f},{cy-r*0.82:.1f} {cx},{cy-r*0.18:.1f}" fill="#fff" opacity="0.22"/>'
    return ring_svg + gem + shine


def serpent(cx, cy, size, color):
    s = size; sw = s*0.14
    body = f'<path d="M{cx-s*0.08:.1f},{cy-s*0.5:.1f} Q{cx+s*0.42:.1f},{cy-s*0.28:.1f} {cx+s*0.3:.1f},{cy+s*0.05:.1f} Q{cx+s*0.15:.1f},{cy+s*0.35:.1f} {cx-s*0.32:.1f},{cy+s*0.32:.1f} Q{cx-s*0.5:.1f},{cy+s*0.3:.1f} {cx-s*0.2:.1f},{cy+s*0.5:.1f}" fill="none" stroke="{color}" stroke-width="{sw:.1f}" stroke-linecap="round"/>'
    head = f'<ellipse cx="{cx-s*0.08:.1f}" cy="{cy-s*0.5:.1f}" rx="{s*0.12:.1f}" ry="{s*0.08:.1f}" fill="{color}"/>'
    return body + head


S = 70  # default symbol size


# ── Item definitions: (bg, border, accent, symbol_svg) ──────────────────────
RACES = [
    ("human",    "#3e0d0d", "#c8a040", "#9a6020", crown(CX, CY+4, S,   "#c8a040")),
    ("dwarf",    "#1e1e2e", "#c8a040", "#7070a0", crossed_hammers(CX, CY+2, S, "#c8a040")),
    ("high-elf", "#102010", "#b0c0d0", "#608070", crescent(CX, CY-10, S, "#b0c0d0") + star5(CX, CY+32, 18, "#b0c0d0")),
    ("dark-elf", "#0a0414", "#8040a8", "#5030b0", spider(CX, CY, S, "#8040a8")),
    ("orc",      "#181008", "#b09060", "#706040", tusk(CX+10, CY, S*0.9, "#c0a060")),
    ("goblin",   "#0c1408", "#9aaa18", "#608010", coil(CX, CY, S, "#9aaa18")),
]

HOUSES = [
    # Twin Cities
    ("house-adkison",    "#380808", "#c8a040", "#a07020", cross(CX, CY, S*0.95, "#c8a040")),
    ("house-aurand",     "#081830", "#b0b8cc", "#6080a0", tower(CX, CY+4, S, "#b0b8cc")),
    ("house-dale",       "#0c1e0c", "#c8a030", "#807820", wheat(CX, CY, S, "#c8a030")),
    ("house-gross",      "#1e1808", "#c8a040", "#a08020", scales(CX, CY, S, "#c8a040")),
    ("house-highland",   "#181a12", "#c8c8c0", "#909090", stag(CX, CY, S, "#c8c8c0")),
    ("house-van-cleave", "#380808", "#c8c8cc", "#909090", fist(CX, CY, S, "#c8c8cc")),
    # Tidefall
    ("house-binx",       "#081e28", "#c8c8cc", "#5090a0", anchor(CX, CY, S, "#c8c8cc")),
    ("house-darkleaf",   "#080c08", "#285828", "#205020", leaf(CX, CY, S, "#285828")),
    ("house-fish",       "#081028", "#c0c8cc", "#7090b0", fish(CX, CY, S, "#c0c8cc")),
    ("house-ver-meer",   "#080c28", "#c8a040", "#6050a0", trident(CX, CY, S, "#c8a040")),
    # Dreadwind
    ("house-blacktide",  "#080808", "#c0c0c0", "#505050", skull(CX, CY, S, "#c0c0c0")),
    ("house-saltbreach", "#101820", "#5880b0", "#305070", wave(CX, CY, S, "#5880b0")),
    ("house-stormvane",  "#121218", "#c8a040", "#806020", lightning(CX, CY, S, "#c8a040")),
    # Glenhaven
    ("house-moonwhisper","#101c10", "#b0b8c8", "#708080", crescent(CX, CY-12, S, "#b0b8c8") + star5(CX, CY+30, 18, "#b0b8c8")),
    ("house-silverleaf", "#0e1c0e", "#b8c0bc", "#708070", leaf(CX, CY, S*1.1, "#b8c0bc")),
    # Shadow Court
    ("house-nightborn",  "#060210", "#7840a0", "#503080", crescent(CX, CY-8, S*0.78, "#7840a0") + serpent(CX, CY+32, S*0.62, "#7840a0")),
    ("house-shadowveil", "#040408", "#9090b0", "#505060", eye_pair(CX, CY, S, "#9090b0")),
    # Gilgeth Clans
    ("clan-ashfang",     "#1c0808", "#808080", "#505050", fang(CX, CY, S, "#909090")),
    ("clan-ironhide",    "#0e0808", "#707070", "#404040", fist(CX, CY, S, "#808080")),
    ("clan-stonejaw",    "#181818", "#8a8a8a", "#606060", diamond(CX, CY, S, "#8a8a8a")),
    # Groth Clans
    ("clan-bloodstone",  "#1e0606", "#981818", "#601010", diamond(CX, CY, S, "#aa2020")),
    ("clan-redtusk",     "#0e0606", "#c04040", "#802020", tusk(CX+10, CY, S, "#c04040")),
    # Vilefin
    ("clan-cogtooth",    "#0a1008", "#90a010", "#607010", gear(CX, CY, S, "#90a010")),
    ("clan-rustfang",    "#181008", "#806030", "#604020", fang(CX, CY, S, "#806030")),
    # Lostfeld Dwarves
    ("clan-ironmaul",    "#181818", "#c8a040", "#806020", hammer(CX, CY+4, S, "#c8a040")),
    ("goldfinger-duke-clan", "#1c1800", "#ffd040", "#c0a000", ring_gem(CX, CY, S, "#ffd040")),
    ("runewardens-clan", "#080818", "#5878c0", "#4060a0", rune_circle(CX, CY, S, "#5878c0")),
]


def write_svg(slug, out_dir, bg, border, accent, symbol):
    path = out_dir / f"{slug}.svg"
    path.write_text(make_svg(bg, border, accent, symbol), encoding="utf-8")
    print(f"  WRITE {slug}.svg")


if __name__ == "__main__":
    print(f"Generating {len(RACES)} race emblems...")
    for slug, bg, border, accent, sym in RACES:
        write_svg(slug, RACE_DIR, bg, border, accent, sym)

    print(f"\nGenerating {len(HOUSES)} house/clan shields...")
    for slug, bg, border, accent, sym in HOUSES:
        write_svg(slug, HOUSE_DIR, bg, border, accent, sym)

    print(f"\nDone — {len(RACES)+len(HOUSES)} SVG files written.")
