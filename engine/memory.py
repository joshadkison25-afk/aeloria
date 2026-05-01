"""Durable faction memory for the Axiom Engine.

Memory promotes high-severity causality records into long-term faction state
before they rotate out of the bounded ledger. Memories decay per tick but
persist across hundreds of ticks, feeding back into pressure and belief.

Pipeline slot: after knowledge update, before surfacing.

  record -> knowledge -> memory -> future pressure / belief
"""

from __future__ import annotations

from typing import Any

from engine.causality import get_tick_causes

SEVERITY_THRESHOLD = 6
MAX_MEMORIES_PER_FACTION = 30
MIN_WEIGHT = 0.05

DECAY_RATES: dict[str, float] = {
    "war_attrition":    0.97,
    "succession":       0.95,
    "rebellion":        0.95,
    "legitimacy":       0.94,
    "treaty":           0.93,
    "tributary":        0.93,
    "health":           0.93,
    "population":       0.93,
    "stability":        0.94,
    "military":         0.92,
    "diplomacy":        0.91,
    "economy":          0.90,
    "character":        0.88,
    "intrigue":         0.87,
    "faction_decision": 0.85,
}
_DEFAULT_DECAY = 0.88

_DOMAIN_TO_PRESSURE: dict[str, str] = {
    "war_attrition":    "military",
    "military":         "military",
    "rebellion":        "stability",
    "legitimacy":       "legitimacy",
    "succession":       "legitimacy",
    "character":        "legitimacy",
    "economy":          "economic",
    "health":           "stability",
    "population":       "stability",
    "stability":        "stability",
    "tributary":        "economic",
    "diplomacy":        "diplomatic",
    "treaty":           "diplomatic",
    "intrigue":         "knowledge",
    "faction_decision": "stability",
}


def _memory_id(cause_id: str, faction: str) -> str:
    slug = "".join(c if c.isalnum() else "_" for c in faction).strip("_").lower()[:20]
    return f"mem_{slug}_{cause_id}"


def _rows(world_state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = world_state.get("faction_memories")
    if not isinstance(rows, list):
        rows = []
        world_state["faction_memories"] = rows
    return rows


def get_faction_memories(world_state: dict[str, Any], faction: str) -> dict[str, Any]:
    """Return the memory row for *faction*, creating it if absent."""
    faction = str(faction or "").strip()
    for row in _rows(world_state):
        if isinstance(row, dict) and row.get("faction") == faction:
            return row
    row: dict[str, Any] = {"faction": faction, "memories": []}
    _rows(world_state).append(row)
    return row


def _promote_cause(world_state: dict[str, Any], cause: dict[str, Any]) -> None:
    severity = int(cause.get("severity", 1) or 1)
    if severity < SEVERITY_THRESHOLD:
        return

    actor = str(cause.get("actor") or "").strip()
    affected = [str(a).strip() for a in (cause.get("affected") or []) if str(a).strip()]
    tick = int(cause.get("tick", 0) or 0)
    domain = str(cause.get("domain") or "general")
    summary = str(cause.get("outcome") or cause.get("decision") or "").strip()
    cause_id = str(cause.get("id") or "")
    hidden = bool(cause.get("hidden_outcome")) or domain == "intrigue"

    def _add(faction: str, memory_type: str) -> None:
        if not faction:
            return
        row = get_faction_memories(world_state, faction)
        mem_id = _memory_id(cause_id, faction)
        if any(m.get("id") == mem_id for m in row["memories"]):
            return
        row["memories"].insert(0, {
            "id": mem_id,
            "cause_id": cause_id,
            "tick": tick,
            "domain": domain,
            "actor": actor,
            "summary": summary,
            "severity": severity,
            "weight": 1.0,
            "affected": affected,
            "memory_type": memory_type,
            "hidden": hidden,
        })
        row["memories"] = row["memories"][:MAX_MEMORIES_PER_FACTION]

    if actor:
        _add(actor, "own_action")
    if not hidden:
        for faction in affected:
            if faction != actor:
                _add(faction, "suffered")


def _decay_and_prune(world_state: dict[str, Any]) -> None:
    for row in _rows(world_state):
        if not isinstance(row, dict):
            continue
        kept = []
        for mem in row.get("memories") or []:
            if not isinstance(mem, dict):
                continue
            rate = DECAY_RATES.get(str(mem.get("domain") or ""), _DEFAULT_DECAY)
            mem["weight"] = round(float(mem.get("weight", 1.0) or 1.0) * rate, 4)
            if mem["weight"] >= MIN_WEIGHT:
                kept.append(mem)
        row["memories"] = kept


def update_faction_memories(world_state: dict[str, Any]) -> list[dict[str, Any]]:
    """Promote current-tick causes to memory, then decay all memories.

    Call after knowledge update, before surfacing.
    """
    for cause in get_tick_causes(world_state):
        _promote_cause(world_state, cause)
    _decay_and_prune(world_state)
    return _rows(world_state)


def memory_pressure_delta(world_state: dict[str, Any], faction: str) -> dict[str, float]:
    """Return small pressure additions from durable faction memories.

    Conservative: caps at 15 points per domain so memories nudge pressure
    without overwhelming current-tick signals.
    """
    row = get_faction_memories(world_state, faction)
    deltas: dict[str, float] = {}
    for mem in row.get("memories") or []:
        if not isinstance(mem, dict):
            continue
        pressure_domain = _DOMAIN_TO_PRESSURE.get(str(mem.get("domain") or ""))
        if not pressure_domain:
            continue
        weight = float(mem.get("weight", 1.0) or 1.0)
        severity = float(mem.get("severity", 1) or 1)
        multiplier = 1.4 if mem.get("memory_type") == "suffered" else 0.7
        contribution = severity * weight * multiplier * 0.25
        deltas[pressure_domain] = min(15.0, deltas.get(pressure_domain, 0.0) + contribution)
    return {k: round(v, 2) for k, v in deltas.items() if v > 0.5}


def memory_beliefs(world_state: dict[str, Any], faction: str) -> list[dict[str, Any]]:
    """Return belief items derived from high-weight suffered memories.

    Only surfaces memories strong enough to plausibly shape current decisions.
    """
    row = get_faction_memories(world_state, faction)
    beliefs = []
    seen: set[str] = set()
    for mem in sorted(
        (m for m in row.get("memories") or [] if isinstance(m, dict)),
        key=lambda m: float(m.get("weight", 0) or 0),
        reverse=True,
    ):
        if mem.get("memory_type") != "suffered":
            continue
        actor = str(mem.get("actor") or "").strip()
        if not actor or actor == faction or actor in seen:
            continue
        weight = float(mem.get("weight", 1.0) or 1.0)
        if weight < 0.25:
            continue
        seen.add(actor)
        summary = str(mem.get("summary") or "").strip()
        claim = f"{actor} has acted against {faction}" + (f": {summary}" if summary else "")
        beliefs.append({
            "subject": actor,
            "claim": claim,
            "confidence": round(min(0.82, weight * 0.85), 2),
            "source": "memory",
            "bias": str(mem.get("domain") or "historical"),
        })
        if len(beliefs) >= 4:
            break
    return beliefs
