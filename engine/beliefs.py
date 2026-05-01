"""Actor belief synthesis for the Axiom Engine.

Beliefs are what an actor currently thinks is true. They are derived from
pressure plus faction-specific knowledge, and sit between pressure and
decision-making in the engine pipeline.
"""

from __future__ import annotations

from typing import Any

MAX_BELIEFS_PER_FACTION = 12


def _belief_id(faction: str, index: int) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in faction).strip("_")
    return f"belief_{slug or 'unknown'}_{index:03d}"


def _confidence(base: float, pressure_score: float) -> float:
    return round(max(0.05, min(0.95, base + pressure_score / 250.0)), 2)


def _pressure_beliefs(faction: str, pressure: dict[str, Any]) -> list[dict[str, Any]]:
    beliefs = []
    domains = pressure.get("domains", {}) if isinstance(pressure, dict) else {}
    for domain, row in domains.items():
        score = float((row or {}).get("score", 0) or 0)
        if score < 20:
            continue
        reasons = list((row or {}).get("reasons", []) or [])
        claim = f"{domain} pressure is shaping {faction}'s choices"
        if reasons:
            claim = f"{faction} faces {domain} pressure because {', '.join(reasons[:2])}"
        beliefs.append({
            "subject": faction,
            "claim": claim,
            "confidence": _confidence(0.45, score),
            "source": "pressure",
            "bias": domain,
        })
    return beliefs


def _knowledge_beliefs(faction: str, knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    beliefs = []
    for text in list(knowledge.get("known_facts", []) or [])[:4]:
        beliefs.append({
            "subject": faction,
            "claim": str(text),
            "confidence": 0.9,
            "source": "known_fact",
            "bias": "confirmed",
        })
    for text in list(knowledge.get("suspicions", []) or [])[:4]:
        beliefs.append({
            "subject": faction,
            "claim": str(text),
            "confidence": 0.58,
            "source": "suspicion",
            "bias": "uncertain",
        })
    for text in list(knowledge.get("rumors", []) or [])[:3]:
        beliefs.append({
            "subject": faction,
            "claim": str(text),
            "confidence": 0.35,
            "source": "rumor",
            "bias": "unverified",
        })
    for text in list(knowledge.get("false_beliefs", []) or [])[:2]:
        beliefs.append({
            "subject": faction,
            "claim": str(text),
            "confidence": 0.7,
            "source": "false_belief",
            "bias": "incorrect",
        })
    return beliefs


def _power_score(row: dict[str, Any]) -> float:
    return (
        float(row.get("militaryPower", 50) or 50)
        + float(row.get("economicPower", 50) or 50)
        + float(row.get("politicalInfluence", 50) or 50)
    ) / 3.0


def _legitimacy_beliefs(faction: str, pressure: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate beliefs about ruler weakness when legitimacy pressure is high."""
    domains = pressure.get("domains", {}) if isinstance(pressure, dict) else {}
    leg_score = float((domains.get("legitimacy") or {}).get("score", 0) or 0)
    if leg_score < 30:
        return []
    confidence = _confidence(0.40, leg_score)
    beliefs = [{
        "subject": faction,
        "claim": f"The ruling house of {faction} appears weak — nobles may challenge the throne",
        "confidence": confidence,
        "source": "pressure",
        "bias": "legitimacy",
    }]
    if leg_score >= 55:
        beliefs.append({
            "subject": faction,
            "claim": f"A succession crisis in {faction} is imminent without decisive action",
            "confidence": _confidence(0.55, leg_score),
            "source": "pressure",
            "bias": "legitimacy",
        })
    return beliefs


def _treaty_distrust_beliefs(faction: str, world_state: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate beliefs about unreliable allies from low-trust relationships."""
    beliefs = []
    for row in world_state.get("relationships") or []:
        if not isinstance(row, dict):
            continue
        a, b = row.get("faction_a", ""), row.get("faction_b", "")
        partner = b if a == faction else (a if b == faction else None)
        if not partner:
            continue
        if row.get("type") == "alliance" and float(row.get("trust", 50) or 50) < 35:
            beliefs.append({
                "subject": faction,
                "claim": f"The alliance with {partner} is hollow — trust has eroded dangerously",
                "confidence": _confidence(0.50, 50 - float(row.get("trust", 50) or 50)),
                "source": "pressure",
                "bias": "diplomatic",
            })
    return beliefs[:2]


def _military_collapse_beliefs(faction: str, pressure: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate beliefs about unsustainable fronts when military pressure is high while at war."""
    domains = pressure.get("domains", {}) if isinstance(pressure, dict) else {}
    mil_score = float((domains.get("military") or {}).get("score", 0) or 0)
    reasons = (domains.get("military") or {}).get("reasons", [])
    at_war = any("at war" in str(r).lower() for r in reasons)
    if mil_score < 35 or not at_war:
        return []
    return [{
        "subject": faction,
        "claim": f"{faction}'s military is overextended — holding the front risks total collapse",
        "confidence": _confidence(0.45, mil_score),
        "source": "pressure",
        "bias": "military",
    }]


def _vulnerable_neighbor_beliefs(
    world_state: dict[str, Any],
    faction: str,
    pressure: dict[str, Any],
) -> list[dict[str, Any]]:
    domains = pressure.get("domains", {}) if isinstance(pressure, dict) else {}
    economic = domains.get("economic", {}) if isinstance(domains, dict) else {}
    economic_score = float(economic.get("score", 0) or 0)
    reasons = " ".join(str(item).lower() for item in economic.get("reasons", []) or [])
    if economic_score < 25 or not any(word in reasons for word in ("food", "grain")):
        return []

    rows = [
        row for row in world_state.get("faction_power_state", []) or []
        if isinstance(row, dict) and row.get("faction")
    ]
    own = next((row for row in rows if row.get("faction") == faction), {})
    own_score = _power_score(own) if own else 50.0
    candidates = [
        row for row in rows
        if row.get("faction") != faction and _power_score(row) <= own_score + 20
    ]
    if not candidates:
        return []
    target = min(candidates, key=lambda row: (_power_score(row), str(row.get("faction") or "")))
    target_name = str(target.get("faction") or "").strip()
    if not target_name:
        return []
    return [{
        "subject": target_name,
        "claim": f"{target_name} appears vulnerable to a provisioning raid",
        "confidence": _confidence(0.50, economic_score),
        "source": "pressure",
        "bias": "economic",
    }]


def build_faction_beliefs(
    world_state: dict[str, Any],
    faction: str,
    pressure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one faction's belief state from pressure and knowledge."""
    from engine.knowledge import get_faction_knowledge
    from engine.pressure import compute_faction_pressure

    pressure = pressure or compute_faction_pressure(world_state, faction)
    knowledge = get_faction_knowledge(world_state, faction)
    from engine.memory import memory_beliefs as _memory_beliefs
    beliefs = (
        _pressure_beliefs(faction, pressure)
        + _legitimacy_beliefs(faction, pressure)
        + _military_collapse_beliefs(faction, pressure)
        + _treaty_distrust_beliefs(faction, world_state)
        + _vulnerable_neighbor_beliefs(world_state, faction, pressure)
        + _knowledge_beliefs(faction, knowledge)
        + _memory_beliefs(world_state, faction)
    )
    for idx, belief in enumerate(beliefs[:MAX_BELIEFS_PER_FACTION], start=1):
        belief["id"] = _belief_id(faction, idx)
    return {
        "faction": faction,
        "dominant_pressure": pressure.get("dominant_pressure", ""),
        "overall_pressure": pressure.get("overall", 0),
        "beliefs": beliefs[:MAX_BELIEFS_PER_FACTION],
    }


def update_beliefs(world_state: dict[str, Any]) -> list[dict[str, Any]]:
    """Recompute and store ``faction_beliefs`` for all factions in pressure_report."""
    from engine.pressure import compute_pressure_report

    pressure_report = world_state.get("pressure_report")
    if not isinstance(pressure_report, list) or not pressure_report:
        pressure_report = compute_pressure_report(world_state)
        world_state["pressure_report"] = pressure_report
    rows = [
        build_faction_beliefs(world_state, str(row.get("faction", "")), row)
        for row in pressure_report
        if row.get("faction")
    ]
    world_state["faction_beliefs"] = rows[:80]
    return world_state["faction_beliefs"]


def get_faction_belief_state(world_state: dict[str, Any], faction: str) -> dict[str, Any]:
    """Return precomputed belief state for a faction, or build it on demand."""
    for row in world_state.get("faction_beliefs", []) or []:
        if isinstance(row, dict) and row.get("faction") == faction:
            return row
    return build_faction_beliefs(world_state, faction)


def dominant_belief(world_state: dict[str, Any], faction: str) -> dict[str, Any]:
    """Return the highest-confidence belief for a faction."""
    row = get_faction_belief_state(world_state, faction)
    beliefs = [item for item in row.get("beliefs", []) if isinstance(item, dict)]
    if not beliefs:
        return {}
    return max(
        beliefs,
        key=lambda item: (
            float(item.get("confidence", 0) or 0),
            1 if item.get("source") == "pressure" else 0,
        ),
    )


def belief_summary(belief: dict[str, Any]) -> str:
    if not belief:
        return ""
    claim = str(belief.get("claim") or "").strip()
    source = str(belief.get("source") or "belief").strip()
    confidence = float(belief.get("confidence", 0) or 0)
    if not claim:
        return ""
    return f"{source} ({confidence:.2f}): {claim}"


def decision_bias_from_beliefs(world_state: dict[str, Any], faction: str) -> dict[str, float]:
    """Return small action-score deltas derived from faction beliefs.

    This is intentionally conservative. Beliefs nudge the old decision model;
    they do not override hard viability checks.
    """
    row = get_faction_belief_state(world_state, faction)
    bias = {
        "declare_war": 0.0,
        "form_alliance": 0.0,
        "betray": 0.0,
        "stabilize_territory": 0.0,
        "do_nothing": 0.0,
    }

    dominant_pressure = str(row.get("dominant_pressure") or "").lower()
    if dominant_pressure == "military":
        bias["declare_war"] += 6.0
    elif dominant_pressure == "diplomatic":
        bias["form_alliance"] += 5.0
    elif dominant_pressure in {"economic", "stability", "legitimacy"}:
        bias["stabilize_territory"] += 8.0
    elif dominant_pressure == "knowledge":
        bias["do_nothing"] += 3.0
        bias["betray"] += 2.0

    for belief in row.get("beliefs", []) or []:
        if not isinstance(belief, dict):
            continue
        claim = str(belief.get("claim") or "").lower()
        source = str(belief.get("source") or "").lower()
        belief_bias = str(belief.get("bias") or "").lower()
        confidence = max(0.0, min(1.0, float(belief.get("confidence", 0) or 0)))

        if source in {"suspicion", "false_belief"}:
            bias["declare_war"] += 5.0 * confidence
            bias["betray"] += 3.0 * confidence
        elif source == "rumor":
            bias["do_nothing"] += 3.0 * confidence
        elif source == "known_fact":
            if "alliance" in claim or "treaty" in claim:
                bias["form_alliance"] += 4.0 * confidence
            if "war" in claim or "hostility" in claim or "betray" in claim:
                bias["declare_war"] += 4.0 * confidence

        if belief_bias in {"economic", "stability", "legitimacy"}:
            bias["stabilize_territory"] += 4.0 * confidence
        elif belief_bias == "diplomatic":
            bias["form_alliance"] += 3.0 * confidence
        elif belief_bias == "military":
            bias["declare_war"] += 3.0 * confidence

    return {key: round(value, 2) for key, value in bias.items() if value > 0}


# ---------------------------------------------------------------------------
# Belief current generation — spreading ideological / cultural movements
# ---------------------------------------------------------------------------

_STAGES = ("rumor", "pattern_recognition", "belief", "doctrine", "organization", "institution")
_STAGE_THRESHOLDS = (0, 500, 2_000, 8_000, 25_000, 80_000)

_BIAS_TO_INTERPRETATION: dict[str, str] = {
    "economic":   "The world favours those who control resources.",
    "military":   "Strength is the only true argument.",
    "stability":  "Order above all — chaos destroys from within.",
    "diplomatic": "Bonds between peoples outlast any army.",
    "legitimacy": "The right to rule must be earned and renewed.",
    "knowledge":  "Secrets are power; ignorance is a weapon used against you.",
}


def _stage_for(followers: int) -> str:
    stage = "rumor"
    for idx, threshold in enumerate(_STAGE_THRESHOLDS):
        if followers >= threshold:
            stage = _STAGES[idx]
    return stage


def _faction_population(world_state: dict[str, Any], faction: str) -> int:
    total = 0
    for loc in world_state.get("locations") or []:
        if not isinstance(loc, dict):
            continue
        if loc.get("controller") == faction or loc.get("owner") == faction:
            total += int(loc.get("population", 0) or 0)
    if total == 0:
        for row in world_state.get("population_state") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("region") or "").lower() == faction.lower():
                total += int(row.get("population", 0) or 0)
    return max(total, 1_000)


def _existing_current(currents: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for c in currents:
        if isinstance(c, dict) and c.get("name") == name:
            return c
    return {}


def generate_belief_currents(world_state: dict[str, Any]) -> list[dict[str, Any]]:
    """Promote strong faction beliefs into spreading cultural / ideological currents.

    Each tick:
      1. High-pressure factions with confident dominant beliefs seed new currents.
      2. Existing currents grow or shrink based on faction relationships.
      3. Currents that lose all followers are pruned.

    The result is stored in world_state["belief_currents"] and returned.
    """
    existing: list[dict[str, Any]] = list(world_state.get("belief_currents") or [])
    pressure_report = world_state.get("pressure_report") or []
    faction_beliefs: list[dict[str, Any]] = world_state.get("faction_beliefs") or []

    belief_by_faction: dict[str, dict[str, Any]] = {
        row["faction"]: row for row in faction_beliefs if isinstance(row, dict) and row.get("faction")
    }

    updated: dict[str, dict[str, Any]] = {
        c["name"]: dict(c) for c in existing if isinstance(c, dict) and c.get("name")
    }

    for pressure_row in pressure_report:
        if not isinstance(pressure_row, dict):
            continue
        faction = str(pressure_row.get("faction") or "").strip()
        overall = float(pressure_row.get("overall", 0) or 0)
        if overall < 35:
            continue

        belief_row = belief_by_faction.get(faction, {})
        dominant_pressure = str(pressure_row.get("dominant_pressure") or "").lower()
        if not dominant_pressure:
            continue

        beliefs = belief_row.get("beliefs") or []
        top_confidence = max(
            (float(b.get("confidence", 0) or 0) for b in beliefs if isinstance(b, dict)),
            default=0.0,
        )
        if top_confidence < 0.45:
            continue

        current_name = f"{faction} — {dominant_pressure} doctrine"
        pop = _faction_population(world_state, faction)
        spread_rate = max(0.05, (overall - 30) / 200.0)
        base_followers = int(pop * spread_rate)

        prev = _existing_current(existing, current_name)
        prev_followers = int(prev.get("followers", 0) or 0)
        new_followers = max(base_followers, prev_followers + int(base_followers * 0.15))

        updated[current_name] = {
            "name": current_name,
            "origin": faction,
            "stage": _stage_for(new_followers),
            "regions": [
                loc.get("name", "") for loc in (world_state.get("locations") or [])
                if isinstance(loc, dict)
                and (loc.get("controller") == faction or loc.get("owner") == faction)
            ][:6],
            "followers": new_followers,
            "interpretation": _BIAS_TO_INTERPRETATION.get(dominant_pressure, dominant_pressure),
        }

    # Decay currents whose origin faction has low pressure (the ideology is fading)
    origin_pressure: dict[str, float] = {
        str(r.get("faction") or ""): float(r.get("overall", 0) or 0)
        for r in pressure_report if isinstance(r, dict)
    }
    pruned: list[dict[str, Any]] = []
    for name, current in updated.items():
        origin = str(current.get("origin") or "")
        op = origin_pressure.get(origin, 0.0)
        followers = int(current.get("followers", 0) or 0)
        if op < 15:
            followers = int(followers * 0.85)
        current["followers"] = followers
        current["stage"] = _stage_for(followers)
        if followers > 0:
            pruned.append(current)

    pruned.sort(key=lambda c: c.get("followers", 0), reverse=True)
    world_state["belief_currents"] = pruned[:20]
    return world_state["belief_currents"]
