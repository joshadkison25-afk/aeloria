"""
Faction armies as concrete units: manpower, morale, discipline, supply, location.

Grain and gold consumption are folded into the economy sim via
`army_manpower_total` in `economy_simulation._population_aggregates` (same
formulas as active military: more men → more food and pay in `_estimate_consumption`).

`run_military_after_economy_tick` applies supply stress, morale loss, and desertion
after `faction_economy` shortage effects are known.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from economy_simulation import (
    army_manpower_total,
    list_faction_ids,
    _population_aggregates,  # type: ignore
)
from siege_blockade import _is_allied, _is_at_war

# Supply / morale / desertion (tunable)
SUPPLY_RECOVERY = 1.2
SUPPLY_STRESS = 2.4
MORALE_SHOCK = 0.18
DESERTION_BASE = 0.004
DESERTION_MAX = 0.028

# Terrain attrition (multiplier per tick; used with (1 - supply/100))
TERRAIN_PLAINS = 0.01
TERRAIN_FOREST = 0.02
TERRAIN_MOUNTAINS = 0.04
TERRAIN_FROZEN = 0.05
# +0.01 per 5 full ticks in hostile (non-faction) territory; cap optional
CAMPAIGN_BONUS_PER_BLOCK = 0.01
CAMPAIGN_TICKS_PER_BONUS = 5
MAX_CAMPAIGN_BONUS = 0.12
# Morale: slight tick drain from field losses
ATTRITION_MORALE_BASE = 0.12
ATTRITION_MORALE_PER_LOST_FRAC = 0.4

# Supply lines (per tick) — strained vs cut; connected recovers slightly
SUPPLY_LINE_STRAINED_PENALTY = 5
SUPPLY_LINE_CUT_PENALTY = 15
SUPPLY_LINE_CONNECTED_BONUS = 2
# Extra attrition when logistics collapse
LOW_SUPPLY_ATTRITION_MULT_25 = 1.75
COLLAPSE_RISK_P10 = 0.09
COLLAPSE_MANPOWER_FRACTION = 0.22


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _clamp_i(x: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, x))


def _faction_id(a: dict) -> str:
    return str(a.get("faction_id") or a.get("faction") or "")


def _controlled_location_names(faction: str, state: dict) -> List[str]:
    out: List[str] = []
    for loc in state.get("locations") or []:
        if loc.get("controller") == faction and loc.get("name"):
            out.append(str(loc.get("name")))
    return out


def _default_location(faction: str, state: dict) -> str:
    names = _controlled_location_names(faction, state)
    if names:
        return names[0]
    for p in state.get("population_state") or []:
        c = str(p.get("culture", ""))
        if faction.split()[0] in c or faction in c:
            if p.get("region"):
                return str(p.get("region"))
    return "Unknown"


def _new_army_id(faction: str) -> str:
    u = uuid.uuid4().hex[:10]
    h = hashlib.md5(faction.encode("utf-8", errors="ignore"), usedforsecurity=False).hexdigest()[:6]
    return f"army_{h}_{u}"


def _default_army(
    faction: str, state: dict, manpower: int, loc: str, prev: Optional[dict] = None
) -> dict:
    p = prev or {}
    m = int(max(0, manpower))
    return {
        "army_id": p.get("army_id") or _new_army_id(faction),
        "faction_id": faction,
        "manpower": m,
        "morale": _clamp_i(int(p.get("morale", 60 + random.randint(-5, 8))), 0, 100),
        "discipline": _clamp_i(int(p.get("discipline", 50 + random.randint(-8, 10))), 0, 100),
        "supply_level": _clamp_i(int(p.get("supply_level", 70 + random.randint(-8, 10))), 0, 100),
        "location": p.get("location") or loc,
        "home_region": p.get("home_region") or p.get("location") or loc,
        "commander": p.get("commander") if p.get("commander") is not None else None,
        "hostile_campaign_ticks": int(p.get("hostile_campaign_ticks", 0) or 0),
    }


def ensure_faction_armies(state: dict, prev_state: Optional[dict] = None) -> None:
    """
    Merge `faction_armies` from the previous state and incoming `state`, validate,
    and create one default army for any faction with none. Call before
    `run_faction_economy_tick`.
    """
    tick = int(state.get("tick", 0) or 0)
    if state.get("_military_ensure_tick") == tick:
        return
    state["_military_ensure_tick"] = tick

    prev = prev_state or {}
    m: Dict[str, dict] = {}
    for a in (prev.get("faction_armies") or []):
        aid = a.get("army_id")
        if aid:
            m[aid] = dict(a)
    for a in (state.get("faction_armies") or []):
        aid = a.get("army_id")
        if not aid:
            continue
        m[aid] = {**(m.get(aid) or {}), **a, "army_id": aid}

    merged: List[dict] = list(m.values())
    by_faction: Dict[str, List[dict]] = {}
    for a in merged:
        f = _faction_id(a)
        if f:
            by_faction.setdefault(f, []).append(a)

    out: List[dict] = []
    factions = list_faction_ids(state)[:32]
    for f in factions:
        rows = by_faction.get(f, [])
        took: List[dict] = []
        if rows:
            for a in rows:
                a = dict(a)
                a["faction_id"] = f
                a.setdefault("army_id", _new_army_id(f))
                a["manpower"] = max(0, int(a.get("manpower", 0) or 0))
                a["morale"] = _clamp_i(int(a.get("morale", 55) or 55), 0, 100)
                a["discipline"] = _clamp_i(int(a.get("discipline", 50) or 50), 0, 100)
                a["supply_level"] = _clamp_i(int(a.get("supply_level", 65) or 65), 0, 100)
                a["location"] = a.get("location") or _default_location(f, state)
                a.setdefault("home_region", a.get("location") or _default_location(f, state))
                if "commander" not in a:
                    a["commander"] = None
                a.setdefault("hostile_campaign_ticks", 0)
                if a["manpower"] < 1:
                    continue
                took.append(a)
        if took:
            out.extend(took)
            continue
        st = {**state, "faction_armies": []}
        pop, mil, _n = _population_aggregates(f, st)
        loc = _default_location(f, state)
        mp = max(12, int(mil) if mil > 0 else max(12, pop // 400))
        out.append(_default_army(f, state, mp, loc, None))

    state["faction_armies"] = out


def _location_record(loc_name: str, state: dict) -> Optional[dict]:
    if not str(loc_name).strip():
        return None
    for loc in state.get("locations") or []:
        if str(loc.get("name", "")) == str(loc_name):
            return loc if isinstance(loc, dict) else None
    return None


def _terrain_modifier_for_location(loc_name: str, state: dict) -> Tuple[str, float]:
    """(label, terrain_modifier) for attrition. Defaults to plains."""
    loc = _location_record(loc_name, state) or {}
    name_l = str(loc.get("name", loc_name) or "").lower()
    rtype = str(loc.get("region_type", "")).lower()

    if "frostvale" in name_l or rtype in ("frost", "tundra", "glacial", "ice", "winter_fell"):
        return ("frozen", TERRAIN_FROZEN)
    if rtype in ("mountain", "mountains", "highlands", "peaks", "alpine", "cliff") or "mountain" in name_l:
        return ("mountains", TERRAIN_MOUNTAINS)
    if rtype in (
        "hills",
        "moor",
        "forest",
        "wood",
        "woodland",
        "jungle",
        "grove",
        "boreal",
    ) or "forest" in rtype or "wood" in name_l or "hill" in rtype:
        return ("forest", TERRAIN_FOREST)
    if rtype in ("plains", "farmland", "heath", "plains_", "meadow", "grassland") or "plain" in rtype:
        return ("plains", TERRAIN_PLAINS)
    if rtype in ("wilderness", "coast", "port", "strait", "default", "steppe"):
        return ("plains", TERRAIN_PLAINS)
    return ("plains", TERRAIN_PLAINS)


def _active_trade_route_pair(fa: str, fb: str, state: dict) -> bool:
    for rt in state.get("economic_trade_routes") or []:
        if str(rt.get("status", "active")) != "active":
            continue
        o, d = str(rt.get("origin", "") or ""), str(rt.get("destination", "") or "")
        if not o or not d:
            continue
        if {o, d} == {fa, fb}:
            return True
    return False


def _faction_route_distance(frm: str, to: str, state: dict) -> int:
    if not frm or not to:
        return 10**9
    if frm == to:
        return 0
    g: Dict[str, Set[str]] = {}
    for rt in state.get("economic_trade_routes") or []:
        if str(rt.get("status", "active")) != "active":
            continue
        o, d = str(rt.get("origin", "") or ""), str(rt.get("destination", "") or "")
        if not o or not d:
            continue
        g.setdefault(o, set()).add(d)
        g.setdefault(d, set()).add(o)
    q: deque[Tuple[str, int]] = deque([(frm, 0)])
    vis: Set[str] = {frm}
    while q:
        n, dist = q.popleft()
        if n == to:
            return dist
        for x in g.get(n, ()):
            if x not in vis:
                vis.add(x)
                q.append((x, dist + 1))
    return 10**9


def _location_under_siege(loc_name: str, state: dict) -> bool:
    for s in (state.get("siege_warfare") or {}).get("sieges") or []:
        if not isinstance(s, dict):
            continue
        if str(s.get("location", "")) != str(loc_name):
            continue
        if s.get("outcome") in ("lifted", "abandoned", "surrendered"):
            continue
        return True
    return False


def compute_army_supply_status(army: dict, state: dict) -> Tuple[str, str]:
    """
    Return (supply_status, reason_code).
    status in: connected | strained | cut
    """
    f = _faction_id(army)
    if not f:
        return "strained", "no_faction"
    if army.get("holding_supply_point"):
        return "connected", "captured_depot"
    if army.get("retreat_to_supply") and str(army.get("location") or "") == str(
        army.get("home_region") or ""
    ):
        return "connected", "rally_to_home"
    if army.get("re_establish_ally") and _active_trade_route_pair(
        f, (army.get("ally_resupply_partner") or ""), state
    ):
        return "strained", "ally_corridor"
    loc_name = str(army.get("location") or "")
    home = str(army.get("home_region") or "")
    if home and loc_name and loc_name == home:
        loc = _location_record(loc_name, state)
        if not loc or (loc.get("controller") or "").strip() == f:
            if not _location_under_siege(loc_name, state):
                return "connected", "home_region"
            return "strained", "siege_at_home"
    loc = _location_record(loc_name, state)
    if not loc:
        return "strained", "unmapped"
    ctrl = (loc.get("controller") or "").strip()
    is_city = str(loc.get("region_type", "")).lower() in (
        "capital",
        "city",
        "port",
        "fortress",
        "fort",
    )
    if ctrl == f:
        if _location_under_siege(loc_name, state) or f in (state.get("besieged_factions") or []):
            return "strained", "siege_interdiction"
        return "connected", "controlled_city" if is_city else "in_core_territory"
    if ctrl and _is_at_war(f, ctrl, state):
        if army.get("retreat_to_supply"):
            return "strained", "retreat_preserve_trains"
        return "cut", "hostile_territory"
    if ctrl and _is_allied(f, ctrl, state):
        dist = _faction_route_distance(f, ctrl, state)
        pair = _active_trade_route_pair(f, ctrl, state)
        if dist < 10**8 and (dist <= 1 or pair):
            if pair:
                return "connected", "ally_firm_lanes"
            return "strained", "allied_shallow"
        return "strained", "allied_tenuous"
    if not ctrl:
        return "strained", "unclaimed"
    dist = _faction_route_distance(f, ctrl, state)
    pair = _active_trade_route_pair(f, ctrl, state)
    if pair or (dist < 10**8 and dist <= 3):
        if pair:
            return "strained", "active_supply_route"
        return "strained", "neutral_distant"
    if dist < 10**8:
        return "strained", "distant_trunk"
    return "cut", "isolated_no_route"


def _apply_line_supply_step(sup: int, status: str) -> int:
    s = int(_clamp(sup, 0, 100))
    if status == "connected":
        return int(_clamp(s + SUPPLY_LINE_CONNECTED_BONUS, 0, 100))
    if status == "strained":
        return int(_clamp(s - SUPPLY_LINE_STRAINED_PENALTY, 0, 100))
    return int(_clamp(s - SUPPLY_LINE_CUT_PENALTY, 0, 100))


def _is_hostile_territory(army_faction: str, loc_name: str, state: dict) -> bool:
    loc = _location_record(loc_name, state)
    if not loc:
        return False
    ctrl = (loc.get("controller") or "").strip()
    if not ctrl:
        return True
    return ctrl != army_faction


def _long_campaign_bonus(hostile_ticks: int) -> float:
    """+0.01 per 5 full ticks, capped."""
    b = CAMPAIGN_BONUS_PER_BLOCK * (max(0, hostile_ticks) // CAMPAIGN_TICKS_PER_BONUS)
    return float(_clamp(b, 0.0, MAX_CAMPAIGN_BONUS))


def _apply_attrition(
    a: dict,
    state: dict,
    attrition_mult: float = 1.0,
) -> Tuple[dict, dict]:
    """
    Returns (updated_army, report_row) with manpower/morale adjusted.
    report_row is one entry for military_attrition.
    """
    m0 = int(a.get("manpower", 0) or 0)
    sup = int(_clamp(int(a.get("supply_level", 50) or 50), 0, 100))
    mor = int(a.get("morale", 50) or 50)
    loc_name = a.get("location") or ""
    fid = _faction_id(a)
    loc_label, t_mod = _terrain_modifier_for_location(str(loc_name), state)
    hostile = _is_hostile_territory(fid, str(loc_name), state)
    if hostile:
        ht = int(a.get("hostile_campaign_ticks", 0) or 0) + 1
    else:
        ht = 0
    a["hostile_campaign_ticks"] = ht

    camp = _long_campaign_bonus(ht) if hostile else 0.0
    eff_terrain = t_mod + camp
    supply_factor = 1.0 - (sup / 100.0)
    raw = float(m0) * eff_terrain * supply_factor
    raw *= max(0.1, float(attrition_mult))
    raw *= float(state.get("military_weather_attrition_mult", 1.0) or 1.0)  # hook for future weather
    loss = int(max(0, min(m0 - 1, int(raw)))) if m0 > 1 else 0
    m1 = max(0, m0 - loss)

    if loss > 0:
        frac = loss / max(1.0, float(m0))
        mor = int(_clamp(mor - ATTRITION_MORALE_BASE - ATTRITION_MORALE_PER_LOST_FRAC * frac, 0, 100))
    # Campaign wear: slight morale loss each tick in hostile ground (even if loss rounds to 0)
    if hostile:
        mor = int(_clamp(mor - 0.15, 0, 100))
    else:
        mor = int(_clamp(mor - 0.06, 0, 100))

    a["manpower"] = m1
    a["morale"] = _clamp_i(mor, 0, 100)
    a["_last_attrition"] = int(loss)

    report: dict = {
        "army_id": a.get("army_id", ""),
        "faction_id": fid,
        "loss": loss,
        "terrain": loc_label,
        "terrain_modifier": round(t_mod, 4),
        "effective_terrain_modifier": round(eff_terrain, 4),
        "campaign_ticks_hostile": ht if hostile else 0,
        "campaign_bonus": round(camp, 4),
        "supply_factor": round(supply_factor, 4),
    }
    return a, report


def _shortage(state: dict, fid: str, res: str) -> float:
    for row in state.get("faction_economy") or []:
        if (row.get("faction_id") or row.get("faction")) != fid:
            continue
        se = (row.get("shortage_effects") or {}).get(res) or {}
        return float(se.get("severity", 0) or 0)
    return 0.0


def run_military_after_economy_tick(state: dict, prev_state: Optional[dict] = None) -> None:
    del prev_state
    tick = int(state.get("tick", 0) or 0)
    if state.get("_military_after_econ_tick") == tick:
        return
    state["_military_after_econ_tick"] = tick

    armies = list(state.get("faction_armies") or [])
    if not armies:
        state["military_attrition"] = []
        state["military_supply"] = []
        return

    attrition_report: List[dict] = []
    supply_report: List[dict] = []
    updated: List[dict] = []
    for a0 in armies:
        a = dict(a0)
        a.setdefault("hostile_campaign_ticks", 0)
        fid = _faction_id(a)
        a.setdefault("home_region", a.get("location") or (fid and _default_location(fid, state)) or "")

        sstat, sreason = compute_army_supply_status(a, state)
        a["supply_status"] = sstat
        a["supply_line_reason"] = sreason

        sup = int(a.get("supply_level", 50) or 50)
        sup = _apply_line_supply_step(sup, sstat)
        a["supply_level"] = _clamp_i(sup, 0, 100)
        if a.get("retreat_to_supply") and sstat != "cut":
            a["supply_level"] = _clamp_i(int(a["supply_level"]) + 4, 0, 100)

        mor = int(a.get("morale", 50) or 50)
        disc = int(a.get("discipline", 50) or 50)
        mnp = int(a.get("manpower", 0) or 0)
        sup = int(a.get("supply_level", 50) or 50)

        g_short = _shortage(state, fid, "grain")
        au_short = _shortage(state, fid, "gold")
        stress = _clamp(0.55 * g_short + 0.45 * au_short, 0.0, 1.0)

        if stress < 0.04:
            sup = int(_clamp(sup + SUPPLY_RECOVERY + random.uniform(-0.3, 0.3), 0, 100))
        else:
            sup = int(
                _clamp(
                    sup - stress * SUPPLY_STRESS * (1.0 + 0.35 * (1.0 - disc / 100.0)),
                    0,
                    100,
                )
            )

        a["supply_level"] = _clamp_i(sup, 0, 100)
        sup = int(a.get("supply_level", 50) or 50)

        if sup < 50:
            mor = int(
                _clamp(
                    mor - (50 - sup) * 0.1 * (1.0 - 0.2 * (disc / 100.0)),
                    0,
                    100,
                )
            )
        if sup < 25:
            mor = int(
                _clamp(
                    mor - (25 - sup) * 0.16 * (1.0 - 0.2 * (disc / 100.0)),
                    0,
                    100,
                )
            )
        if sup < 10 and random.random() < COLLAPSE_RISK_P10:
            mnp = max(1, int(mnp * (1.0 - COLLAPSE_MANPOWER_FRACTION)))
            mor = int(_clamp(mor - 2.0, 0, 100))
            a["_supply_collapse"] = True
        else:
            a.pop("_supply_collapse", None)

        a["morale"] = _clamp_i(mor, 0, 100)
        a["manpower"] = mnp
        sup = int(a.get("supply_level", 50) or 50)
        if sup < 45:
            a["morale"] = int(
                _clamp(
                    int(a.get("morale", 0))
                    - (45 - sup) * MORALE_SHOCK * (1.0 - 0.35 * (disc / 100.0)),
                    0,
                    100,
                )
            )
        elif sup > 72 and stress < 0.08:
            a["morale"] = int(
                _clamp(
                    int(a.get("morale", 0)) + 0.35 + random.uniform(0, 0.2),
                    0,
                    100,
                )
            )

        at_mult = 1.0
        if sup < 25:
            at_mult = LOW_SUPPLY_ATTRITION_MULT_25
        if sup < 10:
            at_mult *= 1.2

        a, row = _apply_attrition(a, state, at_mult)
        row["tick"] = tick
        row["supply_status"] = sstat
        row["supply_line_reason"] = sreason
        attrition_report.append(row)
        sup = int(a.get("supply_level", 50) or 50)
        mor = int(a.get("morale", 50) or 50)
        mnp = int(a.get("manpower", 0) or 0)

        if mnp > 2 and (sup < 55 or mor < 40):
            worst = (55 - min(55, sup)) / 55.0
            m_low = (40 - min(40, mor)) / 40.0 if mor < 40 else 0.0
            rate = _clamp(
                DESERTION_BASE
                + worst * 0.012
                + m_low * 0.01
                + (DESERTION_MAX - DESERTION_BASE) * stress,
                0.0,
                DESERTION_MAX,
            )
            if sstat == "cut":
                rate += 0.006
            rate *= 1.0 - 0.45 * (disc / 100.0)
            lose = int(mnp * rate)
            lose = min(mnp - 1, max(0, lose))
            mnp = max(1, mnp - lose)
            a["_last_desertion"] = lose
        else:
            a.pop("_last_desertion", None)

        a["supply_level"] = _clamp_i(sup, 0, 100)
        a["morale"] = _clamp_i(mor, 0, 100)
        a["manpower"] = mnp
        a["discipline"] = _clamp_i(disc, 0, 100)
        if a.get("manpower", 0) < 1:
            continue
        updated.append(a)
        supply_report.append(
            {
                "army_id": a.get("army_id", ""),
                "faction_id": fid,
                "supply_status": a.get("supply_status", sstat),
                "supply_line_reason": a.get("supply_line_reason", sreason),
                "tick": tick,
            }
        )

    state["faction_armies"] = updated
    state["military_attrition"] = attrition_report
    state["military_supply"] = supply_report


def build_military_export(state: dict) -> List[dict]:
    return [
        {
            "army_id": a.get("army_id", ""),
            "faction_id": _faction_id(a),
            "manpower": int(a.get("manpower", 0) or 0),
            "morale": int(_clamp(int(a.get("morale", 0) or 0), 0, 100)),
            "discipline": int(_clamp(int(a.get("discipline", 0) or 0), 0, 100)),
            "supply_level": int(_clamp(int(a.get("supply_level", 0) or 0), 0, 100)),
            "location": a.get("location") or "",
            "supply_status": a.get("supply_status", "strained"),
            "supply_line_reason": a.get("supply_line_reason", ""),
        }
        for a in (state.get("faction_armies") or [])
        if a.get("army_id")
    ]


__all__ = [
    "army_manpower_total",
    "compute_army_supply_status",
    "ensure_faction_armies",
    "run_military_after_economy_tick",
    "build_military_export",
]
