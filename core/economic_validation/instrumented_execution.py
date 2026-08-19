"""Generation 5, Phase 5 — Per-trade instrumentation.

The Generation 4 post-mortem's central mechanical finding (realized
reward:risk is systematically below nominal) had to be **derived
algebraically** from aggregate profit_factor/win_rate, because per-trade
exit-reason distributions and MFE/MAE were never captured for the
robustness surface, and the reusable per-partition evaluations, while
they DO already persist full per-trade records (``entry_price``,
``exit_price``, ``exit_reason``, ``holding_bars``, ``pnl``, ``gross_pnl``,
``cost_paid`` -- see ``EVALUATION_PURE_HOLDOUT.json``), never tracked the
price path *during* an open position, so Maximum Favorable/Adverse
Excursion could not be measured at all.

**Design constraint this module exists to satisfy.** ``core.
economic_validation.execution.execute()`` produced the checksums pinned
in every committed Generation 4 artifact
(``GENERATION4_SUMMARY.json['result_checksums']``), and
``tests/test_generation4_integration.py::test_pure_holdout_result_reproduces_from_source``
re-derives one of those checksums from a **fresh call** to that exact
code path. Adding fields to ``ExecutedTrade.to_dict()`` would change what
gets hashed and break that reproducibility gate outright. So this module
does not modify ``execution.py`` at all -- it is a parallel, additive
instrumentation layer with its own trade type, proven to reproduce
``execute()``'s economics exactly (see
``tests/test_generation5_instrumentation.py::test_parity_with_execute``)
before its extra measurements (MFE, MAE, signal value) are trusted for
anything.

This module is used to **replay already-frozen, already-terminal
candidate specifications for diagnostic purposes only**. It transitions
no registry state, produces no new verdict, and does not touch
``reports/generation4/*`` -- see ``scripts/run_generation5_instrumentation.py``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from core.economic_validation.execution import CostModel, RiskRules, _pnl, _position_size
from utils.exceptions import EAFactoryError

INSTRUMENTATION_ENGINE_ID = "INSTR-G5-001"


class InstrumentedExecutionError(EAFactoryError):
    pass


@dataclass
class InstrumentedTrade:
    """Generation 5 Phase 5 schema. Superset of ``ExecutedTrade`` plus the
    fields Generation 4 could not measure."""

    trade_id: str
    candidate_id: str
    instrument: str
    direction: int
    entry_time: str
    entry_price: float
    exit_time: Optional[str]
    exit_price: Optional[float]
    holding_period_bars: Optional[int]
    exit_reason: Optional[str]
    stop_loss_price: float
    take_profit_price: float
    nominal_reward_risk: float
    realized_R: Optional[float]
    gross_pnl: Optional[float]
    net_pnl: Optional[float]
    cost_paid: Optional[float]
    spread_at_entry: float
    slippage_assumption: float
    commission: float
    size_lots: float
    mfe_price: Optional[float]   # maximum favourable excursion, in price units, during the hold
    mae_price: Optional[float]   # maximum adverse excursion, in price units, during the hold
    mfe_r: Optional[float]       # MFE expressed as a multiple of the initial stop distance
    mae_r: Optional[float]
    signal_value: Optional[float]     # the feature reading that triggered entry (e.g. rsi_14)
    signal_feature: str
    rule_version: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def execute_instrumented(
    ohlcv: pd.DataFrame,
    signals: pd.Series,
    *,
    costs: CostModel,
    risk: RiskRules,
    candidate_id: str,
    instrument: str,
    signal_feature_series: Optional[pd.Series] = None,
    signal_feature_name: str = "UNKNOWN",
    rule_version: str = "UNKNOWN",
    initial_equity: float = 10_000.0,
    atr_column: str = "atr_14",
) -> List[InstrumentedTrade]:
    """Bar-by-bar replay of the SAME timing/priority/cost semantics as
    ``core.economic_validation.execution.execute`` (next-bar-open fill,
    same-bar risk triggers, STOP_LOSS > TAKE_PROFIT > MAX_HOLDING_PERIOD),
    with running MFE/MAE tracked in addition. Deliberately does not import
    or call ``execute()`` -- it must be provably equivalent, not merely
    delegate and hope; equivalence is asserted by
    ``tests/test_generation5_instrumentation.py``, not assumed here.
    """
    required = {"open", "high", "low", atr_column}
    missing = required - set(ohlcv.columns)
    if missing:
        raise InstrumentedExecutionError("ohlcv missing required columns", missing=sorted(missing))
    if risk.max_positions != 1:
        raise InstrumentedExecutionError("only single-position replay is supported")

    equity = float(initial_equity)
    open_trade: Optional[Dict[str, Any]] = None
    pending_entry: Optional[dict] = None
    trades: List[InstrumentedTrade] = []
    trade_counter = 0

    opens = ohlcv["open"].to_numpy(dtype="float64")
    highs = ohlcv["high"].to_numpy(dtype="float64")
    lows = ohlcv["low"].to_numpy(dtype="float64")
    atrs = ohlcv[atr_column].to_numpy(dtype="float64")
    index = ohlcv.index

    signal_map = {ts: int(v) for ts, v in signals.items() if int(v) != 0}
    feature_at = signal_feature_series if signal_feature_series is not None else pd.Series(dtype="float64")

    for i, ts in enumerate(index):
        if pending_entry is not None and open_trade is None:
            direction = pending_entry["direction"]
            atr_at_signal = pending_entry["atr"]
            if np.isfinite(atr_at_signal) and atr_at_signal > 0:
                entry_price = opens[i] + direction * (costs.spread_price + costs.slippage_price)
                sl_dist = risk.stop_loss_atr_mult * atr_at_signal
                tp_dist = risk.take_profit_atr_mult * atr_at_signal
                size = _position_size(equity, sl_dist, risk, costs)
                trade_counter += 1
                open_trade = {
                    "trade_id": f"{candidate_id}-TRADE-{trade_counter:05d}",
                    "entry_time": ts, "entry_price": entry_price, "direction": direction,
                    "size_lots": size,
                    "stop_loss_price": entry_price - direction * sl_dist,
                    "take_profit_price": entry_price + direction * tp_dist,
                    "entry_bar_index": i, "signal_time": pending_entry["signal_time"],
                    "atr_at_signal": atr_at_signal, "sl_dist": sl_dist,
                    "signal_value": pending_entry.get("signal_value"),
                    "mfe_price": 0.0, "mae_price": 0.0,
                }
            pending_entry = None

        if open_trade is not None:
            # Update running MFE/MAE using this bar's high/low BEFORE
            # checking exit triggers, so the excursion includes the bar
            # the trade eventually exits on (the path went there even if
            # the trade closed on the same bar).
            direction = open_trade["direction"]
            favourable_extreme = highs[i] if direction == 1 else -lows[i]
            adverse_extreme = lows[i] if direction == 1 else -highs[i]
            entry_ref = open_trade["entry_price"] if direction == 1 else -open_trade["entry_price"]
            fav_excursion = favourable_extreme - entry_ref
            adv_excursion = entry_ref - adverse_extreme
            open_trade["mfe_price"] = max(open_trade["mfe_price"], fav_excursion, 0.0)
            open_trade["mae_price"] = max(open_trade["mae_price"], adv_excursion, 0.0)

            holding_bars = i - open_trade["entry_bar_index"]
            reason, trigger_level = None, None
            if direction == 1:
                if lows[i] <= open_trade["stop_loss_price"]:
                    reason, trigger_level = "STOP_LOSS", open_trade["stop_loss_price"]
                elif highs[i] >= open_trade["take_profit_price"]:
                    reason, trigger_level = "TAKE_PROFIT", open_trade["take_profit_price"]
            else:
                if highs[i] >= open_trade["stop_loss_price"]:
                    reason, trigger_level = "STOP_LOSS", open_trade["stop_loss_price"]
                elif lows[i] <= open_trade["take_profit_price"]:
                    reason, trigger_level = "TAKE_PROFIT", open_trade["take_profit_price"]
            if reason is None and holding_bars >= risk.max_holding_bars:
                reason, trigger_level = "MAX_HOLDING_PERIOD", ohlcv["close"].to_numpy(dtype="float64")[i] if "close" in ohlcv.columns else opens[i]

            if reason is not None:
                exit_price = trigger_level
                if costs.apply_exit_slippage:
                    exit_price = trigger_level - direction * costs.slippage_price
                mock_trade = _MockTrade(open_trade["entry_price"], direction, open_trade["size_lots"])
                net, gross, cost = _pnl(mock_trade, exit_price, costs)
                equity += net
                sl_dist = open_trade["sl_dist"]
                nominal_rr = risk.take_profit_atr_mult / risk.stop_loss_atr_mult
                risk_amount = equity - net if sl_dist > 0 else None
                realized_R = (net / (risk.risk_per_trade * (equity - net))) if (equity - net) > 0 else None
                trades.append(InstrumentedTrade(
                    trade_id=open_trade["trade_id"], candidate_id=candidate_id, instrument=instrument,
                    direction=direction, entry_time=str(open_trade["entry_time"]),
                    entry_price=open_trade["entry_price"], exit_time=str(ts), exit_price=exit_price,
                    holding_period_bars=holding_bars, exit_reason=reason,
                    stop_loss_price=open_trade["stop_loss_price"], take_profit_price=open_trade["take_profit_price"],
                    nominal_reward_risk=nominal_rr, realized_R=realized_R,
                    gross_pnl=gross, net_pnl=net, cost_paid=cost,
                    spread_at_entry=costs.spread_price, slippage_assumption=costs.slippage_price,
                    commission=costs.commission_per_lot_round_turn * open_trade["size_lots"],
                    size_lots=open_trade["size_lots"],
                    mfe_price=open_trade["mfe_price"], mae_price=open_trade["mae_price"],
                    mfe_r=(open_trade["mfe_price"] / sl_dist) if sl_dist > 0 else None,
                    mae_r=(open_trade["mae_price"] / sl_dist) if sl_dist > 0 else None,
                    signal_value=open_trade["signal_value"], signal_feature=signal_feature_name,
                    rule_version=rule_version,
                ))
                open_trade = None

        if open_trade is None and pending_entry is None:
            sig = signal_map.get(ts, 0)
            if sig != 0:
                sig_val = float(feature_at.get(ts)) if ts in getattr(feature_at, "index", []) else None
                pending_entry = {"direction": sig, "atr": float(atrs[i]), "signal_time": ts, "signal_value": sig_val}

    return trades


@dataclass
class _MockTrade:
    """Minimal shape ``execution._pnl`` needs (entry_price, direction,
    size_lots) -- avoids constructing a full ``ExecutedTrade`` just to
    reuse the one shared PnL formula, which is deliberately reused (not
    reimplemented) so cost accounting cannot silently drift between the
    two engines."""

    entry_price: float
    direction: int
    size_lots: float
