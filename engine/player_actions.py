"""Player intervention layer for the Axiom Engine.

Player actions are applied before pressure is computed each tick, so factions
react to them in the same tick they land. Each action:

  1. Mutates world state (the mechanical effect)
  2. Records a causality entry (visible in council, chronicles, explainability)
  3. Distributes knowledge (public actions -> facts; covert ones -> rumors)

Queue:  world_state["pending_player_actions"] — list of action dicts.
        Cleared after processing each tick.
Result: world_state["last_player_actions"]    — results from the last batch.
"""

from __future__ import annotations

from typing import Any

from engine.causality import record_cause
from engine.knowledge import record_fact, record_rumor, record_suspicion

_VALID_ACTIONS = {
    "send_aid",
    "spread_rumor",
    "fund_faction",
    "reveal_secret",
    "support_claimant",
    "impose_embargo",
}


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _power_row(world_state: dict[str, Any], faction: str) -> dict[str, Any]:
    for row in world_state.get("faction_power_state") or []:
        if isinstance(row, dict) and row.get("faction") == faction:
            return row
    row: dict[str, Any] = {"faction": faction, "militaryPower": 50, "economicPower": 50, "politicalInfluence": 50}
    world_state.setdefault("faction_power_state", []).append(row)
    return row


def _neighboring_factions(world_state: dict[str, Any], faction: str) -> list[str]:
    neighbors: list[str] = []
    for row in world_state.get("relationships") or []:
        if not isinstance(row, dict):
            continue
        a, b = str(row.get("faction_a") or ""), str(row.get("faction_b") or "")
        if a == faction and b:
            neighbors.append(b)
        elif b == faction and a:
            neighbors.append(a)
    return neighbors


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _send_aid(world_state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    """Deliver resources to a faction, easing economic pressure."""
    target = str(action.get("target_faction") or "").strip()
    resource = str(action.get("resource") or "grain").strip()
    amount = min(float(action.get("amount") or 50), 300.0)
    reason = str(action.get("reason") or "external aid").strip()

    if not target:
        return {"error": "target_faction required"}

    for row in world_state.get("faction_economy") or []:
        if not isinstance(row, dict):
            continue
        if row.get("faction") == target or row.get("faction_id") == target:
            res = row.setdefault("resources", {}).setdefault(
                resource,
                {"stockpile": 0.0, "storage_capacity": 500.0, "production": 0.0, "consumption": 0.0},
            )
            cap = float(res.get("storage_capacity") or 500.0)
            res["stockpile"] = min(cap, float(res.get("stockpile") or 0.0) + amount)
            shortage = row.setdefault("shortage_effects", {}).setdefault(resource, {"severity": 0.0})
            if isinstance(shortage, dict):
                shortage["severity"] = max(0.0, float(shortage.get("severity") or 0.0) - 0.3)
            break

    cause = record_cause(
        world_state,
        domain="economy",
        actor="Player",
        pressure=reason,
        decision="send_aid",
        outcome=f"Player delivered {amount:.0f} {resource} to {target}.",
        affected=["Player", target],
        severity=6,
        confidence=1.0,
        source="player",
    )

    record_fact(world_state, target, f"Aid arrived: {amount:.0f} {resource} received.", cause_id=cause["id"])
    for neighbor in _neighboring_factions(world_state, target):
        record_rumor(world_state, neighbor, f"{target} received outside aid.", cause_id=cause["id"])

    return {"applied": True, "cause_id": cause["id"], "outcome": cause["outcome"]}


def _spread_rumor(world_state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    """Inject a rumor into a faction's knowledge."""
    target = str(action.get("target_faction") or "").strip()
    text = str(action.get("text") or "").strip()
    about = str(action.get("about_faction") or "").strip()

    if not target or not text:
        return {"error": "target_faction and text required"}

    cause = record_cause(
        world_state,
        domain="intrigue",
        actor="Player",
        pressure="player intelligence operation",
        decision="spread_rumor",
        outcome=f"Rumor seeded in {target}: {text}",
        affected=[target],
        hidden="Player origin concealed.",
        severity=5,
        confidence=0.7,
        source="player",
    )

    record_rumor(world_state, target, text, cause_id=cause["id"])
    if about:
        record_suspicion(world_state, target, f"Suspicion regarding {about}: {text}", cause_id=cause["id"])

    return {"applied": True, "cause_id": cause["id"], "outcome": cause["outcome"]}


def _fund_faction(world_state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    """Covertly boost a faction's economic or military power."""
    target = str(action.get("target_faction") or "").strip()
    domain = str(action.get("domain") or "economic").strip()
    amount = min(float(action.get("amount") or 10), 20.0)
    reason = str(action.get("reason") or "covert funding").strip()

    if not target:
        return {"error": "target_faction required"}

    row = _power_row(world_state, target)
    if domain == "military":
        row["militaryPower"] = _clamp(float(row.get("militaryPower") or 50) + amount)
        outcome = f"Player funded {target} military (+{amount:.0f})."
    else:
        row["economicPower"] = _clamp(float(row.get("economicPower") or 50) + amount)
        outcome = f"Player funded {target} economy (+{amount:.0f})."

    cause = record_cause(
        world_state,
        domain="economy",
        actor="Player",
        pressure=reason,
        decision="fund_faction",
        outcome=outcome,
        affected=["Player", target],
        hidden="Funding source concealed.",
        severity=7,
        confidence=1.0,
        source="player",
    )

    record_fact(world_state, target, outcome, cause_id=cause["id"])

    return {"applied": True, "cause_id": cause["id"], "outcome": outcome}


def _reveal_secret(world_state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    """Promote a causality record to a known fact for a target faction."""
    target = str(action.get("target_faction") or "").strip()
    cause_id = str(action.get("cause_id") or "").strip()

    if not target or not cause_id:
        return {"error": "target_faction and cause_id required"}

    ledger = world_state.get("causality_ledger") or []
    source_cause = next(
        (r for r in ledger if isinstance(r, dict) and r.get("id") == cause_id),
        None,
    )

    if not source_cause:
        return {"error": f"cause {cause_id!r} not found in ledger"}

    text = str(source_cause.get("outcome") or source_cause.get("decision") or "").strip()
    record_fact(world_state, target, f"Revealed: {text}", cause_id=cause_id)

    cause = record_cause(
        world_state,
        domain="intrigue",
        actor="Player",
        pressure="player intelligence reveal",
        decision="reveal_secret",
        outcome=f"Player revealed {cause_id} to {target}: {text}",
        affected=["Player", target],
        severity=8,
        confidence=1.0,
        source="player",
    )

    return {"applied": True, "cause_id": cause["id"], "outcome": cause["outcome"]}


def _support_claimant(world_state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    """Boost a faction's political influence and legitimacy."""
    target = str(action.get("target_faction") or "").strip()
    amount = min(float(action.get("amount") or 8), 15.0)
    reason = str(action.get("reason") or "external political backing").strip()

    if not target:
        return {"error": "target_faction required"}

    row = _power_row(world_state, target)
    row["politicalInfluence"] = _clamp(float(row.get("politicalInfluence") or 50) + amount)

    scores = world_state.setdefault("ruler_legitimacy_scores", {})
    scores[target] = _clamp(float(scores.get(target) or 50) + amount * 0.6)

    outcome = f"Player backed {target}'s claim (+{amount:.0f} influence)."

    cause = record_cause(
        world_state,
        domain="diplomacy",
        actor="Player",
        pressure=reason,
        decision="support_claimant",
        outcome=outcome,
        affected=["Player", target],
        severity=7,
        confidence=1.0,
        source="player",
    )

    record_fact(world_state, target, outcome, cause_id=cause["id"])
    for neighbor in _neighboring_factions(world_state, target):
        record_rumor(world_state, neighbor, f"Outside powers are backing {target}.", cause_id=cause["id"])

    return {"applied": True, "cause_id": cause["id"], "outcome": outcome}


def _impose_embargo(world_state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    """Apply trade sanctions against a faction."""
    target = str(action.get("target_faction") or "").strip()
    amount = min(float(action.get("amount") or 8), 15.0)
    reason = str(action.get("reason") or "player-imposed sanctions").strip()

    if not target:
        return {"error": "target_faction required"}

    row = _power_row(world_state, target)
    row["economicPower"] = _clamp(float(row.get("economicPower") or 50) - amount)

    outcome = f"Player imposed embargo on {target} (-{amount:.0f} economic power)."

    cause = record_cause(
        world_state,
        domain="economy",
        actor="Player",
        pressure=reason,
        decision="impose_embargo",
        outcome=outcome,
        affected=["Player", target],
        severity=8,
        confidence=1.0,
        source="player",
    )

    record_fact(world_state, target, outcome, cause_id=cause["id"])
    for row2 in world_state.get("faction_power_state") or []:
        if isinstance(row2, dict):
            f = str(row2.get("faction") or "")
            if f and f != target:
                record_fact(world_state, f, f"Player sanctioned {target}.", cause_id=cause["id"])

    return {"applied": True, "cause_id": cause["id"], "outcome": outcome}


_HANDLERS = {
    "send_aid": _send_aid,
    "spread_rumor": _spread_rumor,
    "fund_faction": _fund_faction,
    "reveal_secret": _reveal_secret,
    "support_claimant": _support_claimant,
    "impose_embargo": _impose_embargo,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_player_actions(world_state: dict[str, Any]) -> list[dict[str, Any]]:
    """Process all pending player actions then clear the queue.

    Call before pressure is computed so factions react this tick.
    Returns a list of result dicts (one per action attempted).
    """
    pending = world_state.get("pending_player_actions")
    if not isinstance(pending, list) or not pending:
        world_state["pending_player_actions"] = []
        return []

    results: list[dict[str, Any]] = []
    for action in pending:
        if not isinstance(action, dict):
            continue
        action_type = str(action.get("action") or "").strip()
        handler = _HANDLERS.get(action_type)
        if handler is None:
            results.append({"error": f"unknown action {action_type!r}", "action": action_type})
            continue
        try:
            result = handler(world_state, action)
            result["action"] = action_type
            results.append(result)
        except Exception as exc:
            results.append({"error": str(exc), "action": action_type})

    world_state["pending_player_actions"] = []
    world_state["last_player_actions"] = results
    return results


def queue_player_action(world_state: dict[str, Any], action: dict[str, Any]) -> int:
    """Append one action to the pending queue. Returns new queue length.

    Normalises the "type" key to "action" so callers can use either.
    """
    queue = world_state.setdefault("pending_player_actions", [])
    if not isinstance(queue, list):
        queue = []
        world_state["pending_player_actions"] = queue
    normalised = dict(action)
    if "action" not in normalised and "type" in normalised:
        normalised["action"] = normalised.pop("type")
    queue.append(normalised)
    return len(queue)
