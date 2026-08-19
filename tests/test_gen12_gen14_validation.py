"""
Tests for GEN 12 (adversarial destruction), GEN 13 (replication freeze
protocol), GEN 14 (final qualification).

Strategy: plant synthetic "edges" with KNOWN properties and assert the
machinery reaches the correct verdict -- a fragile/fake edge must be
destroyed, a robust one must survive. This validates the gates without
spending real research budget or touching the sealed holdout.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.observatory import Bar  # noqa: E402
from discovery.evaluation import Trade, ROUNDTRIP_COST, _stats  # noqa: E402
from discovery.adversarial import (  # noqa: E402
    AdversarialDestroyer, SEED, BOOTSTRAP_MIN_POSITIVE_FRACTION, _bootstrap,
)
from discovery.replication import (  # noqa: E402
    FreezeViolation, FrozenCandidate, QUALIFICATION_GATES, freeze_candidate, qualify,
)


def _bars(n=4000):
    bars, price, ts = [], 1.1000, datetime(2015, 1, 5, 0, 0)
    for i in range(n):
        step = 0.0008 if (i % 3) else -0.0009
        o, c = price, price + step
        bars.append(Bar(ts, o, max(o, c) + 1e-4, min(o, c) - 1e-4, c))
        price, ts = c, ts + timedelta(hours=1)
        if not 0.5 < price < 2.0:
            price = 1.1
    return bars


def _mk_trades(bars, per_trade_net, count, sign_pattern=None):
    """Executor factory: emits `count` trades each netting per_trade_net."""
    def executor(bs, cost=ROUNDTRIP_COST, delay=0, **kw):
        out = []
        step = max(len(bs) // max(count, 1), 1)
        for i in range(0, min(len(bs), count * step), step):
            gross = per_trade_net + ROUNDTRIP_COST
            net = gross - cost
            if delay:
                net -= 0.00005 * delay          # delay erodes the edge a little
            if sign_pattern:
                net *= sign_pattern(i // step)
            out.append(Trade(bs[i].ts.isoformat(), 1, round(gross, 7),
                             round(net, 7), 1, bs[i].ts.hour))
        return out
    return executor


class TestAdversarialKillsFakeEdges:
    def test_cost_marginal_edge_dies_to_cost_shock(self):
        # nets +0.3 pips: dies as soon as cost is doubled
        ex = _mk_trades(None, 0.00003, 400)
        res = AdversarialDestroyer("FAKE-COST-MARGINAL", ex, _bars()).run_all()
        cost = next(a for a in res["attacks"] if a["attack"] == "COST_SHOCK")
        assert not cost["survived"]
        assert res["verdict"] == "DESTROYED"
        assert "COST_SHOCK" in res["fatal_failures"]

    def test_edge_confined_to_one_subperiod_dies(self):
        # Profitable ONLY before a fixed calendar date, so the confinement is
        # absolute -- slicing the sample cannot recreate it inside each block.
        all_bars = _bars()
        cutoff = all_bars[len(all_bars) // 4].ts

        def ex(bs, cost=ROUNDTRIP_COST, delay=0, **kw):
            out = []
            for i in range(0, len(bs) - 1, 10):
                good = bs[i].ts < cutoff
                gross = (0.0010 if good else -0.0002) + ROUNDTRIP_COST
                out.append(Trade(bs[i].ts.isoformat(), 1, gross,
                                 round(gross - cost, 7), 1, bs[i].ts.hour))
            return out
        res = AdversarialDestroyer("FAKE-ONE-PERIOD", ex, all_bars).run_all()
        sub = next(a for a in res["attacks"] if a["attack"] == "SUBPERIOD")
        assert not sub["survived"]
        assert sub["detail"]["positive_blocks"] < 3
        assert res["verdict"] == "DESTROYED"

    def test_fragile_parameter_dies_to_perturbation(self):
        def rebuild(params):
            k = params["k"]
            good = (k == 3)                       # ONLY k=3 works: classic overfit
            return _mk_trades(None, 0.0005 if good else -0.0004, 300)
        res = AdversarialDestroyer(
            "FAKE-FRAGILE", rebuild({"k": 3}), _bars(),
            int_params={"k": 3}, param_rebuild=rebuild).run_all()
        pp = next(a for a in res["attacks"] if a["attack"] == "PARAMETER_PERTURB")
        assert not pp["survived"]
        assert res["verdict"] == "DESTROYED"

    def test_high_variance_noise_dies_to_bootstrap(self):
        # alternating +/- with tiny positive mean: bootstrap CI spans zero
        ex = _mk_trades(None, 0.002, 60, sign_pattern=lambda i: 1 if i % 2 == 0 else -0.97)
        res = AdversarialDestroyer("FAKE-NOISE", ex, _bars()).run_all()
        bs = next(a for a in res["attacks"] if a["attack"] == "BOOTSTRAP")
        assert bs["detail"]["positive_fraction"] < BOOTSTRAP_MIN_POSITIVE_FRACTION
        assert not bs["survived"]


class TestAdversarialPassesRobustEdge:
    def test_robust_edge_survives_all_fatal_attacks(self):
        # +1.5 pips/trade, uniform across time, no parameters
        ex = _mk_trades(None, 0.00015, 800)
        res = AdversarialDestroyer("ROBUST", ex, _bars()).run_all()
        assert res["fatal_failures"] == [], f"unexpected failures: {res['fatal_failures']}"
        assert res["verdict"] == "SURVIVED_ADVERSARIAL"

    def test_symbol_shift_is_advisory_not_fatal(self):
        ex = _mk_trades(None, 0.00015, 800)
        res = AdversarialDestroyer("ROBUST", ex, _bars()).run_all()
        sym = next(a for a in res["attacks"] if a["attack"] == "SYMBOL_SHIFT")
        assert sym["fatal"] is False


class TestDeterminism:
    def test_bootstrap_is_seeded_and_reproducible(self):
        trades = [Trade(f"t{i}", 1, 0.0002, 0.0001 * (1 if i % 3 else -2), 1, 12)
                  for i in range(200)]
        assert _bootstrap(trades) == _bootstrap(trades)

    def test_full_run_reproducible(self):
        ex = _mk_trades(None, 0.00015, 500)
        a = AdversarialDestroyer("R", ex, _bars()).run_all()
        b = AdversarialDestroyer("R", ex, _bars()).run_all()
        assert a == b
        assert a["seed"] == SEED


class TestFreezeProtocol:
    def test_checksum_stable_for_same_spec(self):
        a = freeze_candidate("C1", {"k": 3, "horizon": 4})
        b = FrozenCandidate("C1", {"horizon": 4, "k": 3}, a.frozen_at)
        assert a.spec_checksum == b.spec_checksum   # key order must not matter

    def test_mutating_spec_after_freeze_is_detected(self):
        f = freeze_candidate("C1", {"k": 3})
        f.spec["k"] = 4                              # post-freeze tampering
        with pytest.raises(FreezeViolation):
            f.verify_unchanged()

    def test_unchanged_spec_verifies(self):
        f = freeze_candidate("C1", {"k": 3})
        f.verify_unchanged()


class TestQualification:
    def test_all_gates_pass_yields_provisionally_proven(self):
        rep = qualify("C1", {g: "PASS" for g in QUALIFICATION_GATES})
        assert rep.edge_status == "PROVISIONALLY_PROVEN"
        assert rep.blocking_gates == []

    def test_missing_gate_blocks(self):
        gates = {g: "PASS" for g in QUALIFICATION_GATES}
        del gates["INDEPENDENT_REPLICATION"]
        rep = qualify("C1", gates)
        assert rep.edge_status == "NOT_PROVEN"
        assert "INDEPENDENT_REPLICATION" in rep.blocking_gates
        assert rep.gates["INDEPENDENT_REPLICATION"] == "NOT_RUN"

    def test_single_failed_gate_blocks(self):
        gates = {g: "PASS" for g in QUALIFICATION_GATES}
        gates["COST"] = "FAIL"
        rep = qualify("C1", gates)
        assert rep.edge_status == "NOT_PROVEN"
        assert rep.blocking_gates == ["COST"]

    def test_multiple_testing_context_recorded(self):
        rep = qualify("C1", {g: "PASS" for g in QUALIFICATION_GATES},
                      hypotheses_tested_in_program=11)
        assert any("11 hypotheses" in n for n in rep.notes)


class TestHoldoutRemainsUnconsumed:
    def test_sealed_holdout_not_consumed_by_this_test_run(self):
        from core.factory.evidence_vault import EvidenceVault
        from discovery.replication import SEALED_HOLDOUT_ID
        vault = EvidenceVault()
        meta = vault.datasets[SEALED_HOLDOUT_ID]
        assert meta.seal_status.value == "sealed", (
            "holdout must remain SEALED -- no test may consume it")
