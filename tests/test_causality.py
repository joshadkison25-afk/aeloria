from engine.causality import get_tick_causes, record_cause, summarize_cause


def test_record_cause_appends_bounded_structured_record():
    world = {"tick": 7, "world_date": "Day 7"}

    record = record_cause(
        world,
        domain="diplomacy",
        actor="Twin Cities",
        pressure="border instability",
        belief="known_fact (0.90): Tidefall wants an alliance.",
        decision="form_alliance",
        outcome="Alliance talks begin.",
        affected=["Twin Cities", "Tidefall"],
        severity=9,
        confidence=0.8,
        source="test",
    )

    assert record["id"] == "cause_000001"
    assert record["tick"] == 7
    assert record["domain"] == "diplomacy"
    assert record["belief"] == "known_fact (0.90): Tidefall wants an alliance."
    assert record["affected"] == ["Twin Cities", "Tidefall"]
    assert world["causality_ledger"] == [record]
    assert get_tick_causes(world, tick=7) == [record]
    assert "Twin Cities" in summarize_cause(record)


def test_record_cause_keeps_recent_records_only():
    world = {"tick": 1}
    for idx in range(260):
        world["tick"] = idx
        record_cause(
            world,
            domain="test",
            actor="actor",
            pressure="pressure",
            decision="decision",
            outcome="outcome",
        )

    assert len(world["causality_ledger"]) == 250
    assert world["causality_ledger"][0]["id"] == "cause_000011"
    assert world["causality_ledger"][-1]["id"] == "cause_000260"
