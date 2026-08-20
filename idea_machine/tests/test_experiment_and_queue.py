"""Experiment design, pre-registration (no p-hacking), and queue integrity."""

from __future__ import annotations

import pytest

from idea_machine.core.errors import GovernanceViolation, ImmutabilityError, QueueError, SpecValidationError
from idea_machine.economics.data_feasibility import DataCatalog, FeasibilityChecker
from idea_machine.economics.prefilter import EconomicPreFilter
from idea_machine.experiment.designer import UNDERPOWERED_BY_DESIGN, ExperimentDesigner
from idea_machine.experiment.prereg import PreregistrationError, PreregistrationLedger
from idea_machine.experiment.spec import EvaluationWindow, ExperimentSpec
from idea_machine.queue import queue as qs
from idea_machine.queue.queue import IdeaQueue
from idea_machine.tests.conftest import make_dataset
from idea_machine.tests.test_core_contract import make_idea


def powerable_idea(**overrides):
    """A CROSS_ASSET idea, deliberately not EVENT.

    Event and seasonality families are capped at roughly one observation per
    scheduled release, so they are legitimately underpowered for small effects
    -- which is the designer working correctly, not a fixture to work around.
    """
    from idea_machine.core.idea_spec import ExpectedEffect

    base = dict(
        family="CROSS_ASSET",
        hypothesis="Moves in US10Y lead same-direction moves in EURUSD at a short lag.",
        mechanism=(
            "Rates and FX are traded by partly different participants, so a shared shock reaches "
            "the rates market first because its participants are closest to the information."
        ),
        instruments=("EURUSD",),
        timeframe="H1",
        holding_period="INTRADAY",
        expected_effect=ExpectedEffect(0.00060, "PRICE", "BOTH", 3, "cross-market transmission estimates"),
        required_data=("driver_ohlcv_h1", "target_ohlcv_h1"),
    )
    base.update(overrides)
    return make_idea(**base)


def designed_spec(idea=None, *, rows: int = 30_000) -> ExperimentSpec:
    idea = idea if idea is not None else powerable_idea()
    catalog = DataCatalog([make_dataset(d, rows=rows) for d in idea.required_data])
    outcome = ExperimentDesigner().design(
        idea,
        feasibility=FeasibilityChecker(catalog).check(idea),
        economics=EconomicPreFilter().check(idea),
    )
    assert outcome.designed, outcome.reason
    return outcome.spec


# ----------------------------------------------------------------- designer


def test_a_designed_experiment_has_both_gates():
    spec = designed_spec()
    assert spec.success_gate and spec.kill_gate
    assert "not refuted" in spec.success_gate.lower() or "NOT REFUTED" in spec.success_gate


def test_success_gate_never_claims_an_edge():
    assert "does not mean an edge exists" in designed_spec().success_gate


def test_an_underpowered_design_is_refused_not_run():
    idea = make_idea()
    catalog = DataCatalog([make_dataset(d, rows=2_000) for d in idea.required_data])
    outcome = ExperimentDesigner().design(
        idea,
        feasibility=FeasibilityChecker(catalog).check(idea),
        economics=EconomicPreFilter().check(idea),
    )
    assert outcome.status == UNDERPOWERED_BY_DESIGN
    assert outcome.spec is None
    assert "teaches nothing" in outcome.reason


def test_validation_window_follows_the_training_window():
    spec = designed_spec()
    assert spec.train_period.end <= spec.validation_period.start


def test_overlapping_windows_are_rejected():
    with pytest.raises(SpecValidationError) as exc:
        ExperimentSpec(
            idea_id="IDEA-x", research_question="q", hypothesis="h",
            entry={"a": 1}, exit={"b": 2}, holding_period="INTRADAY",
            instruments=("EURUSD",), timeframe="M15", cost_model={},
            sample_requirement=100,
            train_period=EvaluationWindow("TRAIN", "2015-01-01", "2022-01-01"),
            validation_period=EvaluationWindow("VALIDATION", "2021-01-01", "2025-01-01"),
            evaluation_budget=3, success_gate="s", kill_gate="k", required_data=("d",),
        )
    assert "leak" in str(exc.value)


def test_the_idea_machine_cannot_name_a_holdout_window():
    for name in ("HOLDOUT", "PURE_HOLDOUT", "SEALED"):
        with pytest.raises(SpecValidationError) as exc:
            EvaluationWindow(name, "2015-01-01", "2020-01-01")
        assert "Factory's authority" in str(exc.value)


def test_evaluation_budget_must_be_bounded():
    with pytest.raises(SpecValidationError) as exc:
        ExperimentSpec(
            idea_id="IDEA-x", research_question="q", hypothesis="h",
            entry={"a": 1}, exit={"b": 2}, holding_period="INTRADAY",
            instruments=("EURUSD",), timeframe="M15", cost_model={},
            sample_requirement=100,
            train_period=EvaluationWindow("TRAIN", "2015-01-01", "2022-01-01"),
            validation_period=EvaluationWindow("VALIDATION", "2022-01-01", "2025-01-01"),
            evaluation_budget=0, success_gate="s", kill_gate="k", required_data=("d",),
        )
    assert "multiple-testing" in str(exc.value)


def test_experiment_spec_rejects_backtest_results():
    with pytest.raises(SpecValidationError):
        ExperimentSpec(
            idea_id="IDEA-x", research_question="q", hypothesis="h",
            entry={"sharpe": 2.0}, exit={"b": 2}, holding_period="INTRADAY",
            instruments=("EURUSD",), timeframe="M15", cost_model={},
            sample_requirement=100,
            train_period=EvaluationWindow("TRAIN", "2015-01-01", "2022-01-01"),
            validation_period=EvaluationWindow("VALIDATION", "2022-01-01", "2025-01-01"),
            evaluation_budget=3, success_gate="s", kill_gate="k", required_data=("d",),
        )


# ---------------------------------------------------------- pre-registration


def test_freezing_seals_the_design(tmp_path):
    spec = designed_spec()
    frozen = PreregistrationLedger(tmp_path / "p.json").register(spec)
    assert frozen.frozen and frozen.frozen_at


def test_a_frozen_spec_cannot_be_refrozen(tmp_path):
    frozen = PreregistrationLedger(tmp_path / "p.json").register(designed_spec())
    with pytest.raises(ImmutabilityError):
        frozen.freeze(at="later")


def test_changing_the_design_after_registration_is_a_governance_violation(tmp_path):
    """The p-hacking loop, caught: same experiment_id, different design."""
    ledger = PreregistrationLedger(tmp_path / "p.json")
    frozen = ledger.register(designed_spec())

    tampered = ExperimentSpec.from_dict({**frozen.to_dict(), "entry": {"trigger": "x", "threshold": 0.1}})
    object.__setattr__(tampered, "experiment_id", frozen.experiment_id)

    assert tampered.preregistration_checksum() != frozen.preregistration_checksum()
    with pytest.raises(GovernanceViolation) as exc:
        ledger.verify(tampered)
    assert "design changed after pre-registration" in str(exc.value)


def test_a_result_for_an_unregistered_design_is_refused(tmp_path):
    ledger = PreregistrationLedger(tmp_path / "p.json")
    with pytest.raises(PreregistrationError) as exc:
        ledger.attach_result(designed_spec(), outcome="FAIL", evidence_reference="ref")
    assert "never pre-registered" in str(exc.value)


def test_a_result_must_reference_evidence(tmp_path):
    ledger = PreregistrationLedger(tmp_path / "p.json")
    frozen = ledger.register(designed_spec())
    with pytest.raises(PreregistrationError):
        ledger.attach_result(frozen, outcome="FAIL", evidence_reference="")


def test_amendment_is_recorded_not_hidden(tmp_path):
    ledger = PreregistrationLedger(tmp_path / "p.json")
    original = ledger.register(designed_spec())
    revised = designed_spec(powerable_idea(entry={"trigger": "lead_z", "threshold": 2.5}))
    ledger.amend(original.experiment_id, revised, reason="threshold rationale corrected pre-run")

    assert ledger.summary()["registered"] == 2
    assert ledger.summary()["amendments"] == 1


def test_amending_after_a_result_is_a_governance_violation(tmp_path):
    """Changing the design after seeing the outcome is the thing being prevented."""
    ledger = PreregistrationLedger(tmp_path / "p.json")
    original = ledger.register(designed_spec())
    ledger.attach_result(original, outcome="FAIL", evidence_reference="reports/x.md")

    revised = designed_spec(powerable_idea(entry={"trigger": "lead_z", "threshold": 2.5}))
    with pytest.raises(GovernanceViolation) as exc:
        ledger.amend(original.experiment_id, revised, reason="it did not work, let us try another threshold")
    assert "after seeing the outcome" in str(exc.value)


def test_an_amendment_must_state_a_reason(tmp_path):
    ledger = PreregistrationLedger(tmp_path / "p.json")
    original = ledger.register(designed_spec())
    revised = designed_spec(powerable_idea(entry={"trigger": "lead_z", "threshold": 2.5}))
    with pytest.raises(PreregistrationError):
        ledger.amend(original.experiment_id, revised, reason="")


def test_designs_tried_is_visible_for_multiple_testing(tmp_path):
    ledger = PreregistrationLedger(tmp_path / "p.json")
    idea = powerable_idea()
    original = ledger.register(designed_spec(idea))
    revised = designed_spec(powerable_idea(entry={"trigger": "lead_z", "threshold": 2.5}))
    ledger.amend(original.experiment_id, revised, reason="pre-run correction")
    assert ledger.designs_tried_for_idea(idea.idea_id) >= 1


# ------------------------------------------------------------ queue integrity


def full_path(queue: IdeaQueue, idea) -> None:
    queue.admit(idea)
    for state in (qs.SCREENED, qs.APPROVED_FOR_RESEARCH, qs.QUEUED, qs.RUNNING, qs.FACTORY_RESULT):
        queue.advance(idea.idea_id, state, reason="step")


def test_the_queue_enforces_its_order(tmp_path):
    queue = IdeaQueue(tmp_path / "q.json")
    idea = make_idea()
    queue.admit(idea)
    with pytest.raises(QueueError) as exc:
        queue.advance(idea.idea_id, qs.QUEUED, reason="skipping screening")
    assert "illegal queue transition" in str(exc.value)


def test_terminal_outcomes_require_factory_evidence(tmp_path):
    queue = IdeaQueue(tmp_path / "q.json")
    idea = make_idea()
    full_path(queue, idea)
    with pytest.raises(GovernanceViolation) as exc:
        queue.advance(idea.idea_id, qs.SURVIVOR, reason="looks good to me")
    assert "cannot decide its own idea's fate" in str(exc.value)


def test_terminal_outcomes_are_accepted_with_evidence(tmp_path):
    queue = IdeaQueue(tmp_path / "q.json")
    idea = make_idea()
    full_path(queue, idea)
    queue.advance(idea.idea_id, qs.SURVIVOR, reason="factory verdict",
                  evidence_reference="reports/factory/cycle.md#e1")
    assert queue.state_of(idea.idea_id) == qs.SURVIVOR


def test_every_transition_records_a_reason(tmp_path):
    queue = IdeaQueue(tmp_path / "q.json")
    idea = make_idea()
    queue.admit(idea)
    with pytest.raises(QueueError):
        queue.advance(idea.idea_id, qs.SCREENED, reason="  ")


def test_a_refuted_idea_is_terminal(tmp_path):
    queue = IdeaQueue(tmp_path / "q.json")
    idea = make_idea()
    full_path(queue, idea)
    queue.advance(idea.idea_id, qs.REFUTED, reason="refuted", evidence_reference="ref")
    with pytest.raises(QueueError):
        queue.advance(idea.idea_id, qs.SCREENED, reason="one more go")


def test_an_underpowered_idea_can_be_rescreened(tmp_path):
    queue = IdeaQueue(tmp_path / "q.json")
    idea = make_idea()
    full_path(queue, idea)
    queue.advance(idea.idea_id, qs.UNDERPOWERED, reason="small n", evidence_reference="ref")
    queue.advance(idea.idea_id, qs.SCREENED, reason="more data has arrived")
    assert queue.state_of(idea.idea_id) == qs.SCREENED


def test_blocked_data_is_the_machines_own_verdict_not_the_factorys(tmp_path):
    """Our data pre-screen must not require Factory evidence, and must not be
    confused with the Factory's own BLOCKED outcome."""
    queue = IdeaQueue(tmp_path / "q.json")
    idea = make_idea()
    queue.admit(idea)
    queue.advance(idea.idea_id, qs.SCREENED, reason="screened")
    queue.advance(idea.idea_id, qs.BLOCKED_DATA, reason="dataset absent from the catalog")
    assert queue.state_of(idea.idea_id) == qs.BLOCKED_DATA
    assert qs.BLOCKED_DATA not in qs.FACTORY_OUTCOMES


def test_queue_history_replays_cleanly(tmp_path):
    queue = IdeaQueue(tmp_path / "q.json")
    idea = make_idea()
    full_path(queue, idea)
    queue.advance(idea.idea_id, qs.FAIL, reason="verdict", evidence_reference="ref")
    queue.verify_integrity()
    assert len(queue.history(idea.idea_id)) == 7


def test_next_for_research_is_priority_ordered(tmp_path):
    queue = IdeaQueue(tmp_path / "q.json")
    low = make_idea()
    high = make_idea(timeframe="H1")
    for idea, priority in ((low, 10.0), (high, 90.0)):
        queue.admit(idea, priority=priority)
        queue.advance(idea.idea_id, qs.SCREENED, reason="s")
        queue.advance(idea.idea_id, qs.APPROVED_FOR_RESEARCH, reason="a")
        queue.advance(idea.idea_id, qs.QUEUED, reason="q")
    assert [e.idea_id for e in queue.next_for_research(2)] == [high.idea_id, low.idea_id]
