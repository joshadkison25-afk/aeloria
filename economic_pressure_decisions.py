"""
Per-tick faction decisions driven by economic pressure.

Priority: survival > economy > expansion.
Evaluates resource shortages, trade dependency, and military needs; outputs one
primary decision per faction in state['economic_pressure_decisions'].
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from econ_trade_routes import TIDEFALL, _is_at_war  # type: ignore[attr-defined]
from economy_simulation import list_faction_ids
from engine.beliefs import belief_summary, dominant_belief, get_faction_belief_state
from engine.causality import record_cause


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _row(state: dict, fid: str) -> Optional[dict]:
    for r in state.get("faction_economy") or []:
        if (r.get("faction_id") or r.get("faction")) == fid:
            return r
    return None


def _military_power(faction: str, state: dict) -> int:
    for p in state.get("faction_power_state") or []:
        if p.get("faction") == faction:
            return int(p.get("militaryPower", 50) or 50)
    return 50


def _controlled_locations(faction: str, state: dict) -> List[dict]:
    return [loc for loc in (state.get("locations") or []) if loc.get("controller") == faction]


def _holds_eresteron_breadbasket(faction: str, state: dict) -> bool:
    for loc in _controlled_locations(faction, state):
        n = str(loc.get("name", "")).lower()
        if "eresteron" in n:
            return True
    if faction == "Twin Cities":
        for loc in _controlled_locations(faction, state):
            rt = str(loc.get("region_type", "")).lower()
            if rt in ("farmland", "plains", "heath"):
                return True
    return False


def _route_metrics(faction: str, state: dict) -> Tuple[int, int, float, float]:
    """Routes involving faction: count, disrupted count, inbound grain flow, total flow."""
    routes = state.get("economic_trade_routes") or []
    n = 0
    disrupted = 0
    in_grain = 0.0
    tot_flow = 0.0
    for rt in routes:
        o, d = str(rt.get("origin", "")), str(rt.get("destination", ""))
        if faction not in (o, d):
            continue
        n += 1
        if str(rt.get("status", "active")) != "active":
            disrupted += 1
        fbr = rt.get("flow_by_resource") or {}
        if d == faction:
            in_grain += float(fbr.get("grain", 0) or 0)
        tot_flow += float(rt.get("total_flow", 0) or rt.get("tick_flow", 0) or 0)
    return n, disrupted, in_grain, tot_flow


def _trade_dependency(
    grain_cons: float, n_routes: int, in_grain: float, disrupted: int
) -> float:
    if n_routes <= 0 and in_grain <= 0:
        return 0.0
    flow_ratio = in_grain / max(8.0, grain_cons) if grain_cons > 0 else min(1.0, in_grain / 40.0)
    dis_w = 0.18 * min(3, disrupted)
    r_w = 0.12 * min(8, n_routes)
    return _clamp(r_w + 0.45 * _clamp(flow_ratio, 0, 2.5) + dis_w, 0.0, 1.0)


def _pick_raid_victim(faction: str, state: dict) -> str:
    """Another faction to raid for supplies (not self, prefer non-allied if known)."""
    others = [f for f in list_faction_ids(state) if f and f != faction]
    for o in others:
        if not _is_at_war(faction, o, state):
            return o
    return others[0] if others else ""


def _raid_target_from_beliefs(faction: str, state: dict) -> str:
    belief_state = get_faction_belief_state(state, faction)
    for belief in belief_state.get("beliefs", []) or []:
        if not isinstance(belief, dict):
            continue
        claim = str(belief.get("claim") or "").lower()
        if "vulnerable" in claim and "provisioning raid" in claim:
            target = str(belief.get("subject") or "").strip()
            if target and target != faction:
                return target
    return ""


def _pick_iron_invasion_target(faction: str, state: dict) -> str:
    for loc in state.get("locations") or []:
        if loc.get("controller") in (None, "", faction):
            continue
        name = str(loc.get("name", "")).lower()
        rtype = str(loc.get("region_type", "")).lower()
        if "farrock" in name or rtype == "mine" or "iron" in name or "foundry" in name:
            return str(loc.get("name", ""))
    for loc in state.get("locations") or []:
        if loc.get("controller") in (None, "", faction):
            continue
        if str(loc.get("region_type", "")).lower() in ("hills", "mountain", "highlands", "fortress"):
            return str(loc.get("name", ""))
    return ""


def _apply_raise_taxes(faction: str, state: dict) -> None:
    row = _row(state, faction)
    if not row:
        return
    res = row.setdefault("resources", {})
    g = res.setdefault("gold", {})
    cap = int(g.get("storage_capacity", 3000) or 3000)
    stock = float(g.get("stockpile", 0) or 0)
    bump = max(2.0, cap * 0.008)
    g["stockpile"] = int(min(cap, stock + bump))
    for loc in _controlled_locations(faction, state):
        st = int(loc.get("stability", 50) or 50)
        loc["stability"] = int(_clamp(st - 2, 0, 100))
    regions = {str(loc.get("name")) for loc in _controlled_locations(faction, state)}
    for p in state.get("population_state") or []:
        if str(p.get("region", "")) in regions:
            pr = int(p.get("pressure", 50) or 50)
            p["pressure"] = int(_clamp(pr + 3, 0, 100))


def _decide_one(
    faction: str,
    state: dict,
    sev: Dict[str, float],
    trade_dep: float,
    mil_need: float,
    n_routes: int,
    disrupted: int,
) -> Tuple[str, str, str, Dict[str, Any]]:
    """
    Returns (priority_tier, action, summary, meta).
    """
    g, gold, iron = sev["grain"], sev["gold"], sev["iron"]
    siege = float((state.get("siege_grain_drain_by_faction") or {}).get(faction) or 0.0) > 0.25

    survival_signal = _clamp(
        0.42 * (g * 0.55 + gold * 0.35) + 0.18 * max(g, gold, iron * 0.6) + (0.22 if siege else 0.0) + 0.12 * g,
        0.0,
        1.0,
    )
    economy_signal = _clamp(0.55 * trade_dep + 0.35 * gold + 0.12 * (disrupted * 0.15), 0.0, 1.0)
    expansion_signal = _clamp(0.5 * iron + 0.22 * (mil_need) - 0.15 * g, 0.0, 1.0)

    # Strict tier: survival > economy > expansion
    tier = "expansion"
    if survival_signal >= 0.18 and (survival_signal >= economy_signal * 0.88 or g > 0.28 or gold > 0.32 or siege):
        tier = "survival"
    elif economy_signal >= 0.15 and economy_signal >= expansion_signal * 0.9:
        tier = "economy"
    else:
        tier = "expansion"
        if expansion_signal < 0.12 and economy_signal < 0.12 and survival_signal < 0.12:
            tier = "economy"  # default peacetime: prefer trade / stability
            if trade_dep < 0.08 and n_routes < 2:
                tier = "economy"  # still seek partners

    meta: Dict[str, Any] = {}

    def _r(
        main: str, s: str, priority: Optional[str] = None
    ) -> Tuple[str, str, str, Dict[str, Any]]:
        return (priority or tier, main, s, meta)

    raid_target = _raid_target_from_beliefs(faction, state)
    if (tier == "survival" or g > 0.22) and raid_target and g > 0.12:
        meta["target_faction"] = raid_target
        return _r(
            "raid_for_provisions",
            f"{faction} raiders strike {raid_target} for food after reading weakness across the border.",
            "survival",
        )

    # Flavor: Vilefin raids when starving
    if (tier == "survival" or g > 0.22) and "Vilefin" in faction and g > 0.12:
        meta["target_faction"] = _pick_raid_victim(faction, state)
        return _r(
            "raid_for_provisions",
            f"{faction} raiders strike out for food — coastal hunger leaves little choice.",
            "survival",
        )

    # Eresteron / Twin Cities: defend grain supply lines
    if tier in ("survival", "economy") and (g > 0.12 or disrupted > 0) and _holds_eresteron_breadbasket(
        faction, state
    ):
        meta["focus"] = "grain"
        return _r(
            "defend_supply_lines",
            f"{faction} doubles patrols along grain convoys; the breadbasket cannot starve the realm.",
        )

    if tier == "survival" and gold > 0.3 and g < 0.35:
        _apply_raise_taxes(faction, state)
        return _r(
            "raise_taxes",
            f"{faction} imposes harsher levies to refill the treasury; stability suffers.",
        )

    # Tidefall: trade dominance (not when grain is acutely critical)
    if (faction == TIDEFALL or "Tidefall" in faction) and g < 0.32:
        meta["posture"] = "sea_lanes"
        return _r(
            "prioritize_trade_dominance",
            f"{faction} leans on tariffs, convoys, and port privilege — trade is survival.",
        )

    if tier == "survival" or (g > 0.2 and n_routes < 3):
        meta["seeking"] = "commodities"
        return _r(
            "seek_trade_partners",
            f"{faction} dispatches envoys to secure grain, iron, and credit on whatever terms it can get.",
        )

    if tier == "economy" and (disrupted > 0 or trade_dep > 0.35):
        return _r(
            "defend_supply_lines",
            f"{faction} escorts caravans and reopens disrupted lanes before prices spiral.",
        )

    if tier == "economy":
        return _r(
            "seek_trade_partners",
            f"{faction} works markets and partners to keep flows steady.",
        )

    # Expansion: iron / Farrock-style — Lostfeld, or any faction in iron stress
    iron_motive = iron > 0.22 and _military_power(faction, state) >= 32
    farrock = any("farrock" in str(loc.get("name", "")).lower() for loc in _controlled_locations(faction, state))
    if (tier == "expansion" and iron_motive) or (iron > 0.28 and ("Lostfeld" in faction or farrock)):
        tgt = _pick_iron_invasion_target(faction, state)
        if tgt:
            meta["target_location"] = tgt
        return _r(
            "invade_for_resources",
            f"{faction} plans seizure of iron and ore country — forges and spears outstrip treaties.",
        )

    if tier == "expansion" and mil_need > 0.35:
        return _r(
            "invade_for_resources",
            f"{faction} readies a grab for resource ground to feed the war engine.",
        )

    return _r(
        "seek_trade_partners",
        f"{faction} pursues open commerce and stockpiles while the realm is not in crisis.",
    )


def _merge_into_tick_history(state: dict) -> None:
    tick = int(state.get("tick", 0) or 0)
    decs = state.get("economic_pressure_decisions") or []
    for i in range(len(state.get("tick_history") or []) - 1, -1, -1):
        h = (state.get("tick_history") or [])[i]
        if h.get("tick") == tick:
            h["economic_pressure_decisions"] = decs
            (state.get("tick_history") or [])[i] = h
            break


def _economic_decision_severity(decision: dict) -> int:
    tier = decision.get("priority_tier", "")
    metrics = decision.get("metrics") or {}
    shortage = metrics.get("shortage") or {}
    max_shortage = max([float(v or 0) for v in shortage.values()] or [0.0])
    if tier == "survival":
        return 8 + min(5, int(max_shortage * 8))
    if tier == "economy":
        return 5 + min(4, int(max_shortage * 6))
    return 4 + min(4, int(max_shortage * 5))


def _record_economic_causes(state: dict, decisions: List[dict]) -> None:
    for decision in decisions:
        action = decision.get("action", "")
        if action == "seek_trade_partners" and decision.get("priority_tier") == "economy":
            continue
        faction = decision.get("faction", "")
        if not faction:
            continue
        metrics = decision.get("metrics") or {}
        shortage = metrics.get("shortage") or {}
        trade_dep = metrics.get("trade_dependency", 0)
        mil_need = metrics.get("military_need", 0)
        food_signal = "; food shortage" if float(shortage.get("grain", 0) or 0) > 0 else ""
        pressure = (
            f"{decision.get('priority_tier', 'economic')} economic pressure{food_signal}; "
            f"shortage={shortage}; trade_dependency={trade_dep}; military_need={mil_need}"
        )
        belief = belief_summary(dominant_belief(state, faction))
        affected = [faction]
        meta = decision.get("meta") or {}
        for key in ("target_faction", "focus", "seeking"):
            if meta.get(key):
                affected.append(str(meta[key]))
        record_cause(
            state,
            domain="economy",
            actor=faction,
            pressure=pressure,
            belief=belief,
            decision=action,
            outcome=decision.get("summary", ""),
            affected=affected,
            severity=_economic_decision_severity(decision),
            confidence=0.82,
            source="economic_pressure_decisions",
        )


def run_economic_pressure_decisions(state: dict) -> None:
    tick = int(state.get("tick", 0) or 0)
    if state.get("_economic_pressure_decisions_tick") == tick:
        return
    state["_economic_pressure_decisions_tick"] = tick

    factions = list_faction_ids(state)[:24]
    if not factions:
        state["economic_pressure_decisions"] = []
        _merge_into_tick_history(state)
        return

    out: List[dict] = []

    for fid in factions:
        row = _row(state, fid)
        if not row:
            continue
        se = row.get("shortage_effects") or {}
        res = row.get("resources") or {}

        sev: Dict[str, float] = {}
        for r in ("grain", "iron", "timber", "gold"):
            sev[r] = float((se.get(r) or {}).get("severity", 0) or 0)

        grain_c = float((res.get("grain") or {}).get("consumption", 50) or 50)
        n_routes, disrupted, in_grain, _tot = _route_metrics(fid, state)
        trade_dep = _trade_dependency(grain_c, n_routes, in_grain, disrupted)
        mil = _military_power(fid, state)
        iron_c = float((res.get("iron") or {}).get("consumption", 1) or 1)
        mil_need = _clamp(iron_c / 200.0 + sev["iron"] * 0.5 + (100 - mil) / 120.0, 0.0, 1.0)

        tier, action, summary, meta = _decide_one(
            fid, state, sev, trade_dep, mil_need, n_routes, disrupted
        )

        out.append(
            {
                "faction": fid,
                "priority_tier": tier,
                "action": action,
                "summary": summary,
                "metrics": {
                    "shortage": {k: round(v, 4) for k, v in sev.items()},
                    "trade_dependency": round(trade_dep, 4),
                    "military_need": round(mil_need, 4),
                },
                "meta": meta,
            }
        )

    state["economic_pressure_decisions"] = out
    _record_economic_causes(state, out)
    _merge_into_tick_history(state)


__all__ = ["run_economic_pressure_decisions"]
