# ML-001 — GENERATION 7, CYCLE 2: HORIZON / COST-AMPLIFICATION DISCOVERY

**Date**: 2026-08-19
**Branch**: `claude/ea-factory-pro-system-bc9jaa`
**Final state**: `NO_EDGE_FOUND_YET`

---

## Research question

> Does the same or related market structure become economically tradable when the
> holding horizon is extended so that fixed transaction costs become a smaller
> fraction of expected movement?

**Answer: no — not on this instrument, this window, with a single-symbol search.**
The premise is *structurally* true (cost-efficiency does rise with horizon), but the
same mechanism that produces it destroys the statistical power needed to trust any
resulting estimate. See §4.

---

## 1. Phase 0 — state verification

| Check | Result |
|---|---|
| Sealed holdout (`DS-HOLDOUT-EURUSD-H1-HISTDATA-20240101-20260130`) | **SEALED**, 0 authorizations, 0 consumptions |
| PURE_HOLDOUT | Consumed exactly once (`LEDGER-00000028`, dataset `DATASET-EURUSD-H1-KOMO135-V1`), terminal |
| OGD-4 | Unchanged since commit `3f9bd62` |
| Failure library | 22 records available at cycle start |
| GEN 12/13/14 gates | Operational, validated against planted synthetic edges (16 tests) |
| Holdout observation exposure | None — `discovery/_guards.py` blocks any path containing "holdout" |
| Candidate resurrection | None — cycle-1's 8 hypotheses cross-checked, none silently reintroduced |

**Gap found and fixed before research began**: no cumulative multiple-testing ledger
existed. Cycle-1's `discovery_queue.json` / `hypothesis_evaluation.json` would have
been **silently overwritten** by any re-run, destroying provenance and making "never
reset counters" impossible to honor mechanically. Fixed by archiving cycle-1 outputs
to `reports/factory/discovery_cycles/cycle_01_*.json` (now read-only history) and
building `discovery/ledger.py` — append-only, raises on any attempt to re-record a
cycle_id, no delete/reset method exists on the class.

---

## 2. Phase 1 — research memory

Extracted from the failure library (read-only) into
`reports/factory/research_memory_summary.json` (10 rows, `FAMILY | OBSERVATION |
RESULT | FAILURE_MODE | KNOWN_LIMIT | UNEXPLORED_REGION`). Highlights:

- **RSI_OVERSOLD_MEAN_REVERSION** — refuted family (HYP-000001/2/3, STRAT-000001/2).
  Firewalled; cycle 2 generated zero RSI-threshold hypotheses.
- **COST_AMORTIZATION** (cycle-1's weekend-gap-fade-with-larger-target attempt) —
  n=130, t=0.99: **underpowered, not unprofitable**. Correctly flagged as the region
  to test with more n, not more horizon variants.
- Every cycle-1 1-bar-horizon family was **cost-dominated** (gross positive, net
  negative) — this is precisely what motivated the horizon-expansion mandate.

*(This process caught its own bug: the first draft of the extraction script
re-committed the exact "underpowered mislabeled as negative" mistake corrected in
cycle 1 — FAIL-000015/FAIL-000022. Fixed before the summary was saved; see the
module's `underpowered` branch in `discovery/research_memory.py`.)*

---

## 3. Phases 2–3 — horizon sweep

**5 structurally distinct families**, swept across **9 horizons** (2/4/8/12/24/48/72/
120/240 bars) = **243 (family × params × horizon) evaluations**, all on the same
train (80%, 2012-11→2020-04) / internal-validation (reserved 20%, 2020-04→2022-03)
split used in cycle 1. Same frozen 1.1-pip roundtrip cost, unchanged.

| Family | Mechanism | Structural variants |
|---|---|---|
| A. STREAK_REVERSAL_MULTIBAR | multi-bar streak exhaustion, vol-gated | k∈{2,3,4,6} × vol_gated |
| B. GAP_MAGNITUDE_STRUCTURE | weekend gap: fade vs continuation, by size | 2 modes × 3 magnitude buckets |
| C. VOLATILITY_TRANSITION | compression-breakout trigger; shock momentum/reversal | 1 + (2 z-thresholds × 2 modes) |
| D. BREAKOUT_STRUCTURE | N-bar range breakout: continuation vs reversal | 3 lookbacks × 2 modes |
| E. MULTITIMEFRAME_TREND_FILTER | D1-trend-aligned vs counter-trend streak fade | 2 alignments |

### Gate distribution (all 243 evaluations)

| Gate | Count |
|---|---|
| `KILLED_NEGATIVE_EXPECTANCY` | 96 |
| `KILLED_UNDERPOWERED` | 87 |
| `ECONOMICALLY_UNTRADABLE` (gross+, net−) | 55 |
| `VAL_FAIL_NEGATIVE` (train passed, val sign-flipped) | 3 |
| `VAL_FAIL_UNDERPOWERED` (train passed, val too weak) | 2 |
| **`PASS_TRAIN_AND_VAL`** | **0** |

---

## 4. Phase 4 — economic filter: the core finding

Mean train **cost-efficiency** (`|gross expectancy| / cost`) by family and horizon:

| Family | h=2 | h=4 | h=8 | h=12 | h=24 | h=48 | h=72 | h=120 | h=240 |
|---|---|---|---|---|---|---|---|---|---|
| STREAK_REVERSAL_MULTIBAR | 0.4 | 0.8 | 1.2 | 2.0 | 1.6 | 1.6 | 2.9 | 8.3 | 8.6 |
| GAP_MAGNITUDE_STRUCTURE | 1.2 | 0.8 | 1.0 | 1.2 | 2.4 | 7.2 | 9.9 | 20.5 | **25.0** |
| VOLATILITY_TRANSITION | 0.1 | 0.5 | 0.4 | 0.5 | 0.6 | 1.9 | 4.1 | 1.0 | 14.9 |
| BREAKOUT_STRUCTURE | 0.4 | 0.9 | 0.9 | 1.2 | 0.8 | 2.4 | 3.6 | 3.8 | 14.3 |
| MULTITIMEFRAME_TREND_FILTER | 0.4 | 0.8 | 0.9 | 1.6 | 1.5 | 1.0 | 2.2 | 3.5 | 9.9 |

**The premise is confirmed structurally**: cost-efficiency rises with horizon in
every family, roughly consistent with gross-movement scaling faster than a fixed
cost. But **trade count falls in the same direction** (non-overlapping positional
trades: fewer fit in a fixed window as horizon grows), so **statistical power
collapses exactly where cost-efficiency improves**.

The 5 evaluations that cleared the train gate (t≥2.0) all did so at horizon≥12, and
**none replicated**:

| Family | Params | Train net (t) | Validation net (t) |
|---|---|---|---|
| STREAK_REVERSAL_MULTIBAR | k=3, h=24 | +0.000296 (2.2) | +0.000047 (0.24) — underpowered |
| STREAK_REVERSAL_MULTIBAR | k=4, h=12 | +0.000183 (2.1) | −0.000070 (−0.49) — **sign-flip** |
| STREAK_REVERSAL_MULTIBAR | k=6, h=120 | +0.001974 (2.7) | −0.000858 (−0.72) — **sign-flip** |
| VOLATILITY_TRANSITION shock-momentum | z=2.0, h=240 | +0.002181 (2.0) | +0.001502 (0.87) — underpowered (n=45) |
| BREAKOUT_STRUCTURE reversal | lb=10, h=240 | +0.002855 (2.7) | −0.001927 (−1.08) — **sign-flip** |

No hypothesis is renamed as a near-success. All 5 are `TRAIN_FAIL`-adjacent failures
recorded honestly.

---

## 5. Phase 5 — multiple-testing accounting (cumulative, never reset)

```
cycle_count:                       2
cumulative_hypotheses_generated:  15   (cycle 1: 8, cycle 2: 7)
cumulative_parameter_evaluations: 251  (cycle 1: 8, cycle 2: 243)
cumulative_survivors:              0
families_ever_touched:            11
```

Persisted in `reports/factory/multiple_testing_ledger.json`. Cycle 1's 8 evaluations
were **not excluded** from this cycle's accounting; the ledger's `record_cycle()`
raises `ValueError` on any attempt to re-record an existing `cycle_id`, so a cycle
cannot be silently re-run to "improve" its numbers.

---

## 6. Phase 6 — novelty classification

| Family / mechanism | Classification | Why |
|---|---|---|
| STREAK_REVERSAL_MULTIBAR | `HORIZON_VARIANT` | same mechanism as cycle-1 OP-STREAK-REVERSAL/OP-COST-AMORTIZED, k=6 and full horizon sweep added |
| GAP_MAGNITUDE_STRUCTURE (FADE) | `HORIZON_VARIANT` | same mechanism as cycle-1 OP-EVENT-SEQUENCE/OP-COST-AMORTIZED, magnitude-bucketed and horizon-swept |
| GAP_MAGNITUDE_STRUCTURE (CONTINUATION) | `NEW_MECHANISM` | opposite economic claim (gaps trend, not revert) — never tested |
| VOLATILITY_TRANSITION (compression→breakout trigger) | `NEW_MECHANISM` | cycle 1 used the same state only as a no-trade filter; here it is the entry trigger |
| VOLATILITY_TRANSITION (shock momentum/reversal) | `NEW_FAMILY` | cycle-1 GEN 8 only observed this; never graduated to a tested hypothesis |
| BREAKOUT_STRUCTURE | `NEW_FAMILY` | breakout existed only as the ablation subject in cycle 1; never evaluated as its own hypothesis |
| MULTITIMEFRAME_TREND_FILTER | `NEW_FAMILY` | no cross-timeframe mechanism existed before |

Only `NEW_FAMILY`/`NEW_MECHANISM` entries carry full discovery priority; none of the
`HORIZON_VARIANT` results were used to inflate the survivor count.

---

## 7. Phase 7 — early destruction

| Reason | Count |
|---|---|
| Insufficient sample (n<30) | included in `KILLED_INSUFFICIENT_SAMPLE` |
| Negative expectancy (train) | 96 |
| Cost-dominated (cost_efficiency<1, still net-negative) | included above |
| `ECONOMICALLY_UNTRADABLE` (gross+, net−; never counted as success) | 55 |
| Underpowered (t<2.0 despite net>0) | 87 |

No candidate consumed GEN 12/13/14 budget on an obviously weak signal — all
destruction happened at the cheap train-gate stage.

---

## 8. Phase 8 — survivor identification

**0 `DISCOVERY_SURVIVOR`s.** The 5-criteria bar (economically positive after cost,
sufficient n, persists across subperiods, not single-parameter-dependent, no known
failure-family contamination) was never reached — every train-gate pass failed the
prior, cheaper validation gate. No candidate is called `EDGE`; none reached even
`DISCOVERY_SURVIVOR`.

---

## 9. Phase 9 — GEN 12 handoff

**Not invoked.** Zero survivors exist; Phase 9 explicitly prohibits artificial
advancement. The sealed holdout was not read, authorized, or consumed at any point
in this cycle (re-verified after all 243 evaluations — still `sealed`, 0/0).

---

## 10. Phase 10 — failure memory (6 new records, 28 total)

| ID | Scope | Reusable lesson |
|---|---|---|
| FAIL-000023 | STREAK_REVERSAL_MULTIBAR | streak-exhaustion train edge does not survive horizon extension out-of-sample |
| FAIL-000024 | GAP_MAGNITUDE_STRUCTURE | MEDIUM bucket (8–15 pips) is the best cost-efficiency sub-family but n=47 caps it — needs pooled instruments, not more horizons |
| FAIL-000025 | VOLATILITY_TRANSITION | shock-momentum signal only emerges at horizons where n is already too small |
| FAIL-000026 | BREAKOUT_STRUCTURE | 10-bar breakout-reversal has the 2nd-best train signature in the whole sweep and still fails validation — consistent with an arbitraged-away pattern |
| FAIL-000027 | MULTITIMEFRAME_TREND_FILTER | D1-trend conditioning (24-bar SMA slope) does not rescue streak-fade |
| **FAIL-000028** | **META** (cross-family) | **cost-efficiency and statistical power move in opposite directions as horizon grows on a single instrument — horizon extension relocates the cost problem into a power problem, it does not resolve it alone** |

---

## 11. Search-space region eliminated

With high-quality evidence (243 evaluations, honest gates, no relaxed thresholds),
this cycle eliminates: **short-to-long-horizon extensions of streak-reversal,
gap-fade, volatility-transition, breakout, and simple D1-trend-filtered signals, on
single-instrument EURUSD H1, as a route to a cost-amortized edge.** This is a
genuine, evidence-based result (Phase 11 success condition B), not a null result
from under-searching.

---

## 12. What this rules in for cycle 3

`FAIL-000028`'s prevention rule is actionable: **project achievable n at each
horizon before spending evaluation budget on it** — this sweep would have
pre-rejected horizon≥120 for every family, saving ~1/3 of this cycle's budget for
better-targeted tests. Two structurally different paths remain untried:

1. **Multi-instrument pooling** — decouples n from horizon (GBPUSD dev data exists
   in-repo and is currently used only for GEN 12 symbol-shift checks).
2. **Higher-frequency, higher-magnitude signal** — an instrument where per-bar range
   is a larger multiple of spread, so short horizons already clear cost-efficiency
   without destroying n.

---

## Final governance status

```
GENERATION_7_CYCLE_2_STATE       = NO_EDGE_FOUND_YET
HYPOTHESES_GENERATED_THIS_CYCLE  = 7 (structural families/mechanisms)
PARAMETER_EVALUATIONS_THIS_CYCLE = 243
CUMULATIVE_HYPOTHESES            = 15
CUMULATIVE_PARAMETER_EVALUATIONS = 251
CUMULATIVE_SURVIVORS             = 0
DISCOVERY_SURVIVORS_THIS_CYCLE   = 0
CANDIDATES_FORWARDED_TO_GEN12    = 0
SEALED_HOLDOUT_STATUS            = SEALED, 0 authorizations, 0 consumptions
PURE_HOLDOUT_STATUS              = terminal, consumed exactly once (unchanged)
OGD4_STATUS                      = UNCHANGED
FAILURE_LIBRARY_SIZE             = 28 (+6 this cycle)
STRAT_000003_STATUS              = NOT CREATED
TEST_COUNT                       = 1175 passed (1145 prior + 30 new), 0 failed
```

## Reproduction

```bash
python3 -m discovery.research_memory     # Phase 1 (read-only over failure library)
python3 -m discovery.cycle2_horizon      # Phases 2-3 (prints summary; use run_sweep() for full data)
python3 -m pytest tests/test_gen7_cycle2.py -q
python3 -m pytest tests/ -q
```

No randomness anywhere. Identical inputs produce byte-identical sweep results.
