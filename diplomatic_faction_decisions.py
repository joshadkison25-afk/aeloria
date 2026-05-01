"""
Per-tick diplomatic posture for each faction: structured intent, not auto-enforcement.

Priority: survival > stability > influence > expansion.
Inputs: relationships, treaties, dynastic/marriage ties, economy, military, locations, legitimacy.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Tuple

from economy_simulation import list_faction_ids
from econ_trade_routes import _is_at_war  # type: ignore[attr-defined]
from axiom.engine.beliefs import belief_summary, dominant_belief
from axiom.engine.causality import record_cause


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _faction_id_from_power_row(p: dict) -> str:
    return str(
        p.get("faction")
        or p.get("faction_id")
        or p.get("id")
        or ""
    ).strip()


def _iter_faction_power_dicts(state: dict):
    """Skip non-dict or legacy/invalid entries (saves with stray strings, etc.)."""
    for p in state.get("faction_power_state", []) or []:
        if not isinstance(p, dict):
            continue
        if not _faction_id_from_power_row(p):
            continue
        yield p


def _power_row(f: str, state: dict) -> Dict[str, int]:
    for p in _iter_faction_power_dicts(state):
        if _faction_id_from_power_row(p) == f:
            return {
                "military": int(p.get("militaryPower", 50) or 50),
                "economic": int(p.get("economicPower", 50) or 50),
                "political": int(p.get("politicalInfluence", 50) or 50),
            }
    return {"military": 50, "economic": 50, "political": 50}


def _legitimacy(f: str, state: dict) -> float:
    for r in state.get("legitimacy_report", []) or []:
        if not isinstance(r, dict):
            continue
        if r.get("faction_id") == f:
            return float(r.get("legitimacy", 50) or 50)
    for k, v in (state.get("ruler_legitimacy_scores") or {}).items():
        if k == f:
            return float(v)
    return 50.0


def _avg_stability(f: str, state: dict) -> float:
    vals: List[int] = []
    for loc in state.get("locations", []) or []:
        if not isinstance(loc, dict):
            continue
        if loc.get("controller") == f:
            vals.append(int(loc.get("stability", loc.get("control", 50)) or 50))
    return sum(vals) / max(1, len(vals)) if vals else 50.0


def _resource_stress(f: str, state: dict) -> float:
    for row in state.get("faction_economy", []) or []:
        if not isinstance(row, dict):
            continue
        if (row.get("faction_id") or row.get("faction")) != f:
            continue
        se = (row.get("shortage_effects") or {}) if isinstance(row, dict) else {}
        s = 0.0
        for r in ("grain", "gold", "iron", "timber"):
            s += float((se.get(r) or {}).get("severity", 0) or 0)
        return _clamp(s * 0.22, 0.0, 1.0)
    return 0.0


def _rel_partner_trusts(f: str, state: dict) -> List[Tuple[str, float, str]]:
    out: List[Tuple[str, float, str]] = []
    for r in state.get("relationships", []) or []:
        if not isinstance(r, dict):
            continue
        a, b = r.get("faction_a", ""), r.get("faction_b", "")
        if a == f:
            other, t = b, (r.get("type") or "neutral")
        elif b == f:
            other, t = a, (r.get("type") or "neutral")
        else:
            continue
        tr = float(r.get("trust", 50) or 50)
        out.append((str(other), tr, t))
    return sorted(out, key=lambda x: -x[1])[:20]


def _active_treaty_count(f: str, state: dict) -> int:
    n = 0
    t = int(state.get("tick", 0) or 0)
    for p in state.get("treaties", []) or []:
        if not isinstance(p, dict) or p.get("status") != "active":
            continue
        if f not in (p.get("participants") or []):
            continue
        st = p.get("start_tick")
        start = int(st) if st is not None else t
        dur = int(p.get("duration", 0) or 0)
        if t >= start + max(0, dur):
            continue
        n += 1
    return n


def _marriage_tie_strength(f: str, state: dict) -> float:
    s = 0.0
    for m in state.get("noble_marriages", []) or []:
        if not isinstance(m, dict):
            continue
        if m.get("faction_a") == f or m.get("faction_b") == f:
            s += 0.25 + 0.02 * min(40, int(m.get("marriage_trust_ticks", 0) or 0))
    for row in state.get("dynastic_report", {}).get("marriages", []) or []:
        if not isinstance(row, dict):
            continue
        if row.get("faction_a") == f or row.get("faction_b") == f:
            s += float(row.get("dynastic_tie_strength", 0) or 0) * 0.2
    return _clamp(s, 0.0, 1.0)


def _pick_alliance_target(f: str, state: dict, not_war: bool = True) -> str:
    best = ("", -1.0)
    for other, tr, t in _rel_partner_trusts(f, state):
        if not other or other == f:
            continue
        if not_war and _is_at_war(f, other, state):
            continue
        if t in ("alliance", "war"):
            continue
        h = tr + (10 if t == "rivalry" else 0) * -0.1
        if h > best[1]:
            best = (other, h)
    return best[0]


def _weaker_neighbor(f: str, state: dict) -> str:
    pm = _power_row(f, state)["military"]
    best = ("", 999)
    for p in _iter_faction_power_dicts(state):
        o = _faction_id_from_power_row(p)
        if not o or o == f or _is_at_war(f, o, state):
            continue
        om = int(p.get("militaryPower", 50) or 50)
        if pm > om + 8 and om < best[1]:
            best = (o, om)
    return best[0]


def _claimant_opportunity(f: str, state: dict) -> Tuple[str, str]:
    dr = state.get("dynastic_report")
    if not isinstance(dr, dict):
        return "", ""
    for c in dr.get("claims", []) or []:
        if not isinstance(c, dict):
            continue
        tgt = c.get("target_faction", "")
        if not tgt or tgt == f:
            continue
        if not _is_at_war(f, tgt, state) and c.get("claim_strength", 0) and float(
            c.get("claim_strength", 0) or 0
        ) > 32:
            return tgt, (c.get("claimant", "") or "claimant")
    return "", ""


def _diplomatic_style(faction: str) -> Dict[str, float]:
    x = faction.lower()
    if "twin" in x:
        return {
            "formality": 0.88,
            "legitimacy_weight": 0.85,
            "manipulation": 0.35,
            "trade_focus": 0.45,
            "coercion": 0.25,
            "alliance_hunger": 0.4,
        }
    if "eldoria" in x or "lefleur" in x:
        return {
            "formality": 0.5,
            "legitimacy_weight": 0.45,
            "manipulation": 0.85,
            "trade_focus": 0.4,
            "coercion": 0.4,
            "alliance_hunger": 0.9,
        }
    if "faerwood" in x or "shadow" in x or "verlorn" in x:
        return {
            "formality": 0.35,
            "legitimacy_weight": 0.4,
            "manipulation": 0.92,
            "trade_focus": 0.3,
            "coercion": 0.2,
            "alliance_hunger": 0.5,
        }
    if "farrock" in x or "lostfeld" in x:
        return {
            "formality": 0.3,
            "legitimacy_weight": 0.35,
            "manipulation": 0.45,
            "trade_focus": 0.4,
            "coercion": 0.9,
            "alliance_hunger": 0.5,
        }
    if "tidefall" in x or "ver meer" in x or "tide" in x:
        return {
            "formality": 0.55,
            "legitimacy_weight": 0.5,
            "manipulation": 0.5,
            "trade_focus": 0.95,
            "coercion": 0.4,
            "alliance_hunger": 0.6,
        }
    return {
        "formality": 0.5,
        "legitimacy_weight": 0.5,
        "manipulation": 0.5,
        "trade_focus": 0.5,
        "coercion": 0.5,
        "alliance_hunger": 0.5,
    }


def _priority_tier(
    stress: float, leg: float, stab: float, pmil: int, at_war: bool
) -> str:
    if at_war and pmil < 38 and stress > 0.25:
        return "survival"
    if leg < 32 or stress > 0.45 or stab < 38:
        return "stability"
    if leg < 50 or stress > 0.2:
        return "influence"
    return "expansion"


def _choose_action(
    f: str, state: dict, st: Dict[str, float]
) -> Tuple[str, str, Dict[str, Any]]:
    pw = _power_row(f, state)
    stress = _resource_stress(f, state)
    leg = _legitimacy(f, state)
    stab = _avg_stability(f, state)
    at_war = any(
        isinstance(r, dict)
        and (r.get("type") or "") == "war"
        and f in (r.get("faction_a", ""), r.get("faction_b", ""))
        for r in (state.get("relationships", []) or [])
    )
    band = _priority_tier(stress, leg, stab, pw["military"], at_war)
    n_treaty = _active_treaty_count(f, state)
    m_tie = _marriage_tie_strength(f, state)
    meta: Dict[str, Any] = {
        "legitimacy": round(leg, 1),
        "stability": round(stab, 1),
        "resource_stress": round(stress, 3),
        "active_treaties": n_treaty,
        "marriage_tie_strength": round(m_tie, 3),
        "military": pw["military"],
    }
    if band == "survival" and (stress > 0.3 or leg < 28):
        tgt = _pick_alliance_target(f, state, not_war=True)
        if tgt:
            meta["target_faction"] = tgt
            return "alliance_proposal", "survival_bloc", meta
        wk = _weaker_neighbor(f, state)
        if wk:
            meta["target_faction"] = wk
        return "quiet_diplomacy", "buy_time", meta

    if band == "stability":
        if st.get("formality", 0.5) > 0.7 and m_tie < 0.4 and st.get("legitimacy_weight", 0.5) > 0.5:
            partner = _pick_alliance_target(f, state) or _weaker_neighbor(f, state)
            if partner:
                meta["partner_faction"] = partner
            return "marriage_diplomacy", "legitimacy_anchored", meta
        if n_treaty > 0 and st.get("manipulation", 0.5) > 0.75:
            return "treaty_renegotiation", "favorable_rebalance", meta
        tgt = _pick_alliance_target(f, state, not_war=True)
        if tgt:
            meta["target_faction"] = tgt
            return "alliance_proposal", "crown_safety", meta
        return "reaffirm_treaties", "internal_order", meta

    if band == "influence":
        if n_treaty > 0 and st.get("manipulation", 0.3) > 0.78 and st.get("coercion", 0) > 0.55:
            return "treaty_exit_intent", "strategic_release", meta
        c_tgt, c_name = _claimant_opportunity(f, state)
        if c_tgt and st.get("manipulation", 0.5) + st.get("alliance_hunger", 0.4) * 0.2 > 0.65:
            meta["target_faction"] = c_tgt
            meta["claimant"] = c_name
            return "support_foreign_claimant", "leverage_succession", meta
        weak = _weaker_neighbor(f, state)
        if weak and st.get("coercion", 0.4) + stress * 0.3 > 0.6:
            meta["target_faction"] = weak
            return "demand_tribute", "extract_obligations", meta
        if n_treaty and st.get("manipulation", 0.3) > 0.6:
            return "treaty_renegotiation", "edge_on_terms", meta
        tgt = _pick_alliance_target(f, state, not_war=True)
        if tgt:
            meta["target_faction"] = tgt
        return "alliance_proposal", "influence_bloc", meta

    # expansion
    if st.get("trade_focus", 0.5) > 0.75 and not at_war:
        tgt = _pick_alliance_target(f, state, not_war=True)
        if tgt:
            meta["target_faction"] = tgt
        return "alliance_proposal", "maritime_pact" if st.get("trade_focus", 0) > 0.8 else "trade_tie", meta
    if st.get("coercion", 0.3) > 0.7:
        wk = _weaker_neighbor(f, state)
        if wk:
            meta["target_faction"] = wk
        return "demand_tribute", "resource_frontier", meta
    mt = _pick_alliance_target(f, state, not_war=True)
    if mt:
        meta["target_faction"] = mt
    return "alliance_proposal", "outward_tie", meta


def _summary(f: str, act: str, rsn: str, meta: Dict[str, Any]) -> str:
    t = meta.get("target_faction") or meta.get("partner_faction", "")
    if act == "alliance_proposal" and t:
        return f"{f} leans on envoys to draw {t} into alignment ({rsn})."
    if act == "demand_tribute" and t:
        return f"{f} signals overlords' terms to {t} — pay or be cast as unruly."
    if act == "marriage_diplomacy" and t:
        return f"{f} courts a dynastic match with {t} to steady the bloodline and borders."
    if act == "support_foreign_claimant" and t:
        return f"{f} dangles support to a rival claimant inside {t}."
    if act == "treaty_exit_intent":
        return f"{f} tests which oaths still serve the throne — and which are dead weight."
    if act == "treaty_renegotiation":
        return f"{f} reopens parchment to move clauses while rivals watch."
    if act == "reaffirm_treaties":
        return f"{f} rehearses oaths in hall — continuity before ambition."
    return f"{f} holds channels open; no single envoy steals the day."


def _merge_diplomacy_history(state: dict) -> None:
    out = state.get("diplomatic_faction_decisions") or []
    t = int(state.get("tick", 0) or 0)
    for h in reversed(state.get("tick_history") or []):
        if h.get("tick") == t:
            h["diplomatic_faction_decisions"] = out
            break


def _diplomacy_decision_severity(decision: dict) -> int:
    action = decision.get("action", "")
    band = decision.get("priority_tier", "")
    if action == "support_foreign_claimant":
        return 12
    if action == "demand_tribute":
        return 11
    if action == "treaty_exit_intent":
        return 10
    if action in ("alliance_proposal", "marriage_diplomacy"):
        return 8 if band in ("survival", "stability") else 6
    if action == "treaty_renegotiation":
        return 7
    return 4


def _record_diplomatic_causes(state: dict, decisions: List[dict]) -> None:
    for decision in decisions:
        action = str(decision.get("action") or "")
        if action in ("quiet_diplomacy", "reaffirm_treaties"):
            continue
        faction = str(decision.get("faction") or "").strip()
        if not faction:
            continue

        meta = decision.get("meta") or {}
        affected = [faction]
        for key in ("target_faction", "partner_faction"):
            if meta.get(key):
                affected.append(str(meta[key]))
        if meta.get("claimant"):
            affected.append(str(meta["claimant"]))
        if meta.get("coercion_source_faction"):
            affected.append(str(meta["coercion_source_faction"]))

        pressure = (
            f"{decision.get('priority_tier', 'diplomatic')} diplomatic pressure; "
            f"reason={decision.get('reason', '')}; "
            f"legitimacy={meta.get('legitimacy', 'unknown')}; "
            f"stability={meta.get('stability', 'unknown')}; "
            f"resource_stress={meta.get('resource_stress', 'unknown')}"
        )
        record_cause(
            state,
            domain="diplomacy",
            actor=faction,
            pressure=pressure,
            belief=belief_summary(dominant_belief(state, faction)),
            decision=action,
            outcome=str(decision.get("summary") or ""),
            affected=list(dict.fromkeys(affected)),
            hidden=(
                "Diplomatic posture is shaped by active blackmail coercion."
                if meta.get("coercion_hold")
                else ""
            ),
            severity=_diplomacy_decision_severity(decision),
            confidence=0.78,
            source="diplomatic_faction_decisions",
        )


def run_diplomatic_faction_decisions(state: dict) -> None:
    """Set state['diplomatic_faction_decisions'] to one record per faction (capped)."""
    try:
        from sim_engine_sanitize import sanitize_world_state

        sanitize_world_state(state)
    except Exception:
        pass
    t = int(state.get("tick", 0) or 0)
    if state.get("_diplomatic_faction_decisions_tick") == t:
        return
    state["_diplomatic_faction_decisions_tick"] = t

    if not isinstance(state.get("dynastic_report"), dict):
        state["dynastic_report"] = {"marriages": [], "claims": [], "potential_conflicts": []}
    factions = list_faction_ids(state)[:32]

    out: List[dict] = []
    for f in factions:
        stl = _diplomatic_style(f)
        act, rsn, meta = _choose_action(f, state, stl)
        band = _priority_tier(
            _resource_stress(f, state),
            _legitimacy(f, state),
            _avg_stability(f, state),
            _power_row(f, state)["military"],
            any(
                isinstance(r, dict)
                and r.get("type") == "war"
                and f in (r.get("faction_a"), r.get("faction_b"))
                for r in (state.get("relationships", []) or [])
            ),
        )
        row: Dict[str, Any] = {
            "faction": f,
            "priority_tier": band,
            "action": act,
            "reason": rsn,
            "summary": _summary(f, act, rsn, meta),
            "meta": dict(meta),
        }
        coerced = [
            x
            for x in (state.get("active_blackmail_coercion") or [])
            if isinstance(x, dict) and x.get("target_faction") == f
        ]
        if coerced:
            c0 = coerced[0]
            src = str(c0.get("source_faction") or "")
            row["meta"]["coercion_hold"] = True
            row["meta"]["coercion_source_faction"] = src
            row["meta"]["coercion_leverage_character"] = c0.get("character")
            row["summary"] = (
                row["summary"]
                + f" Coercion shadow: insider pressure linked to {src}."
            )
            if act == "demand_tribute" and random.random() < 0.42:
                row["action"] = "quiet_diplomacy"
                row["reason"] = "coercion_curtail"
                row["summary"] = (
                    f"{f} softens harsh demands; whispers suggest a court figure is leveraged by {src}."
                )
        out.append(row)
    state["diplomatic_faction_decisions"] = out
    _record_diplomatic_causes(state, out)
    _merge_diplomacy_history(state)


__all__ = ["run_diplomatic_faction_decisions"]
