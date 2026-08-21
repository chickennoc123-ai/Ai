"""AGLE HEALTH: real, observational-only live health check (16 required cases).

Every test uses isolated tmp_path files for the switch/heartbeat/operation
log/evaluation ledger/EA registry -- never runtime/master_switch.json or
reports/production/*.json, the real files exercised separately by the live
demonstration. check_health() itself is read-only and this suite never
calls anything that starts a process, changes a switch, or writes to
production state -- consistent with the "observational only" safety rule
under test.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from production.ea_registry import EAProductRegistry
from production.evaluation_ledger import EvaluationLedger
from production.health import check_health, render_health_text
from production.master_switch import MasterSwitch

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _paths(tmp_path):
    return dict(
        switch=tmp_path / "switch.json", audit=tmp_path / "switch_audit.json",
        heartbeat=tmp_path / "heartbeat.json", oplog=tmp_path / "oplog.json",
        ledger=tmp_path / "ledger.json", registry=tmp_path / "registry.json",
    )


def _write_heartbeat(path: Path, *, pid: int, state: str = "IDLE",
                     timestamp: str = None, last_error=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "pid": pid, "state": state, "master_switch": "ON",
        "cycles_completed": 1, "consecutive_failures": 0, "last_error": last_error,
    }), encoding="utf-8")


def _write_oplog(path: Path, cycles: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cycles": cycles}), encoding="utf-8")


def _cycle(cycle_id, ended_at, *, survivors=0, ea_products_created=0, errors=None):
    return {
        "cycle_id": cycle_id, "started_at": ended_at, "ended_at": ended_at,
        "ideas": 1, "hypotheses": 1, "factory_evaluations": 1,
        "survivors": survivors, "still_underpowered": 0, "refuted": 0,
        "ea_products_created": ea_products_created, "errors": errors or [], "recovery_events": [],
    }


# --------------------------------------------------------- 1: ON + RUNNING


def test_case_1_switch_on_supervisor_running(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="case1", source="test")

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(6)", "agle.py"])
    try:
        time.sleep(0.3)
        _write_heartbeat(p["heartbeat"], pid=proc.pid, state="IDLE")
        report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                              operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                              ea_registry_path=p["registry"])
        assert report.master_switch_state == "ON"
        assert report.supervisor_state == "RUNNING"
        assert report.supervisor_pid == proc.pid
        assert report.current_state == "IDLE"
        assert report.overall == "HEALTHY"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


# --------------------------------------------------------------- 2: OFF


def test_case_2_switch_off(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_off(reason="case2", source="test")
    report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                          operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                          ea_registry_path=p["registry"])
    assert report.master_switch_state == "OFF"
    # Section 9 of the 24/7 operations spec: an intentional OFF is a safe,
    # correct state, never a failure -- SAFE / IDLE, not ATTENTION REQUIRED.
    assert report.overall == "SAFE / IDLE"


# ------------------------------------------------- 3: supervisor stopped, ON


def test_case_3_supervisor_stopped_while_switch_on(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="case3", source="test")
    # A pid that (almost certainly) does not correspond to a live process.
    _write_heartbeat(p["heartbeat"], pid=999999)
    report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                          operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                          ea_registry_path=p["registry"])
    assert report.master_switch_state == "ON"
    assert report.supervisor_state == "STOPPED"
    assert report.supervisor_pid is None
    assert report.current_state == "STOPPED"
    assert report.overall == "ATTENTION REQUIRED"


def test_case_3b_pid_alive_but_not_agle_never_false_positive(tmp_path):
    """A live PID whose cmdline does NOT mention agle.py (PID reuse by an
    unrelated process) must NOT be reported RUNNING."""
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="case3b", source="test")
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(6)"])
    try:
        time.sleep(0.3)
        _write_heartbeat(p["heartbeat"], pid=proc.pid)
        report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                              operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                              ea_registry_path=p["registry"])
        assert report.supervisor_state == "STOPPED"
        assert report.supervisor_pid is None
    finally:
        proc.terminate()
        proc.wait(timeout=5)


# ------------------------------------------------- 4/5: missing/corrupt switch


def test_case_4_missing_switch_file_fail_safe_off(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])  # never written
    report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                          operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                          ea_registry_path=p["registry"])
    assert report.master_switch_state == "OFF"
    # Section 9 of the 24/7 operations spec: an intentional OFF is a safe,
    # correct state, never a failure -- SAFE / IDLE, not ATTENTION REQUIRED.
    assert report.overall == "SAFE / IDLE"


def test_case_5_corrupt_switch_file_fail_safe_off(tmp_path):
    p = _paths(tmp_path)
    p["switch"].parent.mkdir(parents=True, exist_ok=True)
    p["switch"].write_text("{ not json", encoding="utf-8")
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                          operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                          ea_registry_path=p["registry"])
    assert report.master_switch_state == "OFF"
    # Section 9 of the 24/7 operations spec: an intentional OFF is a safe,
    # correct state, never a failure -- SAFE / IDLE, not ATTENTION REQUIRED.
    assert report.overall == "SAFE / IDLE"


# --------------------------------------------------------- 6: no cycles yet


def test_case_6_no_cycles_yet(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="case6", source="test")
    report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                          operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                          ea_registry_path=p["registry"])
    assert report.last_cycle_at == "N/A"
    assert report.last_cycle_result == "N/A"
    assert report.last_factory_run_at == "N/A"
    assert report.cycles_today == 0
    assert "no completed production cycle recorded yet" in report.notes


# ------------------------------------------------------- 7/8: real cycle data


def test_case_7_8_real_completed_cycle_and_result(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="case7", source="test")
    now = datetime.now(timezone.utc)
    ended = now.isoformat()
    _write_oplog(p["oplog"], [_cycle("CYCLE-A", ended)])
    report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                          operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                          ea_registry_path=p["registry"], now=now)
    assert report.last_cycle_at == ended
    assert report.last_cycle_result == "NO_EDGE_FOUND"


@pytest.mark.parametrize("survivors,ea_created,errors,expected", [
    (0, 0, None, "NO_EDGE_FOUND"),
    (1, 0, None, "SURVIVOR_FOUND_NOT_PRODUCTIZED"),
    (1, 1, None, "EA_PRODUCT_CREATED"),
    (0, 0, ["boom"], "ERROR"),
])
def test_case_8_result_derivation(tmp_path, survivors, ea_created, errors, expected):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="case8", source="test")
    now = datetime.now(timezone.utc)
    _write_oplog(p["oplog"], [_cycle("CYCLE-B", now.isoformat(), survivors=survivors,
                                     ea_products_created=ea_created, errors=errors)])
    report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                          operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                          ea_registry_path=p["registry"], now=now)
    assert report.last_cycle_result == expected


# ----------------------------------------------------- 9: cycles today only


def test_case_9_cycles_today_excludes_yesterday(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="case9", source="test")
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    _write_oplog(p["oplog"], [
        _cycle("CYCLE-YESTERDAY", yesterday.isoformat()),
        _cycle("CYCLE-TODAY-1", now.isoformat()),
        _cycle("CYCLE-TODAY-2", now.isoformat()),
    ])
    report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                          operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                          ea_registry_path=p["registry"], now=now)
    assert report.cycles_today == 2


# ------------------------------------------------------------ 10: errors


def test_case_10_errors_today_from_logged_cycle_errors(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="case10a", source="test")
    now = datetime.now(timezone.utc)
    _write_oplog(p["oplog"], [_cycle("CYCLE-ERR", now.isoformat(), errors=["real error 1", "real error 2"])])
    report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                          operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                          ea_registry_path=p["registry"], now=now)
    assert report.errors_today == 2
    assert report.errors_today_is_floor is False


def test_case_10b_no_edge_found_and_off_are_never_counted_as_errors(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_off(reason="case10b", source="test")  # normal OFF, not an error
    now = datetime.now(timezone.utc)
    _write_oplog(p["oplog"], [_cycle("CYCLE-CLEAN", now.isoformat())])  # NO_EDGE_FOUND, no errors
    report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                          operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                          ea_registry_path=p["registry"], now=now)
    assert report.errors_today == 0


def test_case_10c_heartbeat_last_error_counted_as_floor(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="case10c", source="test")
    now = datetime.now(timezone.utc)
    _write_heartbeat(p["heartbeat"], pid=999999, state="DEGRADED",
                     timestamp=now.isoformat(), last_error="RuntimeError: simulated")
    report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                          operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                          ea_registry_path=p["registry"], now=now)
    assert report.errors_today >= 1
    assert report.errors_today_is_floor is True


# ---------------------------------------------------- 11: governance safety


def test_case_11_governance_failure_never_healthy(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="case11", source="test")
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(6)", "agle.py"])
    try:
        time.sleep(0.3)
        _write_heartbeat(p["heartbeat"], pid=proc.pid, state="IDLE")

        # Build a valid ledger, then tamper with its on-disk checksum to
        # force a genuine integrity failure -- proving governance can
        # actually go non-PASS, not just always reporting PASS.
        ledger = EvaluationLedger(path=p["ledger"])
        ledger.record(mechanism="m", instrument="EURUSD", driver=None, window_min=60,
                      hyp_id="H1", cycle_id="C1", verdict="V", final_status="REFUTED_THIS_RUN",
                      train={}, validation={})
        raw = json.loads(p["ledger"].read_text())
        raw["checksum"] = "tampered"
        p["ledger"].write_text(json.dumps(raw), encoding="utf-8")

        report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                              operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                              ea_registry_path=p["registry"])
        assert report.governance_state != "PASS"
        assert report.overall == "ATTENTION REQUIRED"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


# ----------------------------------------------------------------- 12: CLI


def test_case_12_cli_health_command(tmp_path):
    result = subprocess.run([sys.executable, "agle.py", "health"], cwd=str(REPO_ROOT),
                            capture_output=True, text=True, timeout=30)
    assert "AGLE HEALTH" in result.stdout
    assert "MASTER SWITCH" in result.stdout
    assert "OVERALL" in result.stdout
    assert result.returncode in (0, 1)  # never crashes; 0=healthy, 1=attention


def test_case_12b_cli_health_json(tmp_path):
    result = subprocess.run([sys.executable, "agle.py", "health", "--json"], cwd=str(REPO_ROOT),
                            capture_output=True, text=True, timeout=30)
    # stdout may carry INFO/WARNING log lines ahead of the JSON block --
    # find the JSON object rather than assuming stdout is pure JSON.
    start = result.stdout.index("{")
    payload = json.loads(result.stdout[start:])
    assert "overall" in payload
    assert "master_switch" in payload


# ---------------------------------------------------- 13: Windows launcher


def test_case_13_windows_launcher_points_to_real_cli():
    bat = REPO_ROOT / "AGLE_HEALTH.bat"
    assert bat.exists()
    text = bat.read_text(encoding="utf-8")
    assert "python agle.py health" in text
    # No GUI/web toolkit references -- stays a thin launcher.
    assert "tkinter" not in text.lower()
    assert "http" not in text.lower()


# ------------------------------------------------- 14: no fabricated values


def test_case_14_no_fabricated_values_when_everything_absent(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])  # OFF by fail-safe
    report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                          operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                          ea_registry_path=p["registry"])
    assert report.supervisor_pid is None
    assert report.last_cycle_at == "N/A"
    assert report.last_factory_run_at == "N/A"
    assert report.last_ea_product == "NONE"
    assert report.last_ea_product_created_at == "N/A"
    assert report.last_ea_product_path == "N/A"


# --------------------------------------------------------- 15: EA product


def test_case_15_ea_product_status_reported(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="case15", source="test")
    registry = EAProductRegistry(path=p["registry"])
    row = registry.register(candidate_id="CAND-1", hypothesis_id="HYP-1", factory_evaluation_id="EVAL-1",
                            spec_hash="deadbeef", source="test", artifact_path="reports/production/ea_products/CAND-1")
    report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                          operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                          ea_registry_path=p["registry"])
    assert report.last_ea_product == "CAND-1"
    assert report.last_ea_product_created_at == row["created_at"]
    assert report.last_ea_product_path == "reports/production/ea_products/CAND-1"


# ----------------------------------------------------- 16: honest notification


def test_case_16_notification_never_claims_sent(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="case16", source="test")
    EAProductRegistry(path=p["registry"]).register(
        candidate_id="CAND-2", hypothesis_id="H", factory_evaluation_id="E",
        spec_hash="feedbead", source="test", artifact_path="x",
    )
    report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                          operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                          ea_registry_path=p["registry"])
    assert report.ea_product_notification == "NOT IMPLEMENTED"
    assert "SENT" not in report.ea_product_notification


# --------------------------------------------------------------- rendering


def test_render_text_matches_requested_layout(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="render", source="test")
    report = check_health(switch=switch, heartbeat_path=p["heartbeat"],
                          operation_log_path=p["oplog"], evaluation_ledger_path=p["ledger"],
                          ea_registry_path=p["registry"])
    text = render_health_text(report)
    assert "AGLE HEALTH" in text
    assert "MASTER SWITCH" in text
    assert "OVERALL" in text


# ---------------------------------------------------- safety: observational


def test_health_never_writes_to_the_switch_file(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="safety", source="test")
    before = p["switch"].read_bytes()
    for _ in range(5):
        check_health(switch=switch, heartbeat_path=p["heartbeat"], operation_log_path=p["oplog"],
                    evaluation_ledger_path=p["ledger"], ea_registry_path=p["registry"])
    assert p["switch"].read_bytes() == before


def test_health_never_creates_heartbeat_or_oplog_files(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="safety2", source="test")
    check_health(switch=switch, heartbeat_path=p["heartbeat"], operation_log_path=p["oplog"],
                evaluation_ledger_path=p["ledger"], ea_registry_path=p["registry"])
    assert not p["heartbeat"].exists()
    assert not p["oplog"].exists()
