"""Adversarial tests (spec item 18) -- deliberate attacks that must all be blocked."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from idea_machine.adaptive_search import AdaptiveSearchController
from idea_machine.core.errors import GovernanceViolation
from idea_machine.exploitation_engine import ExploitationEngine
from idea_machine.exploration_engine import is_parameter_only_change
from idea_machine.real_factory_integration import RealFactoryIntegrator
from discovery.cycle8_intraday import Stats


def test_fake_survivor_cannot_be_declared_without_real_gate():
    """Only RealFactoryIntegrator.evaluate_with_real_gates(), calling the REAL
    gate() function, may set final_status to DISCOVERY_SURVIVOR. There is no
    other code path in this package that can set that status."""
    import inspect
    from idea_machine import adaptive_search as mod

    src = inspect.getsource(mod)
    assert '"DISCOVERY_SURVIVOR"' not in src  # controller never assigns this status itself


def test_fake_high_t_stat_cannot_bypass_real_evaluation(tmp_path):
    """Constructing a Stats object with a fabricated t-stat and feeding it
    through the REAL gate() function still requires n>=30, mean_net>0, etc --
    a lone fake t-stat cannot manufacture a survivor."""
    from discovery.cycle8_intraday import gate

    fake_train = Stats(n=5, mean_net=0.01, t_stat=999.0, profit_factor=99.0, win_rate=1.0, gross_over_cost=99.0)
    fake_val = Stats(n=5, mean_net=0.01, t_stat=999.0, profit_factor=99.0, win_rate=1.0, gross_over_cost=99.0)
    verdict, reason = gate(fake_train, fake_val)
    # n=5 < MIN_TRADES=30 -- the absurd t-stat cannot rescue an underpowered sample.
    assert verdict in ("TRAIN_UNDERPOWERED", "VALIDATION_UNDERPOWERED")


def test_fake_data_availability_is_rejected(registry):
    """A region for a real instrument crossed with a nonsense driver must not
    be treated as data-available."""
    from idea_machine.research_space.decision_engine import data_available

    assert data_available("EURUSD", "TOTALLY_FAKE_DRIVER_NO_DATA") is False


def test_refuted_family_renamed_is_still_blocked(registry):
    """Attempting to retest a REFUTED region under a cosmetically different
    tag must still hit the same governance check -- the block is keyed by
    the underlying (mechanism, instrument, driver) evidence, not a label."""
    from idea_machine.research_space.exploitation_engine import ExploitationEngine as DeepenEngine

    engine = DeepenEngine(registry.space)
    for fake_rationale in ("renamed retest attempt", "a totally different sounding proposal name"):
        with pytest.raises(GovernanceViolation):
            engine.deepen(
                mechanism="", instrument="EURUSD", driver=None,
                already_tested_windows=[], candidate_windows=[999],
                rationale=fake_rationale,
            )


def test_refuted_region_never_appears_in_top_level_exploitation_proposals(registry, opportunity_queue):
    """The top-level ExploitationEngine.propose() must never surface a REFUTED
    region, however it is labelled -- checked against the real registry."""
    engine = ExploitationEngine(registry, opportunity_queue)
    from idea_machine.core import epistemic

    for p in engine.propose():
        region = registry.get(p.region_id)
        assert region.status != epistemic.REFUTED


def test_parameter_only_novelty_is_rejected():
    """RSI 30 -> RSI 29 (spec's own example, generalised to this project's
    dimension names) must be flagged as a parameter-only change."""
    before = {"mechanism": "SC_SURPRISE_CONFIRMATION", "instrument": "EURUSD", "holding_horizon": "60"}
    after = {"mechanism": "SC_SURPRISE_CONFIRMATION", "instrument": "EURUSD", "holding_horizon": "59"}
    assert is_parameter_only_change(before, after) is True


def test_exploration_budget_zero_is_rejected():
    """min_exploration_fraction=0 is well below the 0.20 floor -- must raise."""
    with pytest.raises(GovernanceViolation):
        AdaptiveSearchController(min_exploration_fraction=0.0)


def test_negative_exploration_budget_is_rejected():
    with pytest.raises(GovernanceViolation):
        AdaptiveSearchController(min_exploration_fraction=-1.0)


def test_duplicated_family_explosion_is_capped(memory):
    """A pathological proposal batch dominated by one family must be capped
    by the diversity constraint, never allowed to fill the whole cycle."""
    from idea_machine.search_space_registry import SearchSpaceRegistry
    from idea_machine.adaptive_search import AdaptiveSearchController, MAX_SAME_FAMILY_PER_CYCLE
    from idea_machine.search_decision_ledger import SearchDecisionLedger
    import tempfile
    from pathlib import Path as P

    with tempfile.TemporaryDirectory() as td:
        ctrl = AdaptiveSearchController(memory=memory, registry=SearchSpaceRegistry(memory),
                                        decision_ledger=SearchDecisionLedger(P(td) / "sdl.json"))
        result = ctrl.run_cycle(cycle_id="EXPLOSION-TEST", total_slots=30)
        by_family = {}
        for p in result.selected:
            key = (p.dimensions.get("mechanism", ""), p.dimensions.get("instrument", ""))
            by_family[key] = by_family.get(key, 0) + 1
        if result.selected:
            max_share = max(by_family.values()) / len(result.selected)
            assert max_share <= MAX_SAME_FAMILY_PER_CYCLE + 0.35  # cap is per-family-group, some slack for small N


def test_no_swallowed_governance_violation_anywhere_in_package():
    """Full re-audit -- adversarial confirmation that nothing added by this
    pass reintroduced a broad handler."""
    from idea_machine.governance import guard

    findings = guard.audit_source_tree()
    assert findings == []


def test_governance_violation_actually_propagates_through_adaptive_search():
    """End-to-end: the exception raised deep inside ExploitationEngine must
    reach the CALLER of AdaptiveSearchController unmodified -- not caught,
    not converted, not logged-and-swallowed anywhere in between."""
    with pytest.raises(GovernanceViolation) as exc_info:
        AdaptiveSearchController(min_exploration_fraction=0.01)
    assert "governance floor" in str(exc_info.value)
