from pathlib import Path

from economic_pressure_decisions import run_economic_pressure_decisions
from death_system import run_death_system
from axiom.engine.autopsy import build_tick_autopsy
from axiom.engine.beliefs import update_beliefs
from axiom.engine.causality import get_tick_causes
from axiom.engine.event_surfacer import surface_events
from axiom.engine.knowledge import update_knowledge_from_causes
from axiom.engine.pressure import compute_pressure_report
from axiom.engine.tick import run_tick


def _food_shortage_world():
    return {
        "tick": 50,
        "world_date": "Day 50",
        "primary_event": {},
        "supporting_events": [],
        "active_events": [],
        "recent_events": [],
        "faction_power_state": [
            {
                "faction": "Vilefin Corsairs",
                "militaryPower": 58,
                "economicPower": 42,
                "politicalInfluence": 48,
            },
            {
                "faction": "Twin Cities",
                "militaryPower": 35,
                "economicPower": 38,
                "politicalInfluence": 45,
            },
        ],
        "faction_economy": [
            {
                "faction": "Vilefin Corsairs",
                "resources": {"grain": {"consumption": 100}},
                "shortage_effects": {
                    "grain": {"severity": 0.8},
                    "iron": {"severity": 0.0},
                    "timber": {"severity": 0.0},
                    "gold": {"severity": 0.0},
                },
            },
            {
                "faction": "Twin Cities",
                "resources": {"grain": {"consumption": 80}},
                "shortage_effects": {
                    "grain": {"severity": 0.0},
                    "iron": {"severity": 0.0},
                    "timber": {"severity": 0.0},
                    "gold": {"severity": 0.0},
                },
            },
        ],
        "relationships": [
            {
                "faction_a": "Vilefin Corsairs",
                "faction_b": "Twin Cities",
                "type": "neutral",
                "hostility": 45,
                "trust": 35,
            }
        ],
        "tick_history": [{"tick": 50}],
    }


def test_last_tick_autopsy_exists_after_run_tick():
    world = {
        "tick": 2,
        "world_date": "Day 2",
        "primary_event": {},
        "supporting_events": [],
        "active_events": [],
        "recent_events": [],
        "faction_power_state": [],
        "faction_economy": [],
        "relationships": [],
        "tick_history": [{"tick": 2}],
    }

    result = run_tick(world, prev_world={})

    autopsy = result.get("last_tick_autopsy")
    assert autopsy
    assert autopsy["tick"] == 2
    assert set(autopsy) >= {
        "pressures",
        "beliefs",
        "decisions",
        "outcomes",
        "causality_records",
        "knowledge_updates",
        "relationship_changes",
        "memory_changes",
        "surfaced_events",
    }


def test_tick_autopsy_reports_character_relationship_and_memory_changes():
    prev_world = {
        "tick": 80,
        "world_date": "Day 80",
        "house_characters": [
            {
                "name": "Mira Aurand",
                "faction": "Twin Cities",
                "house": "House Aurand",
                "relationships": {
                    "Lord Tideborn": {"trust": 45, "fear": 20, "respect": 40}
                },
                "memory": [],
            }
        ],
    }
    world = {
        "tick": 81,
        "world_date": "Day 81",
        "house_characters": [
            {
                "name": "Mira Aurand",
                "faction": "Twin Cities",
                "house": "House Aurand",
                "relationships": {
                    "Lord Tideborn": {"trust": 33, "fear": 24, "respect": 37}
                },
                "memory": [
                    {
                        "type": "betrayal",
                        "target": "Lord Tideborn",
                        "impact": -24,
                        "tick": 81,
                        "description": "Mira Aurand begins weaving a quiet plot against Lord Tideborn",
                    }
                ],
            }
        ],
    }

    autopsy = build_tick_autopsy(world, prev_world=prev_world)

    relationship = autopsy["relationship_changes"][0]
    assert relationship["character"] == "Mira Aurand"
    assert relationship["target"] == "Lord Tideborn"
    assert relationship["changes"]["trust"]["delta"] == -12
    assert relationship["changes"]["fear"]["delta"] == 4
    assert relationship["changes"]["respect"]["delta"] == -3

    memory = autopsy["memory_changes"][0]
    assert memory["character"] == "Mira Aurand"
    assert memory["type"] == "betrayal"
    assert memory["target"] == "Lord Tideborn"
    assert memory["new"] is True
    assert memory["impact"] == -24


def test_food_shortage_raid_vertical_slice_records_knowledge_and_surface():
    world = _food_shortage_world()

    world["pressure_report"] = compute_pressure_report(world)
    update_beliefs(world)
    run_economic_pressure_decisions(world)
    knowledge_updates = update_knowledge_from_causes(world)
    surface_events(world)
    autopsy = build_tick_autopsy(world, knowledge_updates=knowledge_updates)

    beliefs = next(row for row in world["faction_beliefs"] if row["faction"] == "Vilefin Corsairs")
    assert any(
        belief["subject"] == "Twin Cities"
        and "vulnerable to a provisioning raid" in belief["claim"]
        for belief in beliefs["beliefs"]
    )

    decision = next(row for row in world["economic_pressure_decisions"] if row["faction"] == "Vilefin Corsairs")
    assert decision["action"] == "raid_for_provisions"
    assert decision["meta"]["target_faction"] == "Twin Cities"

    records = get_tick_causes(world, tick=50)
    raid_record = next(record for record in records if record["decision"] == "raid_for_provisions")
    assert raid_record["domain"] == "economy"
    assert raid_record["actor"] == "Vilefin Corsairs"
    assert "food shortage" in raid_record["pressure"]
    assert "vulnerable to a provisioning raid" in raid_record["belief"]

    twin_knowledge = next(row for row in world["faction_knowledge"] if row["faction"] == "Twin Cities")
    assert any(raid_record["id"] in item for item in twin_knowledge["rumors"])

    assert world["primary_event"]["cause_id"] == raid_record["id"]
    assert any(row.get("cause_id") == raid_record["id"] for row in autopsy["surfaced_events"])
    assert any(row.get("cause_id") == raid_record["id"] for row in autopsy["knowledge_updates"])


def test_engine_and_scheduler_do_not_import_ai_simulation_authority():
    root = Path(__file__).resolve().parents[1]
    scheduler_source = (root / "scheduler.py").read_text(encoding="utf-8")
    engine_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (root / "engine").glob("*.py")
    )

    assert "ai.simulation" not in scheduler_source
    assert "_call_claude" not in scheduler_source
    assert "_call_openai" not in scheduler_source
    assert "from ai" not in engine_sources
    assert "import ai" not in engine_sources


def test_axiom_last_tick_endpoint_returns_autopsy(monkeypatch):
    import app as flask_app_module

    monkeypatch.setattr(
        flask_app_module,
        "_read_json",
        lambda _path, _default: {
            "last_tick_autopsy": {"tick": 77, "world_date": "Day 77"},
            "causality_ledger": [{"id": "cause_000077", "tick": 77}],
        },
    )

    client = flask_app_module.app.test_client()
    response = client.get("/api/axiom/last-tick")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["last_tick_autopsy"]["tick"] == 77
    assert payload["recent_causality_records"][0]["id"] == "cause_000077"


def test_ruler_death_succession_reaches_knowledge_surfacing_and_autopsy():
    world = {
        "tick": 61,
        "world_date": "Day 61",
        "primary_event": {},
        "supporting_events": [],
        "active_events": [],
        "recent_events": [],
        "leadership_state": [
            {
                "faction": "Twin Cities",
                "currentRuler": {
                    "name": "Eldaric Aurand III",
                    "title": "High King",
                    "dynasty": "House Aurand",
                    "startDay": 1,
                    "traits": ["tradition-bound"],
                },
                "rulerHistory": [],
                "dynasties": [{"name": "House Aurand", "status": "active", "members": []}],
            }
        ],
        "house_characters": [
            {
                "name": "Eldaric Aurand III",
                "faction": "Twin Cities",
                "house": "House Aurand",
                "coreRole": "Leader",
                "status": "alive",
                "age": 80,
                "race": "Human",
                "health": 80,
                "influenceScore": 90,
            },
            {
                "name": "Cael Aurand",
                "faction": "Twin Cities",
                "house": "House Aurand",
                "coreRole": "Heir",
                "status": "alive",
                "age": 34,
                "race": "Human",
                "health": 90,
                "influenceScore": 85,
                "parents": ["Eldaric Aurand III"],
            },
        ],
        "pending_character_deaths": [{"name": "Eldaric Aurand III", "cause": "event"}],
        "ruler_legitimacy_scores": {"Twin Cities": 62},
        "locations": [{"name": "Eresteron", "controller": "Twin Cities", "region_type": "capital", "stability": 60, "value": 100}],
        "tick_history": [{"tick": 61}],
    }

    run_death_system(world)
    knowledge_updates = update_knowledge_from_causes(world)
    surface_events(world)
    autopsy = build_tick_autopsy(world, knowledge_updates=knowledge_updates)

    record = next(c for c in get_tick_causes(world, tick=61) if c["domain"] == "succession")
    assert world["primary_event"]["cause_id"] == record["id"]
    assert "Cael Aurand" in world["primary_event"]["summary"]

    knowledge = next(row for row in world["faction_knowledge"] if row["faction"] == "Twin Cities")
    assert any(record["id"] in item for item in knowledge["known_facts"])

    assert any(row["cause_id"] == record["id"] for row in autopsy["outcomes"])
    assert any(row["cause_id"] == record["id"] for row in autopsy["knowledge_updates"])
    assert any(row.get("cause_id") == record["id"] for row in autopsy["surfaced_events"])
