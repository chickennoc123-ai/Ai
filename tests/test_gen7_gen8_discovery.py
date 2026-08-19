"""
Tests for GEN 8 (Market Observatory) and GEN 7 (Discovery Engine).

Covers: holdout firewall, determinism, significance gating, refuted-family
firewall, batch novelty, budget, evidence lineage, economic pre-filter.
"""

import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery._guards import HoldoutFirewallViolation, guard_path  # noqa: E402
from discovery.observatory import (  # noqa: E402
    Bar, MarketObservatory, SIGNIFICANCE_T, load_dev_bars,
)
from discovery.engine import (  # noqa: E402
    ASSUMED_ROUNDTRIP_COST, MAX_HYPOTHESES_PER_CYCLE, DiscoveryEngine, _hyp_id,
)


# ---------------------------------------------------------------------------
# Holdout firewall
# ---------------------------------------------------------------------------

class TestHoldoutFirewall:
    def test_holdout_path_is_blocked(self):
        with pytest.raises(HoldoutFirewallViolation):
            guard_path(REPO_ROOT / "data" / "holdout" / "EURUSD_H1_HOLDOUT_20240101_20260130_UTC.csv")

    def test_dev_path_is_allowed(self):
        assert guard_path(REPO_ROOT / "data" / "csv" / "EURUSD_H1.csv")

    def test_loader_refuses_holdout(self):
        with pytest.raises(HoldoutFirewallViolation):
            load_dev_bars(REPO_ROOT / "data" / "holdout" / "EURUSD_H1_HOLDOUT_20240101_20260130_UTC.csv")


# ---------------------------------------------------------------------------
# Observatory on synthetic series with KNOWN structure
# ---------------------------------------------------------------------------

def _synthetic_bars(n: int = 3000, alternating: bool = True):
    """Deterministic price path; alternating=True builds strong negative AC(1)."""
    bars = []
    price = 1.1000
    ts = datetime(2015, 1, 5, 0, 0)
    for i in range(n):
        step = 0.0008 if (i % 2 == 0) else -0.0008  # alternate up/down
        if not alternating:
            step = 0.0008 if (i % 7) < 4 else -0.0006  # mild drift pattern
        o = price
        c = price + step
        h, l = max(o, c) + 0.0001, min(o, c) - 0.0001
        bars.append(Bar(ts, o, h, l, c))
        price = c
        ts += timedelta(hours=1)
        if price < 0.5:
            price = 1.1
    return bars


class TestObservatory:
    def test_alternating_series_yields_negative_ac1(self):
        obs = MarketObservatory(_synthetic_bars(alternating=True))
        obs.obs_return_autocorrelation()
        ac1 = next(o for o in obs.observations if o.obs_id == "OBS-AC-RET-L1")
        assert ac1.effect_size < -0.9
        assert ac1.significant

    def test_significance_threshold_applied(self):
        obs = MarketObservatory(_synthetic_bars(alternating=False))
        obs.obs_return_autocorrelation()
        for o in obs.observations:
            assert o.significant == (abs(o.t_stat) >= SIGNIFICANCE_T)

    def test_observation_window_is_80_percent(self):
        bars = _synthetic_bars(1000)
        obs = MarketObservatory(bars)
        assert len(obs.window) == 800
        assert obs.reserved_bars == 200

    def test_run_all_is_deterministic(self):
        a = MarketObservatory(_synthetic_bars()); a.run_all()
        b = MarketObservatory(_synthetic_bars()); b.run_all()
        assert [o.to_dict() for o in a.observations] == [o.to_dict() for o in b.observations]

    def test_every_observation_carries_window_and_sample(self):
        obs = MarketObservatory(_synthetic_bars())
        obs.run_all()
        for o in obs.observations:
            assert o.window_start and o.window_end
            assert o.sample_size > 0


# ---------------------------------------------------------------------------
# Discovery engine
# ---------------------------------------------------------------------------

def _fake_payload():
    """Observation payload with the ids the operators consume."""
    def mk(obs_id, family, effect, t, n, details=None):
        return {"obs_id": obs_id, "family": family, "description": obs_id,
                "mechanism_hint": "", "effect_size": effect, "t_stat": t,
                "sample_size": n, "significant": abs(t) >= 3.5,
                "details": details or {}, "window_start": "w0", "window_end": "w1"}
    return {
        "observation_window": {"start": "w0", "end": "w1", "bars": 1000},
        "observations": [
            mk("OBS-TRENDPERSIST-K2", "TREND", -0.043, -8.96, 10883),
            mk("OBS-TRENDPERSIST-K3", "TREND", -0.052, -7.35, 4989),
            mk("OBS-TRENDPERSIST-K4", "TREND", -0.055, -5.20, 2242),
            mk("OBS-WKND-GAPFILL", "GAP", 0.376, 22.37, 386),
            mk("OBS-NR7-EXPAND", "RANGE", -0.289, -49.63, 7825),
            mk("OBS-VOLCLUST-L1", "VOLATILITY", 0.249, 53.49, 46078),
            mk("OBS-SESSVOL-NY_LATE", "SESSION", 0.384, 37.23, 9643),
            mk("OBS-HOUR-04", "SESSION", -0.0001, -6.98, 1814),
            mk("OBS-HOUR-06", "SESSION", 0.00008, 4.49, 1920),
            # An insignificant one that must never seed anything:
            mk("OBS-AC-RET-L1", "AUTOCORRELATION", 0.002, 0.48, 46078),
        ],
    }


class TestDiscoveryEngine:
    def test_generates_hypotheses_with_full_lineage(self):
        eng = DiscoveryEngine(_fake_payload())
        queue = eng.run()
        assert queue, "engine produced nothing from significant observations"
        for h in queue:
            assert h.evidence_obs_ids
            assert h.operator
            assert h.mechanism
            assert h.testable_prediction
            assert h.priority > 0

    def test_insignificant_observations_never_seed(self):
        eng = DiscoveryEngine(_fake_payload())
        queue = eng.run()
        for h in queue:
            assert "OBS-AC-RET-L1" not in h.evidence_obs_ids

    def test_refuted_family_firewall_blocks_rsi_mean_reversion(self):
        refuted = ["mechanism: rsi_14 < 30 => rsi_14 crosses back above 30 from below",
                   "rsi oversold mean-reversion, EURUSD H1"]
        eng = DiscoveryEngine(_fake_payload(), refuted)
        # Inject a hypothesis that IS the refuted family
        eng._emit("OP-TEST", ["OBS-TRENDPERSIST-K2"],
                  mechanism="rsi oversold mean-reversion, EURUSD H1",
                  what="w", why="y", prediction="p", test={}, gross_effect=0.0005)
        before = len(eng.candidates)
        eng.filter_refuted_families()
        blocked = [r for r in eng.rejections if "refuted-family" in r.get("reason", "")]
        assert blocked, "refuted RSI mechanism was not blocked"
        assert len(eng.candidates) == before - 1

    def test_budget_cap_enforced(self):
        eng = DiscoveryEngine(_fake_payload())
        for i in range(30):
            eng._emit("OP-TEST", ["OBS-TRENDPERSIST-K2"],
                      mechanism=f"unique synthetic mechanism variant number {i} "
                                f"with token{i} and flavor{i*7}",
                      what="w", why="y", prediction="p", test={},
                      gross_effect=0.0005 + i * 1e-6)
        eng.apply_budget()
        assert len(eng.candidates) <= MAX_HYPOTHESES_PER_CYCLE

    def test_economic_prefilter_drops_hopeless_effects(self):
        eng = DiscoveryEngine(_fake_payload())
        eng._emit("OP-TEST", ["OBS-TRENDPERSIST-K2"],
                  mechanism="hopeless tiny effect mechanism",
                  what="w", why="y", prediction="p", test={},
                  gross_effect=ASSUMED_ROUNDTRIP_COST * 0.1)
        assert all(h.mechanism != "hopeless tiny effect mechanism" for h in eng.candidates)
        assert any("economic pre-filter" in r["reason"] for r in eng.rejections)

    def test_deterministic_ids_and_output(self):
        a = DiscoveryEngine(_fake_payload()); qa = a.run()
        b = DiscoveryEngine(_fake_payload()); qb = b.run()
        assert [h.to_dict() for h in qa] == [h.to_dict() for h in qb]
        assert _hyp_id("x") == _hyp_id("x")


# ---------------------------------------------------------------------------
# Real registry artifacts (integration)
# ---------------------------------------------------------------------------

class TestRealArtifacts:
    def test_real_observation_registry_exists_and_windowed(self):
        reg = json.loads((REPO_ROOT / "reports/factory/market_observations.json").read_text())
        assert reg["significance_threshold_t"] == SIGNIFICANCE_T
        # observatory must never have seen 2024+ (holdout period)
        assert reg["observation_window"]["end"] < "2021"

    def test_real_queue_respects_budget_and_lineage(self):
        q = json.loads((REPO_ROOT / "reports/factory/discovery_queue.json").read_text())
        assert q["queue_size"] <= MAX_HYPOTHESES_PER_CYCLE
        for h in q["hypotheses"]:
            assert h["evidence_obs_ids"]
            assert h["effect_vs_cost"] >= 0.25
