"""
Ruler legitimacy (0–100): lineage, war performance, economy, popular unrest, treaty standing.

State:
  ruler_legitimacy_scores — { faction: float } persistent baseline for EMA
  legitimacy_report     — [ { faction_id, legitimacy, risk_level, ... } ]
  legitimacy_events     — named threshold / crisis hooks for narrative
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional

from engine.beliefs import belief_summary, dominant_belief
from engine.causality import record_cause

__all__ = ["run_legitimacy_system", "risk_label_for_legitimacy", "composite_legitimacy_score"]


def _clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


def risk_label_for_legitimacy(leg: float) -> str:
    if leg >= 50:
        return "stable"
    if leg >= 35:
        return "straining"  # <50: broader instability; straining = early stage
    if leg >= 30:
        return "unstable"  # <30: factions may rebel
    if leg >= 15:
        return "rebellion_risk"
    return "coup_risk"  # <15: coup or civil war likely


def _dynasty_prestige(lead: dict) -> float:
    best = 50.0
    for d in lead.get("dynasties") or []:
        if not isinstance(d, dict):
            continue
        if str(d.get("status", "active")).lower() != "active":
            continue
        best = max(best, float(d.get("prestige", 50) or 50))
    return best


def _avg_stability_faction(faction: str, state: dict) -> float:
    vals: List[int] = []
    for loc in state.get("locations") or []:
        if not isinstance(loc, dict):
            continue
        if loc.get("controller") != faction:
            continue
        vals.append(int(loc.get("stability", loc.get("control", 50)) or 50))
    return sum(vals) / max(1, len(vals)) if vals else 55.0


def _economic_health(faction: str, state: dict) -> float:
    for row in state.get("faction_economy") or []:
        if (row.get("faction_id") or row.get("faction")) != faction:
            continue
        se = (row.get("shortage_effects") or {}) if isinstance(row, dict) else {}
        sev = 0.0
        for r in ("grain", "gold", "iron", "timber"):
            sev += float((se.get(r) or {}).get("severity", 0) or 0)
        sev = min(1.0, sev * 0.25)
        return _clamp(100.0 * (1.0 - sev * 0.9))
    return 50.0


def _war_performance_legitimacy(faction: str, state: dict) -> float:
    """Higher when the war map favors this side (advantage is attacker-positive)."""
    score = 50.0
    for wo in state.get("war_outcomes") or []:
        if not isinstance(wo, dict):
            continue
        att, defe = wo.get("attacker", ""), wo.get("defender", "")
        if faction not in (att, defe):
            continue
        adv = float(wo.get("advantage", 0) or 0)
        if faction == att:
            score += _clamp(14.0 * (adv / 28.0), -14, 14)
        else:
            score += _clamp(14.0 * (-adv / 28.0), -14, 14)
    return _clamp(score)


def _treaty_standing_legitimacy(faction: str, state: dict) -> float:
    st = float((state.get("diplomatic_standing") or {}).get(faction, 50) or 50)
    wto = float(state.get("world_treaty_order", 100) or 100)
    base = 0.5 * st + 0.5 * wto
    for row in state.get("treaty_tick_outcomes") or []:
        if not isinstance(row, dict) or row.get("status") != "broken":
            continue
        for ch in row.get("trust_changes") or []:
            if not isinstance(ch, dict):
                continue
            be = ch.get("breach_event") or {}
            if (be.get("breacher") or "") == faction:
                base -= 18.0
    return _clamp(base)


def _tributary_strain(faction: str, state: dict) -> float:
    """Being subordinate with high resentment erodes regime legitimacy at home."""
    r = float((state.get("tributary_resentment") or {}).get(faction, 0) or 0)
    return _clamp(55.0 - r * 0.45)


def composite_legitimacy_score(
    faction: str,
    state: dict,
    lead: Optional[dict] = None,
) -> float:
    """Unweighted components blended into 0–100 one-shot target."""
    if lead is None:
        for row in state.get("leadership_state") or []:
            if (row.get("faction") or "") == faction:
                lead = row
                break
    line = float((state.get("dynastic_legitimacy") or {}).get(faction, 50) or 50)
    if lead:
        line = 0.55 * line + 0.45 * _dynasty_prestige(lead)

    mwar = _war_performance_legitimacy(faction, state)
    for p in state.get("faction_power_state") or []:
        if p.get("faction") == faction:
            mil = int(p.get("militaryPower", 50) or 50)
            pol = int(p.get("politicalInfluence", 50) or 50)
            mwar = 0.5 * mwar + 0.25 * mil + 0.25 * pol
            break

    eco = _economic_health(faction, state)
    unrest = _avg_stability_faction(faction, state)  # high stability = low unrest signal
    treaty = _treaty_standing_legitimacy(faction, state)
    trib = _tributary_strain(faction, state)

    # Pressure from population rows tagged to this faction, if any
    pop_strain = 50.0
    ps = [p for p in (state.get("population_state") or []) if p.get("faction") == faction]
    if ps:
        pr_avg = sum(int(p.get("pressure", 50) or 50) for p in ps) / len(ps)
        pop_strain = _clamp(100.0 - pr_avg * 0.65)

    target = (
        0.20 * line
        + 0.18 * mwar
        + 0.16 * eco
        + 0.16 * unrest
        + 0.14 * treaty
        + 0.10 * trib
        + 0.06 * pop_strain
    )
    return _clamp(target)


def _apply_rule_effects(
    faction: str, leg: float, risk: str, state: dict
) -> None:
    """Loyal / restive armies and local order."""
    if leg >= 62:
        for a in state.get("faction_armies") or []:
            if (a.get("faction") or a.get("faction_id")) != faction:
                continue
            a["morale"] = int(_clamp(int(a.get("morale", 55) or 55) + 1, 0, 100))
        for loc in state.get("locations") or []:
            if not isinstance(loc, dict) or loc.get("controller") != faction:
                continue
            if str(loc.get("region_type", "")).lower() == "capital":
                loc["stability"] = int(
                    _clamp(int(loc.get("stability", 50) or 50) + 1, 0, 100)
                )
                break
    elif leg < 42:
        for a in state.get("faction_armies") or []:
            if (a.get("faction") or a.get("faction_id")) != faction:
                continue
            a["morale"] = int(_clamp(int(a.get("morale", 55) or 55) - 1, 0, 100))
    if 30 <= leg < 50:
        for loc in state.get("locations") or []:
            if not isinstance(loc, dict) or loc.get("controller") != faction:
                continue
            if str(loc.get("region_type", "")).lower() in ("capital",) or int(
                loc.get("value", 50) or 50
            ) > 80:
                loc["stability"] = int(
                    _clamp(int(loc.get("stability", 50) or 50) - 1, 0, 100)
                )
                break
    elif leg < 30:
        nudged = 0
        for loc in state.get("locations") or []:
            if not isinstance(loc, dict) or loc.get("controller") != faction:
                continue
            loc["stability"] = int(_clamp(int(loc.get("stability", 50) or 50) - 1, 0, 100))
            nudged += 1
            if nudged >= 2:
                break


def _append_legitimacy_loc_event(
    loc_ev: list, t: int, faction: str, summary: str
) -> None:
    loc_ev.append(
        {
            "tick": t,
            "faction": faction,
            "category": "legitimacy_crisis",
            "summary": summary,
        }
    )


def _record_legitimacy_cause(
    state: dict,
    *,
    faction: str,
    event_type: str,
    severity: int,
    summary: str,
    legitimacy: float,
    risk: str,
) -> None:
    record_cause(
        state,
        domain="legitimacy",
        actor=faction,
        pressure=f"legitimacy crisis; legitimacy={round(legitimacy, 1)}; risk={risk}",
        belief=belief_summary(dominant_belief(state, faction)),
        decision=event_type,
        outcome=summary,
        affected=[faction],
        severity=severity,
        confidence=0.86,
        source="legitimacy_system",
    )


def _maybe_events(
    faction: str, leg: float, risk: str, state: dict
) -> None:
    ev = state.setdefault("legitimacy_events", [])
    t = int(state.get("tick", 0) or 0)
    r = random.random()
    loc_ev = state.setdefault("location_events", [])
    if leg < 15 and r < 0.12:
        e = {
            "tick": t,
            "faction": faction,
            "event_type": "military_overthrow",
            "severity": 10,
        }
        ev.append(e)
        summary = "Military overthrow: regime legitimacy collapsed"
        _append_legitimacy_loc_event(loc_ev, t, faction, summary)
        _record_legitimacy_cause(
            state,
            faction=faction,
            event_type="military_overthrow",
            severity=10,
            summary=summary,
            legitimacy=leg,
            risk=risk,
        )
    elif leg < 30 and r < 0.08:
        e = {
            "tick": t,
            "faction": faction,
            "event_type": "noble_rebellion",
            "severity": 8,
        }
        ev.append(e)
        summary = "Noble houses move against a discredited crown"
        _append_legitimacy_loc_event(loc_ev, t, faction, summary)
        _record_legitimacy_cause(
            state,
            faction=faction,
            event_type="noble_rebellion",
            severity=8,
            summary=summary,
            legitimacy=leg,
            risk=risk,
        )
    elif leg < 50 and r < 0.05:
        e = {
            "tick": t,
            "faction": faction,
            "event_type": "claimant_arises",
            "severity": 6,
        }
        ev.append(e)
        summary = "A pretender with dynastic color presses a formal claim"
        _append_legitimacy_loc_event(loc_ev, t, faction, summary)
        _record_legitimacy_cause(
            state,
            faction=faction,
            event_type="claimant_arises",
            severity=6,
            summary=summary,
            legitimacy=leg,
            risk=risk,
        )
    state["legitimacy_events"] = ev[-24:]
    state["location_events"] = list(loc_ev)[-30:]


def _merge_legitimacy_history(state: dict) -> None:
    rep = state.get("legitimacy_report")
    t = int(state.get("tick", 0) or 0)
    for h in reversed(state.get("tick_history") or []):
        if h.get("tick") == t:
            h["legitimacy_report"] = rep
            break


def run_legitimacy_system(state: dict) -> None:
    """
    Recompute EMA legitimacy per faction, apply effects, emit risk + events.
    """
    t = int(state.get("tick", 0) or 0)
    if state.get("_legitimacy_system_tick") == t:
        return
    state["_legitimacy_system_tick"] = t

    state.setdefault("ruler_legitimacy_scores", {})
    if not isinstance(state.get("ruler_legitimacy_scores"), dict):
        state["ruler_legitimacy_scores"] = {}
    prev_map: Dict[str, float] = {
        k: float(v) for k, v in (state.get("ruler_legitimacy_scores") or {}).items()
    }

    out: List[dict] = []
    for lead in state.get("leadership_state") or []:
        if not isinstance(lead, dict):
            continue
        fac = (lead.get("faction") or "").strip()
        if not fac:
            continue
        target = composite_legitimacy_score(fac, state, lead=lead)
        old = prev_map.get(fac, target)
        leg = 0.68 * old + 0.32 * target
        leg = _clamp(leg, 0, 100)
        state["ruler_legitimacy_scores"][fac] = leg

        risk = risk_label_for_legitimacy(leg)
        out.append(
            {
                "faction_id": fac,
                "legitimacy": round(leg, 1),
                "risk_level": risk,
            }
        )
        _apply_rule_effects(fac, leg, risk, state)
        _maybe_events(fac, leg, risk, state)

    out.sort(key=lambda r: (r.get("legitimacy", 0) or 0))
    state["legitimacy_report"] = out
    _merge_legitimacy_history(state)
