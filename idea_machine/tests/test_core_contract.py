"""Phase 0 contract tests: IdeaSpec immutability, identity, and provenance."""

from __future__ import annotations

import dataclasses

import pytest

from idea_machine.core.epistemic import (
    REFUTED,
    SURVIVED,
    TESTED,
    UNDERPOWERED,
    UNKNOWN,
    assert_transition,
    can_transition,
    is_edge_claim,
)
from idea_machine.core.errors import KnowledgeError, ProvenanceError, SpecValidationError
from idea_machine.core.idea_spec import (
    BANNED_RESULT_KEYS,
    ExpectedEffect,
    IdeaSpec,
    assert_no_result_fields,
    deduplicate,
)
from idea_machine.core.ids import canonical_json, content_hash, mint_id
from idea_machine.core.provenance import Provenance, combine

PROV = Provenance(
    origin_kind="ACADEMIC_PAPER",
    origin_ref="doi:10.1234/x",
    retrieved_at="2026-08-20T00:00:00+00:00",
    content_hash="abc123",
)


def make_idea(**overrides) -> IdeaSpec:
    base = dict(
        family="EVENT",
        hypothesis="EURUSD underreacts to large NFP surprises within the first hour.",
        mechanism=(
            "Dealers widen quotes during the release because inventory risk spikes, so the "
            "information is absorbed over the following bars rather than instantly."
        ),
        instruments=("EURUSD",),
        timeframe="M15",
        entry={"trigger": "nfp_surprise_z", "threshold": 1.5},
        exit={"rule": "time_stop", "bars": 4},
        holding_period="INTRADAY",
        required_data=("nfp_actual_consensus", "eurusd_m15"),
        economic_rationale="Attention constraints delay repricing around scheduled releases.",
        expected_effect=ExpectedEffect(0.00035, "PRICE", "BOTH", 4, "median 1h move on high-surprise days"),
        falsification_condition="No directional drift beyond cost after high-surprise releases.",
        provenance=PROV,
    )
    base.update(overrides)
    return IdeaSpec(**base)


# ---------------------------------------------------------------- immutability


def test_idea_spec_is_frozen():
    idea = make_idea()
    with pytest.raises(dataclasses.FrozenInstanceError):
        idea.hypothesis = "something else"


def test_idea_id_is_content_addressed_and_deterministic():
    a, b = make_idea(), make_idea()
    assert a.idea_id == b.idea_id
    assert a.idea_id.startswith("IDEA-")


def test_idea_id_ignores_created_at_and_provenance():
    """The same idea from two different papers is still the same idea."""
    other_source = Provenance(
        origin_kind="WEBSITE", origin_ref="https://elsewhere", retrieved_at="2026-01-01", content_hash="zzz"
    )
    a = make_idea(created_at="2026-01-01", provenance=PROV)
    b = make_idea(created_at="2026-08-20", provenance=other_source)
    assert a.idea_id == b.idea_id


def test_changing_the_rule_changes_the_identity():
    a = make_idea()
    b = make_idea(entry={"trigger": "nfp_surprise_z", "threshold": 2.5})
    assert a.idea_id != b.idea_id


def test_roundtrip_through_dict_preserves_identity():
    idea = make_idea()
    assert IdeaSpec.from_dict(idea.to_dict()).idea_id == idea.idea_id


def test_deduplicate_collapses_identical_ideas():
    assert len(deduplicate([make_idea(), make_idea(), make_idea(timeframe="H1")])) == 2


# ------------------------------------------------- no backtest results allowed


@pytest.mark.parametrize("banned", ["sharpe", "pnl", "win_rate", "max_drawdown", "backtest_result", "p_value"])
def test_result_fields_are_rejected_in_entry(banned):
    with pytest.raises(SpecValidationError) as exc:
        make_idea(entry={banned: 1.23, "trigger": "x"})
    assert "backtest result" in str(exc.value)


def test_result_fields_are_rejected_when_nested():
    with pytest.raises(SpecValidationError):
        make_idea(exit={"rule": "t", "nested": {"deeper": {"sharpe_ratio": 2.0}}})


def test_banned_key_list_covers_the_obvious_metrics():
    for metric in ("sharpe", "drawdown", "win_rate", "pnl", "cagr", "p_value"):
        assert any(metric in b for b in BANNED_RESULT_KEYS)


def test_assert_no_result_fields_accepts_a_clean_payload():
    assert_no_result_fields({"entry": {"threshold": 1.5}, "exit": {"take_profit_atr": 2.0}})


def test_expected_effect_is_not_treated_as_a_result():
    """A forecast is required; refusing to state one makes an idea unfalsifiable."""
    idea = make_idea()
    assert idea.expected_effect.magnitude > 0


# ------------------------------------------------------------ mechanism gating


def test_an_idea_without_a_real_mechanism_is_rejected():
    with pytest.raises(SpecValidationError) as exc:
        make_idea(mechanism="it works")
    assert "WHY an edge could exist" in str(exc.value)


def test_an_unfalsifiable_idea_is_rejected():
    with pytest.raises(SpecValidationError) as exc:
        make_idea(falsification_condition="nope")
    assert "falsification" in str(exc.value).lower()


def test_required_fields_are_enforced():
    for field, value in [("instruments", ()), ("required_data", ()), ("entry", {}), ("exit", {})]:
        with pytest.raises(SpecValidationError):
            make_idea(**{field: value})


def test_unknown_family_is_rejected():
    with pytest.raises(SpecValidationError):
        make_idea(family="ASTROLOGY")


# ------------------------------------------------------------------ provenance


def test_external_sources_can_never_exceed_idea_source_only():
    with pytest.raises(ProvenanceError):
        Provenance(
            origin_kind="WEBSITE", origin_ref="u", retrieved_at="t", content_hash="h",
            authority="VALIDATED_EVIDENCE",
        )


def test_reasoning_over_a_claim_does_not_upgrade_it():
    """DERIVED_HYPOTHESIS must not out-rank the IDEA_SOURCE_ONLY it came from."""
    derived = PROV.derive(
        origin_kind="INTERNAL_DERIVATION", origin_ref="x", retrieved_at="t", content_hash_="h"
    )
    assert derived.authority == "DERIVED_HYPOTHESIS"
    assert derived.rank == PROV.rank


def test_a_claim_cannot_be_laundered_into_an_observation():
    with pytest.raises(ProvenanceError):
        PROV.derive(
            origin_kind="INTERNAL_DERIVATION", origin_ref="x", retrieved_at="t",
            content_hash_="h", authority="INTERNAL_OBSERVATION",
        )


def test_combination_preserves_all_parents():
    other = Provenance(origin_kind="WEBSITE", origin_ref="u", retrieved_at="t", content_hash="h2")
    merged = combine(PROV, other, retrieved_at="t")
    assert len(merged.parents) == 2
    assert merged.authority == "DERIVED_HYPOTHESIS"


def test_combination_needs_at_least_two_parents():
    with pytest.raises(ProvenanceError):
        combine(PROV, retrieved_at="t")


def test_provenance_requires_its_identifying_fields():
    with pytest.raises(ProvenanceError):
        Provenance(origin_kind="WEBSITE", origin_ref="", retrieved_at="t", content_hash="h")


# ------------------------------------------------------------------ epistemic


def test_unknown_can_never_jump_to_survived():
    """The single rule the roadmap states most emphatically."""
    assert not can_transition(UNKNOWN, SURVIVED)
    with pytest.raises(KnowledgeError):
        assert_transition(UNKNOWN, SURVIVED)


def test_underpowered_is_not_refuted():
    assert UNDERPOWERED != REFUTED
    assert can_transition(UNDERPOWERED, TESTED), "an underpowered result must stay re-testable"
    assert not can_transition(REFUTED, TESTED), "a refutation is terminal"


def test_no_state_means_edge():
    for state in (UNKNOWN, TESTED, SURVIVED, REFUTED, UNDERPOWERED):
        assert is_edge_claim(state) is False


# ------------------------------------------------------------------- identity


def test_canonical_json_is_key_order_independent():
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_float_representation_is_stable():
    assert content_hash({"x": 0.1 + 0.2}) == content_hash({"x": 0.30000000000000004})


def test_mint_id_requires_a_prefix():
    with pytest.raises(ValueError):
        mint_id("", {"a": 1})
