import copy
import logging
import os
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from axiom_clock import (
    get_clock_state,
    is_tick_due,
    mark_processing,
    mark_tick_completed,
    pause_clock,
    resume_clock,
)
from audio_pipeline import generate_weekly_story
from engine.tick import run_tick as _engine_run_tick
from notifier import send_tick_notification
from world_state.io import (
    WORLD_STATE_FILE,
    _apply_pending_lore_mechanical,
    _clear_pending_lore,
    _load_pending_lore,
    _load_world_state,
    _save_history,
    _save_world_state,
    rollback_last_save,
    safe_save_world,
)
from world_state.validate import _canonicalize_world_state, ensure_world_structure, is_valid_world

logger = logging.getLogger(__name__)

TEST_MODE = os.getenv("AXIOM_TEST_MODE", "0").strip().lower() in ("1", "true", "yes", "on")
_scheduler = BackgroundScheduler(timezone="UTC")
_lock = threading.Lock()


def _broadcast(payload: dict) -> None:
    try:
        import tick_bus

        tick_bus.notify_tick(payload)
    except Exception as bus_err:
        logger.warning("tick_bus notify failed: %s", bus_err)


def _prepare_engine_tick_state(prev_state: dict | None) -> dict:
    state = copy.deepcopy(prev_state) if isinstance(prev_state, dict) else {}
    prev_tick = int(state.get("tick", 0) or 0)
    next_tick = prev_tick + 1

    state["tick"] = next_tick
    state["world_date"] = f"Day {next_tick}"
    state.setdefault(
        "primary_event",
        {
            "name": "The World Turns",
            "summary": "Aeloria advances under deterministic simulation.",
            "severity": 1,
            "stage": "ongoing",
            "trend": "stable",
            "involved": [],
        },
    )
    state.setdefault("supporting_events", [])
    state.setdefault("active_events", [])
    state.setdefault("recent_events", [])
    return state


def _ensure_post_engine_images(state: dict) -> None:
    from ai.images import _ensure_character_portraits, _ensure_codex_images

    _ensure_character_portraits(state)
    _ensure_codex_images(state)


def _generate_post_engine_chronicle(state: dict) -> str:
    from ai.narration import _generate_chronicle

    return _generate_chronicle(state)


def _generate_post_engine_voice(chronicle: str, tick: int) -> None:
    from ai.narration import _generate_tick_voice

    _generate_tick_voice(chronicle, tick)


def _generate_post_engine_synopsis(state: dict) -> str:
    from ai.narration import _generate_narrative_synopsis

    return _generate_narrative_synopsis(state)


def run_tick():
    """Scheduler-level tick: load, deterministic Axiom Engine, save, narrate."""
    if not _lock.acquire(blocking=False):
        raise RuntimeError("Axiom tick already in progress")
    mark_processing(True)
    _broadcast({"type": "tick_started", "clock": get_clock_state()})
    try:
        logger.info("Running world tick...")
        try:
            prev_state = _load_world_state()
            if not isinstance(prev_state, dict):
                logger.warning(
                    "run_tick: world_state.json was not an object (%s); using empty state fallback",
                    type(prev_state).__name__,
                )
                prev_state = {}
            pending_lore = _load_pending_lore()
            pending_lore_snapshot = list(pending_lore) if pending_lore else []

            new_state = _prepare_engine_tick_state(prev_state)
            new_state = _canonicalize_world_state(prev_state, new_state)
            new_state = _engine_run_tick(new_state, prev_world=prev_state)
            new_state = _canonicalize_world_state(prev_state, new_state)
            if os.getenv("PAUSE_IMAGE_GEN", "0").strip().lower() not in ("1", "true", "yes"):
                _ensure_post_engine_images(new_state)
            new_state = _canonicalize_world_state(prev_state, new_state)
            _apply_pending_lore_mechanical(new_state, pending_lore)
            _save_world_state(new_state)
            _save_history(new_state)
            _clear_pending_lore()

            send_tick_notification(new_state)
            logger.info("Tick %s complete - %s", new_state["tick"], new_state.get("world_date"))

            clock = mark_tick_completed()
            _broadcast(
                {
                    "type": "tick_completed",
                    "tick": new_state.get("tick"),
                    "world_date": new_state.get("world_date"),
                    "clock": clock,
                }
            )
            _broadcast(
                {
                    "type": "tick",
                    "tick": new_state.get("tick"),
                    "world_date": new_state.get("world_date"),
                    "clock": clock,
                }
            )

            chronicle = _generate_post_engine_chronicle(new_state)
            if chronicle:
                new_state["chronicle"] = chronicle
                new_state = _canonicalize_world_state(prev_state, new_state)
                _apply_pending_lore_mechanical(new_state, pending_lore_snapshot)
                _save_world_state(new_state)

            _generate_post_engine_voice(chronicle, new_state["tick"])
            _generate_post_engine_synopsis(new_state)
            return new_state
        except Exception as exc:
            mark_processing(False, str(exc))
            _broadcast({"type": "tick_failed", "error": str(exc), "clock": get_clock_state()})
            logger.error("Tick failed: %s", exc, exc_info=True)
            raise
    finally:
        _lock.release()


def _run_clock_loop():
    clock = get_clock_state()
    _broadcast({"type": "clock", "clock": clock})
    if not is_tick_due():
        return
    try:
        run_tick()
    except RuntimeError as exc:
        logger.info("Clock tick skipped: %s", exc)
    except Exception as exc:
        logger.error("Clock tick failed: %s", exc, exc_info=True)


def _run_monday_story():
    logger.info("Generating Monday audio story...")
    try:
        state = _load_world_state()
        if state:
            path = generate_weekly_story(state)
            logger.info("Monday story saved to %s", path)
        else:
            logger.warning("No world state yet - skipping Monday story.")
    except Exception as exc:
        logger.error("Monday story failed: %s", exc, exc_info=True)


def start_scheduler():
    _scheduler.add_job(_run_clock_loop, IntervalTrigger(seconds=1), id="axiom_clock", replace_existing=True)
    _scheduler.add_job(
        _run_monday_story,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="UTC"),
        id="monday_story",
        replace_existing=True,
    )
    if _scheduler.get_job("simulation_tick"):
        _scheduler.remove_job("simulation_tick")
    if _scheduler.get_job("world_tick"):
        _scheduler.remove_job("world_tick")
    logger.info("Axiom grand-strategy clock enabled: speed controls drive run_tick().")
    if not TEST_MODE:
        _scheduler.start()
        logger.info("Scheduler started - Axiom clock heartbeat every 1s, story every Monday 9am UTC.")
    else:
        logger.info("TEST_MODE=True - scheduler disabled, no background ticks.")

    if not WORLD_STATE_FILE.exists():
        logger.info("No world state found - generating initial state...")
        try:
            run_tick()
        except Exception as exc:
            logger.error("Initial world generation failed: %s", exc, exc_info=True)


def stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")


def pause_ticks() -> None:
    pause_clock()
    _broadcast({"type": "clock", "clock": get_clock_state()})
    logger.info("Axiom clock paused.")


def resume_ticks() -> None:
    resume_clock()
    _broadcast({"type": "clock", "clock": get_clock_state()})
    logger.info("Axiom clock resumed.")
