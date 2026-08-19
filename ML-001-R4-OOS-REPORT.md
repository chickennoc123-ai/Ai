# ML-001-R4 — Out-of-Sample Report

**Phase:** Generation 4, Phase 13
**Run:** `G4RUN-STRAT-000002-6b1c63d014d4a7be`
**Artifact:** `reports/generation4/EVALUATION_OOS.json`
**Verdict:** `OOS_STATUS = FAIL`

---

## 1. What "out-of-sample" means for a zero-parameter rule

Worth stating precisely, because the usual meaning does not quite apply.

Ordinarily OOS means "data the model was not fitted on". `STRAT-000002`
fits nothing — its RSI threshold, ATR multiples and holding period are
fixed constants in the frozen specification, taken from a public source
claim before any of this data was examined. In that strict sense *every*
partition is out-of-sample.

What the VALIDATION partition provides is still meaningful, and it is a
different thing: it is data that played **no role in the research process
that produced the candidate**, evaluated under a specification frozen
before the partition was opened. That is the property that makes it
evidence rather than description.

---

## 2. Protocol

| Field | Value |
|---|---|
| OOS partition | VALIDATION |
| Period | **2018-06-20 00:00 → 2020-04-29 15:00 UTC** |
| Bars | 11,520 |
| Structurally distinct from | DEVELOPMENT (2012-11-16 → 2018-06-19) |
| Warmup context | DEVELOPMENT tail — strictly prior bars only |
| Dataset checksum | `94400954ab8a91c7…` |
| Candidate checksum | `f38087385217026c…` |
| Cost model | BASE (1.6 pip spread, 0.2 pip slippage both legs, 7.00/lot commission) |
| Parameter changes made on the basis of this result | **none** |

The evaluation window begins exactly at the VALIDATION boundary. Bars
before it are used only to warm up features; no signal before
`2018-06-20 00:00` is acted on, and `evaluate_partition` raises if the
context frame were ever to extend past the evaluation window — the
direction of the relationship that *would* be leakage.

---

## 3. Results

| Metric | Value |
|---|---|
| **Trade count** | **157** |
| Profitable trades | 70 |
| Losing trades | 87 |
| Gross profit | 11,662.94 |
| Gross loss | 14,712.95 |
| **Net profit** | **−3,050.02** |
| **Profit factor** | **0.7927** |
| **Win rate** | **44.59%** |
| **Expectancy per trade** | **−19.43** |
| Average win | +166.61 |
| Average loss | −169.11 |
| Largest win | +266.67 |
| Largest loss | −227.21 |
| Sharpe (annualised) | −0.9513 |
| Sortino | −0.4126 |
| Max drawdown | 4,006.46 (37.43%) |
| Max drawdown duration | 7,628 bars |
| Recovery factor | −0.7613 |
| Longest losing streak | 9 |
| Turnover | 155.53 lots |
| Exposure | 9.84% of bars |
| Total costs paid | 4,199.43 |
| **Gross P&L before costs** | **+1,149.41** |

### 3.1 Exit reasons

| Reason | Count |
|---|---|
| `STOP_LOSS` | 75 |
| `TAKE_PROFIT` | 43 |
| `MAX_HOLDING_PERIOD` | 39 |

---

## 4. The one partition where costs are the whole story

The VALIDATION partition is the only one of the three where gross P&L
before costs is **positive** (+1,149.41), and it is worth being precise
about how little that means.

* Gross before costs: **+1,149.41** over 157 trades — roughly **+7.32 per
  trade**, on a EURUSD position sized to risk 2% of equity.
* Costs paid: **4,199.43** — roughly **26.75 per trade**.
* Net: **−3,050.02**.

The gross edge, such as it is, is about **27% of the size of the execution
cost required to capture it**. A strategy needs its gross edge to exceed
its costs by a comfortable margin to be viable; this one covers about a
quarter of them.

And this is the *favourable* partition. On DEVELOPMENT and PURE_HOLDOUT
the gross figure is negative outright (−3,024.22 and −1,069.79), meaning
the rule loses money before any cost is applied at all. The combined
reusable-data ZERO_COST scenario is likewise negative (−4,628.77, profit
factor 0.8855).

So the honest reading is not "the edge exists but is eaten by costs". It
is: **there is no reliable gross edge, and on the one partition where the
gross sign happened to come out positive, it was a quarter of what would
have been needed.**

---

## 5. Comparison across partitions

| Partition | Trades | PF | Win rate | Expectancy | Net | Gross before costs |
|---|---|---|---|---|---|---|
| DEVELOPMENT | 488 | 0.6727 | 40.16% | −16.95 | −8,273.63 | −3,024.22 |
| **OOS (VALIDATION)** | **157** | **0.7927** | **44.59%** | **−19.43** | **−3,050.02** | **+1,149.41** |
| PURE_HOLDOUT | 142 | 0.6534 | 40.85% | −27.81 | −3,948.86 | −1,069.79 |

OOS is the best of the three by profit factor and the worst but one by
expectancy — the ordering is noise around a consistently negative result,
not a trend.

---

## 6. Verdict

`OOS_STATUS = FAIL`.

Profit factor 0.7927 < 1 on 157 trades, a sample size sufficient for a
resampled interval. The result is consistent in sign with both other
partitions.

**No parameter, threshold, feature, cost assumption or window was changed
on the basis of this result.** The candidate proceeded to walk-forward,
robustness, cost stress, statistics and multiple-testing accounting under
the identical frozen specification.
