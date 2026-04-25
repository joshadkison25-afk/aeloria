"""Regenerate all ruler portraits in the new CK3 cinematic style."""
import os, base64, time, requests, json
from pathlib import Path

API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
MODEL   = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
OUT_DIR = Path(__file__).parent / "static" / "illustrations" / "characters"
OUT_DIR.mkdir(parents=True, exist_ok=True)

STYLE = (
    "Medieval noble portrait, Crusader Kings 3 style, realistic painted portrait, detailed face, "
    "cinematic lighting, dark background, soft shadows, oil painting style, ultra detailed, "
    "3/4 view, serious expression, historically inspired clothing, muted colors, high realism, depth of field. "
    "No text, no letters, no watermark, no UI frame, no border."
)

RULERS = [
    {
        "name": "Roderic Thorne II",
        "slug": "roderic-thorne-ii",
        "prompt": (
            "King Roderic Thorne II — aging human male, 61 years old, grey hair and lined face, proud but visibly ailing. "
            "Wears a heavy dark iron crown and black velvet robes trimmed with gold thread, a royal human medieval court style. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Marcellus Ver Meer",
        "slug": "marcellus-ver-meer",
        "prompt": (
            "Admiral-Lord Marcellus Ver Meer — human male, 52 years old, salt-weathered face, silver-streaked dark hair and short beard. "
            "Wears dark naval officer armour with gold maritime trim and a high collar, human seafarer noble style. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Seran Gross",
        "slug": "seran-gross",
        "prompt": (
            "Trade Prince Seran Gross — human male, calculating sharp eyes, well-fed but cunning. "
            "Wears rich dark merchant's robes with a heavy gold chain of office, human merchant-lord style. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Ulric Ironmaul",
        "slug": "ulric-ironmaul",
        "prompt": (
            "Thane Ulric Ironmaul — dwarf male, broad and iron-built, stone-grey beard braided with iron rings, deep-set resolute eyes. "
            "Wears heavy dark dwarven plate armour with runic engravings hammered into the pauldrons, traditional dwarven forge-lord style. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Lythara the Veiled",
        "slug": "lythara-the-veiled",
        "prompt": (
            "Queen Lythara the Veiled — dark elf female, ageless and cold, pale silver skin, long white hair, half-concealed by a dark shadow-silk veil. "
            "Wears black elven court armour with obsidian trim and silver runes, dark elf shadow court noble style. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Elowen Silverleaf",
        "slug": "elowen-silverleaf",
        "prompt": (
            "Sovereign Elowen Silverleaf — high elf female, silver hair, pointed ears, composed and sorrowful eyes. "
            "Wears dark forest-green elven armour with silver leaf-scroll engravings and a flowing ceremonial mantle, high elf sovereign style. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Hargan Stonejaw",
        "slug": "hargan-stonejaw",
        "prompt": (
            "First Elder Hargan Stonejaw — orc male elder, green-grey skin, heavy scarred face, iron-grey tusks, massive frame. "
            "Wears ceremonial dark iron orc elder armour with clan totems and bone decorations, orc council elder style. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Morgath Bloodstone",
        "slug": "morgath-bloodstone",
        "prompt": (
            "Chieftain Morgath Bloodstone — orc male warlord, deep green skin, red eyes, wild dark hair, brutal scarred face. "
            "Wears dark spiked orc war-armour with bloodstone inlays and fur trim, orc warlord chieftain style. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Skrix Cogtooth",
        "slug": "skrix-cogtooth",
        "prompt": (
            "Speaker Skrix Cogtooth — goblin male, small and wiry, huge sharp yellow eyes, jagged teeth, unsettling cunning intelligence. "
            "Wears dark patchwork leather armour with scavenged metal fittings and a makeshift cloak of dark fabric, goblin speaker style. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Rowen Blacktide",
        "slug": "rowen-blacktide",
        "prompt": (
            "Fleet Captain Rowen Blacktide — human male, salt-weathered face, old scar across cheek, dark eyes that read weather and people alike. "
            "Wears a dark weathered naval captain's coat with no crown allegiance, leather and iron fittings, pirate lord style. "
            f"{STYLE}"
        ),
    },
]


def generate(ruler):
    out = OUT_DIR / f"{ruler['slug']}.png"
    # Always overwrite to apply new style
    print(f"  GEN   {ruler['name']} ...", end=" ", flush=True)
    try:
        r = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={"model": MODEL, "prompt": ruler["prompt"], "size": "1024x1024"},
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

        # Update portrait_image path in world_state
        print("OK")
    except Exception as e:
        print(f"ERROR {e}")


def update_world_state():
    ws_path = Path(__file__).parent / "world_state.json"
    with open(ws_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    slug_map = {r["name"]: f"/static/illustrations/characters/{r['slug']}.png" for r in RULERS}

    for row in state.get("leadership_state", []):
        ruler = row.get("currentRuler", {})
        if ruler.get("name") in slug_map:
            ruler["portrait_image"] = slug_map[ruler["name"]]

    with open(ws_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print("\nworld_state.json updated with new portrait paths.")


if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: OPENAI_API_KEY not set")
        raise SystemExit(1)

    print(f"Regenerating {len(RULERS)} ruler portraits in new CK3 style...\n")
    for i, ruler in enumerate(RULERS):
        generate(ruler)
        if i < len(RULERS) - 1:
            time.sleep(2)

    update_world_state()
    print("\nDone. Restart Flask to serve new portraits.")
