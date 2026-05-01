"""Faction knowledge model for Axiom.

Knowledge is separate from truth. Causality records what happened; this module
tracks which factions know, suspect, misunderstand, or spread versions of it.
"""

from __future__ import annotations

from typing import Any

MAX_ITEMS_PER_BUCKET = 40
KNOWLEDGE_BUCKETS = ("known_facts", "rumors", "suspicions", "false_beliefs", "blind_spots")


def _empty_row(faction: str) -> dict[str, Any]:
    return {
        "faction": faction,
        "known_events": [],
        "known_facts": [],
        "rumors": [],
        "suspicions": [],
        "false_beliefs": [],
        "blind_spots": [],
    }


def _as_text(item: Any) -> str:
    if isinstance(item, dict):
        text = item.get("text") or item.get("summary") or item.get("event") or item.get("belief")
        return str(text or "").strip()
    return str(item or "").strip()


def normalize_faction_knowledge_rows(value: Any) -> list[dict[str, Any]]:
    """Normalize legacy list and future dict formats into stable row objects."""
    rows: list[dict[str, Any]] = []

    if isinstance(value, dict):
        iterable = []
        for faction, payload in value.items():
            if isinstance(payload, dict):
                iterable.append({"faction": faction, **payload})
            else:
                iterable.append({"faction": faction})
    elif isinstance(value, list):
        iterable = [row for row in value if isinstance(row, dict)]
    else:
        iterable = []

    seen = set()
    for row in iterable:
        faction = str(row.get("faction") or "").strip()
        if not faction or faction in seen:
            continue
        seen.add(faction)
        normalized = _empty_row(faction)
        legacy_known = [_as_text(item) for item in row.get("known_events", [])]
        normalized["known_events"] = [item for item in legacy_known if item][:8]
        for bucket in KNOWLEDGE_BUCKETS:
            items = [_as_text(item) for item in row.get(bucket, [])]
            normalized[bucket] = [item for item in items if item][:MAX_ITEMS_PER_BUCKET]
        if not normalized["known_facts"] and normalized["known_events"]:
            normalized["known_facts"] = normalized["known_events"][:]
        rows.append(normalized)
    return rows[:80]


def _knowledge_rows(world_state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = normalize_faction_knowledge_rows(world_state.get("faction_knowledge", []))
    world_state["faction_knowledge"] = rows
    return rows


def get_faction_knowledge(world_state: dict[str, Any], faction: str) -> dict[str, Any]:
    """Return a faction knowledge row, creating it if needed."""
    faction = str(faction or "").strip()
    if not faction:
        faction = "Unknown"
    rows = _knowledge_rows(world_state)
    for row in rows:
        if row.get("faction") == faction:
            return row
    row = _empty_row(faction)
    rows.append(row)
    world_state["faction_knowledge"] = rows[-80:]
    return row


def record_knowledge(
    world_state: dict[str, Any],
    faction: str,
    bucket: str,
    text: str,
    *,
    cause_id: str = "",
) -> dict[str, Any]:
    """Record one knowledge item for one faction.

    ``bucket`` may be known_facts, rumors, suspicions, false_beliefs, or
    blind_spots. Legacy ``known_events`` is kept in sync for known facts.
    """
    if bucket == "known_events":
        bucket = "known_facts"
    if bucket not in KNOWLEDGE_BUCKETS:
        raise ValueError(f"Unknown knowledge bucket: {bucket}")
    text = str(text or "").strip()
    if not text:
        return get_faction_knowledge(world_state, faction)

    row = get_faction_knowledge(world_state, faction)
    item = text if not cause_id else f"{text} [{cause_id}]"
    values = [existing for existing in row.get(bucket, []) if existing != item]
    values.insert(0, item)
    row[bucket] = values[:MAX_ITEMS_PER_BUCKET]
    if bucket == "known_facts":
        legacy = [existing for existing in row.get("known_events", []) if existing != text]
        legacy.insert(0, text)
        row["known_events"] = legacy[:8]
    return row


def record_fact(world_state: dict[str, Any], faction: str, text: str, *, cause_id: str = "") -> dict[str, Any]:
    return record_knowledge(world_state, faction, "known_facts", text, cause_id=cause_id)


def record_rumor(world_state: dict[str, Any], faction: str, text: str, *, cause_id: str = "") -> dict[str, Any]:
    return record_knowledge(world_state, faction, "rumors", text, cause_id=cause_id)


def record_suspicion(world_state: dict[str, Any], faction: str, text: str, *, cause_id: str = "") -> dict[str, Any]:
    return record_knowledge(world_state, faction, "suspicions", text, cause_id=cause_id)


def record_false_belief(world_state: dict[str, Any], faction: str, text: str, *, cause_id: str = "") -> dict[str, Any]:
    return record_knowledge(world_state, faction, "false_beliefs", text, cause_id=cause_id)


def distribute_cause_knowledge(world_state: dict[str, Any], cause: dict[str, Any]) -> None:
    """Create first-pass knowledge traces from a causality record."""
    actor = str(cause.get("actor") or "").strip()
    affected = [str(item).strip() for item in cause.get("affected", []) if str(item).strip()]
    text = str(cause.get("outcome") or cause.get("decision") or "").strip()
    cause_id = str(cause.get("id") or "")
    domain = str(cause.get("domain") or "")
    decision = str(cause.get("decision") or "")

    if not text:
        return

    public_domains = {
        "war_attrition",
        "rebellion",
        "succession",
        "character",
        "dynasty",
        "health",
        "population",
        "stability",
        "treaty",
        "territory",
        "tributary",
    }
    public_decisions = {"declare_war", "form_alliance", "stabilize_territory"}
    private_domains = {"intrigue", "covert", "espionage"}

    if domain in public_domains or decision in public_decisions:
        for faction in dict.fromkeys([actor, *affected]):
            record_fact(world_state, faction, text, cause_id=cause_id)
        return

    if decision == "betray":
        if actor:
            record_fact(world_state, actor, text, cause_id=cause_id)
        for faction in affected:
            record_suspicion(world_state, faction, text, cause_id=cause_id)
        return

    if domain in private_domains:
        if actor:
            record_fact(world_state, actor, text, cause_id=cause_id)
        for faction in affected:
            if faction != actor:
                record_rumor(world_state, faction, text, cause_id=cause_id)
        return

    if actor:
        record_fact(world_state, actor, text, cause_id=cause_id)
    for faction in affected:
        if faction != actor:
            record_rumor(world_state, faction, text, cause_id=cause_id)


def update_knowledge_from_causes(world_state: dict[str, Any], tick: int | None = None) -> list[dict[str, Any]]:
    """Apply current tick causality records to faction knowledge.

    This owns the ``record -> knowledge`` step so the event surfacer can stay
    read-only with respect to knowledge.
    """
    from engine.causality import get_tick_causes

    applied = []
    for cause in get_tick_causes(world_state, tick=tick):
        distribute_cause_knowledge(world_state, cause)
        applied.append(cause)
    world_state["knowledge_updated_tick"] = int(
        world_state.get("tick", 0) if tick is None else tick
    )
    return applied
