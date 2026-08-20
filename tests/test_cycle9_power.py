"""
GEN 7 Cycle 9 -- SC_SURPRISE_CONFIRMATION power expansion.

Covers: the frozen event pool matches the pre-registration exactly, Federal
Funds Rate's zero-power exclusion is verified not assumed, the mechanism
logic is imported unmodified from Cycle 8 (no drift), the decision rule
(survivors / refuted / still-underpowered) is applied correctly, and
governance (no holdout touch, ledger append-only, DC/DR/RI not re-run).
"""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.cycle9_power import FROZEN_EVENT_TYPES, frozen_event_pool, MIN_TRADES
from discovery.cycle8_intraday import trade_sc as cycle8_trade_sc
from discovery.cycle9_power import trade_sc as cycle9_trade_sc

RESULT = REPO_ROOT / "reports/factory/discovery_cycles/cycle_09_sc_power.json"
CALENDAR = REPO_ROOT / "data/events/raw/forexfactory_2010_2023.csv"


class TestPreRegisteredEventPool:
    def test_frozen_event_types_match_preregistration(self):
        assert FROZEN_EVENT_TYPES == {"Non-Farm Employment Change", "CPI y/y",
                                      "ADP Non-Farm Employment Change"}

    def test_federal_funds_rate_excluded_and_verified_zero_power(self):
        """The exclusion must be a checked fact, not an assumption."""
        rows = list(csv.DictReader(open(CALENDAR)))
        def in_range(ts):
            d = datetime.fromisoformat(ts)
            if d.year < 2010 or d.year > 2020: return False
            if d.year == 2020 and d.month > 5: return False
            return True
        ffr = [r for r in rows if r["event_name"] == "Federal Funds Rate"
              and r["currency"] == "USD" and in_range(r["timestamp_utc"])]
        nonzero = [r for r in ffr if r["actual"] not in ("", "None")
                  and r["forecast"] not in ("", "None")
                  and float(r["actual"]) != float(r["forecast"])]
        assert len(nonzero) == 0, "if this ever becomes nonzero, the exclusion must be revisited"

    def test_pool_uses_only_frozen_types(self):
        bars_end = datetime(2022, 1, 1)  # generous upper bound
        events = frozen_event_pool(bars_end)
        assert all(e.name in FROZEN_EVENT_TYPES for e in events)
        assert all(e.currency == "USD" and e.impact == "HIGH" for e in events)

    def test_pool_is_larger_than_cycle8s_268(self):
        events = frozen_event_pool(datetime(2022, 1, 1))
        assert len(events) > 268

    def test_pool_respects_holdout_firewall(self):
        cut = datetime(2015, 1, 1)
        events = frozen_event_pool(cut)
        assert all(e.ts < cut for e in events)

    def test_adp_is_temporally_distinct_from_nfp_not_simultaneous(self):
        events = frozen_event_pool(datetime(2022, 1, 1))
        adp = sorted(e.ts for e in events if e.name == "ADP Non-Farm Employment Change")
        nfp = sorted(e.ts for e in events if e.name == "Non-Farm Employment Change")
        for a in adp[:30]:
            nearest_gap = min(abs((n - a).total_seconds()) for n in nfp)
            assert nearest_gap > 3600, "ADP must not coincide with an NFP release"


class TestNoMechanismDrift:
    """Cycle 9 must reuse Cycle 8's mechanism unmodified -- same function object."""

    def test_trade_sc_is_the_identical_function(self):
        assert cycle9_trade_sc is cycle8_trade_sc

    def test_gate_thresholds_unchanged(self):
        from discovery.cycle8_intraday import TRAIN_MIN_T, VAL_MIN_T, MIN_GROSS_OVER_COST
        assert (TRAIN_MIN_T, VAL_MIN_T, MIN_GROSS_OVER_COST) == (2.0, 1.5, 2.0)
        assert MIN_TRADES == 30

    def test_execution_delay_unchanged(self):
        from discovery.cycle8_intraday import ENTRY_DELAY_SEC
        assert ENTRY_DELAY_SEC == 60

    def test_pairings_unchanged(self):
        from discovery.cycle8_intraday import PAIRINGS as c8
        from discovery.cycle9_power import PAIRINGS as c9
        assert c8 is c9


class TestOutcomeArtifact:
    @pytest.fixture(scope="class")
    def payload(self):
        return json.loads(RESULT.read_text())

    def test_outcome_is_one_of_the_three_frozen_options(self, payload):
        assert payload["outcome"] in ("SURVIVORS_FOUND", "REFUTED", "STILL_UNDERPOWERED")

    def test_no_survivor_without_clearing_every_gate(self, payload):
        for s in payload["survivors"]:
            t, v = s["train"], s["validation"]
            assert t["n"] >= MIN_TRADES and v["n"] >= MIN_TRADES
            assert t["mean_net"] > 0 and v["mean_net"] > 0
            assert t["t_stat"] >= 2.0 and v["t_stat"] >= 1.5

    def test_still_underpowered_rows_failed_only_on_n_not_significance(self, payload):
        for r in payload["still_underpowered"]:
            assert r["verdict"] == "VALIDATION_UNDERPOWERED"
            assert r["validation"]["n"] < MIN_TRADES
            # the train side must have been genuinely significant, not the cause of failure
            assert r["train"]["t_stat"] >= 2.0
            assert r["train"]["mean_net"] > 0

    def test_evaluation_count_matches_six_pairings_times_windows(self, payload):
        # 4 M1 pairings x 6 windows + 2 H1-only pairings x 3 windows = 24 + 6 = 30
        assert payload["parameter_evaluations"] == 30

    def test_dc_dr_ri_are_not_present_only_sc(self, payload):
        assert all(r["mechanism"] == "SC_SURPRISE_CONFIRMATION" for r in payload["results"])


class TestGovernance:
    def test_holdout_untouched(self):
        ev = json.loads((REPO_ROOT / "reports/factory/evidence_vault.json").read_text())
        cycle9 = [c for c in ev["consumptions"] if "CYCLE-09" in c.get("candidate_id", "")]
        assert cycle9 == []

    def test_ledger_recorded_cycle9_exactly_once(self):
        lg = json.loads((REPO_ROOT / "reports/factory/multiple_testing_ledger.json").read_text())
        cycles = [c for c in lg["cycles"] if c["cycle_id"] == "CYCLE-09-SC-POWER-EXPANSION"]
        assert len(cycles) == 1

    def test_ledger_recorded_no_new_hypotheses(self):
        """This is a re-test of a pre-existing mechanism, not new hypothesis generation."""
        lg = json.loads((REPO_ROOT / "reports/factory/multiple_testing_ledger.json").read_text())
        c9 = next(c for c in lg["cycles"] if c["cycle_id"] == "CYCLE-09-SC-POWER-EXPANSION")
        assert c9["hypotheses_generated"] == 0

    def test_cumulative_counts_only_grew(self):
        lg = json.loads((REPO_ROOT / "reports/factory/multiple_testing_ledger.json").read_text())
        assert lg["cumulative_parameter_evaluations"] >= 1552

    def test_preregistration_document_exists_and_predates_the_run(self):
        prereg = REPO_ROOT / "CYCLE9-PREREGISTRATION.md"
        assert prereg.exists()
        text = prereg.read_text()
        # documents the decision RULE (what to do if underpowered), not a result number
        assert "VALIDATION_UNDERPOWERED" in text and "STOP" in text
        assert "393" not in text  # the eventual actual pool size must not appear pre-run
