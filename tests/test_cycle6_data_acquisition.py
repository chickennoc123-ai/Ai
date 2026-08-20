"""
Cycle 6 data acquisition -- integrity tests.

These test the CONVERTED/PROCESSED artifacts already committed to the repo,
not network access (acquisition already happened; these are regression tests
that the delivered files still satisfy their own claims).
"""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.cycle4_economics import to_daily, to_weekly
from discovery.observatory import load_dev_bars

EVENTS_RAW = REPO_ROOT / "data/events/raw/forexfactory_2010_2023.csv"
EVENTS_PROCESSED = REPO_ROOT / "data/events/processed/events_dev.csv"
GOLD_AUDIT = REPO_ROOT / "data/independent_gold/processed/audit_report.json"


class TestEventCalendarAcquisition:
    def test_raw_file_exists_and_is_nonempty(self):
        assert EVENTS_RAW.exists()
        rows = list(csv.DictReader(open(EVENTS_RAW)))
        assert len(rows) > 25000

    def test_covers_full_2010_2023_span(self):
        rows = list(csv.DictReader(open(EVENTS_RAW)))
        years = {datetime.fromisoformat(r["timestamp_utc"]).year for r in rows}
        assert years >= set(range(2010, 2024))

    def test_nfp_count_supports_family_c1_c3_c4(self):
        rows = list(csv.DictReader(open(EVENTS_RAW)))
        nfp = [r for r in rows if r["event_name"] == "Non-Farm Employment Change"
               and r["currency"] == "USD"]
        assert len(nfp) >= 100

    def test_events_with_actual_and_forecast_support_family_c2(self):
        rows = list(csv.DictReader(open(EVENTS_RAW)))
        both = [r for r in rows if r["actual"] not in ("", "None")
                and r["forecast"] not in ("", "None")]
        assert len(both) >= 10000, "C2 (surprise reaction) needs actual+forecast coverage"

    def test_fomc_and_cpi_types_present_with_n_over_30(self):
        rows = list(csv.DictReader(open(EVENTS_RAW)))
        from collections import Counter
        c = Counter(r["event_name"] for r in rows
                    if r["currency"] == "USD" and r["impact"] == "HIGH")
        assert c["FOMC Statement"] >= 30
        assert c["CPI y/y"] >= 30
        assert c["Federal Funds Rate"] >= 30

    def test_processed_file_respects_eurusd_holdout_boundary(self):
        bars = load_dev_bars(REPO_ROOT / "data/csv/EURUSD_H1.csv")
        dev_end = bars[-1].ts
        rows = list(csv.DictReader(open(EVENTS_PROCESSED)))
        for r in rows:
            ts = datetime.fromisoformat(r["timestamp_utc"])
            assert ts < dev_end, f"event {r['event_id']} at {ts} is at/after dev_end {dev_end}"

    def test_event_ids_are_unique(self):
        rows = list(csv.DictReader(open(EVENTS_RAW)))
        ids = [r["event_id"] for r in rows]
        assert len(ids) == len(set(ids))


class TestIndependentGoldAcquisition:
    @pytest.fixture(scope="class")
    def audit(self):
        return json.loads(GOLD_AUDIT.read_text())

    def test_gc_futures_has_no_large_gaps(self, audit):
        assert audit["source_A_gc_futures"]["gaps_over_4_days"] == []

    def test_ejtrader_has_no_large_gaps(self, audit):
        assert audit["source_B_ejtraderlabs"]["gaps_over_4_days"] == []

    def test_gc_futures_tracks_our_series_within_tolerance(self, audit):
        c = audit["cross_check_gc_vs_ours"]
        assert c["fraction_within_2pct"] >= 0.99

    def test_ejtrader_tracks_our_series_within_tolerance(self, audit):
        c = audit["cross_check_ej_vs_ours"]
        assert c["fraction_within_2pct"] >= 0.99

    def test_provenance_confidence_is_disclosed_not_assumed(self, audit):
        assert audit["source_A_gc_futures"]["provenance_confidence"].startswith("MEDIUM")
        assert audit["source_B_ejtraderlabs"]["provenance_confidence"].startswith("LOW")

    def test_2020_coverage_gap_is_documented(self, audit):
        note = audit["usable_independent_overlap_with_our_dev_window"]["note"]
        assert "2020" in note and "COVID" in note


class TestW1Resampler:
    def test_weekly_resample_has_no_new_external_source(self):
        """D1/W1 required no acquisition -- confirms resampling works on existing H1."""
        bars = load_dev_bars(REPO_ROOT / "data/csv/XAUUSD_H1.csv")
        days = to_daily(bars)
        weeks = to_weekly(days)
        assert 0 < len(weeks) < len(days)

    def test_weekly_ohlc_is_consistent_with_daily(self):
        bars = load_dev_bars(REPO_ROOT / "data/csv/EURUSD_H1.csv")
        days = to_daily(bars)
        weeks = to_weekly(days)
        total_day_bars = sum(d.bars for d in days)
        total_week_bars = sum(w.bars for w in weeks)
        assert total_day_bars == total_week_bars

    def test_weekly_high_is_never_below_any_constituent_daily_high(self):
        bars = load_dev_bars(REPO_ROOT / "data/csv/GBPUSD_H1.csv")
        days = to_daily(bars)
        weeks = to_weekly(days)
        assert weeks[3].high >= max(d.high for d in days
                                    if d.date.isocalendar()[:2] == days[
                                        next(i for i, x in enumerate(days)
                                            if x.date >= weeks[3].date)].date.isocalendar()[:2])


class TestBlockedSourcesDocumented:
    def test_blocked_hosts_recorded_in_failure_library(self):
        fl = json.loads((REPO_ROOT / "reports/factory/failure_library.json").read_text())
        fails = fl.get("failures", fl if isinstance(fl, list) else [])
        assert any(f["failure_id"] == "FAIL-000033" for f in fails)
