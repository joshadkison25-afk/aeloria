"""Shared pressure scoring for Axiom actors.

Pressure is an explanatory layer, not an outcome layer. It translates existing
world-state signals into comparable faction stress scores so decisions,
causality, knowledge, and future AI reports can speak the same language.
"""

from __future__ import annotations

from typing import Any

PRESSURE_DOMAINS = (
    "economic",
    "military",
    "stability",
    "diplomatic",
    "legitimacy",
    "knowledge",
)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _faction_names(world_state: dict[str, Any]) -> list[str]:
    names = set()
    for row in world_state.get("faction_power_state", []) or []:
        if isinstance(row, dict) and row.get("faction"):
            names.add(str(row["faction"]))
    for row in world_state.get("relationships", []) or []:
        if isinstance(row, dict):
            for key in ("faction_a", "faction_b"):
                if row.get(key):
                    names.add(str(row[key]))
    for row in world_state.get("locations", []) or []:
        if isinstance(row, dict) and row.get("controller"):
            names.add(str(row["controller"]))
    return sorted(names)


def _power(world_state: dict[str, Any], faction: str) -> dict[str, Any]:
    for row in world_state.get("faction_power_state", []) or []:
        if isinstance(row, dict) and row.get("faction") == faction:
            return row
    return {}


def _economy(world_state: dict[str, Any], faction: str) -> dict[str, Any]:
    for row in world_state.get("faction_economy", []) or []:
        if isinstance(row, dict) and (row.get("faction") == faction or row.get("faction_id") == faction):
            return row
    return {}


def _legacy_resources(world_state: dict[str, Any], faction: str) -> dict[str, Any]:
    for row in world_state.get("faction_resources", []) or []:
        if isinstance(row, dict) and row.get("faction") == faction:
            return row
    return {}


def _resource_shortage_score(world_state: dict[str, Any], faction: str) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0

    econ = _economy(world_state, faction)
    resources = econ.get("resources", {}) if isinstance(econ.get("resources"), dict) else {}
    for name, data in resources.items():
        if not isinstance(data, dict):
            continue
        stockpile = float(data.get("stockpile", 0) or 0)
        capacity = float(data.get("storage_capacity", 0) or 0)
        if capacity <= 0:
            continue
        ratio = stockpile / capacity
        if ratio < 0.20:
            score += (0.20 - ratio) * 180
            reasons.append(f"{name} reserves low")

    shortage_effects = econ.get("shortage_effects", {}) if isinstance(econ.get("shortage_effects"), dict) else {}
    for name, data in shortage_effects.items():
        if not isinstance(data, dict):
            continue
        severity = float(data.get("severity", 0) or 0)
        if severity <= 0:
            continue
        score += severity * 45
        label = "food" if name == "grain" else str(name)
        if severity >= 0.25:
            reasons.append(f"{label} shortage acute")

    legacy = _legacy_resources(world_state, faction)
    for name in ("food", "materials"):
        if name in legacy:
            value = float(legacy.get(name, 50) or 0)
            if value < 40:
                score += (40 - value) * 0.7
                reasons.append(f"{name} below safe level")

    return _clamp(score), reasons[:4]


def _relationships(world_state: dict[str, Any], faction: str) -> list[dict[str, Any]]:
    rows = []
    for row in world_state.get("relationships", []) or []:
        if not isinstance(row, dict):
            continue
        if faction in (row.get("faction_a"), row.get("faction_b")):
            rows.append(row)
    return rows


def _locations(world_state: dict[str, Any], faction: str) -> list[dict[str, Any]]:
    return [
        row for row in world_state.get("locations", []) or []
        if isinstance(row, dict) and row.get("controller") == faction
    ]


def _knowledge_row(world_state: dict[str, Any], faction: str) -> dict[str, Any]:
    from engine.knowledge import get_faction_knowledge

    return get_faction_knowledge(world_state, faction)


def compute_faction_pressure(world_state: dict[str, Any], faction: str) -> dict[str, Any]:
    """Compute pressure scores and dominant reasons for one faction."""
    power = _power(world_state, faction)
    rels = _relationships(world_state, faction)
    locs = _locations(world_state, faction)
    knowledge = _knowledge_row(world_state, faction)

    economic, economic_reasons = _resource_shortage_score(world_state, faction)
    economic_power = float(power.get("economicPower", 50) or 50)
    if economic_power < 45:
        economic += (45 - economic_power) * 1.2
        economic_reasons.append("economic power weakening")

    wars = [row for row in rels if row.get("type") == "war"]
    military = len(wars) * 18.0
    military_reasons = [f"at war with {row.get('faction_b') if row.get('faction_a') == faction else row.get('faction_a')}" for row in wars[:3]]
    military_power = float(power.get("militaryPower", 50) or 50)
    if military_power < 45:
        military += (45 - military_power) * 1.1
        military_reasons.append("military power weakening")

    low_control = []
    for loc in locs:
        stability = float(loc.get("stability", loc.get("control", 50)) or 50)
        control = float(loc.get("control", stability) or stability)
        if min(stability, control) < 45:
            low_control.append(str(loc.get("name") or loc.get("id") or "unknown location"))
    stability_score = min(100.0, len(low_control) * 17.0)
    stability_reasons = [f"weak control in {name}" for name in low_control[:3]]

    hostile = [row for row in rels if float(row.get("hostility", 0) or 0) > 60]
    diplomatic = min(100.0, len(hostile) * 14.0)
    diplomatic_reasons = [
        f"hostility with {row.get('faction_b') if row.get('faction_a') == faction else row.get('faction_a')}"
        for row in hostile[:3]
    ]

    political = float(power.get("politicalInfluence", 50) or 50)
    legitimacy = max(0.0, (45 - political) * 1.4)
    legitimacy_reasons = ["political influence weakening"] if political < 45 else []
    for row in world_state.get("ruler_states", []) or []:
        if isinstance(row, dict) and row.get("faction") == faction:
            pressure = float(row.get("pressure_level", 0) or 0)
            if pressure > 60:
                legitimacy += (pressure - 60) * 0.8
                legitimacy_reasons.append("ruler pressure rising")

    knowledge_score = min(
        100.0,
        len(knowledge.get("rumors", []) or []) * 6.0
        + len(knowledge.get("suspicions", []) or []) * 9.0
        + len(knowledge.get("false_beliefs", []) or []) * 12.0,
    )
    knowledge_reasons = []
    if knowledge.get("suspicions"):
        knowledge_reasons.append("active suspicions")
    if knowledge.get("rumors"):
        knowledge_reasons.append("rumor pressure")
    if knowledge.get("false_beliefs"):
        knowledge_reasons.append("false beliefs shaping judgment")

    domains = {
        "economic": {"score": round(_clamp(economic), 1), "reasons": economic_reasons[:4]},
        "military": {"score": round(_clamp(military), 1), "reasons": military_reasons[:4]},
        "stability": {"score": round(_clamp(stability_score), 1), "reasons": stability_reasons[:4]},
        "diplomatic": {"score": round(_clamp(diplomatic), 1), "reasons": diplomatic_reasons[:4]},
        "legitimacy": {"score": round(_clamp(legitimacy), 1), "reasons": legitimacy_reasons[:4]},
        "knowledge": {"score": round(_clamp(knowledge_score), 1), "reasons": knowledge_reasons[:4]},
    }

    from engine.memory import memory_pressure_delta
    for pdomain, delta in memory_pressure_delta(world_state, faction).items():
        if pdomain in domains:
            domains[pdomain]["score"] = round(_clamp(domains[pdomain]["score"] + delta), 1)
            reasons = domains[pdomain]["reasons"]
            if delta > 2.0 and "historical wounds" not in reasons:
                reasons.append("historical wounds")

    dominant = max(domains.items(), key=lambda item: item[1]["score"])
    overall = sum(value["score"] for value in domains.values()) / len(PRESSURE_DOMAINS)
    return {
        "faction": faction,
        "overall": round(_clamp(overall), 1),
        "dominant_pressure": dominant[0],
        "domains": domains,
        "summary": pressure_summary({"domains": domains, "dominant_pressure": dominant[0]}),
    }


def pressure_summary(report: dict[str, Any]) -> str:
    domains = report.get("domains", {})
    dominant = report.get("dominant_pressure") or "economic"
    row = domains.get(dominant, {}) if isinstance(domains, dict) else {}
    reasons = row.get("reasons") or []
    if reasons:
        return f"{dominant} pressure: {', '.join(reasons[:2])}"
    return f"{dominant} pressure"


def compute_pressure_report(world_state: dict[str, Any], factions: list[str] | None = None) -> list[dict[str, Any]]:
    names = factions or _faction_names(world_state)
    report = [compute_faction_pressure(world_state, faction) for faction in names]
    return sorted(report, key=lambda row: row.get("overall", 0), reverse=True)
