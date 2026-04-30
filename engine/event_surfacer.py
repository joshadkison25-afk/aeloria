"""Promote mechanical engine truth into player-facing event fields.

This module is deliberately deterministic. It does not decide outcomes; it
reads causality records and existing subsystem reports, then presents the most
important results in the world-state fields the UI already understands.
"""

from __future__ import annotations

from typing import Any

from engine.causality import get_tick_causes, summarize_cause

DOMAIN_WEIGHTS = {
    "rebellion": 5.0,
    "succession": 4.5,
    "war_attrition": 4.0,
    "territory": 3.8,
    "tributary": 3.2,
    "population": 3.1,
    "character": 2.0,
    "legitimacy": 3.5,
    "dynasty": 3.0,
    "military": 3.0,
    "diplomacy": 2.5,
    "treaty": 2.8,
    "faction_decision": 2.0,
    "economy": 1.8,
    "intrigue": 1.2,
}

ACTION_DOMAINS = {
    "diplomacy",
    "dynasty",
    "economy",
    "faction_decision",
    "intrigue",
    "legitimacy",
    "military",
    "population",
    "rebellion",
    "succession",
    "territory",
    "treaty",
    "tributary",
    "war_attrition",
}


def _impact_for_severity(severity: int) -> str:
    if severity >= 12:
        return "high"
    if severity >= 6:
        return "medium"
    return "low"


def _stage_for_severity(severity: int) -> str:
    if severity >= 16:
        return "peak"
    if severity >= 10:
        return "escalating"
    if severity >= 5:
        return "emerging"
    return "resolving"


def _trend_for_domain(domain: str) -> str:
    if domain in {"war_attrition", "rebellion", "intrigue", "legitimacy", "population"}:
        return "rising"
    if domain in {"faction_decision", "diplomacy", "economy"}:
        return "stable"
    return "stable"


def _is_hidden(cause: dict[str, Any]) -> bool:
    return bool(cause.get("hidden_outcome")) or str(cause.get("domain") or "") == "intrigue"


def _surfacing_score(cause: dict[str, Any]) -> float:
    """Rank causes for player-facing prominence.

    This does not change truth. It only decides which already-recorded truth is
    most important to present as the headline.
    """
    domain = str(cause.get("domain") or "general")
    severity = float(cause.get("severity", 1) or 1)
    confidence = float(cause.get("confidence", 1.0) or 1.0)
    affected = [item for item in (cause.get("affected") or []) if item]
    score = severity * 2.0
    score += DOMAIN_WEIGHTS.get(domain, 1.0)
    score += min(4, len(set(affected))) * 0.75
    score += confidence
    if _is_hidden(cause):
        score -= 4.0
    if cause.get("decision") in {"seize_control", "military_overthrow", "declare_war"}:
        score += 3.0
    return round(score, 4)


def _event_name(cause: dict[str, Any]) -> str:
    actor = cause.get("actor") or "Unknown Actor"
    decision = str(cause.get("decision") or "action").replace("_", " ").title()
    return f"{decision}: {actor}"


def _cause_to_event(cause: dict[str, Any]) -> dict[str, Any]:
    severity = int(cause.get("severity", 1) or 1)
    domain = str(cause.get("domain", "general") or "general")
    affected = list(cause.get("affected") or [])
    if cause.get("actor") and cause.get("actor") not in affected:
        affected.insert(0, cause.get("actor"))
    return {
        "name": _event_name(cause),
        "summary": cause.get("outcome") or summarize_cause(cause),
        "severity": severity,
        "stage": _stage_for_severity(severity),
        "trend": _trend_for_domain(domain),
        "involved": affected[:8],
        "source": "causality_ledger",
        "cause_id": cause.get("id", ""),
        "domain": domain,
        "public_status": "hidden" if _is_hidden(cause) else "visible",
        "surfacing_score": _surfacing_score(cause),
    }


def _cause_to_recent_event(cause: dict[str, Any]) -> dict[str, Any]:
    affected = list(cause.get("affected") or [])
    return {
        "region": affected[0] if affected else cause.get("actor", "Aeloria"),
        "text": cause.get("outcome") or summarize_cause(cause),
        "impact": _impact_for_severity(int(cause.get("severity", 1) or 1)),
        "source": "causality_ledger",
        "cause_id": cause.get("id", ""),
        "domain": cause.get("domain", "general"),
    }


def _cause_to_faction_action(cause: dict[str, Any]) -> dict[str, Any]:
    affected = [item for item in (cause.get("affected") or []) if item != cause.get("actor")]
    return {
        "faction": cause.get("actor", "Unknown"),
        "action": cause.get("outcome") or cause.get("decision", ""),
        "reason": cause.get("pressure", ""),
        "target": ", ".join(affected[:4]),
        "source": "causality_ledger",
        "cause_id": cause.get("id", ""),
        "domain": cause.get("domain", "general"),
        "severity": int(cause.get("severity", 1) or 1),
    }


def _dedupe_by_name(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for event in events:
        name = event.get("name", "")
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(event)
    return result


def _public_headline_pool(causes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public = [
        cause for cause in causes
        if not _is_hidden(cause) or int(cause.get("severity", 0) or 0) >= 14
    ]
    return public or causes


def surface_events(world_state: dict[str, Any], prev_world: dict[str, Any] | None = None) -> dict[str, Any]:
    """Populate surfaced narrative/event fields from mechanical outputs.

    The function mutates and returns ``world_state``. It only uses current-tick
    causality records, so old events do not keep resurfacing forever.
    """
    if not isinstance(world_state, dict):
        return world_state

    causes = get_tick_causes(world_state)
    ranked = sorted(
        causes,
        key=lambda row: (
            _surfacing_score(row),
            int(row.get("severity", 0) or 0),
            float(row.get("confidence", 0) or 0),
            str(row.get("id", "")),
        ),
        reverse=True,
    )
    if not ranked:
        return world_state

    headline_ranked = sorted(
        _public_headline_pool(ranked),
        key=lambda row: (
            _surfacing_score(row),
            int(row.get("severity", 0) or 0),
            float(row.get("confidence", 0) or 0),
            str(row.get("id", "")),
        ),
        reverse=True,
    )
    surfaced_events = [_cause_to_event(cause) for cause in headline_ranked]
    top_event = surfaced_events[0]

    world_state["primary_event"] = {
        "name": top_event["name"],
        "summary": top_event["summary"],
        "severity": top_event["severity"],
        "stage": top_event["stage"],
        "trend": top_event["trend"],
        "involved": top_event["involved"],
        "cause_id": top_event["cause_id"],
        "domain": top_event["domain"],
    }
    world_state["major_event"] = top_event["summary"]
    world_state["supporting_events"] = [
        {
            "name": event["name"],
            "summary": event["summary"],
            "severity": event["severity"],
            "stage": event["stage"],
            "trend": event["trend"],
            "involved": event["involved"],
            "cause_id": event["cause_id"],
            "domain": event["domain"],
        }
        for event in surfaced_events[1:5]
    ]

    existing_active = [
        event for event in world_state.get("active_events", [])
        if isinstance(event, dict)
    ]
    world_state["active_events"] = _dedupe_by_name(
        existing_active + [event for event in surfaced_events if event["severity"] >= 6]
    )[:10]

    existing_recent = [
        event for event in world_state.get("recent_events", [])
        if isinstance(event, dict)
    ]
    cause_recent = [_cause_to_recent_event(cause) for cause in ranked[:8]]
    world_state["recent_events"] = (cause_recent + existing_recent)[:12]

    world_state["faction_actions"] = [
        _cause_to_faction_action(cause)
        for cause in ranked
        if cause.get("domain") in ACTION_DOMAINS and cause.get("actor")
    ][:12]
    world_state["surfacing_report"] = {
        "tick": int(world_state.get("tick", 0) or 0),
        "top_cause_id": top_event["cause_id"],
        "ranked_causes": [
            {
                "id": cause.get("id", ""),
                "domain": cause.get("domain", "general"),
                "actor": cause.get("actor", "unknown"),
                "severity": int(cause.get("severity", 1) or 1),
                "score": _surfacing_score(cause),
                "hidden": _is_hidden(cause),
            }
            for cause in ranked[:12]
        ],
    }
    world_state["engine_surfaced_tick"] = int(world_state.get("tick", 0) or 0)
    return world_state
