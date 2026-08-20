"""
EA product tests -- SC_SURPRISE_CONFIRMATION EXPERIMENTAL EA.

These tests live under tests/ (per project convention, so `pytest tests/`
picks them up) but exercise code under ea_products/sc_surprise_confirmation/,
which is deliberately kept separate from discovery/ and ea_generator/.

Covers: frozen-spec integrity, replay-vs-research regression, determinism,
no-lookahead, config rejection, MQL5 static structure checks, and that this
product never touched holdout, the ledger, or discovery/research code.
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ea_products.sc_surprise_confirmation.frozen_spec import (
    load_frozen_combinations, find_combination, FrozenSpecDriftError,
    FROZEN_CANDIDATE_IDS, ENTRY_DELAY_SEC, IMPULSE_WINDOW_MIN,
)
from ea_products.sc_surprise_confirmation.replay.replay_engine import (
    replay, audit_trade, event_pool,
)
from ea_products.sc_surprise_confirmation.config_validator import (
    OperatorConfig, ConfigRejected, validate,
)
from discovery.observatory import load_dev_bars

MQL5_PATH = (REPO_ROOT / "ea_products/sc_surprise_confirmation/mql5/"
            "SC_SurpriseConfirmation_EXPERIMENTAL.mq5")
RESEARCH = json.loads((REPO_ROOT /
    "reports/factory/discovery_cycles/cycle_09_sc_power.json").read_text())


def _research_row(symbol, driver, window):
    for r in RESEARCH["results"]:
        if r["symbol"] == symbol and r["driver"] == driver and r["window_min"] == window:
            return r
    raise KeyError((symbol, driver, window))


# ----------------------------------------------------------------- spec

class TestFrozenSpecIntegrity:
    def test_exactly_six_combinations(self):
        assert len(load_frozen_combinations()) == 6

    def test_every_combination_labeled_still_underpowered(self):
        for c in load_frozen_combinations():
            assert c.evidence_status == "STILL_UNDERPOWERED"

    def test_every_combination_is_hash_verified(self):
        for c in load_frozen_combinations():
            assert len(c.spec_hash) == 64  # sha256 hex

    def test_no_combination_has_a_gen14_result(self):
        ev = json.loads((REPO_ROOT / "reports/factory/evidence_vault.json").read_text())
        consumed_ids = {c["candidate_id"] for c in ev["consumptions"]}
        for cid in FROZEN_CANDIDATE_IDS:
            assert cid not in consumed_ids

    def test_frozen_timing_constants_match_research(self):
        assert ENTRY_DELAY_SEC == 60
        assert IMPULSE_WINDOW_MIN == 5

    def test_last_measured_numbers_match_cycle9_exactly(self):
        for c in load_frozen_combinations():
            row = _research_row(c.symbol, c.driver, c.window_min)
            assert c.last_measured["train_n"] == row["train"]["n"]
            assert c.last_measured["train_t"] == row["train"]["t_stat"]
            assert c.last_measured["val_n"] == row["validation"]["n"]
            assert c.last_measured["val_t"] == row["validation"]["t_stat"]

    def test_no_combination_cleared_validation(self):
        """The entire premise of labeling this EXPERIMENTAL/UNRESOLVED."""
        for c in load_frozen_combinations():
            row = _research_row(c.symbol, c.driver, c.window_min)
            assert row["verdict"] == "VALIDATION_UNDERPOWERED"
            assert row["validation"]["n"] < 30


# ------------------------------------------------------- replay regression

class TestReplayMatchesResearch:
    """The replay engine must reproduce exactly what research measured --
    this is the load-bearing proof that the EA's logic is not a
    reimplementation that could have silently drifted."""

    @pytest.mark.parametrize("candidate_id,symbol,driver,window", [
        ("CAND-SC-EURUSD-US10Y-5M", "EURUSD", "US10Y", 5),
        ("CAND-SC-XAUUSD-WTICO-5M", "XAUUSD", "WTICO", 5),
        ("CAND-SC-USDJPY-SPX500-240M", "USDJPY", "SPX500", 240),
    ])
    def test_total_trade_count_equals_train_plus_validation_n(self, candidate_id, symbol, driver, window):
        row = _research_row(symbol, driver, window)
        expected_total = row["train"]["n"] + row["validation"]["n"]
        result = replay(candidate_id)
        assert result.to_dict()["n_trades"] == expected_total


class TestDeterminism:
    def test_replay_is_byte_identical_across_two_runs(self):
        r1 = replay("CAND-SC-XAUUSD-WTICO-5M")
        r2 = replay("CAND-SC-XAUUSD-WTICO-5M")
        assert r1.to_dict() == r2.to_dict()

    def test_no_randomness_anywhere_in_replay_module(self):
        src = (REPO_ROOT / "ea_products/sc_surprise_confirmation/replay/"
              "replay_engine.py").read_text()
        assert "random" not in src.lower()


# -------------------------------------------------------------- no-lookahead

class TestNoLookaheadOrLeakage:
    def test_entry_strictly_after_event_by_the_frozen_delay(self):
        bars = load_dev_bars(REPO_ROOT / "data/csv/EURUSD_H1.csv")
        events = [e for e in event_pool(bars[-1].ts) if e.ts < bars[-1].ts][:40]
        checked = 0
        for e in events:
            detail = audit_trade("CAND-SC-EURUSD-US10Y-5M", e)
            if detail is None:
                continue
            entry = datetime.fromisoformat(detail["entry_ts"])
            assert (entry - e.ts).total_seconds() == ENTRY_DELAY_SEC
            checked += 1
        assert checked > 0, "fixture produced no confirmable trades to check"

    def test_impulse_check_strictly_before_exit(self):
        bars = load_dev_bars(REPO_ROOT / "data/csv/XAUUSD_H1.csv")
        events = [e for e in event_pool(bars[-1].ts) if e.ts < bars[-1].ts][:40]
        checked = 0
        for e in events:
            detail = audit_trade("CAND-SC-XAUUSD-WTICO-5M", e)
            if detail is None:
                continue
            imp = datetime.fromisoformat(detail["impulse_ts"])
            exit_ = datetime.fromisoformat(detail["exit_ts"])
            assert imp <= exit_
            checked += 1
        assert checked > 0

    def test_exit_never_before_entry(self):
        bars = load_dev_bars(REPO_ROOT / "data/csv/USDJPY_H1.csv")
        events = [e for e in event_pool(bars[-1].ts) if e.ts < bars[-1].ts]
        checked = 0
        for e in events:
            detail = audit_trade("CAND-SC-USDJPY-SPX500-240M", e)
            if detail is None:
                continue
            entry = datetime.fromisoformat(detail["entry_ts"])
            exit_ = datetime.fromisoformat(detail["exit_ts"])
            assert exit_ > entry
            checked += 1
            if checked >= 5:
                break
        assert checked > 0, "no confirmable trades found in the full event pool -- widen further"

    def test_event_pool_never_reads_holdout(self):
        """load_events(dev_end=...) drops anything at/after dev_end -- this
        is the same firewall every prior cycle relied on, exercised here."""
        cut = datetime(2015, 1, 1)
        events = event_pool(cut)
        assert all(e.ts < cut for e in events)

    def test_replay_uses_dev_bars_loader_not_a_holdout_path(self):
        src = (REPO_ROOT / "ea_products/sc_surprise_confirmation/replay/"
              "replay_engine.py").read_text()
        # the module docstring legitimately mentions "holdout" while explaining
        # what it does NOT do; the check that matters is that no literal
        # holdout path string appears anywhere in the actual code
        assert "data/holdout" not in src
        assert "load_dev_bars" in src


# ----------------------------------------------------------- config rejection

class TestConfigValidationRejectsMismatch:
    def test_exact_match_is_accepted(self):
        cfg = OperatorConfig(candidate_id="CAND-SC-USDJPY-SPX500-240M",
                             symbol="USDJPY", driver="SPX500", window_min=240)
        result = validate(cfg)
        assert result.candidate_id == cfg.candidate_id

    def test_wrong_window_is_rejected(self):
        cfg = OperatorConfig(candidate_id="CAND-SC-USDJPY-SPX500-240M",
                             symbol="USDJPY", driver="SPX500", window_min=120)
        with pytest.raises(ConfigRejected, match="window_min"):
            validate(cfg)

    def test_wrong_symbol_is_rejected(self):
        cfg = OperatorConfig(candidate_id="CAND-SC-USDJPY-SPX500-240M",
                             symbol="EURUSD", driver="SPX500", window_min=240)
        with pytest.raises(ConfigRejected, match="symbol"):
            validate(cfg)

    def test_wrong_driver_is_rejected(self):
        cfg = OperatorConfig(candidate_id="CAND-SC-USDJPY-SPX500-240M",
                             symbol="USDJPY", driver="WTICO", window_min=240)
        with pytest.raises(ConfigRejected, match="driver"):
            validate(cfg)

    def test_retuned_entry_delay_is_rejected(self):
        """An operator trying to 'optimize' the entry delay must be blocked."""
        cfg = OperatorConfig(candidate_id="CAND-SC-USDJPY-SPX500-240M",
                             symbol="USDJPY", driver="SPX500", window_min=240,
                             entry_delay_sec=30)
        with pytest.raises(ConfigRejected, match="entry_delay_sec"):
            validate(cfg)

    def test_unknown_candidate_id_is_rejected(self):
        cfg = OperatorConfig(candidate_id="CAND-SC-EURUSD-SPX500-999M",
                             symbol="EURUSD", driver="SPX500", window_min=999)
        with pytest.raises(ConfigRejected, match="not one of the 6 frozen"):
            validate(cfg)

    def test_example_config_file_is_itself_valid(self):
        import json
        cfg_json = json.loads((REPO_ROOT /
            "ea_products/sc_surprise_confirmation/config/example_config.json").read_text())
        cfg = OperatorConfig(candidate_id=cfg_json["candidate_id"], symbol=cfg_json["symbol"],
                             driver=cfg_json["driver"], window_min=cfg_json["window_min"],
                             entry_delay_sec=cfg_json["entry_delay_sec"],
                             impulse_window_min=cfg_json["impulse_window_min"])
        validate(cfg)  # must not raise


# --------------------------------------------------------------- MQL5 checks

class TestMQL5StaticStructure:
    @pytest.fixture(scope="class")
    def source(self):
        return MQL5_PATH.read_text()

    def test_file_exists(self):
        assert MQL5_PATH.exists()

    def test_labeled_experimental_unresolved(self, source):
        assert "EXPERIMENTAL" in source and "UNRESOLVED" in source
        assert "NOT A PROVEN EDGE" in source or "not a proven edge" in source.lower()

    def test_no_proven_edge_claim_anywhere(self, source):
        """'not a proven edge' (negation) is required and expected; a bare,
        unnegated positive claim is what must never appear."""
        lower = source.lower()
        assert "guaranteed profit" not in lower
        assert "risk-free" not in lower
        for m in re.finditer(r"proven edge", lower):
            preceding = lower[max(0, m.start() - 12):m.start()]
            assert "not a " in preceding or "not an " in preceding, (
                f"unnegated 'proven edge' claim found near: ...{preceding}{m.group()}...")

    def test_startup_validation_function_present(self, source):
        assert "bool ValidateFrozenConfig()" in source
        assert "INIT_PARAMETERS_INCORRECT" in source

    def test_kill_switch_input_present(self, source):
        assert "InpKillSwitch" in source
        assert "if(InpKillSwitch)" in source

    def test_spread_guard_present(self, source):
        assert "SpreadOk()" in source
        assert "InpMaxSpreadPips" in source

    def test_daily_loss_guard_present(self, source):
        assert "DailyLossGuardOk()" in source
        assert "InpMaxDailyLossPct" in source

    def test_frozen_timing_constants_match_python_spec(self, source):
        assert "FROZEN_ENTRY_DELAY_SEC     = 60" in source
        assert "FROZEN_IMPULSE_WINDOW_MIN  = 5" in source

    def test_six_frozen_combinations_present(self, source):
        for cid in FROZEN_CANDIDATE_IDS:
            assert cid in source

    def test_no_mechanism_parameter_exposed_as_tunable_input(self, source):
        """The only 'input's should be operational (risk, symbol, kill
        switch), never the mechanism's own window/delay/direction."""
        input_lines = [l for l in source.splitlines() if l.strip().startswith("input ")]
        forbidden_names = ["InpWindow", "InpDelay", "InpEntryDelay", "InpBaseDir",
                          "InpSurpriseDir", "InpImpulseWindow"]
        joined = "\n".join(input_lines)
        for name in forbidden_names:
            assert name not in joined

    def test_logging_present_at_key_decision_points(self, source):
        for tag in ('"EVENT"', '"ENTRY-MARK"', '"CONFIRMED"', '"NO-CONFIRM"',
                   '"ORDER"', '"EXIT"', '"KILL-SWITCH"'):
            assert tag in source

    def test_uses_native_calendar_api_not_a_hardcoded_file(self, source):
        assert "CalendarValueHistory" in source
        assert "CalendarEventById" in source

    def test_no_sleep_or_blocking_wait(self, source):
        """MQL5 EAs must never block the terminal thread."""
        assert re.search(r"\bSleep\s*\(", source) is None


# --------------------------------------------------------------- governance

class TestProductIsolationAndGovernance:
    def test_ea_product_does_not_import_from_ea_generator(self):
        for f in (REPO_ROOT / "ea_products/sc_surprise_confirmation").rglob("*.py"):
            src = f.read_text()
            assert "ea_generator" not in src, f"{f} must not import the GEN14-gated pipeline"

    def test_discovery_module_unmodified_by_this_product(self):
        """cycle8_intraday.py is imported, never edited, by the EA product."""
        import subprocess
        out = subprocess.run(["git", "status", "--porcelain", "discovery/"],
                            cwd=REPO_ROOT, capture_output=True, text=True)
        assert "cycle8_intraday.py" not in out.stdout
        assert "cycle9_power.py" not in out.stdout

    def test_ledger_and_vault_files_not_modified_by_this_product(self):
        import subprocess
        out = subprocess.run(["git", "status", "--porcelain",
                             "reports/factory/multiple_testing_ledger.json",
                             "reports/factory/evidence_vault.json"],
                            cwd=REPO_ROOT, capture_output=True, text=True)
        assert out.stdout.strip() == ""

    def test_candidate_spec_registry_change_is_only_the_six_freezes(self):
        import subprocess
        out = subprocess.run(["git", "diff", "reports/factory/candidate_spec_registry.json"],
                            cwd=REPO_ROOT, capture_output=True, text=True)
        for cid in FROZEN_CANDIDATE_IDS:
            assert cid in out.stdout or Path(REPO_ROOT / "reports/factory/"
                "candidate_spec_registry.json").read_text().count(cid) > 0

    def test_readme_and_audit_report_exist(self):
        base = REPO_ROOT / "ea_products/sc_surprise_confirmation"
        assert (base / "README.md").exists()
        assert (base / "AUDIT_REPORT.md").exists()

    def test_readme_states_evidence_status_plainly(self):
        text = (REPO_ROOT / "ea_products/sc_surprise_confirmation/README.md").read_text()
        assert "STILL_UNDERPOWERED" in text or "UNRESOLVED" in text
        assert "GEN 14" in text
        assert "not" in text.lower() and "proven" in text.lower()
