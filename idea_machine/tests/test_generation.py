"""Generator, combinator, knowledge base, and determinism (Phases 2-4)."""

from __future__ import annotations

import pytest

from idea_machine.combinator.combinator import MAX_DEPTH, CombinationEngine
from idea_machine.core import epistemic
from idea_machine.core.errors import KnowledgeError
from idea_machine.core.families import FAMILY_NAMES, get_family, horizon_is_plausible
from idea_machine.generator.generator import IdeaGenerator
from idea_machine.generator.templates import TEMPLATES
from idea_machine.knowledge.base import ConceptEdge, Finding, KnowledgeBase
from idea_machine.knowledge.taxonomy import MECHANISM_LABEL, is_bindable, kind_of


# ----------------------------------------------------------------- knowledge


def test_edges_must_name_their_sources():
    with pytest.raises(KnowledgeError) as exc:
        ConceptEdge("NFP", "AFFECTS", "USD", ())
    assert "unattributed" in str(exc.value).lower()


def test_unknown_relation_is_rejected():
    with pytest.raises(KnowledgeError):
        ConceptEdge("NFP", "CAUSES_MAGICALLY", "USD", ("SRC-1",))


def test_finding_cannot_be_created_already_survived(tmp_path):
    kb = KnowledgeBase(tmp_path / "k.json")
    with pytest.raises(KnowledgeError) as exc:
        kb.record_finding(
            Finding(family="EVENT", mechanism_signature="s", horizon="INTRADAY",
                    state=epistemic.SURVIVED, statement="skipping straight to the answer")
        )
    assert "must pass through the states" in str(exc.value)


def test_finding_history_is_preserved(tmp_path):
    kb = KnowledgeBase(tmp_path / "k.json")
    for state, note in [
        (epistemic.KNOWN, "claimed"), (epistemic.TESTED, "tested"), (epistemic.UNDERPOWERED, "small n"),
    ]:
        kb.record_finding(
            Finding(family="EVENT", mechanism_signature="s", horizon="INTRADAY", state=state, statement=note)
        )
    fid = kb.findings()[0].finding_id
    assert len(kb.finding_history(fid)) == 3
    assert kb.state_of(family="EVENT", mechanism_signature="s", horizon="INTRADAY") == epistemic.UNDERPOWERED
    assert not kb.is_refuted(family="EVENT", mechanism_signature="s", horizon="INTRADAY")


def test_illegal_state_jump_is_blocked(tmp_path):
    kb = KnowledgeBase(tmp_path / "k.json")
    kb.record_finding(Finding(family="EVENT", mechanism_signature="s", horizon="INTRADAY",
                              state=epistemic.KNOWN, statement="claimed"))
    with pytest.raises(KnowledgeError):
        kb.record_finding(Finding(family="EVENT", mechanism_signature="s", horizon="INTRADAY",
                                  state=epistemic.SURVIVED, statement="jump"))


def test_source_ids_are_recoverable_from_concepts(knowledge):
    assert knowledge.source_ids_for("NFP")
    assert knowledge.source_ids_for("NOT_A_CONCEPT") == ()


# ---------------------------------------------------------------- taxonomy


def test_mechanism_labels_are_never_bindable():
    for label in ("MOMENTUM", "MEAN_REVERSION", "LEAD_LAG", "CARRY_TRADE"):
        assert kind_of(label) == MECHANISM_LABEL
        assert not is_bindable(label)


def test_unknown_concepts_are_unbindable():
    assert not is_bindable("SOMETHING_NOBODY_DEFINED")


# ---------------------------------------------------------------- generator


def test_generation_is_deterministic(knowledge):
    a = IdeaGenerator(knowledge).generate()
    b = IdeaGenerator(knowledge).generate()
    assert [i.idea_id for i in a.ideas] == [i.idea_id for i in b.ideas]


def test_generated_ideas_are_well_formed(knowledge):
    ideas = IdeaGenerator(knowledge).generate().ideas
    assert ideas
    for idea in ideas:
        assert idea.family in FAMILY_NAMES
        assert len(idea.mechanism.split()) >= 15
        assert idea.falsification_condition
        assert idea.instruments
        assert idea.required_data
        assert idea.provenance.authority == "DERIVED_HYPOTHESIS"


def test_every_generated_idea_traces_back_to_a_source(knowledge):
    for idea in IdeaGenerator(knowledge).generate().ideas:
        assert idea.provenance.parents, f"{idea.idea_id} has no source lineage"


def test_generator_only_binds_supported_concept_pairs(tmp_path):
    """With no edges and no shared sources, nothing should be proposed."""
    empty = KnowledgeBase(tmp_path / "empty.json")
    assert IdeaGenerator(empty).generate().ideas == ()


def test_generator_respects_role_kinds(knowledge):
    """A calendar template must never bind a non-calendar concept as driver."""
    for idea in IdeaGenerator(knowledge).generate().ideas:
        bindings = idea.entry.get("bindings", {})
        driver = bindings.get("driver")
        if idea.family == "SEASONALITY" and driver:
            assert kind_of(driver) == "CALENDAR_WINDOW", f"{driver} bound as a calendar driver"


def test_generated_horizons_match_their_family(knowledge):
    for idea in IdeaGenerator(knowledge).generate().ideas:
        assert horizon_is_plausible(idea.family, idea.holding_period)


def test_max_ideas_is_respected(knowledge):
    assert len(IdeaGenerator(knowledge, max_ideas=3).generate().ideas) == 3


def test_every_template_declares_role_kinds_for_every_role():
    for template in TEMPLATES:
        for role in template.roles:
            assert template.role_kinds.get(role), f"{template.template_id} role {role} unconstrained"


def test_every_family_declares_a_mechanism_question():
    for name in FAMILY_NAMES:
        family = get_family(name)
        assert family.mechanism_question.endswith("?")
        assert family.typical_horizon
        assert family.why_edge_could_persist


# --------------------------------------------------------------- combinator


def test_combination_is_deterministic(knowledge):
    base = IdeaGenerator(knowledge).generate().ideas
    a = CombinationEngine(knowledge).combine(base)
    b = CombinationEngine(knowledge).combine(base)
    assert [i.idea_id for i in a.ideas] == [i.idea_id for i in b.ideas]


def test_combinations_add_data_and_falsification(knowledge):
    base = IdeaGenerator(knowledge).generate().ideas
    for combined in CombinationEngine(knowledge).combine(base).ideas:
        assert combined.required_data
        assert combined.falsification_condition
        assert len(combined.mechanism) > 100


def test_combination_depth_is_capped(knowledge):
    base = IdeaGenerator(knowledge).generate().ideas
    engine = CombinationEngine(knowledge)
    first = engine.combine(base)
    second = engine.combine(first.ideas)
    assert second.ideas == ()
    assert all(r.reason == "max_depth_reached" for r in second.rejections)
    assert MAX_DEPTH == 1


def test_combination_rejects_unsupported_pairs(knowledge):
    base = IdeaGenerator(knowledge).generate().ideas
    result = CombinationEngine(knowledge).combine(base)
    reasons = {r.reason for r in result.rejections}
    assert "no_graph_support" in reasons, "brute-force pairs must be rejected"


def test_combination_does_not_double_condition(knowledge):
    base = IdeaGenerator(knowledge).generate().ideas
    result = CombinationEngine(knowledge).combine(base)
    assert "already_conditioned" in {r.reason for r in result.rejections}


def test_combination_preserves_parent_lineage(knowledge):
    base = IdeaGenerator(knowledge).generate().ideas
    for combined in CombinationEngine(knowledge).combine(base).ideas:
        assert combined.provenance.origin_kind == "COMBINATION"
        assert combined.provenance.parents
        assert combined.provenance.authority == "DERIVED_HYPOTHESIS"
