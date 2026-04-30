import json
import logging
import os
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from world_state.validate import ensure_world_structure, is_valid_world

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
WORLD_STATE_FILE = BASE_DIR / "world_state.json"
PENDING_LORE_FILE = BASE_DIR / "pending_lore.json"
HISTORY_DIR = BASE_DIR / "history"
PORTRAIT_JOBS_FILE = BASE_DIR / "character_portrait_jobs.json"
CODEX_IMAGE_JOBS_FILE = BASE_DIR / "codex_image_jobs.json"
IMAGE_GENERATION_STATE_FILE = BASE_DIR / "image_generation_state.json"


def load_world():
    return _load_world_state()


def save_world(state: dict) -> None:
    _save_world_state(state)


def _load_world_state():
    if WORLD_STATE_FILE.exists():
        with open(WORLD_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None


def _save_world_state(state):
    if not state or len(state.keys()) == 0:
        logger.error("_save_world_state: refusing to save - state is empty")
        return
    if not is_valid_world(state):
        logger.error("_save_world_state: refusing to save - state failed validation")
        return
    tmp = WORLD_STATE_FILE.with_name(f"world_state_{os.getpid()}_{threading.get_ident()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, WORLD_STATE_FILE)


def safe_save_world(world: dict, previous_world: dict = None) -> None:
    if not world or len(world.keys()) == 0:
        logger.error("safe_save_world: refusing to save - world is empty")
        return
    if previous_world is None and WORLD_STATE_FILE.exists():
        try:
            with open(WORLD_STATE_FILE, encoding="utf-8") as f:
                previous_world = json.load(f)
        except Exception:
            previous_world = {}
    world = ensure_world_structure(world, previous_world or {})
    if not is_valid_world(world):
        logger.error("safe_save_world: refusing to save - world failed validation")
        return
    HISTORY_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = HISTORY_DIR / f"world_{timestamp}.json"
    if WORLD_STATE_FILE.exists():
        shutil.copy2(WORLD_STATE_FILE, backup)
    tmp = WORLD_STATE_FILE.with_name(f"world_state_{os.getpid()}_{threading.get_ident()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(world, f, indent=2)
    os.replace(tmp, WORLD_STATE_FILE)
    logger.info("World state saved (backup: %s)", backup.name)


def rollback_last_save() -> None:
    if not HISTORY_DIR.exists():
        logger.warning("Rollback skipped: history directory does not exist")
        return
    backups = sorted(
        [f for f in os.listdir(HISTORY_DIR) if f.startswith("world_") and f.endswith(".json")],
    )
    if not backups:
        logger.warning("Rollback skipped: no backup files found in history/")
        return
    latest = HISTORY_DIR / backups[-1]
    shutil.copy2(latest, WORLD_STATE_FILE)
    logger.info("Rollback complete: restored world_state.json from %s", latest.name)


def _save_history(state):
    HISTORY_DIR.mkdir(exist_ok=True)
    filename = f"{datetime.now().strftime('%Y-%m-%d')}_tick_{state['tick']}.json"
    with open(HISTORY_DIR / filename, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _load_pending_lore():
    if PENDING_LORE_FILE.exists():
        with open(PENDING_LORE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def _clear_pending_lore():
    with open(PENDING_LORE_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)


def _apply_pending_lore_mechanical(state: dict, pending_lore: list) -> None:
    """Apply queued player lore after normalization without invoking an LLM."""
    if not state or not pending_lore:
        return

    seer = state.get("seer_journey")
    if not isinstance(seer, dict):
        seer = {}
        state["seer_journey"] = seer

    recent = state.get("recent_events")
    if not isinstance(recent, list):
        recent = []
        state["recent_events"] = recent

    for item in pending_lore:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue

        if text.upper().startswith("[SEER MOVEMENT]"):
            bracket = text.find("]")
            rest = text[bracket + 1 :].strip() if bracket >= 0 else text
            user_cmd = rest.split(". The Seer must", 1)[0].strip()[:500] or rest[:500]
            loc = (seer.get("current_location") or seer.get("location") or "Unknown road").strip()
            seer["location"] = loc
            seer["current_location"] = loc
            seer["destination"] = user_cmd[:240]
            seer["purpose"] = user_cmd
            seer["status"] = "traveling"
            tr = int(seer.get("ticks_remaining") or 2)
            seer["ticks_remaining"] = max(1, min(3, tr if tr else 2))
            seer["last_outcome"] = (
                "I set out under Your word-this road and this aim are mine for the turning of the day."
            )
            logger.info("Applied player Seer movement from pending_lore: %.120s", user_cmd)
            continue

        if text.upper().startswith("[DREAM SENT]"):
            recent.insert(0, {"region": "Dream", "text": text[:400], "impact": "low"})
            state["recent_events"] = recent[:15]
            continue

        recent.insert(0, {"region": "Divine whisper", "text": text[:500], "impact": "low"})
        state["recent_events"] = recent[:15]


def _slugify_filename(text):
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "character"


def _load_portrait_jobs():
    if PORTRAIT_JOBS_FILE.exists():
        try:
            with open(PORTRAIT_JOBS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            logger.warning("Could not read character portrait jobs; starting with an empty queue.")
    return []


def _save_portrait_jobs(jobs):
    with open(PORTRAIT_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)


def _load_image_generation_state():
    if IMAGE_GENERATION_STATE_FILE.exists():
        try:
            with open(IMAGE_GENERATION_STATE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            logger.warning("Could not read image generation throttle state.")
    return {}


def _save_image_generation_state(data):
    with open(IMAGE_GENERATION_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
