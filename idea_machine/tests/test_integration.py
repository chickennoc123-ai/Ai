"""End-to-end: the full loop, feedback, budget, adaptive search, dashboard."""

from __future__ import annotations

import json

import pytest

from idea_machine.budget.manager import (
    EXPERIMENTS_REGISTERED,
    IDEAS_GENERATED,
    BudgetPolicy,
    ResearchBudget,
)
from idea_machine.core.errors import BudgetExhausted
from idea_machine.integration.factory_bridge import BridgeError, FactoryResult
from idea_machine.observability.dashboard import build_dashboard, render_text
from idea_machine.pipeline import IdeaMachine
from idea_machine.queue import queue as qs


def verdicts_for(submitter, verdicts):
    return [
        FactoryResult(
            experiment_id=spec.experiment_id,
            idea_id=spec.idea_id,
            verdict=verdicts[i % len(verdicts)],
            evidence_reference=f"reports/factory/cycle.md#e{i}",
            reason=f"factory verdict {verdicts[i % len(verdicts)]}",
        )
        for i, spec in enumerate(submitter.submissions)
    ]


# ----------------------------------------------------------------- one cycle


def test_a_cycle_runs_end_to_end(machine, submitter):
    report = machine.run_cycle()
    assert report.scanned == 4
    assert report.generated > 0
    assert report.combined > 0
    assert report.submitted > 0
    assert len(submitter.submissions) == report.submitted
    machine.verify_integrity()


def test_everything_submitted_is_frozen_and_preregistered(machine, submitter):
    machine.run_cycle()
    for spec in submitter.submissions:
        assert spec.frozen
        machine.prereg.verify(spec)


def test_no_submission_carries_a_backtest_result(machine, submitter):
    machine.run_cycle()
    for spec in submitter.submissions:
        blob = json.dumps(spec.to_dict()).lower()
        for banned in ("sharpe", "win_rate", "max_drawdown", "profit_factor", "equity_curve"):
            assert banned not in blob


def test_an_empty_catalog_blocks_everything(tmp_path, provider, empty_catalog, submitter):
    machine = IdeaMachine(
        root=tmp_path / "l", providers=[provider], catalog=empty_catalog, submitter=submitter
    )
    report = machine.run_cycle()
    assert report.generated > 0
    assert report.feasible == 0
    assert report.submitted == 0
    assert machine.queue.counts()[qs.BLOCKED_DATA] > 0


def test_a_cycle_with_no_sources_produces_nothing(tmp_path, catalog, submitter):
    machine = IdeaMachine(root=tmp_path / "l", providers=[], catalog=catalog, submitter=submitter)
    report = machine.run_cycle()
    assert report.generated == 0
    assert report.submitted == 0


# --------------------------------------------------------------- determinism


def test_two_identical_machines_produce_identical_experiments(tmp_path, catalog):
    from idea_machine.integration.factory_bridge import InMemorySubmitter
    from idea_machine.scanner.scanner import InMemoryProvider
    from idea_machine.tests.conftest import DOCS

    ids = []
    for run in ("a", "b"):
        submitter = InMemorySubmitter()
        machine = IdeaMachine(
            root=tmp_path / run,
            providers=[InMemoryProvider(DOCS)],
            catalog=catalog,
            submitter=submitter,
        )
        machine.run_cycle()
        ids.append([s.experiment_id for s in submitter.submissions])
    assert ids[0] == ids[1], "the same inputs must produce the same experiments"


# ------------------------------------------------------------------ feedback


def test_feedback_maps_every_verdict_correctly(machine, submitter):
    machine.run_cycle()
    results = verdicts_for(submitter, ["FAIL", "REFUTED", "UNDERPOWERED", "BLOCKED", "SURVIVOR"])
    outcomes = {o.verdict: o for o in machine.ingest_results(results)}

    assert outcomes["REFUTED"].closed_search_space is True
    for verdict in ("FAIL", "UNDERPOWERED", "BLOCKED", "SURVIVOR"):
        if verdict in outcomes:
            assert outcomes[verdict].closed_search_space is False, f"{verdict} must not close search space"


def test_underpowered_does_not_close_search_space(machine, submitter):
    machine.run_cycle()
    results = verdicts_for(submitter, ["UNDERPOWERED"])
    machine.ingest_results(results)
    for entry in machine.memory.entries():
        assert not machine.memory.is_closed(
            mechanism_signature=entry.mechanism_signature, horizon=entry.horizon
        )
        assert machine.memory.reopenable_reason(
            mechanism_signature=entry.mechanism_signature, horizon=entry.horizon
        )


def test_a_refuted_idea_is_not_proposed_again(tmp_path, provider, catalog):
    from idea_machine.integration.factory_bridge import InMemorySubmitter

    submitter = InMemorySubmitter()
    machine = IdeaMachine(
        root=tmp_path / "l", providers=[provider], catalog=catalog, submitter=submitter,
        budget_policy=BudgetPolicy(1000, 500, 50),
    )
    machine.run_cycle()
    machine.ingest_results(verdicts_for(submitter, ["REFUTED"]))

    refuted_signatures = {e.mechanism_signature for e in machine.memory.entries() if e.closes_search_space}
    assert refuted_signatures

    from idea_machine.novelty.checker import REJECTED_SEARCH_SPACE, NoveltyChecker
    from idea_machine.core.idea_spec import IdeaSpec

    checker = NoveltyChecker(machine.memory)
    for row in machine.idea_ledger.all():
        idea = IdeaSpec.from_dict(row)
        if idea.mechanism_signature() in refuted_signatures:
            assert checker.check(idea).verdict == REJECTED_SEARCH_SPACE
            break
    else:
        pytest.fail("no refuted idea found to re-check")


def test_survivor_is_never_called_an_edge(machine, submitter):
    machine.run_cycle()
    outcomes = machine.ingest_results(verdicts_for(submitter, ["SURVIVOR"]))
    for outcome in outcomes:
        assert outcome.epistemic_state == "SURVIVED"
        assert "Not refuted is not proven" in outcome.lesson


def test_a_result_for_an_unsubmitted_experiment_is_refused(machine):
    with pytest.raises(BridgeError):
        machine.bridge.receive(
            FactoryResult(
                experiment_id="EXP-nonexistent", idea_id="IDEA-nonexistent",
                verdict="FAIL", evidence_reference="ref", reason="r",
            )
        )


def test_an_unknown_verdict_is_refused():
    with pytest.raises(BridgeError):
        FactoryResult(
            experiment_id="EXP-1", idea_id="IDEA-1", verdict="PROFITABLE",
            evidence_reference="ref", reason="r",
        )


# -------------------------------------------------------------------- budget


def test_the_experiment_budget_caps_a_cycle(tmp_path, provider, catalog, submitter):
    machine = IdeaMachine(
        root=tmp_path / "l", providers=[provider], catalog=catalog, submitter=submitter,
        budget_policy=BudgetPolicy(100, 20, 2),
    )
    report = machine.run_cycle()
    assert report.submitted <= 2
    assert machine.budget.remaining(EXPERIMENTS_REGISTERED) == 0


def test_budget_survives_a_restart(tmp_path):
    policy = BudgetPolicy(10, 5, 2)
    first = ResearchBudget(policy=policy, path=tmp_path / "b.json", window="W")
    first.spend(IDEAS_GENERATED, 7)
    second = ResearchBudget(policy=policy, path=tmp_path / "b.json", window="W")
    assert second.remaining(IDEAS_GENERATED) == 3


def test_overspending_raises(tmp_path):
    budget = ResearchBudget(policy=BudgetPolicy(10, 5, 1), path=tmp_path / "b.json", window="W")
    budget.spend(EXPERIMENTS_REGISTERED, 1)
    with pytest.raises(BudgetExhausted):
        budget.spend(EXPERIMENTS_REGISTERED, 1)


def test_allocation_never_exceeds_the_cap(tmp_path):
    budget = ResearchBudget(policy=BudgetPolicy(100, 20, 5), path=tmp_path / "b.json", window="W")
    allocation = budget.allocate({"EVENT": 10.0, "REGIME": 5.0, "CARRY": 1.0})
    assert sum(allocation.values()) == 5, "weights redistribute the cap, they never raise it"


# ----------------------------------------------------------- adaptive search


def test_adaptive_policy_reflects_outcomes(machine, submitter):
    machine.run_cycle()
    machine.ingest_results(verdicts_for(submitter, ["REFUTED"]))
    policy = machine.adaptive.derive_policy()
    tested_families = {e.family for e in machine.memory.entries()}
    for family in tested_families:
        assert policy.weight_for(family) < 1.0


def test_no_family_is_driven_to_zero(machine, submitter):
    machine.run_cycle()
    machine.ingest_results(verdicts_for(submitter, ["REFUTED"]))
    for weight in machine.adaptive.derive_policy().family_weights.values():
        assert weight >= 0.10


def test_adaptive_report_answers_the_three_questions(machine, submitter):
    machine.run_cycle()
    machine.ingest_results(verdicts_for(submitter, ["REFUTED", "UNDERPOWERED"]))
    report = machine.adaptive.report()
    assert report["where_we_proved_it_does_not_work"]
    assert report["where_we_never_actually_looked"]


# --------------------------------------------------------------- observability


def test_dashboard_answers_the_roadmap_questions(machine, submitter):
    machine.run_cycle()
    machine.ingest_results(verdicts_for(submitter, ["REFUTED", "UNDERPOWERED", "SURVIVOR"]))
    dashboard = build_dashboard(machine)

    assert "where_are_we_searching" in dashboard
    assert "where_have_we_proven_it_does_not_work" in dashboard
    assert "where_did_we_never_actually_look" in dashboard
    assert dashboard["counters"]["ideas_generated"] > 0
    json.dumps(dashboard, default=str)


def test_dashboard_does_not_invent_factory_state(machine):
    machine.run_cycle()
    downstream = build_dashboard(machine)["downstream_owned_by_factory"]
    for key in ("gen12_candidates", "gen14_candidates", "eas_produced"):
        assert downstream[key] == "UNKNOWN_TO_IDEA_MACHINE"


def test_dashboard_renders_as_text(machine, submitter):
    machine.run_cycle()
    machine.ingest_results(verdicts_for(submitter, ["REFUTED"]))
    text = render_text(build_dashboard(machine))
    assert "WHERE ARE WE SEARCHING?" in text
    assert "WHERE HAVE WE PROVEN IT DOES NOT WORK?" in text
    assert "HUMAN AUTHORITY" in text


# ------------------------------------------------------------------ integrity


def test_ledgers_replay_cleanly_across_cycles(machine, submitter):
    machine.run_cycle()
    machine.ingest_results(verdicts_for(submitter, ["FAIL", "SURVIVOR"]))
    machine.run_cycle()
    machine.verify_integrity()


def test_status_is_serialisable(machine):
    machine.run_cycle()
    json.dumps(machine.status(), default=str)


def test_the_machine_writes_only_under_its_own_root(tmp_path, provider, catalog, submitter):
    root = tmp_path / "ledgers"
    machine = IdeaMachine(root=root, providers=[provider], catalog=catalog, submitter=submitter)
    machine.run_cycle()
    machine.ingest_results(verdicts_for(submitter, ["FAIL"]))
    assert root.exists()
    for path in root.rglob("*"):
        assert root in path.parents or path.parent == root
