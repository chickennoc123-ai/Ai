"""Generation 4, Phase 17 — Cost and slippage stress.

The scenario ladder is declared here, in code, before any scenario is
run. Nothing in this module reads a result and adjusts an assumption.

Base assumptions and where they come from — this matters, because a cost
figure invented to be flattering is the single easiest way to fake an
edge:

* **Spread**: ``core.utils.INSTRUMENTS[symbol].typical_spread_pips`` —
  EURUSD 1.6 pips, GBPUSD 2.0 pips. These are the repository's own
  pre-existing committed values (present since long before Generation 4)
  and were not chosen or adjusted here.
* **Slippage**: 0.2 pip, from ``ML-001-R2-CLEAN-REBUILD-SPEC.md`` §7 and
  the candidate's own frozen ``transaction_cost_model`` string.
* **Commission**: 7.00 per lot round turn, from
  ``core.ml_r2.backtest_r2.BacktestConfig``.

**Known limitation, stated plainly**: none of the three has been
confirmed against a real broker feed for this dataset's period — spec §17
Open Item #2 has been open since the original rebuild and this generation
does not close it. They are *plausible retail figures*, not measured
ones. The ZERO_COST scenario is included precisely so a reader can see
how much of any result depends on them.

Latency and market impact are handled as the slippage multiples rather
than as separate additive terms: for a single-lot retail FX position on
H1 bars, market impact is not measurable and latency manifests as
slippage. Modelling them as separate named terms would give false
precision, so they are folded in and disclosed here instead.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

from core.economic_validation.evaluation import evaluate_partition
from core.economic_validation.execution import CostModel, RiskRules
from core.economic_validation.rule_engine import CrossoverRule
from core.utils import INSTRUMENTS
from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

COMMISSION_PER_LOT_ROUND_TURN = 7.0
BASE_SLIPPAGE_PIPS = 0.2
PIP_VALUE_PER_LOT = 10.0

#: Declared scenario ladder. ``spread_mult``/``slippage_mult`` multiply the
#: instrument's base figures; ``commission_mult`` multiplies the base
#: commission.
SCENARIOS: List[Dict[str, Any]] = [
    {"label": "ZERO_COST", "spread_mult": 0.0, "slippage_mult": 0.0, "commission_mult": 0.0,
     "note": "Diagnostic only. Never economic evidence -- no account trades at zero cost."},
    {"label": "BASE", "spread_mult": 1.0, "slippage_mult": 1.0, "commission_mult": 1.0,
     "note": "The candidate's own frozen transaction_cost_model."},
    {"label": "REALISTIC_SPREAD", "spread_mult": 1.25, "slippage_mult": 1.0, "commission_mult": 1.0,
     "note": "Typical spread understates the session-average; +25% approximates a realistic blend."},
    {"label": "1X_SLIPPAGE", "spread_mult": 1.0, "slippage_mult": 1.0, "commission_mult": 1.0,
     "note": "Identical to BASE by construction; retained so the ladder's rungs are explicit."},
    {"label": "2X_SLIPPAGE", "spread_mult": 1.0, "slippage_mult": 2.0, "commission_mult": 1.0,
     "note": "Doubled slippage: news/rollover execution degradation."},
    {"label": "3X_SLIPPAGE", "spread_mult": 1.0, "slippage_mult": 3.0, "commission_mult": 1.0,
     "note": "Tripled slippage: stressed liquidity."},
    {"label": "SPREAD_WIDENING_2X", "spread_mult": 2.0, "slippage_mult": 1.0, "commission_mult": 1.0,
     "note": "Doubled spread: illiquid sessions, event windows."},
    {"label": "STRESSED", "spread_mult": 2.0, "slippage_mult": 3.0, "commission_mult": 1.0,
     "note": "Combined widening and slippage degradation."},
]


class CostStressError(EAFactoryError):
    pass


def base_cost_model(symbol: str, *, label: str = "BASE") -> CostModel:
    """The candidate's declared cost model for ``symbol``."""
    try:
        spec = INSTRUMENTS[symbol]
    except KeyError as exc:
        raise CostStressError(
            "no committed InstrumentSpec for this symbol; refusing to invent a spread figure",
            symbol=symbol,
        ) from exc
    return CostModel(
        spread_price=spec.typical_spread_pips * spec.pip_size,
        slippage_price=BASE_SLIPPAGE_PIPS * spec.pip_size,
        commission_per_lot_round_turn=COMMISSION_PER_LOT_ROUND_TURN,
        pip_size=spec.pip_size,
        pip_value_per_lot=PIP_VALUE_PER_LOT,
        apply_exit_slippage=True,
        label=label,
    )


def scenario_cost_model(symbol: str, scenario: Dict[str, Any]) -> CostModel:
    base = base_cost_model(symbol)
    return CostModel(
        spread_price=base.spread_price * float(scenario["spread_mult"]),
        slippage_price=base.slippage_price * float(scenario["slippage_mult"]),
        commission_per_lot_round_turn=base.commission_per_lot_round_turn * float(scenario["commission_mult"]),
        pip_size=base.pip_size,
        pip_value_per_lot=base.pip_value_per_lot,
        apply_exit_slippage=float(scenario["slippage_mult"]) > 0,
        label=str(scenario["label"]),
    )


@dataclass(frozen=True)
class CostScenarioResult:
    label: str
    note: str
    spread_price: float
    slippage_price: float
    commission_per_lot_round_turn: float
    trade_count: int
    net_profit: float
    profit_factor: Optional[float]
    expectancy: Optional[float]
    win_rate: Optional[float]
    max_drawdown: float
    total_costs_paid: float
    gross_pnl_before_costs: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CostStressReport:
    candidate_id: str
    validation_run_id: str
    partition_name: str
    symbol: str
    assumptions: Dict[str, Any]
    scenarios: tuple
    degradation: Dict[str, Any]
    zero_cost_dependency: str
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["scenarios"] = list(self.scenarios)
        return d

    def report_checksum(self) -> str:
        d = self.to_dict()
        d.pop("timestamp", None)
        return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def run_cost_stress(
    context_ohlcv: pd.DataFrame,
    *,
    evaluation_start: pd.Timestamp,
    rule: CrossoverRule,
    risk: RiskRules,
    symbol: str,
    candidate_id: str,
    validation_run_id: str,
    partition_name: str,
    dataset_checksum: str,
    code_version: str,
    scenarios: Optional[List[Dict[str, Any]]] = None,
    initial_equity: float = 10_000.0,
    timeframe: str = "H1",
    precomputed: Optional[Any] = None,
) -> CostStressReport:
    scenarios = list(scenarios or SCENARIOS)
    cached = precomputed.full() if precomputed is not None else None
    results: List[CostScenarioResult] = []

    for scenario in scenarios:
        costs = scenario_cost_model(symbol, scenario)
        record = evaluate_partition(
            context_ohlcv,
            evaluation_start=evaluation_start,
            rule=rule,
            costs=costs,
            risk=risk,
            candidate_id=candidate_id,
            validation_run_id=validation_run_id,
            partition_name=f"{partition_name}_COST_{scenario['label']}",
            dataset_checksum=dataset_checksum,
            code_version=code_version,
            initial_equity=initial_equity,
            timeframe=timeframe,
            precomputed=cached,
        )
        m = record.metrics
        results.append(
            CostScenarioResult(
                label=str(scenario["label"]),
                note=str(scenario.get("note", "")),
                spread_price=costs.spread_price,
                slippage_price=costs.slippage_price,
                commission_per_lot_round_turn=costs.commission_per_lot_round_turn,
                trade_count=int(m["trade_count"]),
                net_profit=float(m["net_profit"]),
                profit_factor=m["profit_factor"],
                expectancy=m["expectancy"],
                win_rate=m["win_rate"],
                max_drawdown=float(m["max_drawdown"]),
                total_costs_paid=float(m["total_costs_paid"]),
                gross_pnl_before_costs=float(m["gross_pnl_before_costs"]),
            )
        )

    by_label = {r.label: r for r in results}
    zero = by_label.get("ZERO_COST")
    base = by_label.get("BASE")

    degradation = {}
    if base is not None:
        for r in results:
            degradation[r.label] = {
                "net_profit_delta_vs_base": r.net_profit - base.net_profit,
                "profit_factor": r.profit_factor,
                "expectancy": r.expectancy,
                "trade_count_delta_vs_base": r.trade_count - base.trade_count,
                "max_drawdown_delta_vs_base": r.max_drawdown - base.max_drawdown,
            }

    if zero is not None and base is not None:
        zero_positive = zero.net_profit > 0
        base_positive = base.net_profit > 0
        if zero_positive and not base_positive:
            dependency = (
                "ZERO_COST_DEPENDENT: the strategy is profitable only when execution costs are "
                "removed entirely. This is a disqualifying property, not a near miss -- no account "
                "trades at zero cost."
            )
        elif not zero_positive:
            dependency = (
                "NOT_COST_DEPENDENT: the strategy is unprofitable even with all execution costs "
                "removed, so costs are not what is destroying it. The signal itself has no edge."
            )
        else:
            dependency = "SURVIVES_COSTS: profitable both at zero cost and at the declared base cost model."
    else:
        dependency = "UNDETERMINED"

    return CostStressReport(
        candidate_id=candidate_id,
        validation_run_id=validation_run_id,
        partition_name=partition_name,
        symbol=symbol,
        assumptions={
            "spread_source": f"core.utils.INSTRUMENTS['{symbol}'].typical_spread_pips (pre-existing committed value)",
            "typical_spread_pips": INSTRUMENTS[symbol].typical_spread_pips,
            "slippage_pips": BASE_SLIPPAGE_PIPS,
            "slippage_source": "ML-001-R2-CLEAN-REBUILD-SPEC.md §7 / candidate's frozen transaction_cost_model",
            "commission_per_lot_round_turn": COMMISSION_PER_LOT_ROUND_TURN,
            "commission_source": "core.ml_r2.backtest_r2.BacktestConfig",
            "pip_value_per_lot": PIP_VALUE_PER_LOT,
            "applied_legs": "spread on entry; slippage on entry AND exit; commission per round turn",
            "latency_and_market_impact": (
                "folded into the slippage multiples rather than modelled as separate additive terms; "
                "see this module's docstring for why"
            ),
            "swap_financing": (
                "NOT MODELLED. Max holding period is 12 H1 bars, so most trades never cross a "
                "rollover; those that do would incur an additional cost, making these results "
                "optimistic rather than pessimistic."
            ),
            "confirmed_against_broker_feed": False,
            "open_governance_item": "ML-001-R2-CLEAN-REBUILD-SPEC.md §17 Open Item #2 remains open",
        },
        scenarios=tuple(r.to_dict() for r in results),
        degradation=degradation,
        zero_cost_dependency=dependency,
        timestamp=utcnow().isoformat(),
    )
