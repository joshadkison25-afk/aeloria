"""
Tributary relationships: resource flows, resentment, overextension, breaks, AI hints.

State:
  tributary_pacts      — list of active tribute definitions
  tributary_resentment — { subordinate_faction: 0–100 }
Output per tick (tributary_report):
  { tributaries: [], payments: [], tension_level: 0–100 }
"""

from __future__ import annotations

import hashlib
import random
from typing import Dict, List, Optional

from engine.causality import record_cause

__all__ = [
    "run_tributary_system",
    "pact_id_for",
]

_TRIBUTE_TYPES = frozenset({"gold", "grain", "resources", "mixed", "timber", "iron"})


def _clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


def pact_id_for(dom: str, sub: str, start_tick: int) -> str:
    s = f"{start_tick}|{dom}|{sub}"
    h = hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()[:10]
    return f"TRB-{h}"


def _find_rel(state: dict, a: str, b: str) -> Optional[dict]:
    key = tuple(sorted((a.strip(), b.strip())))
    for row in state.get("relationships") or []:
        if not isinstance(row, dict):
            continue
        ra, rb = (row.get("faction_a") or ""), (row.get("faction_b") or "")
        if tuple(sorted((ra, rb))) == key:
            return row
    return None


def _ensure_rel(state: dict, a: str, b: str) -> dict:
    r = _find_rel(state, a, b)
    if r:
        return r
    row = {
        "faction_a": a,
        "faction_b": b,
        "type": "neutral",
        "intensity": 50,
        "trust": 50,
        "hostility": 20,
        "alliance_level": 0,
    }
    state.setdefault("relationships", []).append(row)
    return row


def _econ_row(state: dict, fid: str) -> Optional[dict]:
    for r in state.get("faction_economy") or []:
        if (r.get("faction_id") or r.get("faction")) == fid:
            return r
    return None


def _stock(row: dict, res: str) -> float:
    if not row:
        return 0.0
    m = (row.get("resources") or {}).get(res) or {}
    return max(0.0, float(m.get("stockpile", 0) or 0))


def _set_stock(row: dict, res: str, val: float) -> None:
    rmap = row.setdefault("resources", {})
    rmap.setdefault(
        res,
        {"stockpile": 0, "consumption": 0, "production": 0, "storage_capacity": 5000},
    )
    cap = int((rmap[res] or {}).get("storage_capacity", 5000) or 5000)
    rmap[res]["stockpile"] = int(_clamp(val, 0, float(max(cap, int(val) + 1))))


def _add_stock(row: dict, res: str, delta: float) -> float:
    cur = _stock(row, res)
    nv = cur + delta
    _set_stock(row, res, nv)
    return float(nv - cur)


def _faction_power_entry(state: dict, fid: str) -> Optional[dict]:
    for p in state.get("faction_power_state") or []:
        if p.get("faction") == fid:
            return p
    return None


def _bump_power(state: dict, fid: str, **kwargs: float) -> None:
    p = _faction_power_entry(state, fid)
    if not p:
        return
    for k, dv in kwargs.items():
        if k in p:
            p[k] = int(_clamp(float(p.get(k, 50) or 50) + dv, 0, 100))


def _normalize_pact(p: dict, tick: int) -> dict:
    dom = (p.get("dominant_faction") or p.get("dominant") or "").strip()
    sub = (p.get("subordinate_faction") or p.get("subordinate") or "").strip()
    if not dom or not sub or dom == sub:
        return {}
    st = p.get("start_tick")
    if st is None:
        start = int(tick)
    else:
        start = int(st)
    dur = p.get("duration", 60)
    duration = max(1, int(dur) if dur is not None else 60)
    ttype = (p.get("tribute_type") or "gold").strip().lower()
    if ttype not in _TRIBUTE_TYPES and ttype != "mixed":
        ttype = "gold"
    pay = max(0, int(float(p.get("payment_per_tick", 0) or 0)))
    pid = (p.get("tributary_id") or p.get("pact_id") or "").strip() or pact_id_for(dom, sub, start)
    status = p.get("status", "active")
    if status not in ("active", "broken", "expired", "suspended"):
        status = "active"
    return {
        "tributary_id": pid,
        "dominant_faction": dom,
        "subordinate_faction": sub,
        "tribute_type": ttype,
        "payment_per_tick": pay,
        "start_tick": start,
        "duration": duration,
        "status": status,
    }


def _payment_split(ttype: str, payment: int) -> Dict[str, float]:
    p = max(0, int(payment))
    if ttype == "gold":
        return {"gold": float(p)}
    if ttype == "grain":
        return {"grain": float(p)}
    if ttype in ("iron", "timber"):
        return {ttype: float(p)}
    if ttype == "resources":
        g = p // 3
        return {"iron": g, "timber": g, "grain": p - 2 * g}
    if ttype == "mixed":
        return {
            "gold": float(p // 3),
            "grain": float(p // 3),
            "iron": float(max(0, p - 2 * (p // 3))),
        }
    return {"gold": float(p)}


def _execute_tribute(
    state: dict, dom: str, sub: str, amounts: Dict[str, float]
) -> Dict[str, float]:
    """Move resources sub -> dom, capped by sub stock. Returns actually moved per res."""
    sub_r = _econ_row(state, sub)
    dom_r = _econ_row(state, dom)
    if not sub_r or not dom_r:
        return {}
    moved: Dict[str, float] = {}
    for res, want in amounts.items():
        w = max(0.0, float(want))
        if w < 0.1:
            continue
        have = _stock(sub_r, res)
        m = min(have, w)
        if m < 0.1:
            continue
        _add_stock(sub_r, res, -m)
        _add_stock(dom_r, res, m)
        moved[res] = moved.get(res, 0) + m
    return moved


def _on_break_tribute(
    state: dict, dom: str, sub: str, reason: str, may_war: bool
) -> None:
    r = _ensure_rel(state, dom, sub)
    r["trust"] = 5
    r["hostility"] = 88
    r["alliance_level"] = 0
    if r.get("type") == "alliance":
        r["type"] = "rivalry"
    if may_war and random.random() < 0.45:
        r["type"] = "war"
        r["hostility"] = max(int(r.get("hostility", 80) or 80), 90)
    state.setdefault("tributary_resentment", {})[sub] = min(100, float(
        (state.get("tributary_resentment") or {}).get(sub, 0) or 0
    ) + 12.0)
    if reason:
        log = state.setdefault("tributary_break_log", [])
    log.append(
        {
            "tick": int(state.get("tick", 0) or 0),
            "dominant_faction": dom,
            "subordinate_faction": sub,
            "reason": reason,
        }
    )
    state["tributary_break_log"] = log[-20:]


def _tension(
    pacts: List[dict], resentment: Dict[str, float], overext: float
) -> float:
    rvals = [float(x) for x in resentment.values()] if resentment else [0.0]
    ravg = sum(rvals) / max(1, len(rvals)) if rvals else 0.0
    near = len([x for x in rvals if x > 70])
    t = 0.35 * ravg + 0.2 * min(100, len(pacts) * 7) + 0.35 * overext + near * 4
    return float(_clamp(t, 0, 100))


def _at_war_simple(a: str, b: str, state: dict) -> bool:
    for r in state.get("relationships") or []:
        if not isinstance(r, dict) or r.get("type") != "war":
            continue
        fa, fb = (r.get("faction_a") or ""), (r.get("faction_b") or "")
        if {fa, fb} == {a, b}:
            return True
    return False


def _ai_hints(state: dict) -> Dict[str, List[dict]]:
    """Lightweight heuristics for who might seek or demand tribute (for narrative/LLM)."""
    protect: List[dict] = []
    demand: List[dict] = []
    rebel: List[dict] = []
    seen_p: set = set()
    seen_d: set = set()
    for p in state.get("faction_power_state") or []:
        fac = p.get("faction")
        if not fac:
            continue
        mil = int(p.get("militaryPower", 50) or 50)
        pol = int(p.get("politicalInfluence", 50) or 50)
        for q in state.get("faction_power_state") or []:
            other = q.get("faction")
            if not other or other == fac:
                continue
            mo = int(q.get("militaryPower", 50) or 50)
            if mil < 36 and pol < 45 and mo > 62 and not _at_war_simple(fac, other, state):
                k = (fac, other)
                if k not in seen_p:
                    seen_p.add(k)
                    protect.append(
                        {
                            "subordinate_faction": fac,
                            "potential_dominant": other,
                            "score": (62 - mil) * 0.3 + (mo - 50) * 0.1,
                        }
                    )
            if (
                mo > 65
                and mil < 45
                and mo > mil + 18
                and not _at_war_simple(fac, other, state)
            ):
                kd = (other, fac)
                if kd not in seen_d:
                    seen_d.add(kd)
                    demand.append(
                        {
                            "dominant_faction": other,
                            "target_subordinate": fac,
                            "score": (mo - mil) * 0.12,
                        }
                    )
    for p in state.get("tributary_pacts") or []:
        if not isinstance(p, dict) or p.get("status") != "active":
            continue
        sub = p.get("subordinate_faction")
        dom = p.get("dominant_faction")
        if not sub or not dom:
            continue
        rs = float((state.get("tributary_resentment") or {}).get(sub, 0) or 0)
        dm = int((_faction_power_entry(state, dom) or {}).get("militaryPower", 50) or 50)
        if rs > 55 and dm < 38:
            rebel.append(
                {
                    "subordinate_faction": sub,
                    "dominant_faction": dom,
                    "resentment": round(rs, 1),
                    "dominant_military": dm,
                }
            )
    return {
        "weak_seeks_protection": sorted(protect, key=lambda x: -x.get("score", 0))[:8],
        "strong_may_demand_tribute": sorted(demand, key=lambda x: -x.get("score", 0))[:8],
        "opportunistic_rebellion_risk": rebel[:8],
    }


def _merge_tributary_history(state: dict) -> None:
    rep = state.get("tributary_report") or {}
    t = int(state.get("tick", 0) or 0)
    for h in reversed(state.get("tick_history") or []):
        if h.get("tick") == t:
            h["tributary_report"] = rep
            break


def _record_tributary_cause(
    state: dict,
    pact: dict,
    *,
    decision: str,
    outcome: str,
    severity: int,
    reason: str = "",
    moved: Dict[str, float] | None = None,
) -> None:
    dom = str(pact.get("dominant_faction") or "")
    sub = str(pact.get("subordinate_faction") or "")
    tid = str(pact.get("tributary_id") or "tributary-unspecified")
    ttype = str(pact.get("tribute_type") or "tribute")
    resentment = float((state.get("tributary_resentment") or {}).get(sub, 0) or 0)
    actor = sub if decision == "break_tributary_pact" else dom
    affected = [item for item in [dom, sub, tid] if item]

    if decision == "pay_tribute":
        moved_text = ", ".join(f"{res}={round(amount, 2)}" for res, amount in (moved or {}).items())
        pressure = (
            f"tributary obligation; type={ttype}; payment_per_tick={pact.get('payment_per_tick', 0)}; "
            f"resentment={round(resentment, 2)}"
        )
        belief = "tribute obligations preserve protection at the cost of resentment"
        outcome = outcome or f"{sub} paid tribute to {dom}: {moved_text or 'no resources moved'}."
    elif decision == "break_tributary_pact":
        pressure = (
            f"tributary burden/default; type={ttype}; reason={reason or 'unknown'}; "
            f"resentment={round(resentment, 2)}"
        )
        belief = "tribute burden outweighs submission"
        outcome = outcome or f"{sub} broke tributary pact {tid} with {dom}."
    else:
        pressure = (
            f"tributary duration elapsed; type={ttype}; tributary_id={tid}; "
            f"dominant={dom}; subordinate={sub}"
        )
        belief = "tribute obligations end when the pact duration expires"
        outcome = outcome or f"Tributary pact {tid} between {sub} and {dom} expired."

    record_cause(
        state,
        domain="tributary",
        actor=actor or "Tributary Order",
        pressure=pressure,
        belief=belief,
        decision=decision,
        outcome=outcome,
        affected=affected,
        severity=severity,
        confidence=0.88,
        source="tributary_system",
    )


def run_tributary_system(state: dict) -> None:
    """
    Process tribute payments, apply political/economic effects, handle breaks, AI hints.
    """
    tick = int(state.get("tick", 0) or 0)
    if state.get("_tributary_system_tick") == tick:
        return
    state["_tributary_system_tick"] = tick

    state.setdefault("tributary_pacts", [])
    state.setdefault("tributary_resentment", {})
    if not isinstance(state.get("tributary_resentment"), dict):
        state["tributary_resentment"] = {}
    ress: Dict[str, float] = state["tributary_resentment"]

    normalized: List[dict] = []
    for raw in list(state.get("tributary_pacts") or []):
        if not isinstance(raw, dict):
            continue
        n = _normalize_pact(raw, tick)
        if n:
            for k, v in raw.items():
                if k not in n and not k.startswith("_"):
                    n[k] = v
            if raw.get("status") in ("broken", "expired", "suspended"):
                n["status"] = raw.get("status")
            normalized.append(n)
    state["tributary_pacts"] = normalized

    payments: List[dict] = []
    active_rows: List[dict] = []
    overext = 0.0

    for p in list(normalized):
        if p.get("status") != "active":
            continue
        dom, sub = p.get("dominant_faction"), p.get("subordinate_faction")
        st, dur = int(p.get("start_tick", 0) or 0), int(p.get("duration", 1) or 1)
        if tick >= st + dur:
            p["status"] = "expired"
            _record_tributary_cause(
                state,
                p,
                decision="expire_tributary_pact",
                outcome=f"Tributary pact {p.get('tributary_id')} between {sub} and {dom} expired.",
                severity=5,
                reason="duration_elapsed",
            )
            continue
        pay_amt = int(p.get("payment_per_tick", 0) or 0)
        ttype = p.get("tribute_type", "gold")
        amounts = _payment_split(str(ttype), pay_amt)
        moved = _execute_tribute(state, str(dom), str(sub), amounts)
        if pay_amt > 0 and sum(moved.values()) < pay_amt * 0.15 and pay_amt > 5:
            _on_break_tribute(state, str(dom), str(sub), "payment_default", may_war=True)
            p["status"] = "broken"
            _record_tributary_cause(
                state,
                p,
                decision="break_tributary_pact",
                outcome=f"{sub} defaulted on tribute to {dom}; the tributary pact broke.",
                severity=12,
                reason="payment_default",
            )
            continue
        ress[sub] = ress.get(sub, 0.0) + 0.22 + (pay_amt * 0.0008) * 0.15
        ress[sub] = float(_clamp(ress[sub], 0, 100))

        _bump_power(state, str(sub), militaryPower=-0.35, politicalInfluence=0.4)
        _bump_power(state, str(dom), politicalInfluence=0.35, militaryPower=0.05)
        dcount = len(
            [x for x in normalized if x.get("status") == "active" and x.get("dominant_faction") == dom]
        )
        dom_m = int((_faction_power_entry(state, str(dom)) or {}).get("militaryPower", 50) or 50)
        overext = max(overext, dcount * 9.0 + max(0, 45 - dom_m) * 0.4)
        _bump_power(state, str(dom), politicalInfluence=-0.1 * min(3, dcount) * 0.15)

        _stab_bump = 0
        for loc in state.get("locations") or []:
            if not isinstance(loc, dict):
                continue
            if loc.get("controller") != sub:
                continue
            if int(loc.get("stability", 50) or 50) >= 92:
                continue
            loc["stability"] = int(_clamp(int(loc.get("stability", 50) or 50) + 1, 0, 100))
            if pay_amt > 15:
                loc["stability"] = int(_clamp(loc["stability"] + 1, 0, 100))
            _stab_bump += 1
            if _stab_bump >= 2:
                break

        rr = ress.get(sub, 0.0)
        if rr > 88 and random.random() < 0.08 + (rr - 88) * 0.01:
            _on_break_tribute(state, str(dom), str(sub), "resentment_breach", may_war=True)
            p["status"] = "broken"
            _record_tributary_cause(
                state,
                p,
                decision="break_tributary_pact",
                outcome=f"{sub} rejected tributary submission to {dom} as resentment boiled over.",
                severity=13,
                reason="resentment_breach",
            )
            continue
        if rr > 52 and dom_m < 34 and random.random() < 0.12:
            _on_break_tribute(state, str(dom), str(sub), "opportunistic_rebellion", may_war=True)
            p["status"] = "broken"
            _record_tributary_cause(
                state,
                p,
                decision="break_tributary_pact",
                outcome=f"{sub} rebelled against {dom}'s tributary rule while the dominant power was weak.",
                severity=13,
                reason="opportunistic_rebellion",
            )
            continue

        rel = _ensure_rel(state, str(dom), str(sub))
        rel["trust"] = int(_clamp(58.0 - rr * 0.28, 5, 75))
        rel["hostility"] = int(
            _clamp(18.0 + rr * 0.35 + (5 if pay_amt > 25 else 0), 0, 90)
        )

        payments.append(
            {
                "tributary_id": p.get("tributary_id"),
                "dominant_faction": dom,
                "subordinate_faction": sub,
                "resources_moved": {k: round(v, 2) for k, v in moved.items()},
                "tribute_type": ttype,
            }
        )
        if moved:
            moved_text = ", ".join(f"{res} {round(amount, 2)}" for res, amount in moved.items())
            _record_tributary_cause(
                state,
                p,
                decision="pay_tribute",
                outcome=f"{sub} paid tribute to {dom}: {moved_text}.",
                severity=4,
                moved=moved,
            )
        active_rows.append(
            {
                **p,
                "overextension_note": f"dominant_serves_{dcount}_tributaries",
                "resentment": round(ress.get(sub, 0.0), 2),
            }
        )

    overext = float(_clamp(overext, 0, 100))
    t_level = _tension([x for x in active_rows if x], ress, overext)
    rep = {
        "tributaries": active_rows,
        "payments": payments,
        "tension_level": round(t_level, 1),
    }
    rep["overextension_index"] = round(overext, 1)
    rep["ai_hints"] = _ai_hints(state)
    state["tributary_report"] = rep
    _merge_tributary_history(state)
