from axiom.engine.causality import record_cause
from axiom.engine.event_surfacer import surface_events
from axiom.engine.knowledge import (
    distribute_cause_knowledge,
    get_faction_knowledge,
    normalize_faction_knowledge_rows,
    record_fact,
    update_knowledge_from_causes,
)


def test_normalize_faction_knowledge_preserves_legacy_fields():
    rows = normalize_faction_knowledge_rows([
        {
            "faction": "Glenwood",
            "known_events": ["Border raid"],
            "rumors": ["Shadow courier seen"],
            "blind_spots": ["No spy network in Groth"],
        }
    ])

    assert rows[0]["faction"] == "Glenwood"
    assert rows[0]["known_events"] == ["Border raid"]
    assert rows[0]["known_facts"] == ["Border raid"]
    assert rows[0]["rumors"] == ["Shadow courier seen"]
    assert rows[0]["suspicions"] == []
    assert rows[0]["false_beliefs"] == []
    assert rows[0]["blind_spots"] == ["No spy network in Groth"]


def test_record_fact_creates_faction_row_and_syncs_legacy_known_events():
    world = {}

    record_fact(world, "Twin Cities", "Tidefall signs the treaty.", cause_id="cause_000001")
    row = get_faction_knowledge(world, "Twin Cities")

    assert row["known_facts"] == ["Tidefall signs the treaty. [cause_000001]"]
    assert row["known_events"] == ["Tidefall signs the treaty."]


def test_distribute_cause_knowledge_turns_betrayal_into_suspicion_for_target():
    world = {"tick": 3}
    cause = {
        "id": "cause_000010",
        "domain": "faction_decision",
        "actor": "Shadow Court",
        "decision": "betray",
        "outcome": "Shadow Court betrayed Glenwood.",
        "affected": ["Shadow Court", "Glenwood"],
    }

    distribute_cause_knowledge(world, cause)

    shadow = get_faction_knowledge(world, "Shadow Court")
    glenwood = get_faction_knowledge(world, "Glenwood")
    assert shadow["known_facts"] == ["Shadow Court betrayed Glenwood. [cause_000010]"]
    assert glenwood["suspicions"] == ["Shadow Court betrayed Glenwood. [cause_000010]"]


def test_update_knowledge_from_causes_distributes_current_tick_causes():
    world = {"tick": 8, "world_date": "Day 8", "active_events": [], "recent_events": []}
    record_cause(
        world,
        domain="faction_decision",
        actor="Twin Cities",
        pressure="trusted harbor partner",
        decision="form_alliance",
        outcome="Twin Cities formalized an alliance with Tidefall.",
        affected=["Twin Cities", "Tidefall"],
        severity=9,
    )

    applied = update_knowledge_from_causes(world)
    surface_events(world)

    twin = get_faction_knowledge(world, "Twin Cities")
    tidefall = get_faction_knowledge(world, "Tidefall")
    assert len(applied) == 1
    assert twin["known_facts"]
    assert tidefall["known_facts"]
