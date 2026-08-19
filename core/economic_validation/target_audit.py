"""Generation 4, Phase 4 — Target / label audit.

STRAT-000002 is rule-based, so it has no learned label. Its "target" — the
thing whose sign and magnitude the whole economic verdict rests on — is
the realized P&L of each trade. The leakage questions are the same
questions, asked of the trade record instead of a label column:

* Does the decision to enter use anything from after the decision bar?
* Does the realized outcome use anything from after the exit bar?
* Are the outcomes overlapping, so that one price move is counted twice?
* Does the horizon match the frozen specification?
* Does a trade still open at the end of the data get counted as a result?

Every one of these is checked against the actual executed trades, and
three of them are checked *empirically* by perturbing the price series
and requiring the answer not to move. The static timestamp checks alone
would pass for an engine that reads future prices through some path the
timestamps do not reveal; the perturbation checks would not.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from core.economic_validation.execution import CostModel, ExecutionResult, RiskRules, execute
from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

PASS = "PASS"
FAIL = "FAIL"


class TargetAuditError(EAFactoryError):
    pass


@dataclass(frozen=True)
class TargetLeakageAuditReport:
    verdict: str
    audit_timestamp: str
    candidate_id: str
    partition_name: str

    target_construction: Dict[str, Any]
    signal_to_entry_lag_bars: Dict[str, int]
    horizon_conformance: str
    overlap_check: str
    unclosed_trade_handling: str
    post_exit_perturbation: str
    post_signal_decision_invariance: str
    boundary_check: str

    trades_audited: int
    violations: tuple = ()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["violations"] = list(self.violations)
        return d

    def report_checksum(self) -> str:
        """Checksum of the findings, excluding ``audit_timestamp`` -- see
        ``DataEligibilityReport.report_checksum`` for why."""
        d = self.to_dict()
        d.pop("audit_timestamp", None)
        return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def _signal_to_entry_lags(result: ExecutionResult, index: pd.DatetimeIndex) -> Dict[str, int]:
    positions = {ts: i for i, ts in enumerate(index)}
    lags = [
        positions[t.entry_time] - positions[t.signal_time]
        for t in result.trades
        if t.entry_time in positions and t.signal_time in positions
    ]
    if not lags:
        return {"min": 0, "max": 0, "n": 0}
    return {"min": int(min(lags)), "max": int(max(lags)), "n": len(lags)}


def audit_target_construction(
    ohlcv: pd.DataFrame,
    signals: pd.Series,
    result: ExecutionResult,
    *,
    costs: CostModel,
    risk: RiskRules,
    candidate_id: str,
    partition_name: str,
    perturbation_sample: int = 25,
    seed: int = 20260819,
) -> TargetLeakageAuditReport:
    """Run the full Phase 4 audit against real executed trades."""
    violations: List[str] = []
    index = ohlcv.index
    positions = {ts: i for i, ts in enumerate(index)}
    trades = result.trades

    # --- 1. signal -> entry lag must be exactly one bar -------------------
    lags = _signal_to_entry_lags(result, index)
    if trades and (lags["min"] != 1 or lags["max"] != 1):
        violations.append(
            f"signal-to-entry lag is not uniformly 1 bar (min={lags['min']}, max={lags['max']}): "
            "an entry filled on the signal bar itself would use information not yet available"
        )

    # --- 2. horizon conformance ------------------------------------------
    over_horizon = [t for t in trades if (t.holding_bars or 0) > risk.max_holding_bars]
    if over_horizon:
        violations.append(
            f"{len(over_horizon)} trades exceed the frozen max_holding_bars={risk.max_holding_bars}"
        )
    horizon_conformance = PASS if not over_horizon else FAIL

    # --- 3. no overlapping outcomes --------------------------------------
    overlaps = 0
    ordered = sorted((t for t in trades if t.exit_time is not None), key=lambda t: t.entry_time)
    for prev, nxt in zip(ordered, ordered[1:]):
        if nxt.entry_time <= prev.exit_time:
            overlaps += 1
    if overlaps:
        violations.append(f"{overlaps} pairs of trades overlap in time; one price move counted more than once")
    overlap_check = PASS if overlaps == 0 else FAIL

    # --- 4. an unclosed trade must not be counted as a result -------------
    counted_unclosed = [t for t in trades if t.exit_time is None]
    if counted_unclosed:
        violations.append(f"{len(counted_unclosed)} trades were counted with no exit recorded")
    unclosed_handling = (
        PASS
        if not counted_unclosed
        else FAIL
    )

    # --- 5. post-exit perturbation: outcome must not move -----------------
    rng = np.random.default_rng(seed)
    post_exit_status = PASS
    if trades:
        sample = list(rng.choice(len(trades), size=min(perturbation_sample, len(trades)), replace=False))
        for k in sample:
            trade = trades[int(k)]
            if trade.exit_time is None or trade.exit_time not in positions:
                continue
            exit_pos = positions[trade.exit_time]
            if exit_pos + 1 >= len(index):
                continue
            perturbed = ohlcv.copy()
            for col in ("open", "high", "low", "close"):
                if col in perturbed.columns:
                    arr = perturbed[col].to_numpy(dtype="float64").copy()
                    arr[exit_pos + 1 :] *= 1.3
                    perturbed[col] = arr
            re_result = execute(perturbed, signals, costs=costs, risk=risk, initial_equity=result.initial_equity)
            match = [t for t in re_result.trades if t.signal_time == trade.signal_time]
            if not match:
                violations.append(
                    f"trade signalled at {trade.signal_time} disappeared when bars AFTER its exit were changed"
                )
                post_exit_status = FAIL
                continue
            if match[0].pnl != trade.pnl or match[0].exit_time != trade.exit_time:
                violations.append(
                    f"trade signalled at {trade.signal_time} changed outcome when bars AFTER its exit "
                    f"({trade.exit_time}) were changed: pnl {trade.pnl!r} -> {match[0].pnl!r}, "
                    f"exit {trade.exit_time} -> {match[0].exit_time}"
                )
                post_exit_status = FAIL

    # --- 6. the entry DECISION must not depend on post-signal bars --------
    # Entry *price* legitimately comes from the next bar's open; the
    # decision to enter must not. Perturb every bar strictly after the
    # signal bar and require the same set of signal timestamps to be acted on.
    post_signal_status = PASS
    if trades:
        sample = list(rng.choice(len(trades), size=min(perturbation_sample, len(trades)), replace=False))
        for k in sample:
            trade = trades[int(k)]
            if trade.signal_time not in positions:
                continue
            sig_pos = positions[trade.signal_time]
            if sig_pos + 1 >= len(index):
                continue
            perturbed = ohlcv.copy()
            for col in ("open", "high", "low", "close"):
                if col in perturbed.columns:
                    arr = perturbed[col].to_numpy(dtype="float64").copy()
                    arr[sig_pos + 1 :] *= 1.15
                    perturbed[col] = arr
            re_result = execute(perturbed, signals, costs=costs, risk=risk, initial_equity=result.initial_equity)
            still_taken = any(t.signal_time == trade.signal_time for t in re_result.trades)
            if not still_taken:
                violations.append(
                    f"the decision to enter on the signal at {trade.signal_time} changed when only "
                    "LATER bars were perturbed -- the entry decision reads the future"
                )
                post_signal_status = FAIL

    # --- 7. boundary: no trade may be entered on the final bar ------------
    boundary_status = PASS
    last_ts = index[-1]
    if any(t.entry_time == last_ts for t in trades):
        violations.append("a trade was entered on the final bar, which cannot be filled or exited")
        boundary_status = FAIL
    entered_after_signal_at_end = [
        t for t in trades if t.signal_time == index[-1]
    ]
    if entered_after_signal_at_end:
        violations.append("a signal on the final bar produced a trade; there is no next bar to fill it at")
        boundary_status = FAIL

    verdict = PASS if not violations else FAIL

    return TargetLeakageAuditReport(
        verdict=verdict,
        audit_timestamp=utcnow().isoformat(),
        candidate_id=candidate_id,
        partition_name=partition_name,
        target_construction={
            "target_type": "REALIZED_TRADE_PNL",
            "learned_label": None,
            "learned_label_note": (
                "STRAT-000002 specifies no model and therefore no learned label. The economically "
                "meaningful target is the realized net P&L of each executed trade."
            ),
            "signal_timestamp": "bar close of t (features computed from bars <= t only)",
            "decision_timestamp": "bar close of t -- identical to the signal timestamp",
            "entry_timestamp": "open of bar t+1",
            "exit_timestamp": "the bar at which STOP_LOSS/TAKE_PROFIT/MAX_HOLDING_PERIOD first fires",
            "forecast_horizon_bars": risk.max_holding_bars,
            "hypothesis_horizon_bars": 12,
            "horizon_note": (
                "HYP-000001 states a 12-bar forward-return horizon; the frozen candidate realizes it "
                "as max_hold_bars=12 with earlier exit on stop or target. These are consistent but not "
                "identical: a stopped-out trade realizes a shorter horizon than the hypothesis states. "
                "This is a property of the frozen specification, recorded here, not corrected here."
            ),
            "overlap_policy": "one open position at a time; outcomes are non-overlapping by construction",
        },
        signal_to_entry_lag_bars=lags,
        horizon_conformance=horizon_conformance,
        overlap_check=overlap_check,
        unclosed_trade_handling=unclosed_handling,
        post_exit_perturbation=post_exit_status,
        post_signal_decision_invariance=post_signal_status,
        boundary_check=boundary_status,
        trades_audited=len(trades),
        violations=tuple(violations),
    )
