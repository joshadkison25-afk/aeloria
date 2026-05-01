"""World seeding for the Axiom Engine.

Generates initial relationships and faction identities when the world
has none — called automatically on the first tick if relationships is
empty.  Completely data-driven: no Aeloria-specific names are hardcoded.

Pipeline slot: before pressure, so factions react to relationships on
the very first tick that seeding runs.

  world load → seed_world_if_needed() → pressure → belief → decision …
"""

from __future__ import annotations

import hashlib
import random
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stable_rng(a: str, b: str, salt: str = "") -> random.Random:
    """Return a seeded RNG unique to the pair (a, b) — order-independent."""
    key = "|".join(sorted([a, b])) + salt
    seed = int(hashlib.md5(key.encode()).hexdigest(), 16) % (2**31)
    return random.Random(seed)


def _faction_names(world: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for row in world.get("faction_power_state") or []:
        if isinstance(row, dict) and row.get("faction"):
            names.append(str(row["faction"]))
    return names


def _power(world: dict[str, Any], faction: str) -> dict[str, float]:
    for row in world.get("faction_power_state") or []:
        if isinstance(row, dict) and row.get("faction") == faction:
            return {
                "mil": float(row.get("militaryPower", 50) or 50),
                "eco": float(row.get("economicPower", 50) or 50),
                "pol": float(row.get("politicalInfluence", 50) or 50),
                "rel": float(row.get("religiousInfluence", 50) or 50),
            }
    return {"mil": 50, "eco": 50, "pol": 50, "rel": 50}


def _adjacent_faction_pairs(world: dict[str, Any]) -> set[frozenset]:
    """Return all faction pairs that share a border (adjacent locations)."""
    loc_controller: dict[str, str] = {}
    loc_adjacent: dict[str, list[str]] = {}

    for loc in world.get("locations") or []:
        if not isinstance(loc, dict):
            continue
        name = str(loc.get("name") or loc.get("id") or "").strip()
        controller = str(loc.get("controller") or loc.get("owner") or "").strip()
        adjacent = [str(a) for a in (loc.get("adjacent") or []) if a]
        if name and controller:
            loc_controller[name] = controller
            loc_adjacent[name] = adjacent

    pairs: set[frozenset] = set()
    for loc_name, controller in loc_controller.items():
        for adj_name in loc_adjacent.get(loc_name, []):
            adj_controller = loc_controller.get(adj_name, "")
            if adj_controller and adj_controller != controller:
                pairs.add(frozenset([controller, adj_controller]))

    return pairs


def _tension_pairs(world: dict[str, Any]) -> dict[frozenset, int]:
    """Return {pair: max_severity} from active_tensions."""
    result: dict[frozenset, int] = {}
    for t in world.get("active_tensions") or []:
        if not isinstance(t, dict):
            continue
        parties = t.get("parties") or []
        if len(parties) >= 2:
            key = frozenset([str(parties[0]), str(parties[1])])
            sev = int(t.get("severity", 3) or 3)
            result[key] = max(result.get(key, 0), sev)
    return result


# ---------------------------------------------------------------------------
# Relationship seeding
# ---------------------------------------------------------------------------

_REL_ID_COUNTER = 0


def _rel_id() -> str:
    global _REL_ID_COUNTER
    _REL_ID_COUNTER += 1
    return f"rel_{_REL_ID_COUNTER:05d}"


def _seed_relationships(world: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate an initial relationship matrix from adjacency and tensions."""
    factions = _faction_names(world)
    if len(factions) < 2:
        return []

    adjacent_pairs = _adjacent_faction_pairs(world)
    tension_pairs = _tension_pairs(world)
    all_pairs = {frozenset([a, b]) for i, a in enumerate(factions) for b in factions[i + 1:]}

    relationships: list[dict[str, Any]] = []

    for pair in all_pairs:
        pair_list = sorted(pair)
        a, b = pair_list[0], pair_list[1]
        rng = _stable_rng(a, b, "rel_seed")

        is_adjacent = pair in adjacent_pairs
        tension_sev = tension_pairs.get(pair, 0)

        pa = _power(world, a)
        pb = _power(world, b)
        mil_gap = abs(pa["mil"] - pb["mil"])
        eco_gap = abs(pa["eco"] - pb["eco"])

        if is_adjacent:
            base_hostility = rng.uniform(25, 55)
            base_trust = rng.uniform(10, 45)
        else:
            base_hostility = rng.uniform(5, 30)
            base_trust = rng.uniform(15, 50)

        # Tension boosts hostility significantly
        if tension_sev >= 6:
            base_hostility += rng.uniform(25, 40)
            base_trust -= rng.uniform(15, 25)
        elif tension_sev >= 4:
            base_hostility += rng.uniform(10, 20)
            base_trust -= rng.uniform(5, 15)

        # Power gaps create resentment
        base_hostility += mil_gap * 0.15
        base_trust -= eco_gap * 0.1

        # Religious factions start more trustworthy to similar-power neighbors
        rel_a = pa["rel"]
        rel_b = pb["rel"]
        if rel_a > 60 and rel_b > 60:
            base_trust += rng.uniform(5, 15)

        hostility = max(0, min(100, round(base_hostility)))
        trust = max(0, min(100, round(base_trust)))

        # Relationship type
        if hostility >= 70 and is_adjacent:
            rel_type = "hostile"
        elif trust >= 60:
            rel_type = "neutral"
        else:
            rel_type = "neutral"

        relationships.append({
            "id": _rel_id(),
            "faction_a": a,
            "faction_b": b,
            "type": rel_type,
            "hostility": hostility,
            "trust": trust,
            "war_ticks": 0,
        })

    return relationships


# ---------------------------------------------------------------------------
# Faction identity / goals seeding
# ---------------------------------------------------------------------------

_GOAL_PROFILES = [
    {"primary_goal": "expansion",        "doctrine": "Strength through conquest",      "personality": "aggressive"},
    {"primary_goal": "trade_dominance",  "doctrine": "Wealth is power",                "personality": "mercantile"},
    {"primary_goal": "survival",         "doctrine": "Hold what is ours",              "personality": "defensive"},
    {"primary_goal": "political_control","doctrine": "Influence over brute force",     "personality": "diplomatic"},
    {"primary_goal": "religious_spread", "doctrine": "Convert or be forgotten",        "personality": "zealous"},
    {"primary_goal": "intelligence",     "doctrine": "Know everything before acting",  "personality": "secretive"},
    {"primary_goal": "resource_security","doctrine": "The hungry do not negotiate",    "personality": "pragmatic"},
    {"primary_goal": "regional_dominance","doctrine":"Control the heartland, control the world","personality": "ambitious"},
]


def _seed_faction_identities(world: dict[str, Any]) -> list[dict[str, Any]]:
    factions = _faction_names(world)
    identities: list[dict[str, Any]] = []

    for faction in factions:
        pw = _power(world, faction)
        rng = _stable_rng(faction, faction, "identity")

        # Pick goal profile based on power shape
        if pw["mil"] >= 65:
            candidates = [p for p in _GOAL_PROFILES if p["primary_goal"] in ("expansion", "regional_dominance")]
        elif pw["eco"] >= 65:
            candidates = [p for p in _GOAL_PROFILES if p["primary_goal"] in ("trade_dominance", "resource_security")]
        elif pw["rel"] >= 65:
            candidates = [p for p in _GOAL_PROFILES if p["primary_goal"] in ("religious_spread", "political_control")]
        elif pw["pol"] >= 60:
            candidates = [p for p in _GOAL_PROFILES if p["primary_goal"] in ("political_control", "intelligence")]
        else:
            candidates = _GOAL_PROFILES

        profile = rng.choice(candidates)
        secondary = rng.choice([p for p in _GOAL_PROFILES if p != profile])

        identities.append({
            "faction": faction,
            "goals": [profile["primary_goal"], secondary["primary_goal"]],
            "doctrine": profile["doctrine"],
            "personality": profile["personality"],
        })

    return identities


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def seed_world_if_needed(world: dict[str, Any]) -> bool:
    """Seed relationships and identities if they are missing.

    Returns True if seeding ran (first-time or reset), False if skipped.
    Called before pressure in the tick pipeline.
    """
    rels = world.get("relationships")
    ids_ = world.get("faction_identities")

    needs_rels = not rels or len(rels) == 0
    needs_ids = not ids_ or (isinstance(ids_, list) and len(ids_) == 0)

    if not needs_rels and not needs_ids:
        return False

    if needs_rels:
        world["relationships"] = _seed_relationships(world)

    if needs_ids:
        world["faction_identities"] = _seed_faction_identities(world)

    return True
