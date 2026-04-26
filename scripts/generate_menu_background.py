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
    "Cinematic dark-fantasy main menu background for a strategy game called Aeloria, wide composition, "
    "no text, no logos, no UI elements. Colossal mountain citadel and ancient city lights in a misty valley, "
    "moonlit clouds, dramatic god rays, distant floating embers, deep blue-black sky with subtle stars, "
    "warm amber torchlight accents, epic atmospheric depth, painterly but high-detail, elegant and moody, "
    "designed to sit behind menu panels without distracting readability, strong center-left focal area and "
    "calmer right side for UI, ultra high quality concept art style."
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

