"""Manual, human-operable master switch: restart/corruption cases A-I plus
the no-Claude-Code disaster-recovery demonstration (spec Sections 9-11).

Every test here uses an isolated tmp_path state file -- never
runtime/master_switch.json or reports/production/master_switch.json, the
real operator-facing files exercised separately by the live demonstration.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from production.master_switch import MasterSwitch


def _write_raw(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------- A/B


def test_case_a_switch_off_supervisor_runs_no_cycle(tmp_path):
    """Case A: switch = OFF, start supervisor -> NO production cycle."""
    from production.ea_registry import EAProductRegistry
    from production.evaluation_ledger import EvaluationLedger
    from production.supervisor import ProductionSupervisor

    switch = MasterSwitch(state_path=tmp_path / "switch.json", audit_path=tmp_path / "audit.json")
    switch.turn_off(reason="case A", source="test")

    calls = {"n": 0}

    class _CountingMachine:
        def load(self):
            pass

        def run_adaptive_search_cycle(self, **kwargs):
            calls["n"] += 1
            return {"ideas_generated": 0, "exploration_ideas": 0, "exploitation_ideas": 0,
                    "factory_evaluations": 0, "survivors": 0, "still_underpowered": 0,
                    "refuted_this_run": 0, "hypotheses": []}

    sup = ProductionSupervisor(
        machine=_CountingMachine(), switch=switch,
        evaluation_ledger=EvaluationLedger(path=tmp_path / "ledger.json"),
        ea_registry=EAProductRegistry(path=tmp_path / "registry.json"),
        heartbeat_path=tmp_path / "heartbeat.json", operation_log_path=tmp_path / "oplog.json",
    )
    summary = sup.run_forever(sleep_seconds=0)
    assert calls["n"] == 0
    assert summary["cycles_completed"] == 0


def test_case_b_switch_on_production_permitted(tmp_path):
    """Case B: switch = ON, start supervisor -> production permitted (at
    least one cycle runs)."""
    from production.ea_registry import EAProductRegistry
    from production.evaluation_ledger import EvaluationLedger
    from production.supervisor import ProductionSupervisor

    switch = MasterSwitch(state_path=tmp_path / "switch.json", audit_path=tmp_path / "audit.json")
    switch.turn_on(reason="case B", source="test")

    class _OneShotMachine:
        def load(self):
            pass

        def run_adaptive_search_cycle(self, **kwargs):
            return {"ideas_generated": 1, "exploration_ideas": 1, "exploitation_ideas": 0,
                    "factory_evaluations": 0, "survivors": 0, "still_underpowered": 0,
                    "refuted_this_run": 0, "hypotheses": []}

    sup = ProductionSupervisor(
        machine=_OneShotMachine(), switch=switch,
        evaluation_ledger=EvaluationLedger(path=tmp_path / "ledger.json"),
        ea_registry=EAProductRegistry(path=tmp_path / "registry.json"),
        heartbeat_path=tmp_path / "heartbeat.json", operation_log_path=tmp_path / "oplog.json",
    )
    summary = sup.run_forever(max_cycles=1, sleep_seconds=0)
    assert summary["cycles_completed"] == 1


# ----------------------------------------------------------------------- C


def test_case_c_off_mid_run_finishes_current_cycle_prevents_next(tmp_path):
    """Case C: switch = ON, cycle runs, switch flipped to OFF mid-cycle ->
    the in-progress bounded operation completes safely, the NEXT cycle does
    not start."""
    from production.ea_registry import EAProductRegistry
    from production.evaluation_ledger import EvaluationLedger
    from production.supervisor import ProductionSupervisor

    switch = MasterSwitch(state_path=tmp_path / "switch.json", audit_path=tmp_path / "audit.json")
    switch.turn_on(reason="case C", source="test")

    class _SelfStoppingMachine:
        def __init__(self, switch_ref):
            self._switch = switch_ref
            self.completed = 0

        def load(self):
            pass

        def run_adaptive_search_cycle(self, **kwargs):
            # Flip OFF partway "through" this cycle -- the cycle must still
            # finish and report normally; only the NEXT iteration is denied.
            self._switch.turn_off(reason="case C: operator stop mid-cycle", source="test")
            self.completed += 1
            return {"ideas_generated": 1, "exploration_ideas": 1, "exploitation_ideas": 0,
                    "factory_evaluations": 0, "survivors": 0, "still_underpowered": 0,
                    "refuted_this_run": 0, "hypotheses": []}

    machine = _SelfStoppingMachine(switch)
    sup = ProductionSupervisor(
        machine=machine, switch=switch,
        evaluation_ledger=EvaluationLedger(path=tmp_path / "ledger.json"),
        ea_registry=EAProductRegistry(path=tmp_path / "registry.json"),
        heartbeat_path=tmp_path / "heartbeat.json", operation_log_path=tmp_path / "oplog.json",
    )
    summary = sup.run_forever(max_cycles=10, sleep_seconds=0)
    assert machine.completed == 1, "the in-progress cycle must finish, not be aborted"
    assert summary["cycles_completed"] == 1, "no second cycle may start once OFF is observed"
    assert summary["master_switch"] == "OFF"


# --------------------------------------------------------------- D/E/F/G/H/I


def test_case_d_off_survives_restart(tmp_path):
    path = tmp_path / "switch.json"
    MasterSwitch(state_path=path, audit_path=tmp_path / "audit.json").turn_off(reason="d", source="test")
    fresh = MasterSwitch(state_path=path, audit_path=tmp_path / "audit.json")
    assert fresh.is_on() is False


def test_case_e_on_survives_restart(tmp_path):
    path = tmp_path / "switch.json"
    MasterSwitch(state_path=path, audit_path=tmp_path / "audit.json").turn_on(reason="e", source="test")
    fresh = MasterSwitch(state_path=path, audit_path=tmp_path / "audit.json")
    assert fresh.is_on() is True


def test_case_f_deleted_file_defaults_off(tmp_path):
    path = tmp_path / "switch.json"
    sw = MasterSwitch(state_path=path, audit_path=tmp_path / "audit.json")
    sw.turn_on(reason="f-setup", source="test")
    assert sw.is_on() is True
    path.unlink()
    assert sw.is_on() is False
    fresh = MasterSwitch(state_path=path, audit_path=tmp_path / "audit.json")
    assert fresh.is_on() is False


def test_case_g_corrupted_json_defaults_off(tmp_path):
    path = tmp_path / "switch.json"
    sw = MasterSwitch(state_path=path, audit_path=tmp_path / "audit.json")
    sw.turn_on(reason="g-setup", source="test")
    assert sw.is_on() is True
    _write_raw(path, "{ this is not json")
    assert sw.is_on() is False
    fresh = MasterSwitch(state_path=path, audit_path=tmp_path / "audit.json")
    assert fresh.is_on() is False


def test_case_h_manual_edit_to_true_then_restart_is_on(tmp_path):
    path = tmp_path / "switch.json"
    _write_raw(path, json.dumps({"enabled": True}))
    fresh = MasterSwitch(state_path=path, audit_path=tmp_path / "audit.json")
    assert fresh.is_on() is True
    state = fresh.current()
    assert state.source == "PERSISTED_STATE", "a bare hand-edit must never be attributed to the CLI"


def test_case_i_manual_edit_to_false_then_restart_is_off(tmp_path):
    path = tmp_path / "switch.json"
    _write_raw(path, json.dumps({"enabled": False}))
    fresh = MasterSwitch(state_path=path, audit_path=tmp_path / "audit.json")
    assert fresh.is_on() is False


# ------------------------------------------------------------- fail-safe

def test_never_infers_on_from_history_or_defaults(tmp_path):
    """Section 11: an audit trail full of ON records must NOT make a fresh
    read of a missing/corrupt state file come back ON -- only the
    authoritative file itself may grant permission."""
    state_path = tmp_path / "switch.json"
    audit_path = tmp_path / "audit.json"
    sw = MasterSwitch(state_path=state_path, audit_path=audit_path)
    for _ in range(5):
        sw.turn_on(reason="build history", source="test")
        sw.turn_off(reason="build history", source="test")
    sw.turn_on(reason="last known state is ON", source="test")
    assert sw.is_on() is True

    # Now destroy ONLY the authoritative file -- the rich ON-heavy audit
    # history must count for nothing.
    state_path.unlink()
    assert sw.is_on() is False
    fresh = MasterSwitch(state_path=state_path, audit_path=audit_path)
    assert fresh.is_on() is False
    assert len(fresh.history()) > 0, "audit history must still exist and be untouched"


# ------------------------------------------------------ disaster recovery


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_disaster_recovery_direct_file_edit_without_claude_code(tmp_path):
    """Section 10: simulate the real disaster-recovery scenario end to end
    -- "Claude Code unavailable -> human modifies master_switch.json ->
    AGLE supervisor starts -> AGLE reads persisted state -> AGLE obeys the
    human decision" -- using ONLY separate OS subprocess invocations of the
    REAL agle.py CLI (a fresh Python interpreter each time, nothing shared
    with this test process's memory) and plain os-level file writes standing
    in for a human's text editor. Nothing here imports or depends on Claude
    Code -- it isn't importable from this repo at all.
    """
    import os as _os

    state_path = tmp_path / "master_switch.json"
    env = {**_os.environ, "AGLE_SWITCH_STATE_PATH": str(state_path),
          "AGLE_SWITCH_AUDIT_PATH": str(tmp_path / "audit.json")}

    def run_cli(*args):
        return subprocess.run(
            [sys.executable, "agle.py", *args], cwd=str(REPO_ROOT),
            capture_output=True, text=True, env=env, timeout=30,
        )

    # Step 1: "Claude Code unavailable" -- a human, with only a text editor,
    # writes the switch file directly. No CLI, no library call.
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"enabled": True}), encoding="utf-8")

    # Step 2: "AGLE supervisor starts / reads persisted state" -- the REAL
    # CLI, in a brand-new OS process, is asked its state.
    result = run_cli("switch", "status")
    assert result.returncode == 0, result.stderr
    assert "State: ON" in result.stdout, result.stdout

    # Step 3: the human changes their mind, again by direct file edit only
    # (no CLI call).
    state_path.write_text(json.dumps({"enabled": False}), encoding="utf-8")
    result = run_cli("switch", "status")
    assert result.returncode == 0, result.stderr
    assert "State: OFF" in result.stdout, result.stdout

    # Step 4: a slipped keystroke corrupts the file -- the real CLI, in a
    # fresh process, must still fail safe to OFF, never crash, never grant
    # permission.
    state_path.write_text("{enabled: false", encoding="utf-8")
    result = run_cli("switch", "status")
    assert result.returncode == 0, result.stderr
    assert "State: OFF" in result.stdout, result.stdout

    # Step 5: the human deletes the file entirely -- same fail-safe outcome.
    state_path.unlink()
    result = run_cli("switch", "status")
    assert result.returncode == 0, result.stderr
    assert "State: OFF" in result.stdout, result.stdout

    # Step 6: and the CLI itself (still no Claude Code) can turn it back ON.
    result = run_cli("switch", "on")
    assert result.returncode == 0, result.stderr
    assert "Current:  ON" in result.stdout, result.stdout
    assert json.loads(state_path.read_text())["enabled"] is True
