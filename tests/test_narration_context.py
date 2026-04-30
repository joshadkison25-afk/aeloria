"""Tests for narration context builders in ai.narration.

These tests cover _build_chronicle_context and _format_chronicle_prompt,
which are pure functions with no LLM calls or IO.
"""

from ai.narration import _build_chronicle_context, _format_chronicle_prompt, _format_synopsis_prompt


def _state_with_engine_outputs():
    return {
        "tick": 7,
        "world_date": "Day 7",
        "primary_event": {
            "name": "Raid For Provisions: Ironmark",
            "summary": "Ironmark forces struck Thornhaven grain stores under cover of night.",
            "severity": 12,
            "cause_id": "cause_000001",
        },
        "supporting_events": [
            {
                "name": "Stabilize Territory: Silver Coast",
                "summary": "Silver Coast shored up Saltmouth defenses.",
                "severity": 5,
            }
        ],
        "causality_ledger": [
            {
                "id": "cause_000001",
                "tick": 7,
                "domain": "economy",
                "actor": "Ironmark",
                "decision": "raid_for_provisions",
                "pressure": "food shortage",
                "outcome": "Ironmark raided Thornhaven grain stores.",
                "severity": 12,
                "confidence": 0.9,
            },
            {
                "id": "cause_000002",
                "tick": 7,
                "domain": "stability",
                "actor": "Silver Coast",
                "decision": "stabilize_territory",
                "pressure": "stability pressure: weak control in Saltmouth",
                "outcome": "Silver Coast stabilized Saltmouth.",
                "severity": 5,
                "confidence": 0.8,
            },
            {
                "id": "cause_000003",
                "tick": 6,  # previous tick — should be excluded
                "domain": "military",
                "actor": "Thornhaven",
                "decision": "defensive_posture",
                "pressure": "military pressure",
                "outcome": "Thornhaven reinforced borders.",
                "severity": 8,
                "confidence": 0.85,
            },
        ],
        "council_report": {
            "top_risks": [
                {
                    "kind": "economy",
                    "title": "Ironmark: economic pressure",
                    "summary": "food reserves low",
                    "severity": 14.0,
                    "faction": "Ironmark",
                },
                {
                    "kind": "war",
                    "title": "War: Ironmark vs Thornhaven",
                    "summary": "open conflict begun",
                    "severity": 10.0,
                    "faction": "Ironmark",
                },
            ]
        },
        "faction_beliefs": [
            {
                "faction": "Ironmark",
                "beliefs": [
                    {
                        "claim": "Thornhaven appears vulnerable to a provisioning raid",
                        "confidence": 0.72,
                        "source": "pressure",
                    }
                ],
            },
            {
                "faction": "Thornhaven",
                "beliefs": [
                    {
                        "claim": "Ironmark faces economic pressure because food reserves low",
                        "confidence": 0.65,
                        "source": "known_fact",
                    }
                ],
            },
        ],
        "active_events": [
            {
                "name": "Raid For Provisions: Ironmark",
                "summary": "Ironmark raided Thornhaven grain stores.",
                "severity": 12,
            }
        ],
    }


def test_build_chronicle_context_extracts_tick_and_date():
    ctx = _build_chronicle_context(_state_with_engine_outputs())
    assert ctx["tick"] == 7
    assert ctx["world_date"] == "Day 7"


def test_build_chronicle_context_includes_primary_event():
    ctx = _build_chronicle_context(_state_with_engine_outputs())
    assert ctx["primary_event"]["name"] == "Raid For Provisions: Ironmark"
    assert "grain stores" in ctx["primary_event"]["summary"]


def test_build_chronicle_context_filters_causes_to_current_tick():
    ctx = _build_chronicle_context(_state_with_engine_outputs())
    # tick 6 cause should be excluded
    ticks = [c["tick"] for c in ctx["tick_causes"]]
    assert all(t == 7 for t in ticks)
    assert len(ctx["tick_causes"]) == 2


def test_build_chronicle_context_sorts_causes_by_severity():
    ctx = _build_chronicle_context(_state_with_engine_outputs())
    severities = [c["severity"] for c in ctx["tick_causes"]]
    assert severities == sorted(severities, reverse=True)


def test_build_chronicle_context_includes_top_risks():
    ctx = _build_chronicle_context(_state_with_engine_outputs())
    assert len(ctx["top_risks"]) == 2
    assert ctx["top_risks"][0]["title"] == "Ironmark: economic pressure"


def test_build_chronicle_context_extracts_dominant_beliefs():
    ctx = _build_chronicle_context(_state_with_engine_outputs())
    factions = [b["faction"] for b in ctx["dominant_beliefs"]]
    assert "Ironmark" in factions
    assert "Thornhaven" in factions


def test_build_chronicle_context_empty_state_does_not_raise():
    ctx = _build_chronicle_context({"tick": 1, "world_date": "Day 1"})
    assert ctx["tick"] == 1
    assert ctx["primary_event"] == {}
    assert ctx["tick_causes"] == []
    assert ctx["top_risks"] == []


def test_format_chronicle_prompt_contains_primary_event():
    ctx = _build_chronicle_context(_state_with_engine_outputs())
    prompt = _format_chronicle_prompt(ctx)
    assert "Raid For Provisions: Ironmark" in prompt
    assert "grain stores" in prompt


def test_format_chronicle_prompt_contains_causal_record():
    ctx = _build_chronicle_context(_state_with_engine_outputs())
    prompt = _format_chronicle_prompt(ctx)
    assert "CAUSAL RECORD" in prompt
    assert "Ironmark" in prompt
    assert "food shortage" in prompt


def test_format_chronicle_prompt_contains_council_concerns():
    ctx = _build_chronicle_context(_state_with_engine_outputs())
    prompt = _format_chronicle_prompt(ctx)
    assert "COUNCIL CONCERNS" in prompt
    assert "economic pressure" in prompt


def test_format_chronicle_prompt_contains_faction_beliefs():
    ctx = _build_chronicle_context(_state_with_engine_outputs())
    prompt = _format_chronicle_prompt(ctx)
    assert "WHAT FACTIONS BELIEVE" in prompt
    assert "vulnerable to a provisioning raid" in prompt


def test_format_chronicle_prompt_does_not_dump_raw_json():
    ctx = _build_chronicle_context(_state_with_engine_outputs())
    prompt = _format_chronicle_prompt(ctx)
    # should not contain raw JSON brackets from a full state dump
    assert '"faction_power_state"' not in prompt
    assert '"causality_ledger"' not in prompt


def test_format_synopsis_prompt_uses_active_events_not_active_tensions():
    state = _state_with_engine_outputs()
    # active_tensions is the legacy field — should NOT be required
    state.pop("active_tensions", None)
    prompt = _format_synopsis_prompt(state, "")
    assert "ENGINE TOP RISKS" in prompt
    assert "ACTIVE EVENTS" in prompt
