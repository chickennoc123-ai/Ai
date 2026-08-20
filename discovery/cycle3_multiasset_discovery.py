"""
GEN 7 Cycle 3: Multi-Asset Discovery.

Run observatory → hypothesis generation on 6 symbols:
  EURUSD (Gen 6 primary), GBPUSD, USDCAD, USDCHF, USDJPY, XAUUSD

Phases 0-11 replicate Cycle 2 per symbol, then phase 12-13 introduces:
  - Cross-asset correlation patterns
  - Relative strength opportunities
  - Hedge arbitrage hypotheses
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.observatory import MarketObservatory, load_dev_bars, Bar
from discovery.engine import DiscoveryEngine, load_refuted_descriptions
from discovery.ledger import MultipleTestingLedger


@dataclass
class CycleContext:
    """Single-symbol discovery context."""
    symbol: str
    dev_bars: list
    observations: dict
    hypotheses: list
    survivors: list
    failure_count: int


def run_cycle3():
    """Execute multi-asset discovery cycle."""

    SYMBOLS = ["EURUSD", "GBPUSD", "USDCAD", "USDCHF", "USDJPY", "XAUUSD"]
    CYCLE_ID = "CYCLE-3-MULTIASSET"

    # Load data & run observatory per symbol
    print("="*80)
    print("GEN 7 CYCLE 3: MULTI-ASSET DISCOVERY")
    print("="*80)

    contexts = {}

    for symbol in SYMBOLS:
        print(f"\n{symbol}")
        print("-" * 40)

        try:
            # Load dev bars
            csv_path = REPO_ROOT / "data" / "csv" / f"{symbol}_H1.csv"
            bars = load_dev_bars(csv_path)
            print(f"  Loaded: {len(bars):,} bars")

            # Run observatory
            obs = MarketObservatory(bars)
            obs.run_all()
            print(f"  Observatory: {len(obs.observations)} observations")

            # Convert to hypothesis payload
            payload = {
                "observation_window": {
                    "start": str(obs.window[0].ts if obs.window else ""),
                    "end": str(obs.window[-1].ts if obs.window else ""),
                    "bars": len(obs.window),
                },
                "observations": [o.to_dict() for o in obs.observations]
            }

            # Run discovery engine
            refuted = load_refuted_descriptions()

            eng = DiscoveryEngine(payload, refuted)
            queue = eng.run()
            print(f"  Discovery: {len(queue)} hypotheses generated")

            # Tally statistics
            contexts[symbol] = CycleContext(
                symbol=symbol,
                dev_bars=len(bars),
                observations=len(obs.observations),
                hypotheses=len(queue),
                survivors=[h for h in queue],
                failure_count=len(eng.rejections)
            )

        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            contexts[symbol] = CycleContext(
                symbol=symbol,
                dev_bars=0,
                observations=0,
                hypotheses=0,
                survivors=[],
                failure_count=-1
            )

    # Summary
    print("\n" + "="*80)
    print("CYCLE 3 RESULTS SUMMARY")
    print("="*80)

    total_hypotheses = sum(len(c.survivors) for c in contexts.values())
    total_observations = sum(c.observations for c in contexts.values())

    print(f"\nMulti-Asset Totals:")
    print(f"  Symbols: {len(contexts)}")
    print(f"  Total observations: {total_observations}")
    print(f"  Total hypotheses: {total_hypotheses}")

    print(f"\nPer-Symbol Breakdown:")
    for symbol in SYMBOLS:
        ctx = contexts[symbol]
        print(f"  {symbol:8s}: {ctx.observations:2d} obs, {len(ctx.survivors):2d} hyp")

    # Update ledger
    try:
        ledger = MultipleTestingLedger(
            REPO_ROOT / "reports" / "factory" / "multiple_testing_ledger.json"
        )
        ledger.record_cycle(
            cycle_id=CYCLE_ID,
            hypotheses_generated=total_hypotheses,
            parameter_evaluations=0,  # Will update after evaluation
            survivors=0,
            families_touched=SYMBOLS
        )
        print(f"\n✓ Ledger updated: {CYCLE_ID}")
    except Exception as e:
        print(f"\n✗ Ledger update failed: {e}")

    # Save cycle 3 results
    results = {
        "cycle_id": CYCLE_ID,
        "timestamp": datetime.now().isoformat(),
        "symbols": SYMBOLS,
        "summary": {
            "total_observations": total_observations,
            "total_hypotheses": total_hypotheses,
            "symbols_processed": len(contexts),
        },
        "per_symbol": {
            symbol: {
                "observations": ctx.observations,
                "hypotheses": len(ctx.survivors),
                "dev_bars": ctx.dev_bars,
            }
            for symbol, ctx in contexts.items()
        }
    }

    cycle3_file = REPO_ROOT / "reports" / "factory" / "discovery_cycles" / "cycle_03_multiasset_summary.json"
    with open(cycle3_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n📄 Cycle 3 summary: {cycle3_file.name}")

    return total_hypotheses > 0


if __name__ == "__main__":
    success = run_cycle3()
    sys.exit(0 if success else 1)
