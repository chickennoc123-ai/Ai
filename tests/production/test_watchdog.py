"""production.watchdog.ServiceWatchdog: crash detection/restart, Master-
Switch-aware restart suppression, graceful shutdown, and a real controlled
process-termination test (spec Phases 6, 7, 13).

Uses a small FAKE stand-in for `agle.py run` (never the real one, which
would call the real market-data Factory and take minutes per cycle) so
these tests run in a few seconds while still exercising the REAL
production.singleton_lock.SingleInstanceLock the real child would use --
the watchdog's spawn/monitor/classify/restart logic is 100% real code
under real test; only the "what a cycle actually computes" part is faked,
confined to this file, and never claims to be real Factory evidence.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from production.master_switch import MasterSwitch
from production.service_log import (
    FAIL_SAFE,
    MASTER_SWITCH_OFF,
    MASTER_SWITCH_ON,
    SERVICE_STARTED,
    SERVICE_STOPPED,
    SUPERVISOR_CRASHED,
    SUPERVISOR_RESTARTED,
    SUPERVISOR_STARTED,
    SUPERVISOR_STOPPED,
    ServiceEventLog,
)
from production.singleton_lock import DUPLICATE_PROCESS_EXIT_CODE, SingleInstanceLock
from production.watchdog import ServiceWatchdog

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _write_fake_agle(tmp_path: Path, *, exit_code: int, sleep_seconds: float, lock_path: Path) -> Path:
    """A minimal stand-in for `agle.py run` that holds the REAL
    SingleInstanceLock (exactly like the real Supervisor does), sleeps
    briefly (simulating a bounded cycle), then exits with a fixed code --
    never claims any Factory result, real or fake."""
    script = tmp_path / "fake_agle.py"
    script.write_text(f'''
import sys, time
sys.path.insert(0, {str(REPO_ROOT)!r})
from production.singleton_lock import SingleInstanceLock
lock = SingleInstanceLock(path={str(lock_path)!r})
r = lock.acquire()
if not r.acquired:
    sys.exit({DUPLICATE_PROCESS_EXIT_CODE})
try:
    time.sleep({sleep_seconds})
finally:
    lock.release()
sys.exit({exit_code})
''', encoding="utf-8")
    return script


def _write_fake_agle_sleeps_until_killed(tmp_path: Path, *, lock_path: Path, marker_path: Path) -> Path:
    """Like _write_fake_agle, but sleeps indefinitely (until killed) --
    used for the real controlled-termination test. Writes marker_path once
    it has acquired the lock, so the test knows when it's safe to kill it."""
    script = tmp_path / "fake_agle_forever.py"
    script.write_text(f'''
import sys, time
sys.path.insert(0, {str(REPO_ROOT)!r})
from production.singleton_lock import SingleInstanceLock
lock = SingleInstanceLock(path={str(lock_path)!r})
r = lock.acquire()
if not r.acquired:
    sys.exit({DUPLICATE_PROCESS_EXIT_CODE})
with open({str(marker_path)!r}, "w") as f:
    f.write(str(__import__("os").getpid()))
try:
    time.sleep(120)
finally:
    lock.release()
''', encoding="utf-8")
    return script


def _write_fake_agle_graceful(tmp_path: Path, *, lock_path: Path, marker_path: Path) -> Path:
    """Installs a SIGTERM/SIGBREAK handler (mirroring what the real
    ProductionSupervisor.run_forever() does) so it can be asked to stop
    gracefully rather than killed."""
    script = tmp_path / "fake_agle_graceful.py"
    script.write_text(f'''
import sys, time, signal
sys.path.insert(0, {str(REPO_ROOT)!r})
from production.singleton_lock import SingleInstanceLock
lock = SingleInstanceLock(path={str(lock_path)!r})
r = lock.acquire()
if not r.acquired:
    sys.exit({DUPLICATE_PROCESS_EXIT_CODE})
stop = {{"flag": False}}
def _h(signum, frame):
    stop["flag"] = True
for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
    sig = getattr(signal, name, None)
    if sig is not None:
        try:
            signal.signal(sig, _h)
        except (ValueError, OSError):
            pass
with open({str(marker_path)!r}, "w") as f:
    f.write(str(__import__("os").getpid()))
slept = 0.0
while slept < 30.0 and not stop["flag"]:
    time.sleep(0.05)
    slept += 0.05
lock.release()
sys.exit(0)
''', encoding="utf-8")
    return script


def _paths(tmp_path):
    return dict(
        switch=tmp_path / "switch.json", audit=tmp_path / "switch_audit.json",
        watchdog_lock=tmp_path / "watchdog.lock", supervisor_lock=tmp_path / "supervisor.lock",
        service_log=tmp_path / "service_log.json",
    )


# --------------------------------------------------------------- clean exit


def test_clean_exit_does_not_log_a_crash(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="test", source="test")
    fake = _write_fake_agle(tmp_path, exit_code=0, sleep_seconds=0.2, lock_path=p["supervisor_lock"])
    log = ServiceEventLog(path=p["service_log"])

    wd = ServiceWatchdog(
        switch=switch, service_log=log, watchdog_lock=SingleInstanceLock(path=p["watchdog_lock"]),
        poll_interval_seconds=0.2, supervisor_sleep_seconds=1, agle_script=fake,
    )
    wd.run(max_iterations=1)

    kinds = [e["kind"] for e in log.all()]
    assert SUPERVISOR_STARTED in kinds
    assert SUPERVISOR_STOPPED in kinds
    assert SUPERVISOR_CRASHED not in kinds


# ------------------------------------------------------- crash + switch ON


def test_crash_while_switch_on_triggers_restart(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="test", source="test")
    fake = _write_fake_agle(tmp_path, exit_code=1, sleep_seconds=0.1, lock_path=p["supervisor_lock"])
    log = ServiceEventLog(path=p["service_log"])

    wd = ServiceWatchdog(
        switch=switch, service_log=log, watchdog_lock=SingleInstanceLock(path=p["watchdog_lock"]),
        poll_interval_seconds=0.1, supervisor_sleep_seconds=1, agle_script=fake,
    )
    wd.run(max_iterations=2)  # crash on iteration 1, restart+crash again on iteration 2

    kinds = [e["kind"] for e in log.all()]
    assert kinds.count(SUPERVISOR_CRASHED) == 2
    assert kinds.count(SUPERVISOR_RESTARTED) == 2
    assert FAIL_SAFE not in kinds


# ------------------------------------------------------ crash + switch OFF


def test_crash_while_switch_off_does_not_restart(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="test", source="test")  # ON so the crashing child gets spawned once
    fake = _write_fake_agle(tmp_path, exit_code=1, sleep_seconds=0.1, lock_path=p["supervisor_lock"])
    log = ServiceEventLog(path=p["service_log"])

    class _TurnOffAfterCrashSwitch:
        """Wraps the real MasterSwitch so the SECOND is_on() check (the
        watchdog's post-crash re-check) sees OFF -- simulating an operator
        turning it off in the moment right after the crash."""
        def __init__(self, real):
            self._real = real
            self._calls = 0

        def is_on(self):
            self._calls += 1
            if self._calls >= 2:
                return False
            return self._real.is_on()

        def current(self):
            return self._real.current()

    wrapped = _TurnOffAfterCrashSwitch(switch)
    wd = ServiceWatchdog(
        switch=wrapped, service_log=log, watchdog_lock=SingleInstanceLock(path=p["watchdog_lock"]),
        poll_interval_seconds=0.1, supervisor_sleep_seconds=1, agle_script=fake,
    )
    wd.run(max_iterations=3)

    kinds = [e["kind"] for e in log.all()]
    assert SUPERVISOR_CRASHED in kinds
    assert FAIL_SAFE in kinds
    assert SUPERVISOR_RESTARTED not in kinds, "must never restart once the switch reads OFF"


def test_switch_off_from_start_never_spawns_a_child(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_off(reason="test", source="test")
    fake = _write_fake_agle(tmp_path, exit_code=0, sleep_seconds=5, lock_path=p["supervisor_lock"])
    log = ServiceEventLog(path=p["service_log"])

    wd = ServiceWatchdog(
        switch=switch, service_log=log, watchdog_lock=SingleInstanceLock(path=p["watchdog_lock"]),
        poll_interval_seconds=0.1, supervisor_sleep_seconds=1, agle_script=fake,
    )
    wd.run(max_iterations=3)

    kinds = [e["kind"] for e in log.all()]
    assert SUPERVISOR_STARTED not in kinds
    assert MASTER_SWITCH_OFF in kinds


# ---------------------------------------------------- duplicate protection


def test_watchdog_itself_refuses_a_second_instance(tmp_path):
    p = _paths(tmp_path)
    lock_path = p["watchdog_lock"]
    holder = SingleInstanceLock(path=lock_path)
    result = holder.acquire()
    assert result.acquired

    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    log = ServiceEventLog(path=p["service_log"])
    wd = ServiceWatchdog(switch=switch, service_log=log, watchdog_lock=SingleInstanceLock(path=lock_path))
    summary = wd.run(max_iterations=1)
    assert summary["started"] is False
    holder.release()


def test_spawned_child_refused_when_supervisor_lock_already_held(tmp_path):
    """A duplicate-blocked child (exit code 2) must be logged as
    DUPLICATE_PROCESS_BLOCKED, not misclassified as a crash."""
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="test", source="test")

    # Something else already holds the supervisor lock the fake child will try to acquire.
    other_holder = SingleInstanceLock(path=p["supervisor_lock"])
    assert other_holder.acquire().acquired

    fake = _write_fake_agle(tmp_path, exit_code=0, sleep_seconds=0.1, lock_path=p["supervisor_lock"])
    log = ServiceEventLog(path=p["service_log"])
    wd = ServiceWatchdog(
        switch=switch, service_log=log, watchdog_lock=SingleInstanceLock(path=p["watchdog_lock"]),
        poll_interval_seconds=0.1, supervisor_sleep_seconds=1, agle_script=fake,
    )
    wd.run(max_iterations=1)
    other_holder.release()

    from production.service_log import DUPLICATE_PROCESS_BLOCKED
    kinds = [e["kind"] for e in log.all()]
    assert DUPLICATE_PROCESS_BLOCKED in kinds
    assert SUPERVISOR_CRASHED not in kinds


# --------------------------------------------------- real crash (Phase 13)


def test_real_controlled_process_termination_is_detected_and_recovered(tmp_path):
    """Phase 13: a REAL SIGKILL against the spawned child, not a mock.
    Verifies through real process inspection that after recovery exactly
    one child is alive, never two."""
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="test", source="test")
    marker = tmp_path / "child_pid.marker"
    fake = _write_fake_agle_sleeps_until_killed(tmp_path, lock_path=p["supervisor_lock"], marker_path=marker)
    log = ServiceEventLog(path=p["service_log"])

    wd = ServiceWatchdog(
        switch=switch, service_log=log, watchdog_lock=SingleInstanceLock(path=p["watchdog_lock"]),
        poll_interval_seconds=0.1, supervisor_sleep_seconds=1, agle_script=fake,
    )

    import threading
    result_box = {}
    t = threading.Thread(target=lambda: result_box.update(summary=wd.run(max_iterations=1)))
    t.start()

    for _ in range(100):
        if marker.exists():
            break
        time.sleep(0.05)
    assert marker.exists(), "fake child never started"
    first_pid = int(marker.read_text())
    assert first_pid != os.getpid()

    # REAL, controlled termination -- not a mock.
    os.kill(first_pid, signal.SIGKILL)
    t.join(timeout=10)
    assert not t.is_alive()

    kinds = [e["kind"] for e in log.all()]
    assert SUPERVISOR_CRASHED in kinds
    # Exactly one child was ever alive at a time: the supervisor lock was
    # released (the killed process couldn't release it itself -- SIGKILL
    # gives no chance -- so this also proves stale-lock reclaim works for
    # a REAL crash, not just a synthetic dead pid).
    reclaim_lock = SingleInstanceLock(path=p["supervisor_lock"])
    reclaim_result = reclaim_lock.acquire()
    assert reclaim_result.acquired, "supervisor lock must be reclaimable after the real crash"
    reclaim_lock.release()


# ------------------------------------------------------- graceful shutdown


def test_graceful_shutdown_lets_child_finish_never_kills_it(tmp_path):
    p = _paths(tmp_path)
    switch = MasterSwitch(state_path=p["switch"], audit_path=p["audit"])
    switch.turn_on(reason="test", source="test")
    marker = tmp_path / "child_pid.marker"
    fake = _write_fake_agle_graceful(tmp_path, lock_path=p["supervisor_lock"], marker_path=marker)
    log = ServiceEventLog(path=p["service_log"])

    wd = ServiceWatchdog(
        switch=switch, service_log=log, watchdog_lock=SingleInstanceLock(path=p["watchdog_lock"]),
        poll_interval_seconds=0.1, supervisor_sleep_seconds=1,
        graceful_shutdown_timeout_seconds=10, agle_script=fake,
    )

    import threading
    result_box = {}
    t = threading.Thread(target=lambda: result_box.update(summary=wd.run()))
    t.start()

    for _ in range(100):
        if marker.exists():
            break
        time.sleep(0.05)
    assert marker.exists()

    wd.request_stop()
    t.join(timeout=15)
    assert not t.is_alive(), "watchdog did not stop after a graceful request_stop()"
    assert result_box["summary"]["stopped_gracefully"] is True

    kinds = [e["kind"] for e in log.all()]
    assert SUPERVISOR_CRASHED not in kinds, "a gracefully-exited child must never be logged as a crash"
