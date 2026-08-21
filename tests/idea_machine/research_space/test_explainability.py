"""Phase 9 explainability tests (spec item 12, 26, 30 "Explainability")."""

from __future__ import annotations

import pytest

from idea_machine.research_space.decision_record import DecisionLedger, DecisionRecord
from idea_machine.research_space.explain import explain_dict, render_explain


def test_decision_record_requires_a_reason():
    with pytest.raises(ValueError):
        DecisionRecord(
            cycle_id="C1", decision="EXPLORE", target="X", reason="",
            evidence=[], alternatives_considered=[], score_breakdown={}, confidence="LOW", reversible=True,
        )


def test_decision_record_rejects_unknown_confidence():
    with pytest.raises(ValueError):
        DecisionRecord(
            cycle_id="C1", decision="EXPLORE", target="X", reason="because",
            evidence=[], alternatives_considered=[], score_breakdown={}, confidence="VERY_SURE", reversible=True,
        )


def test_every_decision_record_has_evidence_and_score_breakdown():
    d = DecisionRecord(
        cycle_id="C1", decision="EXPLORE", target="X", reason="unexplored driver, real data confirmed",
        evidence=["driver JP225 confirmed present, never used"], alternatives_considered=["Y", "Z"],
        score_breakdown={"information_gain": 8.0, "total": 8.0}, confidence="MEDIUM", reversible=True,
    )
    data = d.to_dict()
    assert data["evidence"]
    assert data["score_breakdown"]
    assert data["alternatives_considered"] == ["Y", "Z"]


def test_decision_ledger_roundtrips_and_explain_finds_it(decision_ledger):
    d = DecisionRecord(
        cycle_id="C1", decision="ACCEPT", target="RSC-abc123", reason="score 30 ranked in top slots",
        evidence=["real evidence string"], alternatives_considered=[],
        score_breakdown={"information_gain": 20.0, "total": 30.0}, confidence="HIGH", reversible=True,
    )
    decision_ledger.record(d)

    got = decision_ledger.get(d.decision_id)
    assert got is not None
    assert got["decision"] == "ACCEPT"

    text = render_explain(d.decision_id, ledger=decision_ledger)
    assert "WHY:" in text
    assert "EVIDENCE:" in text
    assert "SCORE BREAKDOWN:" in text
    assert "GOVERNANCE CHECKS:" in text
    assert "score 30 ranked in top slots" in text


def test_explain_missing_decision_reports_not_found(decision_ledger):
    text = render_explain("DEC-doesnotexist", ledger=decision_ledger)
    assert "No decision found" in text


def test_explain_dict_returns_full_row(decision_ledger):
    d = DecisionRecord(
        cycle_id="C1", decision="REJECT", target="RSC-xyz", reason="outranked this cycle",
        evidence=["e1"], alternatives_considered=["a1"], score_breakdown={"total": 2.0},
        confidence="LOW", reversible=True,
    )
    decision_ledger.record(d)
    got = explain_dict(d.decision_id, ledger=decision_ledger)
    assert got["decision_id"] == d.decision_id
    assert got["confidence"] == "LOW"


def test_score_breakdown_is_additive_and_transparent():
    from idea_machine.research_space.information_gain import ScoreBreakdown

    b = ScoreBreakdown(
        information_gain=20.0, novelty_value=15.0, unexplored_space_value=10.0,
        evidence_gap_value=0.0, economic_plausibility=12.0, data_feasibility=10.0,
        redundancy_penalty=5.0, refuted_similarity_penalty=0.0, cost_risk=0.0,
    )
    assert b.total == 20.0 + 15.0 + 10.0 + 0.0 + 12.0 + 10.0 - 5.0 - 0.0 - 0.0
    explanation = b.explain()
    assert "information_gain: +20.0" in explanation
    assert "redundancy: -5.0" in explanation
    assert f"TOTAL: {b.total}" in explanation
