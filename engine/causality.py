"""Causality ledger helpers for the Axiom Engine.

The ledger is intentionally lightweight: it records why important mechanical
changes happened without becoming another simulation authority.
"""

from __future__ import annotations

from typing import Any

MAX_CAUSALITY_RECORDS = 250


def _next_cause_id(world_state: dict[str, Any]) -> str:
    ledger = world_state.get("causality_ledger", [])
    if not isinstance(ledger, list):
        ledger = []
    max_seen = 0
    for row in ledger:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("id", ""))
        if not raw.startswith("cause_"):
            continue
        try:
            max_seen = max(max_seen, int(raw.split("_", 1)[1]))
        except (IndexError, TypeError, ValueError):
            continue
    return f"cause_{max_seen + 1:06d}"


def record_cause(
    world_state: dict[str, Any],
    *,
    domain: str,
    actor: str,
    pressure: str,
    decision: str,
    outcome: str,
    belief: str = "",
    affected: list[str] | None = None,
    hidden: str = "",
    severity: int = 1,
    confidence: float = 1.0,
    source: str = "engine",
) -> dict[str, Any]:
    """Append one structured cause record to ``world_state``.

    The function mutates ``world_state`` in-place and returns the new record.
    It does not alter simulation mechanics.
    """
    ledger = world_state.setdefault("causality_ledger", [])
    if not isinstance(ledger, list):
        ledger = []
        world_state["causality_ledger"] = ledger

    record = {
        "id": _next_cause_id(world_state),
        "tick": int(world_state.get("tick", 0) or 0),
        "world_date": str(world_state.get("world_date", "") or ""),
        "domain": str(domain or "general"),
        "actor": str(actor or "unknown"),
        "pressure": str(pressure or ""),
        "belief": str(belief or ""),
        "decision": str(decision or ""),
        "outcome": str(outcome or ""),
        "affected": [str(item) for item in (affected or []) if item],
        "hidden_outcome": str(hidden or ""),
        "severity": max(1, min(20, int(severity or 1))),
        "confidence": max(0.0, min(1.0, float(confidence))),
        "source": str(source or "engine"),
    }
    ledger.append(record)
    world_state["causality_ledger"] = ledger[-MAX_CAUSALITY_RECORDS:]
    return record


def get_tick_causes(world_state: dict[str, Any], tick: int | None = None) -> list[dict[str, Any]]:
    """Return ledger records for ``tick`` or the current world tick."""
    target_tick = int(world_state.get("tick", 0) if tick is None else tick)
    ledger = world_state.get("causality_ledger", [])
    if not isinstance(ledger, list):
        return []
    return [
        row for row in ledger
        if isinstance(row, dict) and int(row.get("tick", -1) or -1) == target_tick
    ]


def summarize_cause(record: dict[str, Any]) -> str:
    """Compact human-readable summary for debug surfaces and reports."""
    actor = record.get("actor") or "Unknown actor"
    decision = record.get("decision") or "acted"
    pressure = record.get("pressure") or "unspecified pressure"
    outcome = record.get("outcome") or "no recorded outcome"
    return f"{actor}: {decision} under {pressure}; {outcome}"
