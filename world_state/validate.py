import logging

logger = logging.getLogger(__name__)

REQUIRED_WORLD_KEYS = {"tick", "world_date", "primary_event", "supporting_events", "active_events"}

STRUCTURE_REQUIRED_KEYS = {
    "tick", "world_date", "primary_event",
    "supporting_events", "active_events",
}

# Container keys — if Claude returns them empty, restore from previous world.
CONTAINER_PRESERVE_KEYS = {
    "faction_identities", "region_control", "relationships", "regions",
    "faction_power_state", "leadership_state", "locations", "house_characters",
    "faction_economy",
    "resource_market",
    "economic_trade_routes",
    "economic_route_flows",
    "siege_warfare",
    "faction_armies",
    "treaties",
    "noble_marriages",
    "character_marriages",
    "tributary_pacts",
    "ruler_legitimacy_scores",
    "faction_lifecycle_report",
    "collapsed_factions",
    "civil_wars",
    "emerging_factions",
    "vacant_thrones",
    "reunification_claims",
    "new_kingdom_claims",
}


def is_valid_world(world: dict) -> bool:
    if not isinstance(world, dict):
        logger.error(f"World validation failed: expected dict, got {type(world).__name__}")
        return False
    missing = REQUIRED_WORLD_KEYS - world.keys()
    if missing:
        logger.error(f"World validation failed: missing keys {sorted(missing)}")
        return False
    return True


def ensure_world_structure(world: dict, previous_world: dict) -> dict:
    if not isinstance(world, dict) or not world:
        logger.error("ensure_world_structure: world is invalid — returning previous world")
        return previous_world if isinstance(previous_world, dict) and previous_world else {}

    try:
        from sim_engine_sanitize import sanitize_world_state
        sanitize_world_state(world)
    except Exception as e:
        logger.warning("sanitize_world_state failed (continuing): %s", e)

    prev = previous_world if isinstance(previous_world, dict) else {}

    for key in STRUCTURE_REQUIRED_KEYS:
        if key not in world or world[key] is None:
            if key in prev and prev[key] is not None:
                world[key] = prev[key]
                logger.warning(f"ensure_world_structure: restored missing key '{key}' from previous world")
            else:
                logger.error(f"ensure_world_structure: '{key}' missing and no fallback — returning previous world")
                return prev if prev else world

    for key in CONTAINER_PRESERVE_KEYS:
        val = world.get(key)
        prev_val = prev.get(key)
        if (val is None or (isinstance(val, (list, dict)) and len(val) == 0)) and prev_val:
            world[key] = prev_val
            logger.warning(f"ensure_world_structure: restored empty container '{key}' from previous world")

    return world


def _canonicalize_world_state(prev_state, state):
    """Return API-safe, normalized world state for persistence and responses."""
    from world_state.normalize import _normalize_state

    normalized = _normalize_state(prev_state or {}, state or {})
    normalized = ensure_world_structure(normalized, prev_state or {})
    if not is_valid_world(normalized):
        logger.error("canonicalize: normalized world failed validation; returning previous state")
        return prev_state or normalized
    return normalized
