"""
Family structures → political effects: large-house alliances & friction, heir crowding,
no-heir weakness, rival siblings, and marriage-webs for indirect faction ties.

State:
  family_politics  — { by_faction: [...], summary: { family_size, heir_count, risk_level },
                      marriage_web: { edges, indirect_pairs } }
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any, DefaultDict, Dict, List, Optional, Set, Tuple

__all__ = ["run_family_politics", "DEFAULT_FAMILY_POLITICS_CONFIG"]

DEFAULT_FAMILY_POLITICS_CONFIG = {
    "large_family_at": 6,
    "many_heirs_at": 3,
    "alliance_trust_bump": 1,
    "alliance_bumps_per_tick": 2,
    "internal_stability_dip": 1,
    "succession_risk_per_extra_heir": 7.0,
    "no_heir_legitimacy_drop": 2.6,
    "no_heir_external_claim_strength": 24.0,
    "rival_sibling_tension_severity": 5,
    "web_legitimacy_bonus_per_edge": 0.15,
    "web_max_legitimacy_bonus": 1.2,
    "max_risk": 100,
}


def _nk(s: str) -> str:
    return (s or "").strip().lower()


def _alive(c: dict) -> bool:
    st = str(c.get("status", "alive") or "alive").lower()
    if st.startswith("deceased") or st in ("dead", "killed", "slain"):
        return False
    return True


def _house_match(a: str, b: str) -> bool:
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return False
    return a == b or a in b or b in a or a.split()[-1] == b.split()[-1]


def _ruling_house(lead: dict) -> str:
    from marriage_succession import _ruling_house as rh
    return rh(lead) or ""


def _parent_fset(c: dict) -> frozenset:
    p = c.get("parents")
    if not isinstance(p, (list, tuple)):
        return frozenset()
    return frozenset(_nk(x) for x in p if str(x).strip())


def _family_members(state: dict, faction: str, house: str) -> List[dict]:
    if not house:
        return []
    out: List[dict] = []
    for c in state.get("house_characters") or []:
        if not isinstance(c, dict) or not _alive(c):
            continue
        if (c.get("faction") or "").strip() != faction:
            continue
        if not _house_match(c.get("house", "") or "", house):
            continue
        out.append(c)
    return out


def _count_rival_sibling_pairs(members: List[dict], cfg: dict) -> int:
    """Rival = shared parent(s), power-relevant or low mutual trust in relationships."""
    n = len(members)
    pairs = 0
    for i in range(n):
        a = members[i]
        for j in range(i + 1, n):
            b = members[j]
            if not (_parent_fset(a) & _parent_fset(b)):
                continue
            cr_a = (a.get("coreRole") or "").strip()
            cr_b = (b.get("coreRole") or "").strip()
            power_roles = {"Heir", "Leader", "Power Role"}
            heir_pair = (cr_a in power_roles) and (cr_b in power_roles)
            amb = float(a.get("ambition", 50) or 50) + float(b.get("ambition", 50) or 50)
            ra = a.get("relationships") or {}
            rb = b.get("relationships") or {}
            na, nb = (a.get("name") or ""), (b.get("name") or "")
            low_trust = False
            if isinstance(ra, dict) and isinstance(rb, dict) and na and nb:
                t1 = (ra.get(nb) or {}).get("trust", 50)
                t2 = (rb.get(na) or {}).get("trust", 50)
                if isinstance(t1, (int, float)) and isinstance(t2, (int, float)):
                    low_trust = min(t1, t2) < 42
            if heir_pair or amb > 130 or low_trust:
                pairs += 1
    return pairs


def _apply_large_family(
    state: dict, faction: str, family_size: int, rh: str, cfg: dict, tick: int
) -> None:
    th = int(cfg.get("large_family_at", 6) or 6)
    if family_size < th:
        return
    rels = [r for r in (state.get("relationships") or []) if isinstance(r, dict)]
    nudge = 0
    for r in rels:
        a, b = (r.get("faction_a") or ""), (r.get("faction_b") or "")
        if faction not in (a, b):
            continue
        other = b if a == faction else a
        if not other:
            continue
        if str(r.get("type", "neutral")) == "war":
            continue
        t = int(r.get("trust", 50) or 50)
        r["trust"] = int(
            max(0, min(100, t + int(cfg.get("alliance_trust_bump", 1) or 1)))
        )
        nudge += 1
        if nudge >= int(cfg.get("alliance_bumps_per_tick", 2) or 2):
            break
    for loc in state.get("locations") or []:
        if not isinstance(loc, dict) or (loc.get("controller") or "") != faction:
            continue
        if str(loc.get("region_type", "")).lower() in ("capital",) or int(
            loc.get("value", 0) or 0
        ) > 75:
            dip = int(cfg.get("internal_stability_dip", 1) or 1)
            loc["stability"] = int(
                max(0, min(100, int(loc.get("stability", 50) or 50) - dip))
            )
            le = list(state.get("location_events") or [])
            le.append(
                {
                    "tick": tick,
                    "type": "house_internal_strife",
                    "location": loc.get("name", ""),
                    "faction": faction,
                    "summary": f"Large {rh or 'ruling house'}: competing branches and appointments strain order.",
                }
            )
            state["location_events"] = le[-30:]
            break


def _apply_no_heir(
    state: dict, faction: str, house: str, cfg: dict, tick: int, rh: str
) -> None:
    drop = float(cfg.get("no_heir_legitimacy_drop", 2.6) or 2.6)
    dl = state.setdefault("dynastic_legitimacy", {})
    if not isinstance(dl, dict):
        dl = {}
        state["dynastic_legitimacy"] = dl
    prev = float(dl.get(faction, 50) or 50)
    dl[faction] = max(0.0, min(100.0, prev - drop))
    st = float(cfg.get("no_heir_external_claim_strength", 24) or 24)
    dr = state.get("dynastic_report")
    if not isinstance(dr, dict):
        dr = {}
        state["dynastic_report"] = dr
    cl = list(dr.get("claims") or [])
    cl.append(
        {
            "target_faction": faction,
            "ruling_house": rh,
            "claimant": f"External / cadet lines — {house or 'ruling line'}",
            "claimant_house": house,
            "lineage_proximity": 0.35,
            "claim_strength": st,
            "trigger": "no_clear_heir",
            "marriage_id": None,
            "foreign_affines_faction": None,
        }
    )
    dr["claims"] = cl[-40:]


def _apply_many_heir_risk(
    state: dict, faction: str, heir_count: int, cfg: dict
) -> None:
    mh = int(cfg.get("many_heirs_at", 3) or 3)
    if heir_count < mh:
        return
    pr = state.setdefault("heir_succession_risk", {})
    if not isinstance(pr, dict):
        pr = {}
        state["heir_succession_risk"] = pr
    extra = max(0, heir_count - (mh - 1))
    pr[faction] = min(
        100.0,
        8.0 + extra * float(cfg.get("succession_risk_per_extra_heir", 7) or 7),
    )


def _sibling_rival_tensions(
    state: dict,
    faction: str,
    house: str,
    members: List[dict],
    rival_pairs: int,
    cfg: dict,
) -> None:
    if rival_pairs < 1:
        return
    sev = int(cfg.get("rival_sibling_tension_severity", 5) or 5)
    tick = int(state.get("tick", 0) or 0)
    at = list(state.get("active_tensions") or [])
    at.append(
        {
            "name": f"Sibling rivalry — {house or faction}",
            "severity": min(18, sev * rival_pairs + 2),
            "factions": [faction],
            "summary": f"Heirs and power-seekers within {house or 'the ruling house'} clash over precedence.",
            "source": "family_politics",
        }
    )
    state["active_tensions"] = at[:8]


def _build_marriage_web(
    state: dict, cfg: dict
) -> Dict[str, Any]:
    """Faction–faction edges from noble/character marriage; indirect 2-hop pairs."""
    edges: List[dict] = []
    seen: Set[Tuple[str, str]] = set()
    for m in state.get("noble_marriages") or []:
        if not isinstance(m, dict):
            continue
        fa, fb = (m.get("faction_a") or "").strip(), (m.get("faction_b") or "").strip()
        if not fa or not fb or fa == fb:
            continue
        a, b = sorted((fa, fb))
        if (a, b) in seen:
            continue
        seen.add((a, b))
        edges.append(
            {
                "faction_a": fa,
                "faction_b": fb,
                "marriage_id": m.get("marriage_id", ""),
                "houses": [m.get("house_a", ""), m.get("house_b", "")],
            }
        )
    adj: DefaultDict[str, Set[str]] = defaultdict(set)
    for e in edges:
        a, b = e["faction_a"], e["faction_b"]
        if a and b:
            adj[a].add(b)
            adj[b].add(a)
    indirect: List[dict] = []
    done: Set[Tuple[str, str, str]] = set()
    for mid, nbrs in adj.items():
        for a in nbrs:
            for c in adj.get(a, ()):
                if c == mid or c in nbrs:
                    continue
                key = tuple(sorted([mid, c, a]))
                if key in done:
                    continue
                done.add(key)
                indirect.append(
                    {
                        "from_faction": mid,
                        "to_faction": c,
                        "via_faction": a,
                    }
                )
    if edges:
        facs: Set[str] = set()
        for e in edges:
            for f in (e.get("faction_a"), e.get("faction_b")):
                if f:
                    facs.add(str(f))
        per = min(
            float(cfg.get("web_max_legitimacy_bonus", 1.2) or 1.2),
            len(edges) * float(cfg.get("web_legitimacy_bonus_per_edge", 0.15) or 0.15),
        ) / max(1, len(facs))
        dl = state.setdefault("dynastic_legitimacy", {})
        if not isinstance(dl, dict):
            dl = {}
            state["dynastic_legitimacy"] = dl
        for f in facs:
            prev = float(dl.get(f, 50) or 50)
            dl[f] = max(0.0, min(100.0, prev + per))
    return {"edges": edges, "indirect_ties": indirect[:24]}


def _risk_level(
    family_size: int,
    heir_count: int,
    rival_sibling_pairs: int,
    large_at: int,
    many_heir_at: int,
    cap: int,
) -> int:
    r = 8
    if heir_count == 0:
        r += 38
    elif heir_count >= many_heir_at:
        r += min(36, 10 + (heir_count - many_heir_at + 1) * 8)
    if family_size >= large_at:
        r += min(22, 6 + (family_size - large_at) * 3)
    r += min(20, rival_sibling_pairs * 9)
    return int(max(0, min(cap, r)))


def run_family_politics(state: dict) -> None:
    t = int(state.get("tick", 0) or 0)
    if state.get("_family_politics_tick") == t:
        return
    state["_family_politics_tick"] = t

    cfg: Dict[str, Any] = {**DEFAULT_FAMILY_POLITICS_CONFIG}
    mc = state.get("family_politics_config")
    if isinstance(mc, dict):
        cfg.update(mc)

    random.seed(t * 13001 + 7)

    cap = int(cfg.get("max_risk", 100) or 100)
    large_at = int(cfg.get("large_family_at", 6) or 6)
    many_h_at = int(cfg.get("many_heirs_at", 3) or 3)

    by_faction: List[dict] = []
    for lead in state.get("leadership_state") or []:
        if not isinstance(lead, dict):
            continue
        fac = (lead.get("faction") or "").strip()
        if not fac:
            continue
        rh = _ruling_house(lead)
        members = _family_members(state, fac, rh)
        family_size = len(members)
        heir_count = sum(
            1 for c in members if (c.get("coreRole") or "").strip() == "Heir"
        )
        rivals = _count_rival_sibling_pairs(members, cfg)
        risk = _risk_level(family_size, heir_count, rivals, large_at, many_h_at, cap)

        row = {
            "faction": fac,
            "ruling_house": rh,
            "family_size": family_size,
            "heir_count": heir_count,
            "rival_sibling_pairs": rivals,
            "risk_level": risk,
        }
        by_faction.append(row)

        _apply_large_family(state, fac, family_size, rh, cfg, t)
        if heir_count == 0 and family_size > 0:
            _apply_no_heir(state, fac, rh, cfg, t, rh)
        _apply_many_heir_risk(state, fac, heir_count, cfg)
        _sibling_rival_tensions(state, fac, rh, members, rivals, cfg)

    by_faction.sort(key=lambda r: -int(r.get("risk_level", 0) or 0))
    worst = by_faction[0] if by_faction else None
    web = _build_marriage_web(state, cfg)

    state["family_politics"] = {
        "by_faction": by_faction,
        "summary": {
            "family_size": int(worst.get("family_size", 0) or 0) if worst else 0,
            "heir_count": int(worst.get("heir_count", 0) or 0) if worst else 0,
            "risk_level": int(worst.get("risk_level", 0) or 0) if worst else 0,
        },
        "marriage_web": web,
        "tick": t,
    }

    for h in reversed(state.get("tick_history", []) or []):
        if h.get("tick") == t:
            h["family_politics"] = state["family_politics"]
            break

