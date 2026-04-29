"""map_data.py — utilities for reading map pin data and computing geographic distances."""
import json
import math
from pathlib import Path
from typing import Optional

_PINS_PATH = Path(__file__).parent / "public" / "data" / "locations.json"

# Engine faction name → pin faction_id
_NAME_TO_ID: dict[str, str] = {
    "Twin Cities":           "twin_cities",
    "High Kingdom":          "twin_cities",
    "Shadow Court":          "faerwood",
    "Faerwood":              "faerwood",
    "Glenhaven":             "glenwood",
    "Glenwood":              "glenwood",
    "Groth Clans":           "groth_clans",
    "Gilgeth Clans":         "gilgeth_clans",
    "Tidefall":              "tidefall",
    "Varkuun":               "varkuun",
    "Farrock":               "varkuun",
    "Vilefin":               "vilefin",
    "The Wintermark":        "frostvale",
    "Wintermark":            "frostvale",
    "Frostvale":             "frostvale",
    "Lostfeld":              "lostfeld",
    "Dur Khadur":            "dur_khadur",
    "Dreadwind":             "dreadwind",
    "Dreadwind Isles":       "dreadwind",
    "Stonebreak":            "stonebreak",
    "Stonebreak Monastery":  "stonebreak",
}

_ID_TO_NAME: dict[str, str] = {v: k for k, v in reversed(list(_NAME_TO_ID.items()))}


def faction_name_to_id(name: str) -> str:
    if name in _NAME_TO_ID:
        return _NAME_TO_ID[name]
    return name.lower().replace(" ", "_").replace("'", "").replace("-", "_")


def faction_id_to_name(fid: str) -> str:
    return _ID_TO_NAME.get(fid, fid.replace("_", " ").title())


def load_pins() -> list[dict]:
    """Load all map pins from locations.json. Returns [] if file missing."""
    try:
        return json.loads(_PINS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def faction_capital(faction_name: str, pins: Optional[list[dict]] = None) -> Optional[dict]:
    """Return the faction_capital pin for a faction, or None."""
    fid = faction_name_to_id(faction_name)
    pins = pins if pins is not None else load_pins()
    for p in pins:
        if p.get("faction") == fid and p.get("type") == "faction_capital":
            return p
    # fallback: any pin belonging to faction
    for p in pins:
        if p.get("faction") == fid:
            return p
    return None


def distance_between(pin_a: dict, pin_b: dict) -> float:
    """Euclidean distance between two pins in map % units (0–141 max)."""
    dx = float(pin_a.get("x", 0)) - float(pin_b.get("x", 0))
    dy = float(pin_a.get("y", 0)) - float(pin_b.get("y", 0))
    return math.sqrt(dx * dx + dy * dy)


def travel_ticks(dist: float) -> int:
    """Convert map distance to travel ticks (1–5)."""
    if dist < 15:
        return 1
    elif dist < 30:
        return 2
    elif dist < 50:
        return 3
    elif dist < 70:
        return 4
    else:
        return 5


def location_to_pin(location_str: str, pins: Optional[list[dict]] = None) -> Optional[dict]:
    """Fuzzy-match a character location string to the nearest matching pin."""
    if not location_str:
        return None
    pins = pins if pins is not None else load_pins()
    loc_lower = location_str.lower().strip()

    # exact label match
    for p in pins:
        if p.get("label", "").lower() == loc_lower:
            return p

    # faction name → capital
    for name, fid in _NAME_TO_ID.items():
        if name.lower() == loc_lower:
            for p in pins:
                if p.get("faction") == fid and p.get("type") == "faction_capital":
                    return p

    # partial label match
    for p in pins:
        label = p.get("label", "").lower()
        if loc_lower in label or label in loc_lower:
            return p

    return None


def faction_pins(faction_name: str, pins: Optional[list[dict]] = None) -> list[dict]:
    """All pins belonging to a faction."""
    fid = faction_name_to_id(faction_name)
    pins = pins if pins is not None else load_pins()
    return [p for p in pins if p.get("faction") == fid]


def nearby_factions(pin: dict, all_pins: list[dict], radius: float = 25.0) -> list[str]:
    """Return faction engine names of other factions with pins within radius map units."""
    own_fid = pin.get("faction")
    seen: set[str] = set()
    for p in all_pins:
        fid = p.get("faction")
        if not fid or fid == own_fid:
            continue
        if distance_between(pin, p) <= radius:
            seen.add(faction_id_to_name(fid))
    return list(seen)
