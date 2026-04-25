import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

def _pause():
    try:
        from scheduler import pause_ticks
        pause_ticks()
    except Exception:
        pass

def _resume():
    try:
        from scheduler import resume_ticks
        resume_ticks()
    except Exception:
        pass

WORLD_STATE_FILE = "world_state.json"
WORLDS_DIR = "worlds"
HISTORY_DIR = "history"
REGIONS_FILE = "regions.json"


_RACE_TERRAIN_SCORE = {
    "Dwarf":     {"mountain": 10, "frozen": 5,  "plains": 2, "dense forest": 1, "coastal": 1},
    "High Elf":  {"dense forest": 10, "plains": 4, "coastal": 3, "mountain": 2, "frozen": 1},
    "Dark Elf":  {"dense forest": 8,  "coastal": 5, "plains": 3, "mountain": 2, "frozen": 2},
    "Orc":       {"plains": 8,  "frozen": 7, "mountain": 5, "coastal": 3, "dense forest": 2},
    "Goblin":    {"plains": 7,  "coastal": 6, "dense forest": 5, "mountain": 3, "frozen": 1},
    "Human":     {"plains": 8,  "coastal": 7, "dense forest": 5, "mountain": 3, "frozen": 2},
}

_TYPE_TERRAIN_BONUS = {
    "Empire":        {"coastal": 5},
    "Hold":          {"mountain": 5},
    "Guild":         {"mountain": 4},
    "Court":         {"dense forest": 5},
    "Horde":         {"frozen": 4, "plains": 3},
    "Confederation": {"plains": 5},
    "Cartel":        {"coastal": 4},
    "Conclave":      {"dense forest": 4},
    "Theocracy":     {"plains": 3},
    "Kingdom":       {"plains": 4},
    "Republic":      {"coastal": 3, "plains": 3},
}


def assign_regions_to_factions(factions: list[dict], regions: dict) -> dict:
    """
    factions: list of dicts with keys 'name', 'race', 'type'
    regions:  the regions dict from get_default_regions()
    Returns the regions dict with 'controller' fields filled in.
    """
    import copy
    regions = copy.deepcopy(regions)

    if not factions or not regions:
        return regions

    # Build affinity score for every (faction, region) pair
    scores = []
    for faction in factions:
        race = faction.get("race", "Human")
        ftype = faction.get("type", "")
        fname = faction.get("name", "")
        race_scores = _RACE_TERRAIN_SCORE.get(race, _RACE_TERRAIN_SCORE["Human"])
        type_bonus  = _TYPE_TERRAIN_BONUS.get(ftype, {})
        for rname, rdata in regions.items():
            terrain = rdata.get("terrain", "")
            score = race_scores.get(terrain, 1) + type_bonus.get(terrain, 0)
            scores.append((score, fname, rname))

    scores.sort(key=lambda x: -x[0])

    assigned_regions = set()
    assigned_factions = set()

    # First pass — each faction claims its best uncontested region
    for score, fname, rname in scores:
        if rname in assigned_regions or fname in assigned_factions:
            continue
        regions[rname]["controller"] = fname
        assigned_regions.add(rname)
        assigned_factions.add(fname)

    # Second pass — factions still without a region get the best remaining (contested)
    unassigned_factions = [f["name"] for f in factions if f["name"] not in assigned_factions]
    for fname in unassigned_factions:
        for score, sname, rname in scores:
            if sname != fname:
                continue
            existing = regions[rname].get("controller")
            regions[rname]["controller"] = f"{existing}, {fname} (contested)"
            break

    return regions


def get_default_regions() -> dict:
    if not os.path.exists(REGIONS_FILE):
        print(f"[get_default_regions] WARNING: {REGIONS_FILE} not found — regions will be empty")
        return {}
    with open(REGIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("regions", {})


def load_world() -> dict:
    if os.path.exists(WORLD_STATE_FILE):
        with open(WORLD_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    starter = os.path.join(WORLDS_DIR, "starter_world.json")
    if os.path.exists(starter):
        shutil.copy2(starter, WORLD_STATE_FILE)
        with open(WORLD_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    print("[load_world] WARNING: no world_state.json and no starter_world.json found")
    return {}


def _extract_portrait_cache() -> dict:
    if not os.path.exists(WORLD_STATE_FILE):
        return {}
    try:
        with open(WORLD_STATE_FILE, "r", encoding="utf-8") as f:
            w = json.load(f)
    except Exception:
        return {}
    portraits = {}
    for c in w.get("character_updates", []):
        if c.get("name") and c.get("portrait_image"):
            portraits[c["name"]] = c["portrait_image"]
    for row in w.get("leadership_state", []):
        r = row.get("currentRuler", {})
        if r.get("name") and r.get("portrait_image"):
            portraits[r["name"]] = r["portrait_image"]
        for h in row.get("rulerHistory", []):
            if h.get("name") and h.get("portrait_image"):
                portraits[h["name"]] = h["portrait_image"]
    for c in w.get("house_characters", []):
        if c.get("name") and c.get("portrait_image"):
            portraits[c["name"]] = c["portrait_image"]
    return portraits


def create_new_world(template_name: str) -> dict:
    template_path = os.path.join(WORLDS_DIR, template_name)
    if not os.path.exists(template_path):
        print(f"[create_new_world] ERROR: template not found: {template_path}")
        return {}
    portrait_cache = _extract_portrait_cache()
    _pause()
    try:
        shutil.copy2(template_path, WORLD_STATE_FILE)
        with open(WORLD_STATE_FILE, "r", encoding="utf-8") as f:
            world = json.load(f)
        if portrait_cache:
            world["portrait_cache"] = portrait_cache
            print(f"[create_new_world] Preserved {len(portrait_cache)} portrait references")
        if "regions" not in world:
            world["regions"] = get_default_regions()
        with open(WORLD_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(world, f, indent=2)
        print(f"[create_new_world] Created new world from template: {template_name}")
        return world
    finally:
        _resume()


def save_world_as(name: str) -> None:
    if not os.path.exists(WORLD_STATE_FILE):
        print("[save_world_as] ERROR: world_state.json not found — nothing to save")
        return
    os.makedirs(WORLDS_DIR, exist_ok=True)
    dest = os.path.join(WORLDS_DIR, name if name.endswith(".json") else name + ".json")
    shutil.copy2(WORLD_STATE_FILE, dest)
    print(f"[save_world_as] Saved world to {dest}")


def load_world_from_slot(filename: str) -> dict:
    slot_path = os.path.join(WORLDS_DIR, filename)
    if not os.path.exists(slot_path):
        print(f"[load_world_from_slot] ERROR: slot not found: {slot_path}")
        return {}
    _pause()
    try:
        shutil.copy2(slot_path, WORLD_STATE_FILE)
        with open(WORLD_STATE_FILE, "r", encoding="utf-8") as f:
            world = json.load(f)
        print(f"[load_world_from_slot] Loaded world from slot: {filename}")
        return world
    finally:
        _resume()


def list_worlds() -> list[str]:
    if not os.path.exists(WORLDS_DIR):
        return []
    return sorted(f for f in os.listdir(WORLDS_DIR) if f.endswith(".json"))


def snapshot_world() -> None:
    if not os.path.exists(WORLD_STATE_FILE):
        print("[snapshot_world] ERROR: world_state.json not found — nothing to snapshot")
        return
    os.makedirs(HISTORY_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(HISTORY_DIR, f"world_{timestamp}.json")
    shutil.copy2(WORLD_STATE_FILE, dest)
    print(f"[snapshot_world] Snapshot saved: {dest}")


def create_custom_world() -> dict:
    portrait_cache = _extract_portrait_cache()

    world = {
        "tick": 0,
        "world_date": "Day 0",
        "primary_event": "A new world is being shaped.",
        "supporting_events": [],
        "active_events": [],
        "factions": {},
        "characters": {},
    }

    if portrait_cache:
        world["portrait_cache"] = portrait_cache

    world["regions"] = get_default_regions()

    count_raw = input("How many factions? ").strip()
    if not count_raw.isdigit() or int(count_raw) < 1:
        print("[create_custom_world] Invalid count — creating world with no factions")
    else:
        count = int(count_raw)
        for i in range(count):
            name = input(f"  Faction {i + 1} name: ").strip()
            if not name:
                print(f"  Skipping faction {i + 1} — no name entered")
                continue
            world["factions"][name] = {
                "name": name,
                "power": 50,
                "relations": {},
                "status": "stable",
            }

    with open(WORLD_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(world, f, indent=2)

    print(f"[create_custom_world] World created with {len(world['factions'])} faction(s)")
    return world


def timeline_menu() -> dict:
    print("\n=== Aeloria — Timeline Manager ===")
    print("  1. Continue Current World")
    print("  2. Load Timeline")
    print("  3. Save Current World")
    print("  4. New World")
    print("  5. Custom World Creator")
    print("==================================")

    choice = input("Select an option (1-5): ").strip()

    if choice == "1":
        print("[timeline_menu] Continuing current world...")
        return load_world()

    elif choice == "2":
        worlds = list_worlds()
        if not worlds:
            print("[timeline_menu] No saved timelines found — loading current world")
            return load_world()
        print("\nAvailable timelines:")
        for i, name in enumerate(worlds, start=1):
            print(f"  {i}. {name}")
        selection = input("Enter number to load: ").strip()
        if selection.isdigit() and 1 <= int(selection) <= len(worlds):
            return load_world_from_slot(worlds[int(selection) - 1])
        print("[timeline_menu] Invalid selection — loading current world")
        return load_world()

    elif choice == "3":
        name = input("Enter a name for this timeline: ").strip()
        if name:
            save_world_as(name)
        else:
            print("[timeline_menu] No name entered — save skipped")
        return load_world()

    elif choice == "4":
        print("[timeline_menu] Starting new world from starter template...")
        return create_new_world("starter_world.json")

    elif choice == "5":
        print("[timeline_menu] Launching Custom World Creator...")
        return create_custom_world()

    else:
        print("[timeline_menu] Invalid input — loading current world")
        return load_world()
