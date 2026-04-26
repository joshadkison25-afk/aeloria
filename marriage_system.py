"""
Mechanical marriage proposals for noble house characters.

Populates:
  - character_marriages, noble_marriages  (for birth + dynastic succession)
  - spouse fields on both characters
  - faction relationship trust; dynastic_legitimacy nudges
  - peer relationships (high trust / respect) between spouses

State:
  marriage_events  — this tick: [ { event, spouse_a, spouse_b, faction_effects }, ... ]
  Optional hooks:  marriage_config  overrides DEFAULT_MARRIAGE_CONFIG
  Optional:          pending_marriage_pairs = [ { "spouse_a", "spouse_b", "type" } ] — always accepted if valid
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Set, Tuple

__all__ = ["run_marriage_system", "DEFAULT_MARRIAGE_CONFIG"]

DEFAULT_MARRIAGE_CONFIG = {
    "min_age": 16,
    "max_marriages_per_tick": 1,
    "allow_polygamy": False,
    "forbid_same_house": True,
    "forbid_shared_parent": True,
    "pair_score_sample_cap": 400,
    "political_trust_delta": 6,
    "internal_trust_delta": 4,
    "alliance_bump_if_neutral": 3,
    "hostility_dampen": 3,
    "dynastic_legitimacy_bump": 1.4,
    "spouse_trust": 86,
    "spouse_respect": 78,
    "spouse_fear": 6,
    "score_political": 24,
    "score_internal_cross_house": 16,
    "score_internal_same_house": 4,
    "score_both_heir": 20,
    "score_one_heir": 11,
    "score_influence": 0.12,
    "score_existing_trust": 0.22,
    "score_alliance_leaning": 8,
    "score_succession_pressure": 14,
}

def _f(v, d=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _age(ch: dict) -> float:
    return _f(ch.get("age", 0), 0.0)


def _alive(c: dict) -> bool:
    s = str(c.get("status", "alive") or "alive").lower()
    if s.startswith("deceased") or s in ("dead", "killed", "slain"):
        return False
    return True


def _sex(c: dict) -> str:
    t = str(c.get("sex", c.get("gender", "")) or "").lower()
    if t in ("m", "male", "man"):
        return "m"
    if t in ("f", "female", "woman", "w"):
        return "f"
    return ""


def _name_key(n: str) -> str:
    return (n or "").strip().lower()


def _married_names(state: dict) -> Set[str]:
    out: Set[str] = set()
    for m in state.get("character_marriages") or []:
        if not isinstance(m, dict):
            continue
        for k in ("mother", "father", "partner_a", "partner_b", "a", "b"):
            v = (m.get(k) or "").strip()
            if v:
                out.add(_name_key(v))
    return out


def _has_spouse_field(c: dict, married_keys: Set[str]) -> bool:
    sp = (c.get("spouse") or "").strip()
    if sp:
        return True
    n = (c.get("name") or "").strip()
    if n and _name_key(n) in married_keys:
        return True
    return False


def _parents_set(c: dict) -> Set[str]:
    p = c.get("parents")
    if not isinstance(p, (list, tuple)):
        return set()
    return {_name_key(x) for x in p if str(x).strip()}


def _close_relatives(
    a: dict, b: dict, cfg: dict
) -> bool:
    if (a.get("house") or "").strip() and (a.get("house") or "").strip() == (b.get("house") or "").strip():
        if cfg.get("forbid_same_house", True):
            return True
    if cfg.get("forbid_shared_parent", True):
        pa, pb = _parents_set(a), _parents_set(b)
        if pa and pb and (pa & pb):
            return True
    return False


def _merge_rel_entry(dst: dict, trust: int, respect: int, fear: int) -> None:
    e = dict(dst) if isinstance(dst, dict) else {}
    e["trust"] = int(max(0, min(100, int(e.get("trust", 50) or 50) * 0.2 + trust * 0.8)))
    e["respect"] = int(max(0, min(100, int(e.get("respect", 50) or 50) * 0.2 + respect * 0.8)))
    e["fear"] = int(max(0, min(100, fear)))
    return e


def _apply_spouse_bonds(
    a: dict, b: dict, na: str, nb: str, cfg: dict
) -> None:
    ta = int(cfg.get("spouse_trust", 86) or 86)
    rs = int(cfg.get("spouse_respect", 78) or 78)
    fr = int(cfg.get("spouse_fear", 6) or 6)
    ra = a.get("relationships")
    if not isinstance(ra, dict):
        ra = {}
    rb = b.get("relationships")
    if not isinstance(rb, dict):
        rb = {}
    ra[nb] = _merge_rel_entry(ra.get(nb, {}), ta, rs, fr)
    rb[na] = _merge_rel_entry(rb.get(na, {}), ta, rs, fr)
    a["relationships"] = ra
    b["relationships"] = rb
    a["spouse"] = nb
    b["spouse"] = na


def _faction_row(state: dict, fa: str, fb: str) -> Optional[dict]:
    from marriage_succession import _find_rel, _ensure_rel

    r = _find_rel(state, fa, fb)
    if r:
        return r
    if not fa or not fb:
        return None
    return _ensure_rel(state, fa, fb)


def _apply_faction_diplomacy(
    state: dict,
    fa: str,
    fb: str,
    mtype: str,
    cfg: dict,
) -> Dict[str, Any]:
    if not fa or not fb or fa == fb:
        r = {
            "trust_delta": 0,
            "hostility_delta": 0,
            "alliance_delta": 0,
            "note": "internal faction bond only",
        }
        return r
    r = _faction_row(state, fa, fb)
    if not r:
        return {"trust_delta": 0, "hostility_delta": 0, "alliance_delta": 0, "note": "no rel row"}
    t0 = int(r.get("trust", 50) or 50)
    h0 = int(r.get("hostility", 20) or 20)
    a0 = int(r.get("alliance_level", 0) or 0)
    dt = int(
        cfg.get("political_trust_delta" if mtype == "political" else "internal_trust_delta", 6)
    )
    r["trust"] = int(max(0, min(100, t0 + dt)))
    dh = int(cfg.get("hostility_dampen", 3) or 3)
    r["hostility"] = int(max(0, min(100, h0 - dh)))
    ab = int(cfg.get("alliance_bump_if_neutral", 3) or 3)
    if str(r.get("type", "neutral")) != "war" and a0 < 90:
        r["alliance_level"] = int(max(0, min(100, a0 + ab)))
    return {
        "trust_delta": int(r["trust"]) - t0,
        "hostility_delta": int(r["hostility"]) - h0,
        "alliance_delta": int(r.get("alliance_level", 0) or 0) - a0,
        "relationship_type": r.get("type", "neutral"),
    }


def _bump_legitimacy(state: dict, fac: str, amount: float) -> float:
    dl = state.setdefault("dynastic_legitimacy", {})
    if not isinstance(dl, dict):
        dl = {}
        state["dynastic_legitimacy"] = dl
    prev = float(dl.get(fac, 50) or 50)
    nxt = max(0.0, min(100.0, prev + amount))
    dl[fac] = round(nxt, 2)
    return round(nxt - prev, 2)


def _score_pair(
    a: dict, b: dict, state: dict, cfg: dict
) -> float:
    s = 0.0
    fa, fb = (a.get("faction") or "").strip(), (b.get("faction") or "").strip()
    ha, hb = (a.get("house") or "").strip(), (b.get("house") or "").strip()
    if fa and fb and fa != fb:
        s += float(cfg.get("score_political", 24) or 24)
    elif fa == fb and ha and hb and ha != hb:
        s += float(cfg.get("score_internal_cross_house", 16) or 16)
    else:
        s += float(cfg.get("score_internal_same_house", 4) or 4)
    cr_a = (a.get("coreRole") or "").strip()
    cr_b = (b.get("coreRole") or "").strip()
    if cr_a == "Heir" and cr_b == "Heir":
        s += float(cfg.get("score_both_heir", 20) or 20)
    elif "Heir" in (cr_a, cr_b) or "Leader" in (cr_a, cr_b):
        s += float(cfg.get("score_one_heir", 11) or 11)
    s += (float(a.get("influenceScore", 40) or 40) + float(b.get("influenceScore", 40) or 40)) * float(
        cfg.get("score_influence", 0.12) or 0.12
    )
    if fa and fb and fa != fb:
        from marriage_succession import _find_rel

        rr = _find_rel(state, fa, fb)
        if rr:
            s += (float(rr.get("trust", 50) or 50) - 50.0) * float(
                cfg.get("score_existing_trust", 0.22) or 0.22
            )
            if int(rr.get("alliance_level", 0) or 0) > 35 or str(rr.get("type")) == "alliance":
                s += float(cfg.get("score_alliance_leaning", 8) or 8)
    succ_press = False
    for lead in state.get("leadership_state") or []:
        if (lead or {}).get("faction") not in (fa, fb) or not fa:
            continue
        from marriage_succession import _faction_power

        pw = _faction_power(lead, state) or {}
        if float(pw.get("politicalInfluence", 50) or 50) < 48:
            succ_press = True
            break
    if succ_press:
        s += float(cfg.get("score_succession_pressure", 14) or 14)
    return s


def _build_pairs(
    chars: List[dict], state: dict, married: Set[str], cfg: dict
) -> List[Tuple[dict, dict, float]]:
    males = [c for c in chars if _sex(c) == "m" and _alive(c) and _age(c) >= cfg.get("min_age", 16)]
    fem = [c for c in chars if _sex(c) == "f" and _alive(c) and _age(c) >= cfg.get("min_age", 16)]
    if not males or not fem:
        return []
    out: List[Tuple[dict, dict, float]] = []
    cap = int(cfg.get("pair_score_sample_cap", 400) or 400)
    random.shuffle(males)
    random.shuffle(fem)
    males = males[:40]
    fem = fem[:40]
    for a in males:
        for b in fem:
            if (a.get("name") or "") == (b.get("name") or ""):
                continue
            na, nb = (a.get("name") or "").strip(), (b.get("name") or "").strip()
            if not na or not nb:
                continue
            if _name_key(na) in married or _name_key(nb) in married:
                continue
            if _has_spouse_field(a, married) or _has_spouse_field(b, married):
                continue
            if _close_relatives(a, b, cfg):
                continue
            if len(out) >= cap * 2:
                break
            sc = _score_pair(a, b, state, cfg)
            out.append((a, b, sc))
        if len(out) >= cap * 2:
            break
    out.sort(key=lambda t: -t[2])
    return out[:cap]


def _register_marriage(
    state: dict,
    mother: dict,
    father: dict,
    mtype: str,
    cfg: dict,
    tick: int,
) -> Dict[str, Any]:
    from marriage_succession import marriage_id_for

    mname = (mother.get("name") or "").strip()
    fname = (father.get("name") or "").strip()
    ha, hb = (mother.get("house") or "House").strip(), (father.get("house") or "House").strip()
    fa, fb = (mother.get("faction") or "").strip(), (father.get("faction") or "").strip()
    mid = marriage_id_for(ha, hb, tick)
    cm = {
        "mother": mname,
        "father": fname,
        "since_tick": tick,
        "marriage_type": mtype,
        "marriage_id": mid,
    }
    state.setdefault("character_marriages", []).append(cm)
    nmar = {
        "marriage_id": mid,
        "house_a": ha,
        "house_b": hb,
        "start_tick": tick,
        "faction_a": fa,
        "faction_b": fb,
        "children": [],
        "marriage_trust_ticks": 0,
    }
    state.setdefault("noble_marriages", []).append(nmar)
    ufac = [x for x in sorted({fa, fb}, key=str) if x]
    fac_eff: Dict[str, Any] = {
        "type": mtype,
        "factions": ufac,
        "marriage_id": mid,
    }
    if mtype == "political" and fa and fb and fa != fb:
        fe = _apply_faction_diplomacy(state, fa, fb, mtype, cfg)
        fac_eff.update(fe)
    else:
        fac_eff["internal_union"] = True
        if fa and fb and fa == fb and ha and hb and ha != hb:
            fac_eff["house_bridge"] = [ha, hb]
    bum = _f(cfg.get("dynastic_legitimacy_bump", 1.4), 1.4)
    lb: Dict[str, float] = {}
    for fac in {fa, fb}:
        if fac:
            lb[fac] = _bump_legitimacy(state, str(fac), bum)
    fac_eff["dynastic_legitimacy_bump"] = lb
    fac_eff["future_claims"] = "Latent claim paths via inter-house children and succession pressure."
    return fac_eff


def _snapshot(ch: dict) -> dict:
    return {
        "name": ch.get("name"),
        "house": ch.get("house"),
        "faction": ch.get("faction"),
        "age": ch.get("age"),
        "coreRole": ch.get("coreRole"),
    }


def _apply_pending(
    state: dict, cfg: dict, tick: int, married: Set[str]
) -> List[dict]:
    from birth_system import _find_char_by_name  # reuse lookup

    ev: List[dict] = []
    hc = list(state.get("house_characters") or [])
    for row in list(state.get("pending_marriage_pairs") or []):
        if not isinstance(row, dict):
            continue
        na = (row.get("spouse_a") or row.get("a") or row.get("mother") or "").strip()
        nb = (row.get("spouse_b") or row.get("b") or row.get("father") or "").strip()
        a = _find_char_by_name(hc, na)
        b = _find_char_by_name(hc, nb)
        if not a or not b or not _alive(a) or not _alive(b):
            continue
        mtype = (row.get("type") or "").strip().lower()
        if mtype not in ("political", "internal"):
            mtype = (
                "political" if (a.get("faction") or "") != (b.get("faction") or "") else "internal"
            )
        if _sex(a) and _sex(b) and _sex(a) == _sex(b):
            continue
        if _age(a) < cfg.get("min_age", 16) or _age(b) < cfg.get("min_age", 16):
            continue
        if _has_spouse_field(a, married) or _has_spouse_field(b, married):
            continue
        if _close_relatives(a, b, cfg):
            continue
        mother, father = (a, b) if _sex(a) == "f" else (b, a)
        if _sex(mother) != "f" or _sex(father) != "m":
            if _sex(father) == "f" and _sex(mother) == "m":
                mother, father = father, mother
        fac_eff = _register_marriage(state, mother, father, mtype, cfg, tick)
        _apply_spouse_bonds(mother, father, mother.get("name", ""), father.get("name", ""), cfg)
        state["house_characters"] = hc
        ev.append(
            {
                "event": "marriage",
                "spouse_a": _snapshot(mother),
                "spouse_b": _snapshot(father),
                "faction_effects": fac_eff,
            }
        )
    state["pending_marriage_pairs"] = []
    return ev


def run_marriage_system(state: dict) -> None:
    t = int(state.get("tick", 0) or 0)
    if state.get("_marriage_system_tick") == t:
        return
    state["_marriage_system_tick"] = t

    bc = state.get("marriage_config")
    cfg: Dict[str, Any] = {**DEFAULT_MARRIAGE_CONFIG, **(bc if isinstance(bc, dict) else {})}

    random.seed(t * 12007 + 31)

    state.setdefault("house_characters", [])
    if not isinstance(state.get("house_characters"), list):
        state["house_characters"] = []
    if not isinstance(state.get("character_marriages"), list):
        state["character_marriages"] = []
    if not isinstance(state.get("noble_marriages"), list):
        state["noble_marriages"] = []

    events: List[dict] = []
    events.extend(_apply_pending(state, cfg, t, _married_names(state)))
    allowed_more = int(cfg.get("max_marriages_per_tick", 1) or 1) - len(events)
    if allowed_more <= 0:
        state["marriage_events"] = events
        for h in reversed(state.get("tick_history", []) or []):
            if h.get("tick") == t:
                h["marriage_events"] = events
                break
        return

    marriedk = _married_names(state)
    for c in state.get("house_characters") or []:
        n = (c.get("name") or "").strip()
        if n and (c.get("spouse") or "").strip() and not cfg.get("allow_polygamy", False):
            marriedk.add(_name_key(n))

    hc = [c for c in (state.get("house_characters") or []) if isinstance(c, dict)]
    pairs = _build_pairs(hc, state, marriedk, cfg)
    used: Set[str] = set()
    slots = allowed_more
    for a, b, sc in pairs:
        if slots <= 0:
            break
        na, nb = (a.get("name") or "").strip(), (b.get("name") or "").strip()
        if not na or not nb:
            continue
        ka, kb = _name_key(na), _name_key(nb)
        if ka in used or kb in used:
            continue
        mtype: str = (
            "political"
            if (a.get("faction") or "") != (b.get("faction") or "")
            else "internal"
        )
        mother, father = (a, b) if _sex(a) == "f" else (b, a)
        if _sex(mother) != "f" and _sex(father) == "f":
            mother, father = father, mother
        if _sex(father) != "m" or _sex(mother) != "f":
            continue
        fac_eff = _register_marriage(state, mother, father, mtype, cfg, t)
        _apply_spouse_bonds(mother, father, (mother.get("name") or ""), (father.get("name") or ""), cfg)
        used.add(ka)
        used.add(kb)
        slots -= 1
        events.append(
            {
                "event": "marriage",
                "spouse_a": _snapshot(mother),
                "spouse_b": _snapshot(father),
                "faction_effects": fac_eff,
            }
        )

    state["marriage_events"] = events
    for h in reversed(state.get("tick_history", []) or []):
        if h.get("tick") == t:
            h["marriage_events"] = events
            break
