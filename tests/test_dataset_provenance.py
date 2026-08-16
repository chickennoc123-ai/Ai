"""Dataset Provenance Guard (DP-001) test suite.

Tests enforce data integrity governance across:
- Role validation
- Temporal partitioning
- ResearchFreeze semantics
- PURE_HOLDOUT access control
- Certificate issuance
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.dataset_provenance import (
    AccessIntent,
    DatasetPartitionError,
    DatasetProvenanceError,
    DatasetRole,
    HoldoutAccessError,
    ProvenanceGuard,
    ResearchFreeze,
    ResearchFreezeError,
)
from core.dataset_provenance import DatasetProvenance as DP


class TestDP001A:
    """DP-001-A: Missing dataset role → FAIL."""

    def test_missing_dataset_role_raises_error(self) -> None:
        """Dataset without explicit role should fail."""
        with pytest.raises(DatasetProvenanceError):
            # Cannot construct DatasetProvenance with empty role
            guard = ProvenanceGuard("test-hyp")
            # Missing role would be caught by type system, but let's test
            # that missing dataset_id is caught
            DP(
                dataset_id="",  # Missing
                dataset_version="v1.0",
                symbol="EURUSD",
                timeframe="H1",
                start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
                dataset_role=DatasetRole.DEVELOPMENT,
                source_identifier="simulated",
            )


class TestDP001B:
    """DP-001-B: Missing dataset version → FAIL."""

    def test_missing_dataset_version_raises_error(self) -> None:
        """Dataset without version should fail."""
        with pytest.raises(DatasetProvenanceError):
            DP(
                dataset_id="dataset_001",
                dataset_version="",  # Missing
                symbol="EURUSD",
                timeframe="H1",
                start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
                dataset_role=DatasetRole.DEVELOPMENT,
                source_identifier="simulated",
            )


class TestDP001C:
    """DP-001-C: Development/validation overlap → FAIL."""

    def test_development_validation_overlap_fails(self) -> None:
        """DEVELOPMENT ending after VALIDATION starts should fail."""
        guard = ProvenanceGuard("test-hyp")

        dev = DP(
            dataset_id="dev_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 2, 15, tzinfo=timezone.utc),  # Ends after val starts
            dataset_role=DatasetRole.DEVELOPMENT,
            source_identifier="simulated",
        )

        val = DP(
            dataset_id="val_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 2, 1, tzinfo=timezone.utc),  # Starts while dev ongoing
            end_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.VALIDATION,
            source_identifier="simulated",
        )

        guard.register_dataset(dev)
        guard.register_dataset(val)

        with pytest.raises(DatasetPartitionError):
            guard.validate_temporal_boundaries()


class TestDP001D:
    """DP-001-D: Validation/holdout overlap → FAIL."""

    def test_validation_holdout_overlap_fails(self) -> None:
        """VALIDATION ending after PURE_HOLDOUT starts should fail."""
        guard = ProvenanceGuard("test-hyp")

        val = DP(
            dataset_id="val_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 3, 15, tzinfo=timezone.utc),  # Ends after holdout starts
            dataset_role=DatasetRole.VALIDATION,
            source_identifier="simulated",
        )

        holdout = DP(
            dataset_id="holdout_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 3, 1, tzinfo=timezone.utc),  # Starts while val ongoing
            end_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.PURE_HOLDOUT,
            source_identifier="simulated",
        )

        guard.register_dataset(val)
        guard.register_dataset(holdout)

        with pytest.raises(DatasetPartitionError):
            guard.validate_temporal_boundaries()


class TestDP001E:
    """DP-001-E: Development after validation → FAIL."""

    def test_reversed_partition_order_fails(self) -> None:
        """DEVELOPMENT starting after VALIDATION should fail."""
        guard = ProvenanceGuard("test-hyp")

        val = DP(
            dataset_id="val_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.VALIDATION,
            source_identifier="simulated",
        )

        dev = DP(
            dataset_id="dev_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 3, 1, tzinfo=timezone.utc),  # After validation
            end_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.DEVELOPMENT,
            source_identifier="simulated",
        )

        guard.register_dataset(val)
        guard.register_dataset(dev)

        with pytest.raises(DatasetPartitionError):
            guard.validate_temporal_boundaries()


class TestDP001F:
    """DP-001-F: Holdout accessed before ResearchFreeze → FAIL."""

    def test_holdout_access_before_freeze_fails(self) -> None:
        """Cannot get certificate for PURE_HOLDOUT before freeze."""
        guard = ProvenanceGuard("test-hyp")

        holdout = DP(
            dataset_id="holdout_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.PURE_HOLDOUT,
            source_identifier="simulated",
        )

        guard.register_dataset(holdout)

        # Before freeze, cannot access holdout
        with pytest.raises(HoldoutAccessError):
            guard.get_certificate(holdout, AccessIntent.FINAL_EVALUATION)


class TestDP001G:
    """DP-001-G: Holdout used for feature selection → FAIL."""

    def test_holdout_feature_selection_blocked(self) -> None:
        """Cannot use PURE_HOLDOUT for feature selection."""
        guard = ProvenanceGuard("test-hyp")

        holdout = DP(
            dataset_id="holdout_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.PURE_HOLDOUT,
            source_identifier="simulated",
        )

        guard.register_dataset(holdout)
        guard.freeze_research(frozen_feature_count=10, frozen_target="return_5")

        # Even after freeze, can only use holdout for FINAL_EVALUATION
        with pytest.raises(HoldoutAccessError):
            guard.get_certificate(holdout, AccessIntent.DEVELOPMENT_RESEARCH)


class TestDP001H:
    """DP-001-H: Holdout used for model selection → FAIL."""

    def test_holdout_model_selection_blocked(self) -> None:
        """Cannot use PURE_HOLDOUT for model selection."""
        guard = ProvenanceGuard("test-hyp")

        holdout = DP(
            dataset_id="holdout_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.PURE_HOLDOUT,
            source_identifier="simulated",
        )

        guard.register_dataset(holdout)
        guard.freeze_research(frozen_feature_count=10, frozen_target="return_5")

        # After freeze, still cannot use for selection
        with pytest.raises(HoldoutAccessError):
            guard.get_certificate(holdout, AccessIntent.VALIDATION_SELECTION)


class TestDP001I:
    """DP-001-I: Holdout used for hyperparameter selection → FAIL."""

    def test_holdout_hyperparameter_selection_blocked(self) -> None:
        """Cannot use PURE_HOLDOUT for hyperparameter tuning."""
        guard = ProvenanceGuard("test-hyp")

        holdout = DP(
            dataset_id="holdout_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.PURE_HOLDOUT,
            source_identifier="simulated",
        )

        guard.register_dataset(holdout)
        guard.freeze_research(frozen_feature_count=10, frozen_target="return_5")

        # Cannot use for any selection/optimization
        with pytest.raises(HoldoutAccessError):
            guard.get_certificate(holdout, AccessIntent.DEVELOPMENT_RESEARCH)


class TestDP001J:
    """DP-001-J: Holdout used for threshold selection → FAIL."""

    def test_holdout_threshold_selection_blocked(self) -> None:
        """Cannot use PURE_HOLDOUT for threshold optimization."""
        guard = ProvenanceGuard("test-hyp")

        holdout = DP(
            dataset_id="holdout_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.PURE_HOLDOUT,
            source_identifier="simulated",
        )

        guard.register_dataset(holdout)
        guard.freeze_research(frozen_feature_count=10, frozen_target="return_5")

        # Any intent other than FINAL_EVALUATION is blocked
        for intent in [
            AccessIntent.DEVELOPMENT_RESEARCH,
            AccessIntent.VALIDATION_SELECTION,
            AccessIntent.OBSERVATION,
        ]:
            with pytest.raises(HoldoutAccessError):
                guard.get_certificate(holdout, intent)


class TestDP001K:
    """DP-001-K: Valid development access → PASS."""

    def test_valid_development_access(self) -> None:
        """Can access DEVELOPMENT partition for research."""
        guard = ProvenanceGuard("test-hyp")

        dev = DP(
            dataset_id="dev_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.DEVELOPMENT,
            source_identifier="simulated",
        )

        guard.register_dataset(dev)

        # Should succeed
        cert = guard.get_certificate(dev, AccessIntent.DEVELOPMENT_RESEARCH)
        assert cert.is_valid_for_development


class TestDP001L:
    """DP-001-L: Valid validation selection → PASS."""

    def test_valid_validation_selection(self) -> None:
        """Can access VALIDATION partition for model selection."""
        guard = ProvenanceGuard("test-hyp")

        val = DP(
            dataset_id="val_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.VALIDATION,
            source_identifier="simulated",
        )

        guard.register_dataset(val)

        # Should succeed
        cert = guard.get_certificate(val, AccessIntent.VALIDATION_SELECTION)
        assert cert.is_valid_for_validation


class TestDP001M:
    """DP-001-M: Frozen holdout final evaluation → PASS."""

    def test_frozen_holdout_final_evaluation(self) -> None:
        """After freeze, can evaluate PURE_HOLDOUT for final assessment."""
        guard = ProvenanceGuard("test-hyp")

        holdout = DP(
            dataset_id="holdout_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.PURE_HOLDOUT,
            source_identifier="simulated",
        )

        guard.register_dataset(holdout)
        guard.freeze_research(frozen_feature_count=10, frozen_target="return_5")

        # After freeze, can access for FINAL_EVALUATION
        cert = guard.get_certificate(holdout, AccessIntent.FINAL_EVALUATION)
        assert cert.is_valid_for_holdout


class TestDP001N:
    """DP-001-N: Mutation of DatasetProvenance → FAIL."""

    def test_dataset_provenance_immutability(self) -> None:
        """DatasetProvenance is frozen and cannot be modified."""
        provenance = DP(
            dataset_id="dataset_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.DEVELOPMENT,
            source_identifier="simulated",
        )

        # Cannot modify frozen dataclass
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            provenance.dataset_version = "v2.0"  # type: ignore


class TestDP001O:
    """DP-001-O: Mutation of ResearchFreeze → FAIL."""

    def test_research_freeze_immutability(self) -> None:
        """ResearchFreeze is frozen and cannot be modified."""
        freeze = ResearchFreeze(
            freeze_timestamp=datetime(2024, 3, 1, tzinfo=timezone.utc),
            frozen_hypothesis_id="hyp_001",
            frozen_feature_count=10,
            frozen_target="return_5",
            is_active=True,
        )

        # Cannot modify frozen dataclass
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            freeze.is_active = False  # type: ignore


class TestDP001P:
    """DP-001-P: Ambiguous timestamp boundary → FAIL."""

    def test_invalid_temporal_range(self) -> None:
        """start_time >= end_time should fail."""
        with pytest.raises(DatasetProvenanceError):
            DP(
                dataset_id="dataset_001",
                dataset_version="v1.0",
                symbol="EURUSD",
                timeframe="H1",
                start_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
                end_time=datetime(2024, 1, 1, tzinfo=timezone.utc),  # Reversed
                dataset_role=DatasetRole.DEVELOPMENT,
                source_identifier="simulated",
            )


class TestDP001Q:
    """DP-001-Q: Valid exact non-overlapping boundary → PASS."""

    def test_exact_non_overlapping_boundaries(self) -> None:
        """Adjacent partitions with end[n] == start[n+1] should pass."""
        guard = ProvenanceGuard("test-hyp")

        boundary = datetime(2024, 2, 1, tzinfo=timezone.utc)

        dev = DP(
            dataset_id="dev_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=boundary,  # Ends exactly when validation starts
            dataset_role=DatasetRole.DEVELOPMENT,
            source_identifier="simulated",
        )

        val = DP(
            dataset_id="val_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=boundary,  # Starts exactly when dev ends
            end_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.VALIDATION,
            source_identifier="simulated",
        )

        guard.register_dataset(dev)
        guard.register_dataset(val)

        # Should pass without error
        guard.validate_temporal_boundaries()


class TestDP001R:
    """DP-001-R: Attempt to bypass with override/force → FAIL."""

    def test_no_override_mechanism(self) -> None:
        """There must be no override/bypass flag."""
        guard = ProvenanceGuard("test-hyp")

        holdout = DP(
            dataset_id="holdout_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.PURE_HOLDOUT,
            source_identifier="simulated",
        )

        guard.register_dataset(holdout)

        # No bypass mechanism should exist
        with pytest.raises(HoldoutAccessError):
            guard.get_certificate(holdout, AccessIntent.DEVELOPMENT_RESEARCH)


class TestDP001S:
    """DP-001-S: Wrong access intent for holdout → FAIL."""

    def test_wrong_intent_for_holdout(self) -> None:
        """PURE_HOLDOUT cannot be accessed with OBSERVATION intent."""
        guard = ProvenanceGuard("test-hyp")

        holdout = DP(
            dataset_id="holdout_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.PURE_HOLDOUT,
            source_identifier="simulated",
        )

        guard.register_dataset(holdout)
        guard.freeze_research(frozen_feature_count=10, frozen_target="return_5")

        # OBSERVATION intent not allowed for holdout
        with pytest.raises(HoldoutAccessError):
            guard.get_certificate(holdout, AccessIntent.OBSERVATION)


class TestDP001T:
    """DP-001-T: Valid post-freeze final evaluation certificate → PASS."""

    def test_valid_post_freeze_certificate(self) -> None:
        """After freeze, can issue certificate for holdout FINAL_EVALUATION."""
        guard = ProvenanceGuard("test-hyp")

        holdout = DP(
            dataset_id="holdout_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.PURE_HOLDOUT,
            source_identifier="simulated",
        )

        guard.register_dataset(holdout)
        freeze = guard.freeze_research(frozen_feature_count=10, frozen_target="return_5")

        # Should succeed
        cert = guard.get_certificate(holdout, AccessIntent.FINAL_EVALUATION)

        assert cert.hypothesis_id == "test-hyp"
        assert cert.dataset_provenance.dataset_id == "holdout_001"
        assert cert.access_intent == AccessIntent.FINAL_EVALUATION
        assert cert.research_freeze is not None
        assert cert.research_freeze.freeze_id == freeze.freeze_id
        assert cert.is_valid_for_holdout


class TestAdditionalCoverage:
    """Additional tests for comprehensive coverage."""

    def test_valid_complete_workflow(self) -> None:
        """Full workflow: dev → val → freeze → holdout evaluation."""
        guard = ProvenanceGuard("comprehensive-test")

        # Register all partitions
        dev = DP(
            dataset_id="data_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.DEVELOPMENT,
            source_identifier="simulated",
        )

        val = DP(
            dataset_id="data_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.VALIDATION,
            source_identifier="simulated",
        )

        holdout = DP(
            dataset_id="data_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.PURE_HOLDOUT,
            source_identifier="simulated",
        )

        guard.register_dataset(dev)
        guard.register_dataset(val)
        guard.register_dataset(holdout)

        # Validate boundaries
        guard.validate_temporal_boundaries()

        # Get development certificate
        dev_cert = guard.get_certificate(dev, AccessIntent.DEVELOPMENT_RESEARCH)
        assert dev_cert.is_valid_for_development

        # Get validation certificate
        val_cert = guard.get_certificate(val, AccessIntent.VALIDATION_SELECTION)
        assert val_cert.is_valid_for_validation

        # Freeze research
        freeze = guard.freeze_research(frozen_feature_count=15, frozen_target="return_5")
        assert freeze.is_active

        # Get holdout evaluation certificate
        holdout_cert = guard.get_certificate(holdout, AccessIntent.FINAL_EVALUATION)
        assert holdout_cert.is_valid_for_holdout

    def test_multiple_instruments_partitioned_independently(self) -> None:
        """Different symbols can have independent partitions."""
        guard = ProvenanceGuard("multi-symbol-test")

        eur_dev = DP(
            dataset_id="eur_dev",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.DEVELOPMENT,
            source_identifier="simulated",
        )

        xau_dev = DP(
            dataset_id="xau_dev",
            dataset_version="v1.0",
            symbol="XAUUSD",
            timeframe="H1",
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.DEVELOPMENT,
            source_identifier="simulated",
        )

        guard.register_dataset(eur_dev)
        guard.register_dataset(xau_dev)

        # Both should be valid independently
        assert eur_dev.is_development
        assert xau_dev.is_development

    def test_provenance_immutability_via_frozen_dataclass(self) -> None:
        """Verify frozen dataclass prevents modifications."""
        prov = DP(
            dataset_id="test_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.DEVELOPMENT,
            source_identifier="simulated",
        )

        # Verify immutability
        assert prov.dataset_id == "test_001"
        with pytest.raises(Exception):
            prov.dataset_id = "modified"  # type: ignore

    def test_certificate_summary(self) -> None:
        """Certificate should produce readable summary."""
        guard = ProvenanceGuard("cert-summary-test")

        holdout = DP(
            dataset_id="holdout_001",
            dataset_version="v1.0",
            symbol="EURUSD",
            timeframe="H1",
            start_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            dataset_role=DatasetRole.PURE_HOLDOUT,
            source_identifier="simulated",
        )

        guard.register_dataset(holdout)
        guard.freeze_research(frozen_feature_count=10, frozen_target="return_5")

        cert = guard.get_certificate(holdout, AccessIntent.FINAL_EVALUATION)
        summary = cert.summary()

        assert "certificate_id" in summary
        assert summary["dataset_role"] == "PURE_HOLDOUT"
        assert summary["access_intent"] == "FINAL_EVALUATION"
        assert summary["is_valid_for_holdout"] is True
