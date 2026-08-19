# ML-001 — Generation 4 Post-Mortem: why STRAT-000002 failed

**Date**: August 19, 2026
**Subject**: `STRAT-000002` — terminally `REJECTED`, EVG verdict `FAIL`, `EDGE_STATUS = NO_EDGE_FOUND`
**Purpose**: explain the failure and extract transferable knowledge. **Not** a re-evaluation: no candidate was re-run, re-tuned, or re-parameterised, and no economic number in `reports/generation4/` was recomputed or altered. Every figure below is read from the committed G4 artifacts; the one derived quantity (§3) is stated with its derivation and its limits.

---

## 1. What the candidate actually was

From `reports/generation4/PARSED_RULE.json` — the frozen, executed specification:

| | |
|---|---|
| Entry | `rsi_14` crosses **up** through 30 (oversold exit), long only |
| Stop / target | 1.5 × ATR / 2.0 × ATR — nominal reward:risk **1.33 : 1** |
| Max holding | **12 bars** |
| Risk | 2% per trade, 1 position |
| Market | EURUSD H1 |
| Lineage | `SRC2-000001` (je-suis-tm/quant-trading README, Apache-2.0, checksummed) → `CLAIM-000001` (verbatim RSI 70/30 lore) → `HYP-000001` → `STRAT-000002` |

## 2. The result: negative everywhere, on every partition and every parameter point

| Partition | Trades | Win rate | Profit factor | Expectancy | Sharpe |
|---|---|---|---|---|---|
| DEVELOPMENT | 488 | 40.16% | 0.673 | −16.95 | −1.53 |
| VALIDATION (OOS) | 157 | 44.59% | 0.793 | −19.43 | −0.95 |
| **PURE_HOLDOUT** | 142 | 40.85% | **0.653** | **−27.81** | −1.40 |

Supporting evidence, all from the committed artifacts:

- **Walk-forward**: 90 windows, only **35.6%** net-positive, total **−18,557.81**, concentration `DISTRIBUTED` — not one bad window dragging an otherwise-working strategy down.
- **Robustness surface**: **360** parameter points. **0 net positive. 0 with PF > 1.** Best PF anywhere on the surface **0.861**; median 0.703; `viable_region: NONE`. The frozen point sat at the 43.6th percentile of its own surface — unremarkable, neither cherry-picked nor unluckily chosen.
- **Cost stress**: `NOT_COST_DEPENDENT` — unprofitable **with all execution costs removed**. Costs are not what killed it.
- **Statistics**: holdout expectancy 95% block-bootstrap CI **[−45.22, −6.00]**, does not straddle zero. The loss is statistically real, not noise.
- **Multiple testing**: observed Sharpe is negative, so the correction has nothing to correct; G4's own artifact says the 2-trial correction is *"NEARLY_UNINFORMATIVE"* — a candidate passing it would not thereby have survived multiplicity scrutiny. That honesty is preserved, not upgraded.

**This is a decisively stronger refutation than `STRAT-000001`'s.** STRAT-000001 failed with *no predictive signal* (IC ≈ 0.015–0.030, ~51% directional accuracy — a coin flip). STRAT-000002 failed with *reliably negative expectancy across an entire 360-point parameter surface*. The first was "we found nothing"; this is "we found something, and it points the wrong way."

## 3. Root cause — two distinct, separable causes

A naive reading says: win rate 41.3% vs. a 42.9% breakeven for 1.33:1 geometry — missed by only 1.6 points, nearly viable. That reading is **wrong**, and the robustness surface shows why.

**Cause A — the entry signal has no edge.** Necessary but not sufficient to explain the magnitude on its own.

**Cause B — realized payoff geometry is systematically worse than nominal.** Derived across all 360 points from each point's own `profit_factor` and `win_rate` via `realized_RR = PF × (1−wr) / wr`:

| Nominal reward:risk | Realized, as % of nominal |
|---|---|
| 0.75 | 99.7% |
| 1.00 | 87.7% |
| 1.33 (**frozen point**) | 77.1% |
| 2.00 | 62.3% |
| 3.00 | **53.1%** |

| Max holding cap | Realized, as % of nominal |
|---|---|
| 6 bars | 64.2% |
| 12 bars (**frozen point**) | 72.8% |
| 24 bars | 85.0% |

Across the whole surface: median **76%** of nominal; only **15/360** points reach ≥100%.

**Mechanism.** A distant take-profit needs both *time* and a *favourable path*. The max-holding-bar timer truncates would-be winners into small or partial outcomes, while the nearer stop-loss still fires at full size. The more ambitious the target and the tighter the clock, the wider the gap — exactly the monotone pattern in both tables.

**Consequence, quantified at the frozen point:**

```
nominal reward:risk  1.33  ->  breakeven win rate  42.9%
realized reward:risk 0.97  ->  breakeven win rate  50.7%   (the bar that actually applied)
observed win rate                                  41.3%
```

So the signal missed its *nominal* bar by 1.6 points and its *realized* bar by **9.4** points. Geometry erosion raised the bar ~7.8 points; the signal then failed to clear even the original one. **A marginal miss became a decisive one.**

That both causes are genuinely present is confirmed by the one place they separate: at nominal RR 0.75, realized ≈ nominal (99.7%), so geometry erosion is essentially absent — and PF there is still ≈ 0.69, with win rates ~45.6–46.4% against a ~57.2% requirement. **With the geometry problem removed, the signal still has no edge.** Neither cause alone explains the result; both are real.

**Derivation limits, stated plainly.** `realized_RR = PF × (1−wr) / wr` is exact given a point's profit factor and win rate, but it is an inference from *aggregates* — the artifacts do not carry per-trade `avg_win`/`avg_loss`, so this is not a direct measurement, and it cannot decompose *which* exit (timeout vs. stop vs. target) contributed how much. Confirming the mechanism directly would require exit-reason distributions per parameter point, which Generation 4 did not persist. Recorded as a Generation 5 instrumentation requirement (§6), not asserted as though already measured.

## 4. Failure classification

| Category | Verdict | Basis |
|---|---|---|
| `NO_SIGNAL` | **PRIMARY** | signal fails its breakeven bar even where geometry erosion is absent |
| `PARAMETER_FRAGILITY` | **PRIMARY (mechanical)** | realized-vs-nominal geometry gap, monotone in target width and holding cap, present across all 360 points |
| `NEGATIVE_EXPECTANCY` | CONFIRMED | all three partitions negative; holdout CI excludes zero |
| `COST_SENSITIVITY` | **RULED OUT** | `NOT_COST_DEPENDENT` — unprofitable at zero cost |
| `OOS_DECAY` | **RULED OUT** | not a decay pattern — DEVELOPMENT was already the second-worst partition |
| `LEAKAGE` / `TEMPORAL_INVALIDITY` | **RULED OUT** | feature temporal safety PASS, target leakage audit PASS |
| `INSUFFICIENT_HISTORY` / `STATISTICAL_FAILURE` (as *insufficiency*) | **RULED OUT** | 646 trades, `SUFFICIENT`; the negative result is statistically significant |

## 5. Epistemic chain closed

Generation 4 rejected the candidate but left the chain above it open — `HYP-000001` still `ELIGIBLE`, `CLAIM-000001` still `FORMALIZED` — despite the hypothesis's **pre-registered** falsification condition being met outright. Closed here on its own stated terms (not reinterpreted): `HYP-000001` → `REFUTED` (evidence level `CANDIDATE_TESTED_NO_EDGE`), `CLAIM-000001` → `REFUTED`, both with evidence references and ledger events. Full reasoning: `ML-001-GENERATION-5-GOVERNANCE-CLOSURE.md` §3.

**Scope**: what is refuted is the *tested operationalisation* — EURUSD H1, 12-bar horizon, frozen cost model. The source stated no instrument, timeframe, horizon, or cost model; other operationalisations remain untested, and the claim's verbatim text is unchanged.

## 6. Knowledge extracted (Failure Library, `reports/factory/failure_library.json`)

Eleven records now, up from eight. The three added by this post-mortem:

1. **`HYP-000001` / `HOLDOUT` / `NEGATIVE_EXPECTANCY`** — hypothesis-level refutation with the pre-registered condition and the numbers that met it.
2. **`CLAIM-000001` / `HOLDOUT` / `NO_SIGNAL`** — source-claim level: 41.3% delivered where 50.7% was required.
3. **`STRAT-000002` / `ROBUSTNESS` / `PARAMETER_FRAGILITY`** — **the transferable one.** Applies to *any* future candidate in this Factory using ATR-multiple take-profits with a max-holding cap, regardless of entry signal. Carries the full table, the mechanism, and the derivation caveat.

**Generation 5 instrumentation requirement** arising from §3's limits: persist per-parameter-point **exit-reason distributions** (target / stop / timeout / reversal) and per-trade `avg_win`/`avg_loss`, so the realized-vs-nominal gap can be *measured* rather than inferred.

## 7. What this post-mortem did not do

Did not re-run, re-tune, or re-parameterise anything; did not alter any G4 artifact or checksum; did not re-open `PURE_HOLDOUT` (consumed exactly once in the Factory's history, asserted by test); did not soften `NO_EDGE_FOUND` or upgrade any status.
