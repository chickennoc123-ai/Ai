"""Spec Section 7 data-quality remediation tests.

Finding C-1 (ML-001-R2-IMPLEMENTATION-INTEGRITY-AUDIT.md): spec Section 7
requires weekday gaps >1 bar to be treated as a data-quality violation;
the pre-remediation implementation silently tolerated all gaps. This
suite exercises the fix directly, independent of the broader feature
test suite, covering exactly the scenarios the remediation instruction
requires: continuous data, legitimate weekend gaps, unexpected weekday
gaps, multiple weekday gaps, and boundary conditions.

Calendar reference (spec Section 7, verbatim): "FX market closed Fri
22:00 UTC - Sun 22:00 UTC; this window is excluded from continuity
checks, not treated as missing data." No other exception is defined
anywhere in the spec, and none is invented here.
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.features.fe_r2_001 import (
    FeatureEngineeringError,
    _check_weekday_gaps,
    _is_weekend_closure_time,
    build_feature_matrix,
)


def _idx(*timestamps: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(list(timestamps))).tz_localize("UTC")


class TestWeekendClosureClassification:
    """Direct unit tests of the calendar predicate itself."""

    def test_friday_before_2200_is_trading_hours(self) -> None:
        assert _is_weekend_closure_time(pd.Timestamp("2020-01-10 21:00", tz="UTC")) is False

    def test_friday_at_2200_is_closure(self) -> None:
        assert _is_weekend_closure_time(pd.Timestamp("2020-01-10 22:00", tz="UTC")) is True

    def test_saturday_is_always_closure(self) -> None:
        assert _is_weekend_closure_time(pd.Timestamp("2020-01-11 00:00", tz="UTC")) is True
        assert _is_weekend_closure_time(pd.Timestamp("2020-01-11 23:00", tz="UTC")) is True

    def test_sunday_before_2200_is_closure(self) -> None:
        assert _is_weekend_closure_time(pd.Timestamp("2020-01-12 21:00", tz="UTC")) is True

    def test_sunday_at_2200_is_trading_hours_again(self) -> None:
        assert _is_weekend_closure_time(pd.Timestamp("2020-01-12 22:00", tz="UTC")) is False

    def test_ordinary_wednesday_is_trading_hours(self) -> None:
        assert _is_weekend_closure_time(pd.Timestamp("2020-01-08 12:00", tz="UTC")) is False


class TestValidContinuousData:
    def test_no_gaps_passes(self) -> None:
        index = pd.date_range("2020-01-06", periods=120, freq="h", tz="UTC")  # Mon onward
        _check_weekday_gaps(index)  # must not raise

    def test_build_feature_matrix_accepts_continuous_data(self) -> None:
        index = pd.date_range("2020-01-06", periods=700, freq="h", tz="UTC")
        df = pd.DataFrame(
            {"open": 1.1, "high": 1.101, "low": 1.099, "close": 1.1005},
            index=index,
        )
        build_feature_matrix(df)  # must not raise


class TestLegitimateWeekendGaps:
    def test_full_weekend_closure_gap_passes(self) -> None:
        # Fri Jan 10 2020 last bar at 21:00 UTC -> reopen Sun Jan 12 22:00 UTC.
        index = _idx("2020-01-10 21:00", "2020-01-12 22:00")
        _check_weekday_gaps(index)  # must not raise

    def test_weekend_gap_followed_by_normal_weekday_bars(self) -> None:
        friday = pd.date_range("2020-01-10 00:00", "2020-01-10 21:00", freq="h", tz="UTC")
        reopen_week = pd.date_range("2020-01-12 22:00", "2020-01-14 21:00", freq="h", tz="UTC")
        index = friday.append(reopen_week)
        _check_weekday_gaps(index)  # must not raise


class TestUnexpectedWeekdayGaps:
    def test_single_weekday_gap_raises(self) -> None:
        index = _idx("2020-01-08 10:00", "2020-01-08 14:00")  # Wed, missing 11/12/13
        with pytest.raises(FeatureEngineeringError):
            _check_weekday_gaps(index)

    def test_gap_starting_before_friday_close_raises(self) -> None:
        # Last bar Fri 20:00 (missing Fri 21:00, a weekday trading hour) -> Sun 22:00.
        index = _idx("2020-01-10 20:00", "2020-01-12 22:00")
        with pytest.raises(FeatureEngineeringError):
            _check_weekday_gaps(index)

    def test_gap_ending_after_sunday_reopen_raises(self) -> None:
        # Sun 22:00 is reopen; missing Sun 23:00 is a weekday-equivalent trading hour.
        index = _idx("2020-01-10 21:00", "2020-01-12 23:00")
        with pytest.raises(FeatureEngineeringError):
            _check_weekday_gaps(index)

    def test_error_reports_violation_details(self) -> None:
        index = _idx("2020-01-08 10:00", "2020-01-08 14:00")
        with pytest.raises(FeatureEngineeringError) as exc_info:
            _check_weekday_gaps(index)
        assert exc_info.value.context["violation_count"] == 1
        assert "2020-01-08T10" in exc_info.value.context["first_violation_start"]
        assert "2020-01-08T14" in exc_info.value.context["first_violation_end"]


class TestMultipleWeekdayGaps:
    def test_two_separate_weekday_gaps_both_counted(self) -> None:
        block_a = pd.date_range("2020-01-08 00:00", "2020-01-08 09:00", freq="h", tz="UTC")
        # gap 1: missing 2020-01-08 10:00, 11:00
        block_b = pd.date_range("2020-01-08 12:00", "2020-01-09 09:00", freq="h", tz="UTC")
        # gap 2: missing 2020-01-09 10:00, 11:00
        block_c = pd.date_range("2020-01-09 12:00", "2020-01-09 18:00", freq="h", tz="UTC")
        index = block_a.append(block_b).append(block_c)

        with pytest.raises(FeatureEngineeringError) as exc_info:
            _check_weekday_gaps(index)
        assert exc_info.value.context["violation_count"] == 2

    def test_one_weekend_gap_and_one_weekday_gap_still_raises(self) -> None:
        friday = pd.date_range("2020-01-10 00:00", "2020-01-10 21:00", freq="h", tz="UTC")
        reopen_through_wednesday = pd.date_range("2020-01-12 22:00", "2020-01-15 09:00", freq="h", tz="UTC")
        # A second, unrelated weekday gap later in the same (otherwise continuous) series.
        later_block = pd.date_range("2020-01-15 12:00", "2020-01-15 18:00", freq="h", tz="UTC")
        index = friday.append(reopen_through_wednesday).append(later_block)

        with pytest.raises(FeatureEngineeringError) as exc_info:
            _check_weekday_gaps(index)
        # Only the weekday gap counts as a violation; the weekend gap does not.
        assert exc_info.value.context["violation_count"] == 1


class TestBoundaryConditions:
    def test_exactly_one_bar_width_is_not_a_gap(self) -> None:
        index = _idx("2020-01-08 10:00", "2020-01-08 11:00")
        _check_weekday_gaps(index)  # must not raise

    def test_exactly_two_bar_widths_missing_one_bar_raises(self) -> None:
        index = _idx("2020-01-08 10:00", "2020-01-08 12:00")
        with pytest.raises(FeatureEngineeringError):
            _check_weekday_gaps(index)

    def test_build_feature_matrix_raises_for_weekday_gap_end_to_end(self) -> None:
        friday = pd.date_range("2020-01-06 00:00", "2020-01-08 09:00", freq="h", tz="UTC")
        after_gap = pd.date_range("2020-01-08 13:00", "2020-01-10 00:00", freq="h", tz="UTC")
        index = friday.append(after_gap)
        df = pd.DataFrame(
            {"open": 1.1, "high": 1.101, "low": 1.099, "close": 1.1005},
            index=index,
        )
        with pytest.raises(FeatureEngineeringError):
            build_feature_matrix(df)
