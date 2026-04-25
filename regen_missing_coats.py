"""Generate missing race/house images in heraldic shield style (matching existing coats of arms)."""
import os, base64, time, requests
from pathlib import Path

_env = Path(__file__).parent / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
MODEL   = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")

RACE_DIR  = Path(__file__).parent / "static" / "illustrations" / "races"
HOUSE_DIR = Path(__file__).parent / "static" / "illustrations" / "houses"

STYLE = (
    "Medieval heraldic coat of arms, painted shield on dark stone, "
    "Crusader Kings 3 style, oil painting, cinematic lighting, muted colors, "
    "ultra detailed, high realism. No text, no letters, no watermark, no UI frame, no border."
)

MISSING = [
    # ── Races ──────────────────────────────────────────────────────────────
    {
        "name": "Dwarf",
        "slug": "dwarf",
        "dir": RACE_DIR,
        "prompt": (
            "Dwarf race emblem — a stone-carved shield bearing crossed war-hammers "
            "over a forge flame, rune border, dwarven mountain stronghold heraldry. "
            f"{STYLE}"
        ),
    },
    {
        "name": "High Elf",
        "slug": "high-elf",
        "dir": RACE_DIR,
        "prompt": (
            "High Elf race emblem — a silver shield bearing a crescent moon above a silver tree, "
            "delicate leaf-scroll border, ancient elven forest court heraldry. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Dark Elf",
        "slug": "dark-elf",
        "dir": RACE_DIR,
        "prompt": (
            "Dark Elf race emblem — an obsidian shield bearing a spider above a broken moon, "
            "shadow-silk border, dark elf shadow court heraldry, cold and ancient. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Orc",
        "slug": "orc",
        "dir": RACE_DIR,
        "prompt": (
            "Orc race emblem — a scarred iron shield bearing crossed tusks over a fist, "
            "bone-and-chain border, brutal orc clan heraldry, proud and warrior. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Goblin",
        "slug": "goblin",
        "dir": RACE_DIR,
        "prompt": (
            "Goblin race emblem — a patchwork iron shield bearing a coiled serpent "
            "gripping a coin, scavenged bolt-and-gear border, goblin cunning heraldry. "
            f"{STYLE}"
        ),
    },
    # ── Houses ─────────────────────────────────────────────────────────────
    {
        "name": "House Dale",
        "slug": "house-dale",
        "dir": HOUSE_DIR,
        "prompt": (
            "House Dale coat of arms — a green shield bearing a gold wheat sheaf, "
            "Twin Cities landed nobility, human medieval heraldry. "
            f"{STYLE}"
        ),
    },
    {
        "name": "House Gross",
        "slug": "house-gross",
        "dir": HOUSE_DIR,
        "prompt": (
            "House Gross coat of arms — a dark gold shield bearing black scales of justice, "
            "Twin Cities merchant-lord house, wealth and leverage, human medieval heraldry. "
            f"{STYLE}"
        ),
    },
    {
        "name": "House Highland",
        "slug": "house-highland",
        "dir": HOUSE_DIR,
        "prompt": (
            "House Highland coat of arms — a grey shield bearing a white stag on a hill, "
            "Twin Cities noble house, human medieval heraldry. "
            f"{STYLE}"
        ),
    },
    {
        "name": "House Shadowveil",
        "slug": "house-shadowveil",
        "dir": HOUSE_DIR,
        "prompt": (
            "House Shadowveil coat of arms — a black shield bearing silver eyes in shadow, "
            "Shadow Court dark elf assassin house, cold ancient heraldry. "
            f"{STYLE}"
        ),
    },
]


def generate(item):
    out = item["dir"] / f"{item['slug']}.png"
    print(f"  GEN   {item['name']} ...", end=" ", flush=True)
    try:
        r = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={"model": MODEL, "prompt": item["prompt"], "size": "1024x1024"},
            timeout=180,
        )
        if r.status_code != 200:
            print(f"FAIL ({r.status_code}) {r.text[:120]}")
            return
        data = (r.json().get("data") or [{}])[0].get("b64_json")
        if not data:
            print("FAIL (no b64_json)")
            return
        out.write_bytes(base64.b64decode(data))
        print("OK")
    except Exception as e:
        print(f"ERROR {e}")


if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: OPENAI_API_KEY not set")
        raise SystemExit(1)

    print(f"Generating {len(MISSING)} missing images in heraldic shield style...\n")
    for i, item in enumerate(MISSING):
        generate(item)
        if i < len(MISSING) - 1:
            time.sleep(2)

    print("\nDone. Restart Flask to serve new images.")
