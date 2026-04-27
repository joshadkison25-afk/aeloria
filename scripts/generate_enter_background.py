"""Generate the cinematic game-enter / loading-bridge background via OpenAI Images API.

Companion to generate_menu_background.py: same Aeloria mood and painterly quality,
but a distinct scene (journey / threshold) so it does not match the main-menu key art.

Usage (from repo root):
  python scripts/generate_enter_background.py

Env:
  OPENAI_API_KEY          (required)
  OPENAI_IMAGE_MODEL      default: gpt-image-1
  OPENAI_IMAGE_SIZE       default: 1536x1024  (override with OPENAI_ENTER_IMAGE_SIZE)
  OPENAI_ENTER_IMAGE_SIZE optional override for this asset only

Output:
  public/aeloria-enter-cinematic-bg.png
"""

from __future__ import annotations

import base64
import os
import urllib.request
from pathlib import Path

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
MODEL = (os.getenv("OPENAI_IMAGE_MODEL") or "gpt-image-1").strip()
SIZE = (
    (os.getenv("OPENAI_ENTER_IMAGE_SIZE") or os.getenv("OPENAI_IMAGE_SIZE") or "1536x1024")
).strip()
OUT_FILE = ROOT / "public" / "aeloria-enter-cinematic-bg.png"

PROMPT = (
    "Cinematic ultra-wide loading-screen key art for a dark high-fantasy game called Aeloria — "
    "DIFFERENT composition from a main-menu aerial citadel vista. Ground-level or low travelers' "
    "perspective: a misty cobble road winding toward enormous weathered stone gates and a fortified "
    "pass, torches and braziers throwing warm amber light through rolling fog; ancient forest or "
    "broken cliffs on the sides; storm clouds parting with a few dramatic golden shafts, distant "
    "thunderhead silhouettes. Sense of crossing a threshold into the realm, pilgrimage or return. "
    "Ultra painterly oil-painting / AAA concept art, deep blue-black shadows with warm bronze light, "
    "immense atmosphere, no characters in the foreground (empty road only), no faces, no text, no "
    "logos, no UI. Focal interest center-right third; left third calmer and darker for overlay text. "
    "Timeless fantasy book-cover quality — never photo-real, never glossy AI sheen."
)


def _save_first_image(items: list, out: Path) -> None:
    if not items:
        raise SystemExit("No image data returned.")
    item = items[0]
    b64 = item.get("b64_json")
    if b64:
        out.write_bytes(base64.b64decode(b64))
        return
    url = item.get("url")
    if url:
        urllib.request.urlretrieve(url, out)
        return
    raise SystemExit("Image response has neither b64_json nor url.")


def main() -> int:
    if not API_KEY:
        print("OPENAI_API_KEY is missing in environment/.env")
        return 1

    payload: dict = {"model": MODEL, "prompt": PROMPT, "size": SIZE}
    if not MODEL.lower().startswith("dall-e"):
        payload["quality"] = "high"

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    resp = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers=headers,
        json=payload,
        timeout=180,
    )
    if resp.status_code >= 400:
        print("Image generation failed:", resp.status_code, resp.text[:500])
        return 2

    data = resp.json()
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _save_first_image(data.get("data") or [], OUT_FILE)
    print(f"Saved: {OUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
