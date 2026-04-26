"""
Per-tick military posture: which action each faction prioritizes, using army math only.

Priority: survival > supply > defense > expansion.
Narration is a separate layer; this module only returns structured actions + metrics.
"""

from __future__ import annotations

from typing import Any, Dict, List

from economy_simulation import army_manpower_total, list_faction_ids
from econ_trade_routes import _is_at_war  # type: ignore[attr-defined]


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _fac(a: dict) -> str:
    return str(a.get("faction_id") or a.get("faction") or "")


def _military_power_row(f: str, state: dict) -> int:
    for p in state.get("faction_power_state", []) or []:
        if p.get("faction") == f:
            return int(p.get("militaryPower", 50) or 50)
    return 50


def _war_enemies(faction: str, state: dict) -> List[str]:
    out: List[str] = []
    for r in state.get("relationships", []) or []:
        if not isinstance(r, dict) or (r.get("type") or "").lower() != "war":
            continue
        a, b = r.get("faction_a", ""), r.get("faction_b", "")
        if a == faction:
            out.append(b)
        elif b == faction:
            out.append(a)
    return out


def _army_combat_strength(army: dict) -> float:
    m = max(0, int(army.get("manpower", 0) or 0))
    mor = int(army.get("morale", 50) or 50)
    dis = int(army.get("discipline", 50) or 50)
    return float(m) * (max(1, mor) / 100.0) * (max(1, dis) / 100.0)


def _faction_army_strength(f: str, state: dict) -> float:
    t = 0.0
    for a in state.get("faction_armies", []) or []:
        if _fac(a) == f:
            t += _army_combat_strength(a)
    if t < 1.0:
        t = max(1.0, float(army_manpower_total(f, state)) * 0.45)
    return t


def _avg_supply_readiness(armies: List[dict]) -> float:
    if not armies:
        return 50.0
    s = 0.0
    n = 0
    for a in armies:
        s += int(_clamp(int(a.get("supply_level", 50) or 50), 0, 100))
        n += 1
    return s / max(1, n)


def _worst_supply_status(armies: List[dict]) -> tuple[str, int]:
    """Worst of cut > strained > connected; and min supply_level."""
    if not armies:
        return "strained", 0
    rank = {"cut": 3, "strained": 2, "connected": 1}
    w = 0
    label = "connected"
    msup = 100
    for a in armies:
        st = str(a.get("supply_status", "strained") or "strained")
        r = rank.get(st, 0)
        if r > w:
            w = r
            label = st
        msup = min(msup, int(a.get("supply_level", 50) or 50))
    return label, msup


def _terrain_defensive_score(f: str, state: dict) -> float:
    """0..1: holding frozen / mountain / fortress ground."""
    acc = 0.0
    n = 0
    for loc in state.get("locations", []) or []:
        if loc.get("controller") != f:
            continue
        rt = str(loc.get("region_type", "")).lower()
        n += 1
        name = str(loc.get("name", "")).lower()
        if "frost" in name or "frostvale" in name or rt in ("frost", "tundra", "ice", "winter", "winter_fell"):
            acc += 0.4
        elif rt in ("mountain", "mountains", "highlands", "fortress", "fort"):
            acc += 0.35
        elif rt == "capital":
            acc += 0.2
        else:
            acc += 0.05
    if n == 0:
        return 0.0
    return _clamp(acc / n + 0.1 * n / max(3, n), 0.0, 1.0)


def _faction_military_style(f: str) -> Dict[str, float]:
    x = f.lower()
    if "groth" in x:
        return {
            "aggression": 0.92,
            "patience": 0.12,
            "defend_home": 0.22,
            "siege_focus": 0.45,
            "supply_priority": 0.4,
            "expansion": 0.9,
            "weak_pick": 0.55,
        }
    if "gilgeth" in x:
        return {
            "aggression": 0.38,
            "patience": 0.75,
            "defend_home": 0.45,
            "siege_focus": 0.88,
            "supply_priority": 0.65,
            "expansion": 0.4,
            "weak_pick": 0.4,
        }
    if "twin" in x or "twin cities" in x:
        return {
            "aggression": 0.28,
            "patience": 0.55,
            "defend_home": 0.9,
            "siege_focus": 0.4,
            "supply_priority": 0.7,
            "expansion": 0.25,
            "weak_pick": 0.2,
        }
    if "farrock" in x or "lostfeld" in x or "dwarf" in x:
        return {
            "aggression": 0.5,
            "patience": 0.4,
            "defend_home": 0.35,
            "siege_focus": 0.55,
            "supply_priority": 0.55,
            "expansion": 0.88,
            "weak_pick": 0.85,
        }
    if "wintermark" in x or "frostvale" in x or "adkison" in x:
        return {
            "aggression": 0.32,
            "patience": 0.5,
            "defend_home": 0.95,
            "siege_focus": 0.35,
            "supply_priority": 0.6,
            "expansion": 0.18,
            "weak_pick": 0.2,
        }
    return {
        "aggression": 0.45,
        "patience": 0.5,
        "defend_home": 0.5,
        "siege_focus": 0.5,
        "supply_priority": 0.55,
        "expansion": 0.5,
        "weak_pick": 0.5,
    }


def _weakest_war_enemy(f: str, state: dict) -> tuple[str, float]:
    best_e = ""
    best_s = 1e12
    for e in _war_enemies(f, state):
        es = _faction_army_strength(e, state)
        if es < best_s and es > 0:
            best_s = es
            best_e = e
    if not best_e:
        for e in _war_enemies(f, state):
            es = _faction_army_strength(e, state)
            if es < best_s:
                best_s = es
                best_e = e
    return (best_e, best_s)


def _active_attacking_siege(f: str, state: dict) -> Optional[dict]:
    for s in (state.get("siege_warfare") or {}).get("sieges") or []:
        if not isinstance(s, dict) or s.get("outcome"):
            continue
        if s.get("attacker") == f and float(s.get("siege_progress_pct", 0) or 0) < 99.0:
            return s
    return None


def _threatens_capital(our_f: str, state: dict) -> bool:
    for loc in state.get("locations", []) or []:
        if loc.get("controller") != our_f:
            continue
        if str(loc.get("region_type", "")).lower() not in ("capital", "fortress"):
            continue
        lname = str(loc.get("name", ""))
        for wt in state.get("war_targets", []) or []:
            if (wt.get("location") or "") == lname and wt.get("defender") == our_f:
                return True
    return False


def _choose_action(
    f: str,
    state: dict,
    my_armies: List[dict],
) -> tuple[str, str, Dict[str, Any]]:
    stl = dict(_faction_military_style(f))
    for loc in state.get("locations", []) or []:
        if loc.get("controller") != f:
            continue
        if "farrock" in str(loc.get("name", "")).lower():
            stl["expansion"] = max(float(stl.get("expansion", 0.5)), 0.88)
            stl["weak_pick"] = max(float(stl.get("weak_pick", 0.5)), 0.82)
            break

    ours = _faction_army_strength(f, state)
    enemies = _war_enemies(f, state)
    if my_armies:
        worst_s, msup = _worst_supply_status(my_armies)
        avg_sup = _avg_supply_readiness(my_armies)
    else:
        worst_s, msup = "connected", 50
        avg_sup = 50.0
    tscore = _terrain_defensive_score(f, state)
    pwr = _military_power_row(f, state)

    meta: Dict[str, Any] = {
        "army_strength": round(ours, 2),
        "enemy_factions": list(enemies),
        "military_power": pwr,
        "terrain_advantage": round(tscore, 3),
        "avg_supply_level": round(avg_sup, 1),
        "worst_supply_status": worst_s,
        "min_supply_level": msup,
    }

    if not enemies:
        if worst_s == "cut" or msup < 30:
            return "protect_supply_lines", "no_war_trains", meta
        if tscore > 0.45:
            return "defend_key_regions", "terrain_hold", meta
        return "hold_position", "peace", meta

    e_tot = 0.0
    for e in enemies:
        e_tot += _faction_army_strength(e, state)
    meta["aggregate_enemy_strength"] = round(e_tot, 2)

    w_en, w_es = _weakest_war_enemy(f, state)
    ratio = ours / (w_es + 1.0) if w_es > 0 else 2.0
    meta["weakest_enemy"] = w_en
    meta["weakest_enemy_strength"] = round(w_es, 2)
    meta["strength_ratio_vs_weakest"] = round(ratio, 3)

    threat = _threatens_capital(f, state) or (e_tot > ours * 1.08 and ratio < 1.0)

    # 1) Survival: catastrophic logistics or morale collapse risk
    if msup < 12 or (worst_s == "cut" and msup < 25):
        return "retreat_to_safety", "logistics_collapse", meta

    # 2) Supply: strained across the line
    if worst_s in ("cut", "strained") and avg_sup < 40 and msup < 45:
        if stl.get("supply_priority", 0.5) > 0.35 or msup < 32:
            return "protect_supply_lines", "sustain_trains", meta

    # 3) Defense: threatened core or outmatched on paper
    if threat or (ratio < 0.92 and stl.get("defend_home", 0.5) > 0.65):
        return "defend_key_regions", "core_or_disadvantage", meta
    if tscore > 0.5 and (stl.get("defend_home", 0.5) > 0.7 or "winter" in f.lower() or "frost" in f.lower()):
        return "defend_key_regions", "use_terrain", meta

    # 4) Siege: reinforce active offensive siege (Gilgeth leans in)
    sg = _active_attacking_siege(f, state)
    if sg and (stl.get("siege_focus", 0.5) > 0.55 or ratio > 0.9):
        meta["siege_location"] = sg.get("location", "")
        meta["siege_progress_pct"] = sg.get("siege_progress_pct", 0)
        return "reinforce_siege", "active_siege", meta

    # 5) Expansion: attack if advantage — aggressive / expansionist
    need = 1.02 - 0.25 * stl.get("aggression", 0.5) - 0.2 * stl.get("expansion", 0.5) + 0.15 * (1.0 - stl.get("patience", 0.5))
    need2 = 0.9 + 0.15 * (1.0 - stl.get("weak_pick", 0.5))  # need stronger edge to hit weak
    attack_ok = ratio > max(need, need2 * 0.95) and w_en and w_es < ours * 0.99
    if stl.get("aggression", 0.5) > 0.8:
        attack_ok = ratio > 0.88 and w_en
    if "twin" in f.lower() and not threat and ratio < 1.12:
        attack_ok = False
    if ("winter" in f.lower() or "frostvale" in f.lower()) and tscore > 0.45 and not threat:
        attack_ok = False
    if attack_ok:
        meta["target_faction"] = w_en
        return "attack_weaker_target", "advantage", meta

    if worst_s == "strained" and avg_sup < 48:
        return "protect_supply_lines", "prevent_cutoff", meta

    return "hold_position", "assess", meta


def _merge_military_faction_decisions_history(state: dict) -> None:
    decs = state.get("military_faction_decisions") or []
    t = int(state.get("tick", 0) or 0)
    for h in reversed(state.get("tick_history") or []):
        if h.get("tick") == t:
            h["military_faction_decisions"] = decs
            break


def run_military_faction_decisions(state: dict) -> None:
    """Populate state['military_faction_decisions'] with one record per faction."""
    t = int(state.get("tick", 0) or 0)
    if state.get("_military_faction_decisions_tick") == t:
        return
    state["_military_faction_decisions_tick"] = t

    factions = list_faction_ids(state)[:32]
    by_fac: Dict[str, List[dict]] = {}
    for a in state.get("faction_armies", []) or []:
        ff = _fac(a)
        if ff:
            by_fac.setdefault(ff, []).append(a)

    out: List[dict] = []
    for f in factions:
        arm = by_fac.get(f, [])
        act, rsn, meta = _choose_action(f, state, arm)
        # Map to priority band
        if act == "retreat_to_safety":
            band = "survival"
        elif act == "protect_supply_lines":
            band = "supply"
        elif act in ("defend_key_regions",):
            band = "defense"
        else:
            band = "expansion" if act in ("attack_weaker_target", "reinforce_siege") else "defense"
        if act == "hold_position" and rsn == "peace":
            band = "defense"
        out.append(
            {
                "faction": f,
                "priority_tier": band,
                "action": act,
                "reason": rsn,
                "summary": _summary_line(f, act, rsn, meta),
                "meta": meta,
            }
        )
    state["military_faction_decisions"] = out
    _merge_military_faction_decisions_history(state)


def _summary_line(f: str, act: str, rsn: str, meta: Dict[str, Any]) -> str:
    t = meta.get("target_faction") or meta.get("siege_location")
    if act == "attack_weaker_target" and t:
        return f"{f} commits to a strike on {t} while it holds a margin of strength."
    if act == "reinforce_siege" and meta.get("siege_location"):
        return f"{f} diverts more weight to the siege at {meta.get('siege_location')}."
    if act == "protect_supply_lines":
        return f"{f} prioritizes convoys, depots, and line security over field gambits."
    if act == "defend_key_regions":
        return f"{f} shores up citadels and borders; taking ground can wait."
    if act == "retreat_to_safety":
        return f"{f} shortens the front and pulls toward safer magazines."
    return f"{f} holds, probes, and waits for a clearer edge."


__all__ = ["run_military_faction_decisions", "_faction_military_style"]
