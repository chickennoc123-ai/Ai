# ML-001-R4 — Cost and Slippage Stress Report

**Phase:** Generation 4, Phase 17
**Run:** `G4RUN-STRAT-000002-6b1c63d014d4a7be`
**Artifact:** `reports/generation4/COST_STRESS.json`
**Verdict:** `COST_STRESS_STATUS = FAIL` — classification **`NOT_COST_DEPENDENT`**

---

## 1. Assumptions, and where each came from

A cost figure invented to be flattering is the single easiest way to fake
an edge, so every number below is traced to something that existed before
this generation.

| Assumption | Value | Source |
|---|---|---|
| Spread (EURUSD) | **1.6 pips** | `core/utils.py` `INSTRUMENTS["EURUSD"].typical_spread_pips` — pre-existing committed repository constant |
| Slippage | **0.2 pip** | `ML-001-R2-CLEAN-REBUILD-SPEC.md` §7, and the candidate's own frozen `transaction_cost_model` |
| Commission | **7.00 per lot round turn** | `core/ml_r2/backtest_r2.py` `BacktestConfig` |
| Pip value | 10.00 per lot | `BacktestConfig` |

**Application:** spread charged on entry (bid series; a long buys at ask),
slippage charged adversely on entry **and** exit, commission per round
turn.

### 1.1 Why this is stricter than the pre-existing engine

`core/ml_r2/backtest_r2.py` applies slippage on **entry only**. A cost
model that charges one side of a round turn systematically flatters every
strategy it evaluates.

`backtest_r2.py` was **not modified** — it is frozen evidence for
`STRAT-000001`. Generation 4 uses `EXEC-R4-001`
(`core/economic_validation/execution.py`), which charges both legs, and
`tests/test_generation4_execution_parity.py` pins it against
`run_backtest` under matched settings (zero spread, exit slippage off),
requiring trade-for-trade equality of entry time, exit time, exit reason,
entry price, exit price, position size and P&L. The extension is
demonstrably an addition to the audited semantics, not a divergence.

### 1.2 Limitations, stated rather than implied

* **None of the three figures has been confirmed against a real broker
  feed** for this dataset's 2012–2022 period. They are plausible retail
  figures, not measured ones. `ML-001-R2-CLEAN-REBUILD-SPEC.md` §17 Open
  Item #2 remains open and this generation does not close it.
* **Latency and market impact are folded into the slippage multiples**
  rather than modelled as separate additive terms. For a single-lot retail
  FX position on H1 bars, market impact is not measurable and latency
  manifests as slippage; separate named terms would be false precision.
* **Swap / financing is not modelled.** Max hold is 12 H1 bars, so most
  trades never cross a rollover; those that do would incur an additional
  cost. **These results are therefore optimistic in this respect, not
  pessimistic.**

---

## 2. Scenario ladder

Declared in `cost_stress.py` before any scenario ran. Evaluated on
DEVELOPMENT + VALIDATION.

| Scenario | Trades | Net profit | Profit factor | Expectancy | Costs paid | Gross before costs |
|---|---|---|---|---|---|---|
| **ZERO_COST** *(diagnostic only)* | 633 | **−4,628.77** | **0.8855** | −7.31 | 0.00 | −4,628.77 |
| **BASE** | 646 | **−8,768.91** | **0.6856** | −13.57 | 5,996.46 | −2,772.46 |
| REALISTIC_SPREAD (×1.25) | 650 | −9,002.68 | 0.6663 | −13.85 | 6,571.18 | −2,431.50 |
| 1X_SLIPPAGE *(= BASE)* | 646 | −8,768.91 | 0.6856 | −13.57 | 5,996.46 | −2,772.46 |
| 2X_SLIPPAGE | 649 | −9,030.56 | 0.6618 | −13.92 | 6,461.01 | −2,569.54 |
| 3X_SLIPPAGE | 650 | −9,214.08 | 0.6409 | −14.18 | 6,898.52 | −2,315.56 |
| SPREAD_WIDENING_2X | 655 | −9,528.32 | 0.5928 | −14.55 | 7,417.75 | −2,110.57 |
| STRESSED (spread ×2, slippage ×3) | 658 | −9,739.43 | 0.5434 | −14.80 | 7,711.41 | −2,028.02 |

Trade counts vary slightly between scenarios because spread shifts the
entry price, which shifts the ATR-derived stop and target levels, which
changes exit timing and therefore when the next signal can be acted on.
This is real mechanical coupling, not noise.

---

## 3. The classification, and why it is the harsher one

`ZERO_COST_DEPENDENCY = NOT_COST_DEPENDENT`

The cost-stress phase exists mainly to catch a strategy that looks
profitable only because its costs were understated. `STRAT-000002` fails
a **different and more fundamental** test:

> **At zero cost — no spread, no slippage, no commission — the strategy
> still loses 4,628.77 with a profit factor of 0.8855.**

There is no cost assumption, however generous, under which this becomes
profitable, because the loss is not caused by costs. Costs make a losing
strategy lose roughly twice as much; they are not what makes it lose.

This distinction matters for what happens next. A `ZERO_COST_DEPENDENT`
result would say: *the signal has an edge too small to trade* — which
points toward a lower-cost venue, a longer horizon, or a larger edge in
the same family. `NOT_COST_DEPENDENT` says: *the signal has no edge at
all* — which points nowhere within this family.

### 3.1 Cost degradation is orderly, and irrelevant

| Scenario | Δ net vs BASE |
|---|---|
| ZERO_COST | +4,140.14 |
| REALISTIC_SPREAD | −233.77 |
| 2X_SLIPPAGE | −261.65 |
| 3X_SLIPPAGE | −445.17 |
| SPREAD_WIDENING_2X | −759.41 |
| STRESSED | −970.52 |

Degradation is monotonic and well-behaved across the ladder — the cost
model is working correctly. It simply has nothing to reveal, because the
sign of the result never changes.

### 3.2 Per-partition gross figures

| Partition | Gross before costs | Costs | Net |
|---|---|---|---|
| DEVELOPMENT | −3,024.22 | 5,249.41 | −8,273.63 |
| OOS (VALIDATION) | **+1,149.41** | 4,199.43 | −3,050.02 |
| PURE_HOLDOUT | −1,069.79 | 2,879.08 | −3,948.86 |

Only VALIDATION shows a positive gross figure, and it is **+7.32 per
trade against a cost of 26.75 per trade** — about a quarter of what would
be needed. On the other two partitions the gross figure is negative
outright.

---

## 4. Verdict

`COST_STRESS_STATUS = FAIL`.

Flagged under the Generation 4 contract's "a strategy that only works at
zero cost must be flagged" requirement — with the correction that this one
does not work at zero cost either.
