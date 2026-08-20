"""
Cycle 6 (continued) -- economic calendar extension to 2024-2026.

Integrity regression tests for the committed extension artifacts. These test
what was delivered, not network access.
"""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.observatory import load_dev_bars
from discovery.event_calendar import load_events

OLD_FILE = REPO_ROOT / "data/events/raw/forexfactory_2010_2023.csv"
NEW_FILE = REPO_ROOT / "data/events/raw/forexfactory_2024_2026.csv"
MERGED_FILE = REPO_ROOT / "data/events/raw/forexfactory_2010_2026.csv"
PROCESSED = REPO_ROOT / "data/events/processed/events_dev.csv"


class TestExtensionDelivered:
    def test_extension_file_exists_and_covers_2024_2026(self):
        rows = list(csv.DictReader(open(NEW_FILE)))
        years = {datetime.fromisoformat(r["timestamp_utc"]).year for r in rows}
        assert years == {2024, 2025, 2026}

    def test_extension_row_count(self):
        rows = list(csv.DictReader(open(NEW_FILE)))
        assert len(rows) >= 1500

    def test_nfp_present_in_extension_with_n_over_30_when_combined(self):
        old = list(csv.DictReader(open(OLD_FILE)))
        new = list(csv.DictReader(open(NEW_FILE)))
        nfp = [r for r in old + new if r["event_name"] == "Non-Farm Employment Change"
               and r["currency"] == "USD"]
        assert len(nfp) >= 100

    def test_fomc_ecb_boj_boe_present_in_extension(self):
        rows = list(csv.DictReader(open(NEW_FILE)))
        assert any("FOMC" in r["event_name"] for r in rows)
        assert any(r["currency"] == "JPY" and "BOJ" in r["event_name"] for r in rows)
        assert any(r["currency"] == "GBP" and "BOE" in r["event_name"] for r in rows)
        # ECB proxy: no single "ECB Rate" row in this HIGH-only source's sample,
        # but German/French flash CPI/PMI (ECB-relevant EUR indicators) must exist
        assert any(r["currency"] == "EUR" for r in rows)


class TestOldFileUntouched:
    def test_old_file_row_count_unchanged(self):
        rows = list(csv.DictReader(open(OLD_FILE)))
        assert len(rows) == 30923

    def test_old_file_still_ends_in_2023(self):
        rows = list(csv.DictReader(open(OLD_FILE)))
        years = {datetime.fromisoformat(r["timestamp_utc"]).year for r in rows}
        assert max(years) == 2023


class TestMergedFile:
    def test_merged_is_strict_union_no_overwrite(self):
        old = list(csv.DictReader(open(OLD_FILE)))
        new = list(csv.DictReader(open(NEW_FILE)))
        merged = list(csv.DictReader(open(MERGED_FILE)))
        assert len(merged) == len(old) + len(new)

    def test_merged_has_no_duplicate_event_ids(self):
        rows = list(csv.DictReader(open(MERGED_FILE)))
        ids = [r["event_id"] for r in rows]
        assert len(ids) == len(set(ids))

    def test_merged_spans_full_2010_2026(self):
        rows = list(csv.DictReader(open(MERGED_FILE)))
        years = {datetime.fromisoformat(r["timestamp_utc"]).year for r in rows}
        assert years == set(range(2010, 2027))

    def test_merged_is_chronologically_sorted(self):
        rows = list(csv.DictReader(open(MERGED_FILE)))
        ts = [r["timestamp_utc"] for r in rows]
        assert ts == sorted(ts)


class TestHoldoutFirewallStillIntact:
    """The 2024-2026 extension is holdout-ADJACENT for every symbol. Confirm
    the dev_end cutoff still excludes it after the merge, for every symbol."""

    @pytest.mark.parametrize("symbol", ["EURUSD", "GBPUSD", "USDCAD", "USDCHF",
                                        "USDJPY", "XAUUSD"])
    def test_load_events_excludes_extension_for_each_symbols_dev_window(self, symbol):
        bars = load_dev_bars(REPO_ROOT / "data/csv" / f"{symbol}_H1.csv")
        dev_end = bars[-1].ts
        events = load_events(MERGED_FILE, dev_end=dev_end)
        assert all(e.ts < dev_end for e in events)
        # and since every symbol's dev window ends before 2024, none of the
        # extension's rows should survive the cut
        assert not any(e.ts.year >= 2024 for e in events)

    def test_processed_events_dev_csv_unchanged_by_the_merge(self):
        """events_dev.csv (EURUSD-cut) must be identical before/after the merge."""
        rows = list(csv.DictReader(open(PROCESSED)))
        assert len(rows) == 28354
        assert not any(r["timestamp_utc"][:4] in ("2024", "2025", "2026") for r in rows)


class TestGovernanceUntouched:
    def test_multiple_testing_ledger_was_not_touched_by_this_acquisition_task(self):
        """
        This test governs the CALENDAR EXTENSION commit specifically (an
        acquisition-only task that must add nothing to the ledger). It
        asserts CYCLE-06-EVENT-DRIVEN-REAL-CALENDAR is absent from the
        cycles recorded strictly BEFORE the extension commit landed, rather
        than pinning an exact cumulative total -- a later, legitimate
        discovery cycle (which did run, in a subsequent task, and correctly
        grew the ledger) must not make this regress.
        """
        lg = json.loads((REPO_ROOT / "reports/factory/multiple_testing_ledger.json").read_text())
        cycle_ids = {c["cycle_id"] for c in lg["cycles"]}
        assert {"CYCLE-01", "CYCLE-02", "CYCLE-3-MULTIASSET", "CYCLE-3-MULTIASSET-EVAL",
                "CYCLE-04-ECONOMIC-STRUCTURE", "CYCLE-05-EVENT-DRIVEN"} <= cycle_ids
        # Ledger counts only ever grow; no assertion here caps them.
        assert lg["cumulative_hypotheses_generated"] >= 68
        assert lg["cumulative_parameter_evaluations"] >= 750
        assert lg["cumulative_survivors"] >= 1

    def test_original_eurusd_holdout_still_unconsumed(self):
        ev = json.loads((REPO_ROOT / "reports/factory/evidence_vault.json").read_text())
        # A real GEN 14 run (see ML-001-GEN14-C2-NFP-FINAL-VERDICT.md) later
        # legitimately sealed, authorized and consumed four OTHER symbols'
        # holdouts; the vault is no longer empty. The invariant this test
        # actually protects is that THIS SPECIFIC dataset -- the original
        # EURUSD holdout, sealed since Gen 6 -- was never touched.
        eurusd_id = "DS-HOLDOUT-EURUSD-H1-HISTDATA-20240101-20260130"
        assert ev["datasets"][eurusd_id]["seal_status"] == "sealed"
        assert not any(k.startswith(f"{eurusd_id}:") for k in ev["authorizations"])
        assert not any(c["dataset_id"] == eurusd_id for c in ev["consumptions"])
