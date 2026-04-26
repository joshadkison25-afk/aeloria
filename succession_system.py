"""
Ruler succession: claim priority (children, relatives, claim strength), crises, outcomes.

`resolve_ruler_succession` updates `currentRuler` / `rulerHistory` and returns
{ new_ruler, claimants, conflict_risk, crisis_outcome }.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

__all__ = [
    "resolve_ruler_succession",
    "DEFAULT_SUCCESSION_CONFIG",
    "classify_relationship_to_deceased",
    "compute_claim_strength",
]

DEFAULT_SUCCESSION_CONFIG = {
    "score_direct": 100.0,
    "score_sibling": 62.0,
    "score_house_kin": 48.0,
    "score_distant": 28.0,
    "score_foreign_affinity": 40.0,
    "min_viable_winner": 18.0,
    "contested_gap_threshold": 12.0,
    "strong_gap_threshold": 20.0,
    "weak_heir_max_score": 40.0,
    "legitimacy_bump_strong": 4.0,
    "legitimacy_drop_contested": 4.0,
    "legitimacy_drop_crisis": 10.0,
    "stability_tweak_capital_strong": 1,
    "stability_tweak_capital_weak": -2,
    "max_claimants": 10,
}


def _nk(s: str) -> str:
    return (s or "").strip().lower()


def _parse_age(s: Any) -> float:
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return 30.0


def _alive(c: dict) -> bool:
    st = str(c.get("status", "alive") or "alive").lower()
    if st.startswith("deceased") or st in ("dead", "killed", "slain"):
        return False
    return True


def _parent_keys(c: dict) -> Set[str]:
    p = c.get("parents")
    if not isinstance(p, (list, tuple)):
        return set()
    return {_nk(x) for x in p if str(x).strip()}


def _house_match(a: str, b: str) -> bool:
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return False
    return a == b or a in b or b in a or a.split()[-1] == b.split()[-1]


def classify_relationship_to_deceased(
    c: dict, dead_name: str, dead: dict, dynasty: str
) -> str:
    """direct_child | sibling | house_kin | distant"""
    dn = _nk(dead_name)
    if not dn or not c:
        return "distant"
    if _nk(c.get("name", "")) == dn:
        return "distant"
    p_c = _parent_keys(c)
    if dn in p_c:
        return "direct_child"
    p_d = _parent_keys(dead)
    if p_c & p_d and dn not in p_c:
        return "sibling"
    ch = (c.get("house") or "").strip()
    dh = (dead.get("house") or "").strip() or dynasty
    if ch and dh and _house_match(ch, dh):
        return "house_kin"
    if (c.get("faction") or "") == (dead.get("faction") or ""):
        return "distant"
    return "distant"


def compute_claim_strength(
    tier: str, influence: float, core_role: str, cfg: dict
) -> float:
    m = {
        "direct_child": float(cfg.get("score_direct", 100)),
        "sibling": float(cfg.get("score_sibling", 62)),
        "house_kin": float(cfg.get("score_house_kin", 48)),
        "distant": float(cfg.get("score_distant", 28)),
        "foreign_affinity": float(cfg.get("score_foreign_affinity", 40)),
    }
    base = m.get(tier, float(cfg.get("score_distant", 28)))
    inf = max(0.0, min(100.0, influence)) / 100.0
    role_boost = 1.12 if (core_role or "").strip() == "Heir" else 1.0
    s = base * (0.35 + 0.65 * inf) * role_boost
    return max(0.0, min(100.0, s))


def _find_char(hc: List[dict], name: str) -> Optional[dict]:
    n = (name or "").strip()
    for c in hc:
        if (c or {}).get("name") == n:
            return c
    return None


def _collect_primary_claimants(
    state: dict,
    faction: str,
    dead_name: str,
    dead: dict,
    dynasty: str,
    cfg: dict,
) -> List[dict]:
    out: List[dict] = []
    seen: Set[str] = set()
    for c in state.get("house_characters") or []:
        if not isinstance(c, dict):
            continue
        nm = (c.get("name") or "").strip()
        if not nm or not _alive(c):
            continue
        if _nk(nm) == _nk(dead_name):
            continue
        if (c.get("faction") or "") != faction:
            continue
        tier = classify_relationship_to_deceased(c, dead_name, dead, dynasty)
        inf = float(c.get("influenceScore", 40) or 40)
        cs = compute_claim_strength(tier, inf, str(c.get("coreRole", "") or ""), cfg)
        if _nk(nm) in seen:
            continue
        seen.add(_nk(nm))
        out.append(
            {
                "name": nm,
                "house": c.get("house", ""),
                "claim_tier": tier,
                "claim_strength": round(cs, 1),
                "influence": int(inf),
                "coreRole": c.get("coreRole", ""),
                "foreign": False,
                "character": c,
            }
        )
    out.sort(key=lambda r: -float(r.get("claim_strength", 0) or 0))
    return out[: int(cfg.get("max_claimants", 10) or 10)]


def _foreign_pressured_claimants(
    state: dict,
    home_faction: str,
    dynasty: str,
    cfg: dict,
    existing: List[dict],
) -> List[dict]:
    ext: List[dict] = []
    seen = {_nk(x["name"]) for x in existing}
    hc = list(state.get("house_characters") or [])
    for c in hc:
        if not isinstance(c, dict) or not _alive(c):
            continue
        if (c.get("faction") or "") == home_faction:
            continue
        sp = (c.get("spouse") or "").strip()
        if not sp:
            continue
        spc = _find_char(hc, sp)
        if not spc or (spc.get("faction") or "") != home_faction:
            continue
        if not _house_match(str(c.get("house", "")), dynasty) and not _house_match(
            str(c.get("house", "")), str(spc.get("house", ""))
        ):
            continue
        nm = (c.get("name") or "").strip()
        if not nm or _nk(nm) in seen:
            continue
        seen.add(_nk(nm))
        inf = float(c.get("influenceScore", 40) or 40)
        cs = (
            compute_claim_strength("foreign_affinity", inf, str(c.get("coreRole", "") or ""), cfg)
            * 0.9
        )
        ext.append(
            {
                "name": nm,
                "house": c.get("house", ""),
                "claim_tier": "foreign_affinity",
                "claim_strength": round(max(5.0, cs), 1),
                "influence": int(inf),
                "coreRole": c.get("coreRole", ""),
                "foreign": True,
                "affined_faction": spc.get("faction"),
                "character": c,
            }
        )
    return sorted(ext, key=lambda r: -float(r.get("claim_strength", 0) or 0))[:3]


def _outcome(
    ranked: List[dict], cfg: dict
) -> Tuple[str, float, bool]:
    """(crisis_outcome, conflict_risk, install_crowned_heir)"""
    if not ranked:
        return "succession_crisis", 88.0, False
    top = float(ranked[0].get("claim_strength", 0) or 0)
    second = float(ranked[1].get("claim_strength", 0) or 0) if len(ranked) > 1 else 0.0
    gap = top - second
    weak = top < float(cfg.get("weak_heir_max_score", 40) or 40)
    cg = float(cfg.get("contested_gap_threshold", 12) or 12)
    sg = float(cfg.get("strong_gap_threshold", 20) or 20)

    if top < float(cfg.get("min_viable_winner", 18) or 18):
        return "succession_crisis", 90.0, False

    has_foreign = any(r.get("foreign") for r in ranked[:3])

    if gap > sg and not weak and top >= 40:
        risk = min(100.0, 14.0 + max(0.0, 12.0 - gap * 0.2))
        return "peaceful_transfer", risk, True

    if gap < cg and second > 30:
        if has_foreign:
            rsk = min(100.0, 58.0 + max(0.0, (cg - gap)) * 1.2)
            return "foreign_intervention", rsk, True
        rsk = min(100.0, 52.0 + max(0.0, (cg - gap)) * 1.4)
        return "contested_claim", rsk, True

    if weak:
        return "contested_claim", min(100.0, 48.0 + (40.0 - top)), True

    return "peaceful_transfer", min(100.0, 20.0 + max(0.0, 25.0 - gap)), True


def _legitimacy_from_succession(
    state: dict,
    faction: str,
    winner: Optional[dict],
    crisis: str,
    cfg: dict,
) -> None:
    rs = state.setdefault("ruler_legitimacy_scores", {})
    base = float(rs.get(faction, 50) or 50)
    t = int(state.get("tick", 0) or 0)
    bump = 0.0
    if winner and crisis == "peaceful_transfer":
        if str(winner.get("claim_tier", "")) == "direct_child":
            bump = float(cfg.get("legitimacy_bump_strong", 4) or 4)
        elif float(winner.get("claim_strength", 0) or 0) >= 50:
            bump = float(cfg.get("legitimacy_bump_strong", 4) or 4) * 0.55
    elif crisis == "contested_claim":
        bump = -float(cfg.get("legitimacy_drop_contested", 4) or 4)
    elif crisis == "foreign_intervention":
        bump = -float(cfg.get("legitimacy_drop_contested", 4) or 4) * 0.85
    elif crisis == "succession_crisis":
        bump = -float(cfg.get("legitimacy_drop_crisis", 10) or 10)
    elif crisis == "peaceful_transfer" and winner and float(
        winner.get("claim_strength", 0) or 0
    ) < 35:
        bump = -2.0

    rs[faction] = max(0.0, min(100.0, base + bump))
    sev = 3 if crisis == "peaceful_transfer" else 6 if crisis == "contested_claim" else 8
    le = state.setdefault("legitimacy_events", [])
    le.append(
        {
            "tick": t,
            "faction": faction,
            "event_type": "succession_legitimacy",
            "severity": sev,
            "crisis": crisis,
        }
    )
    state["legitimacy_events"] = le[-24:]


def _stability_tweak(state: dict, faction: str, strong: bool, cfg: dict) -> None:
    d = int(
        cfg.get("stability_tweak_capital_strong" if strong else "stability_tweak_capital_weak", 0)
    )
    for loc in state.get("locations") or []:
        if not isinstance(loc, dict) or (loc.get("controller") or "") != faction:
            continue
        if str(loc.get("region_type", "")).lower() in ("capital",) or int(
            loc.get("value", 0) or 0
        ) > 80:
            loc["stability"] = int(max(0, min(100, int(loc.get("stability", 50) or 50) + d)))
            return


def _ruler_from_winner(
    cur: dict, winner: dict, dead_name: str, co_end: str, tick: int, wdate: str
) -> dict:
    c = winner.get("character") or {}
    traits: List = []
    if isinstance(c.get("traits"), list):
        traits = c.get("traits")[:6]
    elif isinstance(cur.get("traits"), list):
        traits = (cur.get("traits") or [])[:6]
    if not traits:
        traits = ["ascendant"]
    return {
        "name": (winner.get("name") or c.get("name") or "Unknown").strip(),
        "title": cur.get("title", "Ruler"),
        "dynasty": (c.get("house") or cur.get("dynasty") or "").strip() or cur.get("dynasty", ""),
        "age": str(int(_parse_age(c.get("age", 30)))),
        "startDay": tick,
        "endDay": None,
        "duration": 0,
        "causeOfRise": "inheritance" if winner.get("claim_tier") == "direct_child" else "succession",
        "causeOfEnd": "",
        "traits": list(traits),
        "notableEvents": [
            f"Succeeded {dead_name} ({winner.get('claim_tier', 'heir')}, strength {winner.get('claim_strength', 0)})."
        ],
        "portrait_image": (c.get("portrait_image") or "") or "",
    }


def _regency_ruler(cur: dict, fac: str, dead_name: str, tick: int, wdate: str) -> dict:
    return {
        "name": f"Regency — {fac}",
        "title": (cur.get("title") or "Ruler"),
        "dynasty": (cur.get("dynasty") or "").strip() or "Unknown",
        "age": "?",
        "startDay": tick,
        "endDay": None,
        "duration": 0,
        "causeOfRise": "succession crisis",
        "causeOfEnd": "",
        "traits": ["uncertain", "provisional"],
        "notableEvents": [f"Interregnum after the death of {dead_name} — no clear heir."],
        "portrait_image": "",
    }


def _strip_for_json(rows: List[dict]) -> List[dict]:
    out = []
    for r in rows:
        d = {k: v for k, v in r.items() if k != "character"}
        out.append(d)
    return out


def resolve_ruler_succession(
    state: dict,
    lead: dict,
    cur: dict,
    dead: dict,
    dead_name: str,
    co_end: str,
    wdate: str,
    tick: int,
) -> Dict[str, Any]:
    """
    Mutates `lead` (currentRuler, rulerHistory, dynasties). Returns the public output dict.
    """
    scfg = state.get("succession_config")
    cfg: Dict[str, Any] = {**DEFAULT_SUCCESSION_CONFIG, **(scfg if isinstance(scfg, dict) else {})}
    fac = (lead.get("faction") or "").strip()
    dynasty = (cur.get("dynasty") or dead.get("house") or "").strip()

    primary = _collect_primary_claimants(state, fac, dead_name, dead, dynasty, cfg)
    extra = _foreign_pressured_claimants(state, fac, dynasty, cfg, primary)
    merged = primary + [x for x in extra if _nk(x["name"]) not in {_nk(p["name"]) for p in primary}]
    merged.sort(key=lambda r: -float(r.get("claim_strength", 0) or 0))
    ranked_full = merged[: int(cfg.get("max_claimants", 10) or 10)]

    crisis, risk, can_install = _outcome(ranked_full, cfg)

    leg_winner: Optional[dict] = None
    if can_install and ranked_full:
        win_row = ranked_full[0]
        new_ruler = _ruler_from_winner(cur, win_row, dead_name, co_end, tick, wdate)
        lead["currentRuler"] = new_ruler
        leg_winner = {k: v for k, v in win_row.items() if k != "character"}
    else:
        new_ruler = _regency_ruler(cur, fac, dead_name, tick, wdate)
        lead["currentRuler"] = new_ruler
        if not ranked_full or not can_install:
            crisis = "succession_crisis"
            risk = max(risk, 78.0)
        leg_winner = None

    try:
        sdi = int(cur.get("startDay", 0) or 0)
    except (TypeError, ValueError):
        sdi = 0
    closed = {**cur, "endDay": wdate, "duration": max(1, tick - sdi), "causeOfEnd": co_end}
    hist = list(lead.get("rulerHistory") or [])
    hist.append(closed)
    lead["rulerHistory"] = hist[-32:]

    _legitimacy_from_succession(state, fac, leg_winner, crisis, cfg)

    strong = bool(
        new_ruler
        and (new_ruler.get("name") or "").strip()
        and not str(new_ruler.get("name", "")).startswith("Regency")
    )
    _stability_tweak(state, fac, strong, cfg)

    for d in lead.get("dynasties") or []:
        if (
            isinstance(d, dict)
            and (d.get("name") or "") == dynasty
            and isinstance(d.get("members"), list)
        ):
            mems = [x for x in d["members"] if str(x) != dead_name]
            new_nm = (lead.get("currentRuler") or {}).get("name", "")
            if new_nm:
                mems = (mems + [new_nm])[-24:]
            d["members"] = mems

    claimants_out = _strip_for_json(ranked_full)
    if new_ruler and not str(new_ruler.get("name", "")).startswith("Regency"):
        nr = {
            "name": new_ruler.get("name"),
            "title": new_ruler.get("title"),
            "dynasty": new_ruler.get("dynasty"),
            "age": new_ruler.get("age"),
            "causeOfRise": new_ruler.get("causeOfRise"),
            "claim_tier": (ranked_full[0].get("claim_tier") if ranked_full else None),
        }
    else:
        nr = {
            "name": new_ruler.get("name") if new_ruler else None,
            "title": (new_ruler or {}).get("title"),
            "dynasty": (new_ruler or {}).get("dynasty"),
            "age": (new_ruler or {}).get("age"),
            "causeOfRise": (new_ruler or {}).get("causeOfRise"),
            "claim_tier": None,
        }

    return {
        "new_ruler": nr,
        "claimants": claimants_out,
        "conflict_risk": round(risk, 1),
        "crisis_outcome": crisis,
    }
