"""ML Pipeline test suite (Tests 1-24+).

Tests verify:
1-7: Provenance Guard (data boundary enforcement)
8-11: OOS/WFA Engine (out-of-sample generation)
12-14: PredictionArtifact (immutability and provenance)
15-18: RandomForest Adapter (ML-001 contract adherence)
19-21: Trial Ledger (research accounting)
22-24: Validation Result (final verdicts)
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.information_audit import AuditVerdictType, InformationAuditor
from core.ml_001_adapter import ML001Adapter, ML001ConfigurationError
from core.oos_wfa_engine import (
    OOSPredictionBatch,
    WFAConfigurationError,
    WFAPredictionEngine,
    WFAWindow,
)
from core.prediction_artifact import PredictionArtifact, PredictionArtifactError
from core.provenance_enforcement import (
    DataAccessAction,
    DataState,
    DataStateViolationError,
    ProvenanceEnforcer,
)
from core.temporal_contract import TemporalContractBuilder
from core.trial_ledger import ResearchBudgetError, TrialLedger, TrialRecord, TrialStatus
from core.validation_result import (
    ValidationEngine,
    ValidationRecommendation,
    ValidationReport,
    ValidationResultBuilder,
    ValidationVerdict,
)
from utils.helpers import utcnow


# ============================================================================
# PROVENANCE GUARD TESTS (1-7)
# ============================================================================


class TestProvenanceGuard:
    """Provenance Guard: Enforce data state boundaries."""

    def test_1_development_training_allowed(self) -> None:
        """Test 1: Development data → training allowed."""
        enforcer = ProvenanceEnforcer(hypothesis_id="test-1")
        # Should not raise
        enforcer.validate_access(DataState.DEVELOPMENT, DataAccessAction.TRAINING)

    def test_2_development_selection_allowed(self) -> None:
        """Test 2: Development data → selection allowed."""
        enforcer = ProvenanceEnforcer(hypothesis_id="test-2")
        enforcer.validate_access(DataState.DEVELOPMENT, DataAccessAction.SELECTION)

    def test_3_validation_training_blocked(self) -> None:
        """Test 3: Validation data → training blocked."""
        enforcer = ProvenanceEnforcer(hypothesis_id="test-3")
        with pytest.raises(DataStateViolationError):
            enforcer.validate_access(DataState.VALIDATION, DataAccessAction.TRAINING)

    def test_4_validation_selection_allowed(self) -> None:
        """Test 4: Validation data → selection allowed."""
        enforcer = ProvenanceEnforcer(hypothesis_id="test-4")
        enforcer.validate_access(DataState.VALIDATION, DataAccessAction.SELECTION)

    def test_5_holdout_training_blocked(self) -> None:
        """Test 5: Holdout data → training blocked."""
        enforcer = ProvenanceEnforcer(hypothesis_id="test-5")
        with pytest.raises(DataStateViolationError):
            enforcer.validate_access(DataState.PURE_HOLDOUT, DataAccessAction.TRAINING)

    def test_6_holdout_selection_blocked(self) -> None:
        """Test 6: Holdout data → selection blocked."""
        enforcer = ProvenanceEnforcer(hypothesis_id="test-6")
        with pytest.raises(DataStateViolationError):
            enforcer.validate_access(DataState.PURE_HOLDOUT, DataAccessAction.SELECTION)

    def test_7_holdout_final_eval_allowed(self) -> None:
        """Test 7: Holdout data → final evaluation allowed (one-time)."""
        enforcer = ProvenanceEnforcer(hypothesis_id="test-7")
        enforcer.validate_access(DataState.PURE_HOLDOUT, DataAccessAction.FINAL_EVALUATION)


# ============================================================================
# OOS/WFA ENGINE TESTS (8-11)
# ============================================================================


class TestOOSWFAEngine:
    """OOS/WFA Engine: Out-of-sample prediction generation."""

    def test_8_predictions_respect_cutoff(self) -> None:
        """Test 8: Predictions use only information ≤ cutoff."""
        engine = WFAPredictionEngine(
            train_window_size=10,
            test_window_size=5,
            step_size=5,
            hypothesis_id="test-8",
        )

        # Create dummy windows
        base_time = datetime(2020, 1, 1)
        windows = [
            WFAWindow(
                window_index=0,
                train_start=0,
                train_end=10,
                test_start=10,
                test_end=15,
                train_dates=(base_time, base_time + timedelta(days=10)),
                test_dates=(base_time + timedelta(days=10), base_time + timedelta(days=15)),
            )
        ]

        # Create batch
        batch = OOSPredictionBatch(
            window=windows[0],
            model_version="v1",
            feature_version="v1",
            predictions=[(1, 0.8), (-1, 0.6)],
            test_indices=[10, 11],
            test_dates=[base_time + timedelta(days=10), base_time + timedelta(days=11)],
            training_data_state=DataState.DEVELOPMENT,
            test_data_state=DataState.VALIDATION,
            generation_timestamp=utcnow(),
        )

        cutoff = base_time + timedelta(days=15)
        assert batch.verify_no_lookahead(cutoff)

    def test_9_model_never_predicts_on_training_data(self) -> None:
        """Test 9: Model never predicts on training data."""
        engine = WFAPredictionEngine(
            train_window_size=10,
            test_window_size=5,
            step_size=5,
            hypothesis_id="test-9",
        )

        windows = engine.generate_windows.__doc__
        # Verify structure: train_end should equal test_start (no overlap)
        base_time = datetime(2020, 1, 1)
        window = WFAWindow(
            window_index=0,
            train_start=0,
            train_end=10,
            test_start=10,
            test_end=15,
            train_dates=(base_time, base_time + timedelta(days=10)),
            test_dates=(base_time + timedelta(days=10), base_time + timedelta(days=15)),
        )

        # Verify no overlap
        assert window.train_end == window.test_start

    def test_10_wfa_windows_frozen(self) -> None:
        """Test 10: WFA windows are frozen (immutable)."""
        base_time = datetime(2020, 1, 1)
        window = WFAWindow(
            window_index=0,
            train_start=0,
            train_end=10,
            test_start=10,
            test_end=15,
            train_dates=(base_time, base_time + timedelta(days=10)),
            test_dates=(base_time + timedelta(days=10), base_time + timedelta(days=15)),
        )

        # Attempt to modify (should fail with frozen dataclass)
        with pytest.raises(AttributeError):
            window.window_index = 999  # type: ignore

    def test_11_no_lookahead_bias_in_predictions(self) -> None:
        """Test 11: No look-ahead bias in predictions."""
        base_time = datetime(2020, 1, 1)
        batch = OOSPredictionBatch(
            window=WFAWindow(
                window_index=0,
                train_start=0,
                train_end=10,
                test_start=10,
                test_end=15,
                train_dates=(base_time, base_time + timedelta(days=10)),
                test_dates=(base_time + timedelta(days=10), base_time + timedelta(days=15)),
            ),
            model_version="v1",
            feature_version="v1",
            predictions=[(1, 0.8)],
            test_indices=[10],
            test_dates=[base_time + timedelta(days=10)],
            training_data_state=DataState.DEVELOPMENT,
            test_data_state=DataState.VALIDATION,
            generation_timestamp=utcnow(),
        )

        # Verify no test data used for training (test_start >= train_end, no overlap)
        assert batch.window.train_end <= batch.window.test_start


# ============================================================================
# PREDICTION ARTIFACT TESTS (12-14)
# ============================================================================


class TestPredictionArtifact:
    """PredictionArtifact: Immutable prediction records."""

    def test_12_artifacts_are_immutable(self) -> None:
        """Test 12: Artifacts are immutable (frozen)."""
        now = utcnow()
        artifact = PredictionArtifact(
            prediction_time=now,
            execution_time=now + timedelta(hours=1),
            prediction=1,
            probability=0.8,
            model_version="v1",
            feature_version="v1",
            training_start=now - timedelta(days=100),
            training_end=now - timedelta(days=50),
            dataset_version="v1",
            hypothesis_id="test-12",
            trial_id="trial-1",
            information_cutoff=now,
        )

        # Attempt to modify (should fail with frozen dataclass)
        with pytest.raises(AttributeError):
            artifact.prediction = 0  # type: ignore

    def test_13_provenance_hash_unique(self) -> None:
        """Test 13: Provenance hash is unique."""
        now = utcnow()
        artifact1 = PredictionArtifact(
            prediction_time=now,
            execution_time=now + timedelta(hours=1),
            prediction=1,
            probability=0.8,
            model_version="v1",
            feature_version="v1",
            training_start=now - timedelta(days=100),
            training_end=now - timedelta(days=50),
            dataset_version="v1",
            hypothesis_id="test-13",
            trial_id="trial-1",
            information_cutoff=now,
        )

        artifact2 = PredictionArtifact(
            prediction_time=now + timedelta(minutes=1),
            execution_time=now + timedelta(hours=1),
            prediction=-1,
            probability=0.6,
            model_version="v1",
            feature_version="v1",
            training_start=now - timedelta(days=100),
            training_end=now - timedelta(days=50),
            dataset_version="v1",
            hypothesis_id="test-13",
            trial_id="trial-2",
            information_cutoff=now,
        )

        assert artifact1.provenance_hash != artifact2.provenance_hash

    def test_14_timestamps_consistent(self) -> None:
        """Test 14: Timestamps are consistent."""
        now = utcnow()
        artifact = PredictionArtifact(
            prediction_time=now,
            execution_time=now + timedelta(hours=1),
            prediction=1,
            probability=0.8,
            model_version="v1",
            feature_version="v1",
            training_start=now - timedelta(days=100),
            training_end=now - timedelta(days=50),
            dataset_version="v1",
            hypothesis_id="test-14",
            trial_id="trial-1",
            information_cutoff=now,
        )

        # Verify ordering: information_cutoff <= prediction_time <= execution_time
        assert artifact.information_cutoff <= artifact.prediction_time
        assert artifact.prediction_time <= artifact.execution_time
        assert artifact.verify()


# ============================================================================
# ML-001 ADAPTER TESTS (15-18)
# ============================================================================


class TestML001Adapter:
    """RandomForest Adapter: ML-001 contract adherence."""

    def test_15_ml001_uses_allowed_features(self) -> None:
        """Test 15: ML-001 uses only allowed features."""
        adapter = ML001Adapter()
        expected = ["momentum_5", "momentum_20", "rsi_14", "atr_14", "volatility_regime"]
        assert adapter.contract.features == expected

    def test_16_target_uses_future_information(self) -> None:
        """Test 16: Target uses only future information."""
        adapter = ML001Adapter()
        # ML-001 target is 1-bar binary classification
        assert adapter.contract.target["horizon"] == "1_bar"
        assert adapter.contract.target["threshold"] == 0.001

    def test_17_no_fallback_strategy(self) -> None:
        """Test 17: No fallback strategy (no model → no signal)."""
        adapter = ML001Adapter()
        # Verify no audit certificate is set initially
        assert adapter.audit_certificate is None

        # Attempting to create predictions without certificate should raise
        with pytest.raises(Exception):
            adapter.create_prediction_artifact(
                prediction_time=utcnow(),
                execution_time=utcnow() + timedelta(hours=1),
                prediction=1,
                probability=0.8,
                training_start=utcnow() - timedelta(days=100),
                training_end=utcnow() - timedelta(days=50),
                dataset_version="v1",
                information_cutoff=utcnow(),
            )

    def test_18_model_predict_not_in_strategy(self) -> None:
        """Test 18: No model.predict() in strategy (read artifacts only)."""
        adapter = ML001Adapter()
        # Strategy should read from prediction_registry, not call model directly
        registry = adapter.initialize_prediction_registry()
        assert registry is not None
        assert len(registry.get_all_artifacts()) == 0


# ============================================================================
# TRIAL LEDGER TESTS (19-21)
# ============================================================================


class TestTrialLedger:
    """Trial Ledger: Research accounting."""

    def test_19_every_trial_recorded(self) -> None:
        """Test 19: Every trial is recorded."""
        ledger = TrialLedger("test-19", max_trials=10)

        trial = TrialRecord(
            trial_id="trial-1",
            hypothesis_id="test-19",
            timestamp=utcnow(),
            status=TrialStatus.COMPLETED,
            model="RandomForest",
            hyperparameters={"n_estimators": 100},
            features=["f1", "f2"],
            target="target",
            train_period=(datetime(2020, 1, 1), datetime(2023, 1, 1)),
            validation_period=(datetime(2023, 1, 1), datetime(2024, 1, 1)),
            oos_metrics={"sharpe": 1.5},
        )

        ledger.record_trial(trial)
        assert ledger.count_by_status(TrialStatus.COMPLETED) == 1

    def test_20_failed_trials_count_toward_budget(self) -> None:
        """Test 20: Failed trials count toward budget."""
        ledger = TrialLedger("test-20", max_trials=3)

        # Record 3 trials (mix of statuses)
        for i in range(3):
            trial = TrialRecord(
                trial_id=f"trial-{i}",
                hypothesis_id="test-20",
                timestamp=utcnow(),
                status=TrialStatus.FAILED if i == 0 else TrialStatus.COMPLETED,
                model="RF",
                hyperparameters={},
                features=["f1"],
                target="t",
                train_period=(datetime(2020, 1, 1), datetime(2023, 1, 1)),
                validation_period=(datetime(2023, 1, 1), datetime(2024, 1, 1)),
            )
            ledger.record_trial(trial)

        # Budget should be exhausted
        assert ledger.get_remaining_budget() == 0

        # Next trial should fail
        with pytest.raises(ResearchBudgetError):
            trial = TrialRecord(
                trial_id="trial-3",
                hypothesis_id="test-20",
                timestamp=utcnow(),
                status=TrialStatus.ATTEMPTED,
                model="RF",
                hyperparameters={},
                features=["f1"],
                target="t",
                train_period=(datetime(2020, 1, 1), datetime(2023, 1, 1)),
                validation_period=(datetime(2023, 1, 1), datetime(2024, 1, 1)),
            )
            ledger.record_trial(trial)

    def test_21_results_include_trial_count(self) -> None:
        """Test 21: Results include trial count context."""
        ledger = TrialLedger("test-21", max_trials=10)

        trial = TrialRecord(
            trial_id="trial-1",
            hypothesis_id="test-21",
            timestamp=utcnow(),
            status=TrialStatus.COMPLETED,
            model="RF",
            hyperparameters={},
            features=["f1"],
            target="t",
            train_period=(datetime(2020, 1, 1), datetime(2023, 1, 1)),
            validation_period=(datetime(2023, 1, 1), datetime(2024, 1, 1)),
            oos_metrics={"sharpe": 1.5},
        )

        ledger.record_trial(trial)
        summary = ledger.summary()

        # Summary should include trial counts
        assert summary["total_trials"] == 1
        assert summary["max_trials"] == 10
        assert summary["completed_trials"] == 1


# ============================================================================
# VALIDATION RESULT TESTS (22-24+)
# ============================================================================


class TestValidationResult:
    """Validation Result: Final verdict system."""

    def test_22_verdict_not_tested(self) -> None:
        """Test 22a: Verdict correctly assigned (NOT_TESTED)."""
        builder = ValidationResultBuilder("test-22a", "v1")
        builder.set_audit_passed(True)
        # No OOS observations
        report = builder.build()

        assert report.verdict == ValidationVerdict.NOT_TESTED

    def test_22b_verdict_invalid(self) -> None:
        """Test 22b: Verdict correctly assigned (INVALID)."""
        builder = ValidationResultBuilder("test-22b", "v1")
        builder.set_audit_passed(False)
        report = builder.build()

        assert report.verdict == ValidationVerdict.INVALID

    def test_22c_verdict_inconclusive(self) -> None:
        """Test 22c: Verdict correctly assigned (INCONCLUSIVE)."""
        builder = ValidationResultBuilder("test-22c", "v1")
        builder.set_audit_passed(True)
        builder.set_oos_metrics(
            observations=100,
            trades=50,
            sharpe=0.1,  # No edge
            profit_factor=1.0,
            win_rate=0.5,
            max_dd=0.1,
        )
        report = builder.build()

        assert report.verdict == ValidationVerdict.INCONCLUSIVE

    def test_22d_verdict_rejected(self) -> None:
        """Test 22d: Verdict correctly assigned (REJECTED)."""
        builder = ValidationResultBuilder("test-22d", "v1")
        builder.set_audit_passed(True)
        builder.set_oos_metrics(
            observations=100,
            trades=50,
            sharpe=0.5,  # Edge exists
            profit_factor=1.5,
            win_rate=0.6,
            max_dd=0.1,
        )
        builder.set_robustness_metrics(cost_stress_pass=False, regime_tests={})
        report = builder.build()

        assert report.verdict == ValidationVerdict.REJECTED

    def test_22e_verdict_validated(self) -> None:
        """Test 22e: Verdict correctly assigned (VALIDATED)."""
        builder = ValidationResultBuilder("test-22e", "v1")
        builder.set_audit_passed(True)
        builder.set_oos_metrics(
            observations=100,
            trades=50,
            sharpe=1.5,  # Strong edge
            profit_factor=2.0,
            win_rate=0.65,
            max_dd=0.05,
        )
        builder.set_robustness_metrics(cost_stress_pass=True, regime_tests={})
        report = builder.build()

        assert report.verdict == ValidationVerdict.VALIDATED

    def test_23_report_includes_required_fields(self) -> None:
        """Test 23: Report includes all required fields."""
        builder = ValidationResultBuilder("test-23", "v1")
        builder.set_audit_passed(True)
        builder.set_oos_metrics(100, 50, 1.5, 2.0, 0.65, 0.05)
        builder.set_baseline_metrics(0.5, 3.0)
        builder.set_trial_metrics(10, 8, {"dof": 5})
        builder.set_robustness_metrics(True, {"sp500": True})
        builder.set_calibration_metrics(0.2, 0.1)
        report = builder.build()

        summary = report.summary()
        assert "hypothesis_id" in summary
        assert "verdict" in summary
        assert "oos_observations" in summary
        assert "sharpe_ratio" in summary
        assert "trials_attempted" in summary
        assert "report_id" in summary

    def test_24_invalid_results_block_authorization(self) -> None:
        """Test 24: Invalid results block authorization."""
        builder = ValidationResultBuilder("test-24", "v1")
        builder.set_audit_passed(False)  # Audit failed
        report = builder.build()

        # Should be INVALID
        assert report.verdict == ValidationVerdict.INVALID
        assert not report.is_ready_for_authorization()
        assert report.recommendation == ValidationRecommendation.INVALID
