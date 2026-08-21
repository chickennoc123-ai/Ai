"""The AGLE watchdog: keeps a Supervisor process alive, Master-Switch-aware.

This is the "process availability" layer -- distinct from, and never a
substitute for, the Master Switch (production permission) or the
Supervisor (production orchestration). See the module docstring philosophy
repeated throughout production/: Windows Service/watchdog = process
availability, Master Switch = production permission, Supervisor =
production orchestration, Factory = scientific evaluation. This module
owns exactly the first one.

The watchdog does NOT run the production loop in-process. It spawns
`python agle.py run` as a CHILD process and monitors it, because a real
crash test (a controlled process termination) can only be recovered from
by something OUTSIDE the crashed process -- an in-process try/except
cannot catch its own SIGKILL. The child, in turn, is the one and only
thing that ever acquires production.singleton_lock's supervisor lock (see
production/supervisor.py); the watchdog itself acquires a SEPARATE lock
(its own single-instance protection, so two watchdogs can't race to spawn
two children) but never bypasses the supervisor lock to spawn a second
child while one is already alive -- the child's own lock acquisition is
what actually prevents that, structurally, even if this watchdog had a
bug.

Crash-recovery contract (spec Phases 6-7):
  - Master Switch ON, child crashes  -> re-check the switch; still ON ->
    restart exactly one child. This is a bounded, switch-gated restart,
    never a restart storm: each restart re-reads the switch fresh.
  - Master Switch OFF, child exits (or was never started) -> remain idle,
    poll, never restart. A child that exits because the switch went OFF
    mid-run is NOT a crash -- see _classify_exit().
  - Graceful shutdown (SIGTERM/SIGINT to the watchdog) -> stop spawning
    new children; if a child is alive, send it the same graceful signal
    (production/supervisor.py's run_forever() already handles SIGTERM/
    SIGINT by finishing the current cycle then exiting, never killing an
    active evaluation) and wait for it, bounded by a generous timeout.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from production.master_switch import MasterSwitch
from production.service_log import (
    DUPLICATE_PROCESS_BLOCKED,
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

REPO_ROOT = Path(__file__).resolve().parent.parent
AGLE_SCRIPT = REPO_ROOT / "agle.py"

DEFAULT_WATCHDOG_LOCK_PATH = Path(os.environ.get("AGLE_WATCHDOG_LOCK_PATH", "runtime/agle_watchdog.lock"))

DEFAULT_POLL_INTERVAL_SECONDS = 10.0
DEFAULT_SUPERVISOR_SLEEP_SECONDS = 60.0
DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 600.0  # generous -- a real cycle can take minutes; never kill it early


class ServiceWatchdog:
    def __init__(
        self,
        *,
        switch: Optional[MasterSwitch] = None,
        service_log: Optional[ServiceEventLog] = None,
        watchdog_lock: Optional[SingleInstanceLock] = None,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        supervisor_sleep_seconds: float = DEFAULT_SUPERVISOR_SLEEP_SECONDS,
        graceful_shutdown_timeout_seconds: float = DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
        python_executable: str = sys.executable,
        agle_script: Path = AGLE_SCRIPT,
    ) -> None:
        self.switch = switch or MasterSwitch()
        self.service_log = service_log or ServiceEventLog()
        self.watchdog_lock = watchdog_lock or SingleInstanceLock(path=DEFAULT_WATCHDOG_LOCK_PATH)
        self.poll_interval_seconds = poll_interval_seconds
        self.supervisor_sleep_seconds = supervisor_sleep_seconds
        self.graceful_shutdown_timeout_seconds = graceful_shutdown_timeout_seconds
        self.python_executable = python_executable
        self.agle_script = agle_script
        self._stop_requested = False
        self._child: Optional[subprocess.Popen] = None

    # ------------------------------------------------------------ shutdown

    def request_stop(self) -> None:
        """Ask the watchdog to stop cleanly: no new child will be spawned,
        and any live child is asked (not forced) to finish its current
        cycle and exit -- see module docstring."""
        self._stop_requested = True
        if self._child is not None and self._child.poll() is None:
            self._terminate_child_gracefully(self._child)

    def _terminate_child_gracefully(self, child: subprocess.Popen) -> None:
        """Ask, don't force. On POSIX, Popen.terminate() sends SIGTERM,
        which production.supervisor.ProductionSupervisor.run_forever()
        catches and turns into "finish this cycle, then stop." On Windows,
        Popen.terminate() calls TerminateProcess() -- an UNCONDITIONAL,
        un-catchable kill that would abort an active evaluation, exactly
        what Phase 7 forbids -- so there we send CTRL_BREAK_EVENT instead
        (requires the child to have been spawned with
        CREATE_NEW_PROCESS_GROUP, see _spawn_child()), which Python
        delivers to the child as SIGBREAK, catchable the same way."""
        try:
            if sys.platform == "win32":
                import signal as _signal
                os.kill(child.pid, _signal.CTRL_BREAK_EVENT)
            else:
                child.terminate()
        except OSError:
            pass

    def _install_signal_handlers(self) -> None:
        import signal

        def _handler(signum, frame):  # noqa: ARG001
            self.request_stop()

        for sig_name in ("SIGTERM", "SIGINT", "SIGBREAK"):
            sig = getattr(signal, sig_name, None)
            if sig is not None:
                try:
                    signal.signal(sig, _handler)
                except (ValueError, OSError):
                    pass

    # --------------------------------------------------------------- child

    def _spawn_child(self) -> subprocess.Popen:
        kwargs: Dict[str, Any] = {"cwd": str(REPO_ROOT)}
        if sys.platform == "win32":
            # Own process group so CTRL_BREAK_EVENT can be targeted at this
            # child specifically (without it, the signal would also hit
            # this watchdog process, since Windows console signals are
            # delivered to the whole group by default).
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        return subprocess.Popen(
            [self.python_executable, str(self.agle_script), "run",
             "--sleep-seconds", str(self.supervisor_sleep_seconds)],
            **kwargs,
        )

    def _wait_for_child(self, child: subprocess.Popen) -> int:
        """Poll rather than a blocking wait(), so a stop request arriving
        mid-wait is noticed promptly instead of only after the child exits."""
        while True:
            code = child.poll()
            if code is not None:
                return code
            if self._stop_requested:
                self._terminate_child_gracefully(child)
                try:
                    return child.wait(timeout=self.graceful_shutdown_timeout_seconds)
                except subprocess.TimeoutExpired:
                    return child.wait()  # already asked nicely; block until it actually exits
            time.sleep(min(1.0, self.poll_interval_seconds))

    @staticmethod
    def _classify_exit(exit_code: int) -> str:
        if exit_code == DUPLICATE_PROCESS_EXIT_CODE:
            return "duplicate_blocked"
        if exit_code == 0:
            return "clean"
        return "crashed"

    # ---------------------------------------------------------------- main

    def run(self, *, max_iterations: Optional[int] = None) -> Dict[str, Any]:
        """The watchdog's own loop. Acquires its own single-instance lock
        (separate resource from the supervisor's) so two watchdogs cannot
        race to spawn two children. Returns a summary dict; never fabricates
        cycle results -- everything reported here is about PROCESS
        lifecycle, never about what the Factory found."""
        lock_result = self.watchdog_lock.acquire()
        if not lock_result.acquired:
            self.service_log.record(DUPLICATE_PROCESS_BLOCKED,
                                    detail=f"watchdog already running (pid {lock_result.holder_pid})")
            return {"started": False, "reason": lock_result.reason, "holder_pid": lock_result.holder_pid}

        self._install_signal_handlers()
        self.service_log.record(SERVICE_STARTED, pid=None)
        iterations = 0
        was_on_last_poll = None
        try:
            while not self._stop_requested:
                if max_iterations is not None and iterations >= max_iterations:
                    break
                iterations += 1

                is_on = self.switch.is_on()
                if is_on != was_on_last_poll:
                    self.service_log.record(MASTER_SWITCH_ON if is_on else MASTER_SWITCH_OFF)
                    was_on_last_poll = is_on

                if not is_on:
                    self._sleep_interruptible(self.poll_interval_seconds)
                    continue

                child = self._spawn_child()
                self._child = child
                self.service_log.record(SUPERVISOR_STARTED, pid=child.pid)

                exit_code = self._wait_for_child(child)
                self._child = None

                if self._stop_requested:
                    self.service_log.record(SUPERVISOR_STOPPED, pid=child.pid,
                                            detail="graceful shutdown: child asked to stop, watchdog exiting")
                    break

                outcome = self._classify_exit(exit_code)
                if outcome == "clean":
                    # The child's own run_forever() only returns 0 when the
                    # switch went OFF, max_cycles/failure-bound was hit, or
                    # it was gracefully asked to stop -- never a crash.
                    self.service_log.record(SUPERVISOR_STOPPED, pid=child.pid,
                                            detail=f"child exited cleanly (code {exit_code})")
                elif outcome == "duplicate_blocked":
                    self.service_log.record(
                        DUPLICATE_PROCESS_BLOCKED, pid=child.pid,
                        detail="spawned child refused: another supervisor already held the lock",
                    )
                    self._sleep_interruptible(self.poll_interval_seconds)
                else:  # crashed
                    self.service_log.record(SUPERVISOR_CRASHED, pid=child.pid,
                                            detail=f"child exited with code {exit_code}")
                    if self.switch.is_on():
                        self.service_log.record(SUPERVISOR_RESTARTED,
                                                detail="master switch still ON, restarting on next iteration")
                        # loop continues -> respawns immediately on the next
                        # pass (still bounded: max_iterations, or the
                        # spawned child's OWN max_consecutive_failures if
                        # the crash is a repeated, immediate one).
                    else:
                        self.service_log.record(
                            FAIL_SAFE, detail="master switch OFF after crash -- remaining idle, no restart loop",
                        )
                        self._sleep_interruptible(self.poll_interval_seconds)
        finally:
            self.service_log.record(SERVICE_STOPPED, pid=None)
            self.watchdog_lock.release()

        return {"started": True, "iterations": iterations, "stopped_gracefully": self._stop_requested}

    def _sleep_interruptible(self, seconds: float) -> None:
        slept = 0.0
        slice_s = min(1.0, seconds) if seconds > 0 else 0.0
        while slept < seconds and not self._stop_requested:
            time.sleep(slice_s if seconds - slept >= slice_s else seconds - slept)
            slept += slice_s if slice_s > 0 else seconds

    def status(self) -> Dict[str, Any]:
        """Read-only: is a watchdog currently alive, per the lock file.
        Uses ONLY is_pid_alive() -- the same authoritative definition
        SingleInstanceLock.acquire() itself uses -- so this can never
        disagree with what an actual acquire attempt would decide."""
        from production.process_utils import is_pid_alive

        if not self.watchdog_lock.path.exists():
            return {"running": False, "pid": None}
        holder = self.watchdog_lock._read_holder()
        if holder is None:
            return {"running": False, "pid": None}
        pid, _started = holder
        alive = is_pid_alive(pid)
        return {"running": alive, "pid": pid if alive else None}
