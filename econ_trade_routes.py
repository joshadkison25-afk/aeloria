"""
Inter-faction economic trade routes: land vs sea, capacity, risk, flows, and disruption.

Pulled in after P/C, before the world market. Exposes state['economic_trade_routes'] and
state['economic_disruption_price_mult'] (applied to market prices).
"""

from __future__ import annotations

import hashlib
import random
from typing import Any, Dict, List, Optional, Set, Tuple

from axiom.engine.causality import record_cause

# Keep independent of import order relative to economy_simulation
CORE_RES: Tuple[str, ...] = ("grain", "iron", "timber", "gold")

TIDEFALL = "Tidefall"
DREADWIND = "Dreadwind Isles"

LAND_CAP = (40, 120)
LAND_RISK = (0.02, 0.06)
SEA_CAP = (90, 220)
SEA_RISK = (0.04, 0.12)

PIRACY_RISK_BONUS = 0.05  # third-party sea routes
TIDEFALL_SEA_CAP_MULT = 1.22
TIDEFALL_SEA_RISK_MULT = 0.72
MAX_ROUTE_SLOTS = 40


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _route_key(origin: str, dest: str, kind: str) -> str:
    raw = f"{kind}|{origin}|{dest}"
    h = hashlib.md5(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    return f"{kind}-{h}"


def _relationship_data(a: str, b: str, state: dict) -> Optional[dict]:
    """Read edge data for (a, b) for either list- or dict-shaped `relationships`."""
    rels = state.get("relationships", [])
    if isinstance(rels, list):
        for rel in rels or []:
            if not isinstance(rel, dict):
                continue
            fa, fb = rel.get("faction_a", ""), rel.get("faction_b", "")
            if {a, b} == {fa, fb}:
                return rel
        return None
    if isinstance(rels, dict):
        side = (rels.get(a) or {}).get(b)
        if not isinstance(side, dict):
            side = (rels.get(b) or {}).get(a)
        if not isinstance(side, dict):
            return None
        st = str(side.get("type") or side.get("status", "neutral") or "neutral").lower()
        return {
            "type": st,
            "trust": int(side.get("trust", side.get("score", 50)) or 50),
            "hostility": int(side.get("hostility", 20)),
        }
    return None


def _is_at_war(a: str, b: str, state: dict) -> bool:
    rels = state.get("relationships", [])
    if isinstance(rels, list):
        for rel in rels or []:
            if not isinstance(rel, dict) or rel.get("type") != "war":
                continue
            fa, fb = rel.get("faction_a", ""), rel.get("faction_b", "")
            if {a, b} == {fa, fb}:
                return True
        return False
    if isinstance(rels, dict):
        s = (rels.get(a) or {}).get(b) or (rels.get(b) or {}).get(a)
        if not isinstance(s, dict):
            return False
        st = str(s.get("status", s.get("type", ""))).lower()
        return st == "war"
    return False


def _ally_weight(a: str, b: str, state: dict) -> int:
    rel = _relationship_data(a, b, state)
    if not rel:
        return 30
    t = (rel.get("type") or "").lower()
    if t in ("alliance", "allied"):
        return 100
    if t in ("neutral", "rivalry"):
        return 40 + int(rel.get("trust", 30)) // 2
    return 30


def _maritime_affinity(f: str, state: dict) -> bool:
    for loc in state.get("locations", []) or []:
        if loc.get("controller") != f:
            continue
        rt = str(loc.get("region_type", "")).lower()
        if rt in ("port", "coast", "isles", "archipelago", "island", "bays", "bays_", "sea", "headlands"):
            return True
    return f in (TIDEFALL, DREADWIND)


def _route_kind_for_pair(fa: str, fb: str, state: dict) -> str:
    if _maritime_affinity(fa, state) and _maritime_affinity(fb, state) and (fa, fb) != (DREADWIND, DREADWIND):
        return "sea" if (TIDEFALL in (fa, fb) or DREADWIND in (fa, fb) or random.random() < 0.55) else "land"
    return "land"


def _overstock(cons: float, stock: float) -> float:
    buffer = max(5.0, cons * 12.0)
    return max(0.0, stock - buffer)


def _need(cons: float, stock: float) -> float:
    if cons < 0.05:
        return 0.0
    target = 0.55 * cons
    if stock >= target:
        return 0.0
    return min(cons * 0.35, max(0.0, target * 0.9 - stock * 0.2))


def _parse_route(prev: dict) -> dict:
    o = (prev or {}).get("origin", "")
    d = (prev or {}).get("destination", "")
    kind = (prev or {}).get("kind", "land")
    if not o or not d or o == d:
        return {}
    return {
        "id": (prev or {}).get("id") or _route_key(o, d, kind),
        "origin": o,
        "destination": d,
        "kind": str(kind) if str(kind) in ("land", "sea") else "land",
        "capacity": int(_clamp(float((prev or {}).get("capacity", 0)), 10, 400)),
        "risk": _clamp(float((prev or {}).get("risk", 0.05)), 0.01, 0.5),
        "status": (prev or {}).get("status", "active") if (prev or {}).get("status") in ("active", "disrupted") else "active",
        "disrupted_remaining": int(max(0, int((prev or {}).get("disrupted_remaining", 0)))),
        "profit_ema": float((prev or {}).get("profit_ema", 0.0) or 0.0),
        "age_ticks": int((prev or {}).get("age_ticks", 0) or 0),
    }


def _effective_risk_sea_adj(origin: str, dest: str, base_r: float) -> float:
    r = base_r
    if TIDEFALL in (origin, dest) and (origin, dest) != (DREADWIND, DREADWIND):
        r *= TIDEFALL_SEA_RISK_MULT
    if DREADWIND not in (origin, dest):
        r = _clamp(r + PIRACY_RISK_BONUS, 0.01, 0.6)
    return r


def _sea_capacity_adj(origin: str, dest: str, cap: int) -> int:
    if TIDEFALL in (origin, dest):
        return int(min(400, cap * TIDEFALL_SEA_CAP_MULT + 1))
    return cap


def _new_route(origin: str, dest: str, kind: str) -> dict:
    if kind == "sea":
        c = random.uniform(SEA_CAP[0], SEA_CAP[1])
        rk = random.uniform(SEA_RISK[0], SEA_RISK[1])
    else:
        c = random.uniform(LAND_CAP[0], LAND_CAP[1])
        rk = random.uniform(LAND_RISK[0], LAND_RISK[1])
    c = int(_clamp(c, 15, 350))
    rk = _clamp(rk, 0.01, 0.4)
    if kind == "sea":
        c = _sea_capacity_adj(origin, dest, c)
        rk = _effective_risk_sea_adj(origin, dest, rk)
    return {
        "id": _route_key(origin, dest, kind),
        "origin": origin,
        "destination": dest,
        "kind": kind,
        "capacity": c,
        "risk": round(rk, 4),
        "status": "active",
        "disrupted_remaining": 0,
        "profit_ema": 0.0,
        "age_ticks": 0,
    }


def _iter_peaceful_pairs(state: dict) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    rels = state.get("relationships", [])
    if isinstance(rels, list):
        for rel in rels or []:
            if not isinstance(rel, dict) or (rel.get("type") or "").lower() == "war":
                continue
            fa, fb = rel.get("faction_a", ""), rel.get("faction_b", "")
            if fa and fb and fa != fb and not _is_at_war(fa, fb, state):
                out.append((fa, fb))
        return out
    if isinstance(rels, dict):
        for fa, sub in (rels or {}).items():
            if not isinstance(sub, dict):
                continue
            for fb, side in sub.items():
                if not fa or not fb or fa == fb:
                    continue
                if not isinstance(side, dict):
                    continue
                st = str(side.get("type") or side.get("status", "")).lower()
                if st == "war" or _is_at_war(fa, fb, state):
                    continue
                out.append((fa, fb))
    return out


def _seed_routes(
    state: dict,
    seen: Set[Tuple[str, str, str]],
    routes: List[dict],
) -> None:
    for fa, fb in _iter_peaceful_pairs(state):
        for o, d in ((fa, fb), (fb, fa)):
            kind = _route_kind_for_pair(o, d, state)
            k = (o, d, kind)
            if k in seen:
                continue
            seen.add(k)
            routes.append(_new_route(o, d, kind))
            if len(routes) >= MAX_ROUTE_SLOTS:
                return


def _try_spawn_stress_routes(
    state: dict,
    factions: List[str],
    existing: Set[Tuple[str, str, str]],
) -> List[dict]:
    new_r: List[dict] = []
    rows = {r.get("faction_id") or r.get("faction"): r for r in (state.get("faction_economy") or [])}
    s_tot: Dict[str, float] = {k: 0.0 for k in CORE_RES}
    d_tot: Dict[str, float] = {k: 0.0 for k in CORE_RES}
    for fid in factions:
        for k in CORE_RES:
            m = (rows.get(fid) or {}).get("resources", {}).get(k) or {}
            s_tot[k] += max(0, float(m.get("stockpile", 0) or 0))
            d_tot[k] += max(0, float(m.get("consumption", 0) or 0))
    for k in ("grain", "iron", "timber"):
        s = max(1.0, s_tot.get(k, 0))
        dem = max(0.0, d_tot.get(k, 0))
        stress = dem / s
        if stress < 1.12:
            continue
        surplus_f = max(factions, key=lambda f: (rows.get(f) or {}).get("resources", {}).get(k, {}).get("stockpile", 0) or 0)
        deficit_f = min(factions, key=lambda f: (rows.get(f) or {}).get("resources", {}).get(k, {}).get("stockpile", 999999) or 0)
        if surplus_f == deficit_f or _is_at_war(surplus_f, deficit_f, state):
            continue
        kind = _route_kind_for_pair(surplus_f, deficit_f, state)
        key = (surplus_f, deficit_f, kind)
        if key in existing or (deficit_f, surplus_f, kind) in existing:
            continue
        r = _new_route(surplus_f, deficit_f, kind)
        new_r.append(r)
        existing.add(key)
    return new_r


def _flow_one_route(
    state: dict,
    route: dict,
) -> Dict[str, float]:
    """Move resources from origin to destination for one route; return flow by resource (total under capacity)."""
    o, d = route.get("origin"), route.get("destination")
    o_row = {r.get("faction_id") or r.get("faction"): r for r in (state.get("faction_economy") or [])}
    if o not in o_row or d not in o_row:
        return {x: 0.0 for x in CORE_RES}
    notrade: Set[str] = set(
        (state.get("siege_warfare") or {}).get("no_external_trade_factions")
        or state.get("besieged_factions")
        or []
    )
    if d in notrade:
        return {x: 0.0 for x in CORE_RES}
    origin_map = o_row[o].setdefault("resources", {})
    dest_map = o_row[d].setdefault("resources", {})
    for x in CORE_RES:
        for z in (origin_map, dest_map):
            z.setdefault(
                x,
                {
                    "stockpile": 0,
                    "consumption": 0.0,
                    "storage_capacity": 5000,
                    "production": 0.0,
                },
            )
    cap_left = int(route.get("capacity", 0) or 0)
    if str(route.get("kind")) == "sea":
        bcm = (state.get("siege_warfare") or {}).get("blockade_cap_mult_by_faction") or {}
        fmul = min(float(bcm.get(o, 1.0) or 1.0), float(bcm.get(d, 1.0) or 1.0))
        cap_left = int(cap_left * fmul)
    flow: Dict[str, float] = {x: 0.0 for x in CORE_RES}
    if cap_left < 1:
        return flow

    for res in CORE_RES:
        if cap_left < 0.1:
            break
        oc = max(0, float((origin_map[res] or {}).get("consumption", 0) or 0))
        ost = max(0, float((origin_map[res] or {}).get("stockpile", 0) or 0))
        dcap = int(max(50, (dest_map[res] or {}).get("storage_capacity", 5000) or 5000))
        dst = max(0, float((dest_map[res] or {}).get("stockpile", 0) or 0))
        dc = max(0, float((dest_map[res] or {}).get("consumption", 0) or 0))
        can_send = _overstock(oc, ost)
        need = _need(dc, dst)
        if can_send < 0.1 or need < 0.1:
            continue
        t = int(min(cap_left, can_send * 0.35, need, dcap - dst - 0.1))
        t = max(0, t)
        if t <= 0:
            continue
        origin_map[res]["stockpile"] = int(max(0, ost - t))
        dest_map[res]["stockpile"] = int(min(dcap, dst + t))
        flow[res] += t
        cap_left -= t
    return flow


def _instability_touched(state: dict, fids: Set[str], bump: int) -> None:
    for row in state.get("population_state", []) or []:
        reg = (row.get("region") or row.get("culture", "")) or ""
        for f in fids:
            if f in str(row.get("culture", "")) or f in str(reg):
                p = int(row.get("pressure", 50) or 50)
                row["pressure"] = int(_clamp(p + bump, 0, 100))
                break


def _record_trade_disruption_cause(state: dict, route: dict) -> None:
    origin = str(route.get("origin") or "Unknown origin")
    destination = str(route.get("destination") or "Unknown destination")
    route_id = str(route.get("id") or _route_key(origin, destination, str(route.get("kind", "land"))))
    kind = str(route.get("kind") or "land")
    risk = round(float(route.get("risk", 0.0) or 0.0), 3)
    capacity = int(route.get("capacity", 0) or 0)
    remaining = int(route.get("disrupted_remaining", 0) or 0)
    piracy = bool(route.get("piracy_flag"))
    cause = "piracy" if piracy else "route instability"
    severity = 10 if piracy else (8 if kind == "sea" else 7)

    record_cause(
        state,
        domain="economy",
        actor=origin,
        pressure=(
            f"trade route disruption; route_id={route_id}; kind={kind}; "
            f"risk={risk}; capacity={capacity}; disrupted_remaining={remaining}; cause={cause}"
        ),
        belief="trade networks are vulnerable to piracy, blockade pressure, and local instability",
        decision="disrupt_trade_route",
        outcome=f"{kind.title()} trade route {route_id} from {origin} to {destination} was disrupted by {cause}.",
        affected=[origin, destination, route_id],
        hidden=None,
        severity=severity,
        confidence=0.82,
        source="econ_trade_routes",
    )


def process_economic_trade_routes(state: dict, prev_state: Optional[dict] = None) -> None:
    prev = prev_state or {}
    from economy_simulation import list_faction_ids  # type: ignore

    factions = list_faction_ids(state)[:20]
    if not factions:
        return

    prev_routes: Dict[str, dict] = {r.get("id", ""): r for r in (prev.get("economic_trade_routes") or []) if r.get("id")}
    cur_in = {r.get("id", ""): r for r in (state.get("economic_trade_routes") or []) if r.get("id")}

    routes: List[dict] = []
    seen: Set[Tuple[str, str, str]] = set()
    for rid, r in {**prev_routes, **cur_in}.items():
        p = _parse_route(r)
        if not p:
            continue
        k = (p["origin"], p["destination"], p["kind"])
        if k in seen or _is_at_war(p["origin"], p["destination"], state):
            continue
        seen.add(k)
        routes.append(p)
        if len(routes) >= MAX_ROUTE_SLOTS:
            break

    if len(routes) < 8 and factions:
        _seed_routes(state, seen, routes)

    for s in _try_spawn_stress_routes(state, factions, seen):
        if any(
            (r.get("origin"), r.get("destination"), r.get("kind")) == (s["origin"], s["destination"], s["kind"])
            for r in routes
        ):
            continue
        k = (s["origin"], s["destination"], s["kind"])
        if k in seen or _is_at_war(s["origin"], s["destination"], state):
            continue
        seen.add(k)
        routes.append(s)
        if len(routes) >= MAX_ROUTE_SLOTS:
            break

    def _skey(rt: dict) -> Tuple[int, int]:
        w = _ally_weight(rt.get("origin", ""), rt.get("destination", ""), state)
        return (-w, -int(rt.get("capacity", 0) or 0))

    active_routes: List[dict] = [dict(rt) for rt in sorted(routes, key=_skey)[:MAX_ROUTE_SLOTS]]

    for rt in active_routes:
        rt["age_ticks"] = int(rt.get("age_ticks", 0) or 0) + 1
        st = str(rt.get("status", "active"))
        if st == "disrupted" and int(rt.get("disrupted_remaining", 0) or 0) > 0:
            rt["disrupted_remaining"] = int(rt["disrupted_remaining"]) - 1
            if int(rt.get("disrupted_remaining", 0) or 0) <= 0:
                rt["status"] = "active"
        elif st == "disrupted":
            rt["status"] = "active"

    newly_disrupted: List[dict] = []
    for rt in active_routes:
        if str(rt.get("status")) != "active":
            continue
        rk = _clamp(float(rt.get("risk", 0.04)), 0.01, 0.5)
        if str(rt.get("kind")) == "sea":
            rk = _effective_risk_sea_adj(str(rt.get("origin", "")), str(rt.get("destination", "")), rk)
        if random.random() < rk:
            rt["status"] = "disrupted"
            rt["disrupted_remaining"] = 2 + int(random.random() * 2)
            rt["piracy_flag"] = (
                str(rt.get("kind")) == "sea"
                and DREADWIND not in (rt.get("origin", ""), rt.get("destination", ""))
            )
            newly_disrupted.append(rt)

    n_dis = sum(1 for r in active_routes if str(r.get("status")) != "active")
    n_sea_d = sum(
        1 for r in active_routes
        if str(r.get("status")) != "active" and str(r.get("kind")) == "sea"
    )
    piracy_n = int(sum(1 for r in newly_disrupted if r.get("piracy_flag")))

    for rt in newly_disrupted[:4]:
        _record_trade_disruption_cause(state, rt)

    total_flow: Dict[str, float] = {k: 0.0 for k in CORE_RES}
    route_out: List[dict] = []
    for rt in active_routes:
        fmap: Dict[str, Any] = {k: 0.0 for k in CORE_RES}
        tflow = 0.0
        if str(rt.get("status")) == "active":
            fmap = _flow_one_route(state, rt)
            tflow = float(sum(fmap.values()))
            ema = float(rt.get("profit_ema", 0) or 0) * 0.92 + 0.08 * tflow
            rt["profit_ema"] = round(ema, 2)
            if ema > 4.0 and tflow > 0.1:
                rt["capacity"] = int(_clamp(int(rt.get("capacity", 50)) * 1.02 + 1, 20, 400))
        tsum = {k: round(float(fmap.get(k, 0) or 0), 2) for k in CORE_RES}
        total_flow = {k: total_flow[k] + float(fmap.get(k, 0) or 0) for k in CORE_RES}
        pir = bool(rt.pop("piracy_flag", None))
        rcopy = {**rt, "flow_by_resource": tsum, "total_flow": round(tflow, 2)}
        if pir:
            rcopy["piracy_attributed"] = True
        rcopy["tick_flow"] = round(tflow, 2) if str(rt.get("status")) == "active" else 0.0
        route_out.append(rcopy)

    for rt in newly_disrupted:
        _instability_touched(state, {str(rt.get("origin", "")), str(rt.get("destination", ""))}, 2)
    if n_dis >= 3:
        _instability_touched(state, set(factions), 1)

    m = 1.0 + min(0.14, 0.04 * n_dis) + min(0.1, 0.04 * n_sea_d)
    state["economic_disruption_price_mult"] = _clamp(m, 1.0, 1.4)

    state["economic_trade_routes"] = route_out
    state["economic_route_flows"] = {
        "tick": int(state.get("tick", 0) or 0),
        "totals": {k: round(total_flow.get(k, 0), 2) for k in CORE_RES},
        "active_count": int(sum(1 for r in route_out if r.get("status") == "active")),
        "disrupted_count": n_dis,
        "piracy_disruptions": piracy_n,
    }


__all__ = ["process_economic_trade_routes", "TIDEFALL", "DREADWIND"]
