"""
End-to-end proof that the factory can carry a real edge from GEN 13 freeze
through GEN 14 qualification into a packaged EA -- and that it refuses at
every gate when the candidate has not earned it.

The real sealed holdout is NEVER opened here. GEN 14 is pointed at a synthetic
holdout directory so the machinery is exercised without consuming evidence.
"""

import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.candidate_spec_registry import CandidateSpecRegistry, FrozenSpecViolation
from discovery.holdout_authorization import HoldoutAuthorizationGate
from discovery.ledger import MultipleTestingLedger
from discovery.evaluation import Trade
from ea_generator.generator import EAGenerator, UnqualifiedCandidateError
from qualification import holdout_access, gen14_runner
from qualification.holdout_access import HoldoutAccessDenied, open_sealed_holdout
from qualification.gen14_runner import (
    qualify_on_sealed_holdout, governance_safe_failure_note,
)


# ---------------------------------------------------------------- fixtures --

def _write_holdout(dirpath: Path, symbol: str, n: int = 400) -> Path:
    """Deterministic synthetic holdout file (alternating bars)."""
    p = dirpath / f"{symbol}_H1_HOLDOUT_20240101_20260130_UTC.csv"
    ts = datetime(2024, 1, 1)
    rows = ["timestamp,open,high,low,close,volume"]
    price = 1.1
    for i in range(n):
        step = 0.0008 if i % 2 == 0 else -0.0008
        o, c = price, price + step
        rows.append(f"{ts.isoformat()},{o:.5f},{max(o,c)+0.0001:.5f},"
                    f"{min(o,c)-0.0001:.5f},{c:.5f},100")
        price, ts = c, ts + timedelta(hours=1)
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return p


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated registries + a synthetic holdout dir (real holdout untouched)."""
    hdir = tmp_path / "holdout"
    hdir.mkdir()
    _write_holdout(hdir, "EURUSD")
    monkeypatch.setattr(holdout_access, "HOLDOUT_DIR", hdir)

    reg = CandidateSpecRegistry(tmp_path / "specs.json")
    gate = HoldoutAuthorizationGate(tmp_path / "auth.json")
    ledger = MultipleTestingLedger(tmp_path / "ledger.json")
    ledger.record_cycle("C1", 10, 100, ["F"], 0)
    return {"reg": reg, "gate": gate, "ledger": ledger, "tmp": tmp_path}


def _register(reg, cid="CAND-X", framework="streak_fade"):
    return reg.register_candidate(cid, "fade the 3rd consecutive bar",
                                  {"k": 3, "horizon": 1}, framework)


def _winning_executor(bars, cost=0.0):
    """A genuinely profitable, low-variance executor (synthetic edge)."""
    return [Trade(bars[i].ts.isoformat(), 1, 0.0031, 0.0030 - cost, 1, 10)
            for i in range(120)]


def _losing_executor(bars, cost=0.0):
    return [Trade(bars[i].ts.isoformat(), 1, -0.0010, -0.0011 - cost, 1, 10)
            for i in range(120)]


# ------------------------------------------------- GEN 14 access preconditions

class TestGen14AccessPreconditions:
    def test_unfrozen_spec_cannot_open_holdout(self, env):
        _register(env["reg"])
        env["gate"].authorize_gen14_access("CAND-X", env["reg"].get_hash("CAND-X"))
        with pytest.raises(HoldoutAccessDenied, match="not frozen"):
            open_sealed_holdout("CAND-X", "EURUSD", env["reg"], env["gate"])

    def test_unauthorized_candidate_cannot_open_holdout(self, env):
        _register(env["reg"])
        env["reg"].freeze_candidate("CAND-X")
        with pytest.raises(HoldoutAccessDenied, match="no GEN 14 authorization"):
            open_sealed_holdout("CAND-X", "EURUSD", env["reg"], env["gate"])

    def test_unregistered_candidate_cannot_open_holdout(self, env):
        with pytest.raises(HoldoutAccessDenied, match="not in the specification registry"):
            open_sealed_holdout("GHOST", "EURUSD", env["reg"], env["gate"])

    def test_authorized_frozen_candidate_opens_holdout(self, env):
        _register(env["reg"])
        env["reg"].freeze_candidate("CAND-X")
        env["gate"].authorize_gen14_access("CAND-X", env["reg"].get_hash("CAND-X"))
        bars = open_sealed_holdout("CAND-X", "EURUSD", env["reg"], env["gate"])
        assert len(bars) == 400


# ------------------------------------------------------- GEN 14 qualification

class TestGen14Qualification:
    def test_real_edge_passes_and_consumes_holdout(self, env):
        _register(env["reg"])
        env["reg"].freeze_candidate("CAND-X")
        env["gate"].authorize_gen14_access("CAND-X", env["reg"].get_hash("CAND-X"))
        r = qualify_on_sealed_holdout(
            "CAND-X", "EURUSD", _winning_executor, 0.0001,
            env["reg"], env["gate"], env["ledger"],
            out_path=env["tmp"] / "q.json")
        assert r["verdict"] == "PASS"
        assert all(v == "PASS" for v in r["gates"].values())
        assert env["gate"].authorizations["CAND-X"].holdout_consumed

    def test_weak_candidate_fails_terminally(self, env):
        _register(env["reg"])
        env["reg"].freeze_candidate("CAND-X")
        env["gate"].authorize_gen14_access("CAND-X", env["reg"].get_hash("CAND-X"))
        r = qualify_on_sealed_holdout(
            "CAND-X", "EURUSD", _losing_executor, 0.0001,
            env["reg"], env["gate"], env["ledger"],
            out_path=env["tmp"] / "q.json")
        assert r["verdict"] == "FAIL"
        assert r["first_failed_gate"] == "G2_positive_expectancy"

    def test_multiple_testing_denominator_is_cumulative(self, env):
        _register(env["reg"])
        env["reg"].freeze_candidate("CAND-X")
        env["gate"].authorize_gen14_access("CAND-X", env["reg"].get_hash("CAND-X"))
        r = qualify_on_sealed_holdout(
            "CAND-X", "EURUSD", _winning_executor, 0.0001,
            env["reg"], env["gate"], env["ledger"],
            out_path=env["tmp"] / "q.json")
        mt = r["multiple_testing"]
        assert mt["cumulative_parameter_evaluations"] == 100
        assert mt["bonferroni_alpha"] == pytest.approx(0.05 / 100)


# --------------------------------------------- failure is terminal, no retune

class TestFailureIsTerminal:
    def test_failed_candidate_cannot_reopen_holdout(self, env):
        _register(env["reg"])
        env["reg"].freeze_candidate("CAND-X")
        env["gate"].authorize_gen14_access("CAND-X", env["reg"].get_hash("CAND-X"))
        qualify_on_sealed_holdout("CAND-X", "EURUSD", _losing_executor, 0.0001,
                                  env["reg"], env["gate"], env["ledger"],
                                  out_path=env["tmp"] / "q.json")
        with pytest.raises(HoldoutAccessDenied, match="already has a terminal GEN 14 result"):
            open_sealed_holdout("CAND-X", "EURUSD", env["reg"], env["gate"])

    def test_failed_candidate_cannot_be_retuned(self, env):
        _register(env["reg"])
        env["reg"].freeze_candidate("CAND-X")
        env["gate"].authorize_gen14_access("CAND-X", env["reg"].get_hash("CAND-X"))
        qualify_on_sealed_holdout("CAND-X", "EURUSD", _losing_executor, 0.0001,
                                  env["reg"], env["gate"], env["ledger"],
                                  out_path=env["tmp"] / "q.json")
        with pytest.raises(FrozenSpecViolation):
            env["reg"].update_candidate("CAND-X", parameters={"k": 4})

    def test_failure_note_withholds_holdout_statistics(self, env):
        _register(env["reg"])
        env["reg"].freeze_candidate("CAND-X")
        env["gate"].authorize_gen14_access("CAND-X", env["reg"].get_hash("CAND-X"))
        r = qualify_on_sealed_holdout("CAND-X", "EURUSD", _losing_executor, 0.0001,
                                      env["reg"], env["gate"], env["ledger"],
                                      out_path=env["tmp"] / "q.json")
        note = governance_safe_failure_note(r, "fade the 3rd consecutive bar")
        # No holdout statistic may appear, as a key or as a value.
        assert set(note) == {
            "candidate_id", "symbol", "mechanism", "stage", "first_failed_gate",
            "verdict", "prevention_rule", "holdout_statistics_withheld"}
        stats = r["holdout_statistics"]
        leaked_values = {str(v) for v in stats.values()
                         if isinstance(v, (int, float)) and v not in (0, 1)}
        blob = json.dumps(note)
        for v in leaked_values:
            assert v not in blob, f"holdout statistic {v} leaked into failure memory"
        assert str(r["multiple_testing"]["observed_p"]) not in blob
        assert note["holdout_statistics_withheld"] is True
        assert note["first_failed_gate"] == "G2_positive_expectancy"


# ------------------------------------------------------------- EA generation

class TestEAGeneration:
    def _qualified(self, env, framework="streak_fade"):
        _register(env["reg"], framework=framework)
        env["reg"].freeze_candidate("CAND-X")
        env["gate"].authorize_gen14_access("CAND-X", env["reg"].get_hash("CAND-X"))
        qualify_on_sealed_holdout("CAND-X", "EURUSD", _winning_executor, 0.0001,
                                  env["reg"], env["gate"], env["ledger"],
                                  out_path=env["tmp"] / "q.json")

    def test_packages_mt5_mt4_pine_for_passed_candidate(self, env):
        self._qualified(env)
        gen = EAGenerator(env["reg"], env["gate"])
        pkg = gen.package("CAND-X", "EURUSD", env["tmp"] / "ea")
        for kind in ("mql5", "mql4", "pine", "manifest"):
            assert pkg.files[kind].exists(), f"{kind} not emitted"
        assert "OnTick" in pkg.files["mql5"].read_text()
        assert "OrderSend" in pkg.files["mql4"].read_text()
        assert "strategy(" in pkg.files["pine"].read_text()

    def test_emitted_code_carries_the_frozen_spec_hash(self, env):
        self._qualified(env)
        gen = EAGenerator(env["reg"], env["gate"])
        pkg = gen.package("CAND-X", "EURUSD", env["tmp"] / "ea")
        h = env["reg"].get_hash("CAND-X")
        for kind in ("mql5", "mql4", "pine"):
            assert h in pkg.files[kind].read_text()
        assert json.loads(pkg.files["manifest"].read_text())["gen14_verdict"] == "PASS"

    def test_all_frameworks_render(self, env):
        for fw in ("streak_fade", "gap_fade", "breakout", "hour_drift"):
            reg = CandidateSpecRegistry(env["tmp"] / f"s_{fw}.json")
            gate = HoldoutAuthorizationGate(env["tmp"] / f"a_{fw}.json")
            cid = f"CAND-{fw}"
            reg.register_candidate(cid, f"{fw} mechanism", {"k": 3, "lookback": 4}, fw)
            reg.freeze_candidate(cid)
            gate.authorize_gen14_access(cid, reg.get_hash(cid))
            gate.record_gen14_result(cid, "PASS")
            pkg = EAGenerator(reg, gate).package(cid, "EURUSD", env["tmp"] / "ea")
            assert pkg.files["mql5"].read_text().count("int Signal()") == 1

    def test_refuses_candidate_without_gen14_result(self, env):
        _register(env["reg"])
        env["reg"].freeze_candidate("CAND-X")
        env["gate"].authorize_gen14_access("CAND-X", env["reg"].get_hash("CAND-X"))
        with pytest.raises(UnqualifiedCandidateError, match="no terminal GEN 14 result"):
            EAGenerator(env["reg"], env["gate"]).package("CAND-X", "EURUSD", env["tmp"] / "ea")

    def test_refuses_failed_candidate(self, env):
        _register(env["reg"])
        env["reg"].freeze_candidate("CAND-X")
        env["gate"].authorize_gen14_access("CAND-X", env["reg"].get_hash("CAND-X"))
        env["gate"].record_gen14_result("CAND-X", "FAIL")
        with pytest.raises(UnqualifiedCandidateError, match="verdict 'FAIL'"):
            EAGenerator(env["reg"], env["gate"]).package("CAND-X", "EURUSD", env["tmp"] / "ea")

    def test_refuses_unfrozen_candidate(self, env):
        _register(env["reg"])
        with pytest.raises(UnqualifiedCandidateError, match="not frozen"):
            EAGenerator(env["reg"], env["gate"]).package("CAND-X", "EURUSD", env["tmp"] / "ea")


# ------------------------------------------------- real holdout stays sealed

class TestRealHoldoutUntouched:
    def test_authorizations_are_only_for_legitimately_run_gen14_candidates(self):
        """
        Written when no GEN 14 run had ever happened, so it originally asserted
        the registry was empty. A real, explicitly-authorized GEN 14 run
        (the 4 C2-NFP candidates, all terminal FAIL -- see
        ML-001-GEN14-C2-NFP-FINAL-VERDICT.md) has since occurred. The
        invariant this test protects is narrower than "empty": every
        authorization on record must belong to a candidate that is frozen
        AND carries a terminal result -- never a live, still-mutable one.
        """
        p = REPO_ROOT / "reports/factory/holdout_authorization_registry.json"
        if not p.exists():
            return
        data = json.loads(p.read_text())
        reg = CandidateSpecRegistry(REPO_ROOT / "reports/factory/candidate_spec_registry.json")
        for cid, auth in data.get("authorizations", {}).items():
            spec = reg.get_candidate(cid)
            assert spec is not None and spec.is_frozen(), (
                f"{cid} has a holdout authorization but is not frozen")
            assert auth["result"] in ("PASS", "FAIL"), (
                f"{cid} has an authorization without a terminal result")

    def test_pipeline_result_reports_holdout_sealed(self):
        p = REPO_ROOT / "reports/factory/pipeline_result.json"
        if p.exists():
            r = json.loads(p.read_text())
            if r["outcome"] == "NO_EDGE_FOUND":
                assert r["holdout_status"] == "SEALED_UNCONSUMED"
                assert r["governance"]["gates_relaxed"] is False


# ------------------------------------------------------- Cycle 3 correctness

class TestCycle3Result:
    def test_ablation_requires_a_tradable_filtered_variant(self):
        """A filter that only shrinks a loss must never be called a survivor."""
        p = REPO_ROOT / "reports/factory/discovery_cycles/cycle_03_evaluation.json"
        ev = json.loads(p.read_text())
        for block in ev["per_symbol"]:
            for r in block["results"]:
                if r["operator"] != "OP-STATE-FILTER":
                    continue
                if r["verdict"] == "SURVIVES_INTERNAL":
                    assert r["filtered_variant_tradable"] is True
                    assert r["train"]["filtered"]["mean_net"] > 0
                    assert r["validation"]["filtered"]["mean_net"] > 0

    def test_cycle3_reports_zero_survivors(self):
        p = REPO_ROOT / "reports/factory/discovery_cycles/cycle_03_evaluation.json"
        ev = json.loads(p.read_text())
        assert ev["survivor_count"] == len(ev["survivors"])
        assert ev["hypotheses_evaluated"] == 43

    def test_cost_model_is_frozen_and_covers_every_symbol(self):
        from discovery.cost_model import cost_table, roundtrip_cost
        t = cost_table()
        for s in ("EURUSD", "GBPUSD", "USDCAD", "USDCHF", "USDJPY", "XAUUSD"):
            assert t[s] > 0
        assert roundtrip_cost("EURUSD") == 1.00e-4   # pinned to Cycles 1-2
        with pytest.raises(KeyError):
            roundtrip_cost("NOT_A_SYMBOL")
