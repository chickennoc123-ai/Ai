# ML-001 — Generation 5, Phases 5-9: Trade Instrumentation & Findings

**Date**: August 19, 2026
**Subject**: forensic re-instrumentation of `STRAT-000002` (terminally `REJECTED`, unchanged)
**Status**: `INSTRUMENTATION_STATUS = CLOSED`, `TRADE_OBSERVABILITY_STATUS = OPERATIONAL`, `EXIT_ANALYSIS_STATUS = COMPLETE`, `MFE_MAE_STATUS = PARTIAL (reusable data only)`, `HOLDING_TIME_STATUS = COMPLETE`, `SIGNAL_EXECUTION_SEPARATION_STATUS = COMPLETE (reusable data only)`

This closes the Generation 4 post-mortem's instrumentation-debt finding: its central mechanical claim (realized reward:risk below nominal) was necessarily **derived algebraically** from aggregate profit_factor/win_rate, because no per-trade exit-reason distribution or MFE/MAE was ever persisted. This document reports the **direct per-trade measurement**.

---

## 1. Not a re-validation

`STRAT-000002` remains terminally `REJECTED`; `EDGE_STATUS = NO_EDGE_FOUND` is unchanged. `scripts/run_generation5_instrumentation.py` transitions no registry state and writes nothing to `reports/generation4/`. Non-Negotiable Principles 1-2 (do not modify or resurrect a rejected candidate) are respected by construction — nothing here can change the verdict, only measure it more precisely.

## 2. Instrumentation layer, and why it is a separate module

`core.economic_validation.instrumented_execution.execute_instrumented` reproduces `core.economic_validation.execution.execute`'s trades **exactly** — same next-bar-open fill, same-bar risk-trigger priority (`STOP_LOSS > TAKE_PROFIT > MAX_HOLDING_PERIOD`), same cost formula (reused, not reimplemented) — while additionally tracking Maximum Favourable/Adverse Excursion bar-by-bar during each open position. It is a **parallel, additive** layer, not a modification of `execution.py`: that module's output shape is pinned by `tests/test_generation4_integration.py::test_pure_holdout_result_reproduces_from_source`, which re-derives a committed Generation 4 checksum from a fresh call — adding fields to `ExecutedTrade.to_dict()` would break that reproducibility gate. Equivalence between the two engines is proven, not assumed: `tests/test_generation5_instrumentation.py::test_parity_with_execute` asserts entry/exit price/time, direction, size, exit_reason, holding_bars, pnl, gross_pnl, and cost_paid match exactly on real 2021 EURUSD H1 data.

## 3. PURE_HOLDOUT is treated differently — the holdout-once constraint

`PURE_HOLDOUT` has been consumed exactly once in this Factory's entire history (Generation 4; asserted by `tests/test_generation5_governance_closure.py::TestOGD1HoldoutOrderingIsSettled`). Re-sealing it — even read-only, even for diagnostics — would be a second access, forbidden by Non-Negotiable Principles 5-7. So for `PURE_HOLDOUT`, this instrumentation reads **only** the trade-level fields already committed in `reports/generation4/EVALUATION_PURE_HOLDOUT.json` (exit_reason, holding_bars, pnl — present from the one legitimate access) for exit-mechanism and holding-time analysis. MFE/MAE and signal-quality forward returns, which would require re-reading holdout price bars beyond the already-extracted trade records, are explicitly marked `NOT_COMPUTED` with the reason stated, never fabricated. `DEVELOPMENT_AND_VALIDATION` (reusable data, no such restriction) carries the full analysis.

## 4. Findings — exit mechanism (Phase 6)

| Partition | Trades | TAKE_PROFIT | STOP_LOSS | MAX_HOLDING_PERIOD |
|---|---|---|---|---|
| DEVELOPMENT+VALIDATION | 646 | 157 (24.3%) | 311 (48.1%) | 178 (27.6%) |
| PURE_HOLDOUT | 142 | 32 (22.5%) | 67 (47.2%) | 43 (30.3%) |

**Direct per-trade realized-R by exit reason** (DEVELOPMENT+VALIDATION, nominal RR = 2.0/1.5 = 1.333):

```
TAKE_PROFIT       n=157   mean realized_R = +1.29   (near nominal, small slippage cost)
STOP_LOSS         n=311   mean realized_R = -1.04   (slightly worse than nominal -1.0, slippage)
MAX_HOLDING_PERIOD n=178  mean realized_R = +0.13   (chopped to ~10% of the nominal target)
```

**`realized_reward_risk_measured` = mean(realized_R | win) / |mean(realized_R | loss)`:**

```
DEVELOPMENT_AND_VALIDATION: 76.46% of nominal (measured)  vs  77.1% (Generation 4 post-mortem, algebraic inference, frozen point)
PURE_HOLDOUT:                74.21% of nominal (measured)
```

**This is the direct confirmation the post-mortem's derivation-limits section called for.** The mechanism is now measured, not inferred: `MAX_HOLDING_PERIOD` exits realize only ~10% of the nominal target on average — the timer chops would-be winners into small partial outcomes while `STOP_LOSS` still fires at full nominal size, exactly the asymmetry the algebraic derivation predicted.

## 5. Findings — MFE/MAE (Phase 7, `DEVELOPMENT_AND_VALIDATION` only)

- MFE (in R-multiples of the initial stop distance): mean 0.799, median 0.616, p90 1.713.
- MAE: mean 0.942, median 0.955, p90 1.589.
- MFE/MAE correlation: −0.480 (trades that run further in their favour tend to see less adverse excursion, as expected for a mean-reverting-style entry).
- Loss classification (diagnostic only; **not used to retune the candidate** — Non-Negotiable rule): of 379 losing/timeout trades, 257 are `BAD_ENTRY` (never got meaningfully favourable), 84 `EXECUTION_DEGRADATION` (ran favourably, still stopped out), 32 `GOOD_ENTRY_BAD_EXIT` (ran favourably, timed out), 6 `BAD_ENTRY_BAD_EXIT`.

## 6. Findings — holding time (Phase 8)

Full distribution and bucketed win-rate/realized-R in `reports/generation5/HOLDING_TIME_{DEVELOPMENT_AND_VALIDATION,PURE_HOLDOUT}.json`. Consistent with §4: trades that reach the `13-24` and `25+` bar buckets are disproportionately `MAX_HOLDING_PERIOD` exits with suppressed realized-R.

## 7. Findings — signal vs execution separation (Phase 9, `DEVELOPMENT_AND_VALIDATION` only)

Independent, execution-free measurement: 12-bar forward return conditional on the entry signal firing, vs unconditional, over the full EURUSD H1 series (646 signals within the partition, computed against the full price history for the forward-return horizon).

```
conditional_mean_forward_return - unconditional_mean_forward_return = signal_edge = 0.0000954
round_trip_cost_as_return (spread + 2x slippage, as a fraction of price)  = ~0.000182  (materiality floor)
```

`signal_edge` is **smaller than the cost of trading it once** — the materiality floor this module requires before calling a positive number "edge" (Non-Negotiable Principle 11: statistical sign alone is not economic materiality). Classification: **`SIGNAL_FAILURE`**, not `EXECUTION_FAILURE` — the entry signal carries no economically material edge even before any stop/target/max-hold mechanics are applied. This directly confirms, by independent measurement, the Generation 4 post-mortem's finding at nominal RR 0.75 (where geometry erosion was minimal): "with the geometry problem removed, the signal still has no edge." `NO_SIGNAL` is the primary cause; `PARAMETER_FRAGILITY` (§4) is real but secondary, exactly as the post-mortem classified it — now confirmed by direct measurement on both counts, not inference on either.

## 8. Known limitation, disclosed

This replay covers only the frozen point's two Generation 4 partitions (`DEVELOPMENT_AND_VALIDATION`, `PURE_HOLDOUT`). It does not extend instrumentation to the 360-point robustness surface — that would require re-running `core.economic_validation.robustness.run_robustness` with the instrumented engine substituted in, which was out of scope for this generation's effort budget. A future generation wanting exit-reason distributions across the full robustness grid can build directly on `execute_instrumented`; the parity guarantee (§2) already extends to any parameter point, not just the frozen one.

## 9. Artifacts

`reports/generation5/{INSTRUMENTED_TRADES,EXIT_MECHANISM,MFE_MAE,HOLDING_TIME,SIGNAL_EXECUTION_SEPARATION}_{DEVELOPMENT_AND_VALIDATION,PURE_HOLDOUT}.json`, `GENERATION5_INSTRUMENTATION_SUMMARY.json`.
