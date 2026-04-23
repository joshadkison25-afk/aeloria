import atexit
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory

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

app = Flask(__name__)


def _read_json(path, default):
    if Path(path).exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _default_population_state():
    return [
        {"region": "Twin Cities", "species": "Humans", "culture": "Twin Cities", "population": 160000, "growthRate": 0.00025, "capacity": 180000, "health": 86, "pressure": 22, "activeMilitary": 5600, "navalAllocation": 3, "notes": "Centralized human capital with strong defenses and slower adaptation."},
        {"region": "Tidefall", "species": "Humans", "culture": "Tidefall", "population": 160000, "growthRate": 0.00028, "capacity": 185000, "health": 82, "pressure": 32, "activeMilitary": 6400, "navalAllocation": 20, "notes": "Naval power with a large harbor population, fleet personnel, and higher infiltration risk."},
        {"region": "Faerwood", "species": "Dread Elves", "culture": "Shadow Court", "population": 30000, "growthRate": 0.00003, "capacity": 42000, "health": 74, "pressure": 38, "activeMilitary": 1050, "navalAllocation": 0, "notes": "Low-growth cursed forest society with high individual power."},
        {"region": "Glenhaven", "species": "Glenhaven Elves", "culture": "Wildwood Elves", "population": 35000, "growthRate": 0.00005, "capacity": 52000, "health": 88, "pressure": 18, "activeMilitary": 1225, "navalAllocation": 0, "notes": "Stable, harmony-focused forest population."},
        {"region": "Lostfeld", "species": "Dwarves", "culture": "Lostfeld Clans", "population": 65000, "growthRate": 0.00008, "capacity": 85000, "health": 81, "pressure": 24, "activeMilitary": 2275, "navalAllocation": 0, "notes": "Structured clan society with rare betrayal and strong lineage."},
        {"region": "Gilgeth and Groth", "species": "Orcs", "culture": "Mountain Orcs", "population": 100000, "growthRate": 0.00022, "capacity": 125000, "health": 72, "pressure": 43, "activeMilitary": 4000, "navalAllocation": 0, "notes": "Connected mountain populations split between council stability and chieftain aggression."},
        {"region": "Rock Plains", "species": "Goblins", "culture": "Vilefin", "population": 215000, "growthRate": 0.00055, "capacity": 230000, "health": 63, "pressure": 68, "activeMilitary": 8600, "navalAllocation": 0, "notes": "High-growth goblin population near capacity pressure."},
        {"region": "Dreadwind Isles", "species": "Humans", "culture": "Dreadwind Pirates", "population": 45000, "growthRate": 0.00018, "capacity": 65000, "health": 67, "pressure": 52, "activeMilitary": 1800, "navalAllocation": 16, "notes": "Mobile exile population where betrayal and leadership challenges are normalized."},
        {"region": "Dur Khadur", "species": "Humans", "culture": "Dur Khadur", "population": 115000, "growthRate": 0.00024, "capacity": 155000, "health": 79, "pressure": 36, "activeMilitary": 4025, "navalAllocation": 8, "notes": "Trade-driven population with transactional loyalties."},
        {"region": "Stonebreak", "species": "Druids", "culture": "Monastery of Druids", "population": 5500, "growthRate": 0.00002, "capacity": 9000, "health": 91, "pressure": 12, "activeMilitary": 275, "navalAllocation": 0, "notes": "Low population, high influence, guided by balance rather than conventional state power."},
        {"region": "Gloomspire", "species": "Gnomes", "culture": "Gloomspire Syndicate", "population": 8500, "growthRate": 0.00012, "capacity": 14000, "health": 76, "pressure": 28, "activeMilitary": 340, "navalAllocation": 0, "notes": "Covert influence population tied to pass control and intelligence trade."},
        {"region": "Dragonscar Peaks", "species": "Ice Dragons", "culture": "Dragon Clans", "population": 12, "growthRate": 0, "capacity": 20, "health": 94, "pressure": 9, "activeMilitary": 12, "navalAllocation": 0, "notes": "Not a normal population faction; every dragon is region-level power."},
    ]


# ── Core pages ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("home.html", active_page="home")


@app.route("/map")
def map_page():
    return redirect(MAP_PUBLIC_URL, code=302)


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


@app.route("/story")
def story_page():
    return render_template("story.html", active_page="story")


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
    if not state.get("house_characters"):
        try:
            from scheduler import _default_house_characters

            state["house_characters"] = _default_house_characters()
        except Exception:
            state["house_characters"] = []
    elif _normalize_house_characters:
        _normalize_house_characters(state, state)
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
            entries.append({
                "tick": tick_num,
                "world_date": world_date,
                "mood": mood,
                "major_event": major_event,
                "text": f.read_text(encoding="utf-8"),
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
        from anthropic import Anthropic
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model=os.getenv("API_MODEL", "claude-sonnet-4-6"),
            max_tokens=400,
            system=sys_prompt,
            messages=messages
        )
        reply = response.content[0].text

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
        from anthropic import Anthropic
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model=os.getenv("API_MODEL", "claude-sonnet-4-6"),
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        return jsonify({"prediction": response.content[0].text})
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


if __name__ == "__main__":
    for d in ["logs", "history", "lore", "weekly_stories", "conversations", "static/audio"]:
        (BASE_DIR / d).mkdir(parents=True, exist_ok=True)

    from scheduler import start_scheduler, stop_scheduler
    from lore_watcher import start_watcher, stop_watcher

    start_scheduler()
    start_watcher()

    atexit.register(stop_scheduler)
    atexit.register(stop_watcher)

    port = int(os.getenv("PORT", "5000"))
    logger.info(f"Aeloria starting on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
