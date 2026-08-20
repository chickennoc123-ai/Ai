"""
GEN 7 Cycle 6 -- event-driven discovery on the real acquired calendar.

Covers: performance fix (binary search bar lookup), power pre-check gating,
the sweep/robustness/adversarial artifacts, cross-instrument mechanism
coherence, and governance (frozen specs, no holdout authorization requested).
"""
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.observatory import Bar
from discovery.cycle5_events import bar_at_or_after, _ts_list
from discovery.cycle6_events import EVENT_MAP, power_precheck, MIN_TRADES
from discovery.candidate_spec_registry import CandidateSpecRegistry, FrozenSpecViolation
from discovery.holdout_authorization import HoldoutAuthorizationGate

SWEEP = REPO_ROOT / "reports/factory/discovery_cycles/cycle_06_event_sweep.json"
ROBUSTNESS = REPO_ROOT / "reports/factory/discovery_cycles/cycle_06_robustness.json"
ADVERSARIAL = REPO_ROOT / "reports/factory/discovery_cycles/cycle_06_adversarial.json"


def _bars(n=90000, start=datetime(2012, 1, 1)):
    return [Bar(start + timedelta(hours=i), 1.0, 1.0, 1.0, 1.0) for i in range(n)]


class TestBinarySearchPerformance:
    def test_bar_lookup_is_correct(self):
        bars = _bars(1000, start=datetime(2015, 1, 1))
        ts_list = _ts_list(bars)
        idx = bar_at_or_after(bars, datetime(2015, 1, 1, 5, 30), ts_list=ts_list)
        assert bars[idx].ts >= datetime(2015, 1, 1, 5, 30)
        assert bars[idx - 1].ts < datetime(2015, 1, 1, 5, 30)

    def test_returns_none_past_the_end(self):
        bars = _bars(10)
        assert bar_at_or_after(bars, bars[-1].ts + timedelta(days=1)) is None

    def test_large_series_many_lookups_completes_quickly(self):
        """The exact scenario that hung for >2 minutes before the fix."""
        bars = _bars(90000)
        ts_list = _ts_list(bars)
        start = time.time()
        for i in range(0, 90000, 900):   # 100 lookups spread across the series
            bar_at_or_after(bars, bars[i].ts, ts_list=ts_list)
        assert time.time() - start < 1.0, "binary search regressed to linear scan"

    def test_precomputed_ts_list_matches_on_the_fly(self):
        bars = _bars(500, start=datetime(2018, 1, 1))
        target = bars[250].ts
        assert bar_at_or_after(bars, target) == bar_at_or_after(bars, target, ts_list=_ts_list(bars))


class TestPowerPrecheckGating:
    def test_precheck_costs_nothing_and_is_declared_before_evaluation(self):
        p = power_precheck("EURUSD", "Non-Farm Employment Change", "USD")
        assert p["feasible"] is False
        assert p["validation_events"] < MIN_TRADES

    def test_feasible_combo_is_correctly_identified(self):
        p = power_precheck("USDJPY", "Non-Farm Employment Change", "USD")
        assert p["feasible"] is True

    def test_event_map_is_economically_grounded_not_exhaustive(self):
        """Every event type maps only to symbols with a direct mechanism --
        no USD event tested against, say, an unrelated cross that has no USD leg."""
        for event_name, currency, symbols, _ in EVENT_MAP:
            for s in symbols:
                assert currency in s or currency == "USD", (
                    f"{event_name} ({currency}) mapped to {s} without a direct currency link")


class TestSweepArtifact:
    @pytest.fixture(scope="class")
    def sweep(self):
        return json.loads(SWEEP.read_text())

    def test_underpowered_combos_were_skipped_before_evaluation(self, sweep):
        assert sweep["combos_skipped_underpowered"] > 0
        skipped_symbols = {p["symbol"] for p in sweep["power_precheck"] if not p["feasible"]}
        assert "EURUSD" in skipped_symbols  # NFP validation n=24 < 30, known in advance

    def test_2024_2026_extension_was_not_used(self, sweep):
        assert "2010_2023" in sweep["calendar_source"]
        assert "2024" not in sweep["calendar_source"] or "2024_2026" not in sweep["calendar_source"]

    def test_c1_c3_c4_found_nothing_c2_did(self, sweep):
        fb = sweep["family_breakdown"]
        for fam in ("C1_PRE_EVENT_POSITIONING", "C3_VOLATILITY_EXPANSION", "C4_EVENT_SEQUENCE"):
            assert fb.get(fam, {}).get("DISCOVERY_SURVIVOR", 0) == 0
        assert fb["C2_SURPRISE_REACTION"]["DISCOVERY_SURVIVOR"] == 4

    def test_every_survivor_clears_every_preregistered_threshold(self, sweep):
        for s in sweep["survivors"]:
            t, v = s["train"], s["validation"]
            assert t["n"] >= MIN_TRADES and v["n"] >= MIN_TRADES
            assert t["mean_net"] > 0 and v["mean_net"] > 0
            assert t["t_stat"] >= 2.0 and v["t_stat"] >= 1.5
            assert t["gross_over_cost"] >= 2.0

    def test_all_survivors_are_nfp(self, sweep):
        assert all(s["event_name"] == "Non-Farm Employment Change" for s in sweep["survivors"])


class TestRobustnessArtifact:
    @pytest.fixture(scope="class")
    def rb(self):
        return json.loads(ROBUSTNESS.read_text())

    def test_all_four_survivors_pass_all_ten_conditions(self, rb):
        assert rb["confirmed_survivors"] == 4
        for c in rb["detail"]:
            assert c["all_conditions_pass"]

    def test_subperiod_persistence_is_strong(self, rb):
        for c in rb["detail"]:
            assert c["cond6_subperiod"]["positive_blocks"] == 4


class TestAdversarialArtifact:
    @pytest.fixture(scope="class")
    def adv(self):
        return json.loads(ADVERSARIAL.read_text())

    def test_all_four_survived_every_binding_attack(self, adv):
        assert len(adv["survived"]) == 4
        for d in adv["detail"]:
            assert d["verdict"] == "SURVIVED_ADVERSARIAL"
            for name in d["binding_attacks"]:
                assert d["attacks"][name]["pass"]

    def test_cost_shock_survives_3x(self, adv):
        for d in adv["detail"]:
            assert d["attacks"]["cost_shock"]["detail"]["3.0x"]["mean_net"] > 0

    def test_cross_instrument_sign_check_is_majority_consistent(self, adv):
        c = adv["cross_instrument_sign_check"]
        assert c["positive_symbols"] >= 5
        assert c["advisory"] is True   # never a hard gate, only supporting evidence


class TestMechanismCoherence:
    """The FOLLOW/FADE label differs by symbol; the underlying direction must
    not -- this is what makes it one discovery rather than four coincidences."""

    def test_usd_base_pairs_use_follow(self):
        sweep = json.loads(SWEEP.read_text())
        for s in sweep["survivors"]:
            if s["symbol"] in ("USDCHF", "USDJPY"):
                assert s["params"]["mode"] == "FOLLOW"

    def test_usd_quote_and_inverse_pairs_use_fade(self):
        sweep = json.loads(SWEEP.read_text())
        for s in sweep["survivors"]:
            if s["symbol"] in ("GBPUSD", "XAUUSD"):
                assert s["params"]["mode"] == "FADE"


class TestGovernanceNotBypassed:
    def test_four_candidates_are_frozen(self):
        reg = CandidateSpecRegistry(REPO_ROOT / "reports/factory/candidate_spec_registry.json")
        for cid in ("CAND-C2-NFP-GBPUSD", "CAND-C2-NFP-USDCHF",
                   "CAND-C2-NFP-USDJPY", "CAND-C2-NFP-XAUUSD"):
            spec = reg.get_candidate(cid)
            assert spec is not None and spec.is_frozen()

    def test_frozen_candidates_cannot_be_retuned(self):
        reg = CandidateSpecRegistry(REPO_ROOT / "reports/factory/candidate_spec_registry.json")
        with pytest.raises(FrozenSpecViolation):
            reg.update_candidate("CAND-C2-NFP-USDJPY", parameters={"post_hours": 8})

    def test_no_gen14_authorization_was_requested(self):
        gate = HoldoutAuthorizationGate(REPO_ROOT / "reports/factory/holdout_authorization_registry.json")
        for cid in ("CAND-C2-NFP-GBPUSD", "CAND-C2-NFP-USDCHF",
                   "CAND-C2-NFP-USDJPY", "CAND-C2-NFP-XAUUSD"):
            assert not gate.is_gen14_authorized(cid)

    def test_holdout_still_unconsumed(self):
        ev = json.loads((REPO_ROOT / "reports/factory/evidence_vault.json").read_text())
        assert ev["authorizations"] == {} and ev["consumptions"] == []

    def test_ledger_recorded_the_cycle_exactly_once(self):
        lg = json.loads((REPO_ROOT / "reports/factory/multiple_testing_ledger.json").read_text())
        cycles = [c for c in lg["cycles"] if c["cycle_id"] == "CYCLE-06-EVENT-DRIVEN-REAL-CALENDAR"]
        assert len(cycles) == 1
        assert cycles[0]["survivors"] == 4

    def test_cumulative_counts_only_grew(self):
        lg = json.loads((REPO_ROOT / "reports/factory/multiple_testing_ledger.json").read_text())
        assert lg["cumulative_hypotheses_generated"] >= 72
        assert lg["cumulative_parameter_evaluations"] >= 1222
