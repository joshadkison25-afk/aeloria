"""Player-facing explainability reports for Axiom causes.

This module reads engine truth; it does not create outcomes, knowledge, or
surfaced events.
"""

from __future__ import annotations

from typing import Any


def _ledger(world_state: dict[str, Any]) -> list[dict[str, Any]]:
    value = world_state.get("causality_ledger", [])
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _matches(cause: dict[str, Any], *, domain: str = "", faction: str = "") -> bool:
    if domain and str(cause.get("domain") or "") != domain:
        return False
    if faction:
        affected = [str(item) for item in cause.get("affected", []) or []]
        if faction != str(cause.get("actor") or "") and faction not in affected:
            return False
    return True


def _knowledge_spread(world_state: dict[str, Any], cause_id: str) -> dict[str, list[str]]:
    spread = {
        "known_by": [],
        "rumored_by": [],
        "suspected_by": [],
        "misread_by": [],
    }
    if not cause_id:
        return spread

    rows = world_state.get("faction_knowledge", [])
    if not isinstance(rows, list):
        return spread
    buckets = {
        "known_facts": "known_by",
        "rumors": "rumored_by",
        "suspicions": "suspected_by",
        "false_beliefs": "misread_by",
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        faction = str(row.get("faction") or "").strip()
        if not faction:
            continue
        for bucket, spread_key in buckets.items():
            items = row.get(bucket, [])
            if not isinstance(items, list):
                continue
            if any(cause_id in str(item) for item in items):
                spread[spread_key].append(faction)
    return spread


def _public_status(cause: dict[str, Any], spread: dict[str, list[str]]) -> str:
    domain = str(cause.get("domain") or "")
    if cause.get("hidden_outcome"):
        return "hidden"
    if domain in {
        "rebellion",
        "war_attrition",
        "legitimacy",
        "succession",
        "character",
        "dynasty",
        "health",
        "population",
        "stability",
        "territory",
        "treaty",
        "tributary",
    }:
        return "public"
    if spread["known_by"] and (spread["rumored_by"] or spread["suspected_by"]):
        return "contested"
    if domain == "intrigue":
        return "covert"
    return "partial"


def explain_cause(world_state: dict[str, Any], cause: dict[str, Any]) -> dict[str, Any]:
    cause_id = str(cause.get("id") or "")
    spread = _knowledge_spread(world_state, cause_id)
    return {
        "id": cause_id,
        "tick": int(cause.get("tick", 0) or 0),
        "world_date": str(cause.get("world_date") or ""),
        "domain": str(cause.get("domain") or "general"),
        "actor": str(cause.get("actor") or "unknown"),
        "severity": int(cause.get("severity", 1) or 1),
        "confidence": float(cause.get("confidence", 1.0) or 1.0),
        "public_status": _public_status(cause, spread),
        "affected": [str(item) for item in cause.get("affected", []) or [] if item],
        "source": str(cause.get("source") or ""),
        "pipeline": {
            "pressure": str(cause.get("pressure") or ""),
            "belief": str(cause.get("belief") or ""),
            "decision": str(cause.get("decision") or ""),
            "outcome": str(cause.get("outcome") or ""),
            "hidden_outcome": str(cause.get("hidden_outcome") or ""),
        },
        "knowledge_spread": spread,
    }


def build_explainability_report(
    world_state: dict[str, Any],
    *,
    tick: int | None = None,
    domain: str = "",
    faction: str = "",
    limit: int = 24,
) -> dict[str, Any]:
    """Return ranked cause explanations for UI/API surfaces."""
    if limit <= 0:
        limit = 24
    limit = min(80, limit)
    target_tick = int(world_state.get("tick", 0) if tick is None else tick)
    domain = str(domain or "").strip()
    faction = str(faction or "").strip()

    causes = [
        cause for cause in _ledger(world_state)
        if int(cause.get("tick", -1) or -1) == target_tick
        and _matches(cause, domain=domain, faction=faction)
    ]
    causes.sort(
        key=lambda c: (
            int(c.get("severity", 0) or 0),
            float(c.get("confidence", 0) or 0),
            str(c.get("id") or ""),
        ),
        reverse=True,
    )
    explanations = [explain_cause(world_state, cause) for cause in causes[:limit]]
    domain_counts: dict[str, int] = {}
    for cause in causes:
        key = str(cause.get("domain") or "general")
        domain_counts[key] = domain_counts.get(key, 0) + 1
    return {
        "tick": target_tick,
        "world_date": str(world_state.get("world_date") or ""),
        "filters": {
            "domain": domain,
            "faction": faction,
            "limit": limit,
        },
        "domain_counts": domain_counts,
        "explanations": explanations,
    }
