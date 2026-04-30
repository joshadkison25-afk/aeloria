"""Faction intel reports for player-facing inspection.

Intel combines pressure, belief, and knowledge into one readable surface. It is
read-only with respect to simulation truth.
"""

from __future__ import annotations

from typing import Any

from engine.beliefs import build_faction_beliefs, belief_summary, dominant_belief
from engine.knowledge import get_faction_knowledge
from engine.pressure import compute_faction_pressure, compute_pressure_report


def _knowledge_counts(row: dict[str, Any]) -> dict[str, int]:
    return {
        "known_facts": len(row.get("known_facts", []) or []),
        "rumors": len(row.get("rumors", []) or []),
        "suspicions": len(row.get("suspicions", []) or []),
        "false_beliefs": len(row.get("false_beliefs", []) or []),
        "blind_spots": len(row.get("blind_spots", []) or []),
    }


def _top_pressure_domains(pressure: dict[str, Any]) -> list[dict[str, Any]]:
    domains = pressure.get("domains", {})
    if not isinstance(domains, dict):
        return []
    rows = []
    for domain, payload in domains.items():
        if not isinstance(payload, dict):
            continue
        rows.append({
            "domain": str(domain),
            "score": float(payload.get("score", 0) or 0),
            "reasons": list(payload.get("reasons", []) or [])[:4],
        })
    return sorted(rows, key=lambda row: row["score"], reverse=True)


def build_faction_intel(world_state: dict[str, Any], faction: str) -> dict[str, Any]:
    """Build one faction's pressure/belief/knowledge intel row."""
    pressure = compute_faction_pressure(world_state, faction)
    beliefs = build_faction_beliefs(world_state, faction, pressure)
    knowledge = get_faction_knowledge(world_state, faction)
    dominant = dominant_belief(world_state, faction)
    return {
        "faction": faction,
        "overall_pressure": float(pressure.get("overall", 0) or 0),
        "dominant_pressure": str(pressure.get("dominant_pressure") or ""),
        "pressure_summary": str(pressure.get("summary") or ""),
        "pressure_domains": _top_pressure_domains(pressure),
        "dominant_belief": dominant,
        "dominant_belief_summary": belief_summary(dominant),
        "beliefs": list(beliefs.get("beliefs", []) or [])[:8],
        "knowledge_counts": _knowledge_counts(knowledge),
        "knowledge": {
            "known_facts": list(knowledge.get("known_facts", []) or [])[:8],
            "rumors": list(knowledge.get("rumors", []) or [])[:8],
            "suspicions": list(knowledge.get("suspicions", []) or [])[:8],
            "false_beliefs": list(knowledge.get("false_beliefs", []) or [])[:8],
            "blind_spots": list(knowledge.get("blind_spots", []) or [])[:8],
        },
    }


def build_intel_report(
    world_state: dict[str, Any],
    *,
    faction: str = "",
    limit: int = 18,
) -> dict[str, Any]:
    """Build a player-facing intel report for one or many factions."""
    if limit <= 0:
        limit = 18
    limit = min(80, limit)
    faction = str(faction or "").strip()

    if faction:
        rows = [build_faction_intel(world_state, faction)]
    else:
        pressure_report = compute_pressure_report(world_state)
        rows = [
            build_faction_intel(world_state, str(row.get("faction") or ""))
            for row in pressure_report[:limit]
            if row.get("faction")
        ]

    rows.sort(key=lambda row: row.get("overall_pressure", 0), reverse=True)
    return {
        "tick": int(world_state.get("tick", 0) or 0),
        "world_date": str(world_state.get("world_date") or ""),
        "selected_faction": faction,
        "factions": rows[:limit],
    }
