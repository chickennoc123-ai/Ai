"""
Cycle 5 -- event calendar contract, loader gates, and the four event families.

The families are exercised on synthetic fixtures so the machinery is proven
without spending real parameter evaluations against the multiple-testing
ledger.
"""

import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.observatory import Bar
from discovery._guards import HoldoutFirewallViolation
from discovery.event_calendar import (
    load_events, audit, EventDataError, MacroEvent, REQUIRED, MIN_INSTANCES,
)
from discovery.cycle5_events import (
    c1_pre_event, c2_surprise, c3_volatility, c4_sequence, derive_nfp_events,
    stats, gate, bar_at_or_after, EventTrade,
    MIN_TRADES, TRAIN_MIN_T, VAL_MIN_T, MIN_GROSS_OVER_COST,
)

SWEEP = REPO_ROOT / "reports/factory/discovery_cycles/cycle_05_event_sweep.json"


def _bars(n=400, start=datetime(2015, 1, 1), step=0.001):
    out, p = [], 1.0
    for i in range(n):
        o, c = p, p + step
        out.append(Bar(start + timedelta(hours=i), o, max(o, c) + 1e-5,
                       min(o, c) - 1e-5, c))
        p = c
    return out


def _ev(ts, eid="E1", name="Test Event", actual=None, forecast=None):
    return MacroEvent(ts=ts, event_id=eid, name=name, country="US", currency="USD",
                      impact="HIGH", actual=actual, forecast=forecast, source="test")


def _write_calendar(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(REQUIRED) + ["actual", "forecast",
                                                           "previous", "revision"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


def _row(ts, eid, name="CPI", impact="HIGH", **kw):
    d = {"timestamp_utc": ts, "event_id": eid, "event_name": name, "country": "US",
         "currency": "USD", "impact": impact, "source": "test",
         "actual": "", "forecast": "", "previous": "", "revision": ""}
    d.update(kw)
    return d


# --------------------------------------------------------------- loader gates

class TestCalendarContract:
    def test_missing_required_column_is_rejected(self, tmp_path):
        p = tmp_path / "c.csv"
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["timestamp_utc", "event_id"])
            w.writeheader(); w.writerow({"timestamp_utc": "2015-01-01T12:30", "event_id": "a"})
        with pytest.raises(EventDataError, match="missing required columns"):
            load_events(p)

    def test_empty_timestamp_is_rejected(self, tmp_path):
        p = _write_calendar(tmp_path / "c.csv", [_row("", "a")])
        with pytest.raises(EventDataError, match="empty timestamp_utc"):
            load_events(p)

    def test_unparseable_timestamp_is_rejected(self, tmp_path):
        p = _write_calendar(tmp_path / "c.csv", [_row("not-a-date", "a")])
        with pytest.raises(EventDataError, match="unparseable timestamp"):
            load_events(p)

    def test_duplicate_event_id_is_rejected(self, tmp_path):
        p = _write_calendar(tmp_path / "c.csv",
                            [_row("2015-01-01T12:30", "a"), _row("2015-02-01T12:30", "a")])
        with pytest.raises(EventDataError, match="duplicate event_id"):
            load_events(p)

    def test_bad_impact_value_is_rejected(self, tmp_path):
        p = _write_calendar(tmp_path / "c.csv", [_row("2015-01-01T12:30", "a", impact="HUGE")])
        with pytest.raises(EventDataError, match="impact"):
            load_events(p)

    def test_events_at_or_after_dev_end_are_dropped(self, tmp_path):
        p = _write_calendar(tmp_path / "c.csv", [_row("2015-01-01T12:30", "a"),
                                                 _row("2020-01-01T12:30", "b")])
        ev = load_events(p, dev_end=datetime(2018, 1, 1))
        assert [e.event_id for e in ev] == ["a"], "holdout-period events must not load"

    def test_holdout_path_is_refused_outright(self, tmp_path):
        with pytest.raises(HoldoutFirewallViolation):
            load_events(REPO_ROOT / "data" / "holdout" / "events.csv")

    def test_events_are_returned_in_time_order(self, tmp_path):
        p = _write_calendar(tmp_path / "c.csv", [_row("2016-01-01T12:30", "b"),
                                                 _row("2015-01-01T12:30", "a")])
        assert [e.event_id for e in load_events(p)] == ["a", "b"]


class TestCalendarAudit:
    def _many(self, n=40, minute=30, hours=(12, 13)):
        out = []
        for i in range(n):
            h = hours[i % len(hours)]
            out.append(_ev(datetime(2015, 1, 1) + timedelta(days=30 * i, hours=h,
                                                            minutes=minute),
                           eid=f"E{i}", name="CPI"))
        return out

    def test_clean_calendar_passes_all_gates(self):
        ev = self._many()
        r = audit(ev, ev[0].ts, ev[-1].ts)
        assert r["passed"], r["gates"]

    def test_flat_minute_distribution_is_flagged(self):
        ev = [_ev(datetime(2015, 1, 1) + timedelta(days=30 * i, minutes=i % 60),
                  eid=f"E{i}", name="CPI") for i in range(40)]
        r = audit(ev, ev[0].ts, ev[-1].ts)
        assert not r["gates"]["G-E4_release_minute_clustering"]["pass"]

    def test_constant_utc_hour_fails_the_dst_gate(self):
        ev = self._many(hours=(12,))
        r = audit(ev, ev[0].ts, ev[-1].ts)
        assert not r["gates"]["G-E5_dst_shift_present"]["pass"]

    def test_too_few_instances_fails(self):
        ev = self._many(n=5)
        r = audit(ev, ev[0].ts, ev[-1].ts)
        assert not r["gates"]["G-E7_sufficient_instances"]["pass"]
        assert MIN_INSTANCES == 30

    def test_empty_calendar_does_not_crash(self):
        r = audit([], datetime(2015, 1, 1), datetime(2020, 1, 1))
        assert r["passed"] is False


# ------------------------------------------------------- derivable NFP only

class TestDerivedNFP:
    def test_all_derived_events_are_first_friday(self):
        for e in derive_nfp_events(_bars(24 * 400)):
            assert e.ts.weekday() == 4 and e.ts.day <= 7

    def test_release_minute_is_thirty(self):
        assert all(e.ts.minute == 30 for e in derive_nfp_events(_bars(24 * 400)))

    def test_dst_produces_both_utc_hours(self):
        hours = {e.ts.hour for e in derive_nfp_events(_bars(24 * 400))}
        assert hours == {12, 13}, "US DST must shift the UTC release hour"

    def test_one_event_per_month(self):
        ev = derive_nfp_events(_bars(24 * 400))
        keys = [(e.ts.year, e.ts.month) for e in ev]
        assert len(keys) == len(set(keys))

    def test_source_is_marked_as_derived(self):
        assert all(e.source.startswith("derived:") for e in derive_nfp_events(_bars(24 * 200)))


# ------------------------------------------------------------------ families

class TestEventFamilies:
    def test_pre_event_enters_before_and_exits_at_release(self):
        bars = _bars(200)
        e = _ev(bars[100].ts)
        tr = c1_pre_event(bars, [e], 24, 1, 0.0)
        assert len(tr) == 1 and tr[0].realized_hours == 24.0

    def test_surprise_needs_both_actual_and_forecast(self):
        bars = _bars(200)
        assert c2_surprise(bars, [_ev(bars[100].ts, actual=5.0)], 4, "FOLLOW", 0.0) == []
        assert c2_surprise(bars, [_ev(bars[100].ts, forecast=5.0)], 4, "FOLLOW", 0.0) == []
        assert len(c2_surprise(bars, [_ev(bars[100].ts, actual=6.0, forecast=5.0)],
                               4, "FOLLOW", 0.0)) == 1

    def test_surprise_direction_follows_then_fades(self):
        bars = _bars(200)
        e = _ev(bars[100].ts, actual=6.0, forecast=5.0)     # positive surprise
        assert c2_surprise(bars, [e], 4, "FOLLOW", 0.0)[0].direction == 1
        assert c2_surprise(bars, [e], 4, "FADE", 0.0)[0].direction == -1

    def test_surprise_is_never_imputed_from_actual(self):
        e = _ev(datetime(2015, 1, 1), actual=6.0)
        assert e.surprise is None

    def test_volatility_family_needs_no_forecast(self):
        bars = _bars(200)
        tr = c3_volatility(bars, [_ev(bars[100].ts)], 4, "CONTINUATION", 0.0)
        assert len(tr) == 1

    def test_volatility_modes_are_opposite(self):
        bars = _bars(200)
        e = [_ev(bars[100].ts)]
        a = c3_volatility(bars, e, 4, "CONTINUATION", 0.0)[0]
        b = c3_volatility(bars, e, 4, "REVERSION", 0.0)[0]
        assert a.direction == -b.direction

    def test_sequence_skips_the_first_instance(self):
        bars = _bars(400)
        evs = [_ev(bars[i].ts, eid=f"E{i}") for i in (100, 200, 300)]
        assert len(c4_sequence(bars, evs, 4, "STREAK", 0.0)) == 2

    def test_realized_hold_is_measured_not_assumed(self):
        """FAIL-000030 lesson, enforced for event families too."""
        bars = _bars(200)
        tr = c3_volatility(bars, [_ev(bars[100].ts)], 12, "CONTINUATION", 0.0)
        assert tr[0].realized_hours == 12.0
        assert stats(tr, 1e-4).median_hold_hours == 12.0

    def test_cost_is_charged_once_per_trade(self):
        bars = _bars(200)
        cost = 2e-4
        t = c3_volatility(bars, [_ev(bars[100].ts)], 24, "CONTINUATION", cost)[0]
        assert abs((t.gross - t.net) - cost) < 1e-12

    def test_bar_lookup_returns_first_bar_at_or_after(self):
        bars = _bars(50)
        i = bar_at_or_after(bars, bars[10].ts - timedelta(minutes=30))
        assert i == 10
        assert bar_at_or_after(bars, bars[-1].ts + timedelta(days=5)) is None


# ---------------------------------------------------------------------- gate

class TestEventGate:
    def _s(self, **kw):
        from discovery.cycle5_events import EStats
        base = dict(n=100, gross_mean=1e-3, mean_net=1e-4, t_stat=3.0,
                    profit_factor=1.5, win_rate=0.55, gross_over_cost=5.0,
                    median_hold_hours=4.0)
        base.update(kw)
        return EStats(**base)

    def test_sub_daily_event_trade_is_allowed(self):
        """Event families are exempt from the 24h floor -- by design, declared."""
        s = self._s(median_hold_hours=1.0)
        assert gate(s, s)[0] == "DISCOVERY_SURVIVOR"

    def test_cost_dominated_still_binds_for_events(self):
        s = self._s(gross_over_cost=1.99)
        assert gate(s, s)[0] == "COST_DOMINATED"

    def test_thresholds_are_unchanged_from_cycle4(self):
        assert (MIN_TRADES, TRAIN_MIN_T, VAL_MIN_T, MIN_GROSS_OVER_COST) == (30, 2.0, 1.5, 2.0)


# ------------------------------------------------------------------ artifact

class TestCycle5Artifact:
    @pytest.fixture(scope="class")
    def sweep(self):
        return json.loads(SWEEP.read_text())

    def test_c2_is_reported_blocked_not_refuted(self, sweep):
        assert "C2_SURPRISE_REACTION" in sweep["families_blocked"]
        assert not any(r["family"].startswith("C2") for r in sweep["results"])

    def test_underpowered_symbol_skipped_before_evaluation(self, sweep):
        sk = sweep["symbols_skipped_before_evaluation"]
        assert any(s["symbol"] == "EURUSD" and s["validation_events"] < 30 for s in sk)
        assert not any(r["symbol"] == "EURUSD" for r in sweep["results"])

    def test_evaluation_count_matches_rows(self, sweep):
        assert sweep["parameter_evaluations"] == len(sweep["results"])

    def test_every_result_reports_measured_hold(self, sweep):
        for r in sweep["results"]:
            assert "median_hold_hours" in r["train"]

    def test_survivors_would_clear_every_threshold(self, sweep):
        for s in sweep["survivors"]:
            t, v = s["train"], s["validation"]
            assert t["n"] >= MIN_TRADES and v["n"] >= MIN_TRADES
            assert t["gross_over_cost"] >= MIN_GROSS_OVER_COST
            assert t["t_stat"] >= TRAIN_MIN_T and v["t_stat"] >= VAL_MIN_T


# ------------------------------------------------------------- B2 review

class TestB2Review:
    @pytest.fixture(scope="class")
    def rev(self):
        return json.loads((REPO_ROOT /
            "reports/factory/discovery_cycles/b2_independent_review.json").read_text())

    def test_review_is_diagnostic_and_does_not_adopt_a_variant(self, rev):
        assert "DIAGNOSTIC ONLY" in rev["q3_exogenous_prior"]["note"]

    def test_cross_instrument_check_was_run_on_all_six(self, rev):
        assert len(rev["q1_gold_or_usd"]["per_symbol"]) == 6

    def test_independent_gold_data_absence_is_recorded(self, rev):
        assert rev["q4_independent_data"]["independent_gold_series_available"] is False

    def test_every_probe_was_counted(self, rev):
        assert rev["total_evaluations"] == sum(
            rev[k].get("evaluations", 0) for k in rev if isinstance(rev[k], dict))

    def test_holdout_untouched_by_the_review(self):
        ev = json.loads((REPO_ROOT / "reports/factory/evidence_vault.json").read_text())
        assert ev["authorizations"] == {} and ev["consumptions"] == []


class TestCycle5Ledger:
    def test_cycle5_counted_event_and_review_evaluations(self):
        lg = json.loads((REPO_ROOT / "reports/factory/multiple_testing_ledger.json").read_text())
        c5 = next(c for c in lg["cycles"] if c["cycle_id"] == "CYCLE-05-EVENT-DRIVEN")
        sw = json.loads(SWEEP.read_text())
        b2 = json.loads((REPO_ROOT /
            "reports/factory/discovery_cycles/b2_independent_review.json").read_text())
        assert c5["parameter_evaluations"] == sw["parameter_evaluations"] + b2["total_evaluations"]

    def test_counters_never_decrease(self):
        lg = json.loads((REPO_ROOT / "reports/factory/multiple_testing_ledger.json").read_text())
        assert lg["cumulative_hypotheses_generated"] >= 65
        assert lg["cumulative_parameter_evaluations"] >= 595
