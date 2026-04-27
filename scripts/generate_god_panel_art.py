"""Generate art-directed visual assets for the God Panel.

Generates a small set of matte-painted backdrops and texture plates used as
ambient layers in the redesigned God Panel. Prompts are crafted to avoid
common AI-generated tells (no readable text, no warped figures, no fake
heraldry symbols, no centered subject focus) so the assets sit as
backdrops behind UI without drawing attention to themselves.

Usage:
  python scripts/generate_god_panel_art.py
  python scripts/generate_god_panel_art.py throne_hall   # only one
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
OUT_DIR = ROOT / "static" / "illustrations" / "ui" / "god"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Each entry: filename -> (size, prompt). Prompts emphasize matte painting,
# painterly hand-rendered style, and explicitly forbid the most common
# AI-generated tells.
ASSETS: dict[str, tuple[str, str]] = {
    "throne-hall.png": (
        "1536x1024",
        (
            "Wide matte painting of a colossal empty throne hall at deep night. "
            "Black and blue-gray stone, endless rows of pillars vanishing into fog. "
            "Sparse cold moonlight through a high arch; a few dying braziers cast "
            "small orange pools — no bright golden sunrise, no heroic citadel glow. "
            "Perilous epic fantasy mood, hand-painted illustration, low contrast, "
            "plenty of empty space for UI. No people, no text, no symbols."
        ),
    ),
    "stone-frieze.png": (
        "1536x1024",
        (
            "Matte painting of a long horizontal stretch of ancient carved dark "
            "granite stonework, very subtle abstract knotwork relief, weathered and "
            "dusty, low contrast, designed as a thin wall texture seen straight on, "
            "no central focus. ABSOLUTELY NO text, NO letters, NO numerals, NO "
            "readable runes, NO heraldry crests, NO figures, NO faces. Painterly "
            "hand-rendered style, muted slate and warm umber tones, soft warm rim "
            "light from one side, gentle film grain, intended as a UI border plate."
        ),
    ),
    "parchment-tile.png": (
        "1024x1024",
        (
            "Seamless tile of aged hand-made parchment, soft warm cream and faint "
            "ochre stains, fine fibrous paper grain, no folds, no torn edges, no "
            "ink, no text, no letters, no symbols, no drawings, no decoration. "
            "Even soft lighting, painterly subtle texture only, suitable as a "
            "background tile behind UI text."
        ),
    ),
    "banner-cloth.png": (
        "1024x1536",
        (
            "Matte painting of a long plain hanging fabric banner, deep wine red "
            "with a subtle gold thread border running vertically along the edges, "
            "soft folds, dust catching in side light, cropped tightly with the "
            "banner filling most of the frame. ABSOLUTELY NO text, NO letters, NO "
            "numerals, NO heraldry crest, NO emblem, NO sigil, NO drawings. Plain "
            "fabric only, painterly hand-rendered style, gentle film grain, "
            "muted, suitable as a vertical UI accent."
        ),
    ),
}


def _post(payload: dict) -> dict:
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    resp = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers=headers,
        json=payload,
        timeout=300,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"{resp.status_code}: {resp.text[:400]}")
    return resp.json()


def generate_one(name: str, size: str, prompt: str) -> bool:
    out_file = OUT_DIR / name
    if out_file.exists() and out_file.stat().st_size > 50_000:
        print(f"[skip] {name} already exists ({out_file.stat().st_size} bytes)")
        return True
    print(f"[gen ] {name} ({size}) ...")
    t0 = time.time()
    try:
        data = _post({"model": MODEL, "prompt": prompt, "size": size, "quality": "high"})
    except Exception as exc:
        print(f"[fail] {name}: {exc}")
        return False
    items = data.get("data") or []
    if not items:
        print(f"[fail] {name}: empty response")
        return False
    b64 = items[0].get("b64_json")
    if not b64:
        print(f"[fail] {name}: no b64_json")
        return False
    out_file.write_bytes(base64.b64decode(b64))
    dt = time.time() - t0
    print(f"[done] {name} ({out_file.stat().st_size} bytes, {dt:.1f}s)")
    return True


def main(argv: list[str]) -> int:
    if not API_KEY:
        print("OPENAI_API_KEY is missing in environment/.env")
        return 1

    selectors = argv[1:]
    targets = ASSETS
    if selectors:
        chosen = {}
        for sel in selectors:
            key = sel if sel.endswith(".png") else f"{sel}.png"
            if key in ASSETS:
                chosen[key] = ASSETS[key]
            else:
                print(f"[warn] unknown asset: {sel}")
        targets = chosen or ASSETS

    ok_count = 0
    for name, (size, prompt) in targets.items():
        if generate_one(name, size, prompt):
            ok_count += 1

    print(f"\nDone. {ok_count}/{len(targets)} assets generated into {OUT_DIR}")
    return 0 if ok_count == len(targets) else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
