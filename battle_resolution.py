"""
Deterministic land battle resolution — pure computation, no narrative.

Same inputs always yield the same {winner, losses, remaining_forces}.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

# Terrain category for battle (lowercase labels; aliases accepted)
# Non-plains favor defender per spec; attacker always 1.0 for those.
TERRAIN_ATTACKER: Dict[str, float] = {
    "plains": 1.0,
    "forest": 1.0,
    "mountains": 1.0,
    "frozen": 1.0,
}
TERRAIN_DEFENDER: Dict[str, float] = {
    "plains": 1.0,
    "forest": 1.1,
    "mountains": 1.25,
    "frozen": 1.2,
}

FORT_BONUS_PER_LEVEL = 0.1  # defender multiplier: 1 + fort_level * this


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _normalize_terrain(terrain: Optional[str]) -> str:
    t = (terrain or "plains").strip().lower()
    if t in TERRAIN_DEFENDER:
        return t
    if t in ("wood", "woodland", "jungle", "grove", "boreal", "hills", "moor"):
        return "forest"
    if t in (
        "mountain",
        "highland",
        "highlands",
        "peaks",
        "alpine",
        "cliff",
    ) or "mountain" in t:
        return "mountains"
    if t in ("frost", "tundra", "ice", "glacial", "frostvale", "winter_fell") or "frost" in t:
        return "frozen"
    if t in ("plains", "farmland", "heath", "meadow", "grassland", "wilderness", "default", "steppe"):
        return "plains"
    return "plains"


def effective_strength(
    army: Dict[str, Any],
    side: str,
    terrain: str,
    fort_level: int = 0,
) -> float:
    """
    side: "attacker" | "defender"
    Fortification applies only to the defender in a siege battle.
    """
    m = max(0, int(army.get("manpower", 0) or 0))
    mor = int(army.get("morale", 50) or 50)
    dis = int(army.get("discipline", 50) or 50)
    morf = _clamp(mor, 0, 100) / 100.0
    disf = _clamp(dis, 0, 100) / 100.0
    if morf < 0.01:
        morf = 0.01
    if disf < 0.01:
        disf = 0.01
    cat = _normalize_terrain(terrain)
    if side == "attacker":
        mod = TERRAIN_ATTACKER[cat]
    else:
        mod = TERRAIN_DEFENDER[cat]
        fl = int(_clamp(float(fort_level or 0), 0, 5))
        fort_mul = 1.0 + fl * FORT_BONUS_PER_LEVEL
        mod *= fort_mul
    return float(m) * morf * disf * mod


def resolve_battle(
    attacker_army: Dict[str, Any],
    defender_army: Dict[str, Any],
    terrain: str,
    fort_level: int = 0,
) -> Dict[str, Any]:
    """
    Run steps 1–6 deterministically. No narration.

    Returns:
        winner: "attacker" | "defender"
        attacker_losses, defender_losses: int (men)
        remaining_forces: { "attacker": {manpower, morale}, "defender": {manpower, morale} }
    """
    a = {**attacker_army}
    b = {**defender_army}
    fl = int(_clamp(int(fort_level or 0), 0, 5))

    atk_s = effective_strength(a, "attacker", terrain, 0)
    def_s = effective_strength(b, "defender", terrain, fl)

    total = atk_s + def_s + 1e-6
    margin = abs(atk_s - def_s) / total  # 0..~1, how lopsided

    # Step 4: higher strength wins; tie -> defender (holding ground)
    if atk_s > def_s:
        winner = "attacker"
    else:
        winner = "defender"

    # Step 5: casualties as fractions in [0.1,0.3] winner and [0.3,0.6] loser
    loser_loss_pct = 0.3 + 0.3 * margin
    winner_loss_pct = 0.3 - 0.2 * margin  # 0.1 at margin 1, 0.3 at margin 0

    am = max(0, int(a.get("manpower", 0) or 0))
    dm = max(0, int(b.get("manpower", 0) or 0))
    a_mor = int(_clamp(int(a.get("morale", 50) or 50), 0, 100))
    b_mor = int(_clamp(int(b.get("morale", 50) or 50), 0, 100))
    if winner == "attacker":
        att_loss = int(math.floor(am * winner_loss_pct))
        def_loss = int(math.floor(dm * loser_loss_pct))
        am1 = max(0, am - att_loss)
        dm1 = max(0, dm - def_loss)
        # Morale: loser collapses, winner firms up
        a_mor1 = int(_clamp(round(a_mor * (0.88 + 0.12 * margin)), 0, 100))
        b_mor1 = int(_clamp(round(b_mor * (0.15 + 0.35 * (1.0 - margin))), 0, 100))
    else:
        att_loss = int(math.floor(am * loser_loss_pct))
        def_loss = int(math.floor(dm * winner_loss_pct))
        am1 = max(0, am - att_loss)
        dm1 = max(0, dm - def_loss)
        a_mor1 = int(_clamp(round(a_mor * (0.15 + 0.35 * (1.0 - margin))), 0, 100))
        b_mor1 = int(_clamp(round(b_mor * (0.88 + 0.12 * margin)), 0, 100))

    return {
        "winner": winner,
        "attacker_losses": att_loss,
        "defender_losses": def_loss,
        "remaining_forces": {
            "attacker": {"manpower": am1, "morale": a_mor1},
            "defender": {"manpower": dm1, "morale": b_mor1},
        },
    }


def resolve_battle_with_meta(
    attacker_army: Dict[str, Any],
    defender_army: Dict[str, Any],
    terrain: str,
    fort_level: int = 0,
) -> Dict[str, Any]:
    """
    Same as resolve_battle but includes computed strengths for tests / tooling.
    """
    cat = _normalize_terrain(terrain)
    fl = int(_clamp(int(fort_level or 0), 0, 5))
    atk_s = effective_strength(attacker_army, "attacker", terrain, 0)
    def_s = effective_strength(defender_army, "defender", terrain, fl)
    out = resolve_battle(attacker_army, defender_army, terrain, fort_level)
    out["_computed"] = {
        "terrain": cat,
        "fort_level": fl,
        "attacker_strength": round(atk_s, 4),
        "defender_strength": round(def_s, 4),
    }
    return out


__all__ = [
    "effective_strength",
    "resolve_battle",
    "resolve_battle_with_meta",
    "TERRAIN_ATTACKER",
    "TERRAIN_DEFENDER",
    "FORT_BONUS_PER_LEVEL",
]
