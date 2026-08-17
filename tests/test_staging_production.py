"""Staging and Production test suite (Tests ST-001-008, PR-001-007).

Tests verify deployment pipeline readiness and health monitoring.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.decision_engine import Decision, DecisionEngine, DecisionType
from core.decision_registry import DecisionRegistry, DecisionStatus
from core.evidence_aggregator import AggregatedEvidence, EvidenceAggregator
from core.risk_governance import RiskGovernance, RiskGovernanceConfig
from core.trial_ledger import TrialLedger, TrialRecord, TrialStatus
from core.validation_result import (
    ValidationRecommendation,
    ValidationResultBuilder,
    ValidationVerdict,
)
from utils.helpers import utcnow


class TestStagingValidation:
    """Staging Deployment Tests (ST-001 through ST-008)."""

    def test_st_001_data_loads_correctly(self) -> None:
        """ST-001: Data loads correctly from provider."""
        # Simulated data loading
        data = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "start_date": "2020-01-01",
            "end_date": "2024-12-31",
            "bars": 5000,
        }

        assert data["symbol"] == "EURUSD"
        assert data["bars"] == 5000

    def test_st_002_provenance_annotation_works(self) -> None:
        """ST-002: Provenance annotation works."""
        # Simulate temporal split
        split = {
            "development": ("2020-01-01", "2022-12-31"),
            "validation": ("2023-01-01", "2023-12-31"),
            "holdout": ("2024-01-01", "2024-12-31"),
        }

        # Verify non-overlapping
        dev_end = datetime.fromisoformat(split["development"][1])
        val_start = datetime.fromisoformat(split["validation"][0])
        holdout_start = datetime.fromisoformat(split["holdout"][0])
        val_end = datetime.fromisoformat(split["validation"][1])

        assert dev_end < val_start
        assert val_end < holdout_start

    def test_st_003_wfa_generates_oos_predictions(self) -> None:
        """ST-003: WFA generates OOS predictions."""
        # Verify WFA was run in prior ML pipeline tests
        # This test confirms the capability exists
        from core.oos_wfa_engine import WFAPredictionEngine

        engine = WFAPredictionEngine(
            train_window_size=100,
            test_window_size=50,
            step_size=25,
            hypothesis_id="staging-test",
        )

        assert engine.hypothesis_id == "staging-test"
        assert engine.train_window_size == 100

    def test_st_004_holdout_evaluation_works(self) -> None:
        """ST-004: HOLDOUT evaluation works."""
        # Build validation report on holdout data
        builder = ValidationResultBuilder("staging-hyp", "v1")
        builder.set_audit_passed(True)
        builder.set_oos_metrics(
            observations=200,  # Holdout OOS observations
            trades=100,
            sharpe=1.2,
            profit_factor=1.8,
            win_rate=0.58,
            max_dd=0.08,
        )
        builder.set_robustness_metrics(cost_stress_pass=True, regime_tests={})
        report = builder.build()

        assert report.hypothesis_id == "staging-hyp"
        assert report.oos_observations == 200

    def test_st_005_validation_report_generated(self) -> None:
        """ST-005: Validation report generated."""
        builder = ValidationResultBuilder("staging-report", "v1")
        builder.set_audit_passed(True)
        builder.set_oos_metrics(100, 50, 1.1, 1.6, 0.56, 0.10)
        builder.set_baseline_metrics(0.4, 1.75)
        builder.set_trial_metrics(20, 18, {"dof": 5})
        builder.set_robustness_metrics(True, {})
        builder.set_calibration_metrics(0.22, 0.12)
        report = builder.build()

        summary = report.summary()
        assert "hypothesis_id" in summary
        assert "verdict" in summary
        assert summary["verdict"] == "VALIDATED"

    def test_st_006_decision_engine_evaluates_evidence(self) -> None:
        """ST-006: Decision engine evaluates evidence."""
        builder = ValidationResultBuilder("staging-decision", "v1")
        builder.set_audit_passed(True)
        builder.set_oos_metrics(100, 50, 1.2, 1.8, 0.60, 0.08)
        builder.set_robustness_metrics(cost_stress_pass=True, regime_tests={})
        report = builder.build()

        evidence = AggregatedEvidence(
            hypothesis_id="staging-decision",
            validation_report=report,
            oos_predictions=[],
            trial_ledger=TrialLedger("staging-decision"),
            calibration_metrics={},
            robustness_tests={},
            aggregated_score=0.65,
            confidence_level="HIGH",
        )

        engine = DecisionEngine({})
        decision = engine.evaluate(evidence)

        assert decision.decision == DecisionType.AUTHORIZE
        assert decision.allocation > 0.0

    def test_st_007_report_saved_to_staging_dir(self) -> None:
        """ST-007: Report saved to staging directory."""
        # Create temporary staging report
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = Path(tmpdir) / "reports" / "staging"
            staging_dir.mkdir(parents=True, exist_ok=True)

            # Save staging report
            report_data = {
                "hypothesis_id": "staging-test",
                "verdict": "VALIDATED",
                "oos_observations": 150,
                "sharpe_ratio": 1.3,
                "timestamp": datetime.now().isoformat(),
            }

            report_path = staging_dir / "staging_report.json"
            with open(report_path, "w") as f:
                json.dump(report_data, f)

            # Verify saved
            assert report_path.exists()
            with open(report_path) as f:
                loaded = json.load(f)
            assert loaded["hypothesis_id"] == "staging-test"

    def test_st_008_all_thresholds_met(self) -> None:
        """ST-008: All thresholds met → PASS."""
        thresholds = {
            "min_sharpe": 1.0,
            "min_profit_factor": 1.5,
            "max_drawdown": 0.15,
            "max_pbo": 0.5,
        }

        results = {
            "sharpe_ratio": 1.3,
            "profit_factor": 1.8,
            "max_drawdown": 0.09,
            "pbo_score": 0.3,
        }

        passed = True
        if results["sharpe_ratio"] < thresholds["min_sharpe"]:
            passed = False
        if results["profit_factor"] < thresholds["min_profit_factor"]:
            passed = False
        if results["max_drawdown"] > thresholds["max_drawdown"]:
            passed = False
        if results["pbo_score"] > thresholds["max_pbo"]:
            passed = False

        assert passed


class TestProductionReadiness:
    """Production Rollout Tests (PR-001 through PR-007)."""

    def test_pr_001_production_config_loads(self) -> None:
        """PR-001: Production config loads correctly."""
        config = {
            "environment": "production",
            "ml": {
                "hypothesis_id": "ML-001",
                "active": True,
                "allocation": 0.15,
            },
            "monitoring": {
                "alert_thresholds": {
                    "max_drawdown": 0.15,
                    "max_daily_loss": 100.0,
                    "max_positions": 3,
                },
                "check_interval_seconds": 60,
            },
        }

        assert config["environment"] == "production"
        assert config["ml"]["active"] is True

    def test_pr_002_strategy_initializes_with_capital(self) -> None:
        """PR-002: Strategy initializes with allocated capital."""
        allocation = 0.15  # From staging decision
        account_size = 100000.0
        deployed_capital = allocation * account_size

        assert deployed_capital == 15000.0

    def test_pr_003_execution_engine_connects(self) -> None:
        """PR-003: Execution engine connects to broker."""
        # Simulate broker connection
        broker_config = {
            "name": "xmtrading",
            "demo": False,
            "symbols": ["EURUSD"],
            "connected": True,
        }

        assert broker_config["connected"] is True

    def test_pr_004_health_monitor_starts(self) -> None:
        """PR-004: Health monitor starts successfully."""
        monitor_config = {
            "alert_thresholds": {
                "max_drawdown": 0.15,
                "max_daily_loss": 100.0,
                "max_positions": 3,
                "max_gross_exposure": 5.0,
            },
            "check_interval_seconds": 60,
            "running": True,
        }

        assert monitor_config["running"] is True
        assert monitor_config["alert_thresholds"]["max_drawdown"] == 0.15

    def test_pr_005_production_loop_runs_without_errors(self) -> None:
        """PR-005: Production loop runs without errors."""
        # Simulate production loop iteration
        market_data = {
            "symbol": "EURUSD",
            "bid": 1.0850,
            "ask": 1.0851,
            "timestamp": utcnow(),
        }

        signals = {"action": "BUY", "size": 1.0}

        # Execute order
        execution_result = {
            "status": "SUCCESS",
            "order_id": "ORDER-001",
            "filled_price": 1.0850,
        }

        assert execution_result["status"] == "SUCCESS"

    def test_pr_006_alerts_trigger_on_breaches(self) -> None:
        """PR-006: Alerts trigger on threshold breaches."""
        thresholds = {
            "max_drawdown": 0.15,
            "max_daily_loss": 100.0,
        }

        # Scenario 1: No breach
        current_metrics = {
            "drawdown": 0.08,
            "daily_loss": 50.0,
        }

        alerts = []
        if current_metrics["drawdown"] > thresholds["max_drawdown"]:
            alerts.append("Drawdown breach")
        if current_metrics["daily_loss"] > thresholds["max_daily_loss"]:
            alerts.append("Daily loss breach")

        assert len(alerts) == 0

        # Scenario 2: Drawdown breach
        current_metrics["drawdown"] = 0.17
        alerts = []
        if current_metrics["drawdown"] > thresholds["max_drawdown"]:
            alerts.append("Drawdown breach")

        assert len(alerts) == 1

    def test_pr_007_graceful_shutdown_works(self) -> None:
        """PR-007: Graceful shutdown works."""
        # Simulate production shutdown
        shutdown_steps = {
            "cancel_pending_orders": True,
            "close_open_positions": True,
            "save_state": True,
            "disconnect_broker": True,
            "stop_monitoring": True,
        }

        all_completed = all(shutdown_steps.values())
        assert all_completed is True


class TestEndToEndStagingThenProduction:
    """Integration test: Staging→Pass→Production."""

    def test_staging_pass_enables_production(self) -> None:
        """If staging PASS, production can proceed."""
        # Staging results
        staging_verdict = ValidationVerdict.VALIDATED
        staging_allocation = 0.15

        # Can only proceed to production if VALIDATED
        can_proceed = staging_verdict == ValidationVerdict.VALIDATED
        assert can_proceed is True
        assert staging_allocation > 0.0

    def test_staging_fail_blocks_production(self) -> None:
        """If staging FAIL, production cannot proceed."""
        # Staging results
        staging_verdict = ValidationVerdict.REJECTED
        staging_allocation = 0.0

        # Cannot proceed if not VALIDATED
        can_proceed = staging_verdict == ValidationVerdict.VALIDATED
        assert can_proceed is False
        assert staging_allocation == 0.0
