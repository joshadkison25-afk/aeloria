"""Generate faction banner images for the god panel faction cards."""
import os, base64, time, requests, json
from pathlib import Path

# Load .env from same directory as this script
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
MODEL   = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
OUT_DIR = Path(__file__).parent / "static" / "illustrations" / "factions"
OUT_DIR.mkdir(parents=True, exist_ok=True)

STYLE = (
    "Crusader Kings 3 style, realistic painted scene, cinematic lighting, dark background, "
    "soft shadows, oil painting style, ultra detailed, muted colors, high realism, depth of field. "
    "No text, no letters, no watermark, no UI frame, no border."
)

FACTIONS = [
    {
        "name": "Twin Cities",
        "slug": "twin-cities",
        "prompt": (
            "Twin Cities royal throne room interior — grand stone columns, candlelit vaulted ceiling, "
            "a heavy iron crown on a carved throne, red and gold royal banners, "
            "two noble advisors in formal court dress standing at the edge of the frame, "
            "human medieval royal court, politically charged atmosphere. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Tidefall",
        "slug": "tidefall",
        "prompt": (
            "Tidefall admiral's war room — dark maritime chamber cut into clifftop stone, "
            "a large naval map spread across a heavy table, lanterns swaying, "
            "a salt-weathered officer in dark naval armour with gold trim studying the map, "
            "warship silhouettes visible through a narrow window over stormy sea. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Dur Khadur",
        "slug": "dur-khadur",
        "prompt": (
            "Dur Khadur forge hall interior — enormous dwarven forge chamber carved from black granite, "
            "rivers of molten iron, rune-carved pillars, heavy iron chains and war-bells, "
            "a dwarven smith in heavy armour inspecting a freshly cast blade, "
            "ancient dwarven stronghold, iron and fire, immovable. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Lostfeld Dwarves",
        "slug": "lostfeld-dwarves",
        "prompt": (
            "Lostfeld deep mine gate chamber — vast underground dwarven cavern, "
            "a massive iron gate set into the rock face, sealed with heavy chains and runic wards, "
            "dwarf guards with lanterns posted at the entrance, strange warmth rising from below, "
            "oppressive stone ceiling, something ancient sealed behind the gate. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Shadow Court",
        "slug": "shadow-court",
        "prompt": (
            "Shadow Court throne chamber — a dark elf court in a black-stone forest palace, "
            "obsidian throne draped in shadow-silk, silver rune lights in the walls, "
            "a pale dark elf queen in black armour seated in absolute stillness, "
            "violet mist drifting across the floor, cold ancient power. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Glenhaven",
        "slug": "glenhaven",
        "prompt": (
            "Glenhaven sovereign council chamber — an open-air high elf meeting hall woven between ancient trees, "
            "silver leaf-scroll columns, moonlight through the canopy, "
            "three elven councillors in forest-green ceremonial robes around a stone table, "
            "emerald banners, serious deliberation, ancient wisdom under external pressure. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Gilgeth Clans",
        "slug": "gilgeth-clans",
        "prompt": (
            "Gilgeth elder council fire — a great hall inside a red-stone orc fortress, "
            "a massive fire burning in the centre, scarred orc elders seated in a circle on carved stone, "
            "clan totems hanging from iron rafters, iron war-shields on the walls, "
            "deliberate and proud, orc honour culture in formal session. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Groth Clans",
        "slug": "groth-clans",
        "prompt": (
            "Groth Clans war camp at night — a highland orc warlord's open encampment on a rocky plateau, "
            "fires burning low, bone-and-iron banners, a chieftain in spiked dark armour standing over a war map, "
            "his warband behind him in the darkness, brutal and restless, mountains beyond. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Vilefin",
        "slug": "vilefin",
        "prompt": (
            "Vilefin speaker's den — a cramped goblin command room inside a patchwork tower, "
            "salvaged lanterns, stacked crates of stolen goods, a wiry goblin speaker gesturing at crude maps, "
            "two sharp-eyed goblin lieutenants listening, chaotic but purposeful, "
            "survival through cunning and information. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Dreadwind",
        "slug": "dreadwind",
        "prompt": (
            "Dreadwind fleet captain's cabin — a weathered ship's cabin at sea, "
            "charts pinned to dark wood walls, a lantern swinging with the waves, "
            "a salt-worn captain in a dark weathered coat studying a nautical chart, "
            "an iron key on the table, no crown allegiance, open water through the porthole. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Gilded Exchange",
        "slug": "gilded-exchange",
        "prompt": (
            "Gilded Exchange trading hall — a vaulted merchant hall with golden ceiling reliefs, "
            "long tables covered in ledgers, coin scales, and sealed contracts, "
            "a sharp-eyed human trade lord in rich dark robes with a heavy gold chain of office, "
            "two scribes behind him, wealth and leverage without a single blade in sight. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Gloomspire Syndicate",
        "slug": "gloomspire-syndicate",
        "prompt": (
            "Gloomspire Syndicate briefing room — a narrow chamber inside a hollow city spire, "
            "black-glass walls, a single lantern, hooded figures around a stone table, "
            "poison vials and sealed assignment scrolls arranged precisely, "
            "an assassin guild leader in dark leather reviewing a contract, lethal calm. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Monastery of Druids",
        "slug": "monastery-of-druids",
        "prompt": (
            "Monastery of Druids archive chamber — a candlelit stone library deep inside a sacred monastery, "
            "shelves of ancient pre-Accord texts, a grey-robed Grand Druid reading aloud from an open book, "
            "runes on the pages glowing faintly, a sealed vault door visible at the far end of the chamber, "
            "knowledge and danger in equal measure. "
            f"{STYLE}"
        ),
    },
    {
        "name": "Dragon Clans",
        "slug": "dragon-clans",
        "prompt": (
            "Dragon Clans mountain roost — a volcanic peak at dusk, enormous dragon resting on a stone ledge, "
            "ancient scales catching firelight, scorched rock, bone-and-obsidian clan totems carved into the cliff, "
            "a lone dragon rider in blackened armour standing before the creature, "
            "elemental scale, older than any human war. "
            f"{STYLE}"
        ),
    },
]


def generate(faction):
    out = OUT_DIR / f"{faction['slug']}.png"
    print(f"  GEN   {faction['name']} ...", end=" ", flush=True)
    try:
        r = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={"model": MODEL, "prompt": faction["prompt"], "size": "1024x1024"},
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

    print(f"Generating {len(FACTIONS)} faction images...\n")
    for i, faction in enumerate(FACTIONS):
        generate(faction)
        if i < len(FACTIONS) - 1:
            time.sleep(2)

    print("\nDone. Restart Flask to serve new faction images.")
