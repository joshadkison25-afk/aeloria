from engine.intel import build_faction_intel, build_intel_report
from engine.knowledge import record_rumor, record_suspicion


def test_build_faction_intel_combines_pressure_belief_and_knowledge():
    world = {
        "tick": 15,
        "faction_power_state": [
            {
                "faction": "Twin Cities",
                "militaryPower": 42,
                "economicPower": 35,
                "politicalInfluence": 33,
            }
        ],
        "relationships": [
            {
                "faction_a": "Twin Cities",
                "faction_b": "Groth Clans",
                "type": "war",
                "hostility": 80,
            }
        ],
    }
    record_rumor(world, "Twin Cities", "Groth envoys are buying grain.")
    record_suspicion(world, "Twin Cities", "Shadow Court funded the raids.")

    intel = build_faction_intel(world, "Twin Cities")

    assert intel["faction"] == "Twin Cities"
    assert intel["overall_pressure"] > 0
    assert intel["knowledge_counts"]["rumors"] == 1
    assert intel["knowledge_counts"]["suspicions"] == 1
    assert intel["beliefs"]
    assert intel["pressure_domains"][0]["score"] >= intel["pressure_domains"][-1]["score"]


def test_build_intel_report_sorts_factions_by_pressure():
    world = {
        "tick": 16,
        "faction_power_state": [
            {"faction": "Stable Realm", "militaryPower": 80, "economicPower": 80, "politicalInfluence": 80},
            {"faction": "Pressed Realm", "militaryPower": 20, "economicPower": 20, "politicalInfluence": 20},
        ],
    }

    report = build_intel_report(world)

    assert report["tick"] == 16
    assert report["factions"][0]["faction"] == "Pressed Realm"
