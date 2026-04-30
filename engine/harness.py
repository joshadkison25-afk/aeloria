"""Deterministic multi-tick simulation harness for Axiom.

No AI. No IO. Drives engine.tick.run_tick() for N ticks, validates each
result, and returns a summary dict. Mirrors the tick-prep logic in
scheduler._prepare_engine_tick_state without importing the scheduler.
"""

from __future__ import annotations

import copy
from typing import Any

from engine.tick import run_tick
from world_state.validate import CONTAINER_PRESERVE_KEYS, is_valid_world

_MAX_LEDGER = 250


def _prepare(state: dict[str, Any]) -> dict[str, Any]:
    """Advance tick and world_date in a deep copy, matching scheduler prep."""
    state = copy.deepcopy(state)
    next_tick = int(state.get("tick", 0) or 0) + 1
    state["tick"] = next_tick
    state["world_date"] = f"Day {next_tick}"
    state.setdefault("primary_event", {})
    state.setdefault("supporting_events", [])
    state.setdefault("active_events", [])
    state.setdefault("recent_events", [])
    return state


def _validate(prev: dict[str, Any], result: dict[str, Any], expected_tick: int) -> list[str]:
    """Return a list of validation warning strings for one tick result."""
    warnings: list[str] = []

    if result.get("tick") != expected_tick:
        warnings.append(f"tick={result.get('tick')!r} expected {expected_tick}")

    expected_date = f"Day {expected_tick}"
    if result.get("world_date") != expected_date:
        warnings.append(f"world_date={result.get('world_date')!r} expected {expected_date!r}")

    if not is_valid_world(result):
        warnings.append("is_valid_world() returned False")

    for key in CONTAINER_PRESERVE_KEYS:
        if key in prev and result.get(key) is None:
            warnings.append(f"container {key!r} became None")

    ledger = result.get("causality_ledger") or []
    if isinstance(ledger, list) and len(ledger) > _MAX_LEDGER:
        warnings.append(f"causality_ledger has {len(ledger)} records (max {_MAX_LEDGER})")

    if not isinstance(result.get("last_tick_autopsy"), dict):
        warnings.append("last_tick_autopsy missing")

    ledger_ids = {r.get("id") for r in ledger if isinstance(r, dict)}
    primary = result.get("primary_event") or {}
    cause_id = primary.get("cause_id") if isinstance(primary, dict) else None
    if cause_id and cause_id not in ledger_ids:
        warnings.append(f"primary_event.cause_id {cause_id!r} not in causality_ledger")

    return warnings


def run_ticks(world_state: dict[str, Any], n_ticks: int) -> dict[str, Any]:
    """Run *n_ticks* deterministic ticks starting from *world_state*.

    Returns a summary dict. The final world state is included under
    ``"final_world"`` for further inspection.
    """
    state = copy.deepcopy(world_state)
    all_warnings: list[dict[str, Any]] = []
    domain_counts: dict[str, int] = {}
    faction_counts: dict[str, int] = {}
    total_surfaced_actions = 0

    for _ in range(n_ticks):
        prev = copy.deepcopy(state)
        state = _prepare(state)
        expected_tick = int(state["tick"])

        state = run_tick(state, prev_world=prev)

        tick_warnings = _validate(prev, state, expected_tick)
        if tick_warnings:
            all_warnings.append({"tick": expected_tick, "warnings": tick_warnings})

        for cause in state.get("causality_ledger") or []:
            if not isinstance(cause, dict):
                continue
            if int(cause.get("tick", -1) or -1) != expected_tick:
                continue
            domain = str(cause.get("domain") or "unknown")
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            actor = str(cause.get("actor") or "").strip()
            if actor:
                faction_counts[actor] = faction_counts.get(actor, 0) + 1

        total_surfaced_actions += len([
            e for e in (state.get("faction_actions") or [])
            if isinstance(e, dict) and e.get("faction")
        ])

    ledger = state.get("causality_ledger") or []
    top_domains = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:6]
    top_factions = sorted(faction_counts.items(), key=lambda x: x[1], reverse=True)[:6]

    return {
        "ticks_run": n_ticks,
        "final_tick": int(state.get("tick", 0) or 0),
        "total_causality_records_in_ledger": len(ledger),
        "total_surfaced_faction_actions": total_surfaced_actions,
        "top_pressure_domains": [{"domain": d, "count": c} for d, c in top_domains],
        "top_active_factions": [{"faction": f, "actions": c} for f, c in top_factions],
        "warning_count": sum(len(w["warnings"]) for w in all_warnings),
        "warnings_by_tick": all_warnings,
        "final_world": state,
    }


def print_summary(summary: dict[str, Any]) -> None:
    """Print a human-readable run summary to stdout."""
    print(f"\n=== Axiom Harness Run ({summary['ticks_run']} ticks) ===")
    print(f"  Final tick           : {summary['final_tick']}")
    print(f"  Causality records    : {summary['total_causality_records_in_ledger']}")
    print(f"  Surfaced actions     : {summary['total_surfaced_faction_actions']}")
    print(f"  Validation warnings  : {summary['warning_count']}")
    if summary["top_pressure_domains"]:
        domains = ", ".join(f"{r['domain']}({r['count']})" for r in summary["top_pressure_domains"])
        print(f"  Top domains          : {domains}")
    if summary["top_active_factions"]:
        factions = ", ".join(f"{r['faction']}({r['actions']})" for r in summary["top_active_factions"])
        print(f"  Most active factions : {factions}")
    if summary["warnings_by_tick"]:
        print("  Warnings:")
        for entry in summary["warnings_by_tick"]:
            for w in entry["warnings"]:
                print(f"    tick {entry['tick']}: {w}")
    print()
