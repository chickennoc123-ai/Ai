"""
Phase 8 Tests: Autonomous Idea Machine Research Loop

Tests for:
1. Real Factory integration (uses actual gate() function, not simulation)
2. Autonomous loop orchestration (complete workflow)
3. Hypothesis pre-registration and journey tracking
4. Command execution framework
5. State persistence and restart safety
"""

import pytest
import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass

from idea_machine.real_factory_integration import (
    RealFactoryIntegrator, GateEvaluation, FactoryHypothesisJourney
)
from idea_machine.autonomous_loop import (
    AutonomousIdeaMachine, ResearchCommand
)
from discovery.cycle8_intraday import Stats


REPO_ROOT = Path(__file__).resolve().parent.parent


class TestRealFactoryIntegration:
    """Test real Factory integration using actual gate() function."""

    def test_real_factory_integrator_initialization(self):
        """Initialize integrator with repo root."""
        integrator = RealFactoryIntegrator(REPO_ROOT)
        assert integrator.repo_root == REPO_ROOT
        assert len(integrator.journeys) == 0

    def test_pre_register_hypothesis(self):
        """Pre-register a hypothesis for Factory evaluation."""
        integrator = RealFactoryIntegrator(REPO_ROOT)

        journey = integrator.pre_register_hypothesis(
            hyp_id="HYP-TEST-001",
            source_idea_id="IDEA-TEST-001",
            symbol="EURUSD",
            driver="US10Y"
        )

        assert journey.hypothesis_id == "HYP-TEST-001"
        assert journey.source_idea_id == "IDEA-TEST-001"
        assert journey.symbol == "EURUSD"
        assert journey.driver == "US10Y"
        assert journey.pre_registered_at is not None
        assert len(journey.gate_evaluations) == 0

    def test_pre_registered_hypothesis_tracked_in_journeys(self):
        """Pre-registered hypotheses are tracked in integrator."""
        integrator = RealFactoryIntegrator(REPO_ROOT)

        journey1 = integrator.pre_register_hypothesis("HYP-001", "IDEA-001", "EURUSD", "US10Y")
        journey2 = integrator.pre_register_hypothesis("HYP-002", "IDEA-002", "GBPUSD", None)

        assert len(integrator.journeys) == 2
        assert integrator.journeys[0].hypothesis_id == "HYP-001"
        assert integrator.journeys[1].hypothesis_id == "HYP-002"

    def test_evaluate_with_real_gates_passing_validation(self):
        """Evaluate hypothesis with stats that PASS DISCOVERY_SURVIVOR gate."""
        integrator = RealFactoryIntegrator(REPO_ROOT)
        journey = integrator.pre_register_hypothesis("HYP-PASS-001", "IDEA-001", "EURUSD", "US10Y")

        # Create stats that pass all gates
        train_stats = Stats(n=100, mean_net=0.0005, t_stat=2.5, profit_factor=2.0, win_rate=0.6, gross_over_cost=5.0)
        val_stats = Stats(n=50, mean_net=0.0003, t_stat=1.8, profit_factor=1.5, win_rate=0.55, gross_over_cost=3.0)

        passed = integrator.evaluate_with_real_gates(journey, train_stats, val_stats)

        assert passed is True
        assert len(journey.gate_evaluations) == 1
        assert journey.gate_evaluations[0].verdict == "DISCOVERY_SURVIVOR"
        assert journey.final_status == "DISCOVERY_SURVIVOR"

    def test_evaluate_with_real_gates_failing_validation_underpowered(self):
        """Evaluate hypothesis with val n < 30 (underpowered)."""
        integrator = RealFactoryIntegrator(REPO_ROOT)
        journey = integrator.pre_register_hypothesis("HYP-FAIL-001", "IDEA-001", "EURUSD", "US10Y")

        # Create stats where validation is underpowered
        train_stats = Stats(n=100, mean_net=0.0005, t_stat=2.5, profit_factor=2.0, win_rate=0.6, gross_over_cost=5.0)
        val_stats = Stats(n=10, mean_net=0.0003, t_stat=1.8, profit_factor=1.5, win_rate=0.55, gross_over_cost=3.0)

        passed = integrator.evaluate_with_real_gates(journey, train_stats, val_stats)

        assert passed is False
        assert journey.final_status == "REJECTED"
        assert "VALIDATION_UNDERPOWERED" in journey.gate_evaluations[0].verdict

    def test_evaluate_with_real_gates_failing_train_insignificant(self):
        """Evaluate hypothesis where train t-stat is too low."""
        integrator = RealFactoryIntegrator(REPO_ROOT)
        journey = integrator.pre_register_hypothesis("HYP-FAIL-002", "IDEA-002", "GBPUSD")

        # Create stats where train t-stat < 2.0
        train_stats = Stats(n=100, mean_net=0.0002, t_stat=1.5, profit_factor=1.5, win_rate=0.55, gross_over_cost=2.0)
        val_stats = Stats(n=50, mean_net=0.0003, t_stat=1.8, profit_factor=1.5, win_rate=0.55, gross_over_cost=3.0)

        passed = integrator.evaluate_with_real_gates(journey, train_stats, val_stats)

        assert passed is False
        assert "TRAIN_INSIGNIFICANT" in journey.gate_evaluations[0].verdict

    def test_gate_evaluation_records_real_statistics(self):
        """GateEvaluation dataclass records actual train/val statistics."""
        integrator = RealFactoryIntegrator(REPO_ROOT)
        journey = integrator.pre_register_hypothesis("HYP-STAT-001", "IDEA-001", "EURUSD")

        train_stats = Stats(n=75, mean_net=0.0004, t_stat=2.1, profit_factor=1.8, win_rate=0.58, gross_over_cost=4.5)
        val_stats = Stats(n=35, mean_net=0.0002, t_stat=1.6, profit_factor=1.4, win_rate=0.52, gross_over_cost=2.5)

        integrator.evaluate_with_real_gates(journey, train_stats, val_stats)

        eval_result = journey.gate_evaluations[0]
        assert eval_result.train_n == 75
        assert eval_result.train_t == 2.1
        assert eval_result.val_n == 35
        assert eval_result.val_t == 1.6

    def test_get_journeys_by_status(self):
        """Query journeys by final status."""
        integrator = RealFactoryIntegrator(REPO_ROOT)

        j1 = integrator.pre_register_hypothesis("HYP-001", "IDEA-001", "EURUSD")
        train_pass = Stats(n=100, mean_net=0.0005, t_stat=2.5, profit_factor=2.0, win_rate=0.6, gross_over_cost=5.0)
        val_pass = Stats(n=50, mean_net=0.0003, t_stat=1.8, profit_factor=1.5, win_rate=0.55, gross_over_cost=3.0)
        integrator.evaluate_with_real_gates(j1, train_pass, val_pass)

        j2 = integrator.pre_register_hypothesis("HYP-002", "IDEA-002", "GBPUSD")
        train_fail = Stats(n=100, mean_net=0.0002, t_stat=1.5, profit_factor=1.5, win_rate=0.55, gross_over_cost=2.0)
        val_fail = Stats(n=50, mean_net=0.0003, t_stat=1.8, profit_factor=1.5, win_rate=0.55, gross_over_cost=3.0)
        integrator.evaluate_with_real_gates(j2, train_fail, val_fail)

        survivors = integrator.get_journeys_by_status("DISCOVERY_SURVIVOR")
        rejected = integrator.get_journeys_by_status("REJECTED")

        assert len(survivors) == 1
        assert len(rejected) == 1
        assert survivors[0].hypothesis_id == "HYP-001"

    def test_factory_summary(self):
        """Get summary of all hypothesis journeys."""
        integrator = RealFactoryIntegrator(REPO_ROOT)

        j1 = integrator.pre_register_hypothesis("HYP-001", "IDEA-001", "EURUSD")
        train_pass = Stats(n=100, mean_net=0.0005, t_stat=2.5, profit_factor=2.0, win_rate=0.6, gross_over_cost=5.0)
        val_pass = Stats(n=50, mean_net=0.0003, t_stat=1.8, profit_factor=1.5, win_rate=0.55, gross_over_cost=3.0)
        integrator.evaluate_with_real_gates(j1, train_pass, val_pass)

        summary = integrator.get_summary()

        assert summary["total_hypotheses"] == 1
        assert summary["discovery_survivors"] == 1
        assert summary["rejected"] == 0

    def test_journey_serialization(self):
        """FactoryHypothesisJourney serializes to dict with all fields."""
        journey = FactoryHypothesisJourney(
            hypothesis_id="HYP-001",
            source_idea_id="IDEA-001",
            symbol="EURUSD",
            driver="US10Y",
            pre_registered_at=datetime.utcnow().isoformat(),
            gate_evaluations=[],
            final_status="UNKNOWN",
            final_reason=""
        )

        data = journey.to_dict()

        assert isinstance(data, dict)
        assert data["hypothesis_id"] == "HYP-001"
        assert data["source_idea_id"] == "IDEA-001"
        assert data["symbol"] == "EURUSD"
        assert "pre_registered_at" in data


class TestAutonomousIdeaMachine:
    """Test autonomous research loop orchestration."""

    def test_autonomous_loop_initialization(self):
        """Initialize autonomous loop with all supporting systems."""
        loop = AutonomousIdeaMachine(REPO_ROOT)

        assert loop.repo_root == REPO_ROOT
        assert not loop._loaded
        assert loop.research_memory is not None
        assert loop.novelty_engine is not None
        assert loop.opportunity_queue is not None
        assert loop.factory_integrator is not None

    def test_autonomous_loop_loads_all_data(self):
        """Load all supporting data structures."""
        loop = AutonomousIdeaMachine(REPO_ROOT)
        loop.load()

        assert loop._loaded is True
        assert loop.research_memory._loaded is True
        assert loop.novelty_engine._loaded is True

    def test_get_status_command(self):
        """Execute 'status' command."""
        loop = AutonomousIdeaMachine(REPO_ROOT)
        loop.load()

        cmd = ResearchCommand("status")
        result = loop.execute_command(cmd)

        assert result["system_status"] == "LOADED"
        assert "research_memory" in result
        assert "opportunity_queue" in result
        assert "factory_integration" in result

    def test_get_memory_summary_command(self):
        """Execute 'memory' command."""
        loop = AutonomousIdeaMachine(REPO_ROOT)
        loop.load()

        cmd = ResearchCommand("memory")
        result = loop.execute_command(cmd)

        assert result["type"] == "research_memory"
        assert "summary" in result

    def test_get_queue_summary_command(self):
        """Execute 'queue' command."""
        loop = AutonomousIdeaMachine(REPO_ROOT)
        loop.load()

        cmd = ResearchCommand("queue")
        result = loop.execute_command(cmd)

        assert result["type"] == "opportunity_queue"
        assert "total_opportunities" in result

    def test_verify_hypothesis_command(self):
        """Execute 'verify' command with hypothesis ID."""
        loop = AutonomousIdeaMachine(REPO_ROOT)
        loop.load()

        cmd = ResearchCommand("verify", {"hyp_id": "HYP-IM-0001"})
        result = loop.execute_command(cmd)

        assert result["hypothesis_id"] == "HYP-IM-0001"
        assert "checks" in result
        assert "recommendation" in result

    def test_dry_run_hypothesis_command(self):
        """Execute 'dry-run' command."""
        loop = AutonomousIdeaMachine(REPO_ROOT)
        loop.load()

        cmd = ResearchCommand("dry-run", {"hyp_id": "HYP-IM-0001"})
        result = loop.execute_command(cmd)

        assert result["hypothesis_id"] == "HYP-IM-0001"
        assert "verification" in result
        assert "factory_readiness" in result

    def test_run_discovery_cycle_command(self, tmp_path):
        """Execute 'cycle' command.

        run_discovery_cycle now delegates to run_adaptive_search_cycle (Phase
        9, second pass), which runs a REAL, small Factory cycle -- so this
        test isolates the opportunity queue and search decision ledger to
        tmp_path BEFORE load() wires them into the adaptive search
        controller. Using the default (production) paths here would append
        real entries into reports/idea_machine/*.json on every test run,
        exactly the ledger-pollution bug already found and fixed once this
        session for the opportunity_queue tests.
        """
        from idea_machine.opportunity_queue import OpportunityQueue
        from idea_machine.search_decision_ledger import SearchDecisionLedger

        loop = AutonomousIdeaMachine(REPO_ROOT)
        loop.opportunity_queue = OpportunityQueue(tmp_path / "opp.json")
        loop.search_decision_ledger = SearchDecisionLedger(tmp_path / "sdl.json")
        loop.load()

        cmd = ResearchCommand("cycle", {"cycle_id": "TEST-CYCLE-001"})
        result = loop.execute_command(cmd)

        assert result["cycle_id"] == "TEST-CYCLE-001"
        assert "search_plan" in result
        assert "factory_evaluations" in result
        assert result["ideas_generated"] >= 0

    def test_unknown_command_returns_error(self):
        """Unknown command returns error message."""
        loop = AutonomousIdeaMachine(REPO_ROOT)
        loop.load()

        cmd = ResearchCommand("invalid_command")
        result = loop.execute_command(cmd)

        assert "error" in result

    def test_command_auto_loads_data(self):
        """Executing command auto-loads data if not yet loaded."""
        loop = AutonomousIdeaMachine(REPO_ROOT)
        assert not loop._loaded

        cmd = ResearchCommand("status")
        result = loop.execute_command(cmd)

        assert loop._loaded
        assert result["system_status"] == "LOADED"

    def test_autonomous_loop_framework_complete(self):
        """Verify all orchestration components are in place."""
        loop = AutonomousIdeaMachine(REPO_ROOT)
        loop.load()

        # All systems should be loaded
        assert loop.research_memory._loaded
        assert loop.novelty_engine._loaded
        assert loop.opportunity_queue is not None

        # Factory integrator should be ready
        assert isinstance(loop.factory_integrator, RealFactoryIntegrator)

        # All key methods should exist
        assert callable(loop.execute_command)
        assert callable(loop.get_status)
        assert callable(loop.verify_hypothesis)
        assert callable(loop.dry_run_hypothesis)
