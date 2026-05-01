"""Deterministic long-run harness tests for the Axiom Engine.

No AI. No IO. Verifies the engine stays valid, bounded, and
causally consistent across 10 and 100 consecutive ticks.
"""

import json
from pathlib import Path

from axiom.engine.harness import print_summary, run_ticks

_FIXTURE = Path(__file__).parent / "fixtures" / "minimal_world.json"


def _world():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 10-tick run
# ---------------------------------------------------------------------------

def test_10_tick_run_advances_tick_correctly():
    summary = run_ticks(_world(), 10)
    assert summary["ticks_run"] == 10
    assert summary["final_tick"] == 10


def test_10_tick_run_no_validation_warnings():
    summary = run_ticks(_world(), 10)
    assert summary["warning_count"] == 0, (
        f"Unexpected validation warnings:\n{summary['warnings_by_tick']}"
    )


def test_10_tick_run_causality_ledger_bounded():
    summary = run_ticks(_world(), 10)
    assert summary["total_causality_records_in_ledger"] <= 250


def test_10_tick_run_autopsy_present_on_final_world():
    summary = run_ticks(_world(), 10)
    autopsy = summary["final_world"].get("last_tick_autopsy")
    assert isinstance(autopsy, dict), "last_tick_autopsy missing from final world"
    assert autopsy.get("tick") == 10


def test_10_tick_run_produces_summary_output(capsys):
    summary = run_ticks(_world(), 10)
    print_summary(summary)
    captured = capsys.readouterr()
    assert "Axiom Harness Run" in captured.out
    assert "10 ticks" in captured.out


# ---------------------------------------------------------------------------
# 100-tick run
# ---------------------------------------------------------------------------

def test_100_tick_run_advances_tick_correctly():
    summary = run_ticks(_world(), 100)
    assert summary["ticks_run"] == 100
    assert summary["final_tick"] == 100


def test_100_tick_run_no_validation_warnings():
    summary = run_ticks(_world(), 100)
    assert summary["warning_count"] == 0, (
        f"Unexpected validation warnings:\n{summary['warnings_by_tick']}"
    )


def test_100_tick_run_causality_ledger_stays_bounded():
    summary = run_ticks(_world(), 100)
    assert summary["total_causality_records_in_ledger"] <= 250


def test_100_tick_run_autopsy_present_on_final_world():
    summary = run_ticks(_world(), 100)
    autopsy = summary["final_world"].get("last_tick_autopsy")
    assert isinstance(autopsy, dict), "last_tick_autopsy missing from final world"
    assert autopsy.get("tick") == 100


def test_100_tick_run_generates_causality_records():
    summary = run_ticks(_world(), 100)
    assert summary["total_causality_records_in_ledger"] > 0, (
        "Expected some causality records after 100 ticks"
    )


def test_100_tick_run_world_date_matches_final_tick():
    summary = run_ticks(_world(), 100)
    world = summary["final_world"]
    assert world.get("world_date") == f"Day {world.get('tick')}"
