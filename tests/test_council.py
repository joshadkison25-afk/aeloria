from axiom.engine.causality import record_cause
from axiom.engine.council import build_council_report, update_council_report
from axiom.engine.knowledge import record_suspicion


def test_council_report_routes_pressure_to_advisors():
    world = {
        "tick": 9,
        "world_date": "Day 9",
        "pressure_report": [
            {
                "faction": "Groth Clans",
                "overall": 28,
                "dominant_pressure": "military",
                "domains": {
                    "military": {"score": 60, "reasons": ["at war with Gilgeth Clans"]},
                    "economic": {"score": 35, "reasons": ["food below safe level"]},
                    "stability": {"score": 20, "reasons": ["weak control in Groth"]},
                },
            }
        ],
        "relationships": [
            {
                "faction_a": "Groth Clans",
                "faction_b": "Gilgeth Clans",
                "type": "war",
                "war_ticks": 4,
            }
        ],
    }

    report = build_council_report(world)

    assert report["tick"] == 9
    assert any(item["kind"] == "military" for item in report["advisor_reports"]["marshal"])
    assert any(item["kind"] == "war" for item in report["advisor_reports"]["marshal"])
    assert any(item["kind"] == "economy" for item in report["advisor_reports"]["steward"])
    assert any(item["kind"] == "stability" for item in report["advisor_reports"]["steward"])
    assert report["advisor_briefings"]["marshal"]["status"] in {"watch", "critical"}
    assert report["advisor_briefings"]["steward"]["focus"]
    assert any(item["kind"] == "strategic_question" for item in report["strategic_questions"])
    assert report["top_risks"]


def test_council_report_surfaces_spymaster_and_chronicler_intel():
    world = {
        "tick": 11,
        "world_date": "Day 11",
        "pressure_report": [
            {
                "faction": "Glenwood",
                "overall": 18,
                "dominant_pressure": "knowledge",
                "domains": {
                    "knowledge": {"score": 45, "reasons": ["active suspicions"]},
                },
            }
        ],
        "primary_event": {
            "name": "Border Unrest",
            "summary": "Glenwood suspects outside funding.",
            "severity": 8,
        },
        "faction_beliefs": [
            {
                "faction": "Glenwood",
                "beliefs": [
                    {
                        "claim": "Shadow Court may be funding unrest.",
                        "confidence": 0.58,
                        "source": "suspicion",
                    }
                ],
            }
        ],
    }
    record_suspicion(world, "Glenwood", "Shadow Court may be funding unrest.")
    record_cause(
        world,
        domain="faction_decision",
        actor="Glenwood",
        pressure="knowledge pressure",
        belief="suspicion (0.58): Shadow Court may be funding unrest.",
        decision="stabilize_territory",
        outcome="Glenwood increases patrols.",
        severity=5,
    )

    report = update_council_report(world)

    assert world["council_report"] == report
    assert any(item["kind"] == "suspicion" for item in report["advisor_reports"]["spymaster"])
    assert any(item["kind"] == "cause" for item in report["advisor_reports"]["chronicler"])
    assert any(item["kind"] == "primary_event" for item in report["advisor_reports"]["chronicler"])
    assert report["advisor_briefings"]["spymaster"]["focus"]
    assert any("bad information" in item["title"] for item in report["strategic_questions"])
