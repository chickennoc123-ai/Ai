# ML-001-R4 — Walk-Forward Report

**Phase:** Generation 4, Phases 14–15
**Run:** `G4RUN-STRAT-000002-6b1c63d014d4a7be`
**Artifact:** `reports/generation4/WALK_FORWARD.json`
**Verdict:** `WFA_STATUS = FAIL`

---

## 1. What this protocol can and cannot test here

`STRAT-000002` fits nothing. Its three parameters are constants in the
frozen specification, not estimates from data. A walk-forward protocol's
usual purpose — testing whether parameters fitted on a training window
survive on the following test window — therefore has no subject.

The training-window fields in every window record are deliberately empty:

```json
"training_start": null,
"training_end": null,
"training_note": "NO_TRAINING_WINDOW: STRAT-000002 fits no parameters, so
                  no window was trained. Every window is out-of-sample by
                  construction.",
"model_checksum": "NONE_DETERMINISTIC_RULE"
```

Filling them with a fitting step that did not happen would have made the
report look more complete and mean less.

What the protocol *does* test, and what makes it worth running, is the
Phase 15 question: **is the result stable across time, or is it an
artifact of one period?** That question is entirely real for a
zero-parameter rule.

---

## 2. Protocol

| Field | Value |
|---|---|
| Window definition | 1 calendar month, contiguous, **non-overlapping** |
| Coverage | DEVELOPMENT + VALIDATION, 2012-11 → 2020-04 |
| Windows generated | **90** |
| Windows evaluated | **90** |
| Windows retained | **90** |
| Windows discarded, filtered, or ranked | **0** |
| Warmup per window | all bars at or before that window's end, never later |
| Cost model | BASE |

Non-overlap matters: overlapping test windows would double-count trades
and make the dispersion statistics look tighter than they are.

Window failure handling: a window that failed to evaluate would raise
`WalkForwardError` naming the window, aborting the report. There is no
code path that drops a window. `test_08_window_cherry_picking_is_refused`
asserts the report exposes no selection API, and
`test_walk_forward_retained_every_window` asserts window ids are gapless
and that the retained windows' net profits sum to the reported aggregate.

---

## 3. Aggregate

| Quantity | Value |
|---|---|
| Windows | 90 |
| Windows with trades | 90 |
| Windows without trades | 0 |
| Total trades | 638 |
| **Total net profit** | **−18,557.81** |
| **Positive window fraction** | **0.3556** (32 / 90) |
| **Negative window fraction** | **0.6444** (58 / 90) |
| Flat window fraction | 0.0 |
| Mean window net profit | −206.20 |
| Median window net profit | −155.67 |
| Std dev of window net profit | 524.83 |
| Best window | #72, 2018-10, 11 trades, **+1,103.54** (PF 2.609) |
| Worst window | #48, 2016-10, 15 trades, **−1,932.73** (PF 0.191) |

---

## 4. Phase 15 — concentration and stability

The purpose of this section is to check whether the aggregate is a real
property or an artifact. It could fail in either direction: a *good*
aggregate driven by one window would be suspect, and a *bad* aggregate
driven by one catastrophic window would equally not justify a rejection.

| Test | Value | Reading |
|---|---|---|
| Largest single window's share of absolute P&L | **5.09%** | no window dominates |
| Top-5 windows' share of absolute P&L | **18.26%** | no small cluster dominates |
| Correlation of window P&L with time | **+0.0269** | no trend; not a decayed edge |
| Total with the **best** window removed | −19,661.35 | still deeply negative |
| Total with the **worst** window removed | −16,625.08 | still deeply negative |
| Concentration flag | **DISTRIBUTED** | — |

The two removal tests are the decisive ones. Deleting the single worst
month — the largest possible charitable adjustment — moves the total from
−18,558 to −16,625. The result does not depend on any individual period.

### 4.1 By calendar year

| Year | Trades | Net profit | Sign |
|---|---|---|---|
| 2012 (Nov–Dec) | 5 | −104.61 | − |
| 2013 | 70 | −2,365.10 | − |
| 2014 | 100 | −3,509.87 | − |
| 2015 | 98 | −1,897.78 | − |
| 2016 | 94 | −3,287.08 | − |
| 2017 | 69 | −1,533.52 | − |
| 2018 | 98 | −1,826.66 | − |
| 2019 | 72 | −3,733.40 | − |
| 2020 (Jan–Apr) | 32 | −299.79 | − |

**Every one of the nine calendar years is net negative.** Not one year,
including the partial ones at each end, produces a positive result. This
spans trending and range-bound regimes, the 2015 CHF de-peg, the Brexit
period, and the opening months of the 2020 volatility shock.

### 4.2 Regime dependence

There is no regime in which this rule works. The candidate's own
`regime_conditions` is `"any (unconditional; source states no regime)"` —
the source claim asserted no regime condition, so none was tested, and the
year-by-year result shows none would have rescued it.

This is worth stating because "it works in the right regime" is the most
common rescue argument for a mean-reversion rule. The evidence here does
not support it: the losses are uniform across nine years of varied
conditions, and 58 of 90 individual months are negative.

---

## 5. Verdict

`WFA_STATUS = FAIL`.

* 35.6% of windows positive — materially below the 50% a coin flip would
  produce, and far below what an edge would produce.
* Total net −18,557.81 across 638 trades.
* Losses **DISTRIBUTED**, not concentrated: no window, no cluster, and no
  year carries the result.
* No time trend (correlation +0.027), so this is not a decayed edge that
  once worked.

The failure is a broad, persistent property of the rule across the entire
reusable history — which is precisely the finding that makes the rejection
safe rather than unlucky.
