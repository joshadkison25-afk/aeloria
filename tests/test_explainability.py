from engine.causality import record_cause
from engine.explainability import build_explainability_report
from engine.knowledge import record_fact, record_suspicion


def test_explainability_report_ranks_causes_and_maps_knowledge_spread():
    world = {"tick": 9, "world_date": "Day 9"}
    low = record_cause(
        world,
        domain="economy",
        actor="Twin Cities",
        pressure="minor grain shortage",
        decision="seek_trade_partners",
        outcome="Envoys seek food contracts.",
        severity=4,
    )
    high = record_cause(
        world,
        domain="intrigue",
        actor="Shadow Court",
        pressure="covert pressure",
        belief="suspicion: Twin Cities is vulnerable",
        decision="sabotage",
        outcome="A supply depot burns.",
        affected=["Shadow Court", "Twin Cities"],
        hidden="The sponsor is not public.",
        severity=12,
    )
    record_fact(world, "Shadow Court", "A supply depot burns.", cause_id=high["id"])
    record_suspicion(world, "Twin Cities", "A supply depot burns.", cause_id=high["id"])
    record_fact(world, "Twin Cities", "Envoys seek food contracts.", cause_id=low["id"])

    report = build_explainability_report(world)

    assert report["tick"] == 9
    assert report["explanations"][0]["id"] == high["id"]
    assert report["explanations"][0]["public_status"] == "hidden"
    assert report["explanations"][0]["knowledge_spread"]["known_by"] == ["Shadow Court"]
    assert report["explanations"][0]["knowledge_spread"]["suspected_by"] == ["Twin Cities"]
    assert report["domain_counts"] == {"intrigue": 1, "economy": 1}


def test_explainability_report_filters_by_domain_and_faction():
    world = {"tick": 10}
    record_cause(
        world,
        domain="diplomacy",
        actor="Twin Cities",
        pressure="legitimacy stress",
        decision="marriage_diplomacy",
        outcome="Twin Cities courts Tidefall.",
        affected=["Twin Cities", "Tidefall"],
        severity=8,
    )
    record_cause(
        world,
        domain="military",
        actor="Groth Clans",
        pressure="logistics collapse",
        decision="retreat_to_safety",
        outcome="Groth shortens the front.",
        affected=["Groth Clans"],
        severity=12,
    )

    report = build_explainability_report(world, domain="diplomacy", faction="Tidefall")

    assert len(report["explanations"]) == 1
    assert report["explanations"][0]["domain"] == "diplomacy"
    assert report["explanations"][0]["actor"] == "Twin Cities"
