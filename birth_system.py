"""
Character birth: married couples, age gating, chance roll, child generation + stat inheritance.

Marriage: `state['character_marriages']` entries should name parents:
  { "mother": "Full Name", "father": "Full Name", "since_tick": int }
Alternatively { "partner_a", "partner_b" } if both have `sex` "male" / "female".

Output this tick: `state['birth_events']` = [ { "event", "child", "parents" }, ... ]
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

from axiom.engine.causality import record_cause

__all__ = [
    "run_birth_system",
    "DEFAULT_BIRTH_CONFIG",
]

DEFAULT_BIRTH_CONFIG = {
    "base_chance": 0.15,
    "female_age_min": 16,
    "female_age_max": 45,
    "male_age_min": 16,
    "max_births_per_tick": 3,
    "stat_variance": 8,
    "trait_inherit_chance": 0.45,
    "random_extra_trait_chance": 0.08,
    "sibling_count_penalty": 0.12,
    "max_birth_roll": 0.55,
}

# First names (culture-agnostic supplement; world author can grow pools)
_HUMAN = [
    "Alden",
    "Bria",
    "Cael",
    "Dara",
    "Ewan",
    "Fira",
    "Gareth",
    "Helen",
    "Ivor",
    "Jessa",
    "Kira",
    "Lorne",
    "Mira",
    "Nils",
    "Owen",
    "Palla",
    "Roric",
    "Senna",
    "Torin",
    "Una",
]
_ELF = ["Aelth", "Brynn", "Caelu", "Dwyn", "Elen", "Faelis", "Galen", "Hania", "Ithil", "Lyra"]
_ORC = ["Grim", "Hrak", "Korg", "Lurg", "Maz", "Narg", "Ruk", "Shag", "Torg", "Ukk"]
_GOBL = ["Bix", "Crik", "Drip", "Fizz", "Grikk", "Nixx", "Pik", "Rizz", "Tik", "Zig"]
_DWARF = ["Borin", "Draki", "Gorn", "Hilda", "Korin", "Loki", "Mira", "Rurik", "Thorin", "Yrsa"]


def _name_pool(race: str) -> List[str]:
    r = (race or "Human").lower()
    if "elf" in r or "drow" in r or "faerie" in r:
        return _ELF
    if "orc" in r:
        return _ORC
    if "goblin" in r or "gob" in r:
        return _GOBL
    if "dwarf" in r or "dwarv" in r:
        return _DWARF
    return _HUMAN


def _pick_name(house: str, race: str) -> str:
    pool = _name_pool(race)
    first = random.choice(pool)
    if "House" in (house or ""):
        last = (house or "").split()[-1] if " " in (house or "") else house
    else:
        last = (house or "Line").split()[-1] if " " in (house or "") else (house or "Line")
    return f"{first} {last}"


def _age(ch: dict) -> float:
    try:
        return float(ch.get("age", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_alive(ch: dict) -> bool:
    s = str(ch.get("status", "alive") or "alive").lower()
    return s in ("alive", "available for political action", "active", "healthy", "")


def _find_char_by_name(hc: List[dict], name: str) -> Optional[dict]:
    n = (name or "").strip()
    for ch in hc:
        if (ch.get("name") or "").strip() == n:
            return ch
    return None


def _sex(ch: dict) -> str:
    s = str(ch.get("sex", ch.get("gender", "")) or "").lower()
    if s in ("m", "male", "man"):
        return "male"
    if s in ("f", "female", "woman", "w"):
        return "female"
    return ""


def _resolve_marriage_pair(
    m: dict, hc: List[dict]
) -> Optional[Tuple[dict, dict, str, str]]:
    """Return (mother, father, mother_name, father_name) from a marriage row."""
    if m.get("mother") and m.get("father"):
        mname = str(m["mother"]).strip()
        fname = str(m["father"]).strip()
        mo = _find_char_by_name(hc, mname)
        fa = _find_char_by_name(hc, fname)
        if mo and fa:
            return mo, fa, mname, fname
    a = (m.get("partner_a") or m.get("a") or "").strip()
    b = (m.get("partner_b") or m.get("b") or "").strip()
    if not a or not b:
        return None
    ca = _find_char_by_name(hc, a)
    cb = _find_char_by_name(hc, b)
    if not ca or not cb:
        return None
    sa, sb = _sex(ca), _sex(cb)
    if sa == "female" and sb == "male":
        return ca, cb, a, b
    if sa == "male" and sb == "female":
        return cb, ca, b, a
    return None


def _sibling_count(hc: List[dict], m_name: str, f_name: str) -> int:
    n = 0
    for ch in hc:
        par = ch.get("parents")
        if not isinstance(par, (list, tuple)) or len(par) < 2:
            continue
        if {str(par[0]), str(par[1])} == {m_name, f_name}:
            n += 1
    return n


def _avg_faction_stability(faction: str, state: dict) -> float:
    vals: List[int] = []
    for loc in state.get("locations", []) or []:
        if loc.get("controller") == faction:
            vals.append(int(loc.get("stability", 50) or 50))
    if not vals:
        return 55.0
    return float(sum(vals)) / max(1, len(vals))


def _stability_modifier(stab: float) -> float:
    return 0.45 + 0.55 * (stab / 100.0)


def _inherit_int(a: int, b: int, var: int) -> int:
    base = (int(a) + int(b)) // 2
    return int(_clampf(base + random.randint(-var, var), 0, 100))


def _inherit_f(a: float, b: float, var: int) -> float:
    base = (float(a) + float(b)) / 2.0
    return _clampf(base + random.uniform(-var, var), 0, 100)


def _clampf(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _primary_bias(mo: dict, fa: dict) -> str:
    pool = [str(mo.get("bias", "defensive") or "defensive"), str(fa.get("bias", "defensive") or "defensive")]
    if random.random() < 0.5:
        return pool[0]
    return pool[1] if len(pool) > 1 else "defensive"


def _trait_pool(p: dict) -> List[str]:
    raw = p.get("traits")
    if isinstance(raw, (list, tuple)) and raw:
        return [str(x).strip() for x in raw if str(x).strip()]
    b = (p.get("bias") or "").strip()
    return [b] if b else []


def _traits_from_parents(mo: dict, fa: dict, cfg: dict) -> List[str]:
    out: List[str] = []
    inherit_chance = float(cfg.get("trait_inherit_chance", 0.45) or 0.45)
    for p in (mo, fa):
        pool = _trait_pool(p)
        if pool and random.random() < inherit_chance:
            out.append(random.choice(pool))
    if random.random() < float(cfg.get("random_extra_trait_chance", 0.08) or 0.08):
        out.append(
            random.choice(
                ["inquisitive", "quiet", "bold", "pious", "skeptical", "tenacious", "mercurial"]
            )
        )
    seen: set[str] = set()
    dedup: List[str] = []
    for t in out:
        if t and t not in seen:
            seen.add(t)
            dedup.append(t)
    if not dedup:
        for p in (mo, fa):
            pool = _trait_pool(p)
            if pool:
                dedup.append(pool[0])
                break
    if not dedup:
        dedup = [str(mo.get("bias", "defensive") or "defensive")]
    return dedup[:6]


def _make_child(
    mother: dict,
    father: dict,
    m_name: str,
    f_name: str,
    state: dict,
    cfg: dict,
) -> dict:
    house = (father.get("house") or mother.get("house") or "House Line").strip()  # father default
    faction = (mother.get("faction") or father.get("faction") or "").strip()
    race = mother.get("race") or father.get("race") or "Human"
    name = _pick_name(house, str(race))
    var = int(cfg.get("stat_variance", 8) or 8)
    w = {
        "name": name,
        "faction": faction,
        "house": house,
        "coreRole": "Minor",
        "role": "Child of the line",
        "status": "alive",
        "age": 0.0,
        "birth_tick": int(state.get("tick", 0) or 0),
        "sex": random.choice(["male", "female"]),
        "race": race,
        "influenceScore": _inherit_int(
            int(mother.get("influenceScore", 20) or 20),
            int(father.get("influenceScore", 20) or 20),
            var,
        ),
        "morality": _inherit_f(
            float(mother.get("morality", 50) or 50),
            float(father.get("morality", 50) or 50),
            var,
        ),
        "ambition": _inherit_f(
            float(mother.get("ambition", 50) or 50),
            float(father.get("ambition", 50) or 50),
            var,
        ),
        "loyalty": _inherit_f(
            float(mother.get("loyalty", 50) or 50),
            float(father.get("loyalty", 50) or 50),
            var,
        ),
        "intelligence": _inherit_f(
            float(mother.get("intelligence", 50) or 50),
            float(father.get("intelligence", 50) or 50),
            var,
        ),
        "bias": _primary_bias(mother, father),
        "currentGoal": "",
        "recentActions": [],
        "location": (mother.get("location") or father.get("location") or faction) or "",
        "destination": "",
        "ticks_to_arrive": 0,
        "journey_purpose": "",
        "warfare": _inherit_int(
            int(mother.get("warfare", 40) or 40), int(father.get("warfare", 40) or 40), var
        ),
        "diplomacy": _inherit_int(
            int(mother.get("diplomacy", 40) or 40),
            int(father.get("diplomacy", 40) or 40),
            var,
        ),
        "intrigue": _inherit_int(
            int(mother.get("intrigue", 40) or 40),
            int(father.get("intrigue", 40) or 40),
            var,
        ),
        "faith": _inherit_int(
            int(mother.get("faith", 20) or 20), int(father.get("faith", 20) or 20), var
        ),
        "health": 100.0,
        "wounds": [],
        "memory": [],
        "relationships": {},
        "parents": [m_name, f_name],
        "traits": _traits_from_parents(mother, father, cfg),
    }
    w["influenceScore"] = max(1, min(100, w["influenceScore"]))
    return w


def _record_birth_cause(state: dict, event: dict) -> None:
    child = event.get("child") or {}
    parents = [str(p).strip() for p in event.get("parents", []) if str(p).strip()]
    if not isinstance(child, dict) or not child:
        return
    child_name = str(child.get("name") or "Unnamed child").strip()
    faction = str(child.get("faction") or "Noble Houses").strip()
    house = str(child.get("house") or "").strip()
    role = str(child.get("coreRole") or "Minor").strip()
    severity = 8 if role in {"Heir", "Leader"} else 5

    record_cause(
        state,
        domain="dynasty",
        actor=faction,
        pressure=(
            f"dynastic continuity pressure; house={house}; parents={', '.join(parents)}; "
            f"child_role={role}; inherited_traits={child.get('traits', [])}"
        ),
        belief="birth extends the ruling line and alters future succession pressure",
        decision="record_dynastic_birth",
        outcome=f"{child_name} is born to {', '.join(parents) or 'unknown parents'}, extending {house or faction}.",
        affected=[item for item in [faction, house, child_name, *parents] if item],
        severity=severity,
        confidence=0.9,
        source="birth_system",
    )


def run_birth_system(state: dict) -> None:
    t = int(state.get("tick", 0) or 0)
    if state.get("_birth_system_tick") == t:
        return
    state["_birth_system_tick"] = t

    random.seed(t * 10007 + len(state.get("house_characters") or []) * 13 + 17)

    bc = state.get("birth_config")
    cfg: Dict[str, Any] = {**DEFAULT_BIRTH_CONFIG, **(bc if isinstance(bc, dict) else {})}
    fmin, fmax = int(cfg.get("female_age_min", 16)), int(cfg.get("female_age_max", 45))
    mmin = int(cfg.get("male_age_min", 16))
    base = float(cfg.get("base_chance", 0.15) or 0.15)
    max_b = int(cfg.get("max_births_per_tick", 2) or 2)

    state.setdefault("character_marriages", [])
    state.setdefault("house_characters", [])
    if not isinstance(state.get("house_characters"), list):
        state["house_characters"] = []

    hc: List[dict] = list(state.get("house_characters") or [])
    events: List[dict] = []
    birthed = 0

    for m in list(state.get("character_marriages", []) or []):
        if birthed >= max_b:
            break
        if not isinstance(m, dict):
            continue
        r = _resolve_marriage_pair(m, hc)
        if not r:
            continue
        mother, father, m_name, f_name = r
        if not _is_alive(mother) or not _is_alive(father):
            continue
        a_m, a_f = _age(mother), _age(father)
        if not (fmin <= a_m <= fmax and a_f >= mmin):
            continue
        m_h = float(mother.get("health", 70) or 70)
        f_h = float(father.get("health", 70) or 70)
        fac = (mother.get("faction") or father.get("faction") or "").strip()
        stab = _avg_faction_stability(fac, state) if fac else 55.0
        sm = _stability_modifier(stab)
        n_ch = _sibling_count(hc, m_name, f_name)
        sib_pen = float(cfg.get("sibling_count_penalty", 0.12) or 0.12)
        child_div = 1.0 + sib_pen * n_ch
        p = base * (m_h / 100.0) * (f_h / 100.0) * sm * (1.0 / child_div)
        p = min(float(cfg.get("max_birth_roll", 0.55) or 0.55), max(0.0, p))
        if random.random() > p:
            continue

        child = _make_child(mother, father, m_name, f_name, state, cfg)
        hc.append(child)
        birthed += 1
        events.append(
            {
                "event": "birth",
                "child": child,
                "parents": [m_name, f_name],
            }
        )

    state["house_characters"] = hc
    state["birth_events"] = events
    for event in events:
        _record_birth_cause(state, event)
    for h in reversed(state.get("tick_history", []) or []):
        if h.get("tick") == t:
            h["birth_events"] = events
            break
