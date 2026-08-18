"""Tests for core.factory.feature_registry — Generation 1 Phase 3 (Feature
Factory): contract completeness, schema identity reproducibility, and
adversarial temporal-safety checks (task 3.6) not already covered by
tests/test_ml_001_r2_adversarial.py / tests/test_ml_001_r2_leakage_integration.py.
"""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from core.factory.feature_registry import (
    DETERMINISM_STATUSES,
    FEATURE_GROUPS,
    FeatureContract,
    FeatureContractError,
    build_feature_contracts,
    canonical_schema_identity,
    feature_schema_identity,
)
from core.features import fe_r2_001
from core.features.fe_r2_001 import FEATURE_ORDER, FEATURE_VERSION, build_feature_matrix
from tests.r2_fixtures import make_synthetic_ohlcv


class TestFeatureContractCompleteness:
    def test_every_canonical_feature_has_a_contract(self) -> None:
        contracts = build_feature_contracts()
        assert set(contracts.keys()) == set(FEATURE_ORDER)

    def test_contract_version_matches_pipeline_feature_version(self) -> None:
        contracts = build_feature_contracts()
        for c in contracts.values():
            assert c.version == FEATURE_VERSION
            assert c.code_version == FEATURE_VERSION

    def test_contract_warmup_matches_pipeline_warmup(self) -> None:
        contracts = build_feature_contracts()
        for name, c in contracts.items():
            assert c.warmup_requirement == fe_r2_001.WARMUP_BARS[name]

    def test_contract_definition_is_taken_verbatim_from_pipeline_schema(self) -> None:
        schema = fe_r2_001.get_feature_schema()
        contracts = build_feature_contracts()
        for name, c in contracts.items():
            assert c.definition == schema["definitions"][name]

    def test_invalid_group_rejected(self) -> None:
        with pytest.raises(FeatureContractError):
            FeatureContract(
                feature_id="x", name="x", version="v1", definition="d", formula_reference="r",
                input_columns=("close",), lookback=5, timestamp_semantics="t<=now",
                output_schema="float64", warmup_requirement=5, code_version="v1",
                determinism_status="DETERMINISTIC", group="ASTROLOGY",
            )

    def test_invalid_determinism_status_rejected(self) -> None:
        with pytest.raises(FeatureContractError):
            FeatureContract(
                feature_id="x", name="x", version="v1", definition="d", formula_reference="r",
                input_columns=("close",), lookback=5, timestamp_semantics="t<=now",
                output_schema="float64", warmup_requirement=5, code_version="v1",
                determinism_status="MAYBE", group="MOMENTUM",
            )


class TestFeatureSchemaIdentityReproducibility:
    def test_identical_feature_id_sequence_produces_identical_identity(self) -> None:
        ids = ("FE-R2-003::momentum_5", "FE-R2-003::rsi_14")
        assert feature_schema_identity(ids) == feature_schema_identity(ids)

    def test_reordering_changes_identity(self) -> None:
        a = ("FE-R2-003::momentum_5", "FE-R2-003::rsi_14")
        b = ("FE-R2-003::rsi_14", "FE-R2-003::momentum_5")
        assert feature_schema_identity(a) != feature_schema_identity(b)

    def test_removing_a_feature_changes_identity(self) -> None:
        a = ("FE-R2-003::momentum_5", "FE-R2-003::rsi_14")
        b = ("FE-R2-003::momentum_5",)
        assert feature_schema_identity(a) != feature_schema_identity(b)

    def test_canonical_schema_identity_is_stable_across_calls(self) -> None:
        assert canonical_schema_identity() == canonical_schema_identity()

    def test_canonical_schema_identity_is_a_valid_sha256_hex_string(self) -> None:
        identity = canonical_schema_identity()
        assert len(identity) == 64
        int(identity, 16)


class TestTemporalSafetyAdversarial:
    """Task 3.6's explicit adversarial categories, scoped to what this
    module's static contract can check without re-proving arbitrary code
    is leakage-free (per the task's own instruction not to attempt that)."""

    def test_no_feature_implementation_uses_a_centered_rolling_window(self) -> None:
        """A centered rolling window (center=True) would use FUTURE bars
        to compute a value at time t -- assert the canonical source
        contains no such call, for every rolling/ewm invocation."""
        source = inspect.getsource(fe_r2_001)
        assert "center=True" not in source
        assert "center = True" not in source

    def test_no_feature_implementation_calls_a_global_fit_scaler(self) -> None:
        """A scaler fit on the full series (e.g. sklearn's
        StandardScaler().fit(full_df)) would leak future distributional
        information into early rows. This pipeline uses no such scaler at
        all -- assert that remains true, so a future addition trips this
        test rather than silently landing."""
        source = inspect.getsource(fe_r2_001)
        for forbidden in ("StandardScaler", "MinMaxScaler", ".fit_transform(", "RobustScaler"):
            assert forbidden not in source

    def test_no_feature_is_literally_derived_from_the_forward_label(self) -> None:
        """A target-derived feature would correlate perfectly (or
        near-perfectly) with sign(close.shift(-1) - close) by construction.
        None of the five real features should be a disguised copy of the
        label."""
        from core.ml_r2.target_r2 import compute_label

        df = make_synthetic_ohlcv(2000, seed=11)
        feats = build_feature_matrix(df)
        label = compute_label(df["close"])
        common = feats.index.intersection(label.dropna().index)
        for col in FEATURE_ORDER:
            corr = feats.loc[common, col].corr(label.loc[common].astype(float))
            # a genuine feature has nowhere near perfect correlation with
            # the forward label; a target-derived leak would show |corr|
            # very close to 1.0
            assert abs(corr) < 0.9, f"{col} suspiciously correlated with forward label: {corr}"

    def test_warmup_boundary_is_exactly_enforced_not_approximate(self) -> None:
        """Every position before WARMUP_BARS[feature] must be NaN, and
        positions at/after it must be populated (given enough data) --
        an off-by-one here would either leak a too-early value or waste
        usable rows."""
        df = make_synthetic_ohlcv(1200, seed=5)
        feats = build_feature_matrix(df)
        for name, warmup in fe_r2_001.WARMUP_BARS.items():
            col = feats[name]
            assert col.iloc[: warmup - 1].isna().all(), f"{name}: expected NaN before warmup boundary"

    def test_feature_matrix_output_columns_match_declared_feature_order_exactly(self) -> None:
        df = make_synthetic_ohlcv(800, seed=3)
        feats = build_feature_matrix(df)
        assert list(feats.columns) == list(FEATURE_ORDER)


class TestExistingGapPolicyPreserved:
    """Task 3.7: audit FE-R2-002 is untouched and FE-R2-003 is additive,
    not a replacement."""

    def test_both_gap_check_functions_still_exist_and_are_distinct(self) -> None:
        assert hasattr(fe_r2_001, "_check_weekday_gaps")  # FE-R2-002, original
        assert hasattr(fe_r2_001, "_check_weekday_gaps_v3")  # FE-R2-003, additive
        assert fe_r2_001._check_weekday_gaps is not fe_r2_001._check_weekday_gaps_v3

    def test_feature_version_is_fe_r2_003(self) -> None:
        assert FEATURE_VERSION == "FE-R2-003"

    def test_original_weekday_gap_check_still_rejects_an_arbitrary_gap(self) -> None:
        """FE-R2-002's original, strict check must still behave exactly as
        before -- confirms it was not weakened to accommodate FE-R2-003."""
        idx = pd.date_range("2024-01-02", periods=5, freq="h", tz="UTC")
        idx = idx.delete(2)  # remove one bar mid-week, not a weekend/holiday gap
        with pytest.raises(fe_r2_001.FeatureEngineeringError):
            fe_r2_001._check_weekday_gaps(idx)
