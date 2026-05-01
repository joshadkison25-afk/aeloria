from axiom.engine.beliefs import build_faction_beliefs, decision_bias_from_beliefs, dominant_belief, update_beliefs
from axiom.engine.knowledge import record_rumor, record_suspicion


def test_build_faction_beliefs_combines_pressure_and_knowledge():
    world = {}
    pressure = {
        "faction": "Glenwood",
        "overall": 42.0,
        "dominant_pressure": "diplomatic",
        "domains": {
            "diplomatic": {
                "score": 45.0,
                "reasons": ["hostility with Shadow Court"],
            }
        },
    }
    record_suspicion(world, "Glenwood", "Shadow Court may be funding unrest.")
    record_rumor(world, "Glenwood", "A courier vanished near Faerwood.")

    row = build_faction_beliefs(world, "Glenwood", pressure)

    assert row["faction"] == "Glenwood"
    assert row["dominant_pressure"] == "diplomatic"
    assert any(belief["source"] == "pressure" for belief in row["beliefs"])
    assert any(belief["source"] == "suspicion" for belief in row["beliefs"])
    assert all(belief["id"].startswith("belief_glenwood_") for belief in row["beliefs"])


def test_update_beliefs_uses_pressure_report():
    world = {
        "pressure_report": [
            {
                "faction": "Twin Cities",
                "overall": 22.0,
                "dominant_pressure": "economic",
                "domains": {
                    "economic": {
                        "score": 30.0,
                        "reasons": ["food below safe level"],
                    }
                },
            }
        ]
    }

    rows = update_beliefs(world)

    assert rows == world["faction_beliefs"]
    assert rows[0]["faction"] == "Twin Cities"
    assert rows[0]["beliefs"][0]["source"] == "pressure"


def test_decision_bias_from_beliefs_nudges_relevant_actions():
    world = {
        "faction_beliefs": [
            {
                "faction": "Glenwood",
                "dominant_pressure": "diplomatic",
                "overall_pressure": 44,
                "beliefs": [
                    {
                        "id": "belief_glenwood_001",
                        "claim": "Shadow Court may be funding border unrest.",
                        "confidence": 0.6,
                        "source": "suspicion",
                        "bias": "uncertain",
                    }
                ],
            }
        ]
    }

    bias = decision_bias_from_beliefs(world, "Glenwood")

    assert bias["form_alliance"] == 5.0
    assert bias["declare_war"] == 3.0
    assert bias["betray"] == 1.8
    assert dominant_belief(world, "Glenwood")["id"] == "belief_glenwood_001"
