"""24/7 Supervisor: heartbeat, bounded retry, and the production loop.

Owns the ON/OFF-aware continuous loop:

    while master_switch.is_on():
        recover_state()          # nothing to actively resume -- see note below
        check_governance()       # static audit + master switch re-check
        run_one_cycle()          # AutonomousIdeaMachine.run_adaptive_search_cycle,
                                  #   idempotency-guarded via EvaluationLedger
        maybe_productize()       # only for a real DISCOVERY_SURVIVOR this cycle
        persist_state()          # every ledger touched already wrote atomically
        heartbeat()
        sleep_until_next_job()

Crash recovery model: this loop has no per-cycle checkpoint of its own to
resume mid-function -- AutonomousIdeaMachine.run_adaptive_search_cycle() is
one Python call. Resumability instead comes from the EvaluationLedger: every
real Factory evaluation is persisted immediately after it runs (see
idea_machine/autonomous_loop.py's evaluation_ledger.record() call), so if
the process is killed mid-cycle, the NEXT cycle (this one retried, or a
fresh one proposing an overlapping candidate) finds already-evaluated
triples in the ledger and skips re-running the real gate() for them --
never a duplicate real evaluation. The one disclosed narrow window: a crash
between a STILL_UNDERPOWERED candidate's OpportunityQueue.append() and its
EvaluationLedger.record() (a few lines apart, not atomic across the two
files) could produce a duplicate OpportunityQueue entry on retry -- the same
class of disclosed, real, harmless duplication already documented for
Cycle 15's OPP-000069/070/071 (append-only ledgers cannot un-append, and the
duplicate is real, correctly-computed evidence, not a fabrication).

Bounded retry: `max_consecutive_failures` (default 3) stops the loop rather
than restarting forever -- an unbounded restart-on-failure loop would be
indistinguishable from a hung process quietly burning the real event
calendar / M1 data on every retry. A GovernanceViolation is NEVER caught
here (it is not caught anywhere in this codebase, per design) -- it
propagates and stops the loop immediately, unconditionally, regardless of
the failure counter.
"""

from __future__ import annotations

import os
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from idea_machine.autonomous_loop import AutonomousIdeaMachine
from idea_machine.core.errors import GovernanceViolation
from idea_machine.governance import guard

from production.ea_registry import EAProductRegistry
from production.evaluation_ledger import EvaluationLedger
from production.master_switch import MasterSwitch
from production.productization import maybe_productize
from production.singleton_lock import DuplicateProcessError, SingleInstanceLock

DEFAULT_HEARTBEAT_PATH = Path("reports/production/heartbeat.json")
DEFAULT_OPERATION_LOG_PATH = Path("reports/production/operation_log.json")

DEFAULT_MAX_CONSECUTIVE_FAILURES = 3
DEFAULT_SLEEP_SECONDS = 60


@dataclass
class CycleReport:
    cycle_id: str
    started_at: str
    ended_at: str = ""
    ideas: int = 0
    hypotheses: int = 0
    factory_evaluations: int = 0
    survivors: int = 0
    still_underpowered: int = 0
    refuted: int = 0
    ea_products_created: int = 0
    errors: List[str] = field(default_factory=list)
    recovery_events: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id, "started_at": self.started_at, "ended_at": self.ended_at,
            "ideas": self.ideas, "hypotheses": self.hypotheses,
            "factory_evaluations": self.factory_evaluations, "survivors": self.survivors,
            "still_underpowered": self.still_underpowered, "refuted": self.refuted,
            "ea_products_created": self.ea_products_created, "errors": self.errors,
            "recovery_events": self.recovery_events,
        }


class ProductionSupervisor:
    def __init__(
        self,
        *,
        machine: Optional[AutonomousIdeaMachine] = None,
        switch: Optional[MasterSwitch] = None,
        evaluation_ledger: Optional[EvaluationLedger] = None,
        ea_registry: Optional[EAProductRegistry] = None,
        heartbeat_path: Path = DEFAULT_HEARTBEAT_PATH,
        operation_log_path: Path = DEFAULT_OPERATION_LOG_PATH,
        max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
        lock: Optional[SingleInstanceLock] = None,
    ) -> None:
        self.machine = machine or AutonomousIdeaMachine()
        self.switch = switch or MasterSwitch()
        self.evaluation_ledger = evaluation_ledger or EvaluationLedger()
        self.ea_registry = ea_registry or EAProductRegistry()
        self.heartbeat_path = heartbeat_path
        self.operation_log_path = operation_log_path
        self.max_consecutive_failures = max_consecutive_failures
        # The single-instance mutex: acquired once per run_forever()/
        # run_one_cycle() call (never nested -- see the two call sites
        # below), so a manual `agle.py run`, a manual `agle.py cycle`, and
        # a watchdog-spawned child can never execute a production loop
        # concurrently, regardless of which one gets there first.
        self.lock = lock or SingleInstanceLock()
        self.cycles_completed = 0
        self.consecutive_failures = 0
        self.last_error: Optional[str] = None
        self.state = "STOPPED"  # STOPPED | LOADING | FACTORY_EVALUATION | IDLE | DEGRADED
        self._cycle_seq = 0

    # ------------------------------------------------------------- health

    def heartbeat(self) -> Dict[str, Any]:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(),
            "state": self.state, "master_switch": self.switch.current().state,
            "cycles_completed": self.cycles_completed,
            "consecutive_failures": self.consecutive_failures, "last_error": self.last_error,
        }
        self._atomic_write(self.heartbeat_path, payload)
        return payload

    @staticmethod
    def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
        import json
        import tempfile

        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, default=str)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def check_governance(self) -> None:
        """Re-verify the static source-tree audit before every cycle. Any
        GovernanceViolation here propagates unconditionally -- never caught,
        never converted into a retry."""
        findings = guard.audit_source_tree()
        if findings:
            raise GovernanceViolation(
                "static governance audit failed before a production cycle",
                findings=[f"{f.file}:{f.line} {f.kind}: {f.detail}" for f in findings],
            )

    def recover_state(self) -> List[str]:
        """No mid-function checkpoint to resume -- see module docstring.
        Loads/reloads the machine so every ledger reflects the latest
        on-disk state (including anything written by a prior, possibly
        crashed, run) before this cycle proposes anything new."""
        self.machine.load()
        return []

    # ------------------------------------------------------------- one cycle

    def run_one_cycle(self, *, total_slots: int = 10) -> CycleReport:
        """Public, overridable entry point for a single cycle -- what
        `agle.py cycle` calls standalone, and what run_forever() calls on
        every iteration (via ordinary polymorphism, so a subclass override
        of this method behaves identically either way).

        Lock-aware rather than lock-owning: if this instance's lock is
        already held (run_forever() holds it for its entire loop -- see
        below), this just runs the cycle body directly, on the assumption
        the outer caller already established exclusivity. Otherwise (a
        standalone call) it acquires the lock itself for the duration of
        this one cycle and raises DuplicateProcessError, running nothing,
        if another real production loop already holds it.
        """
        if self.lock._held:
            return self._run_one_cycle_locked(total_slots=total_slots)
        result = self.lock.acquire()
        if not result.acquired:
            raise DuplicateProcessError(result.reason, holder_pid=result.holder_pid)
        try:
            return self._run_one_cycle_locked(total_slots=total_slots)
        finally:
            self.lock.release()

    def _run_one_cycle_locked(self, *, total_slots: int = 10) -> CycleReport:
        """The actual cycle body. Assumes the caller already holds
        self.lock -- called directly (never through run_one_cycle(), which
        would re-acquire a non-reentrant lock) by run_forever(), which
        holds the lock for its entire loop lifetime."""
        # A pure wall-clock timestamp collides when a cycle completes in
        # under a second (the norm for a fast/soak run, and possible even
        # in real production) -- a monotonic sequence number guarantees
        # uniqueness regardless of cycle duration.
        self._cycle_seq += 1
        cycle_id = f"CYCLE-PROD-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{self._cycle_seq:06d}"
        report = CycleReport(cycle_id=cycle_id, started_at=datetime.now(timezone.utc).isoformat())

        self.state = "LOADING"
        self.heartbeat()
        report.recovery_events = self.recover_state()

        self.check_governance()

        self.state = "FACTORY_EVALUATION"
        self.heartbeat()
        result = self.machine.run_adaptive_search_cycle(
            cycle_id=cycle_id, total_slots=total_slots, evaluation_ledger=self.evaluation_ledger,
        )

        report.ideas = result.get("ideas_generated", 0)
        report.hypotheses = result.get("exploration_ideas", 0) + result.get("exploitation_ideas", 0)
        report.factory_evaluations = result.get("factory_evaluations", 0)
        report.survivors = result.get("survivors", 0)
        report.still_underpowered = result.get("still_underpowered", 0)
        report.refuted = result.get("refuted_this_run", 0)

        # Productization gate: only ever for a hypothesis this cycle's real
        # Factory evaluation marked DISCOVERY_SURVIVOR. maybe_productize()
        # defers entirely to ea_generator's own GEN14-PASS gate -- a fresh
        # DISCOVERY_SURVIVOR has never been through GEN12/13/14, so this is
        # expected to report NOT_AUTHORIZED every time until a candidate is
        # separately, manually carried through that governed sequence.
        for hyp in result.get("hypotheses", []):
            if hyp.get("final_status") != "DISCOVERY_SURVIVOR":
                continue
            prod = maybe_productize(
                candidate_id=hyp.get("hyp_id", ""), symbol=hyp.get("instrument", ""),
                hypothesis_id=hyp.get("hyp_id", ""), factory_evaluation_id=hyp.get("eval_id", ""),
                registry=self.ea_registry,
            )
            if prod.status == "PRODUCTIZED":
                report.ea_products_created += 1
            else:
                report.recovery_events.append(f"{hyp.get('hyp_id')}: {prod.status} -- {prod.reason}")

        self.state = "IDLE"
        report.ended_at = datetime.now(timezone.utc).isoformat()
        self.cycles_completed += 1
        self.consecutive_failures = 0
        self.last_error = None
        self._log_cycle(report)
        self.heartbeat()
        return report

    def _log_cycle(self, report: CycleReport) -> None:
        import json

        self.operation_log_path.parent.mkdir(parents=True, exist_ok=True)
        existing: List[Dict[str, Any]] = []
        if self.operation_log_path.exists():
            try:
                existing = json.loads(self.operation_log_path.read_text()).get("cycles", [])
            except (json.JSONDecodeError, OSError):
                existing = []
        existing.append(report.to_dict())
        self._atomic_write(self.operation_log_path, {"cycles": existing})

    # ------------------------------------------------------------- the loop

    def run_forever(self, *, max_cycles: Optional[int] = None,
                    sleep_seconds: float = DEFAULT_SLEEP_SECONDS, total_slots: int = 10) -> Dict[str, Any]:
        """The 24/7 loop. Stops on: master switch OFF, max_cycles reached,
        max_consecutive_failures reached (bounded retry, never unbounded),
        or a graceful shutdown signal (SIGTERM/SIGINT -- see below). A
        GovernanceViolation always propagates immediately, uncaught.

        Holds the single-instance lock for the ENTIRE loop lifetime (one
        acquire, one release, in a finally) -- raises DuplicateProcessError
        immediately, before starting any cycle, if another real production
        loop already holds it. This is deliberately the ONE place a
        long-running loop is ever entered from, so a manual `agle.py run`
        and a watchdog-spawned child can never both be mid-loop at once.

        Graceful shutdown: installs a SIGTERM/SIGINT handler for the
        duration of this call (restored afterward) that sets a stop flag
        rather than letting Python's default handling kill the process
        immediately. The flag is only checked BETWEEN cycles, never inside
        one -- a signal arriving mid-cycle lets that cycle finish exactly
        as it would have, then the loop exits instead of starting another.
        This is what lets a Windows service (or `Ctrl-C`) ask this process
        to stop without ever killing an active evaluation and without
        touching the Master Switch -- "please stop" and "you are not
        authorized to run" are different concepts, kept structurally
        separate here exactly as they are everywhere else in this module.
        """
        lock_result = self.lock.acquire()
        if not lock_result.acquired:
            raise DuplicateProcessError(lock_result.reason, holder_pid=lock_result.holder_pid)

        stop_requested = {"flag": False}

        def _handle_stop_signal(signum, frame):  # noqa: ARG001 -- signal handler signature
            stop_requested["flag"] = True

        import signal
        prev_handlers = {}
        for sig_name in ("SIGTERM", "SIGINT", "SIGBREAK"):
            sig = getattr(signal, sig_name, None)
            if sig is not None:
                try:
                    prev_handlers[sig] = signal.signal(sig, _handle_stop_signal)
                except (ValueError, OSError):
                    pass  # not the main thread / not supported here -- best effort only

        try:
            while self.switch.is_on() and not stop_requested["flag"]:
                if max_cycles is not None and self.cycles_completed >= max_cycles:
                    break
                try:
                    self.run_one_cycle(total_slots=total_slots)
                except GovernanceViolation:
                    self.state = "STOPPED"
                    self.heartbeat()
                    raise
                except (ValueError, KeyError, TypeError, AttributeError, OSError, RuntimeError) as exc:
                    self.consecutive_failures += 1
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    self.state = "DEGRADED"
                    self.heartbeat()
                    if self.consecutive_failures >= self.max_consecutive_failures:
                        self.state = "STOPPED"
                        self.heartbeat()
                        break
                if not self.switch.is_on() or stop_requested["flag"]:
                    break
                if max_cycles is not None and self.cycles_completed >= max_cycles:
                    break
                # Sleep in short slices so a shutdown signal received during
                # the idle gap between cycles is honored promptly, not only
                # at the top of the next iteration.
                slept = 0.0
                slice_s = min(1.0, sleep_seconds) if sleep_seconds > 0 else 0.0
                while slept < sleep_seconds and not stop_requested["flag"]:
                    time.sleep(slice_s if sleep_seconds - slept >= slice_s else sleep_seconds - slept)
                    slept += slice_s if slice_s > 0 else sleep_seconds

            self.state = "STOPPED"
            self.heartbeat()
            return {
                "cycles_completed": self.cycles_completed, "consecutive_failures": self.consecutive_failures,
                "last_error": self.last_error, "master_switch": self.switch.current().state,
                "graceful_shutdown": stop_requested["flag"],
            }
        finally:
            for sig, handler in prev_handlers.items():
                try:
                    signal.signal(sig, handler)
                except (ValueError, OSError):
                    pass
            self.lock.release()

    def status(self) -> Dict[str, Any]:
        return {
            "master_switch": self.switch.current().to_dict(), "state": self.state,
            "cycles_completed": self.cycles_completed, "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error, "ea_products_created": self.ea_registry.count(),
        }
