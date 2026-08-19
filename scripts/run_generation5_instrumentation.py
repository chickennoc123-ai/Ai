#!/usr/bin/env python3
"""Generation 5, Phases 5-9 — Forensic instrumentation replay of
STRAT-000002's already-frozen, already-terminal specification.

**This is not a re-validation.** It transitions no registry state,
writes nothing to ``reports/generation4/``, and changes STRAT-000002's
verdict in no way -- the candidate remains terminally REJECTED. It
re-derives the same real historical trades the Generation 4 evaluation
already produced, using the additive instrumentation layer in
``core.economic_validation.instrumented_execution`` (proven to reproduce
``execute()``'s trades exactly -- see
``tests/test_generation5_instrumentation.py::test_parity_with_execute``),
to measure directly what Generation 4 could only infer algebraically:
per-trade exit-reason distributions, MFE/MAE, and signal-only economics
independent of the stop/target/max-hold mechanics.

Scope, disclosed rather than hidden: this replay covers the frozen
point's two Generation 4 partitions (DEVELOPMENT+VALIDATION combined, and
PURE_HOLDOUT) -- the same partitions Generation 4's headline economics
came from. It does not extend instrumentation to the 360-point robustness
surface; that is recorded as a known limitation in
``ML-001-G5-GENERATION-5-REPORT.md``, not silently omitted.

**PURE_HOLDOUT is treated differently from DEVELOPMENT_AND_VALIDATION.**
The holdout has been consumed exactly once in this Factory's entire
history (Generation 4, governance-closure §1). Re-sealing and
re-releasing it here -- even read-only, even for diagnostics -- would be
a second access, forbidden by Non-Negotiable Principles 5-7. So for
PURE_HOLDOUT this script does NOT touch the sealed dataset at all: it
reads the trade-level fields already committed in
``reports/generation4/EVALUATION_PURE_HOLDOUT.json`` (exit_reason,
holding_bars, pnl -- present there from the one legitimate access) for
Phase 6/8, and explicitly does NOT compute MFE/MAE or signal-quality
forward returns for holdout, since both would require re-reading holdout
price bars beyond what was already extracted. DEVELOPMENT_AND_VALIDATION
is reusable data with no such restriction and gets the full fresh
instrumented replay.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.economic_validation.cost_stress import base_cost_model  # noqa: E402
from core.economic_validation.data_eligibility import load_raw_ohlcv  # noqa: E402
from core.economic_validation.evaluation import build_execution_frame  # noqa: E402
from core.economic_validation.execution import RiskRules  # noqa: E402
from core.economic_validation.instrumented_execution import execute_instrumented  # noqa: E402
from core.economic_validation.partitions import seal_dataset  # noqa: E402
from core.economic_validation.rule_engine import generate_signals, parse_atr_multiple, parse_entry_rule  # noqa: E402
from core.economic_validation.signal_execution_separation import (  # noqa: E402
    compute_signal_quality, decompose_signal_vs_execution,
)
from core.economic_validation.trade_diagnostics import (  # noqa: E402
    analyze_exit_mechanism, analyze_holding_time, analyze_mfe_mae,
)
from core.factory.registry import StrategyRegistry  # noqa: E402
from core.factory.research_ledger import ResearchLedger  # noqa: E402

CANDIDATE_ID = "STRAT-000002"
OUTPUT_DIR = REPO_ROOT / "reports" / "generation5"


def _write(name: str, payload: Any) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return path


def _instrumented_trade_from_committed_dict(
    d: Dict[str, Any], *, equity_before: float, nominal_rr: float, candidate_id: str, instrument: str,
) -> "InstrumentedTrade":
    """Rebuild an InstrumentedTrade from an already-committed Generation 4
    trade dict (EVALUATION_PURE_HOLDOUT.json). MFE/MAE and signal_value
    are unavailable here by design -- see module docstring -- and are
    explicitly None, never fabricated."""
    from core.economic_validation.instrumented_execution import InstrumentedTrade

    pnl = d.get("pnl")
    risk_amount = equity_before * 0.02
    realized_R = (pnl / risk_amount) if (pnl is not None and risk_amount) else None
    return InstrumentedTrade(
        trade_id=f"{candidate_id}-HOLDOUT-{d['entry_time']}", candidate_id=candidate_id, instrument=instrument,
        direction=d["direction"], entry_time=d["entry_time"], entry_price=d["entry_price"],
        exit_time=d.get("exit_time"), exit_price=d.get("exit_price"),
        holding_period_bars=d.get("holding_bars"), exit_reason=d.get("exit_reason"),
        stop_loss_price=d["stop_loss_price"], take_profit_price=d["take_profit_price"],
        nominal_reward_risk=nominal_rr, realized_R=realized_R,
        gross_pnl=d.get("gross_pnl"), net_pnl=pnl, cost_paid=d.get("cost_paid"),
        spread_at_entry=0.0, slippage_assumption=0.0, commission=0.0, size_lots=d.get("size_lots", 0.0),
        mfe_price=None, mae_price=None, mfe_r=None, mae_r=None,
        signal_value=None, signal_feature="rsi_14", rule_version="RULE-R4-001",
    )


def main() -> Dict[str, Any]:
    registry = StrategyRegistry()
    candidate = registry.get(CANDIDATE_ID)
    assert candidate.state.value == "REJECTED", "refusing to instrument a non-terminal candidate"

    full = load_raw_ohlcv(REPO_ROOT / "data" / "csv" / "EURUSD_H1.csv")
    sealed = seal_dataset(full, dataset_id="EURUSD_H1", dataset_checksum="replay-diagnostic-only")

    rule = parse_entry_rule(candidate.spec.entry_rule, candidate.spec.direction)
    risk = RiskRules(
        risk_per_trade=0.02,
        stop_loss_atr_mult=parse_atr_multiple(candidate.spec.stop_loss),
        take_profit_atr_mult=parse_atr_multiple(candidate.spec.take_profit),
        max_holding_bars=int(candidate.spec.max_hold_bars),
    )
    costs = base_cost_model("EURUSD")
    nominal_rr = risk.take_profit_atr_mult / risk.stop_loss_atr_mult

    summary: Dict[str, Any] = {"candidate_id": CANDIDATE_ID, "note": "FORENSIC REPLAY -- no registry mutation, no new verdict"}

    # ---------- DEVELOPMENT_AND_VALIDATION: reusable data, full fresh replay ----------
    dev_and_val = sealed.development_and_validation()
    exec_frame, features = build_execution_frame(dev_and_val)
    signals = generate_signals(features, rule)
    trades = execute_instrumented(
        exec_frame, signals, costs=costs, risk=risk, candidate_id=CANDIDATE_ID, instrument="EURUSD",
        signal_feature_series=features["rsi_14"], signal_feature_name="rsi_14",
        rule_version="RULE-R4-001", initial_equity=10_000.0,
    )
    _write("INSTRUMENTED_TRADES_DEVELOPMENT_AND_VALIDATION.json", [t.to_dict() for t in trades])
    exit_report = analyze_exit_mechanism(trades)
    mfe_mae_report = analyze_mfe_mae(trades)
    holding_report = analyze_holding_time(trades)
    _write("EXIT_MECHANISM_DEVELOPMENT_AND_VALIDATION.json", exit_report)
    _write("MFE_MAE_DEVELOPMENT_AND_VALIDATION.json", mfe_mae_report)
    _write("HOLDING_TIME_DEVELOPMENT_AND_VALIDATION.json", holding_report)

    signal_quality = compute_signal_quality(exec_frame, features, rule, horizon_bars=int(candidate.spec.max_hold_bars))
    gross_win = sum(t.net_pnl for t in trades if (t.net_pnl or 0) > 0)
    gross_loss = -sum(t.net_pnl for t in trades if (t.net_pnl or 0) < 0)
    observed_pf = (gross_win / gross_loss) if gross_loss > 0 else None
    # An "edge" smaller than the cost of trading it once is not
    # economically material regardless of its statistical sign.
    round_trip_cost_as_return = (costs.spread_price + 2 * costs.slippage_price) / float(exec_frame["close"].mean())
    decomposition = decompose_signal_vs_execution(
        signal_quality, {"profit_factor": observed_pf}, materiality_floor=round_trip_cost_as_return,
    )
    _write("SIGNAL_EXECUTION_SEPARATION_DEVELOPMENT_AND_VALIDATION.json", decomposition)

    summary["DEVELOPMENT_AND_VALIDATION"] = {
        "n_trades": len(trades),
        "exit_reason_counts": {k: v["count"] for k, v in exit_report["exit_reason_breakdown"].items()},
        "realized_vs_nominal_pct": exit_report["realized_vs_nominal_pct"],
        "observed_profit_factor": observed_pf,
        "signal_edge": signal_quality.get("signal_edge"),
        "signal_execution_classification": decomposition["classification"],
        "mfe_mae_available": True,
    }
    print(f"[DEVELOPMENT_AND_VALIDATION] {summary['DEVELOPMENT_AND_VALIDATION']}")

    # ---------- PURE_HOLDOUT: NOT re-accessed. Read from the already- ----------
    # committed Generation 4 evaluation record only (one legitimate access,
    # already spent). MFE/MAE and signal-quality forward returns are
    # therefore NOT computed for holdout -- see module docstring.
    committed_holdout = json.loads((REPO_ROOT / "reports" / "generation4" / "EVALUATION_PURE_HOLDOUT.json").read_text())
    equity = 10_000.0
    holdout_trades = []
    for d in committed_holdout["trades"]:
        holdout_trades.append(_instrumented_trade_from_committed_dict(
            d, equity_before=equity, nominal_rr=nominal_rr, candidate_id=CANDIDATE_ID, instrument="EURUSD",
        ))
        equity += d.get("pnl") or 0.0
    _write("INSTRUMENTED_TRADES_PURE_HOLDOUT.json", [t.to_dict() for t in holdout_trades])
    holdout_exit_report = analyze_exit_mechanism(holdout_trades)
    holdout_holding_report = analyze_holding_time(holdout_trades)
    _write("EXIT_MECHANISM_PURE_HOLDOUT.json", holdout_exit_report)
    _write("HOLDING_TIME_PURE_HOLDOUT.json", holdout_holding_report)
    _write("MFE_MAE_PURE_HOLDOUT.json", {
        "n_trades": len(holdout_trades),
        "mfe_r_distribution": None, "mae_r_distribution": None,
        "verdict": "NOT_COMPUTED",
        "reason": (
            "MFE/MAE requires the intra-trade price path, which is not present in the already-"
            "committed EVALUATION_PURE_HOLDOUT.json trade records and cannot be obtained without a "
            "second access to the sealed PURE_HOLDOUT partition. PURE_HOLDOUT has been consumed "
            "exactly once in this Factory's entire history (Generation 4); a second access -- even "
            "read-only, even for diagnostics -- is forbidden by Non-Negotiable Principles 5-7. "
            "DEVELOPMENT_AND_VALIDATION (reusable data) carries the full MFE/MAE analysis instead."
        ),
    })
    _write("SIGNAL_EXECUTION_SEPARATION_PURE_HOLDOUT.json", {
        "verdict": "NOT_COMPUTED",
        "reason": "same holdout-once restriction as MFE/MAE above -- forward-return computation would require re-reading holdout price bars beyond the already-extracted trade records.",
    })
    summary["PURE_HOLDOUT"] = {
        "n_trades": len(holdout_trades),
        "exit_reason_counts": {k: v["count"] for k, v in holdout_exit_report["exit_reason_breakdown"].items()},
        "realized_vs_nominal_pct": holdout_exit_report["realized_vs_nominal_pct"],
        "mfe_mae_available": False,
        "source": "reports/generation4/EVALUATION_PURE_HOLDOUT.json (already-committed, single legitimate access)",
    }
    print(f"[PURE_HOLDOUT] {summary['PURE_HOLDOUT']}")

    _write("GENERATION5_INSTRUMENTATION_SUMMARY.json", summary)

    ledger = ResearchLedger()
    ledger.append(
        "INSTRUMENTATION_REPLAY_COMPLETED", subject_id=CANDIDATE_ID,
        reason="Generation 5 Phase 5-9 forensic instrumentation replay completed over frozen spec; no registry state changed",
        result=json.dumps({k: v for k, v in summary.items() if k != "note"}, sort_keys=True, default=str),
        artifact_reference="reports/generation5/GENERATION5_INSTRUMENTATION_SUMMARY.json",
    )
    return summary


if __name__ == "__main__":
    main()
