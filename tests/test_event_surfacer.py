from engine.causality import record_cause
from engine.event_surfacer import surface_events


def test_surface_events_promotes_highest_cause_to_primary_event():
    world = {"tick": 12, "world_date": "Day 12", "active_events": [], "recent_events": []}
    record_cause(
        world,
        domain="faction_decision",
        actor="Twin Cities",
        pressure="rival power rising",
        decision="form_alliance",
        outcome="Twin Cities formalized an alliance with Tidefall.",
        affected=["Twin Cities", "Tidefall"],
        severity=9,
        confidence=0.8,
    )
    record_cause(
        world,
        domain="war_attrition",
        actor="Groth and Gilgeth",
        pressure="ten consecutive ticks of open war",
        decision="continue_war",
        outcome="War exhaustion spreads through both armies.",
        affected=["Groth", "Gilgeth"],
        severity=12,
        confidence=1.0,
    )

    surface_events(world)

    assert world["primary_event"]["name"] == "Continue War: Groth and Gilgeth"
    assert world["primary_event"]["severity"] == 12
    assert world["primary_event"]["domain"] == "war_attrition"
    assert world["supporting_events"][0]["name"] == "Form Alliance: Twin Cities"
    assert world["recent_events"][0]["impact"] == "high"
    assert world["faction_actions"][0]["faction"] == "Groth and Gilgeth"
    assert world["faction_actions"][0]["domain"] == "war_attrition"
    assert world["surfacing_report"]["top_cause_id"] == world["primary_event"]["cause_id"]
    assert world["engine_surfaced_tick"] == 12


def test_surface_events_no_causes_leaves_world_unchanged():
    world = {"tick": 1, "primary_event": {"name": "Existing"}}

    surface_events(world)

    assert world == {"tick": 1, "primary_event": {"name": "Existing"}}


def test_surface_events_keeps_hidden_intrigue_from_stealing_public_headline():
    world = {"tick": 20, "world_date": "Day 20", "active_events": [], "recent_events": []}
    record_cause(
        world,
        domain="intrigue",
        actor="Shadow Court",
        pressure="covert pressure",
        decision="sabotage",
        outcome="A hidden patron burns a depot.",
        hidden="The sponsor is not public.",
        affected=["Shadow Court", "Twin Cities"],
        severity=13,
        confidence=0.7,
    )
    record_cause(
        world,
        domain="rebellion",
        actor="Rebels",
        pressure="stability collapse",
        decision="rise_in_rebellion",
        outcome="Lowmarket rises against the crown.",
        affected=["Rebels", "Twin Cities"],
        severity=11,
        confidence=0.9,
    )

    surface_events(world)

    assert world["primary_event"]["domain"] == "rebellion"
    assert world["primary_event"]["name"] == "Rise In Rebellion: Rebels"
    assert world["surfacing_report"]["ranked_causes"][0]["domain"] == "rebellion"


def test_surface_events_includes_non_decision_domains_in_faction_actions():
    world = {"tick": 21, "world_date": "Day 21", "active_events": [], "recent_events": []}
    record_cause(
        world,
        domain="diplomacy",
        actor="Twin Cities",
        pressure="legitimacy stress",
        decision="marriage_diplomacy",
        outcome="Twin Cities courts Tidefall.",
        affected=["Twin Cities", "Tidefall"],
        severity=8,
        confidence=0.8,
    )

    surface_events(world)

    assert world["faction_actions"][0]["domain"] == "diplomacy"
    assert world["faction_actions"][0]["faction"] == "Twin Cities"
