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


def build_tick_autopsy(
    world_state: dict[str, Any],
    *,
    tick: int | None = None,
    knowledge_updates: list[dict[str, Any]] | None = None,
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
        "surfaced_events": _surfaced_rows(world_state),
    }
    world_state["last_tick_autopsy"] = autopsy
    return autopsy


__all__ = ["build_tick_autopsy"]
