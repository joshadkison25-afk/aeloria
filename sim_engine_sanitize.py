"""
Harden the simulation engine against malformed world JSON (stray strings, null rows, etc.).

Call `sanitize_world_state` early — e.g. from `ensure_world_structure` in scheduler.py
before any system iterates `faction_power_state` or `relationships` with .get().
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Set

__all__ = [
    "sanitize_faction_power_state",
    "sanitize_relationships",
    "sanitize_list_of_dicts",
    "sanitize_world_state",
]


def _keep_row(row: Any, id_keys: Set[str]) -> bool:
    if not isinstance(row, dict):
        return False
    if not id_keys:
        return True
    for k in id_keys:
        v = row.get(k)
        if v is not None and str(v).strip() != "":
            return True
    return False


def sanitize_faction_power_state(state: dict) -> None:
    key = "faction_power_state"
    raw = state.get(key)
    if not isinstance(raw, list):
        state[key] = []
        return
    out: List[dict] = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        fac = (p.get("faction") or p.get("faction_id") or "").strip()
        if not fac:
            continue
        p = deepcopy(p)
        p["faction"] = fac
        out.append(p)
    state[key] = out


def sanitize_relationships(state: dict) -> None:
    key = "relationships"
    raw = state.get(key)
    if not isinstance(raw, list):
        state[key] = []
        return
    out: List[dict] = []
    seen: Set[tuple] = set()
    for r in raw:
        if not isinstance(r, dict):
            continue
        a = (r.get("faction_a") or "").strip() if r.get("faction_a") is not None else ""
        b = (r.get("faction_b") or "").strip() if r.get("faction_b") is not None else ""
        if not a or not b or a == b:
            continue
        tkey = tuple(sorted((a, b)))
        if tkey in seen:
            continue
        seen.add(tkey)
        r = deepcopy(r)
        r["faction_a"] = a
        r["faction_b"] = b
        out.append(r)
    state[key] = out


def sanitize_list_of_dicts(
    state: dict,
    key: str,
    id_keys: Set[str] | None = None,
) -> None:
    """Keep only dict rows; optionally require at least one of id_keys truthy."""
    raw = state.get(key)
    if not isinstance(raw, list):
        state[key] = []
        return
    if id_keys is None:
        id_keys = set()
    out: List[dict] = [
        x for x in raw if isinstance(x, dict) and (not id_keys or _keep_row(x, id_keys))
    ]
    state[key] = out


def sanitize_world_state(state: dict) -> None:
    """
    In-place cleaning of the worst failure modes. Safe to run every tick.
    Does not add missing top-level keys (scheduler still does that).
    """
    if not isinstance(state, dict):
        return
    sanitize_faction_power_state(state)
    sanitize_relationships(state)
    sanitize_list_of_dicts(state, "locations")
    sanitize_list_of_dicts(state, "faction_economy", {"faction_id", "faction"})
    sanitize_list_of_dicts(state, "house_characters", {"name", "faction"})
    sanitize_list_of_dicts(state, "leadership_state", {"faction"})
    sanitize_list_of_dicts(state, "faction_armies", {"army_id", "faction_id"})
    sanitize_list_of_dicts(state, "region_control", set())
    sanitize_list_of_dicts(state, "treaties", set())
    sanitize_list_of_dicts(state, "active_events", set())
    sanitize_list_of_dicts(state, "supporting_events", set())
    sanitize_list_of_dicts(state, "faction_actions", set())
    sanitize_list_of_dicts(state, "decision_log", set())
    sanitize_list_of_dicts(state, "intrigue_pending", set())
    sanitize_list_of_dicts(state, "diplomatic_faction_decisions", set())
    sanitize_list_of_dicts(state, "legitimacy_report", set())
    th = state.get("tick_history")
    if not isinstance(th, list):
        state["tick_history"] = []
    else:
        state["tick_history"] = [h for h in th if isinstance(h, dict)]
    ac = state.get("active_blackmail_coercion")
    if ac is not None and isinstance(ac, list):
        state["active_blackmail_coercion"] = [x for x in ac if isinstance(x, dict)]
