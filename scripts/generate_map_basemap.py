"""
Generate a fantasy basemap PNG via OpenAI Images API. Prompt is built from
on-disk lore (_lore_*.txt, master_lore.md) + region blurbs parsed from data/regions.ts.

Usage (from repo root):
  python scripts/generate_map_basemap.py

Env:
  OPENAI_API_KEY   (required)
  MAP_IMAGE_MODEL  default: dall-e-3
  MAP_IMAGE_SIZE   default: 1792x1024  (dall-e-3: 1024x1024 | 1792x1024 | 1024x1792)
  MAP_CHAT_MODEL   default: gpt-4o-mini (for long-lore compression step)

Outputs:
  public/aeloria-basemap-openai.png
  public/basemap_prompt.txt
"""

from __future__ import annotations

import base64
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"


def _read_text(p: Path, cap: int) -> str:
    if not p.exists():
        return ""
    raw = p.read_text(encoding="utf-8", errors="replace")
    if len(raw) > cap:
        return raw[:cap] + "\n\n[...truncated for prompt budget...]\n"
    return raw


def _regions_blurbs() -> str:
    p = ROOT / "data" / "regions.ts"
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8", errors="replace")
    parts: list[str] = []
    for m in re.finditer(
        r"id:\s*'([^']+)'[\s\S]*?name:\s*'((?:\\'|[^'])*)'[\s\S]*?description:\s*'((?:\\'|[^'])*)'",
        text,
    ):
        name, desc = m.group(2).replace("\\'", "'"), m.group(3).replace("\\'", "'")
        line = " ".join(desc.split())[:320]
        parts.append(f"- {name}: {line}")
    if not parts:
        return ""
    return "Named regions (geography hints; do not draw text labels):\n" + "\n".join(parts[:24])


def _compress_geography_brief(lore: str, regions_text: str) -> str:
    from openai import OpenAI

    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise SystemExit("OPENAI_API_KEY is not set")
    client = OpenAI(api_key=key)
    model = (os.getenv("MAP_CHAT_MODEL") or "gpt-4o-mini").strip()
    system = (
        "You write a single 2–3 paragraph brief for a fantasy world MAP ILLUSTRATION: geography, climate, major "
        "landmarks, coasts, forests, mountains, islands, deserts, ice, badlands. No character plots or dialogue. "
        "No instructions about UI or text."
    )
    user = f"SOURCE LORE:\n\n{lore}\n\n{regions_text}\n\nSynthesize for map art only."
    r = client.chat.completions.create(
        model=model,
        max_tokens=800,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return (r.choices[0].message.content or "").strip()


def _final_image_prompt(brief: str) -> str:
    return (
        f"{brief}\n\n"
        "Create a top-down, slightly stylized hand-painted FANTASY WORLD ATLAS: parchment or aged vellum, "
        "ornamental margins optional but NO legible text, title, or labels. Unlabeled landforms only. "
        "Do NOT show political coloring, colored faction territories, or map UI. "
        "Single continuous fantasy continent / archipelago; coastlines and terrain readable. "
        "Dark fantasy mood, Aeloria. High detail, painterly."
    )


def _save_image_from_response(data0, out_path: Path) -> None:
    if data0.b64_json:
        out_path.write_bytes(base64.b64decode(data0.b64_json))
        return
    if data0.url:
        urllib.request.urlretrieve(data0.url, out_path)
        return
    raise SystemExit("Image response has neither b64_json nor url")


def main() -> int:
    lore_parts = []
    for name in ("_lore_aeloria.txt", "_lore_final.txt", "master_lore.md"):
        chunk = _read_text(ROOT / name, 120_000)
        if chunk:
            lore_parts.append(f"=== {name} ===\n{chunk}")
    lore = "\n\n".join(lore_parts) or "(no lore files found; using regions only)\n"
    regions_text = _regions_blurbs()
    if len(lore) + len(regions_text) > 20_000:
        brief = _compress_geography_brief(lore, regions_text)
    else:
        brief = f"{lore}\n\n{regions_text}"[:14_000]
    final_prompt = _final_image_prompt(brief)
    PUBLIC.mkdir(exist_ok=True)
    (PUBLIC / "basemap_prompt.txt").write_text(final_prompt, encoding="utf-8")
    out_png = PUBLIC / "aeloria-basemap-openai.png"

    from openai import OpenAI

    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise SystemExit("OPENAI_API_KEY is not set")
    client = OpenAI(api_key=key)
    model = (os.getenv("MAP_IMAGE_MODEL") or "dall-e-3").strip()
    size = (os.getenv("MAP_IMAGE_SIZE") or "1792x1024").strip()

    print(f"Generating {out_png} with {model} size={size} ...", file=sys.stderr)
    img = client.images.generate(model=model, prompt=final_prompt, size=size, quality="hd", n=1)
    if not img.data:
        raise SystemExit("Empty image response")
    _save_image_from_response(img.data[0], out_png)
    print("Wrote", out_png, "and public/basemap_prompt.txt", file=sys.stderr)
    print("Optional: set NEXT_PUBLIC_MAP_ATLAS_URL=/aeloria-basemap-openai.png", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
