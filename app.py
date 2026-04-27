import atexit
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory

from aeloria_llm import complete_chat_anthropic_format

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "logs" / "aeloria.log"),
    ],
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
WORLD_STATE_FILE = BASE_DIR / "world_state.json"
PENDING_LORE_FILE = BASE_DIR / "pending_lore.json"
HISTORY_DIR = BASE_DIR / "history"
CONVERSATIONS_DIR = BASE_DIR / "conversations"
GOD_ACTIONS_FILE = BASE_DIR / "god_actions.json"
SYNOPSIS_FILE = BASE_DIR / "narrative_synopsis.txt"
CHARACTER_PORTRAIT_JOBS_FILE = BASE_DIR / "character_portrait_jobs.json"
CODEX_IMAGE_JOBS_FILE = BASE_DIR / "codex_image_jobs.json"
IMAGE_GENERATION_STATE_FILE = BASE_DIR / "image_generation_state.json"
MAP_PUBLIC_URL = os.getenv("MAP_PUBLIC_URL", "http://localhost:3000/map")
# Same image as Next `/map` by default (files under ./public). Override with NEXT_PUBLIC_MAP_ATLAS_URL or HOME_ATLAS_URL.
HOME_ATLAS_URL = (
    os.getenv("HOME_ATLAS_URL")
    or os.getenv("NEXT_PUBLIC_MAP_ATLAS_URL")
    or "/aeloria-basemap-paint.png"
)
HOME_INTERACTIVE_MAP = os.getenv("HOME_INTERACTIVE_MAP", "1").strip().lower() not in ("0", "false", "no")


def _warn_map_public_url_for_embed() -> None:
    if not HOME_INTERACTIVE_MAP:
        return
    parsed = urlsplit(MAP_PUBLIC_URL)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return
    # Path-only URLs are fine behind one reverse-proxy host (prod). Two-port local dev needs an absolute URL.
    devish = os.getenv("FLASK_DEBUG", "0").strip().lower() in ("1", "true", "yes", "on")
    if not devish or not (parsed.path or "").startswith("/"):
        return
    logger.warning(
        "HOME_INTERACTIVE_MAP is on and MAP_PUBLIC_URL=%r is path-only while FLASK_DEBUG is enabled. "
        "If the home atlas iframe is wrong or nested, set MAP_PUBLIC_URL=http://127.0.0.1:3000/map for local Next on port 3000.",
        MAP_PUBLIC_URL,
    )


_warn_map_public_url_for_embed()

app = Flask(__name__)


def _map_iframe_url(extra_query: dict[str, str] | None = None) -> str:
    """Next `/map` URL with cache-buster (Map.tsx mtime). Optional query keys merged in."""
    try:
        map_ts = int((BASE_DIR / "components" / "Map.tsx").stat().st_mtime)
    except OSError:
        map_ts = 0
    parsed = urlsplit(MAP_PUBLIC_URL)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["cb"] = str(map_ts)
    if extra_query:
        query.update(extra_query)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


@app.context_processor
def _inject_map_public_url():
    return {
        "map_public_url": MAP_PUBLIC_URL,
        "home_atlas_url": HOME_ATLAS_URL,
        "map_iframe_url": _map_iframe_url(),
        "home_map_iframe_url": _map_iframe_url({"embed": "1"}),
        "home_interactive_map": HOME_INTERACTIVE_MAP,
    }

BATTLE_PATTERNS = [
    r"\bbattle\b",
    r"\bbattles\b",
    r"\bwar\b",
    r"\bwarfare\b",
    r"\bskirmish\b",
    r"\bsiege\b",
    r"\bclash\b",
    r"\braid\b",
    r"\bassault\b",
    r"\bcampaign\b",
    r"\bwarship\b",
    r"\bwarships\b",
    r"\bwar-band\b",
    r"\bwar-bands\b",
    r"\bfleet\b",
]


# ── Permanent house identities ────────────────────────────────────────────────
# These houses always exist in every new game; only their members get fresh names.
_PERMANENT_HOUSES = [
    # Shadow Court — Dark Elf, Faerwood
    {"house": "House Verlorn",          "race": "Dark Elf",  "home": "dense forest"},
    {"house": "House Nightborn",        "race": "Dark Elf",  "home": "dense forest"},
    {"house": "House Shadowveil",       "race": "Dark Elf",  "home": "dense forest"},
    # Twin Cities — Human, plains
    {"house": "House Aurand",           "race": "Human",     "home": "plains"},
    {"house": "House Braafhart",        "race": "Human",     "home": "plains"},
    {"house": "House LeFleur",          "race": "Human",     "home": "plains"},
    {"house": "House Bower",            "race": "Human",     "home": "plains"},
    {"house": "House Binx",             "race": "Human",     "home": "plains"},
    {"house": "House Dale",             "race": "Human",     "home": "plains"},
    # Glenhaven — Wood Elf, forest
    {"house": "House Wood",             "race": "Wood Elf",  "home": "dense forest"},
    {"house": "House Darkleaf",         "race": "Wood Elf",  "home": "dense forest"},
    {"house": "House Mistafae",         "race": "Wood Elf",  "home": "dense forest"},
    # Tidefall — Human, coastal
    {"house": "House Ver Meer",         "race": "Human",     "home": "coastal"},
    {"house": "House Highland-Dusken",  "race": "Human",     "home": "coastal"},
    {"house": "House Fish",             "race": "Human",     "home": "coastal"},
    {"house": "House McGowan",          "race": "Human",     "home": "coastal"},
    # Varkuun — Human, rugged
    {"house": "House Van Cleave",       "race": "Human",     "home": "rugged"},
    # Dur Khadur — Human, mountain
    {"house": "House Gross",            "race": "Human",     "home": "mountain"},
    {"house": "House Delonious",        "race": "Human",     "home": "mountain"},
    {"house": "House Galfazzar",        "race": "Human",     "home": "mountain"},
    {"house": "House Vercenti",         "race": "Human",     "home": "mountain"},
    # The Wintermark — Human, frozen
    {"house": "House Adkison",          "race": "Human",     "home": "frozen"},
    {"house": "House McIntosh",         "race": "Human",     "home": "frozen"},
    {"house": "House Holter",           "race": "Human",     "home": "frozen"},
    {"house": "House Duval",            "race": "Human",     "home": "frozen"},
    # Dreadwind Isles — Human, coastal
    {"house": "House Blacktide",        "race": "Human",     "home": "coastal"},
    # Lostfeld — Dwarf, mountain
    {"house": "Clan Goldfinger-Duke",   "race": "Dwarf",     "home": "mountain"},
    {"house": "Clan Runewarden",        "race": "Dwarf",     "home": "mountain"},
    {"house": "Clan Ironmaul",          "race": "Dwarf",     "home": "mountain"},
    # Groth Clans — Orc, mountain
    {"house": "Clan Mijid",             "race": "Orc",       "home": "mountain"},
    {"house": "Clan Ashfang",           "race": "Orc",       "home": "mountain"},
    {"house": "Clan Syncar",            "race": "Orc",       "home": "mountain"},
    # Gilgeth Clans — Orc, mountain
    {"house": "Clan Blackblood",        "race": "Orc",       "home": "mountain"},
    {"house": "Clan Ironhide",          "race": "Orc",       "home": "mountain"},
    {"house": "Clan Redtusk",           "race": "Orc",       "home": "mountain"},
    # Vilefin — Goblin, stone plains
    {"house": "Clan Bloodware",         "race": "Goblin",    "home": "stone plains"},
    {"house": "Clan Cogtooth",          "race": "Goblin",    "home": "stone plains"},
    {"house": "Clan Rustfang",          "race": "Goblin",    "home": "stone plains"},
]

_FRESH_NAMES = {
    "Human":    ["Aldric","Bren","Caela","Davan","Elsin","Farryn","Gara","Holt","Isel","Jorn",
                 "Kella","Leris","Maren","Nori","Orlen","Petra","Quel","Rana","Sela","Torren",
                 "Ulva","Varis","Wren","Aryn","Berin","Doryn","Erris","Fael","Garyn","Heva"],
    "High Elf": ["Aelindra","Bereth","Caladis","Daerith","Elowen","Faelyn","Galadis","Haerith",
                 "Iorel","Jaelis","Kaladis","Lysse","Maerith","Naelis","Oreith","Pyriel","Raelis",
                 "Silith","Taeris","Urelith","Vaelin","Waelis","Xirith","Yaelis","Zaelin"],
    "Wood Elf": ["Aelvorn","Brenwynn","Caeldrith","Daevorn","Eolith","Faernyl","Gaelorn","Haelvyn",
                 "Idrelith","Jaevorn","Kaelwyn","Lorelyn","Maevorn","Naelith","Orelwyn","Pyrelyn",
                 "Raevorn","Sylvorn","Taelvyn","Urvelyn","Vaelyn","Weldrith","Xaelvyn","Yaelvyn",
                 "Zaelorn","Thalorn"],
    "Dwarf":    ["Aldrok","Breth","Dorva","Grath","Helva","Kordak","Morra","Orik","Runa","Skor",
                 "Thora","Urgom","Vessa","Wulda","Bera","Dagna","Fulda","Grunda","Hulda","Jorva"],
}

_HOUSE_MEMBER_ROLES = [
    ("Leader",  "House head",      72, 62, 68, 74, "honorable"),
    ("Heir",    "Heir apparent",   58, 64, 62, 70, "defensive"),
    ("Advisor", "Senior adviser",  54, 72, 52, 68, "opportunistic"),
    ("Agent",   "House agent",     50, 58, 64, 60, "opportunistic"),
]

# ── Region-based faction lore ─────────────────────────────────────────────────
FACTION_LORE: dict[str, dict] = {
    "Shadow Court":          {"species": "Dark Elf",   "role": "Shadow Dominion"},
    "Twin Cities":           {"species": "Human",      "role": "Dual Monarchy"},
    "Glenhaven":             {"species": "Wood Elf",   "role": "Forest Sovereignty"},
    "Groth Clans":           {"species": "Orc",        "role": "War Dominion"},
    "Gilgeth Clans":         {"species": "Orc",        "role": "Organized War State"},
    "Tidefall":              {"species": "Human",      "role": "Naval Trade Power"},
    "Varkuun":               {"species": "Human",      "role": "Mercenary Fortress"},
    "Vilefin":               {"species": "Goblin",     "role": "Scavenger Network"},
    "The Wintermark":        {"species": "Human",      "role": "Frozen Fortress Kingdom"},
    "Lostfeld":              {"species": "Dwarf",      "role": "Mountain Hold"},
    "Dur Khadur":            {"species": "Human",      "role": "Trade Prince Fortress"},
    "Dreadwind Isles":       {"species": "Human",      "role": "Pirate Fleet"},
    "Stonebreak Monastery":  {"species": "Human",      "role": "Druid Monastery"},
}

_SPECIES_RULER: dict[str, tuple] = {
    "Human":            ("Lord",            ["Ambitious", "Pragmatic"],              "appointment"),
    "Dark Elf":         ("Shadowlord",      ["Cunning", "Patient", "Ruthless"],      "chosen"),
    "High Elf":         ("Archon",          ["Ancient", "Measured"],                 "council vote"),
    "High Elf (Ancient)":("Archon",         ["Ancient", "Measured", "Inscrutable"],  "council vote"),
    "Wood Elf":         ("Sovereign",       ["Ancient", "Protective", "Insular"],    "council vote"),
    "Dwarf":            ("Thane",           ["Stubborn", "Honorable"],               "inheritance"),
    "Orc":              ("Warchief",        ["Brutal", "Fierce"],                    "combat"),
    "Goblin":           ("Boss",            ["Greedy", "Cunning"],                   "bribery"),
    "Kenku":            ("Speaker",         ["Cunning", "Observant"],                "election"),
    "Centaur":          ("Chieftain",       ["Fierce", "Independent"],               "combat"),
    "Tortle":           ("Elder",           ["Patient", "Wise"],                     "council vote"),
    "Faeborn":          ("Sovereign",       ["Elusive", "Mystical"],                 "chosen"),
    "Vargai":           ("Pack-lord",       ["Loyal", "Fierce"],                     "combat"),
    "Ursari":           ("Den-lord",        ["Territorial", "Enduring"],             "inheritance"),
    "Frostwraith":      ("Wraith",          ["Ancient", "Unknowable"],               "unknown"),
    "Frost Fey":        ("Winter Queen",    ["Mystical", "Capricious"],              "chosen"),
    "Tideborn":         ("Tide-lord",       ["Fluid", "Strategic"],                  "election"),
    "Roki":             ("Stone-speaker",   ["Stubborn", "Ancient"],                 "council vote"),
    "Kharox":           ("War-elder",       ["Brutal", "Cunning"],                   "combat"),
    "Gravekin":         ("Deepmaster",      ["Ancient", "Patient"],                  "chosen"),
    "Gritkin":          ("Burrow-chief",    ["Cunning", "Industrious"],              "election"),
    "Scorpid":          ("Sting-lord",      ["Precise", "Ruthless"],                 "combat"),
    "Shaleborn":        ("Anchor",          ["Immovable", "Ancient"],                "chosen"),
    "Skarren":          ("Scavenge-lord",   ["Cunning", "Opportunistic"],            "power"),
    "Multi-species":    ("Covenant-Speaker",["Diplomatic", "Wise"],                  "council vote"),
    "Sylthari":         ("Web-sovereign",   ["Patient", "Territorial"],              "chosen"),
    "Verdan":           ("Root-guardian",   ["Ancient", "Protective"],               "chosen"),
    "Stonekin":         ("Stone-warden",    ["Stubborn", "Enduring"],                "inheritance"),
}


def _build_fresh_house_characters(faction_identities: dict) -> list:
    """
    Generate one set of fresh (randomly-named) house_character entries for
    the permanent houses, matched to whichever factions are present by race.
    Returns a list ready to drop into world["house_characters"].
    """
    import random

    # Map race → first faction name that has that race
    race_to_faction: dict[str, str] = {}
    for fname, fdata in faction_identities.items():
        r = fdata.get("race", "Human")
        if r not in race_to_faction:
            race_to_faction[r] = fname

    chars = []
    used_first_names: set = set()

    for hdef in _PERMANENT_HOUSES:
        race     = hdef["race"]
        house    = hdef["house"]
        faction  = race_to_faction.get(race)
        if not faction:
            continue  # no faction of this race in this world — skip

        name_pool = list(_FRESH_NAMES.get(race, _FRESH_NAMES["Human"]))
        random.shuffle(name_pool)

        last_name = house.replace("House ", "").replace(" Clan", "").replace("-Duke", "")

        member_pool = list(_HOUSE_MEMBER_ROLES)
        random.shuffle(member_pool)

        for i, (core_role, role_label, influence, morality, ambition, loyalty, bias) in enumerate(member_pool[:4]):
            # Pick an unused first name from the pool
            first = next((n for n in name_pool if n not in used_first_names), name_pool[0])
            used_first_names.add(first)
            name_pool = [n for n in name_pool if n != first]

            full_name = f"{first} {last_name}"
            age = [45, 32, 38, 27][i]
            intel = max(35, min(90, int((influence + ambition + loyalty) / 3)))

            chars.append({
                "name":         full_name,
                "faction":      faction,
                "house":        house,
                "coreRole":     core_role,
                "role":         role_label,
                "status":       "alive",
                "age":          float(age),
                "race":         race,
                "influenceScore": influence,
                "morality":     float(morality),
                "ambition":     float(ambition),
                "loyalty":      float(loyalty),
                "intelligence": float(intel),
                "bias":         bias,
                "currentGoal":  "",
                "recentActions": [],
                "location":     "",
                "destination":  "",
                "ticks_to_arrive": 0,
                "journey_purpose": "",
                "warfare":   max(5, min(95, int(ambition * 0.5 + (100 - morality) * 0.3 + influence * 0.2))),
                "diplomacy": max(5, min(95, int(intel * 0.4 + loyalty * 0.4 + morality * 0.2))),
                "intrigue":  max(5, min(95, int(ambition * 0.4 + (100 - loyalty) * 0.3 + intel * 0.3))),
                "faith":     20,
                "health":    85.0,
                "wounds":    [],
                "memory":    [],
                "relationships": {},
            })

    return chars


def _read_json(path, default):
    p = Path(path)
    if p.exists() and p.stat().st_size > 0:
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return default


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _classify_chronicle_entry(text, major_event="", mood=""):
    haystack = f"{major_event} {text}".lower()
    if mood.lower() == "violent":
        return "battles"
    if any(re.search(pattern, haystack) for pattern in BATTLE_PATTERNS):
        return "battles"
    return "chronicle"


def _chronicle_excerpt(text, limit=180):
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    trimmed = value[:limit].rsplit(" ", 1)[0].strip()
    return f"{trimmed}..."


def _default_population_state():
    return [
        {"region": "Twin Cities",   "species": "Humans",     "culture": "Twin Cities",         "population": 140000, "growthRate": 0.00025, "capacity": 170000, "health": 86, "pressure": 22, "activeMilitary": 4900, "navalAllocation": 3,  "notes": "Centralized human capital controlling Eresteron and Eldoria."},
        {"region": "Eldoria",       "species": "Humans",     "culture": "Twin Cities",         "population": 95000,  "growthRate": 0.00022, "capacity": 115000, "health": 82, "pressure": 18, "activeMilitary": 2850, "navalAllocation": 0,  "notes": "Cultural and artistic twin capital; may one day fracture from Eresteron."},
        {"region": "Tidefall",      "species": "Humans",     "culture": "Tidefall",            "population": 160000, "growthRate": 0.00028, "capacity": 185000, "health": 82, "pressure": 32, "activeMilitary": 6400, "navalAllocation": 20, "notes": "Naval power with large harbor population and fleet personnel."},
        {"region": "Faerwood",      "species": "Dark Elves", "culture": "Shadow Court",        "population": 30000,  "growthRate": 0.00003, "capacity": 42000,  "health": 74, "pressure": 38, "activeMilitary": 1050, "navalAllocation": 0,  "notes": "Low-growth dark elf society with high individual power and covert reach."},
        {"region": "Glenhaven",     "species": "Wood Elves", "culture": "Glenhaven",           "population": 35000,  "growthRate": 0.00005, "capacity": 52000,  "health": 88, "pressure": 18, "activeMilitary": 1225, "navalAllocation": 0,  "notes": "Stable, council-led wood elf forest sovereignty."},
        {"region": "Lostfeld",      "species": "Dwarves",    "culture": "Lostfeld",            "population": 65000,  "growthRate": 0.00008, "capacity": 85000,  "health": 81, "pressure": 24, "activeMilitary": 2275, "navalAllocation": 0,  "notes": "Sovereign dwarf mountain hold; strong lineage and rare betrayal."},
        {"region": "Gilgeth",       "species": "Orcs",       "culture": "Gilgeth Clans",       "population": 55000,  "growthRate": 0.00020, "capacity": 70000,  "health": 72, "pressure": 44, "activeMilitary": 2200, "navalAllocation": 0,  "notes": "Organized elder council orc stronghold; disciplined and enduring."},
        {"region": "Groth",         "species": "Orcs",       "culture": "Groth Clans",         "population": 45000,  "growthRate": 0.00022, "capacity": 60000,  "health": 68, "pressure": 52, "activeMilitary": 1800, "navalAllocation": 0,  "notes": "War capital orc region; chaotic, warchief-led, aggressive."},
        {"region": "Vilefin",       "species": "Goblins",    "culture": "Vilefin",             "population": 215000, "growthRate": 0.00055, "capacity": 230000, "health": 63, "pressure": 68, "activeMilitary": 8600, "navalAllocation": 0,  "notes": "High-growth goblin population near capacity; communal speaker system."},
        {"region": "Dreadwind Isles","species": "Humans",    "culture": "Dreadwind Isles",     "population": 45000,  "growthRate": 0.00018, "capacity": 65000,  "health": 67, "pressure": 52, "activeMilitary": 1800, "navalAllocation": 16, "notes": "Mobile exile fleet population; betrayal normalized, leadership volatile."},
        {"region": "Dur Khadur",    "species": "Humans",     "culture": "Dur Khadur",          "population": 115000, "growthRate": 0.00024, "capacity": 155000, "health": 79, "pressure": 36, "activeMilitary": 4025, "navalAllocation": 8,  "notes": "Trade-driven mountain fortress; transactional loyalties."},
        {"region": "Wintermark",    "species": "Humans",     "culture": "The Wintermark",      "population": 42000,  "growthRate": 0.00012, "capacity": 62000,  "health": 76, "pressure": 30, "activeMilitary": 1680, "navalAllocation": 0,  "notes": "Frost-hardened fortress kingdom; endurance over ambition."},
        {"region": "Varkuun",       "species": "Humans",     "culture": "Varkuun",             "population": 18000,  "growthRate": 0.00010, "capacity": 28000,  "health": 82, "pressure": 20, "activeMilitary": 1260, "navalAllocation": 0,  "notes": "Professional mercenary fortress; high military ratio, low natural growth."},
        {"region": "Stonebreak",    "species": "Druids",     "culture": "Stonebreak Monastery","population": 5500,   "growthRate": 0.00002, "capacity": 9000,   "health": 91, "pressure": 12, "activeMilitary": 275,  "navalAllocation": 0,  "notes": "Low population, very high influence; gnomes serve as covert arm."},
        {"region": "Dragonscar Peaks","species": "Ice Dragons","culture": "Dragon Clans",      "population": 12,     "growthRate": 0,       "capacity": 20,     "health": 94, "pressure": 9,  "activeMilitary": 12,   "navalAllocation": 0,  "notes": "Not a normal faction; each dragon is region-level power."},
    ]


# ── Core pages ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if not WORLD_STATE_FILE.exists():
        return redirect("/menu")
    return render_template("home.html", active_page="home")


@app.route("/menu")
def menu_page():
    return render_template("menu.html")


@app.route("/api/worlds", methods=["GET"])
def api_list_worlds():
    from world_manager import list_worlds
    return jsonify({"worlds": list_worlds()})


@app.route("/api/worlds/load", methods=["POST"])
def api_load_world():
    from world_manager import load_world_from_slot
    data = request.get_json(force=True)
    filename = data.get("filename", "").strip()
    if not filename:
        return jsonify({"error": "filename required"}), 400
    world = load_world_from_slot(filename)
    if not world:
        return jsonify({"error": "failed to load world"}), 404
    return jsonify({"ok": True})


@app.route("/api/worlds/campaign", methods=["POST"])
def api_load_campaign():
    src = BASE_DIR / "worlds" / "aeloria_campaign_start.json"
    if not src.exists():
        return jsonify({"error": "aeloria_campaign_start.json not found"}), 404
    try:
        world = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e:
        return jsonify({"error": f"failed to read campaign file: {e}"}), 500
    from scheduler import is_valid_world, safe_save_world
    if not world or not is_valid_world(world):
        return jsonify({"error": "campaign file failed validation"}), 500
    _reset_world_files(world.get("faction_identities") or {})
    safe_save_world(world)
    try:
        from scheduler import run_tick
        run_tick()
    except Exception as e:
        logger.warning(f"Campaign tick failed (world loaded anyway): {e}")
    return jsonify({"ok": True, "mode": world.get("mode", "campaign"), "tick": world.get("tick", 0)})


@app.route("/api/worlds/new", methods=["POST"])
def api_new_world():
    from world_manager import create_new_world
    # Preserve codex/faction artwork references before wiping state
    codex_images = {}
    if WORLD_STATE_FILE.exists():
        try:
            existing = json.loads(WORLD_STATE_FILE.read_text(encoding="utf-8"))
            codex_images = existing.get("codex_images", {})
        except Exception:
            pass
    world = create_new_world("starter_world.json")
    if not world:
        return jsonify({"error": "failed to create world"}), 500
    if codex_images:
        world["codex_images"] = codex_images
        from scheduler import is_valid_world, safe_save_world
        if world and world.keys() and is_valid_world(world):
            safe_save_world(world)
        else:
            logger.error("api_new_world: refusing to save codex patch — world failed validation")
    return jsonify({"ok": True})


@app.route("/api/worlds/save", methods=["POST"])
def api_save_world():
    from world_manager import save_world_as
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    save_world_as(name)
    return jsonify({"ok": True})


@app.route("/create")
def create_world_page():
    return render_template("create.html")


@app.route("/loading")
def loading_page():
    return render_template("loading.html")


@app.route("/enter")
def game_enter_page():
    """Full-screen cinematic bridge after menu → home (map/state warm-up)."""
    return render_template("game_enter.html")


@app.route("/api/faction-presets", methods=["GET"])
def api_faction_presets():
    presets_path = BASE_DIR / "faction_presets.json"
    data = json.loads(presets_path.read_text(encoding="utf-8"))
    return jsonify(data["presets"])


@app.route("/api/region-factions", methods=["GET"])
def api_region_factions():
    regions_path = BASE_DIR / "regions.json"
    data = json.loads(regions_path.read_text(encoding="utf-8"))
    result = []
    for region_name, region in data["regions"].items():
        factions = []
        for fname in region.get("available_factions", []):
            lore = FACTION_LORE.get(fname, {"species": "Unknown", "role": "Unknown"})
            factions.append({
                "name": fname,
                "species": lore["species"],
                "role": lore["role"],
                "is_canonical": fname == region.get("canonical_faction"),
            })
        result.append({
            "name": region_name,
            "terrain": region.get("terrain", ""),
            "canonical_faction": region.get("canonical_faction"),
            "factions": factions,
        })
    return jsonify(result)


def _reset_world_files(faction_identities: dict) -> None:
    """Wipe all per-run files so a new game starts completely clean."""
    for f in HISTORY_DIR.glob("chronicle_*.txt"):
        f.unlink(missing_ok=True)
    for f in HISTORY_DIR.glob("*_tick_*.json"):
        f.unlink(missing_ok=True)
    for f in HISTORY_DIR.glob("world_*.json"):
        f.unlink(missing_ok=True)
    _write_json(PENDING_LORE_FILE, [])
    if SYNOPSIS_FILE.exists():
        SYNOPSIS_FILE.write_text("", encoding="utf-8")

    faction_names = list(faction_identities.keys())
    races = list({v.get("race", "Unknown") for v in faction_identities.values()})
    seed_entry = {
        "type": "world_created",
        "target": "Aeloria",
        "detail": ", ".join(faction_names),
        "lore": (
            f"A new world has been forged. {len(faction_names)} faction{'s' if len(faction_names) != 1 else ''} "
            f"({', '.join(faction_names)}) now vie for dominance across Aeloria. "
            f"The age begins — every throne is unsettled, every border unproven."
        ),
        "timestamp": datetime.now().isoformat(),
    }
    _write_json(GOD_ACTIONS_FILE, [seed_entry])


def _build_world_from_regions(region_assignments: dict, world_name: str, portrait_cache: dict) -> "Response":
    import random

    # Load canonical region data for validation
    regions_path = BASE_DIR / "regions.json"
    regions_data = json.loads(regions_path.read_text(encoding="utf-8"))["regions"]

    # Validate: each assigned faction must exist in that region's available_factions
    errors = []
    for rname, fname in region_assignments.items():
        if not fname:
            continue
        rdata = regions_data.get(rname)
        if not rdata:
            errors.append(f"Unknown region: {rname!r}")
            continue
        available = rdata.get("available_factions", [])
        if fname not in available:
            errors.append(f"{fname!r} is not available in {rname!r} (available: {available})")
    if errors:
        return jsonify({"error": "invalid assignments", "details": errors}), 400

    # Exactly one faction per region is enforced by the dict structure (one value per key).
    # Filter out any regions with no assignment.
    assigned = {rname: fname for rname, fname in region_assignments.items() if fname}
    unique_factions = list(dict.fromkeys(assigned.values()))

    if not unique_factions:
        return jsonify({"error": "at least one region must have a faction assigned"}), 400

    leadership_state = []
    faction_identities = {}
    faction_power_state = {}
    relationships = {}

    for fname in unique_factions:
        lore = FACTION_LORE.get(fname, {"species": "Human", "role": "Unknown"})
        species = lore["species"]
        title, traits, succession = _SPECIES_RULER.get(species, ("Lord", ["Ambitious"], "appointment"))

        ruler_name = f"{title} of the {fname}"
        ruler = {
            "name": ruler_name,
            "title": title,
            "dynasty": f"House of {fname}",
            "age": random.randint(34, 58),
            "traits": traits,
            "causeOfRise": succession,
            "causeOfEnd": "",
            "startDay": 0,
            "endDay": None,
            "duration": 0,
            "notableEvents": [],
            "portrait_image": portrait_cache.get(ruler_name, ""),
        }

        leadership_state.append({
            "faction": fname,
            "currentRuler": ruler,
            "rulerHistory": [],
            "dynasties": [{"name": f"House of {fname}", "founder": ruler_name, "prestige": 50, "tier": 2, "status": "active", "members": [ruler_name]}],
        })

        faction_identities[fname] = {
            "race": species,
            "type": lore["role"],
            "description": f"The {fname} — {lore['role']}.",
            "traits": traits,
            "succession": succession,
        }

        faction_power_state[fname] = 50

        for other in unique_factions:
            if other == fname:
                continue
            relationships.setdefault(fname, {})[other] = {"score": 50, "status": "neutral"}

    # Build region map: strip meta fields, set controller only for assigned regions
    regions = {}
    for rname, rdata in regions_data.items():
        r = {k: v for k, v in rdata.items() if k not in ("available_factions", "canonical_faction")}
        r["controller"] = assigned.get(rname)  # None for unassigned regions
        regions[rname] = r

    world = {
        "tick": 0,
        "world_date": "Day 0",
        "primary_event": {
            "name": f"{world_name} Begins",
            "summary": f"{world_name} stirs to life. {len(unique_factions)} faction{'s' if len(unique_factions) != 1 else ''} take their first breath.",
            "severity": 1,
            "stage": "emerging",
            "trend": "stable",
            "involved": unique_factions[:6],
        },
        "supporting_events": [],
        "active_events": [],
        "active_tensions": [],
        "recent_events": [],
        "faction_actions": {},
        "faction_identities": faction_identities,
        "faction_power_state": faction_power_state,
        "leadership_state": leadership_state,
        "relationships": relationships,
        "house_characters": _build_fresh_house_characters(faction_identities),
        "character_updates": [],
        "faction_resources": {f: {"gold": 100, "food": 100, "troops": 50} for f in unique_factions},
        "population_state": [],
        "belief_currents": [],
        "religious_factions": [],
        "weather_and_omens": [],
        "war_outcomes": [],
        "whispers": [],
        "chronicle": [],
        "regions": regions,
    }
    if portrait_cache:
        world["portrait_cache"] = portrait_cache

    from scheduler import is_valid_world, safe_save_world
    if not is_valid_world(world):
        logger.error("_build_world_from_regions: refusing to save — world failed validation")
        return jsonify({"error": "world validation failed"}), 500
    safe_save_world(world)
    _reset_world_files(faction_identities)
    return jsonify({"ok": True, "factions": len(unique_factions), "regions_assigned": len(assigned)})


@app.route("/api/worlds/build", methods=["POST"])
def api_build_world():
    from world_manager import _extract_portrait_cache
    data = request.get_json(force=True)
    world_name = data.get("world_name", "").strip() or "Custom World"
    portrait_cache = _extract_portrait_cache()

    # ── Region-based builder ──────────────────────────────────────────────────
    region_assignments = data.get("region_assignments")
    if region_assignments is not None:
        if not isinstance(region_assignments, dict) or not region_assignments:
            return jsonify({"error": "region_assignments must be a non-empty object"}), 400
        return _build_world_from_regions(region_assignments, world_name, portrait_cache)

    # ── Preset-based builder ──────────────────────────────────────────────────
    selected_ids = data.get("factions", [])
    if not selected_ids:
        return jsonify({"error": "provide region_assignments or a non-empty factions list"}), 400

    presets_path = BASE_DIR / "faction_presets.json"
    all_presets = json.loads(presets_path.read_text(encoding="utf-8"))["presets"]
    preset_map = {p["id"]: p for p in all_presets}

    leadership_state = []
    faction_identities = {}
    faction_power_state = {}
    relationships = {}

    for fid in selected_ids:
        p = preset_map.get(fid)
        if not p:
            continue
        name = p["name"]
        ruler = dict(p["starting_ruler"])
        ruler["startDay"] = 0
        ruler["duration"] = 0
        ruler["notableEvents"] = []
        ruler["portrait_image"] = portrait_cache.get(ruler["name"], "")

        leadership_state.append({
            "faction": name,
            "currentRuler": ruler,
            "rulerHistory": [],
            "dynasties": [{"name": f"House {ruler['name'].split()[-1]}", "prestige": p["power"]}],
        })

        faction_identities[name] = {
            "race": p["race"],
            "type": p["type"],
            "description": p["description"],
            "traits": p["traits"],
            "succession": p["succession"],
        }

        faction_power_state[name] = p["power"]

        for other_id in selected_ids:
            if other_id == fid:
                continue
            other_name = preset_map[other_id]["name"] if other_id in preset_map else other_id
            if name not in relationships:
                relationships[name] = {}
            relationships[name][other_name] = {"score": 50, "status": "neutral"}

    world = {
        "tick": 0,
        "world_date": "Day 0",
        "primary_event": f"{world_name} begins. The factions take their first breath.",
        "supporting_events": [],
        "active_events": [],
        "active_tensions": [],
        "recent_events": [],
        "faction_actions": {},
        "faction_identities": faction_identities,
        "faction_power_state": faction_power_state,
        "leadership_state": leadership_state,
        "relationships": relationships,
        "house_characters": _build_fresh_house_characters(faction_identities),
        "character_updates": [],
        "faction_resources": {f["name"]: {"gold": 100, "food": 100, "troops": 50} for f in [preset_map[i] for i in selected_ids if i in preset_map]},
        "population_state": [],
        "belief_currents": [],
        "religious_factions": [],
        "weather_and_omens": [],
        "war_outcomes": [],
        "whispers": [],
        "chronicle": [],
    }

    if portrait_cache:
        world["portrait_cache"] = portrait_cache

    from world_manager import get_default_regions, assign_regions_to_factions
    faction_list = [
        {"name": p["name"], "race": p["race"], "type": p["type"]}
        for p in [preset_map[i] for i in selected_ids if i in preset_map]
    ]
    world["regions"] = assign_regions_to_factions(faction_list, get_default_regions())

    from scheduler import is_valid_world, safe_save_world
    if not world or not world.keys() or not is_valid_world(world):
        logger.error("api_build_world (preset): refusing to save — world failed validation")
        return jsonify({"error": "world validation failed"}), 500
    safe_save_world(world)
    _reset_world_files(faction_identities)
    return jsonify({"ok": True, "factions": len(leadership_state)})


@app.route("/api/worlds/custom", methods=["POST"])
def api_custom_world():
    from world_manager import _extract_portrait_cache
    data = request.get_json(force=True)
    factions_raw = data.get("factions", [])
    portrait_cache = _extract_portrait_cache()
    world = {
        "tick": 0,
        "world_date": "Day 0",
        "primary_event": "A new world is being shaped.",
        "supporting_events": [],
        "active_events": [],
        "factions": {},
        "characters": {},
    }
    if portrait_cache:
        world["portrait_cache"] = portrait_cache
    for name in factions_raw:
        name = name.strip()
        if name:
            world["factions"][name] = {"name": name, "power": 50, "relations": {}, "status": "stable"}
    from scheduler import is_valid_world, safe_save_world
    if not world or not world.keys() or not is_valid_world(world):
        logger.error("api_build_world (factions): refusing to save — world failed validation")
        return jsonify({"error": "world validation failed"}), 500
    safe_save_world(world)
    return jsonify({"ok": True, "factions": len(world["factions"])})


@app.route("/atlas-embed")
def atlas_embed():
    """Alias: same full-page embed as /map."""
    return redirect("/map", code=302)


def _map_embed_context() -> dict:
    """Next map URL with cache-buster for the iframe (Map.tsx mtime)."""
    return {
        "active_page": "map",
        "map_public_url": MAP_PUBLIC_URL,
        "map_iframe_url": _map_iframe_url(),
    }


@app.route("/map")
def map_page():
    # Full Flask page (nav + hero + iframe). The interactive map still runs inside Next.js; this is not a redirect to port 3000 alone.
    return render_template("map.html", **_map_embed_context())


@app.route("/codex")
def codex_page():
    return render_template("codex.html", active_page="codex")


@app.route("/factions")
def factions_page():
    return render_template("factions.html", active_page="factions")


@app.route("/chronicle")
def chronicle_page():
    return render_template("chronicle.html", active_page="chronicle")


@app.route("/god")
def god_page():
    return render_template("god.html", active_page="god")


@app.route("/leadership")
def leadership_page():
    return render_template("leadership.html", active_page="leadership")


@app.route("/story")
def story_page():
    """The monthly synopsis now lives in Chronicle → Current Chapter."""
    return redirect("/chronicle?section=chapter", code=302)


@app.route("/intel")
def intel_page():
    return render_template("intel.html", active_page="intel")


@app.route("/families")
def families_page():
    return render_template("families.html", active_page="families")


@app.route("/api/story")
def get_story():
    if SYNOPSIS_FILE.exists():
        return jsonify({"text": SYNOPSIS_FILE.read_text(encoding="utf-8"), "exists": True})
    return jsonify({"text": "", "exists": False})


@app.route("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "world_state_exists": WORLD_STATE_FILE.exists(),
            "history_exists": HISTORY_DIR.exists(),
            "map_public_url": MAP_PUBLIC_URL,
        }
    )


# ── World state ──────────────────────────────────────────────────────────────

@app.route("/api/state")
def get_state():
    return jsonify(_state_with_display_defaults(_read_json(WORLD_STATE_FILE, {})))


def _state_with_display_defaults(state):
    if not state.get("population_state"):
        state["population_state"] = _default_population_state()
    try:
        from scheduler import _normalize_house_characters, _normalize_leadership_state
    except Exception:
        _normalize_house_characters = None
        _normalize_leadership_state = None
    if not state.get("leadership_state"):
        try:
            from scheduler import _default_leadership_state

            state["leadership_state"] = _default_leadership_state()
        except Exception:
            state["leadership_state"] = []
    elif _normalize_leadership_state:
        _normalize_leadership_state(state, state)
    has_named_chars = any(c.get("name") for c in state.get("house_characters", []))
    if not has_named_chars and not state.get("house_characters"):
        # Completely missing — legacy world; seed from defaults for backwards compat
        try:
            from scheduler import _default_house_characters
            state["house_characters"] = _default_house_characters()
        except Exception:
            state["house_characters"] = []
    elif has_named_chars and _normalize_house_characters:
        _normalize_house_characters(state, state)
    # else: fresh game stubs present but no names yet — leave as-is
    return state


@app.route("/api/god/panel")
def get_god_panel():
    state = _state_with_display_defaults(_read_json(WORLD_STATE_FILE, {}))
    portrait_jobs = _read_json(CHARACTER_PORTRAIT_JOBS_FILE, [])
    codex_jobs = _read_json(CODEX_IMAGE_JOBS_FILE, [])
    pending = _read_json(PENDING_LORE_FILE, [])
    actions = _read_json(GOD_ACTIONS_FILE, [])
    image_state = _read_json(IMAGE_GENERATION_STATE_FILE, {})

    def summarize_jobs(jobs):
        summary = {"queued": 0, "completed": 0, "failed": 0, "other": 0}
        for job in jobs if isinstance(jobs, list) else []:
            status = (job.get("status") or "other").lower()
            if status in summary:
                summary[status] += 1
            else:
                summary["other"] += 1
        return summary

    return jsonify(
        {
            "state": state,
            "pending_interventions": pending,
            "god_actions": actions[-20:] if isinstance(actions, list) else [],
            "image_generation": {
                "daily_state": image_state,
                "portrait_jobs": summarize_jobs(portrait_jobs),
                "codex_jobs": summarize_jobs(codex_jobs),
                "recent_jobs": (portrait_jobs if isinstance(portrait_jobs, list) else [])[-5:]
                + (codex_jobs if isinstance(codex_jobs, list) else [])[-8:],
            },
        }
    )


@app.route("/api/history")
def get_history():
    if not HISTORY_DIR.exists():
        return jsonify([])
    ticks = []
    for f in sorted(HISTORY_DIR.glob("*_tick_*.json"), reverse=True):
        try:
            data = json.loads(f.read_text())
            ticks.append({
                "filename": f.name,
                "tick": data.get("tick"),
                "world_date": data.get("world_date"),
                "real_timestamp": data.get("real_timestamp"),
                "major_event": data.get("major_event", ""),
                "event_count": len(data.get("recent_events", [])),
            })
        except Exception:
            pass
    return jsonify(ticks)


@app.route("/api/history/<int:tick_number>")
def get_tick(tick_number):
    for f in HISTORY_DIR.glob("*_tick_*.json"):
        try:
            data = json.loads(f.read_text())
            if data.get("tick") == tick_number:
                return jsonify(data)
        except Exception:
            pass
    return jsonify({"error": f"Tick {tick_number} not found"}), 404


# ── Lore & tick control ──────────────────────────────────────────────────────

@app.route("/api/lore", methods=["POST"])
def post_lore():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "No text provided"}), 400
    pending = _read_json(PENDING_LORE_FILE, [])
    pending.append({"text": text, "source_file": "api", "received_at": datetime.now().isoformat()})
    _write_json(PENDING_LORE_FILE, pending)
    return jsonify({"status": "queued", "pending_count": len(pending)})


@app.route("/api/tick", methods=["POST"])
def force_tick():
    from scheduler import run_tick
    try:
        new_state = run_tick()
        return jsonify({"status": "ok", "tick": new_state.get("tick"), "world_date": new_state.get("world_date")})
    except Exception as e:
        logger.error(f"Forced tick failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/pending_lore")
def get_pending_lore():
    return jsonify(_read_json(PENDING_LORE_FILE, []))


@app.route("/api/pending_lore/set", methods=["POST"])
def set_pending_lore():
    body = request.get_json(silent=True)
    if not isinstance(body, list):
        return jsonify({"error": "Expected array"}), 400
    _write_json(PENDING_LORE_FILE, body)
    return jsonify({"status": "ok", "count": len(body)})


# ── Chronicle ────────────────────────────────────────────────────────────────

@app.route("/api/chronicle")
def get_chronicle():
    entries = []
    if not HISTORY_DIR.exists():
        return jsonify([])
    for f in sorted(HISTORY_DIR.glob("chronicle_*.txt"), reverse=True):
        try:
            tick_num = int(f.stem.split("_")[1])
            tick_file = next(HISTORY_DIR.glob(f"*_tick_{tick_num}.json"), None)
            world_date = ""
            if tick_file:
                data = json.loads(tick_file.read_text())
                world_date = data.get("world_date", "")
            mood = ""
            major_event = ""
            if tick_file:
                data = json.loads(tick_file.read_text())
                mood = data.get("mood", "")
                major_event = data.get("major_event", "")
            text = f.read_text(encoding="utf-8")
            category = _classify_chronicle_entry(text, major_event, mood)
            entries.append({
                "tick": tick_num,
                "world_date": world_date,
                "mood": mood,
                "major_event": major_event,
                "category": category,
                "excerpt": _chronicle_excerpt(text),
                "text": text,
            })
        except Exception:
            pass
    return jsonify(entries)


@app.route("/api/chronicle/<int:tick_number>")
def get_chronicle_tick(tick_number):
    f = HISTORY_DIR / f"chronicle_{tick_number}.txt"
    if not f.exists():
        return jsonify({"error": "Not found"}), 404
    return jsonify({"tick": tick_number, "text": f.read_text(encoding="utf-8")})


# ── Characters & NPC talk ────────────────────────────────────────────────────

@app.route("/api/characters")
def get_characters():
    state = _read_json(WORLD_STATE_FILE, {})
    chars = [{"name": c["name"], "faction": c["faction"], "status": c["status"]}
             for c in state.get("character_updates", [])]
    return jsonify(chars)


@app.route("/api/talk", methods=["POST"])
def talk():
    body = request.get_json(silent=True) or {}
    character = (body.get("character") or "").strip()
    message = (body.get("message") or "").strip()
    if not character or not message:
        return jsonify({"error": "character and message required"}), 400

    state = _read_json(WORLD_STATE_FILE, {})
    char_data = next((c for c in state.get("character_updates", []) if c["name"].lower() == character.lower()), None)
    world_date = state.get("world_date", "an unknown time")

    faction_info = ""
    if char_data:
        faction = char_data.get("faction", "")
        morale = next((f for f in state.get("faction_morale", []) if f["faction"] == faction), None)
        if morale:
            faction_info = f"Your faction ({faction}) is currently {morale['status'].lower()}. {morale['reason']}"

    char_status = char_data.get("status", "their whereabouts unknown") if char_data else "a figure of mystery"
    char_faction = char_data.get("faction", "no known faction") if char_data else "unknown"

    sys_prompt = f"""You are {character}, a character in the world of Aeloria. It is {world_date}.
Faction: {char_faction}. Current status: {char_status}. {faction_info}
You do not know you are in a simulation. You know only what your character would know.
Respond in character, in first person, with the voice and knowledge of your character.
Keep responses to 2-4 sentences unless asked something requiring detail.
Speak naturally — not like a narrator, like a person."""

    convo_file = CONVERSATIONS_DIR / f"{character.lower().replace(' ', '_')}.json"
    history = _read_json(convo_file, [])

    messages = [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
    messages.append({"role": "user", "content": message})

    try:
        reply = complete_chat_anthropic_format(
            system=sys_prompt,
            messages=messages,
            max_tokens=400,
            openai_continuity="Continuity: stay in character; no meta or out-of-world framing.",
        )

        history.append({"role": "user", "content": message, "timestamp": datetime.now().isoformat()})
        history.append({"role": "assistant", "content": reply, "timestamp": datetime.now().isoformat()})
        CONVERSATIONS_DIR.mkdir(exist_ok=True)
        _write_json(convo_file, history)

        return jsonify({"response": reply, "character": character})
    except Exception as e:
        logger.error(f"Talk failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/talk/make_canon", methods=["POST"])
def make_canon():
    body = request.get_json(silent=True) or {}
    character = (body.get("character") or "").strip()
    convo_file = CONVERSATIONS_DIR / f"{character.lower().replace(' ', '_')}.json"
    history = _read_json(convo_file, [])
    if not history:
        return jsonify({"error": "No conversation found"}), 404

    summary = f"A stranger spoke with {character}. " + " ".join(
        m["content"] for m in history[-6:] if m["role"] == "assistant"
    )[:400]

    pending = _read_json(PENDING_LORE_FILE, [])
    pending.append({"text": summary, "source_file": f"conversation_{character}", "received_at": datetime.now().isoformat()})
    _write_json(PENDING_LORE_FILE, pending)
    return jsonify({"status": "added to pending lore", "summary": summary})


@app.route("/api/conversations/<character>")
def get_conversation(character):
    convo_file = CONVERSATIONS_DIR / f"{character.lower().replace(' ', '_')}.json"
    return jsonify(_read_json(convo_file, []))


# ── God interventions ────────────────────────────────────────────────────────

INTERVENTION_TEMPLATES = {
    "back_faction": "A secret benefactor has begun channeling resources to {target}. Their coffers grow quietly, loyalty tightens.",
    "plant_rumor": "A whisper spreads through {target}: {detail}",
    "arrange_meeting": "In secret, agents of {target} have arranged a clandestine meeting with representatives of {detail}.",
    "curse_character": "{target} has begun suffering a string of misfortunes — illness, betrayal, and ill omens follow their steps.",
    "bless_region": "Unusual prosperity has come to {target}. Harvests are full, trade flows freely, and the people speak of divine favor.",
    "divine_omen": "Across all of Aeloria, a supernatural sign has appeared: {detail}. Factions scramble to interpret its meaning.",
    "smite": "A terrible force has destroyed {target}. The cause is unknown — some whisper divine wrath.",
    "prophecy": "A prophecy has spread through Aeloria: '{detail}'. Every faction seeks to fulfill or prevent it.",
    "raise_dead": "{target} has returned from death, changed by what they saw beyond. Their loyalties and nature are unclear.",
}


@app.route("/api/god/intervene", methods=["POST"])
def god_intervene():
    body = request.get_json(silent=True) or {}
    intervention_type = body.get("type", "")
    target = body.get("target", "")
    detail = body.get("detail", "")

    template = INTERVENTION_TEMPLATES.get(intervention_type)
    if not template:
        return jsonify({"error": "Unknown intervention type"}), 400

    lore_text = template.format(target=target, detail=detail)

    pending = _read_json(PENDING_LORE_FILE, [])
    pending.append({"text": lore_text, "source_file": f"god_{intervention_type}", "received_at": datetime.now().isoformat()})
    _write_json(PENDING_LORE_FILE, pending)

    actions = _read_json(GOD_ACTIONS_FILE, [])
    actions.append({"type": intervention_type, "target": target, "detail": detail, "lore": lore_text, "timestamp": datetime.now().isoformat()})
    _write_json(GOD_ACTIONS_FILE, actions)

    return jsonify({"status": "queued", "lore": lore_text})


@app.route("/api/god/actions")
def get_god_actions():
    return jsonify(_read_json(GOD_ACTIONS_FILE, []))


# ── Prediction ───────────────────────────────────────────────────────────────

@app.route("/api/predict", methods=["POST"])
def predict():
    body = request.get_json(silent=True) or {}
    faction_a = body.get("faction_a", "")
    faction_b = body.get("faction_b", "")
    state = _read_json(WORLD_STATE_FILE, {})

    prompt = f"""Based on the current state of Aeloria, predict what is most likely to happen in the next 3 months.
{"Focus specifically on the relationship between " + faction_a + " and " + faction_b + "." if faction_a and faction_b else "Give a general prediction for the most volatile situation."}
Current world state: {json.dumps(state, indent=2)}
Write 2-3 sentences of prediction. Be specific. Assign a probability (e.g. 70% chance of...)."""

    try:
        text = complete_chat_anthropic_format(
            system=None,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            openai_continuity="Continuity: keep the same analytical, in-world forecast tone.",
        )
        return jsonify({"prediction": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Search ────────────────────────────────────────────────────────────────────

@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip().lower()
    if not query or len(query) < 2:
        return jsonify([])

    results = []
    if HISTORY_DIR.exists():
        for f in sorted(HISTORY_DIR.glob("*_tick_*.json"), reverse=True):
            try:
                data = json.loads(f.read_text())
                text = json.dumps(data).lower()
                if query in text:
                    excerpts = []
                    for event in data.get("recent_events", []):
                        if query in event.get("text", "").lower() or query in event.get("region", "").lower():
                            excerpts.append(f"[{event['region']}] {event['text']}")
                    for char in data.get("character_updates", []):
                        if query in char.get("name", "").lower() or query in char.get("status", "").lower():
                            excerpts.append(f"{char['name']} ({char['faction']}): {char['status']}")
                    if not excerpts:
                        excerpts = [f"Mentioned in tick data"]
                    results.append({
                        "tick": data.get("tick"),
                        "world_date": data.get("world_date", ""),
                        "excerpts": excerpts[:3],
                    })
            except Exception:
                pass

        for f in HISTORY_DIR.glob("chronicle_*.txt"):
            try:
                text = f.read_text(encoding="utf-8")
                if query in text.lower():
                    tick_num = int(f.stem.split("_")[1])
                    idx = text.lower().find(query)
                    excerpt = text[max(0, idx-60):idx+120].strip()
                    if not any(r["tick"] == tick_num for r in results):
                        results.append({"tick": tick_num, "world_date": "", "excerpts": [f"...{excerpt}..."]})
            except Exception:
                pass

    return jsonify(results[:30])


# ── Audio ─────────────────────────────────────────────────────────────────────

@app.route("/api/audio/latest")
def latest_audio():
    audio_dir = BASE_DIR / "static" / "audio"
    if not audio_dir.exists():
        return jsonify({"url": None})
    files = sorted(audio_dir.glob("tick_*.mp3"), key=lambda f: int(f.stem.split("_")[1]))
    if not files:
        return jsonify({"url": None})
    latest = files[-1]
    return jsonify({"url": f"/static/audio/{latest.name}", "tick": int(latest.stem.split("_")[1])})


# Public files (Next basemap PNGs, etc.) — registered last so this catch-all cannot shadow /api/* or pages.
@app.route("/<path:filename>")
def public_assets(filename):
    public_dir = BASE_DIR / "public"
    target = public_dir / filename
    if not target.exists() or target.is_dir():
        return jsonify({"error": "Not found"}), 404
    return send_from_directory(public_dir, filename)


def _env_truthy(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


if __name__ == "__main__":
    for d in ["logs", "history", "lore", "weekly_stories", "conversations", "static/audio"]:
        (BASE_DIR / d).mkdir(parents=True, exist_ok=True)

    # Auto-reload on code changes: set FLASK_DEBUG=1 in .env (see .env.example) or `dev-flask.bat`
    # Use 0 in production. With the reloader, only the Werkzeug worker runs schedulers (not the parent watch process)
    use_flask_reloader = _env_truthy("FLASK_DEBUG", "0")
    worker_process = os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not use_flask_reloader

    from scheduler import start_scheduler, stop_scheduler
    from lore_watcher import start_watcher, stop_watcher

    if worker_process:
        start_scheduler()
        start_watcher()
        atexit.register(stop_scheduler)
        atexit.register(stop_watcher)

    port = int(os.getenv("PORT", "5000"))
    if use_flask_reloader:
        logger.info(f"Aeloria on port {port} (dev: auto-reload when FLASK_DEBUG=1)")
    else:
        logger.info(f"Aeloria starting on port {port}...")
    app.run(
        host="0.0.0.0",
        port=port,
        debug=use_flask_reloader,
        use_reloader=use_flask_reloader,
    )
