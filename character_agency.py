"""character_agency.py — autonomous character goal-setting and travel resolution."""
import random
from typing import Optional

try:
    from map_data import (
        load_pins, faction_capital, location_to_pin,
        distance_between, travel_ticks,
    )
    _MAP_AVAILABLE = True
except ImportError:
    _MAP_AVAILABLE = False

_MAX_CHARS_PER_TICK  = 30
_MAX_RECENT_ACTIONS  = 3


# ── World state accessors ──────────────────────────────────────────────────────

def _res(world: dict, faction: str) -> dict:
    for r in world.get("faction_resources", []):
        if r.get("faction") == faction:
            return r
    return {}


def _power(world: dict, faction: str) -> dict:
    for p in world.get("faction_power_state", []):
        if p.get("faction") == faction:
            return p
    return {}


def _rel(world: dict, fa: str, fb: str) -> dict:
    for r in world.get("relationships", []):
        if {r.get("faction_a"), r.get("faction_b")} == {fa, fb}:
            return r
    return {}


def _at_war(world: dict, faction: str) -> bool:
    for r in world.get("relationships", []):
        if faction in (r.get("faction_a"), r.get("faction_b")):
            if r.get("type") == "war":
                return True
    for cw in world.get("civil_wars", []):
        if cw.get("faction") == faction:
            return True
    return False


def _ally_factions(world: dict, faction: str) -> list[str]:
    allies = []
    for r in world.get("relationships", []):
        if r.get("type") == "alliance":
            if r.get("faction_a") == faction:
                allies.append(r["faction_b"])
            elif r.get("faction_b") == faction:
                allies.append(r["faction_a"])
    return allies


def _enemy_factions(world: dict, faction: str) -> list[str]:
    enemies = []
    for r in world.get("relationships", []):
        if r.get("type") == "war":
            if r.get("faction_a") == faction:
                enemies.append(r["faction_b"])
            elif r.get("faction_b") == faction:
                enemies.append(r["faction_a"])
    return enemies


def _rival_factions(world: dict, faction: str) -> list[str]:
    rivals = []
    for r in world.get("relationships", []):
        fa, fb = r.get("faction_a"), r.get("faction_b")
        if r.get("type") in ("rivalry", "neutral") and int(r.get("hostility", 0)) > 55:
            if fa == faction:
                rivals.append(fb)
            elif fb == faction:
                rivals.append(fa)
    return rivals


def _legitimacy(world: dict, faction: str) -> float:
    rls = world.get("ruler_legitimacy_scores", {})
    if isinstance(rls, dict):
        return float(rls.get(faction, 50))
    for row in rls:
        if row.get("faction") == faction:
            return float(row.get("score", 50))
    return float(_power(world, faction).get("politicalInfluence", 50))


def _noisy(score: float) -> float:
    return score + random.gauss(0, 7.0)


# ── Action scoring ─────────────────────────────────────────────────────────────

def _score_actions(char: dict, world: dict, pins: list[dict]) -> list[tuple[str, float, dict]]:
    faction   = char.get("faction", "")
    ambition  = float(char.get("ambition",  50))
    loyalty   = float(char.get("loyalty",   50))
    morality  = float(char.get("morality",  50))
    intrigue  = float(char.get("intrigue",  50))
    warfare   = float(char.get("warfare",   50))
    diplomacy = float(char.get("diplomacy", 50))
    faith     = float(char.get("faith",     50))

    res  = _res(world, faction)
    food = float(res.get("food",     50))
    gold = float(res.get("gold",     50))
    mil  = float(res.get("military", 50))

    pw         = _power(world, faction)
    mil_power  = float(pw.get("militaryPower",      50))
    pol_inf    = float(pw.get("politicalInfluence", 50))

    at_war   = _at_war(world, faction)
    allies   = _ally_factions(world, faction)
    enemies  = _enemy_factions(world, faction)
    rivals   = _rival_factions(world, faction)
    legit    = _legitimacy(world, faction)

    candidates: list[tuple[str, float, dict]] = []

    # 1. travel_to_ally — visit an allied faction's capital to strengthen ties
    if allies and not at_war:
        target = random.choice(allies)
        dest   = faction_capital(target, pins) if _MAP_AVAILABLE else None
        if dest:
            score = diplomacy * 0.5 + loyalty * 0.3 - ambition * 0.1
            candidates.append(("travel_to_ally", _noisy(score), {"target_faction": target, "dest_pin": dest}))

    # 2. diplomatic_mission — travel to a hostile faction to negotiate
    if rivals and diplomacy > 50:
        target = random.choice(rivals)
        dest   = faction_capital(target, pins) if _MAP_AVAILABLE else None
        if dest:
            score = diplomacy * 0.6 + loyalty * 0.2
            candidates.append(("diplomatic_mission", _noisy(score), {"target_faction": target, "dest_pin": dest}))

    # 3. seek_alliance — approach a neutral faction for a formal pact
    if not allies and diplomacy > 55 and pol_inf < 65:
        target = _find_neutral(world, faction)
        dest   = faction_capital(target, pins) if (target and _MAP_AVAILABLE) else None
        if dest:
            score = diplomacy * 0.5 + (65 - pol_inf) * 0.3
            candidates.append(("seek_alliance", _noisy(score), {"target_faction": target, "dest_pin": dest}))

    # 4. spy_mission — infiltrate an enemy faction's capital
    if enemies and intrigue > 50:
        target = random.choice(enemies)
        dest   = faction_capital(target, pins) if _MAP_AVAILABLE else None
        if dest:
            score = intrigue * 0.6 + ambition * 0.2 + (100 - loyalty) * 0.2
            candidates.append(("spy_mission", _noisy(score), {"target_faction": target, "dest_pin": dest}))

    # 5. plot_against_rival — covert sabotage of a rival character
    if rivals and intrigue > 40 and morality < 65:
        target_char = _pick_rival_char(char, world)
        if target_char:
            score = ambition * 0.5 + (100 - morality) * 0.35 + intrigue * 0.2 - loyalty * 0.25
            candidates.append(("plot_against_rival", _noisy(score), {"target": target_char}))

    # 6. rally_troops — organize military forces at home capital
    if warfare > 55 and (at_war or mil < 40):
        dest  = faction_capital(faction, pins) if _MAP_AVAILABLE else None
        score = warfare * 0.6 + loyalty * 0.3 + ambition * 0.1
        candidates.append(("rally_troops", _noisy(score), {"dest_pin": dest}))

    # 7. support_ruler — shore up legitimacy
    if loyalty > 60 and (legit < 55 or pol_inf < 45):
        dest  = faction_capital(faction, pins) if _MAP_AVAILABLE else None
        score = loyalty * 0.5 + morality * 0.3 + (100 - ambition) * 0.2
        candidates.append(("support_ruler", _noisy(score), {"dest_pin": dest}))

    # 8. seek_resources — travel to a wealthy partner for aid
    shortage = max(0, 50 - food) + max(0, 50 - gold)
    if shortage > 20 and ambition > 40:
        target = _find_resource_partner(world, faction)
        dest   = faction_capital(target, pins) if (target and _MAP_AVAILABLE) else None
        if dest:
            score = ambition * 0.4 + shortage * 0.35 + (100 - loyalty) * 0.15
            candidates.append(("seek_resources", _noisy(score), {"target_faction": target, "dest_pin": dest}))

    # 9. pilgrimage — journey to a sacred site
    if faith > 65 and not at_war and food > 40:
        sacred = _find_sacred(pins)
        if sacred:
            score = faith * 0.5 + morality * 0.3 + (100 - ambition) * 0.1
            candidates.append(("pilgrimage", _noisy(score), {"dest_pin": sacred}))

    # 10. lay_low — stay put and keep a low profile
    danger = at_war and mil_power < 30
    score  = (100 - ambition) * 0.4 + morality * 0.2 + (50.0 if danger else 0)
    candidates.append(("lay_low", _noisy(score), {}))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates


def _pick_rival_char(char: dict, world: dict) -> Optional[str]:
    faction  = char.get("faction", "")
    targets  = _rival_factions(world, faction) + _enemy_factions(world, faction)
    if not targets:
        return None
    pool = [
        c for c in world.get("house_characters", [])
        if c.get("faction") in targets and int(c.get("influenceScore", 0)) > 30
    ]
    return random.choice(pool).get("name") if pool else None


def _find_resource_partner(world: dict, faction: str) -> Optional[str]:
    best, best_score = None, 0
    for r in world.get("faction_resources", []):
        f = r.get("faction")
        if not f or f == faction:
            continue
        if _rel(world, faction, f).get("type") == "war":
            continue
        score = float(r.get("food", 0)) + float(r.get("gold", 0))
        if score > best_score:
            best_score, best = score, f
    return best


def _find_neutral(world: dict, faction: str) -> Optional[str]:
    for r in world.get("relationships", []):
        if r.get("type") == "neutral":
            if r.get("faction_a") == faction:
                return r["faction_b"]
            if r.get("faction_b") == faction:
                return r["faction_a"]
    return None


def _find_sacred(pins: list[dict]) -> Optional[dict]:
    sacred_words = ("shrine", "temple", "sacred", "stone", "monastery", "holy", "relic", "stonebreak")
    matches = [
        p for p in pins
        if any(w in p.get("label", "").lower() for w in sacred_words)
    ]
    if matches:
        return random.choice(matches)
    stonebreak = [p for p in pins if p.get("faction") == "stonebreak"]
    return random.choice(stonebreak) if stonebreak else None


# ── Action execution ───────────────────────────────────────────────────────────

def _execute_action(char: dict, action: str, ctx: dict, pins: list[dict]) -> dict:
    name    = char.get("name", "Unknown")
    faction = char.get("faction", "")
    updates: dict = {}
    description   = ""

    home = _home_location(char, pins)

    if action in ("travel_to_ally", "diplomatic_mission", "spy_mission",
                  "seek_resources", "seek_alliance"):
        dest_pin      = ctx.get("dest_pin")
        target_f      = ctx.get("target_faction", "")
        dest_label    = dest_pin.get("label", home) if dest_pin else home

        # Distance-based travel time
        if _MAP_AVAILABLE and dest_pin:
            curr_pin = location_to_pin(char.get("location", ""), pins)
            dist     = distance_between(curr_pin, dest_pin) if curr_pin else 30.0
            ticks    = travel_ticks(dist)
        else:
            ticks = 2

        purposes = {
            "travel_to_ally":      (f"Visiting ally {target_f}",
                                    f"Travel to {dest_label} to strengthen ties with {target_f}",
                                    f"{name} departs for {dest_label} to reinforce the alliance with {target_f}"),
            "diplomatic_mission":  (f"Diplomatic mission to {target_f}",
                                    f"Travel to {dest_label} to negotiate with {target_f}",
                                    f"{name} sets out for {dest_label} on a diplomatic mission to {target_f}"),
            "spy_mission":         (f"Intelligence gathering in {target_f} territory",
                                    f"Infiltrate {dest_label} and gather intelligence on {target_f}",
                                    f"{name} slips quietly toward {dest_label}, tasked with spying on {target_f}"),
            "seek_resources":      (f"Seeking aid from {target_f}",
                                    f"Travel to {dest_label} to secure resources from {target_f}",
                                    f"{name} rides for {dest_label} to negotiate resource aid from {target_f}"),
            "seek_alliance":       (f"Alliance overture to {target_f}",
                                    f"Travel to {dest_label} to propose alliance with {target_f}",
                                    f"{name} journeys to {dest_label} seeking a formal alliance with {target_f}"),
        }
        purpose, goal, desc = purposes[action]
        updates = {
            "destination":     dest_label,
            "ticks_to_arrive": ticks,
            "journey_purpose": purpose,
            "currentGoal":     goal,
        }
        description = desc

    elif action == "rally_troops":
        dest_pin   = ctx.get("dest_pin")
        dest_label = dest_pin.get("label", home) if dest_pin else home
        ticks      = 1 if dest_label != char.get("location", "") else 0
        updates = {
            "currentGoal":     f"Organize and reinforce {faction} forces at {dest_label}",
            "destination":     dest_label if ticks else "",
            "ticks_to_arrive": ticks,
            "journey_purpose": "Rallying troops",
        }
        description = (
            f"{name} takes command of {faction} forces at {dest_label}, "
            f"drilling soldiers and shoring up defenses"
        )

    elif action == "support_ruler":
        dest_pin   = ctx.get("dest_pin")
        dest_label = dest_pin.get("label", home) if dest_pin else home
        ticks      = 1 if dest_label != char.get("location", "") else 0
        updates = {
            "currentGoal":     f"Bolster the legitimacy of {faction} leadership",
            "destination":     dest_label if ticks else "",
            "ticks_to_arrive": ticks,
            "journey_purpose": "Supporting the ruler",
        }
        description = (
            f"{name} works openly to shore up support for {faction}'s ruler, "
            f"rallying the court and quieting dissent"
        )

    elif action == "plot_against_rival":
        target = ctx.get("target", "an unnamed rival")
        updates = {
            "currentGoal":     f"Undermine {target} through covert means",
            "destination":     "",
            "ticks_to_arrive": 0,
            "journey_purpose": "",
        }
        description = (
            f"{name} begins weaving a quiet plot against {target}, moving pawns in the shadows"
        )

    elif action == "pilgrimage":
        dest_pin   = ctx.get("dest_pin")
        dest_label = dest_pin.get("label", "a holy site") if dest_pin else "a holy site"
        if _MAP_AVAILABLE and dest_pin:
            curr_pin = location_to_pin(char.get("location", ""), pins)
            ticks    = travel_ticks(distance_between(curr_pin, dest_pin)) if curr_pin else 2
        else:
            ticks = 2
        updates = {
            "destination":     dest_label,
            "ticks_to_arrive": ticks,
            "journey_purpose": "Pilgrimage",
            "currentGoal":     f"Make pilgrimage to {dest_label}",
        }
        description = f"{name} departs on pilgrimage to {dest_label}, seeking spiritual clarity"

    else:  # lay_low
        updates = {
            "currentGoal":     f"Keep a low profile and preserve {faction}'s stability",
            "destination":     "",
            "ticks_to_arrive": 0,
            "journey_purpose": "",
        }
        description = (
            f"{name} withdraws from the public eye, moving cautiously and avoiding unnecessary exposure"
        )

    return {"updates": updates, "description": description, "action": action}


def _home_location(char: dict, pins: list[dict]) -> str:
    loc = char.get("location", "")
    if loc:
        return loc
    if _MAP_AVAILABLE:
        cap = faction_capital(char.get("faction", ""), pins)
        if cap:
            return cap.get("label", "")
    return char.get("faction", "Unknown")


# ── Travel resolution ──────────────────────────────────────────────────────────

def _resolve_travel(char: dict) -> Optional[str]:
    ticks_left = int(char.get("ticks_to_arrive", 0))
    if ticks_left <= 0:
        return None
    ticks_left -= 1
    char["ticks_to_arrive"] = ticks_left
    if ticks_left == 0:
        dest = char.get("destination", "")
        if dest:
            char["location"] = dest
            char["destination"] = ""
            char["journey_purpose"] = ""
            return f"{char.get('name', 'Unknown')} arrives at {dest}"
    return None


# ── Main entry point ───────────────────────────────────────────────────────────

def run_character_agency(world: dict) -> None:
    """Autonomous character goal-setting and travel resolution. Mutates world in-place."""
    chars = world.get("house_characters", [])
    if not chars:
        return

    pins = load_pins() if _MAP_AVAILABLE else []
    tick = int(world.get("tick", 0))
    character_updates = world.setdefault("character_updates", [])

    # Phase 1: advance all in-progress travel
    for char in chars:
        if int(char.get("ticks_to_arrive", 0)) > 0:
            arrival = _resolve_travel(char)
            if arrival:
                character_updates.append({
                    "character":   char.get("name"),
                    "faction":     char.get("faction"),
                    "action":      "arrived",
                    "description": arrival,
                    "detail":      char.get("journey_purpose", "travel"),
                    "tick":        tick,
                })

    # Phase 2: weighted sample of idle characters — higher influence = higher chance
    idle = [c for c in chars if int(c.get("ticks_to_arrive", 0)) == 0]
    if not idle:
        return

    total_w = sum(max(1, int(c.get("influenceScore", 10))) for c in idle)
    selected: list[dict] = []
    for c in idle:
        if len(selected) >= _MAX_CHARS_PER_TICK:
            break
        prob = max(1, int(c.get("influenceScore", 10))) / total_w * _MAX_CHARS_PER_TICK
        if random.random() < prob:
            selected.append(c)

    if not selected:
        selected = random.sample(idle, min(5, len(idle)))

    for char in selected:
        scored = _score_actions(char, world, pins)
        if not scored:
            continue

        action, _, ctx = scored[0]
        result = _execute_action(char, action, ctx, pins)

        for k, v in result["updates"].items():
            char[k] = v

        desc = result["description"]
        if desc:
            actions_list = char.setdefault("recentActions", [])
            actions_list.append(desc)
            if len(actions_list) > _MAX_RECENT_ACTIONS:
                char["recentActions"] = actions_list[-_MAX_RECENT_ACTIONS:]

            character_updates.append({
                "character":   char.get("name"),
                "faction":     char.get("faction"),
                "house":       char.get("house"),
                "action":      result["action"],
                "description": desc,
                "tick":        tick,
            })

    if len(character_updates) > 50:
        world["character_updates"] = character_updates[-50:]
