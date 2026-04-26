"""
Siege and naval blockade mechanics: supply interdiction, starvation, stability,
and simple outcome probabilities. Integrated with the faction economy + trade tick.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Set, Tuple

from economy_simulation import army_manpower_total

DREADWIND = "Dreadwind Isles"
TIDEFALL = "Tidefall"

# Fortification: fort_level 0 = no works, 5 = major fortress
FORT_MAX = 5
# Progress scaling: base increment uses attacker / (fort * 1000) with fort 0 → fast (denom 500)
SIEGE_PROGRESS_RAW_SCALE = 2.0
GARR_SUPPLY_SLOW_SCALE = 2500.0
SUPPLIES_STOCK_SCALE = 6000.0
STOCK_CONSUME_BASE = 6.0
STOCK_CONSUME_PER_GARR = 0.12
GARR_ATTRITION_STARVING = 0.012


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


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


def _is_allied(a: str, b: str, state: dict) -> bool:
    rels = state.get("relationships", [])
    if isinstance(rels, list):
        for rel in rels or []:
            if not isinstance(rel, dict):
                continue
            if {a, b} != {rel.get("faction_a", ""), rel.get("faction_b", "")}:
                continue
            t = (rel.get("type") or "").lower()
            if t in ("alliance", "allied"):
                return True
        return False
    if isinstance(rels, dict):
        s = (rels.get(a) or {}).get(b) or (rels.get(b) or {}).get(a)
        if not isinstance(s, dict):
            return False
        t = str(s.get("type", s.get("status", ""))).lower()
        return t in ("alliance", "allied")
    return False


def _is_coastal_faction(f: str, state: dict) -> bool:
    for loc in state.get("locations", []) or []:
        if loc.get("controller") != f:
            continue
        rt = str(loc.get("region_type", "")).lower()
        if rt in ("port", "coast", "isles", "archipelago", "island", "bays", "bays_", "headlands", "sea"):
            return True
    return f in (TIDEFALL, DREADWIND)


def _location_by_name(state: dict) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for loc in state.get("locations", []) or []:
        n = (loc.get("name") or "").strip()
        if n:
            out[n] = loc
    return out


def ensure_location_fortification_defaults(state: dict) -> None:
    """
    Enrich each location with fort_level (0–5), garrison_size, stored_supplies.
    Safe to call every tick; preserves explicit AI values when present.
    """
    for loc in state.get("locations", []) or []:
        if not isinstance(loc, dict) or not loc.get("name"):
            continue
        rt = str(loc.get("region_type", "")).lower()
        if "fort_level" in loc and loc.get("fort_level") is not None:
            fl = int(loc.get("fort_level", 0) or 0)
        else:
            dfl = 0
            if rt == "fortress":
                dfl = 3
            elif rt in ("capital", "city"):
                dfl = 2
            elif rt in ("port", "mine"):
                dfl = 1
            fl = dfl
        fl = int(_clamp(int(fl), 0, FORT_MAX))
        loc["fort_level"] = fl
        pop = int(loc.get("population", 0) or 0)
        if loc.get("garrison_size") is not None and str(loc.get("garrison_size", "")) != "":
            gs = int(loc.get("garrison_size", 0) or 0)
        else:
            gs = max(20, min(8000, pop // 25 + 80 * fl + 30))
        loc["garrison_size"] = max(0, gs)
        if loc.get("stored_supplies") is not None and str(loc.get("stored_supplies", "")) != "":
            ss = float(loc.get("stored_supplies", 0) or 0)
        else:
            ss = 1800.0 + fl * 450.0 + gs * 0.35
        loc["stored_supplies"] = max(0.0, float(ss))


def _relief_eligible_military(defender: str, lname: str, state: dict) -> float:
    """Sum ally manpower in this location or in adjacent named locations (outside aid)."""
    loc_by = _location_by_name(state)
    lrec = loc_by.get(lname) or {}
    names: Set[str] = {lname}
    for n in lrec.get("adjacent", []) or []:
        if n:
            names.add(str(n))
    acc = 0.0
    for row in state.get("faction_armies", []) or []:
        f = (row.get("faction_id") or row.get("faction") or "").strip()
        if not f or f == defender:
            continue
        if not _is_allied(f, defender, state) or _is_at_war(f, defender, state):
            continue
        if (row.get("location") or "") in names:
            acc += int(row.get("manpower", 0) or 0)
    return acc


def _maritime_rival_tension(f: str, state: dict) -> float:
    """0..1: how much naval pressure from enemies at war."""
    if not _is_coastal_faction(f, state):
        return 0.0
    acc = 0.0
    for other in (TIDEFALL, DREADWIND):
        if other == f or not _is_at_war(f, other, state):
            continue
        acc += 0.16 if other == TIDEFALL else 0.2
    return _clamp(acc, 0, 0.5)


def _identify_sieges(state: dict, prev_sw: dict) -> Tuple[List[dict], Set[str], Dict[str, float]]:
    """
    A location is under siege (supply interdicted) when it is a primary war target
    and (under active fighting, or the assault is explicitly a slow siege/pressure on a strongpoint).

    Fortified locations track siege_progress_pct (breach at 100), remaining_supplies, garrison,
    and defender_morale. Progress: attacker_manpower / (fort_level * 1000) with fort 0 using a
    500-denominator, slowed by garrison and stored supplies.
    """
    terminal_outcomes = {
        "breach",
        "breached",
        "surrender",
        "surrender_starvation",
        "relief",
        "breakout",
    }

    loc_by = _location_by_name(state)
    war_targets: List[dict] = list(state.get("war_targets", []) or [])
    prev_siege_ticks: Dict[str, int] = {}
    prev_siege_by_loc: Dict[str, dict] = {}
    for s in (prev_sw.get("sieges") or []):
        if not isinstance(s, dict):
            continue
        loc = s.get("location", "")
        if not loc:
            continue
        prev_siege_by_loc[str(loc)] = dict(s)
        o = s.get("outcome")
        stl = str(s.get("status", "") or "").lower()
        if o in terminal_outcomes or stl in (
            "breached",
            "surrendered",
            "relief",
            "relieved",
            "broken_out",
        ):
            continue
        if s.get("status") in (None, "active", "sieging", "relief"):
            prev_siege_ticks[loc] = int(s.get("siege_ticks", 0) or 0)

    sieges: List[dict] = []
    besieged: Set[str] = set()
    drain_by: Dict[str, float] = {}

    for wt in war_targets:
        lname = (wt.get("location") or "").strip()
        if not lname or lname not in loc_by:
            continue
        att = (wt.get("attacker", "") or "").strip()
        defe = (wt.get("defender", "") or "").strip()
        if not att or not defe or not _is_at_war(att, defe, state):
            continue
        pvs = prev_siege_by_loc.get(lname, {})
        if pvs.get("outcome") in terminal_outcomes or pvs.get("outcome") in (
            "breach",
            "surrender",
            "surrender_starvation",
            "relief",
            "breakout",
        ):
            continue
        stprev = str(pvs.get("status", "") or "").lower()
        if stprev in ("breached", "surrendered", "relief", "relieved", "broken_out"):
            continue

        reason = str(wt.get("reason", "")).lower()
        loc = loc_by[lname]
        active = bool(loc.get("active_fighting", False))
        r_siege = "siege" in reason
        is_strongpoint = str(loc.get("region_type", "")).lower() in (
            "capital", "fortress", "port", "city", "mine",
        )

        if not (active or r_siege or (is_strongpoint and "pressure" in reason and int(loc.get("control", 50)) < 90)):
            continue

        st = "active"
        ticks = int(prev_siege_ticks.get(lname, 0)) + 1
        g_stock = 0.0
        for row in state.get("faction_economy", []) or []:
            if (row.get("faction_id") or row.get("faction")) == defe:
                g_stock = float((row.get("resources", {}).get("grain") or {}).get("stockpile", 0) or 0)
                break

        drain = 10.0 + min(50.0, 4.0 * ticks) + (25.0 if g_stock < 200 else 0.0)
        drain_by[defe] = drain_by.get(defe, 0.0) + drain

        supp = float(loc.get("stored_supplies", 0) or 0)
        garr = int(loc.get("garrison_size", 0) or 0)
        flc = int(_clamp(int(loc.get("fort_level", 0) or 0), 0, FORT_MAX))
        loc["fort_level"] = flc
        if garr < 1:
            garr = max(10, int(supp * 0.1))
        loc["garrison_size"] = garr

        pr = float(pvs.get("siege_progress_pct", 0) or 0)
        d_morale = float(pvs.get("defender_morale", 78.0) or 78.0)
        if pvs and pvs.get("remaining_supplies") is not None:
            supp = max(0.0, float(pvs.get("remaining_supplies", supp) or 0))
            loc["stored_supplies"] = supp

        att_mil = float(army_manpower_total(att, state) or 0.0)
        if att_mil < 1.0:
            att_mil = 200.0
        # siege_progress += attacker / (fort * 1000); fort 0 = minimal resistance (denom 500)
        den = 500.0 if flc == 0 else float(flc) * 1000.0
        raw = att_mil / den
        slow = 1.0 + (garr / GARR_SUPPLY_SLOW_SCALE) + (supp / SUPPLIES_STOCK_SCALE)
        d_progress = (raw / slow) * SIEGE_PROGRESS_RAW_SCALE
        pr = min(100.0, pr + d_progress)
        d_morale = _clamp(
            d_morale
            - 0.25
            - 0.45 * (1.0 if supp < 400 else 0.0)
            - 0.2 * (pr / 100.0)
            - 0.4 * (1.0 if supp < 120 else 0.0),
            0.0,
            100.0,
        )

        consume = STOCK_CONSUME_BASE + garr * STOCK_CONSUME_PER_GARR + 0.02 * garr * (1.0 - supp / max(1.0, 1200.0 + supp))
        supp = max(0.0, supp - consume)
        if supp < 150.0 and garr > 5:
            garr = int(garr * max(0.7, 1.0 - min(0.2, (150.0 - supp) / 150.0 * 0.12)))
        loc["garrison_size"] = max(0, garr)
        loc["stored_supplies"] = round(supp, 1)

        if supp < 500.0:
            starv = _clamp(1.0 - (supp / 1200.0), 0.0, 1.0)
        elif g_stock < 150.0:
            starv = _clamp(1.0 - (g_stock / 800.0), 0.0, 1.0)
        else:
            starv = max(0, 1.0 - g_stock / 1200.0)
        surrender = _clamp(0.02 * ticks * (0.3 + starv) + 0.1 * starv + 0.12 * (1.0 if supp < 1 else 0.0), 0.0, 0.92)
        w_adv = 0.0
        for wo in state.get("war_outcomes", []) or []:
            if {wo.get("attacker"), wo.get("defender")} == {att, defe}:
                w_adv = float(wo.get("advantage", 0) or 0)
        breakout = _clamp(0.01 + 0.018 * max(0, w_adv + 5), 0.0, 0.4)
        relief = 0.0
        for al in _all_faction_names(state):
            if al in (att, defe):
                continue
            if _is_allied(al, defe, state) and not _is_at_war(al, att, state):
                relief = max(relief, 0.04)
        rarm = _relief_eligible_military(defe, lname, state)
        if rarm > 500:
            relief = min(0.55, relief + 0.08 + min(0.2, rarm / 20000.0))
        elif rarm > 100:
            relief = min(0.4, relief + 0.04)

        eta = 999.0
        if drain > 1 and g_stock > 0:
            eta = g_stock / max(1.0, drain * 0.8)
        if supp > 0 and consume > 0:
            eta = min(eta, supp / max(1.0, consume) * 0.9)

        sieges.append(
            {
                "location": lname,
                "defender": defe,
                "attacker": att,
                "status": st,
                "siege_ticks": ticks,
                "reason": wt.get("reason", ""),
                "control": int(wt.get("control", loc.get("control", 0)) or 0),
                "fort_level": flc,
                "garrison_size": int(loc.get("garrison_size", 0) or 0),
                "siege_progress_pct": round(pr, 2),
                "remaining_supplies": round(supp, 1),
                "defender_morale": round(d_morale, 1),
                "attacker_manpower": int(att_mil),
                "grain_local_proxy": round(g_stock, 1),
                "starvation_index": round(starv, 3),
                "surrender_risk": round(surrender, 3),
                "breakout_risk": round(breakout, 3),
                "relief_risk": round(relief, 3),
                "collapse_eta_ticks": int(min(500, max(0, round(eta)))),
            }
        )
        besieged.add(defe)

    for defe, dtot in list(drain_by.items()):
        drain_by[defe] = round(_clamp(dtot, 5.0, 120.0), 2)
    return sieges, besieged, drain_by


def _all_faction_names(state: dict) -> Set[str]:
    s: Set[str] = set()
    for k in ("faction_identities", "faction_power_state"):
        v = state.get(k)
        if isinstance(v, dict):
            s.update(x for x in v.keys() if x and not str(x).startswith("_"))
    return s


def _apply_siege_to_locations_and_pops(
    state: dict,
    sieges: List[dict],
) -> None:
    locs = {loc.get("name", ""): i for i, loc in enumerate(state.get("locations", []) or []) if loc.get("name")}
    for s in sieges:
        lname = s.get("location", "")
        if lname not in locs:
            continue
        i = locs[lname]
        sl = state["locations"][i]
        stab = int(sl.get("stability", 50) or 50)
        drop = 1 + int(2 * (s.get("starvation_index", 0) or 0))
        sl["stability"] = int(_clamp(stab - drop, 0, 100))
        if int(sl.get("control", 100) or 100) < 5:
            sl["stability"] = int(_clamp((sl.get("stability", 0) or 0) - 1, 0, 100))

    for p in state.get("population_state", []) or []:
        reg = str(p.get("region", ""))
        cult = str(p.get("culture", ""))
        for s in sieges:
            lname = s.get("location", "")
            defe = s.get("defender", "")
            if reg != lname and defe not in cult and lname not in reg:
                continue
            st = s.get("starvation_index", 0) or 0
            pr = int(p.get("pressure", 30) or 30)
            p["pressure"] = int(_clamp(pr + 2 + 8 * st, 0, 100))
            pop = int(p.get("population", 0) or 0)
            if (s.get("grain_local_proxy", 100) or 100) < 30 or st > 0.4:
                loss = max(0, int(pop * (0.0008 + 0.002 * st)))
                p["population"] = max(0, pop - loss)
            mil = int(p.get("activeMilitary", 0) or 0)
            p["activeMilitary"] = max(0, int(mil * (0.99 - 0.02 * st)))


def _roll_outcomes(state: dict, sieges: List[dict], besieged: Set[str]) -> List[dict]:
    events: List[dict] = []
    for s in sieges:
        if s.get("outcome") is not None:
            continue
        lname, defe, att = s.get("location", ""), s.get("defender", ""), s.get("attacker", "")
        spr = float(s.get("siege_progress_pct", 0) or 0)
        rem = float(s.get("remaining_supplies", 0) or 0)
        if spr >= 100.0 - 1e-6:
            s["status"] = "breached"
            s["outcome"] = "breach"
            events.append({"type": "siege_breach", "location": lname, "defender": defe, "attacker": att})
            continue
        r1 = random.random()
        svr = float(s.get("surrender_risk", 0) or 0) * 0.1
        if rem < 0.5:
            svr = min(0.9, svr + 0.22 * (0.5 - min(0.5, rem / 0.5)))
        brk = float(s.get("breakout_risk", 0) or 0) * 0.2
        rlf = float(s.get("relief_risk", 0) or 0) * 0.15
        if rem < 0.05 and r1 < min(0.6, 0.15 + svr * 0.4):
            s["status"] = "surrendered"
            s["outcome"] = "surrender_starvation"
            events.append(
                {
                    "type": "siege_starvation_surrender",
                    "location": lname,
                    "defender": defe,
                    "attacker": att,
                }
            )
            continue
        r = random.random()
        if r < svr:
            s["status"] = "surrendered"
            s["outcome"] = "surrender"
            events.append({"type": "siege_surrender", "location": lname, "defender": defe, "attacker": att})
        elif r < svr + brk:
            s["status"] = "broken_out"
            s["outcome"] = "breakout"
            fps = state.get("faction_power_state", [])
            if isinstance(fps, list):
                for fp in fps:
                    if isinstance(fp, dict) and fp.get("faction") == defe:
                        fp["militaryPower"] = int(
                            _clamp(int(fp.get("militaryPower", 50) or 50) + 1, 0, 100)
                        )
            elif isinstance(fps, dict) and isinstance(fps.get(defe), dict):
                v = fps[defe]
                v["militaryPower"] = int(
                    _clamp(int(v.get("militaryPower", 50) or 50) + 1, 0, 100)
                )
        elif r < svr + brk + rlf:
            s["status"] = "relief"
            s["outcome"] = "relief"
            events.append({"type": "siege_relief", "location": lname, "defender": defe})
    return events


def _military_siege_penalty(state: dict, besieged: Set[str], drain_by: dict) -> None:
    if not besieged:
        return
    fps = state.get("faction_power_state", [])
    if isinstance(fps, list):
        for fp in fps or []:
            if not isinstance(fp, dict):
                continue
            f = fp.get("faction", "")
            if f not in besieged:
                continue
            d = min(6, 1 + (drain_by.get(f, 0) or 0) * 0.04)
            fp["militaryPower"] = int(
                _clamp(int(fp.get("militaryPower", 50) or 50) - d, 0, 100)
            )
            fp["politicalInfluence"] = int(
                _clamp(int(fp.get("politicalInfluence", 50) or 50) - 1, 0, 100)
            )
    elif isinstance(fps, dict):
        for f in besieged:
            v = fps.get(f)
            if not isinstance(v, dict):
                continue
            d = min(6, 1 + (drain_by.get(f, 0) or 0) * 0.04)
            v["militaryPower"] = int(
                _clamp(int(v.get("militaryPower", 50) or 50) - d, 0, 100)
            )
            v["politicalInfluence"] = int(
                _clamp(int(v.get("politicalInfluence", 50) or 50) - 1, 0, 100)
            )


def _compute_blockades(state: dict) -> Tuple[List[dict], float, Dict[str, float]]:
    out: List[dict] = []
    mult = 0.0
    facs = _all_faction_names(state)
    cap_mult: Dict[str, float] = {}
    for f in facs:
        t = _maritime_rival_tension(f, state)
        if t <= 0:
            continue
        out.append(
            {
                "faction": f,
                "strength": round(t, 3),
                "is_coastal": _is_coastal_faction(f, state),
            }
        )
        cap_mult[str(f)] = round(1.0 - min(0.5, t * 0.55), 4)
        mult = max(mult, t * 0.35)
    if not out:
        return out, 1.0, {}
    return out, 1.0 + min(0.45, mult), cap_mult


def process_siege_blockade(state: dict, prev_state: Optional[dict] = None) -> None:
    prev = prev_state or {}
    prev_sw: Dict = prev.get("siege_warfare") or {}
    if not isinstance(prev_sw, dict):
        prev_sw = {}

    ensure_location_fortification_defaults(state)
    sieges, besieged, drain_by = _identify_sieges(state, prev_sw)
    le = list(state.get("location_events", []) or [])

    _apply_siege_to_locations_and_pops(state, sieges)
    _military_siege_penalty(state, besieged, drain_by)
    new_ev = _roll_outcomes(state, sieges, besieged)
    le.extend(new_ev)
    state["location_events"] = le[-40:]

    bl, imp_m, cap_m = _compute_blockades(state)
    n_active = sum(1 for s in sieges if s.get("outcome") is None)

    state["siege_warfare"] = {
        "tick": int(state.get("tick", 0) or 0),
        "sieges": sieges,
        "besieged_factions": sorted(besieged),
        "siege_grain_drain_by_faction": drain_by,
        "no_external_trade_factions": sorted(besieged),
        "active_siege_count": n_active,
        "blockades": bl,
        "import_price_blockade_mult": round(imp_m, 4),
        "blockade_cap_mult_by_faction": cap_m,
    }
    state["siege_grain_drain_by_faction"] = drain_by
    state["besieged_factions"] = list(besieged)
    state["siege_import_mult"] = float(imp_m)
    state["siege_stress_add"] = min(0.2, 0.03 * n_active)


def build_siege_location_export(state: dict) -> List[dict]:
    """Active sieges: progress %, remaining supplies, fort — for API panels."""
    out: List[dict] = []
    for s in (state.get("siege_warfare") or {}).get("sieges") or []:
        if not isinstance(s, dict) or s.get("outcome"):
            continue
        out.append(
            {
                "location": s.get("location", ""),
                "defender": s.get("defender", ""),
                "attacker": s.get("attacker", ""),
                "siege_progress_pct": s.get("siege_progress_pct", 0),
                "remaining_supplies": s.get("remaining_supplies", 0),
                "fort_level": s.get("fort_level", 0),
                "garrison_size": s.get("garrison_size", 0),
                "defender_morale": s.get("defender_morale", 0),
            }
        )
    return out


__all__ = [
    "process_siege_blockade",
    "ensure_location_fortification_defaults",
    "build_siege_location_export",
    "DREADWIND",
    "TIDEFALL",
]
