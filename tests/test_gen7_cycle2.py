"""
Tests for GEN 7 Cycle 2: multiple-testing ledger, research memory extraction,
and the horizon-sweep discovery engine.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.ledger import MultipleTestingLedger  # noqa: E402
from discovery.observatory import Bar  # noqa: E402
from discovery.cycle2_horizon import (  # noqa: E402
    HORIZONS, full_stats, materialize, signals_streak_reversal,
    signals_gap_structure, signals_breakout, build_family_registry,
    run_sweep, _classify_train, _classify_val, FullStats,
)
from discovery.evaluation import Trade, ROUNDTRIP_COST  # noqa: E402
from discovery._guards import HoldoutFirewallViolation, guard_path  # noqa: E402


def _bars(n=2000, pattern="alt"):
    bars, price, ts = [], 1.1000, datetime(2016, 1, 4, 0, 0)
    for i in range(n):
        if pattern == "alt":
            step = 0.0008 if i % 2 == 0 else -0.0008
        else:
            step = 0.0006 if (i % 5) < 3 else -0.0009
        o, c = price, price + step
        bars.append(Bar(ts, o, max(o, c) + 1e-4, min(o, c) - 1e-4, c))
        price, ts = c, ts + timedelta(hours=1)
        if not 0.5 < price < 2.0:
            price = 1.1
    return bars


# ---------------------------------------------------------------------------
# Ledger: append-only, cumulative, never reset
# ---------------------------------------------------------------------------

class TestLedger:
    def test_fresh_ledger_starts_empty(self, tmp_path):
        led = MultipleTestingLedger(tmp_path / "ledger.json")
        assert led.total_hypotheses() == 0
        assert led.total_parameter_evaluations() == 0

    def test_record_cycle_accumulates(self, tmp_path):
        led = MultipleTestingLedger(tmp_path / "ledger.json")
        led.record_cycle("C1", hypotheses_generated=8, parameter_evaluations=8,
                         families_touched=["A"], survivors=0)
        led.record_cycle("C2", hypotheses_generated=7, parameter_evaluations=243,
                         families_touched=["B"], survivors=0)
        assert led.total_hypotheses() == 15
        assert led.total_parameter_evaluations() == 251
        assert led.total_survivors() == 0
        assert led.all_families() == {"A", "B"}

    def test_duplicate_cycle_id_rejected(self, tmp_path):
        led = MultipleTestingLedger(tmp_path / "ledger.json")
        led.record_cycle("C1", hypotheses_generated=1, parameter_evaluations=1,
                         families_touched=[], survivors=0)
        with pytest.raises(ValueError):
            led.record_cycle("C1", hypotheses_generated=1, parameter_evaluations=1,
                             families_touched=[], survivors=0)

    def test_persists_across_instances(self, tmp_path):
        p = tmp_path / "ledger.json"
        MultipleTestingLedger(p).record_cycle("C1", hypotheses_generated=5,
                                              parameter_evaluations=20,
                                              families_touched=["X"], survivors=1)
        reloaded = MultipleTestingLedger(p)
        assert reloaded.total_hypotheses() == 5
        assert reloaded.total_parameter_evaluations() == 20
        assert reloaded.total_survivors() == 1

    def test_no_method_can_decrease_counters(self):
        led = MultipleTestingLedger
        # structural guarantee: no delete/reset method exists on the class
        forbidden = {"reset", "delete_cycle", "clear", "remove_cycle"}
        assert not (forbidden & set(dir(led)))

    def test_real_ledger_reflects_two_cycles_never_reset(self):
        led = MultipleTestingLedger()
        assert led.total_hypotheses() >= 15
        assert led.total_parameter_evaluations() >= 251
        assert len(led.cycles) >= 2
        ids = [c.cycle_id for c in led.cycles]
        assert "CYCLE-01" in ids and "CYCLE-02" in ids


# ---------------------------------------------------------------------------
# Horizon-sweep engine: cost model, materializer, gates
# ---------------------------------------------------------------------------

class TestMaterializer:
    def test_cost_is_fixed_regardless_of_horizon(self):
        bars = _bars(500)
        events = [(10, 1), (100, 1), (200, -1)]
        for h in (2, 240):
            trades = materialize(events, bars, h)
            for t in trades:
                assert abs((t.gross - t.net) - ROUNDTRIP_COST) < 1e-9

    def test_non_overlapping_positional_semantics(self):
        bars = _bars(500)
        # two events close together; second falls inside first trade's window
        events = [(10, 1), (15, 1), (60, 1)]
        trades = materialize(events, bars, horizon=20)
        entry_indices = [i for i, d in events]
        assert len(trades) == 2  # event at 15 must be skipped (inside 10..30)

    def test_full_stats_empty_is_safe(self):
        s = full_stats([], 1000)
        assert s.n == 0 and s.mean_net == 0.0

    def test_cost_efficiency_scales_with_gross_not_net(self):
        trades = [Trade(f"t{i}", 1, 0.002, 0.002 - ROUNDTRIP_COST, 10, 12) for i in range(50)]
        s = full_stats(trades, 1000)
        assert s.cost_efficiency == pytest.approx(0.002 / ROUNDTRIP_COST, rel=1e-3)

    def test_drawdown_nonnegative_and_monotone_sensible(self):
        trades = [Trade(f"t{i}", 1, 0.001, v, 1, 12) for i, v in
                  enumerate([0.001, -0.002, 0.0005, -0.003, 0.004])]
        s = full_stats(trades, 100)
        assert s.max_drawdown >= 0


class TestSignalGenerators:
    def test_streak_reversal_direction_opposes_streak(self):
        bars = _bars(500, pattern="trend")  # has genuine same-direction runs
        events = signals_streak_reversal(bars, k=2)
        assert events
        for idx, direction in events[:5]:
            assert direction in (1, -1)
            # the two bars immediately preceding idx must share a direction
            # opposite to the emitted fade direction
            prev_close, mid_close = bars[idx - 2].close, bars[idx - 1].close
            run_sign = 1 if mid_close > prev_close else -1
            assert direction == -run_sign

    def test_gap_structure_requires_min_gap(self):
        bars = _bars(500)
        # inject an artificial weekend gap
        bars[100].ts = bars[99].ts + timedelta(hours=50)
        bars[100].open = bars[99].close + 0.002
        events_small_thresh = signals_gap_structure(bars, min_pips=1, max_pips=None, mode="FADE")
        events_huge_thresh = signals_gap_structure(bars, min_pips=1000, max_pips=None, mode="FADE")
        assert len(events_small_thresh) >= 1
        assert len(events_huge_thresh) == 0

    def test_gap_fade_and_continuation_are_opposite_directions(self):
        bars = _bars(500)
        bars[100].ts = bars[99].ts + timedelta(hours=50)
        bars[100].open = bars[99].close + 0.002
        fade = signals_gap_structure(bars, 1, None, "FADE")
        cont = signals_gap_structure(bars, 1, None, "CONTINUATION")
        assert fade and cont
        assert fade[0][0] == cont[0][0]
        assert fade[0][1] == -cont[0][1]

    def test_breakout_continuation_and_reversal_are_opposite(self):
        bars = _bars(500, pattern="trend")
        cont = signals_breakout(bars, lookback=10, mode="CONTINUATION")
        rev = signals_breakout(bars, lookback=10, mode="REVERSAL")
        assert len(cont) == len(rev)
        for (i1, d1), (i2, d2) in zip(cont, rev):
            assert i1 == i2 and d1 == -d2


class TestGates:
    def test_insufficient_sample_killed(self):
        s = FullStats(n=5, gross_expectancy=0.002, mean_net=0.001, net_std=0.001,
                      t_stat=5.0, profit_factor=2.0, win_rate=0.6, cost=ROUNDTRIP_COST,
                      cost_efficiency=18.0, turnover=0.01, sharpe=1.0, sortino=1.0,
                      max_drawdown=0.001)
        assert _classify_train(s) == "KILLED_INSUFFICIENT_SAMPLE"

    def test_cost_dominated_killed(self):
        s = FullStats(n=200, gross_expectancy=0.00005, mean_net=0.00001, net_std=0.0001,
                      t_stat=3.0, profit_factor=1.1, win_rate=0.51, cost=ROUNDTRIP_COST,
                      cost_efficiency=0.5, turnover=0.1, sharpe=0.1, sortino=0.1,
                      max_drawdown=0.01)
        assert _classify_train(s) == "KILLED_COST_DOMINATED"

    def test_economically_untradable_when_gross_positive_net_negative(self):
        s = FullStats(n=200, gross_expectancy=0.0001, mean_net=-0.00001, net_std=0.0002,
                      t_stat=-1.0, profit_factor=0.9, win_rate=0.48, cost=ROUNDTRIP_COST,
                      cost_efficiency=0.9, turnover=0.1, sharpe=-0.1, sortino=-0.1,
                      max_drawdown=0.01)
        assert _classify_train(s) == "ECONOMICALLY_UNTRADABLE"

    def test_pass_train_requires_all_three(self):
        s = FullStats(n=200, gross_expectancy=0.0005, mean_net=0.0004, net_std=0.002,
                      t_stat=2.5, profit_factor=1.5, win_rate=0.55, cost=ROUNDTRIP_COST,
                      cost_efficiency=4.5, turnover=0.1, sharpe=0.2, sortino=0.3,
                      max_drawdown=0.01)
        assert _classify_train(s) == "PASS_TRAIN"

    def test_val_negative_fails(self):
        s = FullStats(n=100, gross_expectancy=0.0001, mean_net=-0.0001, net_std=0.001,
                      t_stat=-1.0, profit_factor=0.8, win_rate=0.4, cost=ROUNDTRIP_COST,
                      cost_efficiency=1.0, turnover=0.05, sharpe=-0.1, sortino=-0.1,
                      max_drawdown=0.01)
        assert _classify_val(s) == "VAL_FAIL_NEGATIVE"


class TestRegistryAndDeterminism:
    def test_registry_has_five_families(self):
        reg = build_family_registry()
        families = {e["family"] for e in reg}
        assert families == {"STREAK_REVERSAL_MULTIBAR", "GAP_MAGNITUDE_STRUCTURE",
                            "VOLATILITY_TRANSITION", "BREAKOUT_STRUCTURE",
                            "MULTITIMEFRAME_TREND_FILTER"}

    def test_sweep_covers_all_horizons(self):
        bars = _bars(1500)
        cut = int(len(bars) * 0.8)
        results = run_sweep(bars[:cut], bars[cut:])
        horizons_seen = {r["params"]["horizon"] for r in results}
        assert horizons_seen == set(HORIZONS)

    def test_sweep_is_deterministic(self):
        bars = _bars(1500)
        cut = int(len(bars) * 0.8)
        a = run_sweep(bars[:cut], bars[cut:])
        b = run_sweep(bars[:cut], bars[cut:])
        assert a == b

    def test_every_evaluation_has_a_gate(self):
        bars = _bars(1500)
        cut = int(len(bars) * 0.8)
        results = run_sweep(bars[:cut], bars[cut:])
        assert results
        for r in results:
            assert r["gate"]


class TestHoldoutNeverTouched:
    def test_cycle2_module_imports_no_holdout_path(self):
        src = (REPO_ROOT / "discovery" / "cycle2_horizon.py").read_text()
        assert "holdout" not in src.lower()

    def test_original_eurusd_holdout_remains_sealed_and_unconsumed(self):
        """
        Written when the vault held only the EURUSD Gen 6 holdout, so it
        originally asserted every dataset was sealed and the vault held no
        authorizations/consumptions at all. A real GEN 14 run has since
        legitimately sealed, authorized and consumed four OTHER symbols'
        holdouts (GBPUSD/USDCHF/USDJPY/XAUUSD -- see
        ML-001-GEN14-C2-NFP-FINAL-VERDICT.md). The invariant this test
        protects is that THIS specific dataset -- the one that existed and
        was sealed at Cycle 2 -- was never touched by that or any other run.
        """
        from core.factory.evidence_vault import EvidenceVault
        vault = EvidenceVault()
        eurusd_id = "DS-HOLDOUT-EURUSD-H1-HISTDATA-20240101-20260130"
        assert eurusd_id in vault.datasets
        assert vault.datasets[eurusd_id].seal_status.value == "sealed"
        assert not any(k.startswith(f"{eurusd_id}:") for k in vault.authorizations)
        assert not any(c.dataset_id == eurusd_id for c in vault.consumptions)


# ---------------------------------------------------------------------------
# Real cycle-2 artifacts (integration)
# ---------------------------------------------------------------------------

class TestRealCycle2Artifacts:
    def test_cycle1_archive_preserved(self):
        for name in ("cycle_01_observations.json", "cycle_01_queue.json",
                     "cycle_01_evaluation.json"):
            assert (REPO_ROOT / "reports/factory/discovery_cycles" / name).exists()

    def test_cycle2_sweep_artifact_has_243_evaluations(self):
        sweep = json.loads((REPO_ROOT / "reports/factory/discovery_cycles/cycle_02_sweep.json")
                           .read_text())
        assert sweep["total_evaluations"] == 243
        assert len(sweep["results"]) == 243

    def test_cycle2_zero_survivors_matches_ledger(self):
        sweep = json.loads((REPO_ROOT / "reports/factory/discovery_cycles/cycle_02_sweep.json")
                           .read_text())
        survivors = [r for r in sweep["results"] if r["gate"] == "PASS_TRAIN_AND_VAL"]
        led = MultipleTestingLedger()
        cycle2 = next(c for c in led.cycles if c.cycle_id == "CYCLE-02")
        assert len(survivors) == cycle2.survivors == 0

    def test_failure_library_grew_not_shrank(self):
        from core.factory.failure_library import FailureLibrary
        lib = FailureLibrary()
        assert len(lib.all_failures()) >= 28  # 22 pre-cycle2 + 6 cycle2 records
