"""Deterministic latest-tick debug snapshot for Axiom.

The autopsy is read-only: it explains the tick that just happened without
creating pressure, beliefs, outcomes, knowledge, or surfaced events.
"""

from __future__ import annotations

from typing import Any

from engine.causality import get_tick_causes


def _current_tick(world_state: dict[str, Any], tick: int | None = None) -> int:
    return int(world_state.get("tick", 0) if tick is None else tick)


def _knowledge_spread(world_state: dict[str, Any], cause_id: str) -> dict[str, list[str]]:
    spread = {
        "known_by": [],
        "rumored_by": [],
        "suspected_by": [],
        "misread_by": [],
    }
    if not cause_id:
        return spread
    buckets = {
        "known_facts": "known_by",
        "rumors": "rumored_by",
        "suspicions": "suspected_by",
        "false_beliefs": "misread_by",
    }
    for row in world_state.get("faction_knowledge", []) or []:
        if not isinstance(row, dict):
            continue
        faction = str(row.get("faction") or "").strip()
        if not faction:
            continue
        for bucket, target in buckets.items():
            values = row.get(bucket, [])
            if isinstance(values, list) and any(cause_id in str(item) for item in values):
                spread[target].append(faction)
    return spread


def _decision_rows(world_state: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_key in (
        "decision_log",
        "economic_pressure_decisions",
        "military_faction_decisions",
        "diplomatic_faction_decisions",
    ):
        for row in world_state.get(source_key, []) or []:
            if not isinstance(row, dict):
                continue
            rows.append({
                "source": source_key,
                "faction": row.get("faction", ""),
                "action": row.get("action") or row.get("decision") or "",
                "summary": row.get("summary") or row.get("outcome") or "",
                "meta": row.get("meta", {}),
            })
    return rows[:80]


def _surfaced_rows(world_state: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    primary = world_state.get("primary_event")
    if isinstance(primary, dict) and primary.get("cause_id"):
        rows.append({"surface": "primary_event", **primary})
    for key in ("supporting_events", "active_events", "recent_events", "faction_actions"):
        for item in world_state.get(key, []) or []:
            if isinstance(item, dict) and item.get("cause_id"):
                rows.append({"surface": key, **item})
    return rows[:80]


def _character_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("faction") or ""),
        str(row.get("house") or ""),
        str(row.get("name") or ""),
    )


def _characters_by_key(world_state: dict[str, Any] | None) -> dict[tuple[str, str, str], dict[str, Any]]:
    if not isinstance(world_state, dict):
        return {}
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in world_state.get("house_characters", []) or []:
        if not isinstance(row, dict):
            continue
        key = _character_key(row)
        if key[2]:
            rows[key] = row
    return rows


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _relationship_changes(
    world_state: dict[str, Any],
    prev_world: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    previous = _characters_by_key(prev_world)
    changes: list[dict[str, Any]] = []
    for key, char in _characters_by_key(world_state).items():
        prev_char = previous.get(key, {})
        current_rels = char.get("relationships") or {}
        previous_rels = prev_char.get("relationships") or {}
        if not isinstance(current_rels, dict) or not isinstance(previous_rels, dict):
            continue

        for target, rel in current_rels.items():
            if not isinstance(rel, dict):
                continue
            prev_rel = previous_rels.get(target)
            if not isinstance(prev_rel, dict):
                continue

            axes: dict[str, dict[str, float]] = {}
            for axis, default in (("trust", 40.0), ("fear", 20.0), ("respect", 35.0)):
                before = _num(prev_rel.get(axis), default)
                after = _num(rel.get(axis), default)
                delta = round(after - before, 2)
                if abs(delta) >= 0.01:
                    axes[axis] = {
                        "before": round(before, 2),
                        "after": round(after, 2),
                        "delta": delta,
                    }

            if axes:
                changes.append({
                    "character": key[2],
                    "faction": key[0],
                    "house": key[1],
                    "target": str(target),
                    "changes": axes,
                })
    return changes[:80]


def _memory_signature(memory: dict[str, Any]) -> tuple[str, str]:
    return (str(memory.get("type") or ""), str(memory.get("target") or ""))


def _memory_changes(
    world_state: dict[str, Any],
    prev_world: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    previous = _characters_by_key(prev_world)
    changes: list[dict[str, Any]] = []
    for key, char in _characters_by_key(world_state).items():
        prev_char = previous.get(key, {})
        current_memories = char.get("memory") or []
        previous_memories = {
            _memory_signature(memory): memory
            for memory in (prev_char.get("memory") or [])
            if isinstance(memory, dict)
        }
        if not isinstance(current_memories, list):
            continue

        for memory in current_memories:
            if not isinstance(memory, dict):
                continue
            signature = _memory_signature(memory)
            prev_memory = previous_memories.get(signature)
            current_impact = _num(memory.get("impact"), 0.0)
            previous_impact = _num(prev_memory.get("impact"), 0.0) if isinstance(prev_memory, dict) else None
            is_new = prev_memory is None
            impact_delta = None if previous_impact is None else round(current_impact - previous_impact, 2)
            description_changed = (
                isinstance(prev_memory, dict)
                and str(prev_memory.get("description") or "") != str(memory.get("description") or "")
            )
            if not is_new and impact_delta == 0 and not description_changed:
                continue

            changes.append({
                "character": key[2],
                "faction": key[0],
                "house": key[1],
                "type": signature[0],
                "target": signature[1],
                "impact": round(current_impact, 2),
                "impact_delta": impact_delta,
                "new": is_new,
                "tick": int(memory.get("tick", 0) or 0),
                "description": str(memory.get("description") or ""),
            })
    return changes[:80]


def build_tick_autopsy(
    world_state: dict[str, Any],
    *,
    tick: int | None = None,
    knowledge_updates: list[dict[str, Any]] | None = None,
    prev_world: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and store ``last_tick_autopsy`` for the latest deterministic tick."""
    target_tick = _current_tick(world_state, tick)
    causes = get_tick_causes(world_state, tick=target_tick)
    updates = knowledge_updates if knowledge_updates is not None else causes

    autopsy = {
        "tick": target_tick,
        "world_date": str(world_state.get("world_date", "") or ""),
        "pressures": list(world_state.get("pressure_report", []) or [])[:80],
        "beliefs": list(world_state.get("faction_beliefs", []) or [])[:80],
        "decisions": _decision_rows(world_state),
        "outcomes": [
            {
                "cause_id": cause.get("id", ""),
                "domain": cause.get("domain", "general"),
                "actor": cause.get("actor", "unknown"),
                "decision": cause.get("decision", ""),
                "outcome": cause.get("outcome", ""),
                "severity": int(cause.get("severity", 1) or 1),
                "source": cause.get("source", "engine"),
            }
            for cause in causes
        ],
        "causality_records": causes,
        "knowledge_updates": [
            {
                "cause_id": cause.get("id", ""),
                "domain": cause.get("domain", "general"),
                "actor": cause.get("actor", "unknown"),
                "spread": _knowledge_spread(world_state, str(cause.get("id", ""))),
            }
            for cause in updates
            if isinstance(cause, dict)
        ],
        "relationship_changes": _relationship_changes(world_state, prev_world),
        "memory_changes": _memory_changes(world_state, prev_world),
        "surfaced_events": _surfaced_rows(world_state),
    }
    world_state["last_tick_autopsy"] = autopsy
    return autopsy


__all__ = ["build_tick_autopsy"]
