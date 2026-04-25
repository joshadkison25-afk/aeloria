"""Generate race emblems and house/clan coats of arms for the Characters tab."""
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
RACE_DIR.mkdir(parents=True, exist_ok=True)
HOUSE_DIR.mkdir(parents=True, exist_ok=True)

SHIELD_STYLE = (
    "Medieval heraldic coat of arms, painted shield on dark stone, "
    "Crusader Kings 3 style, oil painting, cinematic lighting, muted colors, "
    "ultra detailed, high realism. No text, no letters, no watermark, no UI frame, no border."
)

RACE_STYLE = (
    "Medieval fantasy race emblem on dark stone, "
    "Crusader Kings 3 style, oil painting, cinematic lighting, muted colors, "
    "ultra detailed, high realism. No text, no letters, no watermark, no UI frame, no border."
)

RACES = [
    {
        "name": "Human",
        "slug": "human",
        "prompt": (
            "Human race emblem — a crowned iron shield bearing a rising sun, "
            "crossed swords beneath, noble and martial, medieval human heraldry. "
            f"{RACE_STYLE}"
        ),
    },
    {
        "name": "Dwarf",
        "slug": "dwarf",
        "prompt": (
            "Dwarf race emblem — a stone-carved shield bearing crossed war-hammers "
            "over a forge flame, rune border, dwarven mountain stronghold heraldry. "
            f"{RACE_STYLE}"
        ),
    },
    {
        "name": "High Elf",
        "slug": "high-elf",
        "prompt": (
            "High Elf race emblem — a silver shield bearing a crescent moon above a silver tree, "
            "delicate leaf-scroll border, ancient elven forest court heraldry. "
            f"{RACE_STYLE}"
        ),
    },
    {
        "name": "Dark Elf",
        "slug": "dark-elf",
        "prompt": (
            "Dark Elf race emblem — an obsidian shield bearing a spider above a broken moon, "
            "shadow-silk border, dark elf shadow court heraldry, cold and ancient. "
            f"{RACE_STYLE}"
        ),
    },
    {
        "name": "Orc",
        "slug": "orc",
        "prompt": (
            "Orc race emblem — a scarred iron shield bearing crossed tusks over a fist, "
            "bone-and-chain border, brutal orc clan heraldry, proud and warrior. "
            f"{RACE_STYLE}"
        ),
    },
    {
        "name": "Goblin",
        "slug": "goblin",
        "prompt": (
            "Goblin race emblem — a patchwork iron shield bearing a coiled serpent "
            "gripping a coin, scavenged bolt-and-gear border, goblin cunning heraldry. "
            f"{RACE_STYLE}"
        ),
    },
]

HOUSES = [
    # ── Twin Cities (Human) ────────────────────────────────────
    {
        "name": "House Adkison",
        "slug": "house-adkison",
        "prompt": (
            "House Adkison coat of arms — a red shield bearing a black eagle with spread wings, "
            "gold trim border, Twin Cities royal court nobility, human medieval heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "House Aurand",
        "slug": "house-aurand",
        "prompt": (
            "House Aurand coat of arms — a deep blue shield bearing a silver tower, "
            "gold star above, Twin Cities noble house, human medieval heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "House Dale",
        "slug": "house-dale",
        "prompt": (
            "House Dale coat of arms — a green shield bearing a gold wheat sheaf, "
            "Twin Cities landed nobility, human medieval heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "House Gross",
        "slug": "house-gross",
        "prompt": (
            "House Gross coat of arms — a dark gold shield bearing black scales of justice, "
            "Twin Cities merchant-lord house, wealth and leverage, human medieval heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "House Highland",
        "slug": "house-highland",
        "prompt": (
            "House Highland coat of arms — a grey shield bearing a white stag on a hill, "
            "Twin Cities noble house, human medieval heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "House Van Cleave",
        "slug": "house-van-cleave",
        "prompt": (
            "House Van Cleave coat of arms — a crimson shield bearing a silver gauntlet holding a sword, "
            "Twin Cities military house, human medieval heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    # ── Tidefall (Human) ──────────────────────────────────────
    {
        "name": "House Binx",
        "slug": "house-binx",
        "prompt": (
            "House Binx coat of arms — a dark teal shield bearing a white anchor, "
            "Tidefall naval house, maritime human heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "House Darkleaf",
        "slug": "house-darkleaf",
        "prompt": (
            "House Darkleaf coat of arms — a black shield bearing a dark green leaf crossed with a dagger, "
            "Tidefall intrigue house, human medieval heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "House Fish",
        "slug": "house-fish",
        "prompt": (
            "House Fish coat of arms — a blue shield bearing a silver leaping fish, "
            "Tidefall harbour house, human maritime heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "House Ver Meer",
        "slug": "house-ver-meer",
        "prompt": (
            "House Ver Meer coat of arms — a dark navy shield bearing a gold trident, "
            "Tidefall admiral house, commanding maritime human heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    # ── Dreadwind (Human) ─────────────────────────────────────
    {
        "name": "House Blacktide",
        "slug": "house-blacktide",
        "prompt": (
            "House Blacktide coat of arms — a black shield bearing a white skull over crossed cutlasses, "
            "Dreadwind pirate captain house, human maritime heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "House Saltbreach",
        "slug": "house-saltbreach",
        "prompt": (
            "House Saltbreach coat of arms — a grey-blue shield bearing a crashing wave over jagged rocks, "
            "Dreadwind corsair house, human maritime heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "House Stormvane",
        "slug": "house-stormvane",
        "prompt": (
            "House Stormvane coat of arms — a dark grey shield bearing a lightning bolt through a ship's wheel, "
            "Dreadwind storm-rider house, human maritime heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    # ── Glenhaven (High Elf) ───────────────────────────────────
    {
        "name": "House Moonwhisper",
        "slug": "house-moonwhisper",
        "prompt": (
            "House Moonwhisper coat of arms — a silver shield bearing a crescent moon above a single feather, "
            "Glenhaven high elf noble house, elven forest council heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "House Silverleaf",
        "slug": "house-silverleaf",
        "prompt": (
            "House Silverleaf coat of arms — a forest-green shield bearing a silver oak leaf, "
            "Glenhaven sovereign house, high elf ancient heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    # ── Shadow Court (Dark Elf) ────────────────────────────────
    {
        "name": "House Nightborn",
        "slug": "house-nightborn",
        "prompt": (
            "House Nightborn coat of arms — an obsidian shield bearing a violet crescent over a coiled serpent, "
            "Shadow Court dark elf noble house, ancient shadow heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "House Shadowveil",
        "slug": "house-shadowveil",
        "prompt": (
            "House Shadowveil coat of arms — a black shield bearing silver eyes in shadow, "
            "Shadow Court dark elf assassin house, cold ancient heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    # ── Gilgeth Clans (Orc) ───────────────────────────────────
    {
        "name": "Clan Ashfang",
        "slug": "clan-ashfang",
        "prompt": (
            "Clan Ashfang orc clan crest — a dark iron shield bearing grey ashen fangs above a burning ember, "
            "Gilgeth orc elder council clan, brutal proud orc heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "Clan Ironhide",
        "slug": "clan-ironhide",
        "prompt": (
            "Clan Ironhide orc clan crest — a black iron shield bearing a great iron-plated fist, "
            "Gilgeth orc elder council clan, warrior orc heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "Clan Stonejaw",
        "slug": "clan-stonejaw",
        "prompt": (
            "Clan Stonejaw orc clan crest — a grey stone shield bearing a massive carved jaw set in rock, "
            "Gilgeth orc elder council clan, immovable elder orc heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    # ── Groth Clans (Orc) ─────────────────────────────────────
    {
        "name": "Clan Bloodstone",
        "slug": "clan-bloodstone",
        "prompt": (
            "Clan Bloodstone orc clan crest — a dark red shield bearing a bloodstone shard above crossed axes, "
            "Groth highland orc warlord clan, brutal war heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "Clan Redtusk",
        "slug": "clan-redtusk",
        "prompt": (
            "Clan Redtusk orc clan crest — a black shield bearing a red-stained tusk, "
            "Groth highland orc raider clan, savage war heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    # ── Vilefin (Goblin) ──────────────────────────────────────
    {
        "name": "Clan Cogtooth",
        "slug": "clan-cogtooth",
        "prompt": (
            "Clan Cogtooth goblin clan crest — a patchwork iron shield bearing a gear set with a jagged tooth, "
            "Vilefin goblin cunning clan, scavenged tinkerer heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "Clan Rustfang",
        "slug": "clan-rustfang",
        "prompt": (
            "Clan Rustfang goblin clan crest — a corroded iron shield bearing a rust-eaten fang, "
            "Vilefin goblin survivor clan, chaotic scavenger heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    # ── Lostfeld Dwarves (Dwarf) ──────────────────────────────
    {
        "name": "Clan Ironmaul",
        "slug": "clan-ironmaul",
        "prompt": (
            "Clan Ironmaul dwarf clan crest — a dark iron shield bearing a great war-maul with rune engravings, "
            "Lostfeld dwarf thane clan, forge-lord dwarven heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "Goldfinger-Duke Clan",
        "slug": "goldfinger-duke-clan",
        "prompt": (
            "Goldfinger-Duke dwarf clan crest — a gold shield bearing a gauntleted hand with a gemstone ring, "
            "Lostfeld dwarf merchant-lord clan, wealthy dwarven heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
    {
        "name": "Runewardens Clan",
        "slug": "runewardens-clan",
        "prompt": (
            "Runewardens dwarf clan crest — a dark blue stone shield bearing a glowing rune circle, "
            "Lostfeld dwarf scholar-guardian clan, ancient rune-keeper heraldry. "
            f"{SHIELD_STYLE}"
        ),
    },
]


def generate(item, out_dir):
    out = out_dir / f"{item['slug']}.png"
    if out.exists():
        print(f"  SKIP  {item['name']} (exists)")
        return
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

    print(f"Generating {len(RACES)} race emblems...\n")
    for i, race in enumerate(RACES):
        generate(race, RACE_DIR)
        if i < len(RACES) - 1:
            time.sleep(2)

    print(f"\nGenerating {len(HOUSES)} house/clan coats of arms...\n")
    for i, house in enumerate(HOUSES):
        generate(house, HOUSE_DIR)
        if i < len(HOUSES) - 1:
            time.sleep(2)

    print("\nDone. Restart Flask to serve new coat of arms images.")
