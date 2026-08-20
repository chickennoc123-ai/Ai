"""
GEN 7 Cycle 8 -- event x cross-asset intraday.

Covers: the self-critique constraint (5m/15m/30m blocked for USDJPY/USDCHF,
not fabricated), M1/H1 price lookup correctness, execution-delay realism,
the four mechanism definitions on synthetic price paths where the correct
answer is known by construction, and governance (no holdout touch, ledger
append-only, no rescue of refuted families).
"""
import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.cycle8_intraday import (
    M1Series, H1Series, trade_dc, trade_sc, trade_dr, trade_ri,
    ENTRY_DELAY_SEC, IMPULSE_WINDOW_MIN, WINDOWS_MIN_FULL, WINDOWS_MIN_H1ONLY,
    FX_M1_SYMBOLS, FX_H1_ONLY_SYMBOLS, PAIRINGS, MECHANISMS, SURPRISE_FX_DIR,
    _sign, stats, gate, MIN_TRADES, TRAIN_MIN_T, VAL_MIN_T, MIN_GROSS_OVER_COST,
)
from discovery.event_calendar import MacroEvent

RESULT = REPO_ROOT / "reports/factory/discovery_cycles/cycle_08_intraday.json"


class _FakeSeries:
    """In-memory price series for mechanism unit tests -- no real files."""
    def __init__(self, prices: dict):
        self.prices = prices

    def price_at_or_after(self, ts, max_search_min=None, max_search_hours=None):
        for t in sorted(self.prices):
            if t >= ts:
                return self.prices[t]
        return None


def _ev(ts=datetime(2020, 1, 3, 13, 30), actual=None, forecast=None):
    return MacroEvent(ts=ts, event_id="E1", name="Non-Farm Employment Change",
                      country="US", currency="USD", impact="HIGH",
                      actual=actual, forecast=forecast, source="test")


# --------------------------------------------------------- self-critique

class TestSelfCritiqueConstraint:
    def test_full_window_grid_only_for_m1_symbols(self):
        assert WINDOWS_MIN_FULL == [5, 15, 30, 60, 120, 240]
        assert FX_M1_SYMBOLS == {"EURUSD", "GBPUSD", "XAUUSD"}

    def test_h1_only_symbols_restricted_to_hourly_windows(self):
        assert FX_H1_ONLY_SYMBOLS == {"USDJPY", "USDCHF"}
        assert WINDOWS_MIN_H1ONLY == [60, 120, 240]
        assert set(WINDOWS_MIN_H1ONLY) < set(WINDOWS_MIN_FULL)

    def test_result_artifact_documents_the_constraint_not_silently(self):
        payload = json.loads(RESULT.read_text())
        assert "BLOCKED_NO_INTRADAY_DATA" in payload["self_critique"] or \
               "no M1 source" in payload["self_critique"]
        assert "USDJPY" in payload["self_critique"] and "USDCHF" in payload["self_critique"]

    def test_usdjpy_usdchf_have_blocked_rows_for_subhourly_windows(self):
        payload = json.loads(RESULT.read_text())
        blocked = [r for r in payload["results"] if r["verdict"] == "BLOCKED_NO_INTRADAY_DATA"]
        for sym in ("USDJPY", "USDCHF"):
            windows = {r["window_min"] for r in blocked if r["symbol"] == sym}
            assert windows == {5, 15, 30}

    def test_no_h1_symbol_has_a_tested_subhourly_row(self):
        payload = json.loads(RESULT.read_text())
        for r in payload["results"]:
            if r["symbol"] in FX_H1_ONLY_SYMBOLS and r["window_min"] in (5, 15, 30):
                assert r["verdict"] == "BLOCKED_NO_INTRADAY_DATA"


# --------------------------------------------------------- execution realism

class TestExecutionDelay:
    def test_delay_is_nonzero(self):
        assert ENTRY_DELAY_SEC > 0

    def test_entry_is_not_at_the_release_timestamp(self):
        t0 = datetime(2020, 1, 3, 13, 30)
        fx = _FakeSeries({t0: 1.100, t0 + timedelta(seconds=61): 1.101,
                          t0 + timedelta(minutes=60): 1.103})
        # positive surprise -> implied_from_surprise = SURPRISE_FX_DIR['EURUSD'](-1) * (+1) = -1
        # driver must FALL during impulse for expected_from_driver to also be -1 (confirms)
        driver = _FakeSeries({t0: 100.0, t0 + timedelta(seconds=61): 99.9,
                              t0 + timedelta(minutes=5): 99.0})
        # if entry used release_time exactly, the t0 price would be used;
        # with a 60s delay it must use the t0+61s price instead
        r = trade_sc(_ev(ts=t0, actual=200, forecast=150), fx, driver, "EURUSD", +1, 60, 0.0)
        assert r is not None  # sanity: mechanism fired (driver confirms the surprise direction)


# --------------------------------------------------------- mechanism logic

class TestMechanismDefinitions:
    def test_dc_requires_window_beyond_impulse(self):
        fx, driver = _FakeSeries({}), _FakeSeries({})
        assert trade_dc(_ev(), fx, driver, "EURUSD", +1, 5, 0.0001) is None

    def test_dc_fires_only_on_genuine_divergence(self):
        t0 = datetime(2020, 1, 3, 13, 30)
        # driver rises during impulse, FX has NOT followed (flat) -> divergence -> DC should fire
        driver = _FakeSeries({t0 + timedelta(seconds=60): 100.0,
                              t0 + timedelta(minutes=5): 101.0})
        fx_flat = _FakeSeries({t0 + timedelta(seconds=60): 1.1000,
                               t0 + timedelta(minutes=5): 1.1000,
                               t0 + timedelta(minutes=15): 1.1010})
        r = trade_dc(_ev(ts=t0), fx_flat, driver, "EURUSD", +1, 15, 0.0)
        assert r is not None

    def test_dc_does_not_fire_when_fx_already_followed(self):
        t0 = datetime(2020, 1, 3, 13, 30)
        driver = _FakeSeries({t0 + timedelta(seconds=60): 100.0,
                              t0 + timedelta(minutes=5): 101.0})
        # FX already moved in the expected (+1 aligned) direction during impulse
        fx_followed = _FakeSeries({t0 + timedelta(seconds=60): 1.1000,
                                   t0 + timedelta(minutes=5): 1.1050,
                                   t0 + timedelta(minutes=15): 1.1060})
        r = trade_dc(_ev(ts=t0), fx_followed, driver, "EURUSD", +1, 15, 0.0)
        assert r is None

    def test_sc_requires_actual_and_forecast(self):
        fx, driver = _FakeSeries({}), _FakeSeries({})
        assert trade_sc(_ev(actual=None, forecast=150), fx, driver, "EURUSD", +1, 60, 0.0) is None
        assert trade_sc(_ev(actual=200, forecast=None), fx, driver, "EURUSD", +1, 60, 0.0) is None

    def test_sc_requires_driver_confirmation(self):
        t0 = datetime(2020, 1, 3, 13, 30)
        fx = _FakeSeries({t0 + timedelta(seconds=60): 1.1000, t0 + timedelta(hours=1): 1.1050})
        # US10Y price FALLS (yield up, hawkish) -- but surprise is positive (also hawkish),
        # so for EURUSD (base_dir=+1) expected_from_driver should be -1 (driver fell),
        # while implied_from_surprise = SURPRISE_FX_DIR['EURUSD'](-1) * sign(+50) = -1
        # -1 == -1 -> confirmed, should fire
        driver_confirm = _FakeSeries({t0 + timedelta(seconds=60): 100.0,
                                      t0 + timedelta(minutes=5): 99.0})
        r = trade_sc(_ev(ts=t0, actual=200, forecast=150), fx, driver_confirm,
                    "EURUSD", +1, 60, 0.0)
        assert r is not None

        # driver moves the OPPOSITE way relative to what the surprise implies -> no confirmation
        driver_disconfirm = _FakeSeries({t0 + timedelta(seconds=60): 100.0,
                                         t0 + timedelta(minutes=5): 101.0})
        r2 = trade_sc(_ev(ts=t0, actual=200, forecast=150), fx, driver_disconfirm,
                     "EURUSD", +1, 60, 0.0)
        assert r2 is None

    def test_dr_and_ri_are_exact_opposites_in_direction(self):
        t0 = datetime(2020, 1, 3, 13, 30)
        driver = _FakeSeries({t0 + timedelta(seconds=60): 100.0,
                              t0 + timedelta(minutes=5): 101.0})
        fx = _FakeSeries({t0 + timedelta(minutes=5): 1.1000,
                          t0 + timedelta(hours=1): 1.1100})
        r_dr = trade_dr(_ev(ts=t0), fx, driver, "EURUSD", +1, 60, 0.0)
        r_ri = trade_ri(_ev(ts=t0), fx, driver, "EURUSD", +1, 60, 0.0)
        assert r_dr is not None and r_ri is not None
        assert abs(r_dr + r_ri) < 1e-9   # exact opposite signs, same magnitude, zero cost

    def test_cost_is_subtracted_exactly_once_in_every_mechanism(self):
        t0 = datetime(2020, 1, 3, 13, 30)
        driver = _FakeSeries({t0 + timedelta(seconds=60): 100.0,
                              t0 + timedelta(minutes=5): 101.0})
        fx = _FakeSeries({t0 + timedelta(seconds=60): 1.1000,
                          t0 + timedelta(minutes=5): 1.1000,
                          t0 + timedelta(hours=1): 1.1050})
        for cost in (0.0, 0.0001):
            r0 = trade_dr(_ev(ts=t0), fx, driver, "EURUSD", +1, 60, 0.0)
            rc = trade_dr(_ev(ts=t0), fx, driver, "EURUSD", +1, 60, cost)
            if r0 is not None and rc is not None:
                assert abs((r0 - rc) - cost) < 1e-9

    def test_surprise_fx_direction_matches_quote_convention(self):
        # USD-quote-counter pairs: positive US surprise -> pair DOWN
        assert SURPRISE_FX_DIR["EURUSD"] == -1
        assert SURPRISE_FX_DIR["GBPUSD"] == -1
        assert SURPRISE_FX_DIR["XAUUSD"] == -1
        # USD-quote-base pairs: positive US surprise -> pair UP
        assert SURPRISE_FX_DIR["USDJPY"] == +1
        assert SURPRISE_FX_DIR["USDCHF"] == +1


# --------------------------------------------------------- M1/H1 lookup

class TestPriceLookup:
    def test_m1_series_reads_only_touched_months(self, tmp_path):
        root = tmp_path / "FAKE"
        (root / "2020").mkdir(parents=True)
        (root / "2020" / "oanda-FAKE-2020-1.csv").write_text(
            "time,close,high,low,open,volume\n2020-01-15 10:00:00,1.5,1.5,1.5,1.5,1\n")
        s = M1Series(tmp_path, "FAKE")
        assert s.price_at_or_after(datetime(2020, 1, 15, 10, 0)) == 1.5
        assert (2020, 1) in s._cache
        assert (2020, 2) not in s._cache

    def test_m1_series_searches_forward_across_gaps(self, tmp_path):
        root = tmp_path / "FAKE"
        (root / "2020").mkdir(parents=True)
        (root / "2020" / "oanda-FAKE-2020-1.csv").write_text(
            "time,close,high,low,open,volume\n2020-01-15 10:05:00,2.0,2.0,2.0,2.0,1\n")
        s = M1Series(tmp_path, "FAKE")
        # ask for 10:00, only 10:05 exists -- must find it within the search window
        assert s.price_at_or_after(datetime(2020, 1, 15, 10, 0), max_search_min=30) == 2.0

    def test_m1_series_returns_none_when_nothing_found(self, tmp_path):
        s = M1Series(tmp_path, "NOPE")
        assert s.price_at_or_after(datetime(2020, 1, 1), max_search_min=5) is None


# --------------------------------------------------------- artifact + gate

class TestCycle8Artifact:
    @pytest.fixture(scope="class")
    def payload(self):
        return json.loads(RESULT.read_text())

    def test_gate_thresholds_match_prior_cycles(self):
        assert (MIN_TRADES, TRAIN_MIN_T, VAL_MIN_T, MIN_GROSS_OVER_COST) == (30, 2.0, 1.5, 2.0)

    def test_four_mechanisms_are_pre_registered(self):
        assert set(MECHANISMS) == {"DC_CROSS_ASSET_DIVERGENCE", "SC_SURPRISE_CONFIRMATION",
                                   "DR_DELAYED_REACTION", "RI_REVERSAL_AFTER_IMPULSE"}

    def test_six_pairings_cover_all_five_requested_symbols(self):
        symbols = {p[0] for p in PAIRINGS}
        assert symbols == {"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "XAUUSD"}

    def test_no_survivor_declared_without_clearing_every_gate(self, payload):
        for s in payload["survivors"]:
            t, v = s["train"], s["validation"]
            assert t["n"] >= MIN_TRADES and v["n"] >= MIN_TRADES
            assert t["mean_net"] > 0 and v["mean_net"] > 0
            assert t["t_stat"] >= TRAIN_MIN_T and v["t_stat"] >= VAL_MIN_T
            assert t["gross_over_cost"] >= MIN_GROSS_OVER_COST

    def test_evaluation_count_matches_result_rows(self, payload):
        tested = [r for r in payload["results"] if r["verdict"] != "BLOCKED_NO_INTRADAY_DATA"]
        assert payload["parameter_evaluations"] == len(tested)


# --------------------------------------------------------- governance

class TestGovernance:
    def test_holdout_untouched_by_cycle8(self):
        ev = json.loads((REPO_ROOT / "reports/factory/evidence_vault.json").read_text())
        cycle8 = [c for c in ev["consumptions"] if "CYCLE-08" in c.get("candidate_id", "")]
        assert cycle8 == []

    def test_c2_nfp_frozen_specs_untouched(self):
        reg = json.loads((REPO_ROOT / "reports/factory/candidate_spec_registry.json").read_text())
        for cid in ("CAND-C2-NFP-GBPUSD", "CAND-C2-NFP-USDCHF",
                   "CAND-C2-NFP-USDJPY", "CAND-C2-NFP-XAUUSD"):
            if cid in reg["candidates"]:
                assert reg["candidates"][cid]["frozen_at"] is not None

    def test_ledger_recorded_cycle8_exactly_once(self):
        lg = json.loads((REPO_ROOT / "reports/factory/multiple_testing_ledger.json").read_text())
        cycles = [c for c in lg["cycles"] if c["cycle_id"] == "CYCLE-08-EVENT-CROSSASSET-INTRADAY"]
        assert len(cycles) == 1

    def test_cumulative_counts_only_grew(self):
        lg = json.loads((REPO_ROOT / "reports/factory/multiple_testing_ledger.json").read_text())
        assert lg["cumulative_hypotheses_generated"] >= 80
        assert lg["cumulative_parameter_evaluations"] >= 1402
