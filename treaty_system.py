"""
Formal treaties: expiration, breach detection, trust / reputation / optional war.
Trust between factions uses the same bilateral row as `relationships[].trust` (0–100).
Output this tick: `state['treaty_tick_outcomes']` — one record per affected treaty.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Set, Tuple

from axiom.engine.causality import record_cause

TREATY_TYPES = frozenset({"alliance", "non_aggression", "trade", "military_pact"})


def _pair_key(a: str, b: str) -> Tuple[str, str]:
    return tuple(sorted((a.strip(), b.strip())))  # type: ignore[return-value]


def _find_rel_row(state: dict, a: str, b: str) -> Optional[dict]:
    key = _pair_key(a, b)
    for row in state.get("relationships") or []:
        if not isinstance(row, dict):
            continue
        ra, rb = (row.get("faction_a") or ""), (row.get("faction_b") or "")
        if _pair_key(ra, rb) == key:
            return row
    return None


def _ensure_pair_row(state: dict, a: str, b: str) -> dict:
    r = _find_rel_row(state, a, b)
    if r:
        return r
    row = {
        "faction_a": a,
        "faction_b": b,
        "type": "neutral",
        "intensity": 50,
        "trust": 50,
        "hostility": 25,
        "alliance_level": 0,
    }
    state.setdefault("relationships", []).append(row)
    return row


def _clamp(v: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(v)))


def _participants(t: dict) -> List[str]:
    out: List[str] = []
    for p in t.get("participants") or []:
        s = str(p).strip()
        if s and s not in out:
            out.append(s)
    return out


def default_terms(treaty_type: str) -> List[str]:
    t = (treaty_type or "").strip().lower()
    if t == "alliance":
        return [
            "mutual military assistance when either signatory is attacked by a third party",
            "no unilateral war declaration against the co-signatory",
            "intelligence and supply cooperation where feasible",
        ]
    if t == "non_aggression":
        return [
            "no offensive military action against the co-signatory's forces or vassal territories",
            "no provisioning of hostile armies for war against the co-signatory",
        ]
    if t == "trade":
        return [
            "unimpeded passage of caravans and agreed tariffs",
            "no seizure of trade goods except under declared blockade of third parties",
            "arbitration envoys for trade disputes",
        ]
    if t == "military_pact":
        return [
            "coordinated campaigns when either signatory is at war and requests aid",
            "no separate peace that abandons the co-signatory without notice",
        ]
    return []


def default_breach_conditions(treaty_type: str) -> dict:
    """Defaults if treaty record omits `breach_conditions`."""
    t = (treaty_type or "").strip().lower()
    base_pen = {
        "trust_loss": 32,
        "reputation_loss": 12,
        "global_order_penalty": 1.5,
        # If true, a breach that does not already imply war can still set `relationships` to war.
        "escalation_war": False,
    }
    if t == "alliance":
        return {
            "violations": [
                {"action": "betray", "against": "treaty_partner", "treaty_types": ["alliance", "military_pact"]},
                {"action": "declare_war", "against": "treaty_partner", "treaty_types": ["alliance"]},
            ],
            "penalties": {**base_pen, "trust_loss": 40, "reputation_loss": 15},
        }
    if t == "military_pact":
        return {
            "violations": [
                {"action": "betray", "against": "treaty_partner", "treaty_types": ["military_pact", "alliance"]},
                {"action": "declare_war", "against": "treaty_partner", "treaty_types": ["military_pact"]},
            ],
            "penalties": {**base_pen, "trust_loss": 35, "reputation_loss": 14},
        }
    if t == "non_aggression":
        return {
            "violations": [
                {"action": "declare_war", "against": "treaty_partner", "treaty_types": ["non_aggression", "trade"]},
                {"action": "raid", "against": "treaty_partner", "treaty_types": ["non_aggression"]},
                {"action": "invade", "against": "treaty_partner", "treaty_types": ["non_aggression"]},
            ],
            "penalties": {**base_pen},
        }
    if t == "trade":
        return {
            "violations": [
                {
                    "action": "block_trade",
                    "against": "treaty_partner",
                    "treaty_types": ["trade", "non_aggression"],
                },
                {"action": "declare_war", "against": "treaty_partner", "treaty_types": ["trade"]},
                {"action": "raid", "against": "treaty_partner", "treaty_types": ["trade", "non_aggression"]},
            ],
            "penalties": {**base_pen, "trust_loss": 28, "escalation_war": False},
        }
    return {
        "violations": [
            {"action": "declare_war", "against": "treaty_partner", "treaty_types": [t]},
        ],
        "penalties": base_pen,
    }


def _merge_breach(treaty: dict) -> dict:
    ttype = (treaty.get("type") or "").strip().lower()
    d = default_breach_conditions(ttype)
    custom = treaty.get("breach_conditions")
    if not isinstance(custom, dict):
        return d
    out = {**d}
    if isinstance(custom.get("violations"), list) and custom["violations"]:
        out["violations"] = custom["violations"]
    if isinstance(custom.get("penalties"), dict):
        out["penalties"] = {**d.get("penalties", {}), **custom["penalties"]}
    return out


def _factions_involved(
    t: dict, violator: str, victim: str, parties: Set[str]
) -> bool:
    return violator in parties and victim in parties


def _location_controller_faction(state: dict, name: str) -> str:
    n = (name or "").strip()
    if not n:
        return ""
    for loc in state.get("locations") or []:
        if (loc.get("name") or "") == n or str(loc.get("id", "")) == n:
            return str(loc.get("controller") or "").strip()
    return ""


def _collect_tick_breach_events(state: dict) -> List[Tuple[str, str, str]]:
    """(kind, violator, victim) — kind in declare_war, betray, raid, invade, block_trade."""
    out: List[Tuple[str, str, str]] = []
    for entry in state.get("decision_log") or []:
        if not isinstance(entry, dict):
            continue
        act = entry.get("action", "")
        f = (entry.get("faction") or "").strip()
        meta = entry.get("meta") or {}
        t = (meta.get("target") or "").strip() if isinstance(meta, dict) else ""
        if act == "declare_war" and f and t:
            out.append(("declare_war", f, t))
        elif act == "betray" and f and t:
            out.append(("betray", f, t))
    for row in state.get("economic_pressure_decisions") or []:
        if not isinstance(row, dict):
            continue
        f = (row.get("faction") or "").strip()
        meta = row.get("meta") or {}
        if not isinstance(meta, dict):
            meta = {}
        act = row.get("action", "")
        if act == "raid_for_provisions":
            tgt = (meta.get("target_faction") or "").strip()
            if f and tgt:
                out.append(("raid", f, tgt))
        elif act in ("disrupt_enemy_routes", "sabotage_routes", "interdict_routes") and f:
            tgt = (meta.get("target_faction") or "").strip()
            if tgt:
                out.append(("block_trade", f, tgt))
        elif act == "invade_for_resources":
            loc = (meta.get("target_location") or meta.get("location") or "").strip()
            tf = (meta.get("target_faction") or "").strip()
            if not tf and loc:
                tf = _location_controller_faction(state, loc)
            if f and tf:
                out.append(("invade", f, tf))
    return out


def _match_violation(
    kind: str, treaty_type: str, vio: dict
) -> bool:
    act = (vio.get("action") or "").strip()
    ttypes = {str(x).lower() for x in (vio.get("treaty_types") or [])}
    if not ttypes and treaty_type:
        ttypes = {treaty_type}
    if treaty_type not in ttypes and ttypes:
        return False
    m = {
        "declare_war": "declare_war",
        "betray": "betray",
        "raid": "raid",
        "invade": "invade",
        "block_trade": "block_trade",
    }
    return m.get(kind) == act


def _apply_penalties(
    state: dict,
    violator: str,
    victim: str,
    pen: dict,
) -> List[dict]:
    """Apply trust + standing; return trust_changes for this breach."""
    trust_loss = int(pen.get("trust_loss", 32) or 32)
    rep = int(pen.get("reputation_loss", 12) or 12)
    gpen = float(pen.get("global_order_penalty", 1.5) or 0.0)
    esc = bool(pen.get("escalation_war", False))

    changes: List[dict] = []
    row = _ensure_pair_row(state, violator, victim)
    before = int(row.get("trust", 50) or 50)
    after = _clamp(before - trust_loss)
    row["trust"] = after
    row["hostility"] = _clamp(int(row.get("hostility", 25) or 25) + min(30, trust_loss // 2))
    if row.get("type") == "alliance":
        row["alliance_level"] = max(0, int(row.get("alliance_level", 0) or 0) - 30)
    changes.append(
        {
            "pair": sorted((violator, victim)),
            "shared_trust_before": before,
            "shared_trust_after": after,
            "delta": after - before,
        }
    )

    standing = state.setdefault("diplomatic_standing", {})
    for fac in (violator,):
        cur = int(standing.get(fac, 50) or 50) if isinstance(standing, dict) else 50
        standing[fac] = _clamp(cur - rep)

    wti = state.setdefault("world_treaty_order", 100.0)
    try:
        wti = float(wti)
    except (TypeError, ValueError):
        wti = 100.0
    state["world_treaty_order"] = max(0.0, min(100.0, wti - gpen))

    rel = _find_rel_row(state, violator, victim)
    at_war = rel and str(rel.get("type", "")).lower() == "war"
    if esc and not at_war:
        r = _ensure_pair_row(state, violator, victim)
        r["type"] = "war"
        r["hostility"] = _clamp(max(int(r.get("hostility", 50) or 50), 78))
        r["alliance_level"] = 0
    elif not esc and not at_war and row.get("type") in ("alliance",):
        row["type"] = "rivalry"

    return changes


def _normalize_treaty_record(t: dict, tick: int) -> dict:
    tid = t.get("treaty_id") or "treaty-unspecified"
    ttype = (t.get("type") or "non_aggression").strip().lower()
    if ttype not in TREATY_TYPES:
        ttype = "non_aggression"
    parts = _participants(t)
    if t.get("start_tick") is None:
        start = int(tick)
    else:
        start = int(t.get("start_tick") or 0)
    dur_raw = t.get("duration", 30)
    duration = max(1, int(dur_raw) if dur_raw is not None else 30)
    terms = t.get("terms")
    if not isinstance(terms, list) or not terms:
        terms = default_terms(ttype)
    bcond = t.get("breach_conditions")
    if not isinstance(bcond, dict) or not bcond:
        bcond = default_breach_conditions(ttype)
    st = t.get("status", "active")
    if st not in ("active", "broken", "expired"):
        st = "active"
    return {
        "treaty_id": str(tid),
        "type": ttype,
        "participants": parts,
        "start_tick": start,
        "duration": duration,
        "terms": terms,
        "breach_conditions": bcond,
        "status": st,
    }


def build_faction_trust_matrix(state: dict) -> Dict[str, Dict[str, int]]:
    """
    Read-only 0–100 trust as adjacency (source of truth: `relationships` bilateral rows).
    When only one trust value exists per pair, it is used for both directions.
    """
    out: Dict[str, Dict[str, int]] = {}
    for row in state.get("relationships") or []:
        if not isinstance(row, dict):
            continue
        a, b = (row.get("faction_a") or ""), (row.get("faction_b") or "")
        if not a or not b:
            continue
        t = int(row.get("trust", 50) or 50)
        out.setdefault(a, {})[b] = t
        out.setdefault(b, {})[a] = t
    return out


def new_treaty_id(seed: str) -> str:
    h = hashlib.sha256(seed.encode("utf-8", errors="replace")).hexdigest()[:10]
    return f"T-{h}"


def _merge_treaty_tick_history(state: dict) -> None:
    tick = int(state.get("tick", 0) or 0)
    out = state.get("treaty_tick_outcomes") or []
    for h in reversed(state.get("tick_history") or []):
        if h.get("tick") == tick:
            h["treaty_tick_outcomes"] = out
            break


def _record_treaty_cause(
    state: dict,
    treaty: dict,
    *,
    decision: str,
    status: str,
    breach_event: dict | None = None,
) -> None:
    tid = str(treaty.get("treaty_id") or "treaty-unspecified")
    ttype = str(treaty.get("type") or "treaty")
    participants = _participants(treaty)
    actor = participants[0] if participants else "Treaty Order"
    affected = [*participants, tid]
    severity = 5
    confidence = 0.92

    if status == "broken":
        breach_event = breach_event or {}
        actor = str(breach_event.get("breacher") or treaty.get("breached_by") or actor)
        victim = str(breach_event.get("victim") or "")
        kind = str(breach_event.get("kind") or "breach")
        pressure = (
            f"treaty breach; type={ttype}; treaty_id={tid}; breach={kind}; "
            f"victim={victim or 'unknown'}; world_treaty_order={state.get('world_treaty_order', 100)}"
        )
        belief = "treaty partners judge the breach through trust and reputation"
        outcome = (
            f"{actor} broke {ttype} treaty {tid}"
            + (f" with {victim}" if victim else "")
            + "; trust and diplomatic standing fell."
        )
        severity = 10
        decision = decision or "break_treaty"
    else:
        pressure = (
            f"treaty duration elapsed; type={ttype}; treaty_id={tid}; "
            f"participants={', '.join(participants)}"
        )
        belief = "formal obligations end when duration expires"
        outcome = f"{ttype} treaty {tid} expired between {', '.join(participants) or 'unknown parties'}."
        decision = decision or "expire_treaty"

    record_cause(
        state,
        domain="treaty",
        actor=actor,
        pressure=pressure,
        belief=belief,
        decision=decision,
        outcome=outcome,
        affected=affected,
        severity=severity,
        confidence=confidence,
        source="treaty_system",
    )


def run_treaty_system(state: dict) -> None:
    """
    Update treaty statuses, expire old treaties, apply breach consequences.
    Sets `treaty_tick_outcomes` (and patches tick_history) with records:
      { treaty_id, factions, status, trust_changes }.
    """
    tick = int(state.get("tick", 0) or 0)
    if state.get("_treaty_system_tick") == tick:
        return
    state["_treaty_system_tick"] = tick

    state.setdefault("treaties", [])
    state.setdefault("diplomatic_standing", {})
    if "world_treaty_order" not in state or state.get("world_treaty_order") is None:
        state["world_treaty_order"] = 100.0
    if not isinstance(state.get("diplomatic_standing"), dict):
        state["diplomatic_standing"] = {}

    treaties: List[dict] = []
    for t in state.get("treaties") or []:
        if not isinstance(t, dict):
            continue
        nt = {**_normalize_treaty_record(t, tick), "breach_conditions": _merge_breach(t)}
        if not t.get("treaty_id") or str(nt.get("treaty_id")) == "treaty-unspecified":
            p = _participants(nt)
            nt["treaty_id"] = new_treaty_id(f"{tick}|{nt.get('type')}|{','.join(p)}")
        # preserve broken_tick / status from storage
        if t.get("broken_tick") is not None:
            nt["broken_tick"] = t.get("broken_tick")
        if t.get("breached_by"):
            nt["breached_by"] = t.get("breached_by")
        if t.get("status") in ("broken", "expired", "active"):
            nt["status"] = t.get("status")
        treaties.append(nt)
    state["treaties"] = treaties

    outcomes: List[dict] = []
    breach_events = _collect_tick_breach_events(state)

    for t in list(state.get("treaties") or []):
        if not isinstance(t, dict):
            continue
        tid = t.get("treaty_id", "")
        ttype = (t.get("type") or "").lower()
        st = t.get("status", "active")
        if st != "active":
            continue
        start = int(t.get("start_tick", 0) or 0)
        dur = int(t.get("duration", 0) or 0)
        if tick >= start + max(0, dur):
            t["status"] = "expired"
            outcomes.append(
                {
                    "treaty_id": tid,
                    "factions": _participants(t),
                    "status": "expired",
                    "trust_changes": [],
                }
            )
            _record_treaty_cause(state, t, decision="expire_treaty", status="expired")
            continue

        parts = set(_participants(t))
        bc = t.get("breach_conditions")
        if not isinstance(bc, dict):
            bc = default_breach_conditions(ttype)
        violations = bc.get("violations") or default_breach_conditions(ttype).get("violations", [])
        default_pen = default_breach_conditions(ttype).get("penalties") or {}
        merged = _merge_breach(t)
        pen: Dict[str, Any] = {**default_pen, **(merged.get("penalties") or {})}
        if isinstance(t.get("breach_conditions"), dict) and isinstance(t["breach_conditions"].get("penalties"), dict):
            pen = {**pen, **t["breach_conditions"]["penalties"]}

        for event in breach_events:
            k, f1, f2 = event
            if not _factions_involved(t, f1, f2, parts):
                continue
            matched = any(_match_violation(k, ttype, v) for v in violations if isinstance(v, dict))
            if not matched:
                continue
            t["status"] = "broken"
            t["broken_tick"] = tick
            t["breached_by"] = f1
            tc = _apply_penalties(state, f1, f2, pen)
            if tc:
                tc[0] = {
                    **tc[0],
                    "breach_event": {"kind": k, "breacher": f1, "victim": f2, "treaty_type": ttype},
                }
            outcomes.append(
                {
                    "treaty_id": tid,
                    "factions": sorted(parts),
                    "status": "broken",
                    "trust_changes": tc,
                }
            )
            breach_event = tc[0].get("breach_event") if tc and isinstance(tc[0], dict) else None
            _record_treaty_cause(
                state,
                t,
                decision="break_treaty",
                status="broken",
                breach_event=breach_event,
            )
            break

    state["treaty_tick_outcomes"] = outcomes
    _merge_treaty_tick_history(state)


__all__ = [
    "run_treaty_system",
    "default_terms",
    "default_breach_conditions",
    "new_treaty_id",
    "build_faction_trust_matrix",
    "TREATY_TYPES",
]
