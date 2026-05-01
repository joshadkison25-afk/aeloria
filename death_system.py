"""
Mechanical character death: old age, illness, battle, assassination/events.

Runs after each tick's house_characters are aged and healed in `_normalize_house_characters`,
so ages/health match attrition and economy from `updateWorld`.

Output: `state["death_events"]` = [ { "event", "character", "cause", "succession_triggered" }, ... ]
Optional narrative hooks: `pending_character_deaths` = [ { "name", "cause" } ] (processed then cleared).
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["run_death_system", "DEFAULT_DEATH_CONFIG"]

DEFAULT_DEATH_CONFIG = {
    "max_combined_roll": 0.48,
    "mortality_onset_fraction": 0.69,  # human ~50 when natural=72
    "linear_elder_coeff": 0.00012,
    "elder_exp_k": 0.05,
    "max_elder_component": 0.14,
    "battle_loss_factor": 0.0007,
    "general_risk_mult": 2.8,
    "influence_important_threshold": 72,
    "ruler_legitimacy_penalty": 11.0,
    "notable_legitimacy_penalty": 3.5,
    "minor_legitimacy_penalty": 0.6,
    "max_deaths_per_tick": 4,
}

_CAUSE_OLD_AGE = "old_age"
_CAUSE_ILLNESS = "illness"
_CAUSE_BATTLE = "battle"
_CAUSE_ASSASSINATION = "assassination"
_CAUSE_EVENT = "event"


def _name_key(n: str) -> str:
    return (n or "").strip().lower()


def _is_living(c: dict) -> bool:
    s = str(c.get("status", "alive") or "alive").lower()
    if s.startswith("deceased") or s in ("dead", "killed", "slain"):
        return False
    return True


def _parse_age_f(val) -> float:
    try:
        return float(str(val).strip())
    except (TypeError, ValueError):
        return 30.0


def _norm_race(r: str) -> str:
    x = (r or "Human").strip()
    lo = x.lower()
    m = {
        "human": "Human",
        "dwarf": "Dwarf",
        "dwarv": "Dwarf",
        "dwarven": "Dwarf",
        "high elf": "High Elf",
        "woodel": "Wood Elf",
        "wood elf": "Wood Elf",
        "dark elf": "Dark Elf",
        "shadow": "Dark Elf",
        "orc": "Orc",
        "goblin": "Goblin",
    }
    for k, v in m.items():
        if k in lo:
            return v
    if x in (
        "Human",
        "Dwarf",
        "High Elf",
        "Wood Elf",
        "Dark Elf",
        "Orc",
        "Goblin",
    ):
        return x
    return "Human"


def _elder_exp_risk(age: float, race: str, cfg: dict) -> float:
    from axiom.engine.characters import RACE_LIFESPAN

    r = _norm_race(race)
    span = RACE_LIFESPAN.get(r, RACE_LIFESPAN["Human"])
    frac = float(cfg.get("mortality_onset_fraction", 0.69) or 0.69)
    onset = max(12.0, min(float(span["natural"]) * frac, float(span["natural"]) - 1.0))
    if age < onset:
        return 0.0
    x = age - onset
    lin = float(cfg.get("linear_elder_coeff", 0.00012) or 0.00012)
    ek = float(cfg.get("elder_exp_k", 0.05) or 0.05)
    cap = float(cfg.get("max_elder_component", 0.14) or 0.14)
    p = lin * x * math.exp(min(5.0, x * ek))
    return min(cap, p)


def _is_general_risk(c: dict) -> bool:
    cr = (c.get("coreRole") or "").strip()
    if cr in ("Leader", "Power Role", "Heir"):
        return True
    role = str(c.get("role", "")).lower()
    return any(
        w in role
        for w in ("general", "admiral", "marshal", "commander", "warlord", "captain")
    )


def _important_character(c: dict, state: dict) -> bool:
    if (c.get("coreRole") or "").strip() == "Leader":
        return True
    if int(c.get("influenceScore", 0) or 0) >= int(
        DEFAULT_DEATH_CONFIG.get("influence_important_threshold", 72) or 72
    ):
        return True
    nm = (c.get("name") or "").strip()
    for lead in state.get("leadership_state") or []:
        r = (lead or {}).get("currentRuler") or {}
        if (r.get("name") or "").strip() == nm:
            return True
    return False


def _army_by_id(state: dict) -> Dict[str, dict]:
    return {
        str(a.get("army_id", "")): a
        for a in (state.get("faction_armies") or [])
        if a.get("army_id")
    }


def _battle_death_chances(
    state: dict, by_name: Dict[str, dict], cfg: dict
) -> Dict[str, float]:
    out: Dict[str, float] = {}
    fac = _army_by_id(state)
    bf = float(cfg.get("battle_loss_factor", 0.0007) or 0.0007)
    gm = float(cfg.get("general_risk_mult", 2.8) or 2.8)
    for row in state.get("military_attrition") or []:
        if not isinstance(row, dict):
            continue
        aid = str(row.get("army_id", "") or "")
        loss = int(row.get("loss", 0) or 0)
        if loss < 1:
            continue
        a = fac.get(aid) or {}
        cmd = (a.get("commander") or "").strip()
        if not cmd:
            continue
        ch = by_name.get(_name_key(cmd))
        if not ch or not _is_living(ch):
            continue
        gmult = gm if ch and _is_general_risk(ch) else 1.0
        p = min(0.32, loss * bf * gmult)
        k = _name_key(cmd)
        out[k] = max(out.get(k, 0.0), p)
    return out


def _pending_kill_map(state: dict) -> Dict[str, str]:
    """Map name_key -> cause from pending_character_deaths and engine hooks."""
    m: Dict[str, str] = {}
    for row in list(state.get("pending_character_deaths") or []):
        if not isinstance(row, dict):
            continue
        n = (row.get("name") or row.get("victim") or "").strip()
        c = (row.get("cause") or "event").strip().lower()
        if not n:
            continue
        if c in ("assassination", "assassin", "murder"):
            m[_name_key(n)] = _CAUSE_ASSASSINATION
        elif c in ("battle", "war", "combat"):
            m[_name_key(n)] = _CAUSE_BATTLE
        else:
            m[_name_key(n)] = _CAUSE_EVENT
    state["pending_character_deaths"] = []
    for row in list(state.get("engine_character_deaths") or []):
        if not isinstance(row, dict):
            continue
        n = (row.get("name") or "").strip()
        c = (row.get("cause") or "event").strip()
        if n:
            m[_name_key(n)] = c if c else _CAUSE_EVENT
    state["engine_character_deaths"] = []
    return m


def _cause_label(canonical: str) -> str:
    return {
        _CAUSE_OLD_AGE: "old_age",
        _CAUSE_ILLNESS: "illness",
        _CAUSE_BATTLE: "battle",
        _CAUSE_ASSASSINATION: "assassination",
        _CAUSE_EVENT: "event",
    }.get(canonical, canonical)


def _apply_legitimacy_penalty(
    state: dict, faction: str, mode: str, cfg: dict
) -> None:
    """mode: 'ruler' | 'notable' | 'minor'"""
    rs = state.setdefault("ruler_legitimacy_scores", {})
    base = float(rs.get(faction, 50) or 50)
    if mode == "ruler":
        d = float(cfg.get("ruler_legitimacy_penalty", 11.0) or 11.0)
        et, sev = "ruler_death_legitimacy_shock", 7
    elif mode == "notable":
        d = float(cfg.get("notable_legitimacy_penalty", 3.5) or 3.5)
        et, sev = "notable_death_legitimacy", 3
    else:
        d = float(cfg.get("minor_legitimacy_penalty", 0.6) or 0.6)
        et, sev = "character_death_ripple", 1
    rs[faction] = max(0.0, min(100.0, base - d))
    t = int(state.get("tick", 0) or 0)
    le = state.setdefault("legitimacy_events", [])
    le.append({"tick": t, "faction": faction, "event_type": et, "severity": sev})
    state["legitimacy_events"] = le[-24:]


def _apply_succession(
    state: dict,
    dead: dict,
    cause: str,
) -> bool:
    from succession_system import resolve_ruler_succession

    dead_name = (dead.get("name") or "").strip()
    if not dead_name:
        return False
    t = int(state.get("tick", 0) or 0)
    wdate = str(state.get("world_date", "") or t)
    triggered = False
    co_map = {
        _CAUSE_OLD_AGE: "natural death",
        _CAUSE_ILLNESS: "illness",
        _CAUSE_BATTLE: "killed in battle",
        _CAUSE_ASSASSINATION: "assassination",
        _CAUSE_EVENT: "violent upheaval",
    }
    for lead in list(state.get("leadership_state") or []):
        if not isinstance(lead, dict):
            continue
        cur = lead.get("currentRuler") or {}
        if (cur.get("name") or "").strip() != dead_name:
            continue
        co_end = co_map.get(cause, "death")
        out = resolve_ruler_succession(
            state, lead, cur, dead, dead_name, co_end, wdate, t
        )
        se = state.setdefault("succession_events", [])
        if isinstance(out, dict):
            se.append(out)
        state["succession_events"] = se[-16:]
        triggered = True

    return triggered


def _emit_major_event(state: dict, dead: dict, cause: str, succession: bool) -> None:
    nm = (dead.get("name") or "").strip()
    fac = (dead.get("faction") or "").strip()
    sev = 17 if succession else 12
    summary = f"{nm} of {fac} has died ({cause})."
    if succession:
        summary += " Succession is underway."
    ev = {
        "name": f"Death: {nm}",
        "summary": summary[:220],
        "severity": sev,
        "stage": "peak",
        "trend": "resolving",
        "involved": [fac, nm],
    }
    re = list(state.get("recent_events") or [])
    re.insert(0, ev)
    state["recent_events"] = re[:5]
    pe = state.get("primary_event") or {}
    if int(pe.get("severity", 0) or 0) < 14 and succession:
        state["primary_event"] = {
            "name": ev["name"],
            "summary": ev["summary"],
            "severity": sev,
            "stage": "peak",
            "trend": "unstable",
            "involved": ev["involved"],
        }


def _record_death_causality(state: dict, dead: dict, cause: str, succession: bool) -> None:
    from axiom.engine.causality import record_cause

    name = (dead.get("name") or "").strip()
    faction = (dead.get("faction") or "").strip()
    if not name or not faction:
        return

    succession_event = {}
    if succession:
        for row in reversed(state.get("succession_events") or []):
            if isinstance(row, dict):
                succession_event = row
                break

    new_ruler = succession_event.get("new_ruler") if isinstance(succession_event, dict) else {}
    new_ruler_name = (new_ruler or {}).get("name") or ""
    crisis = succession_event.get("crisis_outcome", "") if isinstance(succession_event, dict) else ""
    risk = succession_event.get("conflict_risk", "") if isinstance(succession_event, dict) else ""

    if succession:
        pressure = (
            f"ruler death; cause={_cause_label(cause)}; legitimacy shock; "
            f"succession_outcome={crisis}; conflict_risk={risk}"
        )
        decision = "resolve_succession"
        outcome = f"{name} died and {new_ruler_name or 'a regency'} now rules {faction}."
        if crisis:
            outcome += f" Succession outcome: {crisis}."
        affected = [faction, name]
        if new_ruler_name:
            affected.append(str(new_ruler_name))
        domain = "succession"
        severity = 15 if crisis in {"contested_claim", "foreign_intervention", "succession_crisis"} else 12
    else:
        pressure = f"character death; cause={_cause_label(cause)}; political continuity holds"
        decision = "register_death"
        outcome = f"{name} of {faction} died from {_cause_label(cause)}."
        affected = [faction, name]
        domain = "character"
        severity = 8 if _important_character(dead, state) else 4

    record_cause(
        state,
        domain=domain,
        actor=faction,
        pressure=pressure,
        belief="succession law and claimant strength determine the new ruler" if succession else "",
        decision=decision,
        outcome=outcome,
        affected=affected,
        severity=severity,
        confidence=0.95,
        source="death_system",
    )


def _death_probability_for_char(
    ch: dict,
    state: dict,
    by_name: Dict[str, dict],
    battle_p: Dict[str, float],
    pending: Dict[str, str],
    cfg: dict,
) -> Tuple[float, str]:
    from axiom.engine.characters import (
        _critical_health_death_chance,
        _health_death_modifier,
        _natural_death_chance,
    )

    age = _parse_age_f(ch.get("age", 30))
    race = str(ch.get("race") or "Human")
    h = float(ch.get("health", 100) or 100)
    nk = _name_key((ch.get("name") or ""))
    if nk in pending:
        return 0.99, pending[nk]

    p_bat = float(battle_p.get(nk, 0.0))
    p_nat = _natural_death_chance(age, _norm_race(race))
    p_elder = _elder_exp_risk(age, race, cfg)
    hm = _health_death_modifier(h)
    p_crit = _critical_health_death_chance(h)
    base = max(p_nat, p_elder) * hm + p_crit
    p = min(float(cfg.get("max_combined_roll", 0.48)), p_bat + base)
    if p_bat >= max(base, 0.0001) and p_bat >= 0.0002:
        return p, _CAUSE_BATTLE
    if p_crit > 0.0008 and p_crit >= max(p_nat, p_elder) * hm * 0.5:
        return p, _CAUSE_ILLNESS
    if h < 22:
        return p, _CAUSE_ILLNESS
    from axiom.engine.characters import RACE_LIFESPAN

    span = RACE_LIFESPAN.get(_norm_race(race), RACE_LIFESPAN["Human"])
    onset = max(12.0, min(float(span["natural"]) * 0.69, float(span["natural"]) - 1.0))
    if age > onset + 3.0 and p_elder >= p_nat:
        return p, _CAUSE_OLD_AGE
    if age > float(span.get("max", 92)) * 0.88:
        return p, _CAUSE_OLD_AGE
    if h < 38:
        return p, _CAUSE_ILLNESS
    return p, _CAUSE_OLD_AGE


def run_death_system(state: dict) -> None:
    t = int(state.get("tick", 0) or 0)
    if state.get("_death_lifecycle_tick") == t:
        return
    state["_death_lifecycle_tick"] = t
    state["succession_events"] = []

    bc = state.get("death_config")
    cfg: Dict[str, Any] = {**DEFAULT_DEATH_CONFIG, **(bc if isinstance(bc, dict) else {})}
    max_d = int(cfg.get("max_deaths_per_tick", 4) or 4)

    random.seed(t * 11003 + len(state.get("house_characters") or []) * 19 + 42)

    hc = list(state.get("house_characters") or [])
    if not hc:
        state["death_events"] = []
        return

    by_name: Dict[str, dict] = {_name_key(c.get("name", "")): c for c in hc if c.get("name")}
    battle_p = _battle_death_chances(state, by_name, cfg)
    pending = _pending_kill_map(state)

    events: List[dict] = []
    n_kill = 0
    to_remove: List[str] = []

    for ch in list(hc):
        if n_kill >= max_d:
            break
        if not isinstance(ch, dict) or not ch.get("name") or not _is_living(ch):
            continue
        p, cause = _death_probability_for_char(ch, state, by_name, battle_p, pending, cfg)
        if p <= 0 or random.random() > p:
            continue

        name = (ch.get("name") or "").strip()
        snap = dict(ch)
        snap["status"] = "deceased"
        to_remove.append(name)
        n_kill += 1

        fac = (ch.get("faction") or "").strip()
        is_ruler = any(
            ((lead or {}).get("currentRuler") or {}).get("name", "").strip() == name
            for lead in (state.get("leadership_state") or [])
        )
        succ = _apply_succession(state, ch, cause)
        if is_ruler:
            leg_mode = "ruler"
        elif _important_character(ch, state):
            leg_mode = "notable"
        else:
            leg_mode = "minor"
        _apply_legitimacy_penalty(state, fac, leg_mode, cfg)
        if is_ruler or succ or _important_character(ch, state):
            _emit_major_event(state, ch, _cause_label(cause), succ)
            _record_death_causality(state, ch, cause, succ)

        events.append(
            {
                "event": "death",
                "character": snap,
                "cause": _cause_label(cause),
                "succession_triggered": succ,
            }
        )

    if to_remove:
        dead_set = {x.strip().lower() for x in to_remove}
        state["house_characters"] = [
            c
            for c in state.get("house_characters", [])
            if (c.get("name") or "").strip().lower() not in dead_set
        ]

    state["death_events"] = events
    for h in reversed(state.get("tick_history", []) or []):
        if h.get("tick") == t:
            h["death_events"] = events
            if state.get("succession_events"):
                h["succession_events"] = list(state.get("succession_events") or [])
            break
