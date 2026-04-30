from engine.knowledge import record_rumor, record_suspicion
from engine.pressure import compute_faction_pressure, compute_pressure_report, pressure_summary


def test_compute_faction_pressure_detects_material_and_war_stress():
    world = {
        "faction_power_state": [
            {
                "faction": "Groth Clans",
                "militaryPower": 38,
                "economicPower": 32,
                "politicalInfluence": 44,
            }
        ],
        "faction_resources": [{"faction": "Groth Clans", "food": 25, "materials": 60}],
        "relationships": [
            {
                "faction_a": "Groth Clans",
                "faction_b": "Gilgeth Clans",
                "type": "war",
                "hostility": 82,
            }
        ],
        "locations": [
            {"name": "Groth", "controller": "Groth Clans", "stability": 34, "control": 41}
        ],
    }

    report = compute_faction_pressure(world, "Groth Clans")

    assert report["faction"] == "Groth Clans"
    assert report["domains"]["economic"]["score"] > 0
    assert report["domains"]["military"]["score"] > 0
    assert report["domains"]["stability"]["score"] > 0
    assert report["dominant_pressure"] in report["domains"]
    assert "pressure" in pressure_summary(report)


def test_compute_faction_pressure_uses_knowledge_pressure():
    world = {}
    record_rumor(world, "Tidefall", "A fleet has vanished.")
    record_suspicion(world, "Tidefall", "The Shadow Court interfered.")

    report = compute_faction_pressure(world, "Tidefall")

    assert report["domains"]["knowledge"]["score"] == 15.0
    assert "active suspicions" in report["domains"]["knowledge"]["reasons"]


def test_compute_pressure_report_sorts_by_overall_pressure():
    world = {
        "faction_power_state": [
            {"faction": "Stable Realm", "militaryPower": 80, "economicPower": 80, "politicalInfluence": 80},
            {"faction": "Hungry Realm", "militaryPower": 40, "economicPower": 25, "politicalInfluence": 35},
        ],
        "faction_resources": [
            {"faction": "Hungry Realm", "food": 10, "materials": 30},
            {"faction": "Stable Realm", "food": 90, "materials": 90},
        ],
    }

    report = compute_pressure_report(world)

    assert report[0]["faction"] == "Hungry Realm"

