"""Axiom Engine tick entrypoint."""

from engine._core import run_mechanical_tick as _run_mechanical_tick


def run_tick(world_state: dict, prev_world: dict = None) -> dict:
    """Execute one deterministic Axiom mechanical tick. No AI, no IO."""
    return _run_mechanical_tick(world_state, prev_world=prev_world)


__all__ = ["run_tick"]
