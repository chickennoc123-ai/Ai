"""
GEN 7 Cycle 4 -- economic-structure discovery tests.

The central regression here is the realized-hold guard: an earlier version of
this cycle reported three "survivors" that were 2-hour trades wearing a daily
label, because the guard compared a DECLARED parameter against the minimum
instead of measuring the actual interval between entry and exit bars.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.observatory import Bar
from discovery.cycle4_economics import (
    DayBar, to_daily, stats, _materialize, _gate, sig_A1_streak, sig_B1_weekday,
    sig_B2_turn_of_month, sig_C1_nfp, sig_E1_convergence,
    MIN_HOLDING_HOURS, MIN_GROSS_OVER_COST, MIN_TRADES, TRAIN_MIN_T, VAL_MIN_T,
    GRID, CROSS_PAIRS,
)

SWEEP = REPO_ROOT / "reports/factory/discovery_cycles/cycle_04_economic_sweep.json"


def _h1(days: int, start=datetime(2015, 1, 5), hours_per_day=24, step=0.001):
    """Synthetic H1 bars, `hours_per_day` bars on each calendar day."""
    bars, price = [], 1.0
    for d in range(days):
        for h in range(hours_per_day):
            ts = start + timedelta(days=d, hours=h)
            o, c = price, price + step
            bars.append(Bar(ts, o, max(o, c) + 1e-5, min(o, c) - 1e-5, c))
            price = c
    return bars


def _day(date, close, last_ts=None, bars=24):
    return DayBar(date, close, close, close, close, bars, last_ts or date)


# ------------------------------------------------------------ resampling

class TestDailyResample:
    def test_daily_bar_carries_last_h1_timestamp(self):
        days = to_daily(_h1(3))
        assert len(days) == 3
        assert days[0].last_ts == datetime(2015, 1, 5, 23)
        assert days[0].bars == 24

    def test_stub_day_is_visible_as_few_bars(self):
        bars = _h1(2) + [Bar(datetime(2015, 1, 7, h), 1.5, 1.5, 1.5, 1.5) for h in range(2)]
        days = to_daily(bars)
        assert days[-1].bars == 2
        assert days[-1].last_ts == datetime(2015, 1, 7, 1)

    def test_ohlc_aggregation_is_correct(self):
        days = to_daily(_h1(1))
        d = days[0]
        assert d.high >= d.open and d.high >= d.close
        assert d.low <= d.open and d.low <= d.close


# ------------------------------------------------- realized-hold regression

class TestRealizedHoldGuard:
    def test_trade_records_measured_not_assumed_hold(self):
        days = [_day(datetime(2015, 1, 5), 1.0, datetime(2015, 1, 5, 23)),
                _day(datetime(2015, 1, 6), 1.1, datetime(2015, 1, 6, 1), bars=2)]
        tr = _materialize(days, [(0, 1)], 1, 0.0)
        assert tr[0].realized_hours == 2.0, "hold must be measured, not assumed 24h"

    def test_sub_daily_hold_is_refuted_even_when_profitable(self):
        """The exact bug: a hugely profitable 2-hour trade must still be killed."""
        days = [_day(datetime(2015, 1, 5) + timedelta(days=i),
                     1.0 + 0.05 * i,
                     datetime(2015, 1, 5, 23) + timedelta(days=i) if i % 2 == 0
                     else datetime(2015, 1, 5, 1) + timedelta(days=i), bars=2)
                for i in range(120)]
        trades = _materialize(days, [(i, 1) for i in range(0, 118, 2)], 1, 1e-5)
        s = stats(trades, 1e-5)
        assert s.mean_net > 0 and s.t_stat > 5, "fixture should look like a strong edge"
        assert s.median_hold_hours < MIN_HOLDING_HOURS
        verdict, reason = _gate(s, s)
        assert verdict == "SUB_DAILY_REFUTED_FAMILY"
        assert "FAIL-000029" in reason

    def test_genuine_multiday_hold_passes_the_structural_guard(self):
        days = [_day(datetime(2015, 1, 5) + timedelta(days=i), 1.0 + 0.01 * i,
                     datetime(2015, 1, 5, 23) + timedelta(days=i)) for i in range(200)]
        s = stats(_materialize(days, [(i, 1) for i in range(0, 190, 3)], 2, 1e-5), 1e-5)
        assert s.median_hold_hours == 48.0
        assert _gate(s, s)[0] != "SUB_DAILY_REFUTED_FAMILY"


# ---------------------------------------------------------- materialization

class TestMaterialization:
    def test_positions_do_not_overlap(self):
        days = [_day(datetime(2015, 1, 5) + timedelta(days=i), 1.0 + 0.001 * i,
                     datetime(2015, 1, 5, 23) + timedelta(days=i)) for i in range(50)]
        tr = _materialize(days, [(i, 1) for i in range(40)], 5, 0.0)
        entries = [datetime.fromisoformat(t.entry) for t in tr]
        assert all((entries[i + 1] - entries[i]).days >= 5 for i in range(len(entries) - 1))

    def test_one_cost_per_trade_regardless_of_holding_length(self):
        days = [_day(datetime(2015, 1, 5) + timedelta(days=i), 1.0 + 0.001 * i,
                     datetime(2015, 1, 5, 23) + timedelta(days=i)) for i in range(100)]
        cost = 0.0002
        short = _materialize(days, [(0, 1)], 2, cost)[0]
        long_ = _materialize(days, [(0, 1)], 20, cost)[0]
        assert abs((short.gross - short.net) - cost) < 1e-12
        assert abs((long_.gross - long_.net) - cost) < 1e-12

    def test_trade_is_dropped_when_exit_runs_past_the_data(self):
        days = [_day(datetime(2015, 1, 5) + timedelta(days=i), 1.0,
                     datetime(2015, 1, 5, 23) + timedelta(days=i)) for i in range(5)]
        assert _materialize(days, [(3, 1)], 10, 0.0) == []


# ------------------------------------------------------------ economic gate

class TestEconomicFilter:
    def _s(self, **kw):
        base = dict(n=100, gross_mean=1e-3, mean_net=1e-4, t_stat=3.0,
                    profit_factor=1.5, win_rate=0.55, gross_over_cost=5.0,
                    median_hold_hours=48.0)
        base.update(kw)
        from discovery.cycle4_economics import Stats
        return Stats(**base)

    def test_cost_dominated_is_rejected(self):
        s = self._s(gross_over_cost=1.9)
        assert _gate(s, s)[0] == "COST_DOMINATED"

    def test_gross_over_cost_threshold_is_two(self):
        assert MIN_GROSS_OVER_COST == 2.0

    def test_underpowered_train_is_rejected(self):
        s = self._s(n=29)
        assert _gate(s, s)[0] == "TRAIN_UNDERPOWERED"

    def test_negative_train_is_rejected(self):
        s = self._s(mean_net=-1e-6)
        assert _gate(s, s)[0] == "TRAIN_NEGATIVE"

    def test_insignificant_train_is_rejected(self):
        s = self._s(t_stat=1.99)
        assert _gate(s, s)[0] == "TRAIN_INSIGNIFICANT"

    def test_validation_failures_are_distinguished(self):
        good = self._s()
        assert _gate(good, self._s(n=10))[0] == "VALIDATION_UNDERPOWERED"
        assert _gate(good, self._s(mean_net=-1e-6))[0] == "VALIDATION_NEGATIVE"
        assert _gate(good, self._s(t_stat=1.0))[0] == "VALIDATION_INSIGNIFICANT"

    def test_all_conditions_met_yields_survivor(self):
        s = self._s()
        assert _gate(s, s)[0] == "DISCOVERY_SURVIVOR"

    def test_thresholds_match_preregistration(self):
        assert (MIN_TRADES, TRAIN_MIN_T, VAL_MIN_T, MIN_HOLDING_HOURS) == (30, 2.0, 1.5, 24)


# ----------------------------------------------------------- signal shapes

class TestSignals:
    def test_streak_fade_opposes_the_run(self):
        days = [_day(datetime(2015, 1, 5) + timedelta(days=i), 1.0 + 0.01 * i,
                     datetime(2015, 1, 5, 23) + timedelta(days=i)) for i in range(20)]
        assert all(d == -1 for _, d in sig_A1_streak(days, 2, "FADE"))
        assert all(d == 1 for _, d in sig_A1_streak(days, 2, "FOLLOW"))

    def test_weekday_selector_picks_only_that_weekday(self):
        days = [_day(datetime(2015, 1, 5) + timedelta(days=i), 1.0,
                     datetime(2015, 1, 5, 23) + timedelta(days=i)) for i in range(30)]
        for i, _ in sig_B1_weekday(days, 2, 1):
            assert days[i].date.weekday() == 2

    def test_turn_of_month_fires_once_per_month(self):
        days = [_day(datetime(2015, 1, 1) + timedelta(days=i), 1.0,
                     datetime(2015, 1, 1, 23) + timedelta(days=i)) for i in range(365)]
        assert 11 <= len(sig_B2_turn_of_month(days, (1, 1), 1)) <= 12

    def test_nfp_proxy_is_first_friday_only(self):
        days = [_day(datetime(2015, 1, 1) + timedelta(days=i), 1.0 + 0.001 * i,
                     datetime(2015, 1, 1, 23) + timedelta(days=i)) for i in range(365)]
        for i, _ in sig_C1_nfp(days, "FOLLOW"):
            assert days[i].date.weekday() == 4 and days[i].date.day <= 7

    def test_convergence_shorts_the_rich_leg(self):
        # the spread needs non-zero variance for a z-score to exist
        a = [_day(datetime(2015, 1, 1) + timedelta(days=i),
                  1.0 + 0.001 * (i % 5),
                  datetime(2015, 1, 1, 23) + timedelta(days=i)) for i in range(80)]
        b = [_day(x.date, 1.0, x.last_ts) for x in a]
        a[79] = _day(a[79].date, 2.0, a[79].last_ts)     # A spikes rich
        sig = sig_E1_convergence(a, b, 60, 2.0)
        assert sig and sig[-1] == (79, -1), "rich leg must be sold"

    def test_convergence_longs_the_cheap_leg(self):
        a = [_day(datetime(2015, 1, 1) + timedelta(days=i),
                  1.0 + 0.001 * (i % 5),
                  datetime(2015, 1, 1, 23) + timedelta(days=i)) for i in range(80)]
        b = [_day(x.date, 1.0, x.last_ts) for x in a]
        a[79] = _day(a[79].date, 0.5, a[79].last_ts)     # A spikes cheap
        sig = sig_E1_convergence(a, b, 60, 2.0)
        assert sig and sig[-1] == (79, 1)


# ------------------------------------------- produced artifact must be sound

class TestCycle4Artifact:
    @pytest.fixture(scope="class")
    def sweep(self):
        return json.loads(SWEEP.read_text())

    def test_every_survivor_holds_at_least_a_day(self, sweep):
        for s in sweep["survivors"]:
            assert s["train"]["median_hold_hours"] >= MIN_HOLDING_HOURS
            assert s["validation"]["median_hold_hours"] >= MIN_HOLDING_HOURS

    def test_every_survivor_clears_every_preregistered_threshold(self, sweep):
        for s in sweep["survivors"]:
            t, v = s["train"], s["validation"]
            assert t["n"] >= MIN_TRADES and v["n"] >= MIN_TRADES
            assert t["mean_net"] > 0 and v["mean_net"] > 0
            assert t["t_stat"] >= TRAIN_MIN_T and v["t_stat"] >= VAL_MIN_T
            assert t["gross_over_cost"] >= MIN_GROSS_OVER_COST

    def test_sub_daily_disguises_were_caught(self, sweep):
        assert sweep["verdict_distribution"].get("SUB_DAILY_REFUTED_FAMILY", 0) > 0

    def test_no_family_is_an_h1_price_model(self, sweep):
        for r in sweep["results"]:
            assert r["declared_holding_hours"] >= MIN_HOLDING_HOURS

    def test_grid_in_artifact_matches_the_preregistered_grid(self, sweep):
        assert set(sweep["preregistered_grid"]) == set(GRID)
        assert [tuple(p) for p in sweep["cross_pairs"]] == CROSS_PAIRS

    def test_evaluation_count_matches_result_rows(self, sweep):
        assert sweep["parameter_evaluations"] == len(sweep["results"])


# ------------------------------------------------------------- governance

class TestCycle4Governance:
    def test_h1_family_is_registered_as_refuted(self):
        reg = json.loads((REPO_ROOT / "reports/factory/research_family_registry.json").read_text())
        fam = reg["families"].get("FAMILY-H1-PRICE-PATTERN")
        assert fam and fam["status"] == "REFUTED" and fam["refuted_by"] == "FAIL-000029"

    def test_ledger_counts_every_probe_including_robustness_and_attacks(self):
        lg = json.loads((REPO_ROOT / "reports/factory/multiple_testing_ledger.json").read_text())
        c4 = next(c for c in lg["cycles"] if c["cycle_id"] == "CYCLE-04-ECONOMIC-STRUCTURE")
        sweep = json.loads(SWEEP.read_text())
        rb = json.loads((REPO_ROOT / "reports/factory/discovery_cycles/cycle_04_robustness.json").read_text())
        adv = json.loads((REPO_ROOT / "reports/factory/discovery_cycles/cycle_04_adversarial.json").read_text())
        assert c4["parameter_evaluations"] == (sweep["parameter_evaluations"]
                                               + rb["extra_parameter_evaluations"]
                                               + adv["extra_parameter_evaluations"])

    def test_original_eurusd_holdout_still_unconsumed_after_cycle4(self):
        ev = json.loads((REPO_ROOT / "reports/factory/evidence_vault.json").read_text())
        # A real GEN 14 run (see ML-001-GEN14-C2-NFP-FINAL-VERDICT.md) later
        # legitimately sealed, authorized and consumed four OTHER symbols'
        # holdouts; the vault is no longer empty. The invariant this test
        # actually protects is that THIS SPECIFIC dataset -- the original
        # EURUSD holdout, sealed since Gen 6 -- was never touched.
        eurusd_id = "DS-HOLDOUT-EURUSD-H1-HISTDATA-20240101-20260130"
        assert ev["datasets"][eurusd_id]["seal_status"] == "sealed"
        assert not any(k.startswith(f"{eurusd_id}:") for k in ev["authorizations"])
        assert not any(c["dataset_id"] == eurusd_id for c in ev["consumptions"])

    def test_survivor_is_not_called_an_edge(self):
        sweep = json.loads(SWEEP.read_text())
        for s in sweep["survivors"]:
            assert s["verdict"] == "DISCOVERY_SURVIVOR"
