# ML-001 — AGLE STRATEGY FACTORY: COMPLETION REPORT

**Date**: 2026-08-20
**Terminal outcome**: `NO_EDGE_FOUND` (Cycle 3)
**Sealed holdout**: `SEALED_UNCONSUMED` — never opened
**Tests**: 1216 passing

---

## 1. The headline

The factory is complete and runs end-to-end: GEN 7 → GEN 9-11 → GEN 12 →
GEN 13 → GEN 14 → EA packaging (MT5 / MT4 / Pine).

It produced **no edge candidate**. Of 43 Cycle 3 hypotheses across 6
instruments, **0 cleared the pre-registered internal-validation gates** on
development data. No candidate was frozen, no GEN 14 authorization was issued,
and the sealed holdout was not touched.

`NO_EDGE_FOUND` is the honest result. No gate was relaxed to manufacture a
survivor — and one gate was **tightened** when it turned out to be defective
(§3).

---

## 2. What was built in this session

| Component | File | Role |
|---|---|---|
| Per-symbol cost model | `discovery/cost_model.py` | Frozen relative round-trip cost per instrument |
| Cycle 3 evaluation | `discovery/cycle3_evaluation.py` | GEN 9-11 on 6 symbols, dev data only |
| Sealed-holdout door | `qualification/holdout_access.py` | The single audited path to reserved data |
| GEN 14 qualification | `qualification/gen14_runner.py` | 5 pre-registered gates, terminal verdict |
| EA generator | `ea_generator/generator.py` | MQL5 / MQL4 / Pine, PASS-only |
| Pipeline orchestrator | `factory_pipeline.py` | End-to-end run, emits the terminal outcome |
| E2E governance tests | `tests/test_factory_pipeline_e2e.py` | 21 tests |

### The cost model was the prerequisite

Cycles 1–2 ran on EURUSD alone with a frozen **price-terms** cost of 0.00011
(1.1 pips). Every executor measures gross as a **log return**, so an absolute
price cost is meaningless once USDJPY (~150) and XAUUSD (~3000) enter. The
translation to relative terms was fixed and frozen **before** any Cycle 3
evaluation ran, with EURUSD pinned so results stay comparable:

| Symbol | Relative round trip | Basis |
|---|---|---|
| EURUSD | 1.00e-4 | 1.1 pips @ 1.10 — pinned to Cycles 1-2 |
| GBPUSD | 1.20e-4 | 1.5 pips @ 1.30 |
| USDCAD | 1.40e-4 | 1.9 pips @ 1.35 |
| USDCHF | 1.90e-4 | 1.7 pips @ 0.90 |
| USDJPY | 1.00e-4 | 1.4 pips @ 145 |
| XAUUSD | 2.00e-4 | ~$0.55 @ ~$2750 |

Raising a cost is always permitted. **Lowering any value after a candidate has
been evaluated against it is a governance violation.**

---

## 3. A defective gate, found and tightened

The first Cycle 3 run reported **3 survivors** (GBPUSD, USDCHF, USDJPY — all
the same NR7 state-filter ablation). They were not edges.

```
GBPUSD  train  base     n=15524  mean_net=-0.0001678  t=-16.54
        train  filtered n=14915  mean_net=-0.0001675  t=-16.00
```

Both variants **lose ~17 bp per trade**. The filter improved expectancy by
0.03 bp — so the ablation branch called it a survivor. That branch checked only
`improvement > 0`; it never checked that the filtered strategy was profitable,
never applied a t-statistic, never applied a sample floor. Every *other*
hypothesis faced `n≥30, net>0, train t≥2.0, val t≥1.5`.

**A filter that makes a losing strategy lose slightly less is not an edge.**

The ablation branch now applies the same pre-registered standard as everything
else, in both `discovery/cycle3_evaluation.py` and `discovery/evaluation.py`.
Under the corrected gate: **0 survivors**.

**Disclosure**: the 3 survivors were observed *before* the gate was tightened.
This is recorded deliberately. The change moves the gate **toward** the
pre-registered standard, never away from it — the opposite direction from
p-hacking. Cycle 1 (the only prior cycle using this branch) had 0 survivors, so
no historical result changes.

---

## 4. Cycle 3 result

```
43 hypotheses · 61 parameter evaluations · 0 survivors

EURUSD  cost=1.00e-04  REFUTED_INTERNAL=1  TRAIN_FAIL=7
GBPUSD  cost=1.20e-04  REFUTED_INTERNAL=1  TRAIN_FAIL=6
USDCAD  cost=1.40e-04  REFUTED_INTERNAL=1  TRAIN_FAIL=6
USDCHF  cost=1.90e-04  REFUTED_INTERNAL=1  TRAIN_FAIL=6
USDJPY  cost=1.00e-04  REFUTED_INTERNAL=1  TRAIN_FAIL=6
XAUUSD  cost=2.00e-04  REFUTED_INTERNAL=1  TRAIN_FAIL=6
```

Cumulative multiple-testing ledger (append-only, never reset):

| | Hypotheses | Parameter evaluations | Survivors |
|---|---|---|---|
| CYCLE-01 | 8 | 8 | 0 |
| CYCLE-02 | 7 | 243 | 0 |
| CYCLE-3-MULTIASSET | 43 | 0 | 0 |
| CYCLE-3-MULTIASSET-EVAL | 0 | 61 | 0 |
| **Cumulative** | **58** | **312** | **0** |

### The mechanism behind the failure (FAIL-000029)

Every H1 price pattern the observatory found is **smaller than the round-trip
cost on every instrument tested**. Widening the cross-section from 1 to 6
instruments multiplied the sample but did not change the sign of net
expectancy. The **cost floor, not sample size, is the binding constraint**.

**Prevention rule recorded**: do not re-test single-instrument H1 price-pattern
families by adding more instruments. Cross-sectional breadth does not defeat a
cost floor; only a larger gross effect or a lower cost does.

---

## 5. GEN 14: the door that stayed shut

Five pre-registered gates, all required:

| Gate | Threshold |
|---|---|
| G1 sample floor | n ≥ 30 |
| G2 expectancy | mean_net > 0 |
| G3 significance | t ≥ 2.0 |
| G4 profit factor | ≥ 1.10 |
| G5 multiple testing | p < 0.05 / M, **M = 312 cumulative** |

G5 uses the *cumulative* denominator across all factory history — not the
current cycle's count. At M=312 the required p is **1.6e-4**, roughly t ≥ 3.8.

Four preconditions guard the door, checked before a byte is read: spec frozen,
authorization issued, spec hash still matching, no terminal result recorded.
A FAIL is **terminal** — no retuning, no retest, ever.

Failure memory is filtered through `governance_safe_failure_note()`, which
keeps the mechanism and the failed gate name and **drops every holdout
statistic** — n, expectancy, t, profit factor, p-value, window boundaries.
Those are exactly the quantities an optimizer would hill-climb against. A test
asserts no such value can appear in a failure record.

---

## 6. The EA generator

Emits MQL5, MQL4, and Pine Script from a frozen spec, plus a manifest carrying
the spec hash. Supports the four frameworks GEN 7 actually produces:
`streak_fade`, `gap_fade`, `breakout`, `hour_drift`. Generated code includes
ATR-based position sizing, bar-close decisions, stop/target, and horizon exit.

**It refuses to package** a candidate that is unregistered, unfrozen, has no
GEN 14 result, or carries `FAIL`. Four tests assert each refusal.

`artifacts/ea/` is **empty** — the correct state, because nothing qualified.
`artifacts/ea_demo/` holds output from a clearly-labelled synthetic candidate
(`DEMO-SYNTHETIC-NOT-TRADABLE`) to show the emitted shape. Its README states
plainly that it is not a strategy and must not be traded.

---

## 7. Test coverage

**1216 passing.** New this session: 21 E2E governance tests covering GEN 14
access preconditions, qualification verdicts, cumulative multiple-testing
denominator, terminal failure (no reopen, no retune), failure-memory leak
prevention, EA generation across all four frameworks, all four packaging
refusals, and assertions that the production holdout registry is still empty.

---

## 8. Where the search should go next

The cost floor is the binding constraint, so the next cycle must change the
**economics**, not the sample:

1. **Lower-cost execution** — limit-order entry, or venues with materially
   tighter round trips. The gross effects measured are real; they are simply
   below 1–2 bp.
2. **Larger-effect event windows** — scheduled macro releases, session opens,
   rollover. Fewer, bigger dislocations rather than more, smaller ones.
3. **Multi-leg structures** — relative-value or carry spreads whose gross
   effect scales past the cost floor.

What must **not** happen: another cross-sectional sweep of the same H1 price
patterns. FAIL-000029 exists to block exactly that.

---

## 9. Honest summary

The factory works. It ran the full pipeline, applied every gate, found nothing
that survived, tightened a gate that was letting a fake survivor through, and
stopped.

The sealed holdout has never been opened. It remains the one piece of genuinely
independent evidence this project owns, and it is worth more unspent than spent
on a candidate that could not clear development data.

> *"If there is no real edge, NO_EDGE_FOUND is a valid scientific result.
> Never relax the standard to manufacture a fake edge."*

That instruction was followed exactly.
