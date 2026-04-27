"""Generate per-page cinematic hero images for Aeloria using OpenAI Images API.

Same painterly AAA-key-art style as the main menu background. Each prompt locks
the same color/light/composition direction and asks for a calmer right third
that can host UI overlays.

Usage:
  python scripts/generate_page_heroes.py             # generate all (skips existing > 50KB)
  python scripts/generate_page_heroes.py factions    # generate only one (or several)
  python scripts/generate_page_heroes.py --force factions

Output:
  static/illustrations/ui/heroes/<key>.png
"""

from __future__ import annotations

import base64
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
MODEL = (os.getenv("OPENAI_IMAGE_MODEL") or "gpt-image-1").strip()
OUT_DIR = ROOT / "static" / "illustrations" / "ui" / "heroes"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ── Style preamble shared across every hero ───────────────────────────────
# Locks the look so every page feels like the same painted world.
STYLE_PREAMBLE = (
    "Cinematic AAA-game key art for a dark high-fantasy living-world strategy "
    "game called Aeloria. Wide painterly oil-painting composition, no text, no "
    "logos, no UI elements, no characters in the foreground, no symbols, no "
    "watermarks. Mood: perilous epic adventure — deeper shadows, cooler midnight "
    "blues and sooty stone, restrained gold (no bright Gondor citadel glow). "
    "Light from sparse braziers, moonlight, and narrow god rays; drifting cold fog, "
    "distant embers, threat and wonder in equal measure. Painterly, timeless, "
    "never photo-real, never AI-stylized. Strong focal area center-left; darker, "
    "quieter right third reserved for UI overlays."
)

# ── Per-page subject prompts ──────────────────────────────────────────────
HEROES: dict[str, tuple[str, str]] = {
    # key                 (size,         subject)
    "world": (
        "1536x1024",
        "A divine vantage point at twilight looking down across an entire ancient realm: "
        "in the middle distance a colossal weathered stone citadel crowns a shadowed mountain, "
        "warm amber torchlight glowing along its battlements and spilling from arched cathedral "
        "windows; below it, a winding silver river cuts through misty valleys threaded with "
        "smaller walled kingdoms whose ramparts glitter with distant firelight; jagged blue-black "
        "peaks fade into atmospheric haze on the horizon; ancient forests on the slopes; the "
        "suggestion of a road winding into the distance. A single immense pale moon rising "
        "behind the citadel."
    ),
    "factions": (
        "1536x1024",
        "A vast underground war-hall of blackened stone and iron, viewed from the back looking "
        "toward a distant dais lost in shadow. Tattered banners hang like ghosts (wine, midnight, "
        "forest green, cold bronze) — no heraldry, just weathered cloth; a few iron braziers cast "
        "narrow pools of orange fire on wet flagstones; thin cold moonlight through slit windows; "
        "heavy fog at ankle height; sense of armies that have marched through and not returned. "
        "No emblems, no text, no people."
    ),
    "leadership": (
        "1536x1024",
        "A great medieval council hall at twilight: a long carved stone table runs the center, "
        "empty chairs of weathered oak around it suggesting absent rulers, a colossal hearth on "
        "the far wall throwing warm amber firelight across the room; soaring vaulted ceilings "
        "lost in shadow; tall arched windows behind the head of the table letting in cool "
        "twilight god rays; goblets and unrolled maps on the table; antlers and old shields "
        "hanging on the stone walls; faint dust motes in the light. No people, no text."
    ),
    "chronicle": (
        "1536x1024",
        "A lonely stone scriptorium at the hour of wolves: a heavy unopened tome on a rough "
        "lectern, single candle guttering low, more shadow than light; walls of chained books "
        "and scroll cylinders vanishing into black; one tall lancet window leaks cold blue moon "
        "across the floor like frost; melted wax, dried ink, a tarnished astrolabe; breath of "
        "cold fog inside the room. No text on pages, no symbols, no people."
    ),
    "codex": (
        "1536x1024",
        "An ancient library reading nook: a curved wall of leather-bound tomes glows under warm "
        "candle sconces; an open illuminated manuscript rests on a velvet pillow on a marble "
        "lectern; a stained-glass arched window in the deep background filters cool moonlight "
        "between the warmer lantern light; carved stone pillars frame the scene; faint dust in "
        "the slanted light beams; a brass orrery on a side table. No text on pages, no people, "
        "no symbols."
    ),
    "story": (
        "1536x1024",
        "A bard's chamber at moonrise: a vast vaulted stone room lit only by a single guttering "
        "candle on a writing desk piled with parchment, ink and an unrolled illuminated "
        "manuscript; a great open arched window dominates the back wall, framing a moonlit "
        "fantasy realm of distant mountains and a glittering kingdom in the valley below; "
        "long blue-violet god rays from the moon pour into the chamber; warm amber candlelight "
        "fills the foreground; rich tapestry on one wall; a lyre leaned against the desk. "
        "No people, no text."
    ),
    "intel": (
        "1536x1024",
        "A war-room scout's table at night: an enormous unfurled canvas map of an ancient realm "
        "spread across a heavy oak table, marked with brass tokens, weighted iron pieces, "
        "tiny carved figurines, candles, a magnifying glass, a folded letter with a wax seal; "
        "warm overhead lantern pool of amber light on the table; the rest of the great hall "
        "dissolves into shadow with hints of stone columns, hanging banners, a hearth in the "
        "deep background; cool moonlight from a high window adds a second light. "
        "No text on the map, no symbols, no people."
    ),
    "families": (
        "1536x1024",
        "A long ancestral portrait gallery: a dim stone corridor with arched alcoves containing "
        "framed empty heavy gilt picture frames (no faces, no figures, completely empty canvases) "
        "lit by individual candle sconces; the floor of polished dark stone catches warm amber "
        "highlights; at the far end a tall arched window throws cool god rays into the corridor; "
        "ornate wooden benches along the wall; a single tapestry hanging in shadow; faint dust "
        "in the light. No people, no text, no portraits inside the frames."
    ),
    "god": (
        "1536x1024",
        "A colossal throne hall swallowed by night: an empty black stone throne on a tiered "
        "dais, almost a silhouette; only thin beams of moonlight and a few dying braziers "
        "punch through rolling fog; endless rows of pillars fade into nothing; cold blue haze "
        "dominates — gold light is scarce and distant, more threat than comfort. "
        "No people, no text, no symbols."
    ),
    "create": (
        "1536x1024",
        "A celestial forge at twilight: a vast ancient stone vault open to a starlit purple-black "
        "sky on one side; at the center stands a massive anvil and forge with cool blue-white "
        "ethereal flame mixed with warm amber sparks rising into the air; rivers of molten gold "
        "flow in carved stone channels in the floor; an unfinished crown and unstrung weapons "
        "rest on stone tables nearby; god rays and drifting embers fill the chamber. "
        "No people, no text, no symbols."
    ),
    "loading": (
        "1536x1024",
        "A vast astronomical orrery chamber at deep twilight: an enormous brass orrery of "
        "concentric rings and golden planetary spheres occupies the center of a circular stone "
        "observatory, slowly suspended in shafts of moonlight pouring through a great oculus in "
        "the domed ceiling; warm amber lanterns ring the chamber walls; tall arched windows "
        "around the perimeter open onto a cloudy fantasy sky; faint dust and embers in the air. "
        "No people, no text, no symbols."
    ),
}


def build_prompt(subject: str) -> str:
    """Wrap a per-page subject in the shared style preamble."""
    return STYLE_PREAMBLE + " SUBJECT: " + subject


def generate_one(key: str, size: str, subject: str, force: bool = False) -> bool:
    out = OUT_DIR / f"{key}.png"
    if out.exists() and out.stat().st_size > 50_000 and not force:
        print(f"[skip] {out.name} already present ({out.stat().st_size:,} bytes)")
        return True

    prompt = build_prompt(subject)
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "size": size,
        "quality": "high",
    }
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    print(f"[gen ] {out.name} ({size}) ...", flush=True)
    t0 = time.time()
    resp = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers=headers,
        json=payload,
        timeout=300,
    )
    dt = time.time() - t0
    if resp.status_code >= 400:
        print(f"[FAIL] {out.name} {resp.status_code} {resp.text[:300]}")
        return False

    data = resp.json()
    items = data.get("data") or []
    if not items:
        print(f"[FAIL] {out.name} no data returned")
        return False
    b64 = items[0].get("b64_json")
    if not b64:
        print(f"[FAIL] {out.name} no b64_json")
        return False

    out.write_bytes(base64.b64decode(b64))
    print(f"[ok  ] {out.name} -> {out.stat().st_size:,} bytes in {dt:.1f}s")
    return True


def main(argv: list[str]) -> int:
    if not API_KEY:
        print("OPENAI_API_KEY missing in environment / .env")
        return 1

    args = list(argv)
    force = False
    if "--force" in args:
        force = True
        args.remove("--force")

    if args:
        keys = [a.lower().replace(".png", "") for a in args]
        bad = [k for k in keys if k not in HEROES]
        if bad:
            print(f"unknown key(s): {bad}; known: {sorted(HEROES)}")
            return 2
    else:
        keys = list(HEROES)

    fails = 0
    for k in keys:
        size, subject = HEROES[k]
        if not generate_one(k, size, subject, force=force):
            fails += 1

    print(f"\nDone. {len(keys) - fails}/{len(keys)} succeeded.")
    return 0 if fails == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
