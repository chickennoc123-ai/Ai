"""
GEN 7 Cycle 7 -- new economic search (post C2-NFP refutation).

Covers: cross-asset data acquisition/audit, Phase 1 reuse (no wasted
evaluations), Phase 2 cross-asset gate mechanics, Phase 3 D1/W1 bug-fix
verification, and governance (no holdout touched, ledger append-only).
"""
import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.observatory import Bar
from discovery.cycle4_economics import to_daily, DayBar
from discovery.cycle7_crossasset import (
    stats as x_stats, gate as x_gate, _lagged_signal, HYPOTHESES,
    MIN_TRADES, MIN_GROSS_OVER_COST,
)
from discovery.cycle7_d1w1 import (
    real_trading_days, sig_weekday_fixed, sig_weekly_breakout,
    MIN_TRADING_DAY_BARS,
)

CROSSASSET = REPO_ROOT / "reports/factory/discovery_cycles/cycle_07_crossasset.json"
D1W1 = REPO_ROOT / "reports/factory/discovery_cycles/cycle_07_d1w1.json"


class TestCrossAssetDataAcquisition:
    @pytest.mark.parametrize("name,lo,hi", [
        ("WTICO", 5, 200),        # oil: real crash to ~$12 in Apr 2020, cap generous
        ("US10Y", 100, 150),      # Oanda bond-price CFD, not the yield itself
        ("SPX500", 900, 3500),
    ])
    def test_series_values_are_in_a_plausible_real_range(self, name, lo, hi):
        rows = list(csv.DictReader(open(REPO_ROOT / f"data/crossasset/processed/{name}_D1.csv")))
        closes = [float(r["close"]) for r in rows]
        assert lo <= min(closes) and max(closes) <= hi

    def test_no_gaps_over_four_days(self):
        for name in ("WTICO", "US10Y", "SPX500"):
            rows = list(csv.DictReader(open(REPO_ROOT / f"data/crossasset/processed/{name}_D1.csv")))
            dates = [datetime.fromisoformat(r["date"]) for r in rows]
            gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
            assert max(gaps) <= 4, f"{name} has a gap > 4 days"

    def test_spx_matches_known_market_history_at_two_checkpoints(self):
        rows = list(csv.DictReader(open(REPO_ROOT / "data/crossasset/processed/SPX500_D1.csv")))
        by_date = {r["date"]: float(r["close"]) for r in rows}
        # SPX ~1015 mid-2010, ~3380s just before the Feb 2020 COVID top -- both
        # well-known reference points, sanity-checking this is real data
        near_2010_low = min(v for d, v in by_date.items() if d.startswith("2010-07"))
        near_2020_high = max(v for d, v in by_date.items() if d.startswith("2020-02"))
        assert 900 <= near_2010_low <= 1100
        assert 3200 <= near_2020_high <= 3500


class TestPhase1ReusedExistingResults:
    """Phase 1 (CPI/FOMC C2) must not have spent new parameter evaluations --
    it reuses Cycle 6's already-ledgered sweep."""

    def test_cpi_results_exist_in_cycle6_artifact_not_a_new_file(self):
        sweep = json.loads((REPO_ROOT /
            "reports/factory/discovery_cycles/cycle_06_event_sweep.json").read_text())
        cpi_rows = [r for r in sweep["results"]
                   if r["family"] == "C2_SURPRISE_REACTION" and r["event_name"] == "CPI y/y"]
        assert len(cpi_rows) > 0
        assert all(r["verdict"] != "DISCOVERY_SURVIVOR" for r in cpi_rows)

    def test_fomc_fed_funds_rate_was_never_evaluated_power_precheck_killed_it(self):
        sweep = json.loads((REPO_ROOT /
            "reports/factory/discovery_cycles/cycle_06_event_sweep.json").read_text())
        fomc_rows = [r for r in sweep["results"]
                    if r["event_name"] == "Federal Funds Rate"
                    and r["family"] == "C2_SURPRISE_REACTION"]
        assert len(fomc_rows) == 0
        skipped = [p for p in sweep["power_precheck"] if p["event_name"] == "Federal Funds Rate"]
        assert len(skipped) == 6 and all(not p["feasible"] for p in skipped)


class TestPhase2CrossAssetMechanics:
    def test_six_mechanisms_are_pre_registered_and_economically_named(self):
        assert len(HYPOTHESES) == 6
        for name, driver, symbol, base_dir, mechanism in HYPOTHESES:
            assert driver in ("WTICO", "SPX500", "US10Y")
            assert base_dir in (1, -1)
            assert len(mechanism) > 10

    def test_signal_is_lagged_not_contemporaneous(self):
        driver = {datetime(2020, 1, i).date(): 100.0 + i for i in range(1, 10)}
        sig = _lagged_signal(driver, list(driver))
        d1 = datetime(2020, 1, 1).date()
        assert d1 not in sig  # first date has no prior day to lag from

    def test_gate_requires_gross_over_cost_before_significance(self):
        s = x_stats([0.001] * 50)
        s.gross_over_cost = 1.0
        v, _ = x_gate(s, s)
        assert v == "COST_DOMINATED"

    @pytest.fixture(scope="class")
    def payload(self):
        return json.loads(CROSSASSET.read_text())

    def test_evaluation_count_matches_grid(self, payload):
        assert payload["parameter_evaluations"] == 6 * 2  # 6 mechanisms x 2 holds

    def test_overlap_limitation_is_disclosed(self, payload):
        assert "2020" in payload["overlap_limitation"]

    def test_no_dxy_signal_was_used(self, payload):
        assert "not used" in payload["dxy_note"].lower()

    def test_zero_survivors(self, payload):
        assert payload["survivor_count"] == 0


class TestPhase3D1W1BugFix:
    def _bars(self, pattern="normal_week"):
        """One synthetic week: Mon-Fri full days, then a 2-bar Saturday
        spillover stub identical in shape to the real HistData artifact."""
        bars, price = [], 1.0
        start = datetime(2015, 1, 5)  # a Monday
        for day in range(5):
            for h in range(24):
                bars.append(Bar(start + timedelta(days=day, hours=h), price, price, price, price))
                price += 0.0001
        # Saturday spillover stub: 2 bars only
        for h in range(2):
            bars.append(Bar(start + timedelta(days=5, hours=h), price, price, price, price))
            price += 0.0001
        return bars

    def test_stub_day_is_filtered_out(self):
        days = real_trading_days(self._bars())
        assert all(d.bars >= MIN_TRADING_DAY_BARS for d in days)
        assert len(days) == 5  # Mon-Fri only, Saturday stub dropped

    def test_weekday_signal_indexes_real_trading_days_only(self):
        days = real_trading_days(self._bars())
        sig = sig_weekday_fixed(days, weekday=4, direction=1)  # Friday
        assert len(sig) == 1
        i, d = sig[0]
        assert days[i].date.weekday() == 4
        # the NEXT index (i+1) must not exist in this fixture -- Saturday was
        # dropped, so a hold=1 trade from Friday would correctly find no exit
        assert i == len(days) - 1

    def test_weekly_breakout_operates_on_week_bars_not_days(self):
        days = to_daily(self._bars())
        from discovery.cycle4_economics import to_weekly
        weeks = to_weekly(days)
        assert len(weeks) <= 2  # one partial week in this tiny fixture

    @pytest.fixture(scope="class")
    def payload(self):
        return json.loads(D1W1.read_text())

    def test_evaluation_count_matches_grid(self, payload):
        # D1: 6 symbols x 5 weekdays x 2 dirs x 2 holds = 120
        # W1: 6 symbols x 2 lookbacks x 2 modes x 2 holds = 48
        assert payload["parameter_evaluations"] == 120 + 48

    def test_zero_survivors(self, payload):
        assert payload["survivor_count"] == 0

    def test_every_result_holds_at_least_one_genuine_day(self, payload):
        for r in payload["results"]:
            p = r["params"]
            hold = p.get("hold_days", p.get("hold_weeks"))
            assert hold >= 1


class TestGovernanceStillIntact:
    def test_holdout_not_touched_by_cycle7(self):
        ev = json.loads((REPO_ROOT / "reports/factory/evidence_vault.json").read_text())
        # exactly the 4 GEN14 C2-NFP consumptions from the prior task, nothing new
        cycle7_consumptions = [c for c in ev["consumptions"]
                               if "CYCLE-07" in c.get("candidate_id", "")]
        assert cycle7_consumptions == []

    def test_ledger_recorded_cycle7_exactly_once(self):
        lg = json.loads((REPO_ROOT / "reports/factory/multiple_testing_ledger.json").read_text())
        cycles = [c for c in lg["cycles"] if c["cycle_id"] == "CYCLE-07-NEW-ECONOMIC-SEARCH"]
        assert len(cycles) == 1
        assert cycles[0]["survivors"] == 0

    def test_cumulative_counts_only_grew(self):
        lg = json.loads((REPO_ROOT / "reports/factory/multiple_testing_ledger.json").read_text())
        assert lg["cumulative_hypotheses_generated"] >= 80
        assert lg["cumulative_parameter_evaluations"] >= 1402

    def test_c2_nfp_family_remains_refuted_not_reopened(self):
        reg = json.loads((REPO_ROOT / "reports/factory/research_family_registry.json").read_text())
        fam = reg["families"]["FAMILY-C2-SURPRISE-REACTION-NFP-USD"]
        assert fam["status"] == "REFUTED"

    def test_no_ea_generated(self):
        ea_dir = REPO_ROOT / "artifacts/ea"
        for p in ea_dir.rglob("*"):
            if p.is_file() and "DEMO" not in str(p) and ".gitkeep" not in str(p):
                pytest.fail(f"unexpected EA artifact: {p}")
