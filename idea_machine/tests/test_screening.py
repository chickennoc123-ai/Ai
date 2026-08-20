"""Novelty, failure memory, data feasibility, economics, and ranking (5-8)."""

from __future__ import annotations

import pytest

from idea_machine.core.idea_spec import ExpectedEffect
from idea_machine.economics.cost_model import DEFAULT_COST_MODEL
from idea_machine.economics.data_feasibility import (
    BLOCKED_DATA,
    FEASIBLE,
    DataCatalog,
    FeasibilityChecker,
)
from idea_machine.economics.prefilter import (
    FAILED_ECONOMICS,
    MARGINAL,
    VIABLE,
    EconomicPreFilter,
)
from idea_machine.generator.generator import IdeaGenerator
from idea_machine.novelty.checker import (
    NOVEL,
    REJECTED_SEARCH_SPACE,
    REVIEW_REQUIRED,
    NoveltyChecker,
)
from idea_machine.novelty.memory import FailureEntry, FailureMemory
from idea_machine.ranking.ranker import WEIGHTS, IdeaRanker
from idea_machine.tests.test_core_contract import make_idea


# ------------------------------------------------------------ failure memory


def test_refuted_closes_search_space_and_underpowered_does_not(tmp_path):
    memory = FailureMemory(tmp_path / "fm.json")
    memory.record(FailureEntry("IDEA-1", "EVENT", "sig-refuted", "INTRADAY", "REFUTED", "mechanism contradicted"))
    memory.record(FailureEntry("IDEA-2", "EVENT", "sig-weak", "INTRADAY", "UNDERPOWERED", "n too small"))

    assert memory.is_closed(mechanism_signature="sig-refuted", horizon="INTRADAY")
    assert not memory.is_closed(mechanism_signature="sig-weak", horizon="INTRADAY")
    assert "UNDERPOWERED" in memory.reopenable_reason(mechanism_signature="sig-weak", horizon="INTRADAY")


def test_failure_entries_carry_no_performance_metric():
    entry = FailureEntry("IDEA-1", "EVENT", "sig", "INTRADAY", "REFUTED", "reason")
    for field in entry.to_dict():
        assert not any(m in field for m in ("sharpe", "pnl", "drawdown", "return"))


def test_unknown_outcome_is_rejected():
    with pytest.raises(ValueError):
        FailureEntry("IDEA-1", "EVENT", "sig", "INTRADAY", "PROFITABLE", "reason")


def test_two_records_of_the_same_lesson_do_not_collide(tmp_path):
    """A repeated lesson at a later time is a new record, not a rewrite."""
    memory = FailureMemory(tmp_path / "fm.json")
    stamps = iter(["2026-01-01T00:00:00+00:00", "2026-06-01T00:00:00+00:00"])
    memory._clock = lambda: next(stamps)
    memory.record(FailureEntry("IDEA-1", "EVENT", "sig", "INTRADAY", "FAIL", "same reason"))
    memory.record(FailureEntry("IDEA-1", "EVENT", "sig", "INTRADAY", "FAIL", "same reason"))
    assert len(memory.entries()) == 2


def test_factory_failure_library_is_read_only(tmp_path):
    """Reading the Factory's library must not write to it."""
    from core.factory.failure_library import DEFAULT_FAILURE_LIBRARY_PATH

    memory = FailureMemory(tmp_path / "fm.json")
    before = DEFAULT_FAILURE_LIBRARY_PATH.read_bytes() if DEFAULT_FAILURE_LIBRARY_PATH.exists() else None
    counts = memory.factory_failure_counts()
    after = DEFAULT_FAILURE_LIBRARY_PATH.read_bytes() if DEFAULT_FAILURE_LIBRARY_PATH.exists() else None
    assert isinstance(counts, dict)
    assert before == after, "reading the Factory's failure library must not modify it"


# ------------------------------------------------------------------ novelty


def test_a_refuted_mechanism_is_rejected(tmp_path):
    idea = make_idea()
    memory = FailureMemory(tmp_path / "fm.json")
    memory.record(
        FailureEntry(idea.idea_id, idea.family, idea.mechanism_signature(), idea.holding_period,
                     "REFUTED", "already contradicted")
    )
    verdict = NoveltyChecker(memory).check(idea)
    assert verdict.verdict == REJECTED_SEARCH_SPACE
    assert not verdict.may_proceed


def test_retesting_a_refuted_idea_with_a_tweaked_parameter_is_still_rejected(tmp_path):
    """The p-hacking loop: same mechanism, nudged threshold."""
    original = make_idea()
    memory = FailureMemory(tmp_path / "fm.json")
    memory.record(
        FailureEntry(original.idea_id, original.family, original.mechanism_signature(),
                     original.holding_period, "REFUTED", "contradicted")
    )
    tweaked = make_idea(entry={"trigger": "nfp_surprise_z", "threshold": 1.6})
    assert tweaked.idea_id != original.idea_id, "the tweak really does make a different IdeaSpec"
    assert tweaked.mechanism_signature() == original.mechanism_signature()
    assert NoveltyChecker(memory).check(tweaked).verdict == REJECTED_SEARCH_SPACE


def test_an_underpowered_idea_comes_back_as_novel(tmp_path):
    idea = make_idea()
    memory = FailureMemory(tmp_path / "fm.json")
    memory.record(
        FailureEntry(idea.idea_id, idea.family, idea.mechanism_signature(), idea.holding_period,
                     "UNDERPOWERED", "sample too small")
    )
    verdict = NoveltyChecker(memory).check(idea)
    assert verdict.verdict == NOVEL
    assert "UNDERPOWERED" in verdict.reopened_from


def test_near_duplicates_are_flagged_not_silently_dropped(tmp_path):
    memory = FailureMemory(tmp_path / "fm.json")
    checker = NoveltyChecker(memory)
    first = make_idea()
    checker.remember(first)
    verdict = checker.check(make_idea(entry={"trigger": "nfp_surprise_z", "threshold": 3.0}))
    assert verdict.verdict == REVIEW_REQUIRED
    assert verdict.may_proceed, "similar is a flag, not a rejection"


def test_a_fresh_idea_is_novel(tmp_path):
    memory = FailureMemory(tmp_path / "fm.json")
    assert NoveltyChecker(memory).check(make_idea()).verdict == NOVEL


# -------------------------------------------------------------- feasibility


def test_missing_data_blocks_rather_than_assumes(empty_catalog):
    verdict = FeasibilityChecker(empty_catalog).check(make_idea())
    assert verdict.verdict == BLOCKED_DATA
    assert not verdict.may_proceed
    assert verdict.missing_datasets


def test_an_incomplete_dataset_blocks(tmp_path):
    from idea_machine.tests.conftest import make_dataset

    incomplete = make_dataset("nfp_actual_consensus")
    incomplete = type(incomplete)(**{**incomplete.__dict__, "timezone": "", "has_cost_data": False})
    catalog = DataCatalog([incomplete, make_dataset("eurusd_m15")])
    verdict = FeasibilityChecker(catalog).check(make_idea())
    assert verdict.verdict == BLOCKED_DATA
    assert "timezone" in verdict.incomplete_datasets["nfp_actual_consensus"]
    assert "cost_data" in verdict.incomplete_datasets["nfp_actual_consensus"]


def test_a_complete_catalog_is_feasible():
    from idea_machine.tests.conftest import make_dataset

    catalog = DataCatalog([make_dataset("nfp_actual_consensus"), make_dataset("eurusd_m15")])
    verdict = FeasibilityChecker(catalog).check(make_idea())
    assert verdict.verdict == FEASIBLE
    assert verdict.min_rows == 30_000


def test_a_small_sample_blocks():
    from idea_machine.tests.conftest import make_dataset

    catalog = DataCatalog([make_dataset("nfp_actual_consensus", rows=50), make_dataset("eurusd_m15")])
    verdict = FeasibilityChecker(catalog).check(make_idea())
    assert verdict.verdict == BLOCKED_DATA


def test_default_catalog_is_empty_so_nothing_is_assumed():
    from idea_machine.economics.data_feasibility import default_catalog

    assert default_catalog().dataset_ids() == ()


# ---------------------------------------------------------------- economics


def test_an_effect_below_cost_fails():
    idea = make_idea(
        expected_effect=ExpectedEffect(0.00001, "PRICE", "BOTH", 4, "tiny")
    )
    verdict = EconomicPreFilter().check(idea)
    assert verdict.verdict == FAILED_ECONOMICS
    assert not verdict.may_proceed


def test_failing_economics_is_not_a_refutation():
    idea = make_idea(expected_effect=ExpectedEffect(0.00001, "PRICE", "BOTH", 4, "tiny"))
    verdict = EconomicPreFilter().check(idea)
    assert "not a refutation of the mechanism" in verdict.reason


def test_a_healthy_effect_is_viable():
    idea = make_idea(expected_effect=ExpectedEffect(0.0010, "PRICE", "BOTH", 4, "large"))
    verdict = EconomicPreFilter().check(idea)
    assert verdict.verdict == VIABLE
    assert verdict.effect_vs_cost > 2.0


def test_a_marginal_effect_is_kept_but_flagged():
    idea = make_idea(expected_effect=ExpectedEffect(0.00016, "PRICE", "BOTH", 4, "small"))
    verdict = EconomicPreFilter().check(idea)
    assert verdict.verdict == MARGINAL
    assert verdict.may_proceed


def test_horizon_mechanism_mismatch_is_warned():
    idea = make_idea(family="MICROSTRUCTURE", holding_period="MONTHS",
                     expected_effect=ExpectedEffect(0.0010, "PRICE", "BOTH", 4, "large"))
    verdict = EconomicPreFilter().check(idea)
    assert not verdict.horizon_coherent
    assert any("does not usually operate" in w for w in verdict.warnings)


def test_cost_comes_from_the_most_expensive_instrument():
    assert DEFAULT_COST_MODEL.worst_round_trip(("EURUSD", "XAUUSD")) == DEFAULT_COST_MODEL.round_trip("XAUUSD")


def test_an_instrument_with_no_cost_model_cannot_be_screened():
    with pytest.raises(KeyError):
        DEFAULT_COST_MODEL.round_trip("DOGECOIN")


# ------------------------------------------------------------------ ranking


def test_ranking_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_ranker_rejects_weights_that_do_not_sum_to_one():
    with pytest.raises(ValueError):
        IdeaRanker(weights={"novelty": 0.5})


def test_ranking_accepts_no_performance_input():
    """The signature itself is the guarantee: only pre-test verdicts go in."""
    import inspect

    params = set(inspect.signature(IdeaRanker.score).parameters)
    assert params == {"self", "idea", "novelty", "feasibility", "economics"}


def test_ranking_is_deterministic_and_totally_ordered(knowledge, catalog, tmp_path):
    ideas = IdeaGenerator(knowledge).generate().ideas
    memory = FailureMemory(tmp_path / "fm.json")
    nov_pass, nov = NoveltyChecker(memory).screen(ideas)
    feas_pass, feas = FeasibilityChecker(catalog).screen(nov_pass)
    econ_pass, econ = EconomicPreFilter().screen(feas_pass)
    args = dict(
        novelty={v.idea_id: v for v in nov},
        feasibility={v.idea_id: v for v in feas},
        economics={v.idea_id: v for v in econ},
    )
    a = IdeaRanker().rank(econ_pass, **args)
    b = IdeaRanker().rank(econ_pass, **args)
    assert [i.idea_id for i, _ in a] == [i.idea_id for i, _ in b]
    scores = [p.score for _, p in a]
    assert scores == sorted(scores, reverse=True)


def test_implausibly_large_claims_are_penalised_not_rewarded(knowledge, catalog, tmp_path):
    from idea_machine.tests.conftest import make_dataset

    big = make_idea(expected_effect=ExpectedEffect(0.05, "PRICE", "BOTH", 4, "suspiciously huge"))
    cat = DataCatalog([make_dataset(d) for d in big.required_data])
    memory = FailureMemory(tmp_path / "fm.json")
    nov = NoveltyChecker(memory).check(big)
    feas = FeasibilityChecker(cat).check(big)
    econ = EconomicPreFilter().check(big)
    priority = IdeaRanker().score(big, novelty=nov, feasibility=feas, economics=econ)
    assert priority.potential_magnitude == 0.5
    assert any("implausibly large" in n for n in priority.notes)


def test_repeatedly_failing_families_lose_priority(tmp_path):
    from idea_machine.tests.conftest import make_dataset

    idea = make_idea()
    cat = DataCatalog([make_dataset(d) for d in idea.required_data])
    priority = IdeaRanker(family_failure_counts={"EVENT": 12}).score(
        idea,
        novelty=NoveltyChecker(FailureMemory(tmp_path / "fm.json")).check(idea),
        feasibility=FeasibilityChecker(cat).check(idea),
        economics=EconomicPreFilter().check(idea),
    )
    assert priority.distance_from_failed_ideas == 0.1
