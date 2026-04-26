"""
Faction lifecycle: collapse, civil wars, rebel factions, vassalage, and thrones.

This is a deterministic post-processor. It does not narrate; it records mechanical
state transitions that later UI / narrative layers can read.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Optional, Tuple

__all__ = ["run_faction_lifecycle", "is_faction_collapsed"]


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(v)))


def _tick(state: dict) -> int:
    return int(state.get("tick", 0) or 0)


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(str(p) for p in parts)
    return f"{prefix}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:10]}"


def _as_list(state: dict, key: str) -> list:
    val = state.get(key)
    if isinstance(val, list):
        return val
    state[key] = []
    return state[key]


def _as_dict(state: dict, key: str) -> dict:
    val = state.get(key)
    if isinstance(val, dict):
        return val
    state[key] = {}
    return state[key]


def _collapsed_names(state: dict) -> set[str]:
    names = set()
    for row in state.get("collapsed_factions") or []:
        if isinstance(row, dict) and row.get("faction"):
            names.add(str(row["faction"]))
    return names


def is_faction_collapsed(state: dict, faction: str) -> bool:
    return faction in _collapsed_names(state)


def _faction_names(state: dict) -> List[str]:
    names: List[str] = []

    def add(name: Any) -> None:
        value = str(name or "").strip()
        if value and value not in names and value not in _collapsed_names(state):
            names.append(value)

    fi = state.get("faction_identities")
    if isinstance(fi, dict):
        for name in fi:
            add(name)
    elif isinstance(fi, list):
        for row in fi:
            if isinstance(row, dict):
                add(row.get("faction") or row.get("name"))

    for key in ("faction_power_state", "leadership_state", "faction_morale"):
        for row in state.get(key) or []:
            if isinstance(row, dict):
                add(row.get("faction") or row.get("faction_id"))

    for loc in state.get("locations") or []:
        if isinstance(loc, dict):
            add(loc.get("controller"))

    regions = state.get("regions")
    if isinstance(regions, dict):
        for data in regions.values():
            if isinstance(data, dict):
                add(data.get("controller"))

    return names


def _power_row(state: dict, faction: str) -> dict:
    for row in state.get("faction_power_state") or []:
        if isinstance(row, dict) and row.get("faction") == faction:
            return row
    return {}


def _avg_power(state: dict, faction: str) -> float:
    row = _power_row(state, faction)
    if not row:
        return 50.0
    vals = [
        float(row.get("militaryPower", 50) or 50),
        float(row.get("economicPower", 50) or 50),
        float(row.get("politicalInfluence", 50) or 50),
        float(row.get("religiousInfluence", 50) or 50),
    ]
    return sum(vals) / len(vals)


def _legitimacy(state: dict, faction: str) -> float:
    scores = state.get("ruler_legitimacy_scores") or {}
    if isinstance(scores, dict) and faction in scores:
        return float(scores.get(faction, 50) or 50)
    for row in state.get("legitimacy_report") or []:
        if isinstance(row, dict) and row.get("faction_id") == faction:
            return float(row.get("legitimacy", 50) or 50)
    return 50.0


def _morale_status(state: dict, faction: str) -> str:
    for row in state.get("faction_morale") or []:
        if isinstance(row, dict) and row.get("faction") == faction:
            return str(row.get("status") or "").lower()
    return ""


def _family_risk(state: dict, faction: str) -> float:
    fp = state.get("family_politics") or {}
    for row in fp.get("by_faction") or []:
        if isinstance(row, dict) and row.get("faction") == faction:
            return float(row.get("risk_level", 0) or 0)
    return 0.0


def _region_entries(state: dict) -> List[dict]:
    out: List[dict] = []
    for loc in state.get("locations") or []:
        if isinstance(loc, dict) and loc.get("name"):
            out.append(
                {
                    "kind": "location",
                    "name": loc.get("name"),
                    "controller": loc.get("controller"),
                    "stability": float(loc.get("stability", loc.get("control", 50)) or 50),
                    "rebellion": bool(loc.get("in_rebellion") or loc.get("rebellion_risk")),
                    "contested": bool(loc.get("contested")),
                    "raw": loc,
                }
            )
    regions = state.get("regions")
    if isinstance(regions, dict):
        for name, data in regions.items():
            if not isinstance(data, dict):
                continue
            stability = data.get("stability", "medium")
            stab_num = {"low": 20, "medium": 55, "high": 82}.get(str(stability).lower(), 50)
            out.append(
                {
                    "kind": "region",
                    "name": name,
                    "controller": data.get("controller"),
                    "stability": float(stab_num),
                    "rebellion": bool(data.get("rebellion_risk")),
                    "contested": "contested" in str(data.get("controller", "")).lower(),
                    "raw": data,
                }
            )
    return out


def _controlled_regions(state: dict, faction: str, exact: bool = True) -> List[dict]:
    rows = []
    for entry in _region_entries(state):
        controller = str(entry.get("controller") or "")
        if exact:
            if controller == faction:
                rows.append(entry)
        elif faction and faction.lower() in controller.lower():
            rows.append(entry)
    return rows


def _set_region_controller(state: dict, region_name: str, controller: str) -> None:
    for loc in state.get("locations") or []:
        if isinstance(loc, dict) and loc.get("name") == region_name:
            loc["controller"] = controller
            loc["contested"] = False
    regions = state.get("regions")
    if isinstance(regions, dict) and region_name in regions and isinstance(regions[region_name], dict):
        regions[region_name]["controller"] = controller


def _ensure_faction_identity(
    state: dict,
    name: str,
    parent: str = "",
    kind: str = "Minor Faction",
    description: str = "",
) -> None:
    fi = state.get("faction_identities")
    if isinstance(fi, dict):
        if name not in fi:
            parent_row = fi.get(parent) if isinstance(fi.get(parent), dict) else {}
            fi[name] = {
                "race": parent_row.get("race", "Multi-species") if parent_row else "Multi-species",
                "type": kind,
                "description": description or f"{name} emerged from faction lifecycle pressure.",
                "traits": ["emergent", "unstable"],
                "succession": "contested",
                "origin_faction": parent,
            }
    else:
        rows = fi if isinstance(fi, list) else []
        if not any(isinstance(r, dict) and (r.get("faction") or r.get("name")) == name for r in rows):
            rows.append(
                {
                    "faction": name,
                    "goals": ["survive"],
                    "doctrine": kind,
                    "personality": "emergent",
                    "description": description,
                }
            )
        state["faction_identities"] = rows


def _ensure_power_row(state: dict, name: str, base: int = 28, source_faction: str = "") -> None:
    rows = _as_list(state, "faction_power_state")
    for row in rows:
        if isinstance(row, dict) and row.get("faction") == name:
            return
    source = _power_row(state, source_faction) if source_faction else {}
    if source:
        rows.append(
            {
                "faction": name,
                "militaryPower": max(18, int(source.get("militaryPower", base) or base)),
                "economicPower": max(18, int(source.get("economicPower", max(15, base - 4)) or max(15, base - 4))),
                "politicalInfluence": max(18, int(source.get("politicalInfluence", base) or base)),
                "religiousInfluence": max(10, int(source.get("religiousInfluence", max(10, base - 8)) or max(10, base - 8))),
            }
        )
        return
    rows.append(
        {
            "faction": name,
            "militaryPower": base,
            "economicPower": max(15, base - 4),
            "politicalInfluence": base,
            "religiousInfluence": max(10, base - 8),
        }
    )


def _ensure_leadership_row(
    state: dict,
    name: str,
    title: str = "Interim Council",
    source_faction: str = "",
    cause: str = "emergence",
) -> None:
    rows = _as_list(state, "leadership_state")
    if any(isinstance(r, dict) and r.get("faction") == name for r in rows):
        return
    source_row = None
    for row in rows:
        if isinstance(row, dict) and row.get("faction") == source_faction:
            source_row = row
            break
    if source_row and isinstance(source_row.get("currentRuler"), dict):
        ruler = dict(source_row["currentRuler"])
        ruler["title"] = title
        ruler["causeOfRise"] = cause
        ruler["startDay"] = _tick(state)
        ruler["duration"] = 0
        ruler.setdefault("notableEvents", [])
        ruler["notableEvents"] = list(ruler.get("notableEvents") or []) + [f"Founded {name} on Day {_tick(state)}."]
        rows.append(
            {
                "faction": name,
                "currentRuler": ruler,
                "rulerHistory": [],
                "dynasties": source_row.get("dynasties", []),
            }
        )
        return
    rows.append(
        {
            "faction": name,
            "currentRuler": {
                "name": title,
                "title": title if title != "Interim Council" else "Interim Authority",
                "dynasty": "Unsettled",
                "age": "Unknown",
                "traits": ["provisional"],
                "causeOfRise": cause,
                "causeOfEnd": "",
                "startDay": _tick(state),
                "endDay": None,
                "duration": 0,
                "notableEvents": [],
            },
            "rulerHistory": [],
            "dynasties": [],
        }
    )


def _ensure_relationship(state: dict, a: str, b: str, rel_type: str, hostility: int = 60, trust: int = 25) -> None:
    if not a or not b or a == b:
        return
    rows = _as_list(state, "relationships")
    key = tuple(sorted((a, b)))
    for row in rows:
        if not isinstance(row, dict):
            continue
        if tuple(sorted((row.get("faction_a", ""), row.get("faction_b", "")))) == key:
            row["type"] = rel_type
            row["hostility"] = max(int(row.get("hostility", 0) or 0), hostility)
            row["trust"] = min(int(row.get("trust", 50) or 50), trust)
            return
    rows.append(
        {
            "faction_a": a,
            "faction_b": b,
            "type": rel_type,
            "intensity": 6,
            "trust": trust,
            "hostility": hostility,
            "alliance_level": 0,
        }
    )


def _copy_faction_rows(state: dict, source: str, target: str) -> None:
    copy_specs = {
        "faction_resources": ("faction",),
        "faction_morale": ("faction",),
        "faction_economy": ("faction_id", "faction"),
    }
    for key, faction_keys in copy_specs.items():
        rows = _as_list(state, key)
        if any(isinstance(r, dict) and any(r.get(k) == target for k in faction_keys) for r in rows):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not any(row.get(k) == source for k in faction_keys):
                continue
            new_row = dict(row)
            for fk in faction_keys:
                if new_row.get(fk) == source:
                    new_row[fk] = target
            if key == "faction_morale":
                new_row["reason"] = f"{target} is stabilizing after being proclaimed from {source}."
            rows.append(new_row)
            break


def _found_new_kingdom(
    state: dict,
    old_kingdom: str,
    claimant: str,
    new_title: str,
    original_regions: List[str],
) -> None:
    _ensure_faction_identity(
        state,
        new_title,
        claimant,
        "Kingdom",
        f"{new_title} was founded from territory once tied to {old_kingdom}.",
    )
    _ensure_power_row(state, new_title, 45, source_faction=claimant)
    _ensure_leadership_row(
        state,
        new_title,
        f"Founder of {new_title}",
        source_faction=claimant,
        cause="founded new kingdom",
    )
    _copy_faction_rows(state, claimant, new_title)
    for region in original_regions:
        for entry in _region_entries(state):
            if entry["name"] == region and entry.get("controller") == claimant:
                _set_region_controller(state, region, new_title)
                break
    _ensure_relationship(state, new_title, old_kingdom, "rivalry", hostility=50, trust=18)


def _existing_tributary(state: dict, dom: str, sub: str) -> bool:
    for pact in state.get("tributary_pacts") or []:
        if not isinstance(pact, dict):
            continue
        if pact.get("dominant_faction") == dom and pact.get("subordinate_faction") == sub and pact.get("status", "active") == "active":
            return True
    return False


def _add_vacant_throne(state: dict, faction: str, reason: str, original_regions: Iterable[str]) -> Optional[dict]:
    rows = _as_list(state, "vacant_thrones")
    for row in rows:
        if isinstance(row, dict) and row.get("kingdom") == faction and row.get("status", "vacant") in ("vacant", "contested"):
            return None
    rec = {
        "throne_id": _stable_id("THR", faction, str(_tick(state))),
        "kingdom": faction,
        "status": "vacant",
        "vacated_tick": _tick(state),
        "reason": reason,
        "original_regions": list(dict.fromkeys(original_regions)),
        "claimants": [],
    }
    rows.append(rec)
    return rec


def _active_vacant_for(state: dict, kingdom: str) -> bool:
    for row in state.get("vacant_thrones") or []:
        if isinstance(row, dict) and row.get("kingdom") == kingdom and row.get("status", "vacant") in ("vacant", "contested"):
            return True
    return False


def _record_event(state: dict, report: dict, key: str, row: dict) -> None:
    report.setdefault(key, []).append(row)


def _evaluate_collapse(state: dict, report: dict) -> None:
    collapsed = _as_list(state, "collapsed_factions")
    collapsed_names = _collapsed_names(state)
    for faction in _faction_names(state):
        if faction in collapsed_names:
            continue
        controlled = _controlled_regions(state, faction, exact=True)
        contested = _controlled_regions(state, faction, exact=False)
        avg_power = _avg_power(state, faction)
        leg = _legitimacy(state, faction)
        morale = _morale_status(state, faction)
        no_clear_realm = not controlled and len(contested) <= 1
        collapse_score = 0
        collapse_score += 2 if avg_power < 16 else 1 if avg_power < 24 else 0
        collapse_score += 2 if leg < 15 else 1 if leg < 25 else 0
        collapse_score += 1 if morale in ("critical", "collapsing") else 0
        collapse_score += 2 if no_clear_realm else 0
        if collapse_score < 5:
            continue

        original_regions = [r["name"] for r in controlled or contested]
        rec = {
            "faction": faction,
            "status": "extinct" if no_clear_realm else "collapsed",
            "tick": _tick(state),
            "avg_power": round(avg_power, 2),
            "legitimacy": round(leg, 2),
            "morale": morale or "unknown",
            "territory_count": len(controlled),
            "reason": "power, legitimacy, morale, and territorial control failed together",
            "original_regions": original_regions,
        }
        collapsed.append(rec)
        throne = _add_vacant_throne(state, faction, "collapse", original_regions)
        if throne:
            rec["vacant_throne_id"] = throne["throne_id"]
        _record_event(state, report, "collapsed", rec)


def _evaluate_civil_wars(state: dict, report: dict) -> None:
    civil_wars = _as_list(state, "civil_wars")
    active_parents = {
        row.get("parent_faction")
        for row in civil_wars
        if isinstance(row, dict) and row.get("status", "active") == "active"
    }
    for faction in _faction_names(state):
        if faction in active_parents or _active_vacant_for(state, faction):
            continue
        controlled = _controlled_regions(state, faction, exact=True)
        if len(controlled) < 2:
            continue
        leg = _legitimacy(state, faction)
        risk = _family_risk(state, faction)
        avg_stability = sum(r["stability"] for r in controlled) / max(1, len(controlled))
        if not (leg < 18 or risk >= 70 or (leg < 28 and avg_stability < 34)):
            continue

        split_region = sorted(controlled, key=lambda r: r["stability"])[0]
        splinter = f"{split_region['name']} League"
        _ensure_faction_identity(state, splinter, faction, "Splinter Faction")
        _ensure_power_row(state, splinter, 32)
        _ensure_leadership_row(state, splinter, f"Council of {split_region['name']}")
        _ensure_relationship(state, faction, splinter, "war", hostility=82, trust=8)
        _set_region_controller(state, split_region["name"], splinter)

        original_regions = [r["name"] for r in controlled]
        throne = _add_vacant_throne(state, faction, "civil_war", original_regions)
        rec = {
            "war_id": _stable_id("CVW", faction, splinter, str(_tick(state))),
            "parent_faction": faction,
            "splinter_faction": splinter,
            "status": "active",
            "started_tick": _tick(state),
            "flashpoint_region": split_region["name"],
            "original_regions": original_regions,
            "reason": "legitimacy or family pressure split the realm",
        }
        if throne:
            rec["vacant_throne_id"] = throne["throne_id"]
        civil_wars.append(rec)
        _record_event(state, report, "civil_wars", rec)


def _evaluate_minor_factions(state: dict, prev_state: dict, report: dict) -> None:
    emerging = _as_list(state, "emerging_factions")
    existing_regions = {
        row.get("location") or row.get("region")
        for row in emerging
        if isinstance(row, dict)
    }
    prev_age = {}
    for row in prev_state.get("emerging_factions") or []:
        if isinstance(row, dict):
            key = row.get("location") or row.get("region")
            if key:
                prev_age[key] = int(row.get("ticks_unstable", row.get("ticks_since_emergence", 0)) or 0)

    for entry in _region_entries(state):
        if not entry.get("rebellion"):
            continue
        region = entry["name"]
        occupier = str(entry.get("controller") or "").strip()
        age = prev_age.get(region, 0) + 1
        if region in existing_regions:
            for row in emerging:
                if isinstance(row, dict) and (row.get("location") or row.get("region")) == region:
                    row["ticks_unstable"] = age
            continue
        if age < 2:
            emerging.append(
                {
                    "faction": "",
                    "region": region,
                    "location": region,
                    "origin_faction": occupier,
                    "status": "unrest",
                    "ticks_unstable": age,
                }
            )
            continue

        name = f"{region} Freehold"
        _ensure_faction_identity(state, name, occupier, "Minor Rebel Faction")
        _ensure_power_row(state, name, 24)
        _ensure_leadership_row(state, name, f"{region} Assembly")
        _ensure_relationship(state, name, occupier, "rivalry", hostility=74, trust=12)
        _set_region_controller(state, region, name)
        rec = {
            "faction": name,
            "region": region,
            "location": region,
            "origin_faction": occupier,
            "status": "emerged",
            "tick_emerged": _tick(state),
            "ticks_unstable": age,
            "reason": "occupied territory remained rebellious",
        }
        emerging.append(rec)
        _record_event(state, report, "emerging_factions", rec)


def _evaluate_vassalage(state: dict, report: dict) -> None:
    pacts = _as_list(state, "tributary_pacts")
    for wo in state.get("war_outcomes") or []:
        if not isinstance(wo, dict):
            continue
        attacker = wo.get("attacker")
        defender = wo.get("defender")
        if not attacker or not defender:
            continue
        advantage = float(wo.get("advantage", 0) or 0)
        if advantage >= 24:
            dom, sub = attacker, defender
        elif advantage <= -24:
            dom, sub = defender, attacker
        else:
            continue
        if _existing_tributary(state, dom, sub) or is_faction_collapsed(state, sub):
            continue
        sub_regions = _controlled_regions(state, sub, exact=True)
        if not sub_regions:
            continue
        if _avg_power(state, sub) > 38 and _legitimacy(state, sub) > 32:
            continue
        payment = max(8, min(40, int(_avg_power(state, sub) * 0.65)))
        rec = {
            "tributary_id": _stable_id("TRB", dom, sub, str(_tick(state))),
            "dominant_faction": dom,
            "subordinate_faction": sub,
            "tribute_type": "mixed",
            "payment_per_tick": payment,
            "start_tick": _tick(state),
            "duration": 60,
            "status": "active",
            "origin": "faction_lifecycle",
            "reason": "conquest pressure favored vassalage over extinction",
        }
        pacts.append(rec)
        _ensure_relationship(state, dom, sub, "rivalry", hostility=55, trust=20)
        _record_event(state, report, "vassalage", rec)


def _evaluate_throne_claims(state: dict, report: dict) -> None:
    vacants = _as_list(state, "vacant_thrones")
    reunifications = _as_list(state, "reunification_claims")
    new_kingdoms = _as_list(state, "new_kingdom_claims")
    for throne in vacants:
        if not isinstance(throne, dict) or throne.get("status", "vacant") not in ("vacant", "contested"):
            continue
        original_regions = [r for r in throne.get("original_regions") or [] if r]
        if not original_regions:
            continue
        counts: Dict[str, int] = {}
        for region in original_regions:
            controller = ""
            for entry in _region_entries(state):
                if entry["name"] == region:
                    controller = str(entry.get("controller") or "")
                    break
            if controller and "contested" not in controller.lower():
                counts[controller] = counts.get(controller, 0) + 1
        if not counts:
            throne["status"] = "contested"
            continue
        claimant, held = max(counts.items(), key=lambda item: item[1])
        share = held / max(1, len(original_regions))
        leg = _legitimacy(state, claimant)
        avg_stab = 0.0
        controlled = [r for r in _region_entries(state) if r["name"] in original_regions and r.get("controller") == claimant]
        if controlled:
            avg_stab = sum(r["stability"] for r in controlled) / len(controlled)

        if share >= (2.0 / 3.0) and leg >= 45:
            rec = {
                "claim_id": _stable_id("RUN", throne.get("kingdom", ""), claimant, str(_tick(state))),
                "kingdom": throne.get("kingdom"),
                "claimed_by": claimant,
                "tick": _tick(state),
                "control_share": round(share, 3),
                "legitimacy": round(leg, 2),
                "status": "restored",
            }
            throne["status"] = "restored"
            throne["claimed_by"] = claimant
            throne["claimed_tick"] = _tick(state)
            reunifications.append(rec)
            _record_event(state, report, "reunifications", rec)
        elif share >= 0.50 and leg >= 55 and avg_stab >= 45:
            new_title = f"Kingdom of {claimant}"
            if any(isinstance(r, dict) and r.get("founded_by") == claimant and r.get("old_kingdom") == throne.get("kingdom") for r in new_kingdoms):
                continue
            _found_new_kingdom(
                state,
                str(throne.get("kingdom") or ""),
                claimant,
                new_title,
                original_regions,
            )
            rec = {
                "claim_id": _stable_id("NKG", throne.get("kingdom", ""), claimant, str(_tick(state))),
                "new_kingdom": new_title,
                "founded_by": claimant,
                "old_kingdom": throne.get("kingdom"),
                "tick": _tick(state),
                "control_share": round(share, 3),
                "legitimacy": round(leg, 2),
                "status": "founded",
            }
            new_kingdoms.append(rec)
            _record_event(state, report, "new_kingdoms", rec)
        else:
            throne["status"] = "contested" if len(counts) > 1 else "vacant"
            throne["leading_claimant"] = claimant
            throne["leading_control_share"] = round(share, 3)


def _prune_active_decision_rows(state: dict) -> None:
    collapsed = _collapsed_names(state)
    if not collapsed:
        return
    for key in (
        "faction_power_state",
        "faction_morale",
        "faction_resources",
        "faction_economy",
        "faction_armies",
    ):
        val = state.get(key)
        if isinstance(val, list):
            state[key] = [
                row
                for row in val
                if not isinstance(row, dict)
                or (row.get("faction") or row.get("faction_id") or row.get("controller")) not in collapsed
            ]


def run_faction_lifecycle(state: dict, prev_state: Optional[dict] = None) -> dict:
    """Mutate state with faction lifecycle outcomes and return it."""
    if not isinstance(state, dict):
        return state
    prev_state = prev_state if isinstance(prev_state, dict) else {}
    t = _tick(state)
    if state.get("_faction_lifecycle_tick") == t:
        return state

    for key in (
        "faction_lifecycle_report",
        "collapsed_factions",
        "civil_wars",
        "emerging_factions",
        "tributary_pacts",
        "vacant_thrones",
        "reunification_claims",
        "new_kingdom_claims",
    ):
        if key != "faction_lifecycle_report":
            _as_list(state, key)

    report: Dict[str, Any] = {
        "tick": t,
        "collapsed": [],
        "civil_wars": [],
        "emerging_factions": [],
        "vassalage": [],
        "reunifications": [],
        "new_kingdoms": [],
    }

    _evaluate_collapse(state, report)
    _evaluate_civil_wars(state, report)
    _evaluate_minor_factions(state, prev_state, report)
    _evaluate_vassalage(state, report)
    _evaluate_throne_claims(state, report)
    _prune_active_decision_rows(state)

    state["faction_lifecycle_report"] = report
    state["_faction_lifecycle_tick"] = t
    return state
