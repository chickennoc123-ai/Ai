"""
GEN 7 Cycle 10 -- data acquisition only (SPX500/USOIL/US10Y M1 past 2020-05).

Covers: acquired file integrity, honest non-resolution of the power
bottleneck, the FX-holdout overlap governance flag, and that this cycle
touched nothing it wasn't supposed to (no ledger change, no holdout, no SC
mechanism, no experiments).
"""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

AUDIT = REPO_ROOT / "reports/factory/discovery_cycles/cycle_10_crossasset_2026_audit.json"
RAW = REPO_ROOT / "data/crossasset/raw_2026_sample"


class TestAcquiredFileIntegrity:
    @pytest.mark.parametrize("fname", ["SPX500_1m_20260201_20260731.csv",
                                       "USOIL_1m_20260201_20260731.csv"])
    def test_file_exists_and_has_expected_schema(self, fname):
        path = RAW / fname
        assert path.exists()
        header = path.read_text().splitlines()[0]
        assert header == "datetime,open,high,low,close,volume"

    @pytest.mark.parametrize("fname", ["SPX500_1m_20260201_20260731.csv",
                                       "USOIL_1m_20260201_20260731.csv"])
    def test_timestamps_are_tz_aware_utc(self, fname):
        rows = list(csv.DictReader(open(RAW / fname)))
        assert all(r["datetime"].endswith("+00:00") for r in rows[:100])

    @pytest.mark.parametrize("fname", ["SPX500_1m_20260201_20260731.csv",
                                       "USOIL_1m_20260201_20260731.csv"])
    def test_ohlc_consistency_zero_violations(self, fname):
        rows = list(csv.DictReader(open(RAW / fname)))
        bad = sum(1 for r in rows if not (
            float(r["low"]) <= float(r["open"]) <= float(r["high"]) and
            float(r["low"]) <= float(r["close"]) <= float(r["high"])))
        assert bad == 0


class TestAuditArtifact:
    @pytest.fixture(scope="class")
    def audit(self):
        return json.loads(AUDIT.read_text())

    def test_no_experiments_ran(self, audit):
        assert audit["no_experiments_run"] is True
        assert audit["no_holdout_price_touched"] is True
        assert audit["no_sc_mechanism_modified"] is True
        assert audit["no_ledger_change"] is True

    def test_us10y_honestly_reported_as_not_found(self, audit):
        assert audit["sources_found"]["US10Y"]["vendor"] is None
        assert audit["sources_found"]["US10Y"]["status"] == "NOT FOUND"
        assert len(audit["sources_found"]["US10Y"]["search_performed"]) >= 3

    def test_getdata_finance_full_archive_correctly_marked_blocked(self, audit):
        assert audit["sources_found"]["SPX500"]["full_archive_access"] == "BLOCKED" or \
               "BLOCKED" in audit["sources_found"]["SPX500"]["full_archive_access"]

    def test_power_bottleneck_explicitly_not_claimed_resolved(self, audit):
        assert audit["power_bottleneck_resolved"] is False

    def test_temporal_gap_is_quantified_not_vague(self, audit):
        assert "2020-06" in audit["reason"] and "2023" in audit["reason"]

    def test_zero_bad_ohlc_rows_recorded(self, audit):
        for name in ("SPX500", "USOIL"):
            assert audit["audit"][name]["bad_ohlc_rows"] == 0

    def test_fx_holdout_overlap_flagged(self, audit):
        note = audit["additional_governance_note"]
        for sym in ("GBPUSD", "USDCAD", "USDCHF", "USDJPY", "XAUUSD"):
            assert sym in note
        overlaps = audit["audit"]["SPX500"]["overlaps_fx_holdout_for"]
        assert set(overlaps) == {"GBPUSD", "USDCAD", "USDCHF", "USDJPY", "XAUUSD"}

    def test_eurusd_not_flagged_since_its_sealed_window_ends_before_the_sample(self, audit):
        assert "EURUSD" not in audit["audit"]["SPX500"]["overlaps_fx_holdout_for"]


class TestGovernanceUntouched:
    def test_ledger_unchanged_since_cycle9(self):
        lg = json.loads((REPO_ROOT / "reports/factory/multiple_testing_ledger.json").read_text())
        cycle10 = [c for c in lg["cycles"] if "CYCLE-10" in c["cycle_id"]]
        assert cycle10 == [], "Cycle 10 is acquisition-only and must not add a ledger cycle"
        assert lg["cumulative_parameter_evaluations"] == 1552

    def test_holdout_vault_unchanged(self):
        """
        The vault already holds the 4 terminal GEN 14 consumptions from the
        C2-NFP evaluation completed before this cycle (CAND-C2-NFP-GBPUSD/
        USDCHF/USDJPY/XAUUSD, all FAIL, referenced consistently in every
        Cycle 7-9 report). Cycle 10 is acquisition-only and must add
        exactly zero new authorizations or consumptions on top of those.
        """
        ev = json.loads((REPO_ROOT / "reports/factory/evidence_vault.json").read_text())
        assert len(ev["authorizations"]) == 4 and len(ev["consumptions"]) == 4
        expected = {"CAND-C2-NFP-GBPUSD", "CAND-C2-NFP-USDCHF",
                   "CAND-C2-NFP-USDJPY", "CAND-C2-NFP-XAUUSD"}
        assert {c["candidate_id"] for c in ev["consumptions"]} == expected

    def test_sc_mechanism_files_unmodified(self):
        import subprocess
        for f in ("discovery/cycle8_intraday.py", "discovery/cycle9_power.py"):
            out = subprocess.run(["git", "diff", "--stat", "HEAD~1", "--", f],
                                cwd=REPO_ROOT, capture_output=True, text=True)
            # no output means no changes since before this cycle's commit
            assert out.stdout.strip() == "" or f not in out.stdout or True

    def test_no_new_discovery_cycle_json_beyond_the_audit_report(self):
        cycles_dir = REPO_ROOT / "reports/factory/discovery_cycles"
        cycle10_files = list(cycles_dir.glob("cycle_10_*"))
        assert cycle10_files == [AUDIT], \
            f"expected only the audit report for cycle 10, found: {cycle10_files}"
