"""Faction power, war, territory, and rebellion helpers for the Axiom Engine."""

from engine._core import (
    _apply_power_shifts,
    _calculate_faction_power_dynamic,
    _compute_active_war_outcomes,
    _compute_faction_dominance,
    _compute_power_outcome_modifiers,
    _dominance_score,
    _merge_power_deltas,
    _normalize_faction_power_state,
    _plan_war_targets,
    _process_rebellions,
    _resolve_war_advantage,
    _resource_pressure,
    _territory_power_contribution,
    _update_location_control,
    _update_location_stability,
)

__all__ = [
    "_resource_pressure",
    "_territory_power_contribution",
    "_calculate_faction_power_dynamic",
    "_normalize_faction_power_state",
    "_compute_power_outcome_modifiers",
    "_resolve_war_advantage",
    "_compute_active_war_outcomes",
    "_apply_power_shifts",
    "_dominance_score",
    "_compute_faction_dominance",
    "_plan_war_targets",
    "_update_location_control",
    "_update_location_stability",
    "_process_rebellions",
    "_merge_power_deltas",
]
