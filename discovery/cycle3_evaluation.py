"""
GEN 9-11 for Cycle 3: evaluate every multi-asset hypothesis on DEVELOPMENT data.

Per symbol:
    TRAIN               = first 80% of that symbol's dev bars
    INTERNAL VALIDATION = reserved last 20% of that symbol's dev bars

Gates are the SAME pre-registered thresholds used in Cycles 1-2 and are not
tunable here:
    train      : n >= 30, mean_net > 0, t >= 2.0
    validation : n >= 30, mean_net > 0, t >= 1.5

Cost is the frozen per-symbol relative round trip from discovery.cost_model.
The sealed holdout is never touched: every load goes through the firewall.
Deterministic -- same dev data produces a byte-identical result file.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.observatory import MarketObservatory, load_dev_bars, OBSERVATION_FRACTION
from discovery.engine import DiscoveryEngine, load_refuted_descriptions
from discovery.evaluation import (
    build_executor, exec_breakout, regime_breakdown, _stats,
    TRAIN_MIN_T, VAL_MIN_T, VAL_MIN_TRADES,
)
from discovery.cost_model import roundtrip_cost, cost_table, COST_MODEL_ID

SYMBOLS = ["EURUSD", "GBPUSD", "USDCAD", "USDCHF", "USDJPY", "XAUUSD"]
QUEUE_DIR = REPO_ROOT / "reports/factory/discovery_cycles/cycle_03_queues"
OUT = REPO_ROOT / "reports/factory/discovery_cycles/cycle_03_evaluation.json"


def build_queue(symbol: str):
    """Regenerate the symbol's Cycle 3 hypotheses (deterministic) and persist them."""
    bars = load_dev_bars(REPO_ROOT / "data/csv" / f"{symbol}_H1.csv")
    obs = MarketObservatory(bars)
    obs.run_all()
    payload = {
        "observation_window": {"start": obs.window[0].ts.isoformat(),
                               "end": obs.window[-1].ts.isoformat(),
                               "bars": len(obs.window)},
        "observations": [o.to_dict() for o in obs.observations],
    }
    eng = DiscoveryEngine(payload, load_refuted_descriptions())
    queue = eng.run()
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    (QUEUE_DIR / f"{symbol}.json").write_text(json.dumps(
        {"symbol": symbol, "queue_size": len(queue),
         "hypotheses": [h.to_dict() for h in queue]}, indent=2), encoding="utf-8")
    return bars, [h.to_dict() for h in queue]


def evaluate_symbol(symbol: str):
    bars, hyps = build_queue(symbol)
    cut = int(len(bars) * OBSERVATION_FRACTION)
    train, val = bars[:cut], bars[cut:]
    cost = roundtrip_cost(symbol)

    results, evals = [], 0
    for h in hyps:
        entry = {"symbol": symbol, "hyp_id": h["hyp_id"], "operator": h["operator"],
                 "mechanism": h["mechanism"]}

        if h["operator"] == "OP-STATE-FILTER":
            # ablation pair: breakout with vs without the NR7 no-trade filter
            tb, tf = exec_breakout(train, nr7_filter=False, cost=cost), \
                     exec_breakout(train, nr7_filter=True, cost=cost)
            vb, vf = exec_breakout(val, nr7_filter=False, cost=cost), \
                     exec_breakout(val, nr7_filter=True, cost=cost)
            evals += 4
            st_b, st_f = _stats(tb), _stats(tf)
            sv_b, sv_f = _stats(vb), _stats(vf)
            ti = st_f.mean_net - st_b.mean_net
            vi = sv_f.mean_net - sv_b.mean_net
            # An ablation only survives if the FILTERED strategy itself clears the
            # same pre-registered economic + statistical bar as every other
            # hypothesis. "Loses less than the unfiltered version" is not an edge.
            improves = ti > 0 and vi > 0
            tradable = (st_f.n >= VAL_MIN_TRADES and st_f.mean_net > 0
                        and st_f.t_stat >= TRAIN_MIN_T
                        and sv_f.n >= VAL_MIN_TRADES and sv_f.mean_net > 0
                        and sv_f.t_stat >= VAL_MIN_T)
            entry.update({
                "train": {"base": st_b.to_dict(), "filtered": st_f.to_dict()},
                "validation": {"base": sv_b.to_dict(), "filtered": sv_f.to_dict()},
                "train_filter_improvement": round(ti, 8),
                "validation_filter_improvement": round(vi, 8),
                "filter_improves_expectancy": improves,
                "filtered_variant_tradable": tradable,
                "verdict": "SURVIVES_INTERNAL" if (improves and tradable) else "REFUTED_INTERNAL",
            })
            if not tradable:
                entry["verdict_reason"] = (
                    f"filtered variant not tradable: train(n={st_f.n}, "
                    f"net={st_f.mean_net}, t={st_f.t_stat}) "
                    f"val(n={sv_f.n}, net={sv_f.mean_net}, t={sv_f.t_stat}); "
                    f"a filter that only reduces a loss is not an edge")
            results.append(entry)
            continue

        ex = build_executor(h)
        if ex is None:
            entry["verdict"] = "NO_EXECUTOR"
            results.append(entry)
            continue

        tr = ex(train, cost=cost); ts = _stats(tr); evals += 1
        entry["train"] = ts.to_dict()
        if ts.n < VAL_MIN_TRADES or ts.mean_net <= 0 or ts.t_stat < TRAIN_MIN_T:
            entry["verdict"] = "TRAIN_FAIL"
            entry["verdict_reason"] = (f"train: n={ts.n}, mean_net={ts.mean_net}, t={ts.t_stat} "
                                       f"(need n>={VAL_MIN_TRADES}, net>0, t>={TRAIN_MIN_T})")
            results.append(entry)
            continue

        va = ex(val, cost=cost); vs = _stats(va); evals += 1
        entry["validation"] = vs.to_dict()
        if vs.n < VAL_MIN_TRADES or vs.mean_net <= 0 or vs.t_stat < VAL_MIN_T:
            entry["verdict"] = "VALIDATION_FAIL"
            entry["verdict_reason"] = (f"validation: n={vs.n}, mean_net={vs.mean_net}, t={vs.t_stat} "
                                       f"(need n>={VAL_MIN_TRADES}, net>0, t>={VAL_MIN_T})")
        else:
            entry["verdict"] = "SURVIVES_INTERNAL"
            entry["regime_breakdown_train"] = regime_breakdown(tr, train)
            entry["regime_breakdown_validation"] = regime_breakdown(va, val)
        results.append(entry)

    return {"symbol": symbol,
            "train_window": {"start": train[0].ts.isoformat(), "end": train[-1].ts.isoformat(),
                             "bars": len(train)},
            "validation_window": {"start": val[0].ts.isoformat(), "end": val[-1].ts.isoformat(),
                                  "bars": len(val)},
            "roundtrip_cost": cost,
            "parameter_evaluations": evals,
            "results": results}


def main() -> int:
    per_symbol = [evaluate_symbol(s) for s in SYMBOLS]
    all_results = [r for b in per_symbol for r in b["results"]]
    survivors = [r for r in all_results if r["verdict"] == "SURVIVES_INTERNAL"]
    total_evals = sum(b["parameter_evaluations"] for b in per_symbol)

    payload = {
        "cycle_id": "CYCLE-3-MULTIASSET",
        "stage": "GEN 9-11 internal evaluation (development data only)",
        "cost_model_id": COST_MODEL_ID,
        "cost_table": cost_table(),
        "gates": {"train_min_t": TRAIN_MIN_T, "val_min_t": VAL_MIN_T,
                  "min_trades": VAL_MIN_TRADES},
        "hypotheses_evaluated": len(all_results),
        "parameter_evaluations": total_evals,
        "survivor_count": len(survivors),
        "survivors": [{"symbol": s["symbol"], "hyp_id": s["hyp_id"],
                       "mechanism": s["mechanism"]} for s in survivors],
        "per_symbol": per_symbol,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"GEN 9-11 CYCLE 3: {len(all_results)} hypotheses, {total_evals} parameter "
          f"evaluations, {len(survivors)} survive internal validation")
    for b in per_symbol:
        verds = {}
        for r in b["results"]:
            verds[r["verdict"]] = verds.get(r["verdict"], 0) + 1
        print(f"  {b['symbol']:7s} cost={b['roundtrip_cost']:.2e}  " +
              "  ".join(f"{k}={v}" for k, v in sorted(verds.items())))
    for s in survivors:
        print(f"  SURVIVOR {s['symbol']} {s['hyp_id']} :: {s['mechanism'][:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
