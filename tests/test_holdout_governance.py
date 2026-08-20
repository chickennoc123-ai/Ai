"""
Tests for holdout research exposure governance.

Enforces:
1. GEN 7-13 cannot access reserved holdout data
2. GEN 14 requires explicit authorization before holdout access
3. Candidate specification is frozen before GEN 14 holdout access
4. A GEN 14 failure cannot return to parameter tuning + retesting
5. Holdout consumption/reuse rules prevent replay attacks
"""

import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery._guards import HoldoutFirewallViolation, guard_path
from discovery.holdout_authorization import HoldoutAuthorizationGate, AuthorizedAccess
from discovery.candidate_spec_registry import (
    CandidateSpecRegistry, CandidateSpec, FrozenSpecViolation
)


# ---------------------------------------------------------------------------
# Test 1: GEN 7-13 cannot access reserved holdout data
# ---------------------------------------------------------------------------

class TestHoldoutFirewall:
    """Verify holdout firewall blocks GEN 7-13 from accessing sealed data."""

    def test_gen7_discovery_engine_blocked_from_holdout(self):
        """GEN 7 discovery engine cannot load holdout CSV."""
        holdout_path = REPO_ROOT / "data" / "holdout" / "EURUSD_H1_HOLDOUT_20240101_20260130_UTC.csv"
        if holdout_path.exists():
            with pytest.raises(HoldoutFirewallViolation):
                guard_path(holdout_path)

    def test_any_holdout_path_raises_violation(self):
        """Any path containing 'holdout' raises HoldoutFirewallViolation."""
        with pytest.raises(HoldoutFirewallViolation):
            guard_path(REPO_ROOT / "data" / "holdout" / "any_file.csv")

    def test_dev_paths_are_allowed(self):
        """Development paths bypass firewall."""
        dev_path = REPO_ROOT / "data" / "csv" / "EURUSD_H1.csv"
        guarded = guard_path(dev_path)
        assert guarded.exists() or not dev_path.exists()  # Path is allowed even if missing


# ---------------------------------------------------------------------------
# Test 2: GEN 14 requires explicit authorization before holdout access
# ---------------------------------------------------------------------------

class TestGen14Authorization:
    """Verify GEN 14 authorization gate controls holdout access."""

    def test_candidate_not_authorized_initially(self):
        """Candidates start without GEN 14 authorization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gate = HoldoutAuthorizationGate(Path(tmpdir) / "auth.json")
            assert not gate.is_gen14_authorized("CAND-001")

    def test_authorize_candidate_for_gen14(self):
        """Explicitly authorize candidate for GEN 14 holdout access."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gate = HoldoutAuthorizationGate(Path(tmpdir) / "auth.json")
            spec_hash = "abc123def456"
            authorized = gate.authorize_gen14_access("CAND-001", spec_hash)
            assert authorized
            assert gate.is_gen14_authorized("CAND-001")

    def test_authorization_requires_spec_hash(self):
        """Authorization binds to frozen spec hash (prevents tuning after authorization)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gate = HoldoutAuthorizationGate(Path(tmpdir) / "auth.json")
            hash1 = "hash_v1"
            gate.authorize_gen14_access("CAND-001", hash1)

            # Attempt to re-authorize with different spec hash raises error
            with pytest.raises(ValueError, match="hash mismatch"):
                gate.authorize_gen14_access("CAND-001", "hash_v2")

    def test_unauthorized_candidate_cannot_access_holdout(self):
        """Candidate without authorization cannot proceed to holdout evaluation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gate = HoldoutAuthorizationGate(Path(tmpdir) / "auth.json")
            # Simulate GEN 14 evaluation attempting to access holdout for CAND-002
            assert not gate.is_gen14_authorized("CAND-002")


# ---------------------------------------------------------------------------
# Test 3: Candidate spec is frozen before GEN 14 holdout access
# ---------------------------------------------------------------------------

class TestCandidateSpecFreeze:
    """Verify candidate specs are immutable once frozen for GEN 14."""

    def test_candidate_spec_mutable_initially(self):
        """Newly registered specs are mutable (GEN 7-13 phase)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = CandidateSpecRegistry(Path(tmpdir) / "specs.json")
            spec = reg.register_candidate(
                "CAND-001",
                mechanism="streak_reversal",
                parameters={"k": 3, "horizon": 4},
                test_framework="streak_fade"
            )
            assert not spec.is_frozen()

    def test_candidate_spec_can_be_updated_before_freeze(self):
        """Parameters can be modified before freeze."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = CandidateSpecRegistry(Path(tmpdir) / "specs.json")
            spec = reg.register_candidate(
                "CAND-001",
                mechanism="streak_reversal",
                parameters={"k": 3},
                test_framework="streak_fade"
            )
            hash1 = spec.spec_hash

            updated = reg.update_candidate("CAND-001", parameters={"k": 5})
            assert updated.parameters["k"] == 5
            assert updated.spec_hash != hash1  # Hash changed

    def test_freeze_candidate_for_gen14(self):
        """Freeze candidate spec before GEN 14 authorization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = CandidateSpecRegistry(Path(tmpdir) / "specs.json")
            reg.register_candidate(
                "CAND-001",
                mechanism="streak_reversal",
                parameters={"k": 3},
                test_framework="streak_fade"
            )
            frozen = reg.freeze_candidate("CAND-001")
            assert frozen.is_frozen()
            assert frozen.frozen_at is not None

    def test_frozen_spec_cannot_be_modified(self):
        """After freeze, spec becomes read-only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = CandidateSpecRegistry(Path(tmpdir) / "specs.json")
            reg.register_candidate(
                "CAND-001",
                mechanism="streak_reversal",
                parameters={"k": 3},
                test_framework="streak_fade"
            )
            reg.freeze_candidate("CAND-001")

            # Attempt to modify frozen spec raises FrozenSpecViolation
            with pytest.raises(FrozenSpecViolation):
                reg.update_candidate("CAND-001", parameters={"k": 5})

    def test_spec_hash_matches_authorization(self):
        """Spec hash is deterministic and matches authorization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = CandidateSpecRegistry(Path(tmpdir) / "specs.json")
            spec = reg.register_candidate(
                "CAND-001",
                mechanism="streak_reversal",
                parameters={"k": 3, "horizon": 4},
                test_framework="streak_fade"
            )
            spec_hash = spec.spec_hash

            gate = HoldoutAuthorizationGate(Path(tmpdir) / "auth.json")
            gate.authorize_gen14_access("CAND-001", spec_hash)
            assert gate.is_gen14_authorized("CAND-001")


# ---------------------------------------------------------------------------
# Test 4: Failed candidate cannot return to parameter tuning + same holdout
# ---------------------------------------------------------------------------

class TestFailedCandidateTerminal:
    """Verify GEN 14 failures are terminal; no re-tuning and reuse."""

    def test_failed_candidate_cannot_be_reauthorized(self):
        """Once result recorded, cannot re-authorize for another attempt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gate = HoldoutAuthorizationGate(Path(tmpdir) / "auth.json")
            gate.authorize_gen14_access("CAND-001", "spec_hash_1")
            gate.record_gen14_result("CAND-001", "FAIL")

            # Attempt to re-authorize raises error
            with pytest.raises(ValueError, match="already has GEN 14 result"):
                gate.authorize_gen14_access("CAND-001", "spec_hash_1")

    def test_failed_candidate_result_is_immutable(self):
        """Result cannot be changed once recorded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gate = HoldoutAuthorizationGate(Path(tmpdir) / "auth.json")
            gate.authorize_gen14_access("CAND-001", "spec_hash_1")
            gate.record_gen14_result("CAND-001", "FAIL")

            # Attempt to record different result raises error
            with pytest.raises(ValueError, match="already has result"):
                gate.record_gen14_result("CAND-001", "PASS")

    def test_failure_prevents_parameter_tuning(self):
        """Failed candidates cannot be re-tuned (frozen after result)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = CandidateSpecRegistry(Path(tmpdir) / "specs.json")
            gate = HoldoutAuthorizationGate(Path(tmpdir) / "auth.json")

            # Register, freeze, authorize
            reg.register_candidate("CAND-001", "mechanism_A", {"k": 3}, "test_framework")
            reg.freeze_candidate("CAND-001")
            gate.authorize_gen14_access("CAND-001", reg.get_hash("CAND-001"))

            # Record failure
            gate.record_gen14_result("CAND-001", "FAIL")

            # Attempt to re-tune raises FrozenSpecViolation (permanently frozen)
            with pytest.raises(FrozenSpecViolation):
                reg.update_candidate("CAND-001", parameters={"k": 5})


# ---------------------------------------------------------------------------
# Test 5: Holdout consumption/reuse rules (replay prevention)
# ---------------------------------------------------------------------------

class TestHoldoutConsumption:
    """Verify holdout consumption rules prevent replay attacks."""

    def test_holdout_marked_consumed_after_result(self):
        """Holdout is marked consumed once result recorded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gate = HoldoutAuthorizationGate(Path(tmpdir) / "auth.json")
            gate.authorize_gen14_access("CAND-001", "spec_hash_1")
            assert not gate.authorizations["CAND-001"].holdout_consumed

            gate.record_gen14_result("CAND-001", "PASS")
            assert gate.authorizations["CAND-001"].holdout_consumed

    def test_consumed_holdout_no_reuse(self):
        """Once consumed, holdout cannot be revisited."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gate = HoldoutAuthorizationGate(Path(tmpdir) / "auth.json")
            gate.authorize_gen14_access("CAND-001", "spec_hash_1")
            gate.record_gen14_result("CAND-001", "PASS")

            # Cannot re-authorize same candidate against same holdout
            with pytest.raises(ValueError, match="already has GEN 14 result"):
                gate.authorize_gen14_access("CAND-001", "spec_hash_1")

    def test_multiple_candidates_independent_authorization(self):
        """Different candidates can be authorized independently."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gate = HoldoutAuthorizationGate(Path(tmpdir) / "auth.json")

            # CAND-001 passes
            gate.authorize_gen14_access("CAND-001", "spec_hash_1")
            gate.record_gen14_result("CAND-001", "PASS")

            # CAND-002 can still be authorized (different candidate)
            gate.authorize_gen14_access("CAND-002", "spec_hash_2")
            assert gate.is_gen14_authorized("CAND-002")


# ---------------------------------------------------------------------------
# Integration Test: Full GEN 7-14 workflow with governance
# ---------------------------------------------------------------------------

class TestFullGen7To14Workflow:
    """Integration test of GEN 7-14 workflow with governance controls."""

    def test_complete_candidate_lifecycle(self):
        """Candidate goes from creation (GEN 7) through failure (GEN 14)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = CandidateSpecRegistry(Path(tmpdir) / "specs.json")
            gate = HoldoutAuthorizationGate(Path(tmpdir) / "auth.json")

            # GEN 7: Create candidate (mutable)
            spec = reg.register_candidate(
                "CAND-EURUSD-001",
                mechanism="streak_reversal, k=3",
                parameters={"k": 3, "horizon": 4, "hours": [9, 10]},
                test_framework="streak_fade"
            )
            assert not spec.is_frozen()

            # GEN 7-13: Tune parameters as research evolves
            reg.update_candidate("CAND-EURUSD-001", parameters={"k": 3, "horizon": 5})
            assert not spec.is_frozen()

            # Prepare for GEN 14: Freeze spec
            frozen = reg.freeze_candidate("CAND-EURUSD-001")
            assert frozen.is_frozen()

            # GEN 14: Authorize for holdout access
            spec_hash = reg.get_hash("CAND-EURUSD-001")
            gate.authorize_gen14_access("CAND-EURUSD-001", spec_hash, phase="QUALIFICATION")
            assert gate.is_gen14_authorized("CAND-EURUSD-001")

            # GEN 14: Evaluate on holdout → FAIL
            gate.record_gen14_result("CAND-EURUSD-001", "FAIL")
            assert gate.has_gen14_result("CAND-EURUSD-001")

            # Post-GEN 14: Candidate is terminal
            # Cannot re-tune or reteste
            with pytest.raises(FrozenSpecViolation):
                reg.update_candidate("CAND-EURUSD-001", parameters={"k": 4})

            # Cannot re-authorize for same holdout
            with pytest.raises(ValueError):
                gate.authorize_gen14_access("CAND-EURUSD-001", spec_hash)

    def test_governance_audit_trail(self):
        """Authorization and spec registries maintain audit trail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = CandidateSpecRegistry(Path(tmpdir) / "specs.json")
            gate = HoldoutAuthorizationGate(Path(tmpdir) / "auth.json")

            # Create and freeze 3 candidates
            for i in range(1, 4):
                reg.register_candidate(
                    f"CAND-{i:03d}",
                    f"mechanism_{i}",
                    {"k": i},
                    "test_framework"
                )
                reg.freeze_candidate(f"CAND-{i:03d}")

            # Authorize and record results
            for i in range(1, 4):
                spec_hash = reg.get_hash(f"CAND-{i:03d}")
                gate.authorize_gen14_access(f"CAND-{i:03d}", spec_hash)
                result = "PASS" if i == 1 else "FAIL"
                gate.record_gen14_result(f"CAND-{i:03d}", result)

            # Verify summary
            reg_summary = reg.summary()
            gate_summary = gate.summary()

            assert reg_summary["total_candidates"] == 3
            assert reg_summary["frozen_for_gen14"] == 3
            assert gate_summary["total_authorizations"] == 3
            assert gate_summary["results_recorded"]["PASS"] == 1
            assert gate_summary["results_recorded"]["FAIL"] == 2
