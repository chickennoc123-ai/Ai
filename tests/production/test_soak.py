"""Deterministic accelerated soak test (spec Section 18).

A real 24/7 run cannot be reproduced inside a CI-length test. This test
substitutes many-cycles-in-seconds for hours-in-real-time while proving the
same properties a real soak run would: repeated cycles, on-disk persistence,
restart recovery, no duplicate (real) evaluation, no queue/ledger corruption,
no fabricated EA success, no uncontrolled network activity, stable heartbeat.

What this test does NOT do, and why that is still honest:

  * It injects a test-only double in place of AutonomousIdeaMachine so that
    dozens of cycles run in milliseconds instead of calling the real,
    market-data-driven discovery.cycle8_intraday.gate() dozens of times.
    The double is confined to this file, is never imported by any
    production/ or idea_machine/ module, and its verdicts are a fixed,
    clearly-labeled deterministic function of the input triple -- never a
    claim of real market edge. This is the standard "inject a scripted
    double to soak-test the scheduler" pattern; the real Factory's
    statistical correctness is exercised elsewhere (test_cycle8_intraday.py
    and friends), not re-litigated here.
  * Every ledger it writes to is an isolated tmp_path instance -- nothing
    here ever touches reports/production/ or reports/factory/.
  * It still drives the REAL EvaluationLedger, REAL EAProductRegistry, REAL
    MasterSwitch, REAL ProductionSupervisor, and the REAL
    maybe_productize() -> ea_generator.EAGenerator gate. The one thing
    faked is the market-data evaluation step inside "the machine" -- the
    orchestration around it is 100% real code, under real test.
  * It proves, not just asserts, "no fake success" (Section 16): even
    though the fake machine reports DISCOVERY_SURVIVOR repeatedly across
    many cycles, the real productization gate refuses every one of them
    (none was ever carried through real GEN12/13/14), so
    ea_products_created stays at 0 for the whole soak run -- exactly the
    correct, non-inflated outcome.
"""

from __future__ import annotations

import json
import socket

import pytest

from production.ea_registry import EAProductRegistry
from production.evaluation_ledger import EvaluationLedger
from production.master_switch import MasterSwitch
from production.supervisor import ProductionSupervisor

TOTAL_CYCLES = 40
# A small, fixed pool of triples so several cycles legitimately resubmit
# the SAME triple -- the scenario the EvaluationLedger dedup exists for.
_TRIPLE_POOL = [
    ("streak_fade", "EURUSD", "cpi_release", 60),
    ("gap_fade", "XAUUSD", None, 60),
    ("streak_fade", "GBPUSD", "nfp_release", 60),
]


class _SoakTestOnlyFakeMachine:
    """TEST FIXTURE ONLY -- never used outside this file, never registered
    with any production path. Mimics the on-the-wire shape of
    AutonomousIdeaMachine.run_adaptive_search_cycle() so the real
    ProductionSupervisor code can be soak-tested at cycle-per-millisecond
    speed. Verdicts are a fixed, deterministic function of the triple, not
    a statistical claim -- every candidate_id it proposes as a
    DISCOVERY_SURVIVOR is deliberately never registered in
    CandidateSpecRegistry, so the real productization gate always,
    correctly, refuses it.
    """

    def __init__(self):
        self.loads = 0

    def load(self):
        self.loads += 1

    def run_adaptive_search_cycle(self, *, cycle_id, total_slots=10, evaluation_ledger=None):
        results = []
        survivors = underpowered = refuted = 0
        for i, (mechanism, instrument, driver, window_min) in enumerate(_TRIPLE_POOL):
            hyp_id = f"HYP-SOAK-{cycle_id}-{i}"
            prior = evaluation_ledger.already_evaluated(mechanism, instrument, driver, window_min) \
                if evaluation_ledger is not None else None
            if prior is not None:
                row = dict(prior)
                row["hyp_id"] = hyp_id
                row["reused_from_eval_id"] = prior.get("eval_id")
            else:
                # Fixed, deterministic-by-triple label -- never randomness,
                # never a claim of real evidence.
                final_status = "DISCOVERY_SURVIVOR" if instrument == "EURUSD" else "STILL_UNDERPOWERED"
                row = {
                    "hyp_id": hyp_id, "mechanism": mechanism, "instrument": instrument,
                    "driver": driver, "window_min": window_min, "final_status": final_status,
                    "verdict": "TEST_FIXTURE_VERDICT -- not real evidence",
                    "train": {"t": 0.0}, "validation": {"n": 0},
                }
                if evaluation_ledger is not None:
                    saved = evaluation_ledger.record(
                        mechanism=mechanism, instrument=instrument, driver=driver, window_min=window_min,
                        hyp_id=hyp_id, cycle_id=cycle_id, verdict=row["verdict"],
                        final_status=final_status, train=row["train"], validation=row["validation"],
                    )
                    row["eval_id"] = saved.get("eval_id")
            if row["final_status"] == "DISCOVERY_SURVIVOR":
                survivors += 1
            elif row["final_status"] == "STILL_UNDERPOWERED":
                underpowered += 1
            else:
                refuted += 1
            results.append(row)

        return {
            "ideas_generated": len(_TRIPLE_POOL), "exploration_ideas": len(_TRIPLE_POOL),
            "exploitation_ideas": 0, "factory_evaluations": len(results),
            "survivors": survivors, "still_underpowered": underpowered, "refuted_this_run": refuted,
            "hypotheses": results,
        }


class _NoNetwork:
    """Context manager: raise if any code under it tries to open a real
    socket -- proves the soak run has no uncontrolled network activity."""

    def __enter__(self):
        self._real_socket = socket.socket

        def _forbidden(*args, **kwargs):
            raise AssertionError("soak test attempted to open a real network socket")

        socket.socket = _forbidden
        return self

    def __exit__(self, *exc):
        socket.socket = self._real_socket


def _new_supervisor(tmp_path, machine=None, switch=None) -> ProductionSupervisor:
    return ProductionSupervisor(
        machine=machine or _SoakTestOnlyFakeMachine(),
        switch=switch or MasterSwitch(path=tmp_path / "switch.json"),
        evaluation_ledger=EvaluationLedger(path=tmp_path / "evaluation_ledger.json"),
        ea_registry=EAProductRegistry(path=tmp_path / "ea_registry.json"),
        heartbeat_path=tmp_path / "heartbeat.json",
        operation_log_path=tmp_path / "operation_log.json",
    )


def test_soak_many_cycles_no_duplicate_evaluation_no_fake_success(tmp_path):
    switch = MasterSwitch(path=tmp_path / "switch.json")
    switch.turn_on(reason="soak test", source="test")
    sup = _new_supervisor(tmp_path, switch=switch)

    with _NoNetwork():
        summary = sup.run_forever(max_cycles=TOTAL_CYCLES, sleep_seconds=0)

    assert summary["cycles_completed"] == TOTAL_CYCLES
    assert sup.cycles_completed == TOTAL_CYCLES
    assert sup.consecutive_failures == 0
    assert sup.last_error is None

    # Persistence: the operation log has exactly one entry per cycle.
    log = json.loads((tmp_path / "operation_log.json").read_text())
    assert len(log["cycles"]) == TOTAL_CYCLES
    cycle_ids = [c["cycle_id"] for c in log["cycles"]]
    assert len(cycle_ids) == len(set(cycle_ids)), "duplicate cycle_id in operation log"

    # No duplicate (fake, but ledger-real) evaluation: 3 distinct triples
    # resubmitted every cycle for 40 cycles must still resolve to exactly 3
    # ledger records, never 120.
    ledger = EvaluationLedger(path=tmp_path / "evaluation_ledger.json")
    assert len(ledger.all()) == len(_TRIPLE_POOL)

    # No fake success (Section 16): the fake machine claimed a
    # DISCOVERY_SURVIVOR every single cycle, but none of those candidate_ids
    # was ever carried through real GEN12/13/14 -- the real productization
    # gate must have refused every one of them.
    registry = EAProductRegistry(path=tmp_path / "ea_registry.json")
    assert registry.count() == 0

    # No corruption of any ledger touched during the soak run.
    ledger.verify_integrity()
    registry.verify_integrity()
    switch.verify_integrity()

    # Stable heartbeat: valid JSON, correct pid, final state STOPPED
    # (switch still ON but max_cycles reached is a clean stop, not a crash).
    heartbeat = json.loads((tmp_path / "heartbeat.json").read_text())
    import os
    assert heartbeat["pid"] == os.getpid()
    assert heartbeat["state"] == "STOPPED"
    assert heartbeat["consecutive_failures"] == 0


def test_soak_restart_recovery_mid_run_no_duplication(tmp_path):
    """Simulate a crash-and-restart halfway through the soak run: a fresh
    ProductionSupervisor (and fresh AutonomousIdeaMachine double, exactly as
    a real process restart would produce) must continue cleanly, with no
    duplicate cycle_ids, no duplicate real (ledger) evaluations, and no
    lost cycle count."""
    switch = MasterSwitch(path=tmp_path / "switch.json")
    switch.turn_on(reason="soak restart test", source="test")

    half = TOTAL_CYCLES // 2
    sup_a = _new_supervisor(tmp_path, switch=switch)
    with _NoNetwork():
        sup_a.run_forever(max_cycles=half, sleep_seconds=0)
    assert sup_a.cycles_completed == half

    # "Restart": a brand new supervisor instance, brand new fake machine,
    # but pointed at the SAME on-disk paths -- exactly what a killed-and-
    # relaunched process would construct.
    sup_b = _new_supervisor(tmp_path, switch=switch)
    assert sup_b.cycles_completed == 0  # in-memory counter resets...
    with _NoNetwork():
        sup_b.run_forever(max_cycles=TOTAL_CYCLES - half, sleep_seconds=0)
    assert sup_b.cycles_completed == TOTAL_CYCLES - half  # ...but disk state doesn't.

    log = json.loads((tmp_path / "operation_log.json").read_text())
    assert len(log["cycles"]) == TOTAL_CYCLES
    cycle_ids = [c["cycle_id"] for c in log["cycles"]]
    assert len(cycle_ids) == len(set(cycle_ids)), "restart produced a duplicate cycle_id"

    ledger = EvaluationLedger(path=tmp_path / "evaluation_ledger.json")
    assert len(ledger.all()) == len(_TRIPLE_POOL), "restart caused duplicate real evaluation"

    registry = EAProductRegistry(path=tmp_path / "ea_registry.json")
    assert registry.count() == 0


def test_soak_master_switch_off_stops_loop_promptly(tmp_path):
    """A switch flipped OFF partway through must stop the loop before
    max_cycles is reached -- proving the loop actually re-checks the
    persistent switch every iteration, not just once at start."""
    switch = MasterSwitch(path=tmp_path / "switch.json")
    switch.turn_on(reason="soak switch test", source="test")

    stop_after = 7

    class _StoppingMachine(_SoakTestOnlyFakeMachine):
        def __init__(self, switch_ref):
            super().__init__()
            self._switch = switch_ref
            self._n = 0

        def run_adaptive_search_cycle(self, *, cycle_id, total_slots=10, evaluation_ledger=None):
            self._n += 1
            if self._n >= stop_after:
                self._switch.turn_off(reason="soak test: simulated operator stop", source="test")
            return super().run_adaptive_search_cycle(
                cycle_id=cycle_id, total_slots=total_slots, evaluation_ledger=evaluation_ledger,
            )

    sup = _new_supervisor(tmp_path, machine=_StoppingMachine(switch), switch=switch)
    with _NoNetwork():
        summary = sup.run_forever(max_cycles=TOTAL_CYCLES, sleep_seconds=0)

    assert summary["cycles_completed"] == stop_after
    assert summary["master_switch"] == "OFF"
    assert sup.cycles_completed < TOTAL_CYCLES
