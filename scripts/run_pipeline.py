"""Run the full research pipeline from the command line.

Backtests and validates every requested strategy/symbol pair, then prints the
capital allocation the Decision Engine would grant.

Usage::

    python scripts/run_pipeline.py
    python scripts/run_pipeline.py --strategies RSI,MACD --symbols XAUUSD --full
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from core.backtest import BacktestConfig, BacktestEngine  # noqa: E402
from core.data_manager import DataManager  # noqa: E402
from core.decision import DecisionEngine  # noqa: E402
from core.lifecycle import LifecycleManager  # noqa: E402
from core.strategy_registry import available_strategies, create_strategy, load_strategies  # noqa: E402
from core.validation import ValidationSuite  # noqa: E402
from utils.config import get_config  # noqa: E402
from utils.logger import get_logger, setup_logging_from_config  # noqa: E402


async def run(strategies: List[str], symbols: List[str], timeframe: str, bars: int, full: bool) -> None:
    """Execute the research pipeline and print a report."""
    config = get_config()
    setup_logging_from_config(config)
    logger = get_logger("pipeline")
    load_strategies()

    data_manager = DataManager(config)
    engine = BacktestEngine(BacktestConfig.from_config(config))
    suite = ValidationSuite(config, engine)
    lifecycle = LifecycleManager(config)
    decision = DecisionEngine(config, lifecycle)

    frames = await data_manager.get_many(symbols, timeframe, bars)
    rows: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []

    for name in strategies:
        for symbol, frame in frames.items():
            try:
                strategy = create_strategy(name, symbol, timeframe)
                report = suite.run(strategy, frame, quick=not full)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Pipeline step failed", strategy=name, symbol=symbol, error=str(exc))
                continue

            metrics = report.baseline.get("metrics", {})
            key = f"{name}-{symbol}"
            lifecycle.register(key)
            lifecycle.update_state(key, metrics)
            rows.append(
                {
                    "strategy": name,
                    "symbol": symbol,
                    "sharpe": round(float(metrics.get("sharpe", 0.0)), 3),
                    "trades": int(metrics.get("trades", 0)),
                    "max_dd": round(float(metrics.get("max_drawdown", 0.0)), 4),
                    "wfa": round(report.walk_forward.efficiency, 3),
                    "pbo": round(report.pbo.pbo, 3) if report.pbo.computed else None,
                    "score": round(report.score, 3),
                    "passed": report.passed,
                    "state": lifecycle.get(key).state.value,
                }
            )
            candidates.append(
                {
                    "strategy_id": key,
                    "strategy_name": name,
                    "symbol": symbol,
                    "metrics": metrics,
                    "validation": report.to_dict(),
                }
            )

    if not rows:
        print("No strategy produced a usable result.")
        return

    table = pd.DataFrame(rows).sort_values("score", ascending=False)
    print("\n=== VALIDATION RESULTS ===")
    print(table.to_string(index=False))

    allocations = decision.allocate_portfolio(candidates, config.get_float("decision.capital", 10_000.0))
    print("\n=== CAPITAL ALLOCATION ===")
    allocation_rows = [
        {
            "strategy": item.strategy_name,
            "symbol": item.symbol,
            "raw_kelly": item.raw_kelly,
            "allocation": f"{item.allocation:.2%}",
            "capital": item.capital,
            "reason": "; ".join(item.reasons[:2]),
        }
        for item in allocations
    ]
    print(pd.DataFrame(allocation_rows).to_string(index=False))

    deployed = sum(1 for item in allocations if item.allocation > 0)
    print(f"\nPassed the gate : {int(table['passed'].sum())}/{len(table)}")
    print(f"Funded          : {deployed}/{len(allocations)}")
    if deployed == 0:
        print(
            "\nNo strategy was funded. On the simulated feed this is the expected outcome: "
            "the data has no persistent edge, and the validation gate is designed to say so."
        )
    await data_manager.close()


def main() -> int:
    """Parse arguments and run the pipeline."""
    config = get_config()
    parser = argparse.ArgumentParser(description="Run the EA Factory Pro research pipeline")
    parser.add_argument("--strategies", type=str, default=",".join(config.get_list("strategies.active", [])))
    parser.add_argument("--symbols", type=str, default=",".join(config.get_list("broker.xmtrading.symbols", [])))
    parser.add_argument("--timeframe", type=str, default="H1")
    parser.add_argument("--bars", type=int, default=6000)
    parser.add_argument("--full", action="store_true", help="Run PBO and robustness (slower)")
    arguments = parser.parse_args()

    strategies = [item.strip() for item in arguments.strategies.split(",") if item.strip()] or available_strategies()[:4]
    symbols = [item.strip() for item in arguments.symbols.split(",") if item.strip()] or ["EURUSD"]
    asyncio.run(run(strategies, symbols, arguments.timeframe, arguments.bars, arguments.full))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
