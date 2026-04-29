import atexit
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

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
MAP_PUBLIC_URL = os.getenv("MAP_PUBLIC_URL", "http://localhost:3000/worldmap")


app = Flask(__name__)

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


# ── SSE tick stream ───────────────────────────────────────────────────────────

@app.route("/api/events")
def sse_events():
    """Server-Sent Events stream — emits a JSON message after every world tick."""
    import tick_bus

    q = tick_bus.subscribe()

    def _stream():
        # Send an initial heartbeat so the browser knows the connection is alive
        yield "data: {\"type\":\"connected\"}\n\n"
        try:
            while True:
                try:
                    msg = q.get(timeout=30)          # block until tick or 30s
                    yield f"data: {msg}\n\n"
                except Exception:
                    # Heartbeat — keeps proxy/nginx from closing the connection
                    yield ": heartbeat\n\n"
        finally:
            tick_bus.unsubscribe(q)

    return Response(
        stream_with_context(_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


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

    # Auto-reload: FLASK_DEBUG=1 enables the debugger. Werkzeug's use_reloader is optional — when `npm run dev`
    # runs Flask under nodemon, set FLASK_SKIP_RELOADER=1 so only nodemon restarts the process (avoids double
    # reloaders and flaky exits on Windows). Plain `python app.py` keeps the built-in reloader when FLASK_DEBUG=1.
    flask_debug = _env_truthy("FLASK_DEBUG", "0")
    use_flask_reloader = flask_debug and not _env_truthy("FLASK_SKIP_RELOADER", "0")
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
        logger.info(f"Aeloria on port {port} (dev: Werkzeug reloader + FLASK_DEBUG=1)")
    elif flask_debug:
        logger.info(f"Aeloria on port {port} (dev: FLASK_DEBUG=1, nodemon or single process)")
    else:
        logger.info(f"Aeloria starting on port {port}...")
    app.run(
        host="0.0.0.0",
        port=port,
        debug=flask_debug,
        use_reloader=use_flask_reloader,
    )
