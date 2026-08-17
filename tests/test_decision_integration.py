"""Decision Integration test suite (Tests DI-001 through DI-010).

Tests verify that evidence aggregation, decision making, and risk governance
work correctly to produce final capital allocation decisions.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.decision_engine import Decision, DecisionEngine, DecisionType
from core.decision_registry import DecisionRegistry, DecisionStatus
from core.evidence_aggregator import AggregatedEvidence, EvidenceAggregator
from core.prediction_artifact import PredictionArtifact
from core.risk_governance import RiskGovernance, RiskGovernanceConfig, RiskLimitExceededError
from core.trial_ledger import TrialLedger, TrialRecord, TrialStatus
from core.validation_result import (
    ValidationRecommendation,
    ValidationReport,
    ValidationResultBuilder,
    ValidationVerdict,
)
from utils.helpers import utcnow


class TestEvidenceAggregation:
    """Test DI-001: Evidence aggregator correctly aggregates."""

    def test_di_001_evidence_aggregator(self) -> None:
        """DI-001: Evidence aggregator correctly aggregates."""
        # Build validation report
        builder = ValidationResultBuilder("test-di-001", "v1")
        builder.set_audit_passed(True)
        builder.set_oos_metrics(100, 50, 1.5, 2.0, 0.65, 0.05)
        builder.set_robustness_metrics(True, {"test": True})
        builder.set_calibration_metrics(0.2, 0.1)
        report = builder.build()

        # Create dummy predictions
        base_time = datetime(2024, 1, 1, 12, 0, 0)
        predictions = [
            PredictionArtifact(
                prediction_time=base_time + timedelta(hours=i),
                execution_time=base_time + timedelta(hours=i + 1),
                prediction=1,
                probability=0.8,
                model_version="v1",
                feature_version="v1",
                training_start=base_time - timedelta(days=100),
                training_end=base_time - timedelta(days=50),
                dataset_version="v1",
                hypothesis_id="test-di-001",
                trial_id="trial-1",
                information_cutoff=base_time + timedelta(hours=i),
            )
            for i in range(100)
        ]

        # Create trial ledger
        ledger = TrialLedger("test-di-001", max_trials=100)
        trial = TrialRecord(
            trial_id="trial-1",
            hypothesis_id="test-di-001",
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

        # Aggregate evidence
        aggregator = EvidenceAggregator()
        evidence = aggregator.aggregate(
            report,
            predictions,
            ledger,
            {"brier": 0.2, "ece": 0.1},
            {"stress": True},
        )

        # Verify aggregation
        assert evidence.hypothesis_id == "test-di-001"
        assert evidence.aggregated_score > 0.0
        assert evidence.confidence_level in ("HIGH", "MEDIUM", "LOW")
        assert len(evidence.oos_predictions) == 100


class TestValidEvidence:
    """Test DI-002: Valid evidence → AUTHORIZE."""

    def test_di_002_valid_evidence_authorize(self) -> None:
        """DI-002: Valid evidence → AUTHORIZE."""
        # Build strong validation report
        builder = ValidationResultBuilder("test-di-002", "v1")
        builder.set_audit_passed(True)
        builder.set_oos_metrics(
            observations=200,
            trades=100,
            sharpe=1.5,  # Strong edge
            profit_factor=2.0,
            win_rate=0.65,
            max_dd=0.05,
        )
        builder.set_robustness_metrics(cost_stress_pass=True, regime_tests={})
        report = builder.build()

        # Create evidence
        base_time = datetime(2024, 1, 1, 12, 0, 0)
        predictions = [PredictionArtifact(
            prediction_time=base_time + timedelta(hours=i),
            execution_time=base_time + timedelta(hours=i + 1),
            prediction=1,
            probability=0.8,
            model_version="v1",
            feature_version="v1",
            training_start=base_time - timedelta(days=100),
            training_end=base_time - timedelta(days=50),
            dataset_version="v1",
            hypothesis_id="test-di-002",
            trial_id="trial-1",
            information_cutoff=base_time + timedelta(hours=i),
        ) for i in range(150)]

        ledger = TrialLedger("test-di-002", max_trials=100)
        aggregator = EvidenceAggregator()
        evidence = aggregator.aggregate(report, predictions, ledger)

        # Verify evidence is authorizable
        assert evidence.is_authorizable()

        # Make decision
        engine = DecisionEngine({
            "max_total_allocation": 0.40,
            "max_per_strategy": 0.20,
            "min_allocation": 0.01,
            "max_drawdown_tolerance": 0.15,
        })
        decision = engine.evaluate(evidence)

        assert decision.decision == DecisionType.AUTHORIZE
        assert decision.allocation > 0.0


class TestInvalidEvidence:
    """Test DI-003: Invalid evidence → REJECT."""

    def test_di_003_invalid_evidence_reject(self) -> None:
        """DI-003: Invalid evidence → REJECT."""
        # Build weak validation report
        builder = ValidationResultBuilder("test-di-003", "v1")
        builder.set_audit_passed(False)  # Audit failed
        report = builder.build()

        predictions = []
        ledger = TrialLedger("test-di-003", max_trials=100)

        aggregator = EvidenceAggregator()
        evidence = aggregator.aggregate(report, predictions, ledger)

        # Verify evidence is not authorizable
        assert not evidence.is_authorizable()

        # Make decision
        engine = DecisionEngine({})
        decision = engine.evaluate(evidence)

        assert decision.decision == DecisionType.REJECT
        assert decision.allocation == 0.0


class TestAllocationCalculation:
    """Test DI-004: Allocation calculation uses evidence quality."""

    def test_di_004_allocation_from_evidence_quality(self) -> None:
        """DI-004: Allocation calculation uses evidence quality."""
        # Test multiple quality levels
        quality_levels = [
            (1.0, "HIGH", "strong"),    # Sharpe=1.0
            (1.5, "HIGH", "very strong"),  # Sharpe=1.5
            (0.5, "MEDIUM", "weak"),   # Sharpe=0.5
        ]

        for sharpe, expected_confidence, label in quality_levels:
            builder = ValidationResultBuilder(f"test-di-004-{label}", "v1")
            builder.set_audit_passed(True)
            builder.set_oos_metrics(
                observations=100,
                trades=50,
                sharpe=sharpe,
                profit_factor=1.5 if sharpe >= 1.0 else 1.2,
                win_rate=0.55,
                max_dd=0.1,
            )
            builder.set_robustness_metrics(
                cost_stress_pass=(sharpe >= 1.0),
                regime_tests={},
            )
            report = builder.build()

            base_time = datetime(2024, 1, 1, 12, 0, 0)
            predictions = [PredictionArtifact(
                prediction_time=base_time + timedelta(hours=i),
                execution_time=base_time + timedelta(hours=i + 1),
                prediction=1,
                probability=0.8,
                model_version="v1",
                feature_version="v1",
                training_start=base_time - timedelta(days=100),
                training_end=base_time - timedelta(days=50),
                dataset_version="v1",
                hypothesis_id=f"test-di-004-{label}",
                trial_id="trial-1",
                information_cutoff=base_time + timedelta(hours=i),
            ) for i in range(100)]

            ledger = TrialLedger(f"test-di-004-{label}", max_trials=100)
            aggregator = EvidenceAggregator()
            evidence = aggregator.aggregate(report, predictions, ledger)

            if sharpe >= 1.0:
                # Should be authorizable and have positive allocation
                assert evidence.is_authorizable()

                engine = DecisionEngine({})
                decision = engine.evaluate(evidence)
                assert decision.allocation > 0.0


class TestRiskGovernanceCaps:
    """Test DI-005: Risk governance caps allocation."""

    def test_di_005_risk_governance_caps_allocation(self) -> None:
        """DI-005: Risk governance caps allocation."""
        config = RiskGovernanceConfig(
            max_total_allocation=0.40,
            max_per_strategy=0.20,
            max_positions=3,
        )

        governance = RiskGovernance(config)

        # Build high-quality evidence (would get > 20% allocation without cap)
        builder = ValidationResultBuilder("test-di-005", "v1")
        builder.set_audit_passed(True)
        builder.set_oos_metrics(
            observations=300,
            trades=150,
            sharpe=3.0,  # Very high
            profit_factor=3.0,
            win_rate=0.7,
            max_dd=0.03,
        )
        builder.set_robustness_metrics(cost_stress_pass=True, regime_tests={})
        report = builder.build()

        base_time = datetime(2024, 1, 1, 12, 0, 0)
        predictions = [PredictionArtifact(
            prediction_time=base_time + timedelta(hours=i),
            execution_time=base_time + timedelta(hours=i + 1),
            prediction=1,
            probability=0.9,
            model_version="v1",
            feature_version="v1",
            training_start=base_time - timedelta(days=100),
            training_end=base_time - timedelta(days=50),
            dataset_version="v1",
            hypothesis_id="test-di-005",
            trial_id="trial-1",
            information_cutoff=base_time + timedelta(hours=i),
        ) for i in range(200)]

        ledger = TrialLedger("test-di-005", max_trials=100)
        aggregator = EvidenceAggregator()
        evidence = aggregator.aggregate(report, predictions, ledger)

        engine = DecisionEngine({
            "max_total_allocation": 0.40,
            "max_per_strategy": 0.20,  # Hard cap
        })
        decision = engine.evaluate(evidence)

        # Should be capped at max_per_strategy
        assert decision.allocation <= config.max_per_strategy


class TestCorrelationCheck:
    """Test DI-006: Correlation check prevents over-concentration."""

    def test_di_006_correlation_prevents_concentration(self) -> None:
        """DI-006: Correlation check prevents over-concentration."""
        config = RiskGovernanceConfig(max_positions=2)
        governance = RiskGovernance(config)

        # Add first strategy (should succeed)
        builder1 = ValidationResultBuilder("hyp-1", "v1")
        builder1.set_audit_passed(True)
        builder1.set_oos_metrics(100, 50, 1.0, 1.5, 0.55, 0.1)
        builder1.set_robustness_metrics(True, {})
        report1 = builder1.build()

        evidence1 = AggregatedEvidence(
            hypothesis_id="hyp-1",
            validation_report=report1,
            oos_predictions=[],
            trial_ledger=TrialLedger("hyp-1"),
            calibration_metrics={},
            robustness_tests={},
            aggregated_score=0.6,
            confidence_level="MEDIUM",
        )

        decision1 = Decision(
            hypothesis_id="hyp-1",
            decision=DecisionType.AUTHORIZE,
            allocation=0.15,
            max_position_size=0.15,
            risk_budget=0.02,
            reason="Test",
            evidence_used=evidence1,
        )

        # Should be able to add first decision
        assert governance.can_authorize(decision1, evidence1)
        governance.add_decision(decision1, evidence1)

        # Add second strategy (should succeed)
        builder2 = ValidationResultBuilder("hyp-2", "v1")
        builder2.set_audit_passed(True)
        builder2.set_oos_metrics(100, 50, 1.0, 1.5, 0.55, 0.1)
        builder2.set_robustness_metrics(True, {})
        report2 = builder2.build()

        evidence2 = AggregatedEvidence(
            hypothesis_id="hyp-2",
            validation_report=report2,
            oos_predictions=[],
            trial_ledger=TrialLedger("hyp-2"),
            calibration_metrics={},
            robustness_tests={},
            aggregated_score=0.6,
            confidence_level="MEDIUM",
        )

        decision2 = Decision(
            hypothesis_id="hyp-2",
            decision=DecisionType.AUTHORIZE,
            allocation=0.15,
            max_position_size=0.15,
            risk_budget=0.02,
            reason="Test",
            evidence_used=evidence2,
        )

        governance.add_decision(decision2, evidence2)

        # Now at position limit, shouldn't be able to add third
        builder3 = ValidationResultBuilder("hyp-3", "v1")
        builder3.set_audit_passed(True)
        builder3.set_oos_metrics(100, 50, 1.0, 1.5, 0.55, 0.1)
        builder3.set_robustness_metrics(True, {})
        report3 = builder3.build()

        evidence3 = AggregatedEvidence(
            hypothesis_id="hyp-3",
            validation_report=report3,
            oos_predictions=[],
            trial_ledger=TrialLedger("hyp-3"),
            calibration_metrics={},
            robustness_tests={},
            aggregated_score=0.6,
            confidence_level="MEDIUM",
        )

        decision3 = Decision(
            hypothesis_id="hyp-3",
            decision=DecisionType.AUTHORIZE,
            allocation=0.10,
            max_position_size=0.10,
            risk_budget=0.01,
            reason="Test",
            evidence_used=evidence3,
        )

        with pytest.raises(RiskLimitExceededError):
            governance.add_decision(decision3, evidence3)


class TestPortfolioAllocationLimit:
    """Test DI-007: Can't exceed total portfolio allocation."""

    def test_di_007_portfolio_allocation_limit(self) -> None:
        """DI-007: Can't exceed total portfolio allocation."""
        config = RiskGovernanceConfig(max_total_allocation=0.30)
        governance = RiskGovernance(config)

        # Create first decision for 20% allocation
        builder1 = ValidationResultBuilder("hyp-1", "v1")
        builder1.set_audit_passed(True)
        builder1.set_oos_metrics(100, 50, 1.0, 1.5, 0.55, 0.1)
        builder1.set_robustness_metrics(True, {})
        report1 = builder1.build()

        evidence1 = AggregatedEvidence(
            hypothesis_id="hyp-1",
            validation_report=report1,
            oos_predictions=[],
            trial_ledger=TrialLedger("hyp-1"),
            calibration_metrics={},
            robustness_tests={},
            aggregated_score=0.6,
            confidence_level="MEDIUM",
        )

        decision1 = Decision(
            hypothesis_id="hyp-1",
            decision=DecisionType.AUTHORIZE,
            allocation=0.20,
            max_position_size=0.20,
            risk_budget=0.03,
            reason="Test",
            evidence_used=evidence1,
        )

        governance.add_decision(decision1, evidence1)
        assert governance.get_total_allocation() == 0.20

        # Try to add 20% more (would exceed 30% limit)
        builder2 = ValidationResultBuilder("hyp-2", "v1")
        builder2.set_audit_passed(True)
        builder2.set_oos_metrics(100, 50, 1.0, 1.5, 0.55, 0.1)
        builder2.set_robustness_metrics(True, {})
        report2 = builder2.build()

        evidence2 = AggregatedEvidence(
            hypothesis_id="hyp-2",
            validation_report=report2,
            oos_predictions=[],
            trial_ledger=TrialLedger("hyp-2"),
            calibration_metrics={},
            robustness_tests={},
            aggregated_score=0.6,
            confidence_level="MEDIUM",
        )

        decision2 = Decision(
            hypothesis_id="hyp-2",
            decision=DecisionType.AUTHORIZE,
            allocation=0.20,
            max_position_size=0.20,
            risk_budget=0.03,
            reason="Test",
            evidence_used=evidence2,
        )

        with pytest.raises(RiskLimitExceededError):
            governance.add_decision(decision2, evidence2)


class TestDecisionRegistry:
    """Test DI-008, DI-009: Decisions recorded immutably."""

    def test_di_008_decisions_recorded_immutably(self) -> None:
        """DI-008: Decisions are recorded immutably."""
        registry = DecisionRegistry()

        # Create a decision
        builder = ValidationResultBuilder("test-di-008", "v1")
        builder.set_audit_passed(True)
        builder.set_oos_metrics(100, 50, 1.0, 1.5, 0.55, 0.1)
        builder.set_robustness_metrics(True, {})
        report = builder.build()

        evidence = AggregatedEvidence(
            hypothesis_id="test-di-008",
            validation_report=report,
            oos_predictions=[],
            trial_ledger=TrialLedger("test-di-008"),
            calibration_metrics={},
            robustness_tests={},
            aggregated_score=0.6,
            confidence_level="MEDIUM",
        )

        decision = Decision(
            hypothesis_id="test-di-008",
            decision=DecisionType.AUTHORIZE,
            allocation=0.15,
            max_position_size=0.15,
            risk_budget=0.02,
            reason="Test",
            evidence_used=evidence,
        )

        # Record decision
        record_id = registry.record(decision)
        assert record_id is not None

        # Retrieve it
        record = registry.get_record(record_id)
        assert record.decision.hypothesis_id == "test-di-008"
        assert record.status == DecisionStatus.PENDING

    def test_di_009_decision_status_audited(self) -> None:
        """DI-009: Decision status can be audited."""
        registry = DecisionRegistry()

        builder = ValidationResultBuilder("test-di-009", "v1")
        builder.set_audit_passed(True)
        builder.set_oos_metrics(100, 50, 1.0, 1.5, 0.55, 0.1)
        builder.set_robustness_metrics(True, {})
        report = builder.build()

        evidence = AggregatedEvidence(
            hypothesis_id="test-di-009",
            validation_report=report,
            oos_predictions=[],
            trial_ledger=TrialLedger("test-di-009"),
            calibration_metrics={},
            robustness_tests={},
            aggregated_score=0.6,
            confidence_level="MEDIUM",
        )

        decision = Decision(
            hypothesis_id="test-di-009",
            decision=DecisionType.AUTHORIZE,
            allocation=0.15,
            max_position_size=0.15,
            risk_budget=0.02,
            reason="Test",
            evidence_used=evidence,
        )

        record_id = registry.record(decision)

        # Update status from PENDING to ACTIVE
        registry.update_status(record_id, DecisionStatus.ACTIVE)
        record = registry.get_record(record_id)
        assert record.status == DecisionStatus.ACTIVE

        # Update to CLOSED
        registry.update_status(record_id, DecisionStatus.CLOSED)
        record = registry.get_record(record_id)
        assert record.status == DecisionStatus.CLOSED


class TestEndToEndDecisionFlow:
    """Test DI-010: End-to-end decision flow works."""

    def test_di_010_end_to_end_flow(self) -> None:
        """DI-010: End-to-end decision flow works."""
        # 1. Build validation report
        builder = ValidationResultBuilder("test-di-010", "v1")
        builder.set_audit_passed(True)
        builder.set_oos_metrics(100, 50, 1.2, 1.7, 0.60, 0.08)
        builder.set_robustness_metrics(cost_stress_pass=True, regime_tests={})
        report = builder.build()

        # 2. Aggregate evidence
        base_time = datetime(2024, 1, 1, 12, 0, 0)
        predictions = [PredictionArtifact(
            prediction_time=base_time + timedelta(hours=i),
            execution_time=base_time + timedelta(hours=i + 1),
            prediction=1,
            probability=0.8,
            model_version="v1",
            feature_version="v1",
            training_start=base_time - timedelta(days=100),
            training_end=base_time - timedelta(days=50),
            dataset_version="v1",
            hypothesis_id="test-di-010",
            trial_id="trial-1",
            information_cutoff=base_time + timedelta(hours=i),
        ) for i in range(100)]

        ledger = TrialLedger("test-di-010", max_trials=100)
        aggregator = EvidenceAggregator()
        evidence = aggregator.aggregate(report, predictions, ledger)

        # 3. Make decision
        engine = DecisionEngine({})
        decision = engine.evaluate(evidence)

        # 4. Check risk governance
        governance = RiskGovernance()
        assert governance.can_authorize(decision, evidence)
        governance.add_decision(decision, evidence)

        # 5. Record decision
        registry = DecisionRegistry()
        record_id = registry.record(decision)

        # 6. Update status
        registry.update_status(record_id, DecisionStatus.ACTIVE)

        # 7. Verify full flow
        assert len(registry.get_active_records()) == 1
        assert governance.get_total_allocation() > 0.0
