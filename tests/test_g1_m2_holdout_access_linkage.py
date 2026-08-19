"""Closes Generation 1 finding G1-M2 (holdout access linkage).

Per ML-001-GENERATION-1-INDEPENDENT-AUDIT.md finding G1: HOLDOUT_TESTED
was pure bookkeeping, with no code-level tie to a verified real holdout
access. core.factory.holdout_access.HoldoutAccessEvent plus
StrategyRegistry.transition()'s new validation is the fix.

No real holdout data is touched anywhere in this file -- every event uses
synthetic fixture identifiers, per the task's explicit "do not actually
expose real holdout data during Generation 2" instruction.
"""

from __future__ import annotations

import pytest

from core.factory.holdout_access import HoldoutAccessEvent, HoldoutAccessEventError, validate_holdout_access_event
from core.factory.registry import HoldoutAccessEventRequiredError, StrategyRegistry
from core.factory.state_machine import CandidateState
from tests.test_factory_registry import _holdout_event, _spec, _walk_to_frozen, _walk_to_holdout_tested


class TestHoldoutAccessEventCompleteness:
    def test_complete_event_constructs(self) -> None:
        HoldoutAccessEvent(
            candidate_id="STRAT-000099", candidate_version=1, dataset_id="D", dataset_checksum="c",
            holdout_partition_identity="P", access_timestamp="2026-01-01T00:00:00+00:00",
            frozen_state_confirmed=True, evidence_reference="ref",
        )

    @pytest.mark.parametrize(
        "field", ["candidate_id", "dataset_id", "dataset_checksum", "holdout_partition_identity",
                  "access_timestamp", "evidence_reference"],
    )
    def test_missing_required_field_rejected(self, field) -> None:
        kwargs = dict(
            candidate_id="STRAT-000099", candidate_version=1, dataset_id="D", dataset_checksum="c",
            holdout_partition_identity="P", access_timestamp="2026-01-01T00:00:00+00:00",
            frozen_state_confirmed=True, evidence_reference="ref",
        )
        kwargs[field] = ""
        with pytest.raises(HoldoutAccessEventError):
            HoldoutAccessEvent(**kwargs)

    def test_frozen_state_not_confirmed_is_rejected(self) -> None:
        """The event itself must assert the candidate was actually frozen
        at access time -- an event claiming otherwise cannot justify
        HOLDOUT_TESTED at all, regardless of who presents it."""
        with pytest.raises(HoldoutAccessEventError):
            HoldoutAccessEvent(
                candidate_id="STRAT-000099", candidate_version=1, dataset_id="D", dataset_checksum="c",
                holdout_partition_identity="P", access_timestamp="2026-01-01T00:00:00+00:00",
                frozen_state_confirmed=False, evidence_reference="ref",
            )

    def test_invalid_candidate_version_rejected(self) -> None:
        with pytest.raises(HoldoutAccessEventError):
            HoldoutAccessEvent(
                candidate_id="STRAT-000099", candidate_version=0, dataset_id="D", dataset_checksum="c",
                holdout_partition_identity="P", access_timestamp="2026-01-01T00:00:00+00:00",
                frozen_state_confirmed=True, evidence_reference="ref",
            )

    def test_event_is_frozen(self) -> None:
        import dataclasses

        event = HoldoutAccessEvent(
            candidate_id="STRAT-000099", candidate_version=1, dataset_id="D", dataset_checksum="c",
            holdout_partition_identity="P", access_timestamp="2026-01-01T00:00:00+00:00",
            frozen_state_confirmed=True, evidence_reference="ref",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.candidate_id = "STRAT-000001"  # type: ignore[misc]

    def test_event_checksum_is_deterministic_and_content_sensitive(self) -> None:
        e1 = HoldoutAccessEvent(
            candidate_id="STRAT-000099", candidate_version=1, dataset_id="D", dataset_checksum="c",
            holdout_partition_identity="P", access_timestamp="2026-01-01T00:00:00+00:00",
            frozen_state_confirmed=True, evidence_reference="ref",
        )
        e2 = HoldoutAccessEvent(**{**e1.to_dict()})
        e3 = HoldoutAccessEvent(**{**e1.to_dict(), "evidence_reference": "different"})
        assert e1.event_checksum() == e2.event_checksum()
        assert e1.event_checksum() != e3.event_checksum()


class TestValidateHoldoutAccessEvent:
    def test_matching_candidate_id_and_version_passes(self) -> None:
        event = HoldoutAccessEvent(
            candidate_id="STRAT-000099", candidate_version=1, dataset_id="D", dataset_checksum="c",
            holdout_partition_identity="P", access_timestamp="2026-01-01T00:00:00+00:00",
            frozen_state_confirmed=True, evidence_reference="ref",
        )
        validate_holdout_access_event(event, candidate_id="STRAT-000099", candidate_version=1)  # must not raise

    def test_wrong_candidate_id_rejected(self) -> None:
        event = HoldoutAccessEvent(
            candidate_id="STRAT-000099", candidate_version=1, dataset_id="D", dataset_checksum="c",
            holdout_partition_identity="P", access_timestamp="2026-01-01T00:00:00+00:00",
            frozen_state_confirmed=True, evidence_reference="ref",
        )
        with pytest.raises(HoldoutAccessEventError):
            validate_holdout_access_event(event, candidate_id="STRAT-000001", candidate_version=1)

    def test_wrong_candidate_version_rejected(self) -> None:
        """An event minted for candidate v1 must not authorize v2's
        HOLDOUT_TESTED transition, or vice versa -- versions are distinct
        candidates in every sense that matters here."""
        event = HoldoutAccessEvent(
            candidate_id="STRAT-000099", candidate_version=1, dataset_id="D", dataset_checksum="c",
            holdout_partition_identity="P", access_timestamp="2026-01-01T00:00:00+00:00",
            frozen_state_confirmed=True, evidence_reference="ref",
        )
        with pytest.raises(HoldoutAccessEventError):
            validate_holdout_access_event(event, candidate_id="STRAT-000099", candidate_version=2)


class TestRegistryEnforcesHoldoutAccessEvent:
    def test_holdout_tested_without_event_is_rejected(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        _walk_to_frozen(reg, c.candidate_id)
        with pytest.raises(HoldoutAccessEventRequiredError):
            reg.transition(c.candidate_id, CandidateState.HOLDOUT_TESTED, reason="no event presented")
        # the failed attempt must not have advanced the candidate's state
        assert reg.get(c.candidate_id).state == CandidateState.FROZEN

    def test_holdout_tested_with_event_for_a_different_candidate_is_rejected(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c1 = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        c2 = reg.register(_spec(max_hold_bars=48), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        _walk_to_frozen(reg, c1.candidate_id)
        _walk_to_frozen(reg, c2.candidate_id)
        wrong_event = _holdout_event(reg, c2.candidate_id)  # minted for c2, presented for c1
        with pytest.raises(HoldoutAccessEventError):
            reg.transition(c1.candidate_id, CandidateState.HOLDOUT_TESTED, reason="wrong event", holdout_access_event=wrong_event)
        assert reg.get(c1.candidate_id).state == CandidateState.FROZEN

    def test_holdout_tested_with_valid_matching_event_succeeds(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        _walk_to_holdout_tested(reg, c.candidate_id)
        assert reg.get(c.candidate_id).state == CandidateState.HOLDOUT_TESTED

    def test_event_checksum_is_recorded_in_candidate_history_evidence_reference(self, tmp_path) -> None:
        """The event's identity is preserved in the audit trail, not
        discarded once validation succeeds."""
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        _walk_to_frozen(reg, c.candidate_id)
        event = _holdout_event(reg, c.candidate_id)
        reg.transition(c.candidate_id, CandidateState.HOLDOUT_TESTED, reason="evaluated", holdout_access_event=event)
        last_entry = reg.get(c.candidate_id).history[-1]
        assert last_entry["state"] == "HOLDOUT_TESTED"
        assert event.event_checksum() in last_entry["evidence_reference"]

