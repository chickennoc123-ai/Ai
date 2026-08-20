"""
GEN 14 -- final sealed-holdout evaluation of the 4 frozen C2-NFP candidates.

These tests verify the TERMINAL, ALREADY-CONSUMED state of the real holdout
run (0/4 PASS) is correctly recorded and structurally irreversible. They do
not re-run any evaluation against real holdout data -- that would violate the
one-shot consumption rule this project exists to enforce.
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.candidate_spec_registry import CandidateSpecRegistry, FrozenSpecViolation
from discovery.holdout_authorization import HoldoutAuthorizationGate
from core.factory.evidence_vault import EvidenceVault

RESULT = REPO_ROOT / "reports/factory/gen14_c2_nfp_qualification.json"
CANDIDATES = ["CAND-C2-NFP-GBPUSD", "CAND-C2-NFP-USDCHF",
             "CAND-C2-NFP-USDJPY", "CAND-C2-NFP-XAUUSD"]


class TestGen14Verdict:
    @pytest.fixture(scope="class")
    def payload(self):
        return json.loads(RESULT.read_text())

    def test_all_four_evaluated(self, payload):
        assert payload["candidates_evaluated"] == 4

    def test_verdict_is_zero_of_four_pass(self, payload):
        assert payload["passed"] == 0
        assert payload["failed"] == 4

    def test_every_result_used_the_fixed_bonferroni_m(self, payload):
        for r in payload["individual_results"]:
            assert r["multiple_testing"]["fixed_M"] == 1222

    def test_every_candidate_marked_terminal(self, payload):
        for r in payload["individual_results"]:
            assert r["terminal"] is True

    def test_calendar_tail_gap_was_disclosed_per_candidate(self, payload):
        for r in payload["individual_results"]:
            assert "2026-01-30" in r["event_source_note"]

    def test_sign_consistency_reported_without_overclaiming(self, payload):
        assert "4/4" in payload["mechanism_note"] or "positive" in payload["mechanism_note"]
        assert "cleared every GEN 14 gate" in payload["mechanism_note"]


class TestGovernanceStateIsTerminal:
    def test_all_four_holdout_datasets_consumed(self):
        ev = json.loads((REPO_ROOT / "reports/factory/evidence_vault.json").read_text())
        for sym in ("GBPUSD", "USDCHF", "USDJPY", "XAUUSD"):
            did = next(d for d in ev["datasets"] if d.startswith(f"DS-HOLDOUT-{sym}-"))
            assert ev["datasets"][did]["seal_status"] == "consumed"

    def test_four_consumption_records_exist_all_fail(self):
        ev = json.loads((REPO_ROOT / "reports/factory/evidence_vault.json").read_text())
        gen14_consumptions = [c for c in ev["consumptions"]
                              if c["candidate_id"] in CANDIDATES]
        assert len(gen14_consumptions) == 4
        assert all(c["result_summary"] == "FAIL" for c in gen14_consumptions)

    def test_holdout_authorization_gate_shows_terminal_fail_for_all_four(self):
        gate = HoldoutAuthorizationGate(REPO_ROOT / "reports/factory/holdout_authorization_registry.json")
        for cid in CANDIDATES:
            assert gate.has_gen14_result(cid)
            auth = gate.authorizations[cid]
            assert auth.holdout_consumed is True
            assert auth.result == "FAIL"

    def test_eurusd_holdout_untouched_by_this_run(self):
        """The original EURUSD holdout (Gen 6) must remain independent of this run."""
        ev = json.loads((REPO_ROOT / "reports/factory/evidence_vault.json").read_text())
        eurusd = ev["datasets"]["DS-HOLDOUT-EURUSD-H1-HISTDATA-20240101-20260130"]
        assert eurusd["seal_status"] == "sealed"  # unchanged: still just sealed, not consumed


class TestTerminalityIsEnforced:
    def test_failed_candidates_cannot_be_retuned(self):
        reg = CandidateSpecRegistry(REPO_ROOT / "reports/factory/candidate_spec_registry.json")
        for cid in CANDIDATES:
            with pytest.raises(FrozenSpecViolation):
                reg.update_candidate(cid, parameters={"post_hours": 8})

    def test_failed_candidates_cannot_be_reauthorized(self):
        gate = HoldoutAuthorizationGate(REPO_ROOT / "reports/factory/holdout_authorization_registry.json")
        reg = CandidateSpecRegistry(REPO_ROOT / "reports/factory/candidate_spec_registry.json")
        for cid in CANDIDATES:
            spec_hash = reg.get_hash(cid)
            with pytest.raises(ValueError, match="already has GEN 14 result"):
                gate.authorize_gen14_access(cid, spec_hash)

    def test_datasets_cannot_be_reconsumed(self):
        vault = EvidenceVault()
        for sym in ("GBPUSD", "USDCHF", "USDJPY", "XAUUSD"):
            did = next(d for d in vault.datasets if d.startswith(f"DS-HOLDOUT-{sym}-"))
            with pytest.raises(ValueError, match="already consumed"):
                vault.consume_dataset(did, f"CAND-RETRY-{sym}", "x", "x")


class TestFailureMemoryIsGovernanceSafe:
    def test_failure_record_exists(self):
        fl = json.loads((REPO_ROOT / "reports/factory/failure_library.json").read_text())
        fails = fl.get("failures", fl if isinstance(fl, list) else [])
        assert any(f["failure_id"] == "FAIL-000037" for f in fails)

    def test_failure_record_does_not_leak_holdout_statistics(self):
        fl = json.loads((REPO_ROOT / "reports/factory/failure_library.json").read_text())
        fails = fl.get("failures", fl if isinstance(fl, list) else [])
        rec = next(f for f in fails if f["failure_id"] == "FAIL-000037")
        blob = json.dumps(rec)
        # exact n/mean_net/t values from the real run must not appear verbatim
        payload = json.loads(RESULT.read_text())
        for r in payload["individual_results"]:
            s = r["holdout_statistics"]
            assert str(s["mean_net"]) not in blob
            assert str(s["t_stat"]) not in blob

    def test_family_registry_shows_refuted_not_pending(self):
        reg = json.loads((REPO_ROOT / "reports/factory/research_family_registry.json").read_text())
        fam = reg["families"]["FAMILY-C2-SURPRISE-REACTION-NFP-USD"]
        assert fam["status"] == "REFUTED"
        assert fam["refuted_by"] == "FAIL-000037"


class TestNoOverclaiming:
    def test_no_proven_edge_language_anywhere_in_the_result(self):
        payload = json.loads(RESULT.read_text())
        blob = json.dumps(payload).lower()
        assert "proven edge" not in blob and "proven_edge" not in blob

    def test_no_ea_or_deployment_artifact_was_produced(self):
        ea_dir = REPO_ROOT / "artifacts/ea"
        for p in ea_dir.rglob("*"):
            if p.is_file() and "DEMO" not in str(p) and ".gitkeep" not in str(p):
                pytest.fail(f"unexpected EA artifact for a FAILED GEN 14 run: {p}")
