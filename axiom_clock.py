import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

from axiom.world_state.io import BASE_DIR, _load_world_state

logger = logging.getLogger(__name__)

CLOCK_STATE_FILE = BASE_DIR / "clock_state.json"

SPEED_INTERVALS_SECONDS = {
    1: 300,
    2: 120,
    3: 45,
    4: 15,
    5: 5,
}

_lock = Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _world_clock_fields() -> dict:
    world = _load_world_state()
    if not isinstance(world, dict):
        return {"current_tick": 0, "world_date": ""}
    return {
        "current_tick": int(world.get("tick", 0) or 0),
        "world_date": str(world.get("world_date", "") or ""),
    }


def _default_state() -> dict:
    now = _now()
    return {
        "paused": True,
        "speed": 3,
        "next_tick_eta": _iso(now + timedelta(seconds=SPEED_INTERVALS_SECONDS[3])),
        "is_processing": False,
        "last_error": "",
        **_world_clock_fields(),
    }


def _read_state_unlocked() -> dict:
    if CLOCK_STATE_FILE.exists():
        try:
            data = json.loads(CLOCK_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                state = {**_default_state(), **data}
                state["speed"] = max(1, min(5, int(state.get("speed", 3) or 3)))
                state["paused"] = bool(state.get("paused", True))
                state["is_processing"] = bool(state.get("is_processing", False))
                return {**state, **_world_clock_fields()}
        except Exception as exc:
            logger.warning("Could not read Axiom clock state: %s", exc)
    return _default_state()


def _write_state_unlocked(state: dict) -> dict:
    state = {**state, **_world_clock_fields()}
    tmp = CLOCK_STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(CLOCK_STATE_FILE)
    return state


def get_clock_state() -> dict:
    with _lock:
        state = _read_state_unlocked()
        return _with_countdown(state)


def _with_countdown(state: dict) -> dict:
    eta = _parse_iso(state.get("next_tick_eta"))
    if eta:
        state["seconds_until_next_tick"] = max(0, int((eta - _now()).total_seconds()))
    else:
        state["seconds_until_next_tick"] = None
    return state


def _schedule_next_unlocked(state: dict, from_now: bool = True) -> dict:
    speed = max(1, min(5, int(state.get("speed", 3) or 3)))
    base = _now() if from_now else (_parse_iso(state.get("next_tick_eta")) or _now())
    state["next_tick_eta"] = _iso(base + timedelta(seconds=SPEED_INTERVALS_SECONDS[speed]))
    return state


def pause_clock() -> dict:
    with _lock:
        state = _read_state_unlocked()
        state["paused"] = True
        return _with_countdown(_write_state_unlocked(state))


def resume_clock() -> dict:
    with _lock:
        state = _read_state_unlocked()
        state["paused"] = False
        _schedule_next_unlocked(state, from_now=True)
        return _with_countdown(_write_state_unlocked(state))


def set_clock_speed(speed: int) -> dict:
    with _lock:
        state = _read_state_unlocked()
        state["speed"] = max(1, min(5, int(speed or 3)))
        _schedule_next_unlocked(state, from_now=True)
        return _with_countdown(_write_state_unlocked(state))


def mark_processing(is_processing: bool, error: str = "") -> dict:
    with _lock:
        state = _read_state_unlocked()
        state["is_processing"] = bool(is_processing)
        if error:
            state["last_error"] = error
        elif is_processing:
            state["last_error"] = ""
        return _with_countdown(_write_state_unlocked(state))


def mark_tick_completed() -> dict:
    with _lock:
        state = _read_state_unlocked()
        state["is_processing"] = False
        state["last_error"] = ""
        _schedule_next_unlocked(state, from_now=True)
        return _with_countdown(_write_state_unlocked(state))


def is_tick_due() -> bool:
    with _lock:
        state = _read_state_unlocked()
        if state.get("paused") or state.get("is_processing"):
            return False
        eta = _parse_iso(state.get("next_tick_eta"))
        return eta is None or _now() >= eta
