"""Tests for engine.memory — durable faction memory system."""

import json
from pathlib import Path

from axiom.engine.memory import (
    MAX_MEMORIES_PER_FACTION,
    MIN_WEIGHT,
    SEVERITY_THRESHOLD,
    _decay_and_prune,
    _promote_cause,
    get_faction_memories,
    memory_beliefs,
    memory_pressure_delta,
    update_faction_memories,
)
from axiom.engine.tick import run_tick


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _world(tick=5):
    return {
        "tick": tick,
        "world_date": f"Day {tick}",
        "primary_event": {},
        "supporting_events": [],
        "active_events": [],
        "recent_events": [],
        "causality_ledger": [],
        "faction_memories": [],
    }


def _cause(*, tick=5, actor="Ironmark", affected=None, domain="economy",
           decision="raid_for_provisions", outcome="Ironmark raided Thornhaven.",
           severity=12, hidden=False):
    return {
        "id": f"cause_{tick:06d}_test",
        "tick": tick,
        "domain": domain,
        "actor": actor,
        "decision": decision,
        "outcome": outcome,
        "severity": severity,
        "confidence": 0.9,
        "affected": affected or ["Ironmark", "Thornhaven"],
        "hidden_outcome": "secret" if hidden else "",
        "source": "engine",
    }


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------

def test_high_severity_cause_promotes_actor_as_own_action():
    world = _world()
    _promote_cause(world, _cause(actor="Ironmark", affected=["Ironmark", "Thornhaven"], severity=12))
    row = get_faction_memories(world, "Ironmark")
    assert any(m["memory_type"] == "own_action" for m in row["memories"])


def test_high_severity_cause_promotes_affected_as_suffered():
    world = _world()
    _promote_cause(world, _cause(actor="Ironmark", affected=["Ironmark", "Thornhaven"], severity=12))
    row = get_faction_memories(world, "Thornhaven")
    assert any(m["memory_type"] == "suffered" for m in row["memories"])


def test_low_severity_cause_is_not_promoted():
    world = _world()
    _promote_cause(world, _cause(severity=SEVERITY_THRESHOLD - 1))
    row = get_faction_memories(world, "Ironmark")
    assert row["memories"] == []


def test_hidden_cause_does_not_promote_to_affected():
    world = _world()
    _promote_cause(world, _cause(actor="Ironmark", affected=["Ironmark", "Thornhaven"],
                                  severity=14, hidden=True))
    suffered_row = get_faction_memories(world, "Thornhaven")
    assert suffered_row["memories"] == []
    own_row = get_faction_memories(world, "Ironmark")
    assert any(m["memory_type"] == "own_action" for m in own_row["memories"])


def test_intrigue_domain_is_treated_as_hidden():
    world = _world()
    _promote_cause(world, _cause(actor="Ironmark", affected=["Ironmark", "Thornhaven"],
                                  domain="intrigue", severity=14))
    suffered_row = get_faction_memories(world, "Thornhaven")
    assert suffered_row["memories"] == []


def test_duplicate_promotion_is_idempotent():
    world = _world()
    cause = _cause(severity=12)
    _promote_cause(world, cause)
    _promote_cause(world, cause)
    row = get_faction_memories(world, "Ironmark")
    ids = [m["id"] for m in row["memories"]]
    assert len(ids) == len(set(ids))


def test_memory_capped_at_max_per_faction():
    world = _world()
    for i in range(MAX_MEMORIES_PER_FACTION + 5):
        cause = _cause(severity=12)
        cause["id"] = f"cause_{i:06d}"
        _promote_cause(world, cause)
    row = get_faction_memories(world, "Ironmark")
    assert len(row["memories"]) <= MAX_MEMORIES_PER_FACTION


def test_promoted_memory_starts_at_weight_1():
    world = _world()
    _promote_cause(world, _cause(severity=12))
    row = get_faction_memories(world, "Ironmark")
    assert row["memories"][0]["weight"] == 1.0


# ---------------------------------------------------------------------------
# Decay and pruning
# ---------------------------------------------------------------------------

def test_decay_reduces_weight():
    world = _world()
    _promote_cause(world, _cause(severity=12))
    _decay_and_prune(world)
    row = get_faction_memories(world, "Ironmark")
    assert row["memories"][0]["weight"] < 1.0


def test_memories_below_min_weight_are_pruned():
    world = _world()
    _promote_cause(world, _cause(severity=12))
    row = get_faction_memories(world, "Ironmark")
    row["memories"][0]["weight"] = MIN_WEIGHT - 0.001
    _decay_and_prune(world)
    assert row["memories"] == []


def test_strong_memories_survive_many_decays():
    world = _world()
    _promote_cause(world, _cause(domain="war_attrition", severity=15))
    for _ in range(30):
        _decay_and_prune(world)
    row = get_faction_memories(world, "Ironmark")
    assert len(row["memories"]) > 0, "High-severity war memory should survive 30 ticks"


# ---------------------------------------------------------------------------
# Memory pressure delta
# ---------------------------------------------------------------------------

def test_memory_pressure_delta_returns_nonzero_for_suffered_memory():
    world = _world()
    _promote_cause(world, _cause(actor="Ironmark", affected=["Ironmark", "Thornhaven"], severity=12))
    delta = memory_pressure_delta(world, "Thornhaven")
    assert delta, "Suffered memory should produce a pressure delta"
    assert any(v > 0 for v in delta.values())


def test_memory_pressure_delta_caps_at_15():
    world = _world()
    for i in range(10):
        cause = _cause(severity=15, domain="economy")
        cause["id"] = f"cause_{i:06d}"
        _promote_cause(world, cause)
    delta = memory_pressure_delta(world, "Thornhaven")
    assert all(v <= 15.0 for v in delta.values())


def test_memory_pressure_delta_maps_war_attrition_to_military():
    world = _world()
    _promote_cause(world, _cause(actor="Ironmark", affected=["Ironmark", "Thornhaven"],
                                  domain="war_attrition", severity=14))
    delta = memory_pressure_delta(world, "Thornhaven")
    assert "military" in delta


# ---------------------------------------------------------------------------
# Memory beliefs
# ---------------------------------------------------------------------------

def test_memory_beliefs_returns_suffered_claim():
    world = _world()
    _promote_cause(world, _cause(actor="Ironmark", affected=["Ironmark", "Thornhaven"], severity=12))
    beliefs = memory_beliefs(world, "Thornhaven")
    assert any("Ironmark" in b["claim"] for b in beliefs)


def test_memory_beliefs_source_is_memory():
    world = _world()
    _promote_cause(world, _cause(actor="Ironmark", affected=["Ironmark", "Thornhaven"], severity=12))
    beliefs = memory_beliefs(world, "Thornhaven")
    assert all(b["source"] == "memory" for b in beliefs)


def test_memory_beliefs_excludes_low_weight_memories():
    world = _world()
    _promote_cause(world, _cause(actor="Ironmark", affected=["Ironmark", "Thornhaven"], severity=12))
    row = get_faction_memories(world, "Thornhaven")
    row["memories"][0]["weight"] = 0.10  # below 0.25 threshold
    beliefs = memory_beliefs(world, "Thornhaven")
    assert beliefs == []


def test_memory_beliefs_excludes_own_action_type():
    world = _world()
    _promote_cause(world, _cause(actor="Ironmark", affected=["Ironmark", "Thornhaven"], severity=12))
    beliefs = memory_beliefs(world, "Ironmark")
    assert beliefs == [], "own_action memories should not generate memory beliefs"


# ---------------------------------------------------------------------------
# update_faction_memories integration
# ---------------------------------------------------------------------------

def test_update_faction_memories_promotes_current_tick_causes():
    world = _world(tick=5)
    world["causality_ledger"] = [_cause(tick=5, severity=12)]
    update_faction_memories(world)
    row = get_faction_memories(world, "Ironmark")
    assert len(row["memories"]) > 0


def test_update_faction_memories_ignores_previous_tick_causes():
    world = _world(tick=5)
    world["causality_ledger"] = [_cause(tick=4, severity=12)]  # old tick
    update_faction_memories(world)
    row = get_faction_memories(world, "Ironmark")
    assert len(row["memories"]) == 0


# ---------------------------------------------------------------------------
# End-to-end: memory appears after run_tick
# ---------------------------------------------------------------------------

def test_run_tick_populates_faction_memories_from_fixture():
    fixture = Path(__file__).parent / "fixtures" / "minimal_world.json"
    world = json.loads(fixture.read_text(encoding="utf-8"))

    from axiom.engine.harness import _prepare
    world = _prepare(world)
    result = run_tick(world, prev_world={})

    # faction_memories container should exist after a tick
    assert "faction_memories" in result
    assert isinstance(result["faction_memories"], list)


def test_memories_accumulate_and_decay_over_10_ticks():
    fixture = Path(__file__).parent / "fixtures" / "minimal_world.json"
    world = json.loads(fixture.read_text(encoding="utf-8"))

    from axiom.engine.harness import run_ticks
    summary = run_ticks(world, 10)
    final = summary["final_world"]

    rows = final.get("faction_memories") or []
    total_memories = sum(len(r.get("memories", [])) for r in rows if isinstance(r, dict))
    assert total_memories > 0, "Expected faction memories after 10 ticks"

    weights = [
        m["weight"]
        for r in rows if isinstance(r, dict)
        for m in r.get("memories", []) if isinstance(m, dict)
    ]
    assert all(w <= 1.0 for w in weights), "All memory weights should be <= 1.0"
    assert all(w >= MIN_WEIGHT for w in weights), "All surviving memories should be >= MIN_WEIGHT"
