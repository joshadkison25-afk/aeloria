"""
Covert operations: spy networks, sabotage, assassination hooks, intel, blackmail.

State:
  faction_intrigue  — rows with spy_networks[target] = { network_strength: 0–100, exposure: 0–100 }
  intrigue_pending  — in-flight operations (gold paid upfront, ticks to resolve)
  intrigue_actions  — this tick’s completed / failed / progress events
  spy_networks      — flattened [ { ..., defender_counter_intelligence, detection_risk } ] per edge
  assassination_reports — [ { assassination_attempt, success, exposure, consequences } ] per attempt
  sabotage_reports   — [ { sabotage_event, target, impact } ] per resolution
  blackmail_reports  — [ { blackmail_target, success, forced_action } ] per resolution
  active_blackmail_coercion — { target_faction, source_faction, character, expires_tick } (diplomatic nudge)
  counter_intelligence  — per faction 0–100 in each faction_intrigue row (defensive CI)
  counterintelligence_report — { detected_actions, exposed_factions, penalties } (tick summary)
  intrigue_decisions — per-tick { source_faction, target_faction, action, agent_intelligence, culture, target_avg_stability, … } from goal/culture weighting
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections import defaultdict
from typing import Any, DefaultDict, Dict, List, Optional, Tuple

from economy_simulation import list_faction_ids

__all__ = ["run_intrigue_system", "DEFAULT_INTRIGUE_CONFIG"]

DEFAULT_INTRIGUE_CONFIG: Dict[str, Any] = {
    "min_intelligence_spy": 32,
    "min_intelligence_sabotage": 42,
    "min_intelligence_assassination": 58,
    "min_intelligence_intel": 28,
    "min_intelligence_blackmail": 40,
    "base_gold_spy": 55,
    "base_gold_sabotage": 140,
    "base_gold_assassination": 320,
    "base_gold_intel": 38,
    "base_gold_blackmail": 75,
    "ticks_spy": 2,
    "ticks_sabotage": 3,
    "ticks_assassination": 4,
    "ticks_intel": 1,
    "ticks_blackmail": 2,
    "max_ops_per_faction": 1,
    "max_completions_per_tick": 6,
    "max_new_starts_per_tick": 3,
    "start_new_probability": 0.42,
    "detection_baseline": 0.14,
    "max_pending": 32,
    "ruler_target_weight": 0.15,
    "network_passive_growth": 0.45,
    "exposure_on_failed_action": 7.0,
    "exposure_on_detected": 3.0,
    "exposure_on_failed_traced": 10.0,
    "exposure_tick_decay": 0.42,
    "sabotage_network_bonus": 0.0019,
    "assassination_network_bonus": 0.0022,
    "detection_strength_mitigation": 0.0048,
    "detection_exposure_amplification": 0.0052,
    "detection_risk_baseline": 38,
    "detection_risk_exposure": 0.48,
    "detection_risk_strength": 0.5,
    "max_network_edges_per_faction": 24,
    "assassination_min_network_strength": 18,
    "assassination_roll_denom_k": 1.08,
    "assassination_failure_exposure_extra": 6.0,
    "assassination_war_exposure_threshold": 70,
    "assassination_war_probability_scale": 0.42,
    "assassination_trust_loss_base": 10,
    "assassination_hostility_gain_base": 8,
    "assassination_legitimacy_per_exposure": 0.12,
    "assassination_legitimacy_base_hit": 2.5,
    "assassination_commander_morale_penalty": 12,
    "sabotage_base_p": 0.14,
    "sabotage_intelligence_scale": 0.0036,
    "sabotage_network_scale": 0.0025,
    "sabotage_failure_detection_extra": 5.0,
    "sabotage_min_network_strength": 6,
    "sabotage_supply_level_hit": 14,
    "sabotage_trade_cap_mult": 0.78,
    "sabotage_trade_disrupted_ticks": 4,
    "sabotage_price_stress_add": 0.038,
    "sabotage_fort_level_drop": 1,
    "sabotage_fort_restore_in_ticks": 5,
    "sabotage_production_mult": 0.94,
    "blackmail_base_p": 0.16,
    "blackmail_intelligence_scale": 0.0034,
    "blackmail_network_scale": 0.0022,
    "blackmail_morality_resist": 0.00135,
    "blackmail_loyalty_resist": 0.00095,
    "blackmail_ruler_penalty": 0.042,
    "blackmail_min_network_strength": 8,
    "blackmail_failure_exposure_extra": 6.0,
    "blackmail_fail_legitimacy_hit": 3.2,
    "blackmail_coercion_diplomacy_ticks": 6,
    "blackmail_loyalty_delta_lo": 4,
    "blackmail_loyalty_delta_hi": 9,
    "blackmail_betrayal_trust_lo": 6,
    "blackmail_betrayal_trust_hi": 14,
    "ci_infiltrate_dampen": 0.32,
    "ci_op_detect_mult": 0.34,
    "ci_def_intel_op_mult": 0.14,
    "ci_op_network_weaken_on_detected": 0.11,
    "ci_sabotage_det_scale": 0.28,
    "ci_sabotage_intel_scale": 0.09,
    "ci_sweep_base_p": 0.014,
    "ci_sweep_on_ci": 0.0014,
    "ci_sweep_on_def_intel": 0.00075,
    "ci_sweep_on_network": 0.001,
    "ci_sweep_p_cap": 0.19,
    "ci_sweep_min_network": 5,
    "ci_sweep_weaken_min": 6,
    "ci_sweep_weaken_max": 14,
    "ci_sweep_exposure_bump": 8,
    "ci_sweep_trust_hit": 5,
    "ci_sweep_hostility_bump": 6,
    "ci_sweep_retaliation_p": 0.36,
    "ci_sweep_gold_drain_p": 0.24,
    "ci_sweep_gold_max": 28,
    "ci_defender_gain_on_intercept": 1,
    "intrigue_start_intel_scale": 0.002,
    "intrigue_start_farrock_mult": 0.64,
    "intrigue_start_faerwood_mult": 1.12,
    "intrigue_start_twin_mult": 0.92,
}

ACTION_TYPES = (
    "spy_network_expansion",
    "sabotage",
    "assassination",
    "information_gathering",
    "blackmail",
)

SABOTAGE_KINDS = (
    "supply_sabotage",
    "trade_disruption",
    "infrastructure_damage",
)

# Outcomes when leverage lands (or failure tag)
BLACKMAIL_FORCED_ACTIONS = (
    "forced_loyalty",
    "forced_betrayal",
    "diplomatic_leverage",
)

_W_ACTION = {
    "spy_network_expansion": 0.9,
    "sabotage": 1.1,
    "assassination": 1.35,
    "information_gathering": 0.75,
    "blackmail": 1.0,
}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _coerce_network_cell(raw: Any) -> Dict[str, int]:
    """Legacy int or dict → { network_strength, exposure }."""
    if isinstance(raw, dict):
        ns = int(_clamp(float(raw.get("network_strength", raw.get("strength", 0) or 0)), 0, 100))
        ex = int(_clamp(float(raw.get("exposure", 0) or 0), 0, 100))
        return {"network_strength": ns, "exposure": ex}
    try:
        ns = int(_clamp(float(raw or 0), 0, 100))
    except (TypeError, ValueError):
        ns = 0
    return {"network_strength": ns, "exposure": 0}


def _get_cell(source_row: dict, target: str) -> Dict[str, int]:
    sm = source_row.get("spy_networks") or {}
    if not isinstance(sm, dict):
        return {"network_strength": 0, "exposure": 0}
    return _coerce_network_cell(sm.get(target, 0))


def _set_cell(source_row: dict, target: str, cell: Dict[str, int]) -> None:
    source_row.setdefault("spy_networks", {})
    if not isinstance(source_row["spy_networks"], dict):
        source_row["spy_networks"] = {}
    ns = int(_clamp(float(cell.get("network_strength", 0) or 0), 0, 100))
    ex = int(_clamp(float(cell.get("exposure", 0) or 0), 0, 100))
    source_row["spy_networks"][target] = {"network_strength": ns, "exposure": ex}


def _detection_risk_for_edge(ns: int, exposure: int, cfg: dict) -> int:
    """0–100: how visible / catchable this network is to the target (higher = worse for spymaster)."""
    base = float(cfg.get("detection_risk_baseline", 38) or 38)
    we = float(cfg.get("detection_risk_exposure", 0.48) or 0.48)
    ws = float(cfg.get("detection_risk_strength", 0.5) or 0.5)
    v = base + we * float(exposure) - ws * float(ns)
    return int(_clamp(v, 0, 100))


def _visibility_into_target(ns: int, exposure: int) -> int:
    """0–100 intelligence reach for the source into the target (for intel quality)."""
    vis = float(ns) * (1.0 - 0.35 * (float(exposure) / 100.0))
    return int(_clamp(vis, 0, 100))


def _row_for_faction(
    faction: str, by_f: Optional[Dict[str, dict]], state: dict
) -> dict:
    if by_f:
        r = by_f.get(faction)
        if isinstance(r, dict):
            return r
    for r in state.get("faction_intrigue") or []:
        if isinstance(r, dict) and (r.get("faction") or "").strip() == faction:
            return r
    return {}


def _average_faction_intelligence(faction: str, state: dict) -> int:
    vals: List[int] = []
    for ch in state.get("house_characters") or []:
        if not isinstance(ch, dict) or (ch.get("faction") or "") != faction:
            continue
        vals.append(int(ch.get("intelligence", 50) or 50))
    if not vals:
        return 45
    return int(sum(vals) / max(1, len(vals)))


def _defender_counterintel_for_op(
    target: str, by_f: Optional[Dict[str, dict]], state: dict
) -> Tuple[int, int]:
    r = _row_for_faction(target, by_f, state)
    dci = int(_clamp(float(r.get("counter_intelligence", 40) or 40), 0, 100))
    dintel = _average_faction_intelligence(target, state)
    return dci, dintel


def _counterintel_sweep_p(ns: int, dci: int, dintel: int, cfg: dict) -> float:
    p = float(cfg.get("ci_sweep_base_p", 0.014) or 0.014) + float(
        cfg.get("ci_sweep_on_ci", 0.0014) or 0
    ) * dci + float(
        cfg.get("ci_sweep_on_def_intel", 0.00075) or 0
    ) * dintel + float(
        cfg.get("ci_sweep_on_network", 0.001) or 0
    ) * float(ns)
    return _clamp(p, 0.002, float(cfg.get("ci_sweep_p_cap", 0.19) or 0.19))


def _migrate_spy_networks_map(sm: Any) -> Dict[str, Dict[str, int]]:
    if not isinstance(sm, dict):
        return {}
    out: Dict[str, Dict[str, int]] = {}
    for tgt, raw in sm.items():
        if not tgt:
            continue
        out[str(tgt)] = _coerce_network_cell(raw)
    return out


def _trim_spy_network_row(row: dict, max_edges: int) -> None:
    sm = row.get("spy_networks")
    if not isinstance(sm, dict) or len(sm) <= max_edges:
        return
    items = sorted(
        sm.items(), key=lambda kv: _coerce_network_cell(kv[1])["network_strength"]
    )
    for tgt, _ in items[: max(0, len(items) - max_edges)]:
        sm.pop(tgt, None)


def _apply_spy_network_passive_tick(
    by_f: Dict[str, dict], fids: List[str], cfg: dict
) -> None:
    """Passive network growth (cap 100) and exposure decay; mutates by_f in place."""
    g0 = float(cfg.get("network_passive_growth", 0.45) or 0.45)
    dec = float(cfg.get("exposure_tick_decay", 0.42) or 0.42)
    for fid, row in by_f.items():
        il = float(row.get("intrigue_level", 30) or 30)
        sm = row.get("spy_networks")
        if not isinstance(sm, dict):
            continue
        for tgt in list(sm.keys()):
            ts = str(tgt)
            if ts not in fids or ts == fid:
                sm.pop(tgt, None)
                continue
            cell = _get_cell(row, ts)
            ns = float(cell["network_strength"])
            ex = float(cell["exposure"])
            trow = by_f.get(ts) or {}
            dci = float(
                (trow.get("counter_intelligence", 40) or 40)
            ) / 100.0
            dampen = 1.0 - float(
                cfg.get("ci_infiltrate_dampen", 0.32) or 0.32
            ) * dci
            dampen = _clamp(dampen, 0.45, 1.0)
            if ns > 0.5:
                gr = g0 * (0.82 + 0.18 * (il / 100.0)) * dampen
                ns = min(100.0, ns + gr * (1.0 - ns / 100.0))
            ex = max(0.0, ex - dec)
            _set_cell(row, ts, {"network_strength": int(_clamp(ns, 0, 100)), "exposure": int(_clamp(ex, 0, 100))})


def _apply_counterintelligence_sweep(
    state: dict,
    by_f: Dict[str, dict],
    cfg: dict,
    tick: int,
) -> Dict[str, Any]:
    """
    Periodic chance that defender intelligence + counter-espionage catches foreign networks.
    Weakens the attacker's network edge, applies trust/hostility, optional retaliation and gold.
    """
    detected_actions: List[dict] = []
    penalties: List[dict] = []
    exposed = set()
    min_ns = int(cfg.get("ci_sweep_min_network", 5) or 5)
    wmin = int(cfg.get("ci_sweep_weaken_min", 6) or 6)
    wmax = int(cfg.get("ci_sweep_weaken_max", 14) or 14)
    gmax = int(cfg.get("ci_sweep_gold_max", 28) or 28)

    for source, srow in by_f.items():
        if not isinstance(srow, dict) or not source:
            continue
        sm = srow.get("spy_networks") or {}
        if not isinstance(sm, dict):
            continue
        for target, raw in list(sm.items()):
            ts = str(target)
            cell = _coerce_network_cell(raw)
            ns = int(cell["network_strength"])
            ex = int(cell["exposure"])
            if ns < min_ns:
                continue
            trow = by_f.get(ts) or {}
            dci = int(
                _clamp(
                    float(trow.get("counter_intelligence", 40) or 40),
                    0,
                    100,
                )
            )
            dintel = _average_faction_intelligence(ts, state)
            p = _counterintel_sweep_p(ns, dci, dintel, cfg)
            if random.random() >= p:
                continue

            cut = random.randint(wmin, wmax) + int(0.06 * float(dci))
            ns2 = int(max(0, ns - cut))
            ex2 = int(
                min(100, ex + int(cfg.get("ci_sweep_exposure_bump", 8) or 8))
            )
            _set_cell(srow, ts, {"network_strength": ns2, "exposure": ex2})
            exposed.add(str(source))
            th = int(cfg.get("ci_sweep_trust_hit", 5) or 5)
            hh = int(cfg.get("ci_sweep_hostility_bump", 6) or 6)
            for rel in state.get("relationships") or []:
                if not isinstance(rel, dict):
                    continue
                a, b = (rel.get("faction_a") or ""), (rel.get("faction_b") or "")
                if a and b and {a, b} == {str(source), ts}:
                    tr = int(rel.get("trust", 50) or 50)
                    ho = int(rel.get("hostility", 20) or 20)
                    rel["trust"] = max(0, tr - th)
                    rel["hostility"] = min(100, ho + hh)
                    break
            if random.random() < float(
                cfg.get("ci_sweep_gold_drain_p", 0.24) or 0.24
            ):
                amt = 8 + int(random.random() * max(1, gmax - 8))
                if _spend_gold(str(source), amt, state):
                    penalties.append(
                        {
                            "kind": "seized_operational_gold",
                            "faction": str(source),
                            "amount": amt,
                            "reason": f"Counter-intel interdicts {ts}.",
                        }
                    )
            if random.random() < float(
                cfg.get("ci_sweep_retaliation_p", 0.36) or 0.36
            ):
                at = list(state.get("active_tensions") or [])
                at.append(
                    {
                        "tick": tick,
                        "source": "counterintelligence",
                        "parties": [str(source), ts],
                        "severity": 5,
                        "summary": f"{ts} retaliates diplomatically after exposing foreign assets linked to {source}.",
                    }
                )
                state["active_tensions"] = at[-24:]
                penalties.append(
                    {
                        "kind": "retaliation_tension",
                        "from_faction": ts,
                        "against": str(source),
                    }
                )
            dg = int(cfg.get("ci_defender_gain_on_intercept", 1) or 1)
            if ts in by_f and isinstance(by_f[ts], dict):
                o = int(
                    (by_f[ts] or {}).get("counter_intelligence", 40) or 40
                )
                (by_f[ts])["counter_intelligence"] = int(
                    min(100, o + dg)
                )
            detected_actions.append(
                {
                    "kind": "network_intercept",
                    "source_faction": str(source),
                    "target_faction": ts,
                    "network_strength_after": ns2,
                    "defender_intelligence_rollup": dintel,
                    "defender_counter_intelligence": dci,
                }
            )
            penalties.append(
                {
                    "kind": "diplomatic",
                    "source_faction": str(source),
                    "target_faction": ts,
                    "trust_drop": th,
                    "hostility_rise": hh,
                }
            )

    return {
        "detected_actions": detected_actions[-32:],
        "exposed_factions": sorted(exposed)[:20],
        "penalties": penalties[-48:],
    }


def _find_house_char(name: str, faction: str, state: dict) -> Optional[dict]:
    n = (name or "").strip()
    if not n:
        return None
    for ch in state.get("house_characters") or []:
        if not isinstance(ch, dict):
            continue
        if (ch.get("faction") or "") != faction:
            continue
        if (ch.get("name") or "").strip() == n:
            return ch
    return None


def _victim_is_ruler(name: str, faction: str, state: dict) -> bool:
    for ls in state.get("leadership_state") or []:
        if not isinstance(ls, dict) or (ls.get("faction") or "") != faction:
            continue
        r = ls.get("currentRuler") or {}
        if (r.get("name") or "").strip() == (name or "").strip():
            return True
    return False


def _commander_fallen_in_armies(
    name: str, faction: str, state: dict, morale_pen: int
) -> List[dict]:
    out: List[dict] = []
    n = (name or "").strip()
    if not n:
        return out
    arms = list(state.get("faction_armies") or [])
    for i, a in enumerate(arms):
        if not isinstance(a, dict):
            continue
        if (a.get("faction_id") or "") != faction:
            continue
        if (a.get("commander") or "").strip() != n:
            continue
        m0 = int(a.get("morale", 60) or 60)
        a["morale"] = max(0, m0 - morale_pen)
        a["commander"] = None
        arms[i] = a
        out.append(
            {
                "army_id": a.get("army_id"),
                "faction": faction,
                "commander_cleared": True,
            }
        )
    state["faction_armies"] = arms
    return out


def _assassination_exposure_consequences(
    source: str, target: str, exposure: int, state: dict, cfg: dict
) -> dict:
    from marriage_succession import _find_rel, _ensure_rel

    cons: Dict[str, Any] = {"trust": None, "war": None, "legitimacy": None}
    r = _find_rel(state, source, target) or _ensure_rel(state, source, target)
    if not r:
        return cons
    tr0 = int(r.get("trust", 50) or 50)
    ho0 = int(r.get("hostility", 20) or 20)
    tb = int(cfg.get("assassination_trust_loss_base", 10) or 10)
    hb = int(cfg.get("assassination_hostility_gain_base", 8) or 8)
    tloss = min(45, tb + int(exposure) // 6)
    hgain = min(40, hb + int(exposure) // 8)
    r["trust"] = max(0, tr0 - tloss)
    r["hostility"] = min(100, ho0 + hgain)
    cons["trust"] = {
        "before": tr0,
        "after": r["trust"],
        "change": r["trust"] - tr0,
    }
    th = int(cfg.get("assassination_war_exposure_threshold", 70) or 70)
    ps = float(cfg.get("assassination_war_probability_scale", 0.42) or 0.42)
    w_roll = random.random() < ps * (float(exposure) / 100.0) ** 1.15
    if (exposure >= th or w_roll) and (r.get("type") or "") not in ("war", "alliance"):
        r["type"] = "war"
        r["intensity"] = int(
            _clamp(float(int(r.get("intensity", 50) or 50) + 18), 0, 100)
        )
        cons["war"] = {
            "triggered": True,
            "parties": [source, target],
        }
    rs = state.setdefault("ruler_legitimacy_scores", {})
    if not isinstance(rs, dict):
        rs = {}
        state["ruler_legitimacy_scores"] = rs
    base_hit = float(cfg.get("assassination_legitimacy_base_hit", 2.5) or 2.5)
    per = float(cfg.get("assassination_legitimacy_per_exposure", 0.12) or 0.12)
    if source in rs:
        h = base_hit + per * float(exposure)
        rs[source] = max(0.0, min(100.0, float(rs[source] or 50) - h))
    cons["legitimacy"] = {
        "attacker_legitimacy_penalty": round(base_hit + per * float(exposure), 2)
    }
    at = list(state.get("active_tensions") or [])
    at.append(
        {
            "tick": int(state.get("tick", 0) or 0),
            "source": "assassination_exposed",
            "parties": [source, target],
            "severity": min(15, 4 + int(exposure) // 15),
            "summary": f"Exposed plot strains relations between {source} and {target}.",
        }
    )
    state["active_tensions"] = at[-24:]
    return cons


def _fid(row: dict) -> str:
    return str(row.get("faction_id") or row.get("faction") or "").strip()


def _gold_stockpile(faction: str, state: dict) -> int:
    for row in state.get("faction_economy") or []:
        if not isinstance(row, dict):
            continue
        if _fid(row) != faction:
            continue
        g = ((row.get("resources") or {}).get("gold") or {}).get("stockpile", 0)
        try:
            return int(g)
        except (TypeError, ValueError):
            return 0
    return 0


def _spend_gold(faction: str, amount: int, state: dict) -> bool:
    if amount < 1:
        return True
    rows = list(state.get("faction_economy") or [])
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or _fid(row) != faction:
            continue
        res = row.setdefault("resources", {})
        g = res.setdefault("gold", {"stockpile": 0, "storage_capacity": 5000, "production": 0, "consumption": 0})
        cur = int(g.get("stockpile", 0) or 0)
        if cur < amount:
            return False
        g["stockpile"] = int(max(0, cur - amount))
        rows[i] = row
        state["faction_economy"] = rows
        return True
    return False


def _iter_relations(fa: str, state: dict) -> List[Tuple[str, int, str]]:
    out: List[Tuple[str, int, str]] = []
    for r in state.get("relationships") or []:
        if not isinstance(r, dict):
            continue
        a, b = (r.get("faction_a") or ""), (r.get("faction_b") or "")
        if a == fa:
            out.append((b, int(r.get("trust", 50) or 50), str(r.get("type") or "neutral")))
        elif b == fa:
            out.append((a, int(r.get("trust", 50) or 50), str(r.get("type") or "neutral")))
    return out


def _location_avg_stability(faction: str, state: dict) -> float:
    vals: List[int] = []
    for loc in state.get("locations") or []:
        if not isinstance(loc, dict):
            continue
        if (loc.get("controller") or "") != faction:
            continue
        vals.append(
            int(loc.get("stability", loc.get("control", 50)) or 50)
        )
    if not vals:
        return 50.0
    return float(sum(vals)) / float(len(vals))


def _rel_pair(
    source: str, other: str, state: dict
) -> dict:
    for r in state.get("relationships") or []:
        if not isinstance(r, dict):
            continue
        a, b = (r.get("faction_a") or ""), (r.get("faction_b") or "")
        if a and b and {a, b} == {source, other}:
            return r
    return {}


def _all_action_weights_unity() -> Dict[str, float]:
    return {a: 1.0 for a in ACTION_TYPES}


def _intrigue_culture_action_weights(
    faction: str,
) -> Dict[str, float]:
    """Culture-specific bias toward each intrigue action (Faerwood heavy, Farrock light, etc.)."""
    w = _all_action_weights_unity()
    u = (faction or "").lower()
    if any(x in u for x in ("faerwood", "shadow", "verlorn")) and "dread" not in u:
        w["spy_network_expansion"] *= 1.5
        w["blackmail"] *= 1.4
        w["assassination"] *= 1.2
        w["information_gathering"] *= 1.15
    elif "eldoria" in u or "lefleur" in u:
        w["blackmail"] *= 1.5
        w["information_gathering"] *= 1.4
        w["spy_network_expansion"] *= 1.2
    elif "twin" in u or "aurand" in u or "eresteron" in u:
        w["information_gathering"] *= 1.4
        w["spy_network_expansion"] *= 1.25
        w["sabotage"] *= 0.75
        w["assassination"] *= 0.7
    elif "tidefall" in u or "dreadwind" in u or "isles" in u or "ver meer" in u or "blacktide" in u:
        w["information_gathering"] *= 1.2
        w["spy_network_expansion"] *= 1.1
        w["sabotage"] *= 1.08
        w["assassination"] *= 0.92
    elif "farrock" in u or "lostfeld" in u:
        w["assassination"] *= 1.2
        w["sabotage"] *= 0.8
        w["blackmail"] *= 0.65
        w["spy_network_expansion"] *= 0.55
        w["information_gathering"] *= 0.7
    elif "vilefin" in u or "bloodware" in u or "cogtooth" in u or "rustfang" in u:
        w["sabotage"] *= 1.6
        w["assassination"] *= 1.15
        w["blackmail"] *= 0.85
        w["information_gathering"] *= 0.9
    return w


def _goal_action_weights(
    source: str, target: str, state: dict
) -> Dict[str, float]:
    """Favor destabilization vs rivals/war, quiet intel vs low hostility."""
    w = _all_action_weights_unity()
    r = _rel_pair(source, target, state)
    h = int(r.get("hostility", 20) or 20)
    tru = int(r.get("trust", 50) or 50)
    t = (r.get("type") or "neutral")
    if t == "war" or h > 72:
        w["sabotage"] *= 1.5
        w["assassination"] *= 1.35
        w["blackmail"] *= 0.88
    elif t == "rivalry" or (h > 50 and tru < 40):
        w["sabotage"] *= 1.3
        w["blackmail"] *= 1.25
        w["assassination"] *= 1.1
    if tru > 60 and h < 32 and t != "war":
        w["information_gathering"] *= 1.25
        w["spy_network_expansion"] *= 1.15
        w["sabotage"] *= 0.5
        w["assassination"] *= 0.3
    return w


def _intel_agent_action_weights(itel: int) -> Dict[str, float]:
    w = _all_action_weights_unity()
    if itel >= 58:
        w["assassination"] *= 1.25
        w["blackmail"] *= 1.2
        w["sabotage"] *= 1.1
    elif itel < 40:
        w["information_gathering"] *= 1.3
        w["spy_network_expansion"] *= 1.2
        w["assassination"] *= 0.4
    return w


def _stability_target_action_weights(
    target: str, state: dict
) -> Dict[str, float]:
    """Unstable target territory favors hard covert pressure."""
    s = _location_avg_stability(target, state)
    destab = (72.0 - s) / 72.0
    destab = _clamp(destab, 0.0, 1.0)
    w = _all_action_weights_unity()
    w["sabotage"] *= 1.0 + 0.5 * destab
    w["blackmail"] *= 1.0 + 0.42 * destab
    w["assassination"] *= 1.0 + 0.32 * destab
    w["information_gathering"] *= 1.0 + 0.2 * destab
    return w


def _combine_action_weights(
    *maps: Dict[str, float],
) -> Dict[str, float]:
    w = _all_action_weights_unity()
    for m in maps:
        for a in ACTION_TYPES:
            w[a] *= float(m.get(a, 1.0) or 1.0)
    return w


def _select_intrigue_action(
    viable: List[str], source: str, target: str, itel: int, state: dict
) -> str:
    if not viable:
        return ""
    if len(viable) == 1:
        return viable[0]
    wmap = _combine_action_weights(
        _intrigue_culture_action_weights(source),
        _goal_action_weights(source, target, state),
        _intel_agent_action_weights(itel),
        _stability_target_action_weights(target, state),
    )
    weights = [max(0.04, wmap.get(a, 0.1)) for a in viable]
    return str(random.choices(viable, weights=weights, k=1)[0])


def _pick_target_for_intrigue(
    source: str, fids: List[str], state: dict
) -> str:
    """Favor war/rival, low trust, and destabilized enemy territory."""
    cands = [f for f in fids if f and f != source]
    if not cands:
        return ""
    wts: List[float] = []
    for c in cands:
        r = _rel_pair(source, c, state)
        tr = int(r.get("trust", 50) or 50)
        h = int(r.get("hostility", 20) or 20)
        typ = (r.get("type") or "neutral")
        s_avg = _location_avg_stability(c, state)
        weight = 0.45 + 0.018 * h + 0.016 * (100 - tr) + 0.014 * max(0.0, 60.0 - s_avg)
        if typ == "war":
            weight += 1.15
        elif typ == "rivalry":
            weight += 0.68
        elif typ in ("alliance",) and h < 28 and tr > 60:
            weight *= 0.32
        weight = max(0.1, weight)
        wts.append(weight)
    return str(random.choices(cands, weights=wts, k=1)[0])


def _intrigue_culture_tag(faction: str) -> str:
    u = (faction or "").lower()
    if any(x in u for x in ("faerwood", "shadow", "verlorn")) and "dread" not in u:
        return "faerwood"
    if "eldoria" in u or "lefleur" in u:
        return "eldoria"
    if "twin" in u or "aurand" in u or "eresteron" in u:
        return "twin_cities"
    if "tidefall" in u or "dreadwind" in u or "isles" in u or "ver meer" in u or "blacktide" in u:
        return "maritime"
    if "farrock" in u or "lostfeld" in u:
        return "direct_dwar"
    if "vilefin" in u or "bloodware" in u or "cogtooth" in u or "rustfang" in u:
        return "vilefin"
    return "default"


def _start_intrigue_probability(
    source: str, itel: int, cfg: dict
) -> float:
    p = float(cfg.get("start_new_probability", 0.4) or 0.4) * (
        0.86
        + float(cfg.get("intrigue_start_intel_scale", 0.002) or 0.0)
        * (itel - 40.0)
    )
    u = (source or "").lower()
    if "farrock" in u or "lostfeld" in u:
        p *= float(cfg.get("intrigue_start_farrock_mult", 0.64) or 0.64)
    if any(
        x in u for x in ("faerwood", "shadow", "verlorn")
    ) and "dread" not in u:
        p *= float(cfg.get("intrigue_start_faerwood_mult", 1.12) or 1.12)
    if "twin" in u or "aurand" in u or "eresteron" in u or "tidefall" in u:
        p *= float(cfg.get("intrigue_start_twin_mult", 0.92) or 0.92)
    return _clamp(p, 0.09, 0.8)


def _is_chaotic_sabotage_faction(faction: str) -> bool:
    u = (faction or "").lower()
    return "vilefin" in u or "bloodware" in u or "cogtooth" in u or "rustfang" in u


def _pick_target(source: str, state: dict) -> str:
    cands: List[Tuple[str, float]] = []
    for other, tr, typ in _iter_relations(source, state):
        if not other or other == source:
            continue
        # Prefer rivals / low trust for covert ops
        w = 1.0
        if typ == "war":
            w = 0.3
        elif tr < 35:
            w = 2.0
        elif tr < 55:
            w = 1.2
        else:
            w = 0.45
        cands.append((other, w))
    if not cands:
        fids = [f for f in list_faction_ids(state) if f != source]
        return random.choice(fids) if fids else ""
    tot = sum(x[1] for x in cands)
    r = random.random() * tot
    acc = 0.0
    for o, w in cands:
        acc += w
        if r <= acc:
            return o
    return cands[0][0]


def _pick_target_character_name(target_faction: str, state: dict) -> str:
    pool: List[str] = []
    rname = ""
    for ls in state.get("leadership_state") or []:
        if (ls or {}).get("faction") == target_faction:
            rname = str(((ls or {}).get("currentRuler") or {}).get("name") or "")
            break
    for ch in state.get("house_characters") or []:
        if not isinstance(ch, dict):
            continue
        if (ch.get("faction") or "") != target_faction:
            continue
        s = str(ch.get("status", "alive") or "alive").lower()
        if s.startswith("deceased") or s in ("dead", "killed"):
            continue
        n = (ch.get("name") or "").strip()
        if n:
            pool.append(n)
    if rname and random.random() < 0.35:
        return rname
    if not pool:
        return ""
    return random.choice(pool)


def _blackmail_vulnerability_score(ch: dict) -> float:
    """Lower loyalty and lower morality = easier to gather material for coercion."""
    lo = float(ch.get("loyalty", 50) or 50)
    mo = float(ch.get("morality", 50) or 50)
    return 8.0 + (100.0 - lo) * 0.48 + (100.0 - mo) * 0.4


def _pick_blackmail_victim(target_faction: str, state: dict) -> str:
    pool: List[dict] = []
    for ch in state.get("house_characters") or []:
        if not isinstance(ch, dict):
            continue
        if (ch.get("faction") or "") != target_faction:
            continue
        s = str(ch.get("status", "alive") or "alive").lower()
        if s.startswith("deceased") or s in ("dead", "killed", "slain"):
            continue
        n = (ch.get("name") or "").strip()
        if n:
            pool.append(ch)
    if not pool:
        return ""
    w = [max(0.15, _blackmail_vulnerability_score(c)) for c in pool]
    chosen = random.choices(pool, weights=w, k=1)[0]
    return str(chosen.get("name") or "").strip()


def _prune_blackmail_coercion(state: dict, tick: int) -> None:
    ac = state.get("active_blackmail_coercion")
    if not isinstance(ac, list):
        state["active_blackmail_coercion"] = []
        return
    t = int(tick)
    state["active_blackmail_coercion"] = [
        x
        for x in ac
        if isinstance(x, dict) and int(x.get("expires_tick", 0) or 0) >= t
    ]


def _agent_for_faction(faction: str, state: dict) -> Tuple[Optional[dict], int, int]:
    """Return (char_or_none, intelligence, intrigue_skill) for best available agent."""
    best: Optional[dict] = None
    best_score = -1.0
    for ch in state.get("house_characters") or []:
        if not isinstance(ch, dict):
            continue
        if (ch.get("faction") or "") != faction:
            continue
        s = str(ch.get("status", "alive") or "alive").lower()
        if s.startswith("deceased") or s in ("dead", "killed", "slain"):
            continue
        ing = int(ch.get("intrigue", 50) or 50)
        itel = int(ch.get("intelligence", 50) or 50)
        score = 0.55 * itel + 0.45 * ing
        role = str(ch.get("role", "")).lower()
        if any(x in role for x in ("spy", "assassin", "spymaster", "shadow", "informer")):
            score += 8.0
        if (ch.get("coreRole") or "") in ("Heir", "Power Role", "Leader"):
            score += 2.0
        if score > best_score:
            best_score = score
            best = ch
    if not best:
        return None, 40, 40
    return best, int(best.get("intelligence", 50) or 50), int(best.get("intrigue", 50) or 50)


def _get_or_create_faction_row(
    faction: str, by_f: Dict[str, dict], all_f: List[str]
) -> dict:
    if faction in by_f:
        return by_f[faction]
    sn: Dict[str, Dict[str, int]] = {}
    for o in all_f:
        if o == faction:
            continue
        if random.random() < 0.18:
            sn[o] = {
                "network_strength": max(0, min(100, int(random.gauss(8, 5)))),
                "exposure": max(0, min(35, int(abs(random.gauss(4, 3))))),
            }
    row = {
        "faction": faction,
        "intrigue_level": 28,
        "spy_networks": sn,
        "counter_intelligence": int(
            _clamp(32.0 + random.gauss(0, 9), 15.0, 80.0)
        ),
    }
    by_f[faction] = row
    return row


def _ensure_faction_intrigue_map(state: dict) -> Dict[str, dict]:
    all_f = list_faction_ids(state)
    li = list(state.get("faction_intrigue") or [])
    by: Dict[str, dict] = {}
    for r in li:
        if not isinstance(r, dict):
            continue
        f = (r.get("faction") or "").strip()
        if f:
            r.setdefault("intrigue_level", 25)
            r["spy_networks"] = _migrate_spy_networks_map(r.get("spy_networks"))
            if "counter_intelligence" not in r:
                r["counter_intelligence"] = int(
                    _clamp(30.0 + random.gauss(0, 10), 12.0, 85.0)
                )
            else:
                r["counter_intelligence"] = int(
                    _clamp(
                        float(r.get("counter_intelligence", 40) or 40), 0.0, 100.0
                    )
                )
            by[f] = r
    for f in all_f:
        if f not in by:
            by[f] = {
                "faction": f,
                "intrigue_level": max(8, min(88, 22 + int(random.gauss(0, 9)))),
                "counter_intelligence": int(
                    _clamp(30.0 + random.gauss(0, 9), 10.0, 85.0)
                ),
                "spy_networks": {
                    o: {
                        "network_strength": max(0, min(16, int(random.gauss(5, 4)))),
                        "exposure": max(0, min(22, int(abs(random.gauss(3, 2))))),
                    }
                    for o in all_f
                    if o != f and random.random() < 0.25
                },
            }
    return by


def _action_costs(action: str, cfg: dict) -> Tuple[int, int, int, str]:
    min_ints = {
        "spy_network_expansion": int(cfg.get("min_intelligence_spy", 32)),
        "sabotage": int(cfg.get("min_intelligence_sabotage", 42)),
        "assassination": int(cfg.get("min_intelligence_assassination", 58)),
        "information_gathering": int(cfg.get("min_intelligence_intel", 28)),
        "blackmail": int(cfg.get("min_intelligence_blackmail", 40)),
    }
    gbase = {
        "spy_network_expansion": int(cfg.get("base_gold_spy", 55)),
        "sabotage": int(cfg.get("base_gold_sabotage", 140)),
        "assassination": int(cfg.get("base_gold_assassination", 320)),
        "information_gathering": int(cfg.get("base_gold_intel", 38)),
        "blackmail": int(cfg.get("base_gold_blackmail", 75)),
    }
    tbase = {
        "spy_network_expansion": int(cfg.get("ticks_spy", 2)),
        "sabotage": int(cfg.get("ticks_sabotage", 3)),
        "assassination": int(cfg.get("ticks_assassination", 4)),
        "information_gathering": int(cfg.get("ticks_intel", 1)),
        "blackmail": int(cfg.get("ticks_blackmail", 2)),
    }
    a = min_ints.get(action, 35)
    g = gbase.get(action, 50)
    tk = tbase.get(action, 2)
    return a, g, max(1, tk), action


def _op_id(components: str) -> str:
    h = hashlib.sha256(components.encode("utf-8", errors="replace")).hexdigest()[:10]
    return f"INT-{h}"


def _resolve_assassination_completed(
    op: dict,
    source_row: dict,
    target: str,
    state: dict,
    cfg: dict,
    tick: int,
) -> dict:
    """
    Kill chance from R = (attacker_intelligence + network_strength) /
    (target_loyalty + target_intelligence), then P = R / (R + k).
    """
    itel = int(op.get("intelligence", 45) or 45)
    il = int(source_row.get("intrigue_level", 30) or 30)
    cell = _get_cell(source_row, target)
    ns0 = int(cell["network_strength"])
    ex0 = int(cell["exposure"])
    min_ns = int(cfg.get("assassination_min_network_strength", 18) or 18)
    k = float(cfg.get("assassination_roll_denom_k", 1.08) or 1.08)
    xtra = float(cfg.get("assassination_failure_exposure_extra", 6) or 6)
    pen = int(cfg.get("assassination_commander_morale_penalty", 12) or 12)
    src = str(op.get("source_faction", ""))

    victim = (op.get("target_character") or "").strip() or _pick_target_character_name(
        target, state
    )
    tch = _find_house_char(victim, target, state)
    if tch:
        t_loy = int(tch.get("loyalty", 50) or 50)
        t_int = int(tch.get("intelligence", 50) or 50)
    else:
        t_loy, t_int = 50, 50

    denom = max(1, t_loy + t_int)
    R = (float(itel) + float(ns0)) / float(denom)
    p_kill = _clamp(R / (R + k), 0.04, 0.9)
    if ns0 < min_ns:
        p_kill = 0.0
    u = random.random()
    u2 = random.random()
    success = u < p_kill and ns0 >= min_ns

    consequences: Dict[str, Any] = {
        "trust": None,
        "war": None,
        "legitimacy": None,
        "succession": None,
        "military": [],
    }
    ex1 = float(ex0)
    outcome = "success" if success else "failed"
    if not success:
        ex1 = min(
            100.0,
            ex1
            + float(cfg.get("exposure_on_failed_action", 7) or 7.0)
            + xtra
            + (9.0 if u2 < 0.4 else 0.0),
        )
        ex_i = int(_clamp(ex1, 0, 100))
        dc = _assassination_exposure_consequences(src, target, ex_i, state, cfg)
        for key in ("trust", "war", "legitimacy"):
            if dc.get(key) is not None:
                consequences[key] = dc[key]
        source_row["intrigue_level"] = int(_clamp(il - 1.0, 0, 100))
    else:
        if random.random() < 0.1:
            ex1 = min(100.0, ex1 + 0.5)
        source_row["intrigue_level"] = int(_clamp(il + 1.2, 0, 100))
        if victim:
            state.setdefault("pending_character_deaths", []).append(
                {"name": victim, "cause": "assassination"}
            )
        if _victim_is_ruler(victim, target, state):
            consequences["succession"] = {
                "ruler_dies": True,
                "note": "succession_resolves_when_death_system_processes_ruler",
            }
        mil = _commander_fallen_in_armies(victim, target, state, pen)
        if mil:
            consequences["military"] = mil

    _set_cell(
        source_row,
        target,
        {
            "network_strength": int(_clamp(float(ns0), 0, 100)),
            "exposure": int(_clamp(ex1, 0, 100)),
        },
    )
    cell_f = _get_cell(source_row, target)
    det_risk = _detection_risk_for_edge(
        cell_f["network_strength"], cell_f["exposure"], cfg
    )
    vis = _visibility_into_target(cell_f["network_strength"], cell_f["exposure"])

    attempt = {
        "victim": victim,
        "target_faction": target,
        "attacker_faction": src,
        "attacker_intelligence": itel,
        "network_strength": ns0,
        "target_loyalty": t_loy,
        "target_intelligence": t_int,
        "success_index": round(R, 4),
        "kill_roll_probability": round(p_kill, 4),
        "gold_paid": int(op.get("gold_paid", 0) or 0),
    }
    out_rec = {
        "assassination_attempt": attempt,
        "success": success,
        "exposure": int(cell_f["exposure"]),
        "consequences": consequences,
    }
    st = state.setdefault("assassination_reports", [])
    if isinstance(st, list):
        st.append(out_rec)
        state["assassination_reports"] = st[-20:]

    return {
        "tick": tick,
        "op_id": op.get("id", ""),
        "action": "assassination",
        "outcome": outcome,
        "source_faction": src,
        "target_faction": target,
        "actor": op.get("actor", ""),
        "intelligence_used": itel,
        "gold_paid": int(op.get("gold_paid", 0) or 0),
        "target_character": victim,
        "target_visibility": vis,
        "target_detection_risk": det_risk,
        "assassination_report": out_rec,
    }


def _resolve_blackmail_completed(
    op: dict,
    source_row: dict,
    target: str,
    state: dict,
    cfg: dict,
    tick: int,
) -> dict:
    """
    Secrets through spy networks: low-loyalty, low-morality targets are easier.
    Resistance from high morality / high loyalty. Failure exposes and hits source reputation.
    """
    itel = int(op.get("intelligence", 45) or 45)
    il = int(source_row.get("intrigue_level", 30) or 30)
    src = str(op.get("source_faction", ""))
    victim_name = (op.get("target_character") or "").strip()
    ch = _find_house_char(victim_name, target, state) if victim_name else None
    if not victim_name or not ch:
        victim_name = _pick_blackmail_victim(target, state)
        ch = _find_house_char(victim_name, target, state) if victim_name else None

    cell = _get_cell(source_row, target)
    ns0 = int(cell["network_strength"])
    ex0 = int(cell["exposure"])
    min_ns = int(cfg.get("blackmail_min_network_strength", 8) or 8)

    morality = int((ch or {}).get("morality", 50) or 50)
    loyalty = int((ch or {}).get("loyalty", 50) or 50)

    bp = float(cfg.get("blackmail_base_p", 0.16) or 0.16)
    si = float(cfg.get("blackmail_intelligence_scale", 0.0034) or 0.0034)
    sn = float(cfg.get("blackmail_network_scale", 0.0022) or 0.0022)
    mr = float(cfg.get("blackmail_morality_resist", 0.00135) or 0.00135)
    lr = float(cfg.get("blackmail_loyalty_resist", 0.00095) or 0.00095)
    rp = float(cfg.get("blackmail_ruler_penalty", 0.042) or 0.042)

    p_ok = bp + si * (itel - 40) + sn * float(ns0)
    p_ok -= mr * (morality - 45)
    p_ok -= lr * (loyalty - 45)
    if victim_name and _victim_is_ruler(victim_name, target, state):
        p_ok -= rp
    p_ok = p_ok / 1.05
    p_ok = _clamp(p_ok, 0.06, 0.86)
    if ns0 < min_ns:
        p_ok = 0.0

    u = random.random()
    success = u < p_ok and ns0 >= min_ns

    ex1 = float(ex0)
    if not success:
        ex1 = min(
            100.0,
            ex1
            + float(cfg.get("exposure_on_failed_action", 7) or 7.0)
            + float(cfg.get("blackmail_failure_exposure_extra", 6) or 6.0),
        )
        source_row["intrigue_level"] = int(_clamp(il - 1.2, 0, 100))
    else:
        ex1 = min(100.0, ex1 + 3.0)
        source_row["intrigue_level"] = int(_clamp(il + 2.0, 0, 100))

    _set_cell(
        source_row,
        target,
        {
            "network_strength": int(_clamp(float(ns0), 0, 100)),
            "exposure": int(_clamp(ex1, 0, 100)),
        },
    )
    cell_f = _get_cell(source_row, target)
    det_risk = _detection_risk_for_edge(
        cell_f["network_strength"], cell_f["exposure"], cfg
    )
    vis = _visibility_into_target(cell_f["network_strength"], cell_f["exposure"])

    forced: str
    if not success:
        hit_leg = float(cfg.get("blackmail_fail_legitimacy_hit", 3.2) or 3.2)
        rs = state.setdefault("ruler_legitimacy_scores", {})
        if not isinstance(rs, dict):
            rs = {}
            state["ruler_legitimacy_scores"] = rs
        if src in rs:
            try:
                rs[src] = max(
                    0.0,
                    min(100.0, float(rs[src] or 50) - hit_leg),
                )
            except (TypeError, ValueError):
                pass
        at = list(state.get("active_tensions") or [])
        at.append(
            {
                "tick": tick,
                "source": "blackmail",
                "parties": [src, target],
                "severity": 5,
                "summary": f"Coercion attempt against {target} is exposed; {src} loses face.",
            }
        )
        state["active_tensions"] = at[-24:]
        forced = "exposed_on_failure"
        for rel in state.get("relationships") or []:
            if not isinstance(rel, dict):
                continue
            a, b = (rel.get("faction_a") or ""), (rel.get("faction_b") or "")
            if a and b and {a, b} == {src, target}:
                tr = int(rel.get("trust", 50) or 50)
                rel["trust"] = max(0, min(100, tr - 2))
                break
    else:
        if morality < 38:
            weights = (0.45, 0.25, 0.30)
        elif morality > 70:
            weights = (0.22, 0.20, 0.58)
        else:
            weights = (0.34, 0.33, 0.33)
        forced = str(
            random.choices(BLACKMAIL_FORCED_ACTIONS, weights=weights, k=1)[0]
        )
        if ch and isinstance(ch, dict):
            lo = int(ch.get("loyalty", 50) or 50)
            ra = list(ch.get("recentActions") or [])
            if forced == "forced_loyalty":
                d0 = int(cfg.get("blackmail_loyalty_delta_lo", 4) or 4)
                d1 = int(cfg.get("blackmail_loyalty_delta_hi", 9) or 9)
                ch["loyalty"] = int(min(100, lo + random.randint(d0, d1)))
                ra.append(
                    f"Swears renewed fealty in court after private leverage ({tick})."
                )
            elif forced == "forced_betrayal":
                ch["loyalty"] = int(_clamp(float(lo) - random.randint(2, 6), 0, 100))
                mem = list(ch.get("memory") or [])
                mem.append(
                    {
                        "tick": tick,
                        "target": src,
                        "impact": -22,
                        "description": "Withholds or warps reports under coercive pressure.",
                    }
                )
                ch["memory"] = mem[-28:]
                ra.append(
                    f"Holds back counsel that would aid an ally; pressure traceable to foreign interest ({tick})."
                )
                all_rels: List[dict] = [
                    r
                    for r in (state.get("relationships") or [])
                    if isinstance(r, dict)
                    and target in (r.get("faction_a", ""), r.get("faction_b", ""))
                    and (r.get("type") or "") in ("alliance", "neutral", "rivalry")
                ]
                if all_rels:
                    r = random.choice(all_rels)
                    oa = r.get("faction_a") if r.get("faction_b") == target else r.get("faction_b")
                    if oa and oa != src:
                        tr0 = int(r.get("trust", 50) or 50)
                        tl = int(
                            random.randint(
                                int(cfg.get("blackmail_betrayal_trust_lo", 6) or 6),
                                int(cfg.get("blackmail_betrayal_trust_hi", 14) or 14),
                            )
                        )
                        r["trust"] = max(0, tr0 - tl)
            else:
                n_tick = int(cfg.get("blackmail_coercion_diplomacy_ticks", 6) or 6)
                ac = list(state.setdefault("active_blackmail_coercion", []))
                ac.append(
                    {
                        "target_faction": target,
                        "source_faction": src,
                        "character": victim_name,
                        "tick": tick,
                        "expires_tick": tick + n_tick,
                    }
                )
                state["active_blackmail_coercion"] = ac[-16:]
                ra.append(
                    f"Diplomatic channels show uncharacteristic caution; a court figure is leveraged ({tick})."
                )
            ch["recentActions"] = ra[-14:]

        for rel in state.get("relationships") or []:
            if not isinstance(rel, dict):
                continue
            a, b = (rel.get("faction_a") or ""), (rel.get("faction_b") or "")
            if a and b and {a, b} == {src, target}:
                tr = int(rel.get("trust", 50) or 50)
                rel["trust"] = max(0, min(100, tr - 3))
                break

    out_bm = {
        "blackmail_target": (
            f"{victim_name} ({target})" if victim_name else str(target)
        ),
        "success": success,
        "forced_action": forced,
    }
    bst = state.setdefault("blackmail_reports", [])
    if isinstance(bst, list):
        bst.append(out_bm)
        state["blackmail_reports"] = bst[-32:]

    return {
        "tick": tick,
        "op_id": op.get("id", ""),
        "action": "blackmail",
        "outcome": "success" if success else "failed",
        "source_faction": src,
        "target_faction": target,
        "actor": op.get("actor", ""),
        "intelligence_used": itel,
        "gold_paid": int(op.get("gold_paid", 0) or 0),
        "target_character": victim_name,
        "target_visibility": vis,
        "target_detection_risk": det_risk,
        "network_strength_versus_target": int(cell_f["network_strength"]),
        "exposure": int(cell_f["exposure"]),
        "blackmail_report": out_bm,
    }


def _sabotage_success_probability(itel: int, ns: int, cfg: dict) -> float:
    """Success from attacker intelligence + spy network (linear blend, capped)."""
    bp = float(cfg.get("sabotage_base_p", 0.14) or 0.14)
    si = float(cfg.get("sabotage_intelligence_scale", 0.0036) or 0.0036)
    sn = float(cfg.get("sabotage_network_scale", 0.0025) or 0.0025)
    p = bp + si * (itel - 40) + sn * float(ns)
    p = p / 1.1
    return _clamp(p, 0.08, 0.88)


def _sabotage_kind_for_op(op: dict) -> str:
    k = op.get("sabotage_kind")
    if k in SABOTAGE_KINDS:
        return str(k)
    oid = str(op.get("id", "0"))
    return SABOTAGE_KINDS[abs(hash(oid)) % 3]


def _restore_sabotage_fortifications(state: dict, tick: int) -> None:
    for loc in state.get("locations") or []:
        if not isinstance(loc, dict):
            continue
        rt = loc.get("fort_sabotage_restore_tick")
        if rt is None:
            continue
        if int(tick) < int(rt):
            continue
        prev = loc.get("fort_level_pre_sabotage")
        if prev is not None:
            try:
                loc["fort_level"] = int(
                    _clamp(float(int(prev)), 0, 5)
                )
            except (TypeError, ValueError):
                pass
            loc.pop("fort_level_pre_sabotage", None)
        loc.pop("fort_sabotage_restore_tick", None)


def _resolve_sabotage_completed(
    op: dict,
    source_row: dict,
    target: str,
    state: dict,
    cfg: dict,
    tick: int,
    by_f: Optional[Dict[str, dict]] = None,
) -> dict:
    itel = int(op.get("intelligence", 45) or 45)
    il = int(source_row.get("intrigue_level", 30) or 30)
    kind = _sabotage_kind_for_op(op)
    min_ns = int(cfg.get("sabotage_min_network_strength", 6) or 6)
    cell = _get_cell(source_row, target)
    ns0 = int(cell["network_strength"])
    ex0 = int(cell["exposure"])
    src = str(op.get("source_faction", ""))

    p_ok = _sabotage_success_probability(itel, ns0, cfg)
    if ns0 < min_ns:
        p_ok = 0.0
    u = random.random()
    u2 = random.random()
    success = u < p_ok and ns0 >= min_ns
    dci, dintel = _defender_counterintel_for_op(target, by_f, state)
    det = _clamp(
        0.12
        * max(0.35, 1.0 - 0.0038 * float(ns0))
        * (1.0 + 0.006 * float(ex0))
        - 0.0009 * (itel - 40),
        0.03,
        0.5,
    )
    detm = (
        1.0
        + float(cfg.get("ci_sabotage_det_scale", 0.28) or 0.28) * (dci / 100.0)
        + float(cfg.get("ci_sabotage_intel_scale", 0.09) or 0.09) * max(0.0, (dintel - 42) / 58.0)
    )
    det = _clamp(det * detm, 0.03, 0.6)
    if success and u2 < det:
        partial = "detected"
    else:
        partial = None

    ex1 = float(ex0)
    outcome: str
    if not success:
        ex1 = min(
            100.0,
            ex1
            + float(cfg.get("exposure_on_failed_action", 7) or 7.0)
            + float(cfg.get("sabotage_failure_detection_extra", 5) or 5.0)
            + (7.0 if u2 < 0.4 else 0.0)
        )
        source_row["intrigue_level"] = int(_clamp(il - 1.0, 0, 100))
        outcome = "failed"
    else:
        ex1 = min(100.0, ex1 + 2.0)
        if partial == "detected":
            ex1 = min(100.0, ex1 + 4.0)
        source_row["intrigue_level"] = int(_clamp(il + 1.5, 0, 100))
        outcome = "detected" if partial == "detected" else "success"

    _set_cell(
        source_row,
        target,
        {
            "network_strength": int(_clamp(float(ns0), 0, 100)),
            "exposure": int(_clamp(ex1, 0, 100)),
        },
    )
    cell_f = _get_cell(source_row, target)
    det_risk = _detection_risk_for_edge(
        cell_f["network_strength"], cell_f["exposure"], cfg
    )
    vis = _visibility_into_target(cell_f["network_strength"], cell_f["exposure"])

    impact: Dict[str, Any] = {"kind": kind, "outcome": outcome, "target_faction": target}
    sev = 0.5 if (success and partial == "detected") else (1.0 if success else 0.0)

    if success and kind == "supply_sabotage":
        hit = int(cfg.get("sabotage_supply_level_hit", 14) or 14)
        arms_aff: List[dict] = []
        fas = list(state.get("faction_armies") or [])
        tgt_arm = [
            a
            for a in fas
            if isinstance(a, dict) and (a.get("faction_id") or "") == target
        ]
        random.shuffle(tgt_arm)
        for a in tgt_arm[:2]:
            s0 = int(a.get("supply_level", 65) or 65)
            a["supply_level"] = max(0, s0 - int(hit * sev + 4))
            a["supply_line_reason"] = "sabotage"
            arms_aff.append(
                {
                    "army_id": a.get("army_id"),
                    "supply_level_before": s0,
                    "supply_level_after": a["supply_level"],
                }
            )
        state["faction_armies"] = fas
        impact["armies"] = arms_aff
        impact["supply_lines"] = "disrupted"
    elif success and kind == "trade_disruption":
        capm = float(cfg.get("sabotage_trade_cap_mult", 0.78) or 0.78)
        dtk = int(cfg.get("sabotage_trade_disrupted_ticks", 4) or 4)
        routes = list(state.get("economic_trade_routes") or [])
        touched: List[dict] = []
        idxs = [i for i, r in enumerate(routes) if isinstance(r, dict) and (r.get("origin") == target or r.get("destination") == target)]
        random.shuffle(idxs)
        for i in idxs[:2]:
            r = dict(routes[i])
            c0 = int(r.get("capacity", 50) or 50)
            r["capacity"] = max(10, int(c0 * capm * sev + 8 * (1.0 - sev)))
            r["status"] = "disrupted"
            r["disrupted_remaining"] = max(
                int(r.get("disrupted_remaining", 0) or 0), dtk
            )
            routes[i] = r
            touched.append(
                {
                    "route_id": r.get("id", ""),
                    "origin": r.get("origin", ""),
                    "destination": r.get("destination", ""),
                    "capacity_before": c0,
                    "capacity_after": r["capacity"],
                }
            )
        state["economic_trade_routes"] = routes
        stress = float(cfg.get("sabotage_price_stress_add", 0.038) or 0.038) * (0.65 + 0.35 * sev)
        ps = min(
            0.15, float(state.get("sabotage_price_stress", 0) or 0) + stress
        )
        state["sabotage_price_stress"] = round(ps, 4)
        impact["routes"] = touched
        impact["trade_price_stress"] = state["sabotage_price_stress"]
    elif success and kind == "infrastructure_damage":
        drf = int(cfg.get("sabotage_fort_level_drop", 1) or 1)
        drop = int(_clamp(float(drf) * (0.6 + 0.4 * sev), 0, 3))
        mult = float(cfg.get("sabotage_production_mult", 0.94) or 0.94)
        restore = int(
            tick + int(cfg.get("sabotage_fort_restore_in_ticks", 5) or 5)
        )
        locs = [
            l
            for l in (state.get("locations") or [])
            if isinstance(l, dict) and l.get("controller") == target
        ]
        if locs and drop > 0:
            loc = random.choice(locs)
            fl = int(_clamp(float(loc.get("fort_level", 0) or 0), 0, 5))
            if "fort_level_pre_sabotage" not in loc:
                loc["fort_level_pre_sabotage"] = fl
            loc["fort_level"] = int(max(0, fl - drop))
            loc["fort_sabotage_restore_tick"] = restore
            impact["location_name"] = str(loc.get("name", ""))
            impact["fort_level_before"] = fl
            impact["fort_level_after"] = int(loc.get("fort_level", 0) or 0)
            impact["fort_restores_on_tick"] = restore
        rows = list(state.get("faction_economy") or [])
        for j, row in enumerate(rows):
            if (row.get("faction_id") or row.get("faction")) != target:
                continue
            if not isinstance(row, dict):
                continue
            resmap = {**(row.get("resources") or {})}
            for res in ("grain", "iron", "timber"):
                m = dict(resmap.get(res) or {})
                p0 = float(m.get("production", 0) or 0)
                if p0 < 0.1:
                    continue
                m["production"] = round(
                    p0 * (mult + (1.0 - mult) * (1.0 - sev)), 2
                )
                resmap[res] = m
            row = dict(row)
            row["resources"] = {**(row.get("resources") or {}), **resmap}
            rows[j] = row
            impact["production_slowed"] = {
                "resource": "grain, iron, timber",
                "multiplier": mult,
            }
            break
        state["faction_economy"] = rows

    sabotage_out = {
        "sabotage_event": f"{kind}:{outcome}",
        "target": target,
        "impact": impact,
    }
    srep = state.setdefault("sabotage_reports", [])
    if isinstance(srep, list):
        srep.append(sabotage_out)
        state["sabotage_reports"] = srep[-32:]

    if not success:
        at = list(state.get("active_tensions") or [])
        at.append(
            {
                "tick": tick,
                "source": "sabotage",
                "parties": [src, target],
                "severity": 5,
                "summary": f"Clandestine operation against {target} fails and raises suspicion.",
            }
        )
        state["active_tensions"] = at[-24:]
    if outcome in ("success", "detected"):
        le = list(state.get("location_events") or [])
        le.append(
            {
                "tick": tick,
                "type": f"sabotage_{kind}",
                "location": str(impact.get("location_name", "")) or target,
                "faction": target,
                "summary": f"Sabotage ({kind}) from {src} hits {target} ({outcome}).",
            }
        )
        state["location_events"] = le[-32:]

    return {
        "tick": tick,
        "op_id": op.get("id", ""),
        "action": "sabotage",
        "sabotage_kind": kind,
        "outcome": outcome,
        "source_faction": src,
        "target_faction": target,
        "actor": op.get("actor", ""),
        "intelligence_used": itel,
        "gold_paid": int(op.get("gold_paid", 0) or 0),
        "target_visibility": vis,
        "target_detection_risk": det_risk,
        "network_strength_versus_target": int(cell_f["network_strength"]),
        "exposure": int(cell_f["exposure"]),
        "sabotage_report": sabotage_out,
    }


def _success_chance(
    action: str,
    intelligence: int,
    intrigue_level: int,
    network_strength: int,
    cfg: dict,
) -> float:
    w = _W_ACTION.get(action, 1.0)
    ns = float(_clamp(float(network_strength), 0, 100))
    p = 0.22
    p += 0.0038 * (intelligence - 40)
    p += 0.0018 * (intrigue_level - 35)
    p += 0.0014 * (ns - 20.0)
    p += 0.0009 * (ns / 100.0) * float(intelligence)  # visibility / placement quality
    p = p / w
    return _clamp(p, 0.08, 0.92)


def _resolve_completed(
    op: dict,
    source_row: dict,
    target: str,
    state: dict,
    cfg: dict,
    tick: int,
    by_f: Optional[Dict[str, dict]] = None,
) -> dict:
    action = str(op.get("action") or "")
    if action == "assassination":
        return _resolve_assassination_completed(
            op, source_row, target, state, cfg, tick
        )
    if action == "sabotage":
        return _resolve_sabotage_completed(
            op, source_row, target, state, cfg, tick, by_f
        )
    if action == "blackmail":
        return _resolve_blackmail_completed(
            op, source_row, target, state, cfg, tick
        )
    itel = int(op.get("intelligence", 45) or 45)
    il = int(source_row.get("intrigue_level", 30) or 30)
    cell = _get_cell(source_row, target)
    ns0 = int(cell["network_strength"])
    ex0 = int(cell["exposure"])
    p_ok = _success_chance(action, itel, il, ns0, cfg)
    base = float(cfg.get("detection_baseline", 0.14))
    mit = float(cfg.get("detection_strength_mitigation", 0.0048) or 0.0048)
    amp = float(cfg.get("detection_exposure_amplification", 0.0052) or 0.0052)
    det = base * max(0.22, 1.0 - mit * float(ns0)) * (1.0 + amp * float(ex0))
    det = _clamp(det, 0.03, 0.6)
    det = _clamp(
        det - 0.0011 * (itel - 40) - 0.0006 * (il - 35),
        0.025,
        0.58,
    )
    dci, dintel = _defender_counterintel_for_op(target, by_f, state)
    det = det * (
        1.0
        + float(cfg.get("ci_op_detect_mult", 0.34) or 0.34) * (dci / 100.0)
        + float(cfg.get("ci_def_intel_op_mult", 0.14) or 0.14) * max(0.0, (dintel - 42) / 58.0)
    )
    det = _clamp(det, 0.02, 0.9)
    u = random.random()
    u2 = random.random()

    outcome = "success"
    if u > p_ok:
        outcome = "failed"
    if u2 < det and outcome == "success":
        outcome = "detected"
    if outcome == "failed" and u2 < det * 0.55:
        outcome = "failed_traced"

    ex1 = float(ex0)
    if outcome == "failed":
        ex1 = min(100.0, ex1 + float(cfg.get("exposure_on_failed_action", 7) or 7.0))
    elif outcome == "failed_traced":
        ex1 = min(
            100.0, ex1 + float(cfg.get("exposure_on_failed_traced", 10) or 10.0)
        )
    elif outcome == "detected":
        ex1 = min(100.0, ex1 + float(cfg.get("exposure_on_detected", 3) or 3.0))

    if outcome in ("success", "detected"):
        source_row["intrigue_level"] = int(
            _clamp(il + (4 if action == "spy_network_expansion" else 2.2), 0, 100)
        )
    elif outcome in ("failed", "failed_traced"):
        source_row["intrigue_level"] = int(_clamp(il - 1.5, 0, 100))

    final_ns = float(ns0)
    if action == "spy_network_expansion" and outcome in ("success", "detected"):
        delta = 6 + int((itel - 40) * 0.12)
        if outcome == "detected":
            delta = max(1, int(delta * 0.6))
        final_ns = min(100.0, final_ns + float(delta))
    if outcome in ("detected", "failed_traced"):
        wk = float(cfg.get("ci_op_network_weaken_on_detected", 0.11) or 0.11) * (1.0 + dci / 100.0)
        wk = _clamp(wk, 0.0, 0.45)
        final_ns = final_ns * (1.0 - wk)

    _set_cell(
        source_row,
        target,
        {
            "network_strength": int(_clamp(final_ns, 0, 100)),
            "exposure": int(_clamp(ex1, 0, 100)),
        },
    )
    cell_f = _get_cell(source_row, target)
    det_risk = _detection_risk_for_edge(
        cell_f["network_strength"], cell_f["exposure"], cfg
    )
    vis = _visibility_into_target(cell_f["network_strength"], cell_f["exposure"])

    report: dict = {
        "tick": tick,
        "op_id": op.get("id", ""),
        "action": action,
        "outcome": outcome,
        "source_faction": op.get("source_faction", ""),
        "target_faction": target,
        "actor": op.get("actor", ""),
        "intelligence_used": itel,
        "gold_paid": int(op.get("gold_paid", 0) or 0),
        "network_strength_versus_target": int(cell_f["network_strength"]),
        "exposure": int(cell_f["exposure"]),
        "target_visibility": vis,
        "target_detection_risk": det_risk,
    }
    if action == "spy_network_expansion" and outcome in ("success", "detected"):
        report["network_strength_delta"] = int(min(100, final_ns) - ns0)
    if action == "information_gathering" and outcome in ("success", "detected", "failed"):
        q = round(0.12 + 0.0065 * float(vis) + 0.0038 * float(itel), 2)
        report["intel_summary"] = (
            f"Posture, supply, and war intentions on {target} (visibility {vis}/100, intel quality {q})."
        )
    if outcome in ("detected", "failed_traced"):
        at = list(state.get("active_tensions") or [])
        at.append(
            {
                "tick": tick,
                "source": "intrigue",
                "parties": [op.get("source_faction", ""), target],
                "severity": 6,
                "summary": f"Covert operation ({action}) from {op.get('source_faction', '')} toward {target} surfaces in rumor.",
            }
        )
        state["active_tensions"] = at[-24:]

    return report


def _flatten_spy_networks(rows: List[dict], cfg: dict) -> List[dict]:
    dci_by: Dict[str, int] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        fac = (r.get("faction") or "").strip()
        if fac:
            dci_by[fac] = int(
                _clamp(
                    float((r or {}).get("counter_intelligence", 40) or 40), 0.0, 100.0
                )
            )
    out: List[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        fac = (r.get("faction") or "").strip()
        sm = r.get("spy_networks") or {}
        if not isinstance(sm, dict):
            continue
        for tgt, raw in sm.items():
            if not tgt:
                continue
            cell = _coerce_network_cell(raw)
            ns = int(cell["network_strength"])
            ex = int(cell["exposure"])
            tstr = str(tgt)
            out.append(
                {
                    "faction_id": fac,
                    "target_faction": tstr,
                    "network_strength": ns,
                    "defender_counter_intelligence": dci_by.get(
                        tstr, 40
                    ),
                    "detection_risk": _detection_risk_for_edge(ns, ex, cfg),
                }
            )
    return sorted(
        out, key=lambda x: (-x.get("network_strength", 0), x.get("faction_id", ""))
    )[:200]


def run_intrigue_system(state: dict) -> None:
    t = int(state.get("tick", 0) or 0)
    if state.get("_intrigue_system_tick") == t:
        return
    try:
        from sim_engine_sanitize import sanitize_world_state

        sanitize_world_state(state)
    except Exception:
        pass
    state["_intrigue_system_tick"] = t
    state["intrigue_actions"] = []
    state["spy_networks"] = []
    state["assassination_reports"] = []
    state["sabotage_reports"] = []
    state["blackmail_reports"] = []
    state["counterintelligence_report"] = {
        "detected_actions": [],
        "exposed_factions": [],
        "penalties": [],
    }
    state["intrigue_decisions"] = []
    _prune_blackmail_coercion(state, t)
    _restore_sabotage_fortifications(state, t)

    raw_cfg = state.get("intrigue_config")
    cfg: Dict[str, Any] = {**DEFAULT_INTRIGUE_CONFIG, **(raw_cfg if isinstance(raw_cfg, dict) else {})}

    random.seed(t * 15007 + 91)

    fids = list_faction_ids(state)
    if not fids:
        return

    by_f = _ensure_faction_intrigue_map(state)
    _apply_spy_network_passive_tick(by_f, fids, cfg)
    pending: List[dict] = [x for x in (state.get("intrigue_pending") or []) if isinstance(x, dict)]
    this_tick: List[dict] = []
    decision_entries: List[dict] = []
    max_comp = int(cfg.get("max_completions_per_tick", 6) or 6)
    max_new = int(cfg.get("max_new_starts_per_tick", 3) or 3)
    max_ops = int(cfg.get("max_ops_per_faction", 1) or 1)
    n_started = 0
    n_done = 0

    new_pending: List[dict] = []
    for op in pending:
        if op.get("source_faction") not in fids or op.get("target_faction") not in fids:
            continue
        _st = op.get("started_tick")
        tid = int(t) if _st is None else int(_st)
        elapsed = t - tid
        ticks_req = int(op.get("ticks_required", 1) or 1)
        if ticks_req < 1:
            ticks_req = 1
        if elapsed < 0:
            new_pending.append(op)
            continue
        if elapsed < ticks_req:
            new_pending.append(op)
            pro = {
                "tick": t,
                "op_id": op.get("id", ""),
                "action": op.get("action", ""),
                "status": "in_progress",
                "source_faction": op.get("source_faction", ""),
                "target_faction": op.get("target_faction", ""),
                "actor": op.get("actor", ""),
                "intelligence_used": int(op.get("intelligence", 0) or 0),
                "gold_paid": int(op.get("gold_paid", 0) or 0),
                "ticks_total": ticks_req,
                "ticks_remaining": max(0, ticks_req - elapsed - 1),
            }
            this_tick.append(pro)
            continue
        if n_done >= max_comp:
            new_pending.append(op)
            continue
        src = str(op.get("source_faction", ""))
        tgt = str(op.get("target_faction", ""))
        srow = by_f.get(src) or _get_or_create_faction_row(src, by_f, fids)
        rep = _resolve_completed(op, srow, tgt, state, cfg, t, by_f)
        this_tick.append(rep)
        n_done += 1

    by_source: DefaultDict[str, int] = defaultdict(int)
    for op in new_pending:
        by_source[str(op.get("source_faction", ""))] += 1

    fids_shuffled = fids[:]
    random.shuffle(fids_shuffled)

    # start new operations
    for source in fids_shuffled:
        if n_started >= max_new:
            break
        if by_source[source] >= max_ops:
            continue
        ch, itel, ing = _agent_for_faction(source, state)
        if not ch:
            continue
        if random.random() > _start_intrigue_probability(
            source, itel, cfg
        ):
            continue
        target = _pick_target_for_intrigue(source, fids, state)
        if not target or target == source:
            target = _pick_target(source, state)
        if not target or target == source:
            continue
        afford = _gold_stockpile(source, state)
        srow = by_f.get(source) or _get_or_create_faction_row(source, by_f, fids)
        ns_vs = _get_cell(srow, target)["network_strength"]
        min_asn = int(cfg.get("assassination_min_network_strength", 18) or 18)
        min_sab = int(cfg.get("sabotage_min_network_strength", 6) or 6)
        min_bm = int(cfg.get("blackmail_min_network_strength", 8) or 8)
        viable: List[str] = []
        for a in ACTION_TYPES:
            mi, gc, _tk, _ = _action_costs(a, cfg)
            if mi > itel or gc > afford * 0.55:
                continue
            if a == "assassination" and ns_vs < min_asn:
                continue
            if a == "sabotage" and ns_vs < min_sab:
                continue
            if a == "blackmail" and ns_vs < min_bm:
                continue
            viable.append(a)
        if not viable:
            continue
        action = _select_intrigue_action(
            viable, source, target, itel, state
        )
        if not action:
            continue
        _mi, g_need, t_need, _ = _action_costs(action, cfg)
        w = _W_ACTION.get(action, 1.0)
        gold = int(_clamp(g_need * w * (0.88 + 0.08 * random.random()), 12, 9000))
        if not _spend_gold(source, gold, state):
            continue
        victim = ""
        if action == "assassination":
            victim = _pick_target_character_name(target, state)
        elif action == "blackmail":
            victim = _pick_blackmail_victim(target, state)
        oid = _op_id(f"{t}|{source}|{target}|{action}|{uuid.uuid4()}")
        stab_t = _location_avg_stability(target, state)
        dec_prof = f"{_intrigue_culture_tag(source)}:stab{int(stab_t)}"
        opn = {
            "id": oid,
            "action": action,
            "source_faction": source,
            "target_faction": target,
            "actor": (ch.get("name") or "").strip() or "operative",
            "intelligence": itel,
            "intrigue_skill": ing,
            "gold_paid": gold,
            "ticks_required": t_need,
            "started_tick": t,
            "target_character": victim,
            "decision_profile": dec_prof,
        }
        if action == "sabotage":
            if _is_chaotic_sabotage_faction(source):
                opn["sabotage_kind"] = str(
                    random.choices(
                        SABOTAGE_KINDS, weights=(0.38, 0.32, 0.3), k=1
                    )[0]
                )
            else:
                opn["sabotage_kind"] = random.choice(SABOTAGE_KINDS)
        decision_entries.append(
            {
                "tick": t,
                "source_faction": source,
                "target_faction": target,
                "action": action,
                "agent_intelligence": itel,
                "culture": _intrigue_culture_tag(source),
                "target_avg_stability": round(stab_t, 1),
                "op_id": oid,
            }
        )
        new_pending.append(opn)
        by_source[source] += 1
        n_started += 1
        this_tick.append(
            {
                "tick": t,
                "op_id": oid,
                "action": action,
                "status": "started",
                "source_faction": source,
                "target_faction": target,
                "actor": opn["actor"],
                "intelligence_used": itel,
                "gold_cost": gold,
                "ticks_total": t_need,
                "ticks_remaining": t_need,
                "target_avg_stability": round(stab_t, 1),
                "decision_culture": _intrigue_culture_tag(source),
            }
        )

    # cap
    mp = int(cfg.get("max_pending", 32) or 32)
    new_pending = new_pending[-mp:]
    state["intrigue_pending"] = new_pending
    state["intrigue_decisions"] = decision_entries[-32:]

    state["counterintelligence_report"] = _apply_counterintelligence_sweep(
        state, by_f, cfg, t
    )
    emax = int(cfg.get("max_network_edges_per_faction", 24) or 24)
    out_rows = [by_f[f] for f in sorted(by_f.keys())]
    for row in out_rows:
        if isinstance((row or {}).get("intrigue_level"), (int, float)):
            row["intrigue_level"] = int(_clamp(float(row.get("intrigue_level", 0) or 0), 0, 100))
        if isinstance((row or {}).get("counter_intelligence"), (int, float)):
            row["counter_intelligence"] = int(
                _clamp(
                    float(row.get("counter_intelligence", 40) or 40), 0.0, 100.0
                )
            )
        row["spy_networks"] = _migrate_spy_networks_map(row.get("spy_networks"))
        _trim_spy_network_row(row, emax)
    state["faction_intrigue"] = out_rows
    state["intrigue_actions"] = this_tick[:80]
    state["spy_networks"] = _flatten_spy_networks(out_rows, cfg)

    for h in reversed(state.get("tick_history") or []):
        if h.get("tick") == t:
            h["intrigue_actions"] = list(state.get("intrigue_actions") or [])
            h["spy_networks"] = list(state.get("spy_networks") or [])
            h["assassination_reports"] = list(state.get("assassination_reports") or [])
            h["sabotage_reports"] = list(state.get("sabotage_reports") or [])
            h["blackmail_reports"] = list(state.get("blackmail_reports") or [])
            h["counterintelligence_report"] = (
                state.get("counterintelligence_report")
                if isinstance(
                    state.get("counterintelligence_report"), dict
                )
                else {
                    "detected_actions": [],
                    "exposed_factions": [],
                    "penalties": [],
                }
            )
            h["intrigue_decisions"] = list(
                state.get("intrigue_decisions") or []
            )
            break
