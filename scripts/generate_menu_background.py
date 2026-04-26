"""Generate a cinematic main-menu background using OpenAI Images API.

Usage:
  python scripts/generate_menu_background.py
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
MODEL = (os.getenv("OPENAI_IMAGE_MODEL") or "gpt-image-1").strip()
SIZE = (os.getenv("OPENAI_IMAGE_SIZE") or "1536x1024").strip()
OUT_FILE = ROOT / "public" / "aeloria-menu-cinematic-bg.png"

PROMPT = (
    "Cinematic AAA-game main menu key art for a dark high-fantasy living-world strategy game called "
    "Aeloria. Ultra-wide painterly oil-painting composition, no text, no logos, no UI elements, no "
    "characters in the foreground. A divine vantage point at twilight looking down across an entire "
    "ancient realm: in the middle distance a colossal weathered stone citadel crowns a shadowed mountain, "
    "warm amber torchlight glowing along its battlements and spilling from arched cathedral windows; "
    "below it, a winding silver river cuts through misty valleys threaded with smaller walled kingdoms "
    "whose ramparts glitter with distant firelight; jagged blue-black peaks fade into atmospheric haze "
    "on the horizon; ancient forests on the slopes, the suggestion of a road winding into the distance. "
    "Above, a dramatic broken-cloud sky parted by colossal golden god rays, a single immense pale moon "
    "(or a soft solar disc) just rising behind the citadel, faint constellations and slow drifting embers, "
    "wisps of low fog. Cinematic painterly concept-art style — deep blue-black with rich warm amber and "
    "bronze torchlight accents, profound stillness, sacred and mysterious, immense atmospheric depth and "
    "scale. Strong focal area in the center-left third (citadel + god rays); calmer, darker right third "
    "with simpler silhouettes intentionally reserved for menu UI. Inspired by classic high-fantasy book "
    "covers and AAA RPG title screens (Elden Ring, Baldur's Gate 3, Skyrim) — painterly, timeless, never "
    "photo-real, never AI-stylized. No text or logos anywhere in the image."
)


def main() -> int:
    if not API_KEY:
        print("OPENAI_API_KEY is missing in environment/.env")
        return 1

    payload = {
        "model": MODEL,
        "prompt": PROMPT,
        "size": SIZE,
        "quality": "high",
    }
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
    items = data.get("data") or []
    if not items:
        print("No image data returned.")
        return 3

    b64 = items[0].get("b64_json")
    if not b64:
        print("No b64_json image in response.")
        return 4

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_bytes(base64.b64decode(b64))
    print(f"Saved: {OUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

