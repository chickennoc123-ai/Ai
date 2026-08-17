"""Integration tests proving assert_no_leakage is wired into the
authoritative training/walk-forward pipeline (not merely unit-tested
in isolation).

Finding M-1 (ML-001-R2-IMPLEMENTATION-INTEGRITY-AUDIT.md): assert_no_leakage
existed and was tested but was never called from any production code
path. Remediation: core.ml_r2.target_r2.build_training_set is now the
sole authoritative entry point from raw OHLCV to a trainable (X, y), and
it unconditionally calls assert_no_leakage before returning. Both
core.ml_r2.walkforward_r2.generate_oos_predictions (the walk-forward
path) route through it.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from core.ml_r2 import target_r2 as target_r2_module
from core.ml_r2.target_r2 import LabelConstructionError, build_training_set, compute_label
from core.ml_r2.walkforward_r2 import generate_oos_predictions, make_walk_forward_windows
from tests.r2_fixtures import make_synthetic_ohlcv

#: Captured before any patching, so tampering side-effects can compute the
#: TRUE label independently of whatever mock later replaces the module-level
#: name — otherwise assert_no_leakage's own internal recomputation call
#: would also be tampered identically, defeating the test.
_REAL_COMPUTE_LABEL = target_r2_module.compute_label


def _tamper_first_call_only(bad_value: float):
    """Return a side_effect: 1st call (build_training_set's own labels
    assignment) is tampered; every subsequent call (assert_no_leakage's
    independent ground-truth recomputation) returns the true labels."""
    state = {"count": 0}

    def _side_effect(close: pd.Series) -> pd.Series:
        state["count"] += 1
        real = _REAL_COMPUTE_LABEL(close)
        if state["count"] == 1:
            tampered = real.copy()
            tampered.loc[real.notna()] = bad_value
            return tampered
        return real

    return _side_effect


class TestCleanDataProceeds:
    def test_build_training_set_succeeds_on_clean_data(self) -> None:
        """A. Clean feature data: pipeline proceeds."""
        df = make_synthetic_ohlcv(800, seed=300)
        X, y = build_training_set(df)
        assert len(X) > 0
        assert len(X) == len(y)

    def test_generate_oos_predictions_succeeds_end_to_end_on_clean_data(self) -> None:
        df = make_synthetic_ohlcv(2500, seed=301)
        windows = make_walk_forward_windows(
            df, train_window_size=1200, test_window_size=300, step_size=300, hypothesis_id="leakage-integration-test"
        )
        batches, provenance = generate_oos_predictions(
            df, windows[:1], hypothesis_id="leakage-integration-test", dataset_id="synthetic-fixture-301",
            validation_period=("2023-01-01", "2023-12-31"), holdout_period=("2024-01-01", "2024-12-31"),
        )
        assert len(batches) == 1
        assert len(provenance) == 1


class TestContaminatedDataFailsClosed:
    def test_build_training_set_raises_when_labels_are_tampered(self) -> None:
        """B. Intentionally contaminated feature/label pairing: pipeline fails.

        Patches compute_label (as build_training_set calls it) to return a
        label series that does NOT correspond to TARGET-R2-001's true
        definition — simulating a leakage-introducing bug elsewhere in the
        pipeline. assert_no_leakage must catch this and the function must
        raise, not silently return a corrupted (X, y).
        """
        df = make_synthetic_ohlcv(800, seed=302)

        with patch("core.ml_r2.target_r2.compute_label", side_effect=_tamper_first_call_only(0.0)):
            with pytest.raises(LabelConstructionError):
                build_training_set(df)

    def test_generate_oos_predictions_fails_closed_on_tampered_labels(self) -> None:
        """The walk-forward path inherits the same fail-closed guarantee,
        since it routes through build_training_set for every window."""
        df = make_synthetic_ohlcv(2500, seed=303)
        windows = make_walk_forward_windows(
            df, train_window_size=1200, test_window_size=300, step_size=300, hypothesis_id="leakage-integration-test"
        )

        with patch("core.ml_r2.target_r2.compute_label", side_effect=_tamper_first_call_only(1.0)):
            with pytest.raises(LabelConstructionError):
                generate_oos_predictions(
                    df, windows[:1], hypothesis_id="leakage-integration-test", dataset_id="synthetic-fixture-303",
                    validation_period=("2023-01-01", "2023-12-31"), holdout_period=("2024-01-01", "2024-12-31"),
                )


class TestLabelFutureShiftRemainsPermitted:
    def test_compute_label_future_shift_is_not_treated_as_a_violation(self) -> None:
        """C. The target's legitimate close.shift(-1) is permitted because it
        belongs to label construction, not feature construction — the
        pipeline must not (and does not) flag this as leakage."""
        df = make_synthetic_ohlcv(800, seed=304)
        # This must succeed: compute_label's own shift(-1) is exactly what
        # assert_no_leakage recomputes and compares against — it is the
        # ground truth, not a violation of it.
        X, y = build_training_set(df)
        assert len(X) > 0


class TestLeakageAssertionActuallyExecutes:
    def test_assert_no_leakage_is_called_during_build_training_set(self) -> None:
        """D. Leakage assertion actually executes during a normal pipeline run."""
        df = make_synthetic_ohlcv(800, seed=305)
        with patch(
            "core.ml_r2.target_r2.assert_no_leakage", wraps=target_r2_module.assert_no_leakage
        ) as spy:
            build_training_set(df)
        spy.assert_called_once()

    def test_assert_no_leakage_is_called_for_every_walk_forward_window(self) -> None:
        df = make_synthetic_ohlcv(3500, seed=306)
        windows = make_walk_forward_windows(
            df, train_window_size=1200, test_window_size=300, step_size=300, hypothesis_id="leakage-integration-test"
        )
        assert len(windows) >= 2

        with patch(
            "core.ml_r2.target_r2.assert_no_leakage", wraps=target_r2_module.assert_no_leakage
        ) as spy:
            generate_oos_predictions(
                df, windows[:2], hypothesis_id="leakage-integration-test", dataset_id="synthetic-fixture-306",
                validation_period=("2023-01-01", "2023-12-31"), holdout_period=("2024-01-01", "2024-12-31"),
            )
        assert spy.call_count == 2  # once per window, not merely once total
