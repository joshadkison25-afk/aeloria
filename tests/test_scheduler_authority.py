import inspect

import scheduler


def test_prepare_engine_tick_state_advances_tick_and_date():
    prev = {
        "tick": 7,
        "world_date": "Day 7",
        "primary_event": {"name": "Old Event"},
        "supporting_events": [],
        "active_events": [],
        "recent_events": [],
    }

    state = scheduler._prepare_engine_tick_state(prev)

    assert state["tick"] == 8
    assert state["world_date"] == "Day 8"
    assert state["primary_event"] == {"name": "Old Event"}
    assert prev["tick"] == 7


def test_scheduler_does_not_import_ai_simulation_authority():
    source = inspect.getsource(scheduler)

    assert "ai.simulation" not in source
    assert "_call_claude" not in source
    assert "_call_openai" not in source
    assert "resolve_aeloria_llm_provider" not in source


def test_run_tick_calls_engine_with_mechanically_advanced_state(monkeypatch):
    prev = {
        "tick": 7,
        "world_date": "Day 7",
        "primary_event": {"name": "Old Event"},
        "supporting_events": [],
        "active_events": [],
        "recent_events": [],
    }
    saved_states = []
    engine_calls = []

    def fake_engine(state, prev_world=None):
        engine_calls.append((state.copy(), prev_world))
        state["primary_event"] = {
            "name": "Engine Event",
            "summary": "The engine decided truth.",
        }
        return state

    monkeypatch.setattr(scheduler, "_load_world_state", lambda: prev)
    monkeypatch.setattr(scheduler, "_load_pending_lore", lambda: [])
    monkeypatch.setattr(scheduler, "_canonicalize_world_state", lambda _prev, state: state)
    monkeypatch.setattr(scheduler, "_engine_run_tick", fake_engine)
    monkeypatch.setattr(scheduler, "_ensure_post_engine_images", lambda _state: None)
    monkeypatch.setattr(scheduler, "_apply_pending_lore_mechanical", lambda _state, _lore: None)
    monkeypatch.setattr(scheduler, "_save_world_state", lambda state: saved_states.append(state.copy()))
    monkeypatch.setattr(scheduler, "_save_history", lambda _state: None)
    monkeypatch.setattr(scheduler, "_clear_pending_lore", lambda: None)
    monkeypatch.setattr(scheduler, "send_tick_notification", lambda _state: None)
    monkeypatch.setattr(scheduler, "_generate_post_engine_chronicle", lambda _state: "flavor only")
    monkeypatch.setattr(scheduler, "_generate_post_engine_voice", lambda _text, _tick: None)
    monkeypatch.setattr(scheduler, "_generate_post_engine_synopsis", lambda _state: None)
    monkeypatch.setattr(scheduler, "get_clock_state", lambda: {})
    monkeypatch.setattr(scheduler, "mark_processing", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scheduler, "mark_tick_completed", lambda: {})
    monkeypatch.setattr(scheduler, "_broadcast", lambda _payload: None)

    result = scheduler.run_tick()

    assert engine_calls
    engine_state, engine_prev = engine_calls[0]
    assert engine_prev is prev
    assert engine_state["tick"] == 8
    assert engine_state["world_date"] == "Day 8"
    assert saved_states[0]["primary_event"]["name"] == "Engine Event"
    assert "chronicle" not in saved_states[0]
    assert saved_states[-1]["chronicle"] == "flavor only"
    assert result["tick"] == 8
