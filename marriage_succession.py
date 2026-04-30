"""
Marriage alliances and succession claims between noble houses.

Persistent state:
  noble_marriages — { marriage_id, house_a, house_b, start_tick, children?[], ... }
  dynastic_legitimacy — optional per-faction legitimacy bonus from lineage (0–100 scale contribution)

Per-tick report `dynastic_report`:
  { "marriages": [], "claims": [], "potential_conflicts": [] }
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from engine.causality import record_cause

__all__ = [
    "run_marriage_succession_tick",
    "bump_marriage_trust",
    "marriage_id_for",
]


def _pair_key(a: str, b: str) -> Tuple[str, str]:
    return tuple(sorted((a.strip(), b.strip())))  # type: ignore[return-value]


def _find_rel(state: dict, a: str, b: str) -> Optional[dict]:
    key = _pair_key(a, b)
    for row in state.get("relationships") or []:
        if not isinstance(row, dict):
            continue
        ra, rb = (row.get("faction_a") or ""), (row.get("faction_b") or "")
        if _pair_key(ra, rb) == key:
            return row
    return None


def _ensure_rel(state: dict, a: str, b: str) -> dict:
    r = _find_rel(state, a, b)
    if r:
        return r
    row = {
        "faction_a": a,
        "faction_b": b,
        "type": "neutral",
        "intensity": 50,
        "trust": 50,
        "hostility": 20,
        "alliance_level": 0,
    }
    state.setdefault("relationships", []).append(row)
    return row


def _clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


def marriage_id_for(house_a: str, house_b: str, start_tick: int) -> str:
    s = f"{start_tick}|{_pair_key(house_a, house_b)}"
    h = hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"M-{h}"


def _house_factions(state: dict) -> Dict[str, str]:
    """Map 'House X' / 'Clan Y' string -> primary faction id."""
    m: Dict[str, str] = {}
    for ch in state.get("house_characters") or []:
        if not isinstance(ch, dict):
            continue
        h = (ch.get("house") or "").strip()
        f = (ch.get("faction") or "").strip()
        if h and f and h not in m:
            m[h] = f
    return m


def _normalize_marriage_row(
    state: dict, row: dict, tick: int, house_map: Dict[str, str]
) -> dict:
    ha = (row.get("house_a") or row.get("houseA") or "").strip()
    hb = (row.get("house_b") or row.get("houseB") or "").strip()
    if not ha or not hb:
        return {}
    st = row.get("start_tick")
    if st is None:
        st = tick
    start_tick = int(st)
    mid = (row.get("marriage_id") or "").strip() or marriage_id_for(ha, hb, start_tick)
    fa = (row.get("faction_a") or house_map.get(ha) or "").strip()
    fb = (row.get("faction_b") or house_map.get(hb) or "").strip()
    children = row.get("children")
    if not isinstance(children, list):
        children = []
    trust_ticks = int(row.get("marriage_trust_ticks", 0) or 0)
    return {
        "marriage_id": mid,
        "house_a": ha,
        "house_b": hb,
        "start_tick": start_tick,
        "faction_a": fa,
        "faction_b": fb,
        "children": children,
        "marriage_trust_ticks": trust_ticks,
    }


def bump_marriage_trust(
    state: dict, fa: str, fb: str, bonus_applied: int, max_extra: int = 10
) -> Tuple[int, int]:
    """Apply +1 trust for active marriage, up to `max_extra` over baseline. Returns (new_bonus, trust_delta)."""
    if not fa or not fb or fa == fb:
        return bonus_applied, 0
    r = _ensure_rel(state, fa, fb)
    before = int(r.get("trust", 50) or 50)
    if bonus_applied >= max_extra:
        return bonus_applied, 0
    r["trust"] = int(_clamp(before + 1))
    if int(r.get("hostility", 20) or 20) > 25:
        r["hostility"] = max(0, int(r.get("hostility", 20) or 20) - 1)
    return bonus_applied + 1, 1


def _ruling_house(lead: dict) -> str:
    cr = (lead.get("currentRuler") or {}) if isinstance(lead, dict) else {}
    d = (cr.get("dynasty") or "").strip()
    if d and not d.lower().startswith("house "):
        return f"House {d}" if " " not in d else d
    if d:
        return d
    for dyn in lead.get("dynasties") or []:
        if not isinstance(dyn, dict):
            continue
        if str(dyn.get("status", "active")).lower() == "active":
            n = (dyn.get("name") or "").strip()
            if n:
                return n if n.startswith("House ") or n.startswith("Clan ") else f"House {n}"
    return ""


def _dynasty_prestige(lead: dict, name_fragment: str) -> float:
    if not name_fragment:
        return 50.0
    frag = name_fragment.replace("House ", "").replace("Clan ", "").lower()
    for dyn in lead.get("dynasties") or []:
        if not isinstance(dyn, dict):
            continue
        n = (dyn.get("name") or "").lower()
        if frag in n or n in frag:
            return float(dyn.get("prestige", 50) or 50)
    return 50.0


def _faction_power(lead: dict, state: dict) -> Optional[dict]:
    fac = (lead.get("faction") or "").strip()
    for p in state.get("faction_power_state") or []:
        if p.get("faction") == fac:
            return p
    return None


def _military_of(faction: str, state: dict) -> int:
    for p in state.get("faction_power_state") or []:
        if p.get("faction") == faction:
            return int(p.get("militaryPower", 50) or 50)
    return 50


def _is_collapsing(faction: str, state: dict) -> bool:
    fd = state.get("faction_dominance") or {}
    for row in fd.get("collapsingFactions") or []:
        if not isinstance(row, dict):
            continue
        if (row.get("faction") or row.get("name")) == faction:
            return True
    return False


def _houses_overlap(a: str, b: str) -> bool:
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _lineage_proximity(claimant_house: str, ruling_house: str, child_houses: List[str]) -> float:
    """1.0 = same house, ~0.85 spouse house in union, 0.5 else."""
    ch = (claimant_house or "").strip()
    rh = (ruling_house or "").strip()
    if ch and rh and ch == rh:
        return 1.0
    if ch and rh and (ch in child_houses or rh in child_houses):
        return 0.85
    if ch and rh and (ch.lower() in rh.lower() or rh.lower() in ch.lower()):
        return 0.75
    return 0.45


def _merge_dynastic_history(state: dict) -> None:
    out = state.get("dynastic_report") or {}
    t = int(state.get("tick", 0) or 0)
    for h in reversed(state.get("tick_history") or []):
        if h.get("tick") == t:
            h["dynastic_report"] = out
            break


def _record_dynastic_claim_causes(
    state: dict,
    claims: List[dict],
    potential_conflicts: List[dict],
) -> None:
    """Record major claim pressure without changing claim resolution."""
    for claim in claims[:3]:
        if not isinstance(claim, dict):
            continue
        strength = float(claim.get("claim_strength", 0) or 0)
        trigger = str(claim.get("trigger") or "")
        if strength < 35 and trigger not in {"succession_pressure", "no_clear_heir"}:
            continue
        target = str(claim.get("target_faction") or "")
        claimant = str(claim.get("claimant") or "Unknown claimant")
        claimant_house = str(claim.get("claimant_house") or "")
        ruling_house = str(claim.get("ruling_house") or "")
        foreign = str(claim.get("foreign_affines_faction") or "")
        severity = 7
        if strength >= 55:
            severity = 10
        if trigger == "succession_pressure":
            severity = max(severity, 11)
        if foreign:
            severity = max(severity, 12)

        record_cause(
            state,
            domain="dynasty",
            actor=target or claimant_house or "Dynastic Order",
            pressure=(
                f"succession claim pressure; target={target}; claimant={claimant}; "
                f"claimant_house={claimant_house}; ruling_house={ruling_house}; "
                f"claim_strength={round(strength, 1)}; trigger={trigger}; "
                f"foreign_affines={foreign or 'none'}"
            ),
            belief="lineage proximity, prestige, and faction weakness shape who is seen as a lawful claimant",
            decision="assert_dynastic_claim",
            outcome=f"{claimant} gains a {round(strength, 1)} strength claim on {target}.",
            affected=[item for item in [target, claimant, claimant_house, ruling_house, foreign] if item],
            severity=severity,
            confidence=0.87,
            source="marriage_succession",
        )

    for conflict in potential_conflicts[:2]:
        if not isinstance(conflict, dict):
            continue
        instability = float(conflict.get("instability", 0) or 0)
        if instability < 35:
            continue
        target = str(conflict.get("target_faction") or "")
        outcome_type = str(conflict.get("outcome_type") or "succession_pressure")
        severity = 11 if outcome_type == "contested_succession" else 9
        if outcome_type == "foreign_intervention":
            severity = 13
        record_cause(
            state,
            domain="dynasty",
            actor=target or "Dynastic Order",
            pressure=(
                f"dynastic conflict pressure; target={target}; outcome_type={outcome_type}; "
                f"claim_count={conflict.get('claim_count', 0)}; instability={round(instability, 1)}; "
                f"top_claim_strength={conflict.get('top_claim_strength', 0)}; "
                f"second_claim_strength={conflict.get('second_claim_strength', None)}"
            ),
            belief="multiple credible heirs create succession instability",
            decision="flag_dynastic_conflict",
            outcome=f"{target} faces {outcome_type.replace('_', ' ')} risk from competing claims.",
            affected=[target],
            severity=severity,
            confidence=0.84,
            source="marriage_succession",
        )


def run_marriage_succession_tick(state: dict) -> None:
    """
    Enrich dynastic data, apply marriage trust, evaluate succession pressure.
    Fills `dynastic_report` = { marriages, claims, potential_conflicts }.
    """
    tick = int(state.get("tick", 0) or 0)
    if state.get("_marriage_succession_tick") == tick:
        return
    state["_marriage_succession_tick"] = tick

    state.setdefault("noble_marriages", [])
    state.setdefault("dynastic_legitimacy", {})
    if not isinstance(state.get("dynastic_legitimacy"), dict):
        state["dynastic_legitimacy"] = {}

    house_map = _house_factions(state)
    normalized: List[dict] = []
    for raw in list(state.get("noble_marriages") or []):
        if not isinstance(raw, dict):
            continue
        n = _normalize_marriage_row(state, raw, tick, house_map)
        if n:
            # merge back extra keys from author
            for k, v in raw.items():
                if k not in n and k not in ("houseA", "houseB"):
                    n[k] = v
            normalized.append(n)
    state["noble_marriages"] = normalized

    marriage_rows: List[dict] = []
    for m in normalized:
        st = m["start_tick"]
        age_ticks = max(0, tick - st)
        fa, fb = m.get("faction_a") or "", m.get("faction_b") or ""
        mt = int(m.get("marriage_trust_ticks", 0) or 0)
        if fa and fb:
            nbonus, _ = bump_marriage_trust(state, fa, fb, mt, max_extra=10)
            m["marriage_trust_ticks"] = nbonus
        dyn_tie = min(1.0, 0.15 + min(age_ticks, 500) * 0.0015)
        if m.get("children"):
            dyn_tie = min(1.0, dyn_tie + 0.05 * len(m["children"]))
        row = {
            "marriage_id": m["marriage_id"],
            "house_a": m["house_a"],
            "house_b": m["house_b"],
            "start_tick": m["start_tick"],
            "faction_a": fa,
            "faction_b": fb,
            "age_ticks": age_ticks,
            "dynastic_tie_strength": round(dyn_tie, 3),
            "children": m.get("children") or [],
        }
        marriage_rows.append(row)

    # Legitimacy from lineage (0–100, higher = stronger public acceptance)
    lineage_weight: Dict[str, float] = {}
    for mm in marriage_rows:
        tstr = float(mm.get("dynastic_tie_strength", 0) or 0)
        nch = len(mm.get("children") or [])
        w = tstr * 2.0 + nch * 0.4
        for fac in (mm.get("faction_a"), mm.get("faction_b")):
            if not fac:
                continue
            lineage_weight[fac] = lineage_weight.get(fac, 0.0) + w
    for fac, w in lineage_weight.items():
        prev = float((state.get("dynastic_legitimacy") or {}).get(fac, 50) or 50)
        blended = _clamp(prev * 0.92 + min(20.0, w) * 0.4)
        state["dynastic_legitimacy"][fac] = round(blended)

    # Claims: children with ties to the ruling house (any overlap with houses in union)
    claims_out: List[dict] = []
    for lead in state.get("leadership_state") or []:
        if not isinstance(lead, dict):
            continue
        faction = (lead.get("faction") or "").strip()
        if not faction:
            continue
        rh = _ruling_house(lead)
        pw = _faction_power(lead, state) or {}
        pol = float(pw.get("politicalInfluence", 50) or 50)
        prestige = _dynasty_prestige(lead, rh)
        pressure = pol < 38 or _is_collapsing(faction, state) or prestige < 32

        for m in normalized:
            ha, hb = m.get("house_a") or "", m.get("house_b") or ""
            for ch in m.get("children") or []:
                if not isinstance(ch, dict):
                    continue
                name = (ch.get("name") or "Heir").strip()
                ph = (ch.get("primary_house") or ch.get("house") or "").strip()
                inherited = ch.get("inherited_houses")
                if not isinstance(inherited, list) or not inherited:
                    inherited = [ha, hb]
                pool = [str(x) for x in inherited if x] + [ha, hb, ph]
                if rh and not any(_houses_overlap(rh, x) for x in pool):
                    continue
                proximity = _lineage_proximity(ph, rh, [str(x) for x in inherited if x])
                leg = float(lineage_weight.get(faction, 0) or 0)
                base = 100.0 * proximity * (0.45 + 0.55 * (prestige / 100.0))
                base *= 0.75 + 0.25 * min(1.0, leg / 12.0)
                inf = float(ch.get("influenceScore", 45) or 45) / 100.0
                strength = _clamp(base * (0.5 + 0.5 * inf), 0, 100)
                if not pressure and strength < 25:
                    continue
                foreign = m.get("faction_b") if m.get("faction_a") == faction else m.get("faction_a")
                claims_out.append(
                    {
                        "target_faction": faction,
                        "ruling_house": rh,
                        "claimant": name,
                        "claimant_house": ph or rh,
                        "lineage_proximity": round(proximity, 2),
                        "claim_strength": round(strength, 1),
                        "trigger": "succession_pressure" if pressure else "latent",
                        "marriage_id": m.get("marriage_id"),
                        "foreign_affines_faction": foreign if foreign and foreign != faction else None,
                    }
                )

    # Deduplicate claims by (target, claimant)
    seen: Set[Tuple[str, str]] = set()
    deduped: List[dict] = []
    for c in claims_out:
        k = (c.get("target_faction", ""), c.get("claimant", ""))
        if k in seen:
            continue
        seen.add(k)
        deduped.append(c)
    claims_out = sorted(deduped, key=lambda x: -float(x.get("claim_strength", 0) or 0))[:32]

    by_faction: Dict[str, List[dict]] = defaultdict(list)
    for c in claims_out:
        by_faction[str(c.get("target_faction", ""))].append(c)

    potential: List[dict] = []
    for t_fac, clist in by_faction.items():
        if not t_fac or not clist:
            continue
        clist = sorted(clist, key=lambda x: -float(x.get("claim_strength", 0) or 0))
        top, second = clist[0], clist[1] if len(clist) > 1 else None
        s1 = float(top.get("claim_strength", 0) or 0)
        s2 = float(second.get("claim_strength", 0) or 0) if second else 0.0
        n_claims = len(clist)
        has_strong_affin = any(
            (c.get("foreign_affines_faction") or "")
            and _military_of(str(c.get("foreign_affines_faction")), state) >= 52
            for c in clist
        )
        out_type = "peaceful_union"
        if n_claims >= 2:
            if s1 > s2 + 24:
                out_type = "peaceful_union"
            elif abs(s1 - s2) < 20 and s1 > 32:
                out_type = "contested_succession"
            elif s1 > 38 and s2 > 34 and abs(s1 - s2) < 16:
                out_type = "contested_succession"
        if out_type == "contested_succession" and has_strong_affin:
            out_type = "foreign_intervention"

        instab = _clamp(12.0 + n_claims * 14.0 + max(0, 30.0 - abs(s1 - s2)) * 0.6, 0, 100)
        if n_claims == 1:
            instab = _clamp(4.0 + s1 * 0.12, 0, 100)

        potential.append(
            {
                "target_faction": t_fac,
                "outcome_type": out_type,
                "claim_count": n_claims,
                "top_claim_strength": round(s1, 1),
                "second_claim_strength": round(s2, 1) if second else None,
                "instability": round(instab, 1),
            }
        )

    potential = sorted(potential, key=lambda x: -float(x.get("instability", 0) or 0))[:16]
    state["dynastic_report"] = {
        "marriages": marriage_rows,
        "claims": claims_out,
        "potential_conflicts": potential,
    }
    _record_dynastic_claim_causes(state, claims_out, potential)
    _merge_dynastic_history(state)
