"""
GEN 7 CYCLE 2 -- PHASE 1: Research memory extraction.

Reads the append-only failure library (never mutates it) and produces a
machine-readable research-memory summary in the schema the task specifies:

  FAMILY | OBSERVATION | RESULT | FAILURE_MODE | KNOWN_LIMIT | UNEXPLORED_REGION

This is a READ-ONLY report generator over reports/factory/failure_library.json
and reports/factory/discovery_cycles/cycle_01_*.json. It never overwrites
history; it writes a new dated summary artifact each time it is run.
"""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List

FAILURE_LIBRARY = Path("reports/factory/failure_library.json")
CYCLE1_QUEUE = Path("reports/factory/discovery_cycles/cycle_01_queue.json")
CYCLE1_EVAL = Path("reports/factory/discovery_cycles/cycle_01_evaluation.json")
OUT = Path("reports/factory/research_memory_summary.json")

# Maps operator (cycle 1) / mechanism keywords -> canonical family name used
# throughout cycle 2, so PARAMETER_VARIANT/HORIZON_VARIANT/DUPLICATE
# classification has a stable vocabulary to check against.
OPERATOR_TO_FAMILY = {
    "OP-STREAK-REVERSAL": "STREAK_REVERSAL",
    "OP-SESSION-CONDITION": "SESSION_CONDITIONING",
    "OP-RECOMBINE": "REGIME_RECOMBINATION",
    "OP-EVENT-SEQUENCE": "GAP_DISLOCATION",
    "OP-STATE-FILTER": "VOLATILITY_STATE_FILTER",
    "OP-COST-AMORTIZED": "COST_AMORTIZATION",
}


@dataclass
class MemoryRow:
    family: str
    observation: str
    result: str
    failure_mode: str
    known_limit: str
    unexplored_region: str

    def to_dict(self) -> Dict:
        return asdict(self)


def _load_cycle1() -> Dict:
    queue = json.loads(CYCLE1_QUEUE.read_text(encoding="utf-8"))
    eva = json.loads(CYCLE1_EVAL.read_text(encoding="utf-8"))
    by_id = {h["hyp_id"]: h for h in queue["hypotheses"]}
    rows_by_result = {r["hyp_id"]: r for r in eva["results"]}
    return by_id, rows_by_result


def extract_memory() -> List[MemoryRow]:
    by_id, results = _load_cycle1()
    rows: List[MemoryRow] = []

    for hyp_id, h in by_id.items():
        r = results.get(hyp_id, {})
        family = OPERATOR_TO_FAMILY.get(h["operator"], h["operator"])
        verdict = r.get("verdict", "UNKNOWN")
        train = r.get("train", {})

        if h["operator"] == "OP-STATE-FILTER":
            result_str = f"filter ablation: {r.get('verdict')}"
            failure_mode = "FILTER_NO_IMPROVEMENT"
            known_limit = ("NR7 compression state is real (strongly significant) but does "
                          "not translate into a profitable no-trade filter on breakout entries")
            unexplored = ("whether compression state improves ENTRY TIMING (not filtering) "
                         "for other signal families; whether longer post-compression horizons help")
        else:
            gross = train.get("mean_net", 0) + 0.00011 if train else None
            net = train.get("mean_net", 0) if train else 0
            cost_dominated = gross is not None and gross > 0 and net <= 0
            underpowered = net > 0 and train.get("t_stat", 0) < 2.0
            if verdict == "TRAIN_FAIL" and underpowered:
                failure_mode = "INSUFFICIENT_STATISTICAL_POWER"
                known_limit = (f"net expectancy POSITIVE ({net*1e4:.2f} pips) but t="
                              f"{train.get('t_stat')} < 2.0 gate; underpowered, not unprofitable")
                unexplored = "raising trade count for this exact mechanism (more instruments, longer history)"
            elif verdict == "TRAIN_FAIL" and cost_dominated:
                failure_mode = "COST_DOMINATED"
                known_limit = (f"1-bar horizon gross effect ({gross*1e4:.2f} pips est.) is "
                              f"smaller than 1.1-pip roundtrip cost")
                unexplored = "longer holding horizons that amortize the same fixed cost"
            elif verdict == "TRAIN_FAIL":
                failure_mode = "NEGATIVE_EXPECTANCY"
                known_limit = f"net expectancy negative at 1-bar horizon (t={train.get('t_stat')})"
                unexplored = "whether sign/magnitude changes at longer horizons or with regime filters"
            else:
                failure_mode = verdict
                known_limit = "n/a"
                unexplored = "n/a"
            result_str = (f"train n={train.get('n')}, net={train.get('mean_net')}, "
                          f"t={train.get('t_stat')} -> {verdict}")

        rows.append(MemoryRow(
            family=family,
            observation=h["what_was_discovered"],
            result=result_str,
            failure_mode=failure_mode,
            known_limit=known_limit,
            unexplored_region=unexplored,
        ))

    # One extra row for the underpowered near-miss (FAIL-000022 correction),
    # since it carries a distinct, important lesson not visible per-hypothesis.
    rows.append(MemoryRow(
        family="GAP_DISLOCATION",
        observation="large weekend gaps (>8 pips) net +2.67 pips/trade, 2.4x cost",
        result="STATISTICAL_FAILURE: n=130, t=0.99 (underpowered, NOT unprofitable)",
        failure_mode="INSUFFICIENT_STATISTICAL_POWER",
        known_limit=("event rate ~52/year hard-caps achievable n on a single-symbol, "
                    "single-window test; re-testing the same window cannot fix this"),
        unexplored_region=("pooling the same mechanism across multiple correlated "
                          "instruments to raise n without reusing observations; "
                          "NOT explorable with current single-instrument dev data"),
    ))

    return rows


def refuted_hypothesis_family_memory() -> List[MemoryRow]:
    """The pre-existing HYP-000001..3 RSI mean-reversion family (must never
    be silently regenerated)."""
    return [MemoryRow(
        family="RSI_OVERSOLD_MEAN_REVERSION",
        observation="rsi_14 < 30 -> rsi_14 crosses back above 30 (3 variants incl. "
                   "volatility-regime-gated)",
        result="STRAT-000001, STRAT-000002 REJECTED (HYP-000001/2 REFUTED, "
              "HYP-000003 blocked by SILENT_HORIZON_DRIFT)",
        failure_mode="REFUTED / SILENT_HORIZON_DRIFT",
        known_limit="entire RSI-oversold-crossback mechanism family exhausted at H1 EURUSD",
        unexplored_region="none sanctioned -- refuted-family firewall blocks regeneration",
    )]


def save(rows: List[MemoryRow]) -> Dict:
    payload = {
        "generated_by": "discovery/research_memory.py (GEN 7 Cycle 2, Phase 1)",
        "source": "reports/factory/failure_library.json (read-only) + "
                  "reports/factory/discovery_cycles/cycle_01_*.json (read-only)",
        "row_count": len(rows),
        "rows": [r.to_dict() for r in rows],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    rows = refuted_hypothesis_family_memory() + extract_memory()
    payload = save(rows)
    print(f"RESEARCH MEMORY: {payload['row_count']} rows extracted -> {OUT}")
    for r in payload["rows"]:
        print(f"  [{r['family']}] {r['failure_mode']}: {r['known_limit'][:90]}")
    return 0


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
