import json
import os

import pytest

from sim_engine_sanitize import (
    sanitize_faction_power_state,
    sanitize_relationships,
    sanitize_world_state,
)


def test_sanitize_drops_str_from_faction_power():
    state: dict = {
        "faction_power_state": [
            "Twin Cities",
            {"faction": "Vilefin", "militaryPower": 30},
        ]
    }
    sanitize_faction_power_state(state)
    assert state["faction_power_state"] == [
        {"faction": "Vilefin", "militaryPower": 30}
    ]


def test_sanitize_drops_str_from_relationships():
    state: dict = {
        "relationships": [
            "broken",
            {"faction_a": "A", "faction_b": "B", "trust": 30},
        ]
    }
    sanitize_relationships(state)
    assert state["relationships"] == [
        {"faction_a": "A", "faction_b": "B", "trust": 30}
    ]


def test_sanitize_world_state_real_file_if_present():
    path = os.path.join(os.path.dirname(__file__), "..", "world_state.json")
    if not os.path.isfile(path):
        pytest.skip("world_state.json not in repo")
    with open(path, encoding="utf-8") as f:
        state = json.load(f)
    sanitize_world_state(state)
    for row in state.get("faction_power_state") or []:
        assert isinstance(row, dict)
    for r in state.get("relationships") or []:
        assert isinstance(r, dict)


def test_diplomatic_runs_on_polluted_state():
    from diplomatic_faction_decisions import run_diplomatic_faction_decisions

    state: dict = {
        "tick": 1,
        "dynastic_report": {"marriages": [], "claims": [], "potential_conflicts": []},
        "faction_power_state": ["oops", {"faction": "A", "militaryPower": 50}],
        "relationships": ["nope", {"faction_a": "A", "faction_b": "B", "type": "neutral"}],
        "locations": [],
        "treaties": [],
        "noble_marriages": [],
    }
    run_diplomatic_faction_decisions(state)
    assert isinstance(state.get("diplomatic_faction_decisions"), list)
