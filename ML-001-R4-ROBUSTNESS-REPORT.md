# ML-001-R4 — Robustness Report

**Phase:** Generation 4, Phase 16
**Run:** `G4RUN-STRAT-000002-6b1c63d014d4a7be`
**Artifact:** `reports/generation4/ROBUSTNESS.json`
**Verdict:** `ROBUSTNESS_STATUS = FAIL` (viable region: **NONE**)

---

## 1. Disclosure, before any number

**This grid was not pre-registered.** No robustness protocol existed
before Generation 4. The grid below was declared as a module-level
constant in `core/economic_validation/robustness.py` before any robustness
result was computed, but choosing the neighbourhood during the generation
that evaluates it is a researcher degree of freedom.

`RobustnessReport.pre_registered` is therefore `false`, and the report's
own `declaration` field records the limitation in full. Consequences,
applied and enforced:

* These results are **not** an unbiased confirmation of any hypothesis.
* The module exposes **no** "best parameter" field, and
  `test_robustness_reports_the_whole_surface_and_names_no_best_point`
  asserts the summary contains no `best` key.
* The full 360-point surface is reported, not a selection from it.

---

## 2. Grid

Centred on the frozen values, extending symmetrically. Fully contains
`SEARCHSPACE-000001`'s declared alternatives (holding periods 12/24, stops
1.5/2.0×ATR, targets 2.0/3.0×ATR).

| Dimension | Values | Frozen value |
|---|---|---|
| RSI threshold | 25.0, 27.5, **30.0**, 32.5, 35.0 | 30.0 |
| Stop-loss ×ATR | 1.0, **1.5**, 2.0 | 1.5 |
| Take-profit ×ATR | 1.5, **2.0**, 2.5, 3.0 | 2.0 |
| Max hold (bars) | 6, **12**, 24 | 12 |
| Entry delay (bars) | **0**, 1 | 0 |

5 × 3 × 4 × 3 × 2 = **360 points**, all evaluated on DEVELOPMENT +
VALIDATION under the BASE cost model. Entry delay of 1 bar is the timing
perturbation: it tests whether the result depends on capturing one
specific bar's open.

---

## 3. The surface

| Quantity | Value |
|---|---|
| Points evaluated | 360 |
| Points producing trades | 360 |
| **Points with profit factor > 1** | **0** |
| Points net positive | **0** |
| Points net negative | **360** |
| Profit factor — minimum | 0.4636 |
| Profit factor — median | 0.7027 |
| **Profit factor — maximum** | **0.8611** |
| Net profit — minimum | −9,970.39 |
| Net profit — median | −8,496.03 |
| Net profit — maximum | −4,190.62 |
| Trade count range | 290 – 1,179 |
| **Viable region** | **NONE** |

**Not one point in a 360-point neighbourhood reaches break-even.** The
best point in the entire surface has profit factor 0.8611 — still losing
14 cents of every dollar risked.

### 3.1 The frozen point is unremarkable, which is the point

| | Value |
|---|---|
| Frozen point net profit | −8,768.91 |
| Frozen point profit factor | 0.6856 |
| Frozen point trade count | 646 |
| **Percentile within the surface** | **43.6%** |

The frozen parameters sit near the middle of their own neighbourhood —
slightly below median. They were neither a lucky pick nor an unlucky one.
That is exactly what one expects when the parameters were drawn from a
declared search space *before* any result was visible, and it is
corroborating evidence that no parameter tuning occurred.

### 3.2 Marginal behaviour along each dimension

| RSI threshold | Median PF | Max PF |
|---|---|---|
| 25.0 | 0.6393 | 0.7441 |
| 27.5 | 0.7072 | 0.8233 |
| **30.0** | 0.7021 | 0.8160 |
| 32.5 | 0.7405 | 0.8475 |
| 35.0 | 0.7380 | 0.8611 |

| Max hold | Median PF | Max PF |
|---|---|---|
| 6 | 0.6610 | 0.8052 |
| **12** | 0.7355 | 0.8475 |
| 24 | 0.7293 | 0.8611 |

| Stop / target (×ATR) | Median PF | Max PF |
|---|---|---|
| 1.0 / 1.5 | 0.6315 | 0.7328 |
| **1.5 / 2.0** | 0.7055 | 0.8255 |
| 2.0 / 2.5 | 0.7661 | 0.8413 |
| 2.0 / 3.0 | 0.7721 | 0.8611 |

| Entry delay | Median PF |
|---|---|
| **0 bars** | 0.6824 |
| 1 bar | 0.7216 |

Three observations, each of which cuts against the strategy rather than
for it:

1. **Loosening the oversold threshold improves things monotonically.**
   Profit factor rises from 0.64 at RSI 25 to 0.74 at RSI 35. The rule's
   own premise is that *deeper* oversold conditions are stronger
   mean-reversion signals; the data says the opposite — the more selective
   the signal, the worse the outcome. That is the signature of a signal
   with no information in it, where tighter selection buys only fewer
   trades and worse cost amortisation.

2. **Wider stops with wider targets are always better.** Profit factor
   rises monotonically along both axes. This is what a random entry looks
   like under fixed-fractional sizing: the closer the stop, the more often
   ordinary noise touches it first.

3. **Delaying entry by one bar makes it slightly better** (0.68 → 0.72).
   If the RSI crossover carried a genuine short-horizon mean-reversion
   signal, acting on it promptly should beat acting late. It does not.

None of these is a route to a working strategy — every point is still
below 1. They are diagnostic: the surface behaves the way a costed random
entry behaves, not the way a decaying edge behaves.

---

## 4. What this does and does not establish

**Establishes:** the frozen point is not an isolated island. The failure
is a property of the *rule family* — RSI-30 oversold mean reversion on
EURUSD H1 with ATR stops — not of the particular parameters drawn.

**Does not establish:** that no RSI-based strategy can work anywhere. The
grid covers one rule form, one instrument, one timeframe, one exit
structure. A different formulation is a different hypothesis requiring its
own lineage, its own candidate, and its own evaluation.

**Explicitly not permitted:** widening this grid now, after seeing that
nothing in it works, in search of something that does. That would be
opportunistic search-space expansion — the rescue loop Phase 25 forbids.
The grid stands as declared.
