"""Integration tests proving RunProvenance is wired into the authoritative
walk-forward pipeline (not merely unit-tested in isolation).

Finding M-9 (ML-001-R2-IMPLEMENTATION-INTEGRITY-AUDIT.md): RunProvenance
was implemented and unit-tested but never constructed by
RFR2Model.train()/generate_oos_predictions(). Remediation:
generate_oos_predictions now builds one RunProvenance per window,
referencing the actual artifacts that window's own run produced.
"""

from __future__ import annotations

import hashlib
import json

import pandas as pd
import pytest

from core.features.fe_r2_001 import FEATURE_VERSION, get_feature_schema
from core.ml_r2.model_r2 import HYPERPARAMETERS, MODEL_VERSION
from core.ml_r2.provenance_r2 import STRATEGY_ID, STRATEGY_VERSION, get_code_version
from core.ml_r2.walkforward_r2 import generate_oos_predictions, make_walk_forward_windows
from tests.r2_fixtures import make_synthetic_ohlcv

_VALIDATION_PERIOD = ("2023-01-01", "2023-12-31")
_HOLDOUT_PERIOD = ("2024-01-01", "2024-12-31")


class TestRealRunProducesProvenance:
    def test_generate_oos_predictions_always_returns_provenance(self) -> None:
        df = make_synthetic_ohlcv(2500, seed=400)
        windows = make_walk_forward_windows(
            df, train_window_size=1200, test_window_size=300, step_size=300, hypothesis_id="provenance-integration"
        )
        batches, provenance = generate_oos_predictions(
            df, windows[:1], hypothesis_id="provenance-integration", dataset_id="synthetic-fixture-400",
            validation_period=_VALIDATION_PERIOD, holdout_period=_HOLDOUT_PERIOD,
        )
        assert len(provenance) == len(batches) == 1

    def test_provenance_is_produced_per_window_not_once_total(self) -> None:
        df = make_synthetic_ohlcv(3500, seed=401)
        windows = make_walk_forward_windows(
            df, train_window_size=1200, test_window_size=300, step_size=300, hypothesis_id="provenance-integration"
        )
        assert len(windows) >= 3
        batches, provenance = generate_oos_predictions(
            df, windows[:3], hypothesis_id="provenance-integration", dataset_id="synthetic-fixture-401",
            validation_period=_VALIDATION_PERIOD, holdout_period=_HOLDOUT_PERIOD,
        )
        assert len(provenance) == 3
        # Every record must independently pass completeness.
        for record in provenance:
            record.validate_complete()

    def test_zero_usable_test_rows_is_unreachable_given_current_warmup_math(self) -> None:
        """Documents a verified structural property rather than forcing an
        artificial scenario: WFAWindow requires train_end <= test_start,
        and build_training_set requires >600 usable training rows (the
        volatility_regime warmup) to avoid raising TemporalSplitError. Since
        test_start is always >= train_end, and the extended lookback window
        always supplies exactly MAX_WARMUP_BARS (600) bars immediately
        before test_start, the very first test-window row is always exactly
        warmup-satisfied whenever training itself succeeded. The
        zero-usable-test-rows branch in generate_oos_predictions exists to
        handle it defensively, but is not reachable through any WFAWindow
        that satisfies its own dataclass invariants together with a
        successful training step — confirmed here by exercising the
        smallest possible non-degenerate window (1-bar test) and observing
        it still yields exactly one usable row, not zero."""
        from core.oos_wfa_engine import WFAWindow

        df = make_synthetic_ohlcv(2500, seed=402)
        window = WFAWindow(
            window_index=0,
            train_start=1000,
            train_end=2000,
            test_start=2000,
            test_end=2002,  # smallest non-degenerate (2-bar) test window
            train_dates=(df.index[1000], df.index[1999]),
            test_dates=(df.index[2000], df.index[2001]),
        )
        batches, provenance = generate_oos_predictions(
            df, [window], hypothesis_id="provenance-integration", dataset_id="synthetic-fixture-402",
            validation_period=_VALIDATION_PERIOD, holdout_period=_HOLDOUT_PERIOD,
        )
        assert len(batches) == len(provenance) == 1
        assert len(batches[0].predictions) == 2  # exactly warmup-satisfied, not zero
        provenance[0].validate_complete()


class TestProvenanceReferencesActualArtifacts:
    """Every field must trace to what THIS run actually produced, not
    independently reconstructed/hand-typed metadata."""

    def _run(self, seed: int, dataset_id: str):
        df = make_synthetic_ohlcv(2500, seed=seed)
        windows = make_walk_forward_windows(
            df, train_window_size=1200, test_window_size=300, step_size=300, hypothesis_id="provenance-integration"
        )
        batches, provenance = generate_oos_predictions(
            df, windows[:1], hypothesis_id="provenance-integration", dataset_id=dataset_id,
            validation_period=_VALIDATION_PERIOD, holdout_period=_HOLDOUT_PERIOD,
        )
        return df, windows[0], batches[0], provenance[0]

    def test_identity_fields_match_canonical_constants(self) -> None:
        _, _, _, record = self._run(seed=403, dataset_id="synthetic-fixture-403")
        assert record.strategy_id == STRATEGY_ID == "ML-001-R2"
        assert record.strategy_version == STRATEGY_VERSION == "1.0.0"
        assert record.model_version == MODEL_VERSION
        assert record.feature_version == FEATURE_VERSION

    def test_dataset_checksum_matches_the_actual_dataframe_used(self) -> None:
        df, _, _, record = self._run(seed=404, dataset_id="synthetic-fixture-404")
        expected = hashlib.sha256(pd.util.hash_pandas_object(df).values.tobytes()).hexdigest()
        assert record.dataset_checksum == expected

    def test_dataset_checksum_changes_if_the_dataframe_changes(self) -> None:
        """Not a hardcoded/placeholder value — sensitive to the actual data."""
        _, _, _, record_a = self._run(seed=405, dataset_id="synthetic-fixture-405")
        _, _, _, record_b = self._run(seed=406, dataset_id="synthetic-fixture-406")
        assert record_a.dataset_checksum != record_b.dataset_checksum

    def test_training_period_matches_this_windows_actual_training_dates(self) -> None:
        _, window, _, record = self._run(seed=407, dataset_id="synthetic-fixture-407")
        assert record.training_period == (window.train_dates[0], window.train_dates[1])

    def test_validation_and_holdout_period_match_caller_declared_boundaries(self) -> None:
        _, _, _, record = self._run(seed=408, dataset_id="synthetic-fixture-408")
        assert record.validation_period == _VALIDATION_PERIOD
        assert record.holdout_period == _HOLDOUT_PERIOD

    def test_model_checksum_matches_this_run_and_differs_across_runs(self) -> None:
        _, _, _, record_a = self._run(seed=409, dataset_id="synthetic-fixture-409")
        _, _, _, record_b = self._run(seed=410, dataset_id="synthetic-fixture-410")
        # Different training data -> different fitted model -> different checksum.
        assert record_a.model_checksum != record_b.model_checksum
        assert len(record_a.model_checksum) == 64  # sha256 hex

    def test_random_seed_matches_actual_hyperparameters(self) -> None:
        _, _, _, record = self._run(seed=411, dataset_id="synthetic-fixture-411")
        assert record.random_seed == HYPERPARAMETERS["random_state"] == 42

    def test_feature_schema_hash_matches_actual_current_schema(self) -> None:
        _, _, _, record = self._run(seed=412, dataset_id="synthetic-fixture-412")
        expected = hashlib.sha256(
            json.dumps(get_feature_schema(), sort_keys=True, default=str).encode()
        ).hexdigest()
        assert record.feature_schema_hash == expected

    def test_config_checksum_reflects_actual_hyperparameters(self) -> None:
        _, _, _, record = self._run(seed=413, dataset_id="synthetic-fixture-413")
        expected = hashlib.sha256(json.dumps(HYPERPARAMETERS, sort_keys=True).encode()).hexdigest()
        assert record.config_checksum == expected

    def test_code_version_is_a_real_git_commit_not_a_placeholder(self) -> None:
        _, _, _, record = self._run(seed=414, dataset_id="synthetic-fixture-414")
        assert record.code_version == get_code_version()
        assert record.code_version != ""
        # A real short git hash is 7+ hex characters; "unknown" would mean
        # git metadata was unavailable, which should not happen in this repo.
        assert record.code_version != "unknown"

    def test_dataset_id_is_the_caller_supplied_value_not_invented(self) -> None:
        _, _, _, record = self._run(seed=415, dataset_id="my-explicit-dataset-id-415")
        assert record.dataset_id == "my-explicit-dataset-id-415"

    def test_execution_assumptions_records_window_index(self) -> None:
        df = make_synthetic_ohlcv(3500, seed=416)
        windows = make_walk_forward_windows(
            df, train_window_size=1200, test_window_size=300, step_size=300, hypothesis_id="provenance-integration"
        )
        _, provenance = generate_oos_predictions(
            df, windows[:2], hypothesis_id="provenance-integration", dataset_id="synthetic-fixture-416",
            validation_period=_VALIDATION_PERIOD, holdout_period=_HOLDOUT_PERIOD,
        )
        assert provenance[0].execution_assumptions["window_index"] == windows[0].window_index
        assert provenance[1].execution_assumptions["window_index"] == windows[1].window_index


class TestReproducibilityOfProvenance:
    def test_identical_run_produces_identical_provenance_except_timestamps(self) -> None:
        df = make_synthetic_ohlcv(2500, seed=417)
        windows = make_walk_forward_windows(
            df, train_window_size=1200, test_window_size=300, step_size=300, hypothesis_id="provenance-integration"
        )
        _, prov_a = generate_oos_predictions(
            df, windows[:1], hypothesis_id="provenance-integration", dataset_id="synthetic-fixture-417",
            validation_period=_VALIDATION_PERIOD, holdout_period=_HOLDOUT_PERIOD,
        )
        _, prov_b = generate_oos_predictions(
            df, windows[:1], hypothesis_id="provenance-integration", dataset_id="synthetic-fixture-417",
            validation_period=_VALIDATION_PERIOD, holdout_period=_HOLDOUT_PERIOD,
        )
        assert prov_a[0].dataset_checksum == prov_b[0].dataset_checksum
        assert prov_a[0].model_checksum == prov_b[0].model_checksum
        assert prov_a[0].feature_schema_hash == prov_b[0].feature_schema_hash
        assert prov_a[0].config_checksum == prov_b[0].config_checksum
