"""
territory_engine.py
Post-tick processor that scans world events for territorial actions
and updates region controllers + stability accordingly.
Never modifies existing event data — only reads it and updates regions.
"""
import re
import logging

logger = logging.getLogger(__name__)

# ── Stability ladder ──────────────────────────────────────────────────────────
_STABILITY = ["low", "medium", "high"]

def _shift_stability(current: str, delta: int) -> str:
    idx = _STABILITY.index(current) if current in _STABILITY else 1
    return _STABILITY[max(0, min(2, idx + delta))]

# ── Keyword patterns ──────────────────────────────────────────────────────────
_EXPAND_RE   = re.compile(r"\b(expand|march into|occupy|annex|capture|take control of|move into|seize)\b", re.I)
_RAID_RE     = re.compile(r"\b(raid|raids|raiding|ambush|ambushes|strike|strikes|assault|attack|attacks|skirmish)\b", re.I)
_LOSE_RE     = re.compile(r"\b(lose control|loses control|retreat|retreats|abandon|abandons|fall|falls|collapse|collapses|cede|cedes)\b", re.I)
_CONTEST_RE  = re.compile(r"\b(contest|contested|dispute|disputed|fight over|battle for|clash over)\b", re.I)

def _detect_action(text: str) -> str | None:
    if _EXPAND_RE.search(text):  return "expansion"
    if _RAID_RE.search(text):    return "raid"
    if _LOSE_RE.search(text):    return "loss"
    if _CONTEST_RE.search(text): return "contest"
    return None

def _find_region(text: str, regions: dict) -> str | None:
    for name in regions:
        if name.lower() in text.lower():
            return name
    return None

def _find_faction(text: str, factions: list[str]) -> str | None:
    for name in factions:
        if name.lower() in text.lower():
            return name
    return None

# ── Core processors ───────────────────────────────────────────────────────────

def apply_control_change(regions: dict, region_name: str, new_controller: str) -> None:
    if region_name not in regions:
        return
    old = regions[region_name].get("controller")
    if old == new_controller:
        return
    regions[region_name]["controller"] = new_controller
    regions[region_name]["stability"]  = _shift_stability(regions[region_name].get("stability", "medium"), -1)
    logger.info(f"[territory] {region_name}: control changed from '{old}' to '{new_controller}'")

def mark_contested(regions: dict, region_name: str, aggressor: str) -> None:
    if region_name not in regions:
        return
    current = regions[region_name].get("controller") or "None"
    if aggressor.lower() in current.lower():
        return
    label = f"{current}, {aggressor} (contested)"
    regions[region_name]["controller"] = label
    regions[region_name]["stability"]  = _shift_stability(regions[region_name].get("stability", "medium"), -1)
    logger.info(f"[territory] {region_name}: contested between '{current}' and '{aggressor}'")

def adjust_stability(regions: dict, region_name: str, delta: int) -> None:
    if region_name not in regions:
        return
    before = regions[region_name].get("stability", "medium")
    regions[region_name]["stability"] = _shift_stability(before, delta)
    after = regions[region_name]["stability"]
    if before != after:
        logger.info(f"[territory] {region_name}: stability {before} -> {after}")

# ── Regional pressure ─────────────────────────────────────────────────────────

def _resource_drain(region_data: dict) -> int:
    """Return -1 if two or more resource slots are low, else 0."""
    resources = region_data.get("resources", {})
    if sum(1 for v in resources.values() if v == "low") >= 2:
        return -1
    return 0

def _controller_bonus(region_data: dict) -> int:
    """Return +1 for a single clear controller with no contest, else 0."""
    controller = str(region_data.get("controller") or "None")
    if controller == "None" or "contested" in controller.lower():
        return 0
    return 1

def apply_regional_pressure(regions: dict, conflict_regions: set[str]) -> None:
    """
    Per-region pass run after event processing.
    - Regions that took a conflict hit this tick skip the peace bonus.
    - Low resources bleed stability.
    - Sets conflict_pressure and rebellion_risk flags for the LLM to read.
    """
    for rname, rdata in regions.items():
        delta = _resource_drain(rdata)

        if rname not in conflict_regions:
            delta += _controller_bonus(rdata)

        if delta != 0:
            adjust_stability(regions, rname, delta)

        stability   = regions[rname].get("stability", "medium")
        controller  = str(regions[rname].get("controller") or "None")
        uncontrolled = controller == "None" or "contested" in controller.lower()

        regions[rname]["conflict_pressure"] = stability == "low"
        regions[rname]["rebellion_risk"]    = stability == "low" and uncontrolled

        if regions[rname]["conflict_pressure"]:
            logger.info(f"[territory] {rname}: LOW stability — conflict pressure active")
        if regions[rname]["rebellion_risk"]:
            logger.info(f"[territory] {rname}: LOW stability + no clear control — rebellion risk")

# ── Main entry point ──────────────────────────────────────────────────────────

def process_territorial_events(world: dict) -> dict:
    """
    Reads active_events and recent_events from world state.
    Updates regions in-place based on detected territorial actions.
    Returns the modified world dict.
    """
    regions = world.get("regions")
    if not regions:
        return world

    # Build faction name list from leadership_state + faction_identities
    factions = list(world.get("faction_identities", {}).keys())
    for row in world.get("leadership_state", []):
        fname = row.get("faction", "")
        if fname and fname not in factions:
            factions.append(fname)

    # Collect all event texts to scan
    events = []
    primary = world.get("primary_event")
    if isinstance(primary, dict):
        events.append(primary.get("summary") or primary.get("name") or "")
    elif isinstance(primary, str):
        events.append(primary)

    for ev in world.get("active_events", []):
        events.append(f"{ev.get('name','')} {ev.get('summary','')}")
    for ev in world.get("supporting_events", []):
        events.append(f"{ev.get('name','')} {ev.get('summary','')}")
    for ev in world.get("recent_events", []):
        events.append(ev.get("text") or "")

    # Process each event; track which regions took a conflict hit this tick
    conflict_regions: set[str] = set()

    for text in events:
        if not text:
            continue
        action  = _detect_action(text)
        region  = _find_region(text, regions)
        faction = _find_faction(text, factions)

        if not action or not region:
            continue

        if action == "expansion" and faction:
            apply_control_change(regions, region, faction)
            conflict_regions.add(region)

        elif action == "raid":
            adjust_stability(regions, region, -1)
            conflict_regions.add(region)
            if faction:
                logger.info(f"[territory] {region}: raided by {faction}")

        elif action == "loss" and faction:
            current = regions[region].get("controller", "")
            if faction.lower() in current.lower():
                regions[region]["controller"] = "None"
                regions[region]["stability"]  = _shift_stability(regions[region].get("stability", "medium"), -1)
                logger.info(f"[territory] {region}: {faction} lost control")
            conflict_regions.add(region)

        elif action == "contest" and faction:
            mark_contested(regions, region, faction)
            conflict_regions.add(region)

    # Second pass: resource drain, peace recovery, and pressure flags
    apply_regional_pressure(regions, conflict_regions)

    world["regions"] = regions
    return world
