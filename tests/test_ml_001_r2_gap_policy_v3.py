"""FE-R2-003 gap-policy tests.

Covers the corrected weekend-closure window and the explicit holiday/
anomaly exception list added to unblock real EURUSD/GBPUSD H1 data (see
ML-001-REAL-MARKET-GAP-SEMANTICS-AUDIT.md and
ML-001-PHASE-1A-TEMPORAL-SEMANTICS-CONTRACT.md). FE-R2-002's
``_check_weekday_gaps`` is untouched and remains covered by
``tests/test_ml_001_r2_data_quality.py`` — these tests exercise only the
new v3 function and its narrower admission surface.
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.features.fe_r2_001 import (
    FeatureEngineeringError,
    _check_weekday_gaps_v3,
    _is_corrected_weekend_closure_time,
)


def _idx(*timestamps: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(list(timestamps))).tz_localize("UTC")


class TestCorrectedWeekendPredicate:
    def test_saturday_before_close_hour_is_trading(self) -> None:
        assert _is_corrected_weekend_closure_time(pd.Timestamp("2020-01-11 00:00", tz="UTC")) is False

    def test_saturday_at_close_hour_is_closure(self) -> None:
        assert _is_corrected_weekend_closure_time(pd.Timestamp("2020-01-11 01:00", tz="UTC")) is True

    def test_sunday_is_always_closure(self) -> None:
        assert _is_corrected_weekend_closure_time(pd.Timestamp("2020-01-12 12:00", tz="UTC")) is True

    def test_monday_before_reopen_hour_is_closure(self) -> None:
        assert _is_corrected_weekend_closure_time(pd.Timestamp("2020-01-13 04:00", tz="UTC")) is True

    def test_monday_at_reopen_hour_is_trading(self) -> None:
        assert _is_corrected_weekend_closure_time(pd.Timestamp("2020-01-13 05:00", tz="UTC")) is False

    def test_ordinary_wednesday_is_trading(self) -> None:
        assert _is_corrected_weekend_closure_time(pd.Timestamp("2020-01-08 12:00", tz="UTC")) is False


class TestCorrectedWeekendGapAdmission:
    def test_full_corrected_weekend_closure_passes(self) -> None:
        # Sat 2020-01-11 00:00 (trading) -> Mon 2020-01-13 05:00 (reopen).
        index = _idx("2020-01-11 00:00", "2020-01-13 05:00")
        log = _check_weekday_gaps_v3(index)
        assert len(log) == 1
        assert "corrected_weekend_closure" in log[0]["reasons"]

    def test_gap_extending_before_saturday_close_hour_still_raises(self) -> None:
        # Missing Friday-equivalent hour (Sat 00:00 is trading under v3) -> violation.
        index = _idx("2020-01-10 20:00", "2020-01-13 05:00")
        with pytest.raises(FeatureEngineeringError):
            _check_weekday_gaps_v3(index)

    def test_gap_extending_past_monday_reopen_hour_still_raises(self) -> None:
        index = _idx("2020-01-11 01:00", "2020-01-13 06:00")
        with pytest.raises(FeatureEngineeringError):
            _check_weekday_gaps_v3(index)


class TestAdmittedHolidayWindows:
    def test_christmas_2019_window_passes(self) -> None:
        # Exact audited real-data boundary (EURUSD_H1.csv): last pre-holiday
        # bar 2019-12-25 01:00, first post-holiday bar 2019-12-26 11:00.
        index = _idx("2019-12-25T01:00", "2019-12-26T11:00")
        log = _check_weekday_gaps_v3(index)
        assert len(log) == 1
        assert "Christmas 2019" in log[0]["reasons"]

    def test_isolated_2016_03_22_gap_passes(self) -> None:
        # Exact audited real-data boundary (EURUSD_H1.csv).
        index = _idx("2016-03-22T20:00", "2016-03-22T22:00")
        log = _check_weekday_gaps_v3(index)
        assert len(log) == 1

    def test_gap_one_hour_outside_admitted_holiday_window_still_raises(self) -> None:
        # One hour wider than the real, audited 2016-03-22 admitted window.
        index = _idx("2016-03-22T18:00", "2016-03-22T23:00")
        with pytest.raises(FeatureEngineeringError):
            _check_weekday_gaps_v3(index)


class TestStillRejectsArbitraryGaps:
    def test_arbitrary_weekday_gap_still_rejected(self) -> None:
        index = _idx("2020-01-08 10:00", "2020-01-08 14:00")
        with pytest.raises(FeatureEngineeringError):
            _check_weekday_gaps_v3(index)

    def test_no_gap_passes_with_empty_log(self) -> None:
        index = pd.date_range("2020-01-06", periods=120, freq="h", tz="UTC")
        assert _check_weekday_gaps_v3(index) == []
