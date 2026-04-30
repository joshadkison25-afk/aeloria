from economic_pressure_decisions import run_economic_pressure_decisions
from diplomatic_faction_decisions import run_diplomatic_faction_decisions
from birth_system import run_birth_system
from death_system import run_death_system
from econ_trade_routes import process_economic_trade_routes
from economy_simulation import _run_resource_market
from engine._core import _process_rebellions, _update_location_control
from engine.event_surfacer import surface_events
from engine.knowledge import update_knowledge_from_causes
from intrigue_system import run_intrigue_system
from family_politics import run_family_politics
from legitimacy_system import run_legitimacy_system
from military_faction_decisions import run_military_faction_decisions
from military_simulation import run_military_after_economy_tick
from marriage_succession import run_marriage_succession_tick
from marriage_system import run_marriage_system
from treaty_system import run_treaty_system
from tributary_system import run_tributary_system


def test_economic_pressure_decisions_record_causality():
    world = {
        "tick": 12,
        "faction_power_state": [
            {"faction": "Vilefin Corsairs", "militaryPower": 44},
            {"faction": "Twin Cities", "militaryPower": 50},
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
            }
        ],
        "tick_history": [{"tick": 12}],
    }

    run_economic_pressure_decisions(world)

    records = [
        c
        for c in world.get("causality_ledger", [])
        if c.get("source") == "economic_pressure_decisions"
    ]
    assert len(records) == 1
    assert records[0]["domain"] == "economy"
    assert records[0]["actor"] == "Vilefin Corsairs"
    assert records[0]["decision"] == "raid_for_provisions"
    assert records[0]["severity"] >= 8
    assert "vulnerable to a provisioning raid" in records[0]["belief"]


def test_military_faction_decisions_record_causality():
    world = {
        "tick": 13,
        "faction_power_state": [
            {"faction": "Groth Clans", "militaryPower": 45},
            {"faction": "Gilgeth Clans", "militaryPower": 40},
        ],
        "relationships": [
            {
                "faction_a": "Groth Clans",
                "faction_b": "Gilgeth Clans",
                "type": "war",
            }
        ],
        "faction_armies": [
            {
                "faction": "Groth Clans",
                "manpower": 1000,
                "morale": 50,
                "discipline": 50,
                "supply_status": "cut",
                "supply_level": 10,
            },
            {
                "faction": "Gilgeth Clans",
                "manpower": 800,
                "morale": 50,
                "discipline": 50,
                "supply_status": "connected",
                "supply_level": 80,
            },
        ],
        "tick_history": [{"tick": 13}],
    }

    run_military_faction_decisions(world)

    records = [
        c
        for c in world.get("causality_ledger", [])
        if c.get("source") == "military_faction_decisions"
    ]
    groth_record = next(c for c in records if c.get("actor") == "Groth Clans")
    assert groth_record["domain"] == "military"
    assert groth_record["decision"] == "retreat_to_safety"
    assert groth_record["severity"] == 12
    assert "logistics_collapse" in groth_record["pressure"]


def test_rebellion_processing_records_public_causality():
    world = {
        "tick": 20,
        "faction_power_state": [
            {
                "faction": "Twin Cities",
                "militaryPower": 55,
                "economicPower": 55,
                "politicalInfluence": 55,
            }
        ],
        "locations": [
            {
                "name": "Lowmarket",
                "owner": "Twin Cities",
                "controller": "Rebels",
                "original_controller": "Twin Cities",
                "rebel_faction": "Rebels",
                "in_rebellion": True,
                "rebellion_tick_started": 10,
                "rebellion_intensity": 60,
                "control": 0,
                "stability": 12,
            }
        ],
    }

    _process_rebellions(world)

    records = [
        c
        for c in world.get("causality_ledger", [])
        if c.get("source") == "rebellion_processing"
    ]
    assert len(records) == 1
    assert records[0]["domain"] == "rebellion"
    assert records[0]["decision"] == "seize_control"
    assert "Lowmarket" in records[0]["outcome"]


def test_intrigue_resolution_records_private_causality():
    world = {
        "tick": 30,
        "faction_power_state": [
            {"faction": "Shadow Court"},
            {"faction": "Twin Cities"},
        ],
        "faction_intrigue": [
            {
                "faction": "Shadow Court",
                "intrigue_level": 60,
                "spy_networks": {
                    "Twin Cities": {"network_strength": 55, "exposure": 5}
                },
            },
            {
                "faction": "Twin Cities",
                "counter_intelligence": 35,
                "spy_networks": {},
            },
        ],
        "intrigue_pending": [
            {
                "id": "INT-test",
                "action": "information_gathering",
                "source_faction": "Shadow Court",
                "target_faction": "Twin Cities",
                "actor": "quiet agent",
                "intelligence": 70,
                "gold_paid": 20,
                "ticks_required": 1,
                "started_tick": 28,
            }
        ],
        "intrigue_config": {
            "max_new_starts_per_tick": 0,
            "start_new_probability": 0,
        },
        "tick_history": [{"tick": 30}],
    }

    run_intrigue_system(world)

    records = [
        c
        for c in world.get("causality_ledger", [])
        if c.get("source") == "intrigue_system"
    ]
    assert len(records) == 1
    assert records[0]["domain"] == "intrigue"
    assert records[0]["actor"] == "Shadow Court"
    assert records[0]["decision"] == "information_gathering"
    assert "Twin Cities" in records[0]["affected"]


def test_diplomatic_decisions_record_causality():
    world = {
        "tick": 40,
        "faction_power_state": [
            {"faction": "Twin Cities", "militaryPower": 45},
            {"faction": "Tidefall", "militaryPower": 50},
        ],
        "ruler_legitimacy_scores": {"Twin Cities": 25},
        "relationships": [
            {
                "faction_a": "Twin Cities",
                "faction_b": "Tidefall",
                "type": "neutral",
                "trust": 82,
            }
        ],
        "locations": [
            {"name": "Twin Gates", "controller": "Twin Cities", "stability": 32}
        ],
        "tick_history": [{"tick": 40}],
    }

    run_diplomatic_faction_decisions(world)

    records = [
        c
        for c in world.get("causality_ledger", [])
        if c.get("source") == "diplomatic_faction_decisions"
    ]
    twin_record = next(c for c in records if c.get("actor") == "Twin Cities")
    assert twin_record["domain"] == "diplomacy"
    assert twin_record["decision"] == "marriage_diplomacy"
    assert "Tidefall" in twin_record["affected"]
    assert "legitimacy=25.0" in twin_record["pressure"]


def test_legitimacy_crisis_records_causality(monkeypatch):
    monkeypatch.setattr("legitimacy_system.random.random", lambda: 0.0)
    world = {
        "tick": 41,
        "leadership_state": [
            {
                "faction": "Fallen Crown",
                "dynasties": [{"status": "active", "prestige": 0}],
            }
        ],
        "dynastic_legitimacy": {"Fallen Crown": 0},
        "ruler_legitimacy_scores": {"Fallen Crown": 0},
        "faction_power_state": [
            {
                "faction": "Fallen Crown",
                "militaryPower": 0,
                "economicPower": 0,
                "politicalInfluence": 0,
            }
        ],
        "faction_economy": [
            {
                "faction": "Fallen Crown",
                "shortage_effects": {
                    "grain": {"severity": 1.0},
                    "gold": {"severity": 1.0},
                    "iron": {"severity": 1.0},
                    "timber": {"severity": 1.0},
                },
            }
        ],
        "locations": [
            {"name": "Broken Keep", "controller": "Fallen Crown", "stability": 0}
        ],
        "diplomatic_standing": {"Fallen Crown": 0},
        "world_treaty_order": 0,
        "tributary_resentment": {"Fallen Crown": 100},
        "population_state": [{"faction": "Fallen Crown", "pressure": 100}],
        "tick_history": [{"tick": 41}],
    }

    run_legitimacy_system(world)

    records = [
        c
        for c in world.get("causality_ledger", [])
        if c.get("source") == "legitimacy_system"
    ]
    assert len(records) == 1
    assert records[0]["domain"] == "legitimacy"
    assert records[0]["decision"] == "military_overthrow"
    assert records[0]["actor"] == "Fallen Crown"
    assert "legitimacy crisis" in records[0]["pressure"]


def test_ruler_death_succession_records_causality():
    world = {
        "tick": 52,
        "world_date": "Day 52",
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
                "dynasties": [
                    {
                        "name": "House Aurand",
                        "status": "active",
                        "members": ["Eldaric Aurand III", "Cael Aurand"],
                    }
                ],
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
        "pending_character_deaths": [
            {"name": "Eldaric Aurand III", "cause": "event"}
        ],
        "ruler_legitimacy_scores": {"Twin Cities": 62},
        "locations": [
            {
                "name": "Eresteron",
                "controller": "Twin Cities",
                "region_type": "capital",
                "stability": 60,
                "value": 100,
            }
        ],
        "tick_history": [{"tick": 52}],
    }

    run_death_system(world)

    records = [
        c
        for c in world.get("causality_ledger", [])
        if c.get("source") == "death_system"
    ]
    assert len(records) == 1
    assert records[0]["domain"] == "succession"
    assert records[0]["actor"] == "Twin Cities"
    assert records[0]["decision"] == "resolve_succession"
    assert "Cael Aurand" in records[0]["outcome"]
    assert records[0]["severity"] >= 12
    assert world["leadership_state"][0]["currentRuler"]["name"] == "Cael Aurand"


def test_treaty_breach_records_causality_and_surfaces():
    world = {
        "tick": 60,
        "world_date": "Day 60",
        "treaties": [
            {
                "treaty_id": "T-test",
                "type": "non_aggression",
                "participants": ["Vilefin Corsairs", "Twin Cities"],
                "start_tick": 55,
                "duration": 20,
                "status": "active",
            }
        ],
        "relationships": [
            {
                "faction_a": "Vilefin Corsairs",
                "faction_b": "Twin Cities",
                "type": "neutral",
                "trust": 70,
                "hostility": 20,
            }
        ],
        "economic_pressure_decisions": [
            {
                "faction": "Vilefin Corsairs",
                "action": "raid_for_provisions",
                "meta": {"target_faction": "Twin Cities"},
            }
        ],
        "tick_history": [{"tick": 60}],
    }

    run_treaty_system(world)
    update_knowledge_from_causes(world)
    surface_events(world, {})

    records = [
        c
        for c in world.get("causality_ledger", [])
        if c.get("source") == "treaty_system"
    ]
    assert len(records) == 1
    assert records[0]["domain"] == "treaty"
    assert records[0]["actor"] == "Vilefin Corsairs"
    assert records[0]["decision"] == "break_treaty"
    assert "Twin Cities" in records[0]["affected"]
    assert world["treaties"][0]["status"] == "broken"
    assert world["faction_knowledge"]
    assert world["primary_event"]["cause_id"] == records[0]["id"]


def test_tributary_default_records_causality_and_surfaces():
    world = {
        "tick": 61,
        "world_date": "Day 61",
        "tributary_pacts": [
            {
                "tributary_id": "TRB-test",
                "dominant_faction": "Twin Cities",
                "subordinate_faction": "Vilefin Corsairs",
                "tribute_type": "gold",
                "payment_per_tick": 50,
                "start_tick": 60,
                "duration": 20,
                "status": "active",
            }
        ],
        "faction_economy": [
            {
                "faction": "Twin Cities",
                "resources": {"gold": {"stockpile": 0, "storage_capacity": 1000}},
            },
            {
                "faction": "Vilefin Corsairs",
                "resources": {"gold": {"stockpile": 0, "storage_capacity": 1000}},
            },
        ],
        "relationships": [
            {
                "faction_a": "Twin Cities",
                "faction_b": "Vilefin Corsairs",
                "type": "neutral",
                "trust": 55,
                "hostility": 25,
            }
        ],
        "tick_history": [{"tick": 61}],
    }

    run_tributary_system(world)
    update_knowledge_from_causes(world)
    surface_events(world, {})

    records = [
        c
        for c in world.get("causality_ledger", [])
        if c.get("source") == "tributary_system"
    ]
    assert len(records) == 1
    assert records[0]["domain"] == "tributary"
    assert records[0]["actor"] == "Vilefin Corsairs"
    assert records[0]["decision"] == "break_tributary_pact"
    assert "payment_default" in records[0]["pressure"]
    assert world["tributary_pacts"][0]["status"] == "broken"
    assert world["faction_knowledge"]
    assert world["primary_event"]["cause_id"] == records[0]["id"]


def test_military_logistics_attrition_records_causality_and_surfaces(monkeypatch):
    monkeypatch.setattr("military_simulation.random.random", lambda: 1.0)
    monkeypatch.setattr("military_simulation.random.uniform", lambda *_args: 0.0)
    world = {
        "tick": 62,
        "world_date": "Day 62",
        "relationships": [
            {
                "faction_a": "Groth Clans",
                "faction_b": "Twin Cities",
                "type": "war",
            }
        ],
        "locations": [
            {
                "name": "Twin Pass",
                "controller": "Twin Cities",
                "region_type": "mountain",
            }
        ],
        "faction_armies": [
            {
                "army_id": "army-groth-test",
                "faction_id": "Groth Clans",
                "manpower": 1000,
                "morale": 55,
                "discipline": 50,
                "supply_level": 20,
                "location": "Twin Pass",
                "home_region": "Groth Camp",
            }
        ],
        "faction_economy": [
            {
                "faction": "Groth Clans",
                "shortage_effects": {
                    "grain": {"severity": 0},
                    "gold": {"severity": 0},
                },
            }
        ],
        "tick_history": [{"tick": 62}],
    }

    run_military_after_economy_tick(world)
    update_knowledge_from_causes(world)
    surface_events(world, {})

    records = [
        c
        for c in world.get("causality_ledger", [])
        if c.get("source") == "military_simulation"
    ]
    assert len(records) == 1
    assert records[0]["domain"] == "war_attrition"
    assert records[0]["actor"] == "Groth Clans"
    assert records[0]["decision"] == "endure_campaign_attrition"
    assert "supply_status=cut" in records[0]["pressure"]
    assert "Twin Pass" in records[0]["affected"]
    assert world["faction_knowledge"]
    assert world["primary_event"]["cause_id"] == records[0]["id"]


def test_territory_capture_records_causality_and_surfaces(monkeypatch):
    monkeypatch.setattr("engine._core.random.randint", lambda *_args: 24)
    world = {
        "tick": 63,
        "world_date": "Day 63",
        "relationships": [
            {
                "faction_a": "Groth Clans",
                "faction_b": "Twin Cities",
                "type": "war",
            }
        ],
        "war_outcomes": [
            {
                "attacker": "Groth Clans",
                "defender": "Twin Cities",
                "advantage": 18,
                "verdict": "attacker advantage",
            }
        ],
        "locations": [
            {
                "id": "ere",
                "name": "Eresteron",
                "owner": "Twin Cities",
                "controller": "Twin Cities",
                "control": 1,
                "stability": 5,
                "value": 100,
                "region_type": "capital",
                "territory_type": "capital",
                "adjacent": [],
            }
        ],
        "tick_history": [{"tick": 63}],
    }

    _update_location_control(world)
    update_knowledge_from_causes(world)
    surface_events(world, {})

    records = [
        c
        for c in world.get("causality_ledger", [])
        if c.get("source") == "territory_control"
    ]
    assert len(records) == 1
    assert records[0]["domain"] == "territory"
    assert records[0]["actor"] == "Groth Clans"
    assert records[0]["decision"] == "capture_capital"
    assert "Eresteron" in records[0]["affected"]
    assert world["locations"][0]["controller"] == "Groth Clans"
    assert world["faction_knowledge"]
    assert world["primary_event"]["cause_id"] == records[0]["id"]


def test_political_marriage_records_dynasty_causality_and_surfaces():
    world = {
        "tick": 64,
        "world_date": "Day 64",
        "house_characters": [
            {
                "name": "Mira Aurand",
                "faction": "Twin Cities",
                "house": "House Aurand",
                "coreRole": "Heir",
                "status": "alive",
                "age": 24,
                "sex": "female",
                "influenceScore": 70,
            },
            {
                "name": "Cael Tideborn",
                "faction": "Tidefall",
                "house": "House Tideborn",
                "coreRole": "Heir",
                "status": "alive",
                "age": 26,
                "sex": "male",
                "influenceScore": 68,
            },
        ],
        "pending_marriage_pairs": [
            {
                "spouse_a": "Mira Aurand",
                "spouse_b": "Cael Tideborn",
                "type": "political",
            }
        ],
        "relationships": [
            {
                "faction_a": "Twin Cities",
                "faction_b": "Tidefall",
                "type": "neutral",
                "trust": 50,
                "hostility": 20,
                "alliance_level": 0,
            }
        ],
        "tick_history": [{"tick": 64}],
    }

    run_marriage_system(world)
    update_knowledge_from_causes(world)
    surface_events(world, {})

    records = [
        c
        for c in world.get("causality_ledger", [])
        if c.get("source") == "marriage_system"
    ]
    assert len(records) == 1
    assert records[0]["domain"] == "dynasty"
    assert records[0]["decision"] == "formalize_marriage"
    assert "Twin Cities" in records[0]["affected"]
    assert "Tidefall" in records[0]["affected"]
    assert world["character_marriages"]
    assert world["faction_knowledge"]
    assert world["primary_event"]["cause_id"] == records[0]["id"]


def test_birth_records_dynasty_causality_and_surfaces():
    world = {
        "tick": 65,
        "world_date": "Day 65",
        "birth_config": {
            "base_chance": 1.0,
            "max_birth_roll": 1.0,
            "max_births_per_tick": 1,
            "sibling_count_penalty": 0,
        },
        "character_marriages": [
            {
                "mother": "Mira Aurand",
                "father": "Cael Aurand",
                "since_tick": 60,
                "marriage_id": "M-birth-test",
            }
        ],
        "house_characters": [
            {
                "name": "Mira Aurand",
                "faction": "Twin Cities",
                "house": "House Aurand",
                "status": "alive",
                "age": 25,
                "sex": "female",
                "health": 100,
                "traits": ["diplomatic"],
            },
            {
                "name": "Cael Aurand",
                "faction": "Twin Cities",
                "house": "House Aurand",
                "status": "alive",
                "age": 27,
                "sex": "male",
                "health": 100,
                "traits": ["steady"],
            },
        ],
        "locations": [
            {"name": "Eresteron", "controller": "Twin Cities", "stability": 100}
        ],
        "tick_history": [{"tick": 65}],
    }

    run_birth_system(world)
    update_knowledge_from_causes(world)
    surface_events(world, {})

    records = [
        c
        for c in world.get("causality_ledger", [])
        if c.get("source") == "birth_system"
    ]
    assert len(records) == 1
    assert records[0]["domain"] == "dynasty"
    assert records[0]["decision"] == "record_dynastic_birth"
    assert "House Aurand" in records[0]["affected"]
    assert world["birth_events"]
    assert len(world["house_characters"]) == 3
    assert world["faction_knowledge"]
    assert world["primary_event"]["cause_id"] == records[0]["id"]


def test_dynastic_claim_records_causality_and_surfaces():
    world = {
        "tick": 66,
        "world_date": "Day 66",
        "leadership_state": [
            {
                "faction": "Twin Cities",
                "currentRuler": {
                    "name": "Eldaric Aurand III",
                    "dynasty": "House Aurand",
                },
                "dynasties": [
                    {
                        "name": "House Aurand",
                        "status": "active",
                        "prestige": 60,
                    }
                ],
            }
        ],
        "faction_power_state": [
            {
                "faction": "Twin Cities",
                "politicalInfluence": 20,
                "militaryPower": 45,
            },
            {
                "faction": "Tidefall",
                "politicalInfluence": 55,
                "militaryPower": 70,
            },
        ],
        "noble_marriages": [
            {
                "marriage_id": "M-claim-test",
                "house_a": "House Aurand",
                "house_b": "House Tideborn",
                "faction_a": "Twin Cities",
                "faction_b": "Tidefall",
                "start_tick": 40,
                "children": [
                    {
                        "name": "Lysa Aurand-Tideborn",
                        "house": "House Aurand",
                        "primary_house": "House Aurand",
                        "inherited_houses": ["House Aurand", "House Tideborn"],
                        "influenceScore": 80,
                    }
                ],
            }
        ],
        "relationships": [
            {
                "faction_a": "Twin Cities",
                "faction_b": "Tidefall",
                "type": "neutral",
                "trust": 55,
                "hostility": 18,
                "alliance_level": 10,
            }
        ],
        "tick_history": [{"tick": 66}],
    }

    run_marriage_succession_tick(world)
    update_knowledge_from_causes(world)
    surface_events(world, {})

    records = [
        c
        for c in world.get("causality_ledger", [])
        if c.get("source") == "marriage_succession"
    ]
    assert len(records) == 1
    assert records[0]["domain"] == "dynasty"
    assert records[0]["decision"] == "assert_dynastic_claim"
    assert "Lysa Aurand-Tideborn" in records[0]["affected"]
    assert "Twin Cities" in records[0]["affected"]
    assert world["dynastic_report"]["claims"]
    assert world["faction_knowledge"]
    assert world["primary_event"]["cause_id"] == records[0]["id"]


def test_no_clear_heir_records_family_politics_causality_and_surfaces():
    world = {
        "tick": 67,
        "world_date": "Day 67",
        "leadership_state": [
            {
                "faction": "Twin Cities",
                "currentRuler": {
                    "name": "Eldaric Aurand III",
                    "dynasty": "House Aurand",
                },
                "dynasties": [
                    {
                        "name": "House Aurand",
                        "status": "active",
                        "prestige": 60,
                    }
                ],
            }
        ],
        "house_characters": [
            {
                "name": "Eldaric Aurand III",
                "faction": "Twin Cities",
                "house": "House Aurand",
                "coreRole": "Leader",
                "status": "alive",
                "age": 70,
            }
        ],
        "dynastic_legitimacy": {"Twin Cities": 55},
        "dynastic_report": {"marriages": [], "claims": [], "potential_conflicts": []},
        "tick_history": [{"tick": 67}],
    }

    run_family_politics(world)
    update_knowledge_from_causes(world)
    surface_events(world, {})

    records = [
        c
        for c in world.get("causality_ledger", [])
        if c.get("source") == "family_politics"
    ]
    assert len(records) == 1
    assert records[0]["domain"] == "dynasty"
    assert records[0]["decision"] == "flag_no_clear_heir"
    assert "no_clear_heir=True" in records[0]["pressure"]
    assert "House Aurand" in records[0]["affected"]
    assert world["family_politics"]["summary"]["heir_count"] == 0
    assert world["dynastic_report"]["claims"]
    assert world["faction_knowledge"]
    assert world["primary_event"]["cause_id"] == records[0]["id"]


def test_trade_route_disruption_records_economy_causality_and_surfaces(monkeypatch):
    world = {
        "tick": 68,
        "world_date": "Day 68",
        "relationships": [],
        "faction_power_state": [
            {"faction": "Twin Cities", "militaryPower": 45},
            {"faction": "Tidefall", "militaryPower": 42},
        ],
        "faction_economy": [
            {
                "faction": "Twin Cities",
                "resources": {
                    "grain": {
                        "stockpile": 500,
                        "consumption": 10,
                        "storage_capacity": 1000,
                        "production": 20,
                    },
                    "iron": {"stockpile": 120, "consumption": 2, "storage_capacity": 1000},
                    "timber": {"stockpile": 120, "consumption": 2, "storage_capacity": 1000},
                    "gold": {"stockpile": 120, "consumption": 2, "storage_capacity": 1000},
                },
            },
            {
                "faction": "Tidefall",
                "resources": {
                    "grain": {
                        "stockpile": 10,
                        "consumption": 100,
                        "storage_capacity": 1000,
                        "production": 5,
                    },
                    "iron": {"stockpile": 120, "consumption": 2, "storage_capacity": 1000},
                    "timber": {"stockpile": 120, "consumption": 2, "storage_capacity": 1000},
                    "gold": {"stockpile": 120, "consumption": 2, "storage_capacity": 1000},
                },
            },
        ],
        "economic_trade_routes": [
            {
                "id": "land-test-route",
                "origin": "Twin Cities",
                "destination": "Tidefall",
                "kind": "land",
                "capacity": 120,
                "risk": 0.5,
                "status": "active",
                "disrupted_remaining": 0,
            }
        ],
        "tick_history": [{"tick": 68}],
    }
    monkeypatch.setattr("econ_trade_routes.random.random", lambda: 0.0)

    process_economic_trade_routes(world)
    update_knowledge_from_causes(world)
    surface_events(world, {})

    records = [
        c
        for c in world.get("causality_ledger", [])
        if c.get("source") == "econ_trade_routes"
    ]
    assert len(records) == 1
    assert records[0]["domain"] == "economy"
    assert records[0]["decision"] == "disrupt_trade_route"
    assert records[0]["actor"] == "Twin Cities"
    assert "Tidefall" in records[0]["affected"]
    assert world["economic_trade_routes"][0]["status"] == "disrupted"
    assert world["economic_route_flows"]["disrupted_count"] == 1
    assert world["faction_knowledge"]
    assert world["primary_event"]["cause_id"] == records[0]["id"]


def test_market_price_shock_records_economy_causality_and_surfaces():
    world = {
        "tick": 69,
        "world_date": "Day 69",
        "economic_disruption_price_mult": 1.25,
        "faction_economy": [
            {
                "faction_id": "Twin Cities",
                "resources": {
                    "grain": {
                        "stockpile": 8,
                        "consumption": 120,
                        "storage_capacity": 1000,
                    },
                    "iron": {"stockpile": 200, "consumption": 5, "storage_capacity": 1000},
                    "timber": {"stockpile": 200, "consumption": 5, "storage_capacity": 1000},
                    "gold": {"stockpile": 500, "consumption": 5, "storage_capacity": 1000},
                },
                "shortage_effects": {
                    "grain": {"severity": 0.7, "unmet_demand": 80},
                    "iron": {"severity": 0.0, "unmet_demand": 0},
                    "timber": {"severity": 0.0, "unmet_demand": 0},
                    "gold": {"severity": 0.0, "unmet_demand": 0},
                },
            },
            {
                "faction_id": "Tidefall",
                "resources": {
                    "grain": {
                        "stockpile": 12,
                        "consumption": 110,
                        "storage_capacity": 1000,
                    },
                    "iron": {"stockpile": 200, "consumption": 5, "storage_capacity": 1000},
                    "timber": {"stockpile": 200, "consumption": 5, "storage_capacity": 1000},
                    "gold": {"stockpile": 500, "consumption": 5, "storage_capacity": 1000},
                },
                "shortage_effects": {
                    "grain": {"severity": 0.6, "unmet_demand": 70},
                    "iron": {"severity": 0.0, "unmet_demand": 0},
                    "timber": {"severity": 0.0, "unmet_demand": 0},
                    "gold": {"severity": 0.0, "unmet_demand": 0},
                },
            },
        ],
        "tick_history": [{"tick": 69}],
    }

    _run_resource_market(world)
    update_knowledge_from_causes(world)
    surface_events(world, {})

    records = [
        c
        for c in world.get("causality_ledger", [])
        if c.get("source") == "economy_simulation"
    ]
    assert len(records) == 1
    assert records[0]["domain"] == "economy"
    assert records[0]["decision"] == "market_price_shock"
    assert "grain market shock" in records[0]["pressure"]
    assert "Twin Cities" in records[0]["affected"]
    assert "Tidefall" in records[0]["affected"]
    assert world["resource_market"]["price_spike_mult"] == 1.25
    assert world["faction_knowledge"]
    assert world["primary_event"]["cause_id"] == records[0]["id"]
