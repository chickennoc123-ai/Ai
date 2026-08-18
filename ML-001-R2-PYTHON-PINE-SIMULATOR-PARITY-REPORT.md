# ML-001-R2 Python↔Pine Simulator Parity Report

**Date**: August 18, 2026
**Baseline commit**: `5a516c3`
**This phase's changes**: see git diff / new files listed below
**Status**: **PARTIAL PARITY — MODEL_PARITY BLOCKED (unchanged verdict, now with substantially stronger evidence)**

This report supersedes `ML-001-R2-PYTHON-PINE-PARITY-REPORT.md` for the
position/risk/trade-sequence dimensions it did not previously cover
(that report's feature-layer findings are re-confirmed, not
contradicted, below). See
`ML-001-R2-PYTHON-PINE-SIMULATOR-FORENSIC-BASELINE.md` for the
independently re-verified Phase 0 forensic baseline this report builds on.

---

## 1. What was built this phase

| File | Layer | Contents |
|---|---|---|
| `core/ml_r2/simulator_r2.py` | A–E orchestration | `FeatureEngine`, `ModelOutputProvider`/`NullModelProvider`/`FixtureProbabilityProvider`, `SignalDecisionEngine`/`decide_signal`, trade-event translation over `core.ml_r2.backtest_r2.run_backtest` (D/E), `run_simulation()` |
| `core/ml_r2/pine_model_exporter_r2.py` | Model export architecture | `export_model_to_pine()` — fails closed with `MODEL_ARTIFACT_MISSING` (or `NotImplementedError` for the never-reached translation branch); never fabricates Pine model code |
| `ML-001-R2-GOLDEN-OHLCV-FIXTURE.csv` | Golden dataset | 1001-bar deterministic OHLCV fixture: 650-bar warmup + 8 engineered scenarios + weekend-hour gaps |
| `ML-001-R2-GOLDEN-PROBABILITY-FIXTURE.csv` | Golden dataset | 11 supplied probabilities, `MODEL_PARITY_TEST_FIXTURE_ONLY`, driving the 8 scenarios |
| `ML-001-R2-GOLDEN-PARITY-VECTOR.csv` | Golden dataset | Full per-bar export (OHLCV, all 5 features, `feature_valid`, `supplied_model_probability`, `signal`, `position_state`, `entry`, `exit`, `exit_reason`, `position_size`, `stop_loss`, `take_profit`) — 1001 rows |
| `pine/ML_001_R2_STRATEGY.pine` (modified) | Pine, D/E | Added **PARITY TEST FIXTURE MODE**: embeds the same 11 supplied probabilities (keyed by `bar_index`), wired through the file's existing §10 mechanics, for genuine TradingView Strategy Tester replay against an imported copy of the golden OHLCV CSV |
| `tests/test_ml_001_r2_simulator.py` | Tests | 25 tests: layer separation, model fail-closed, a small hand-traced SL scenario, golden-dataset regression (exact 7-trade event sequence), fresh-process reproducibility |
| `ML-001-R2-PYTHON-PINE-SIMULATOR-FORENSIC-BASELINE.md` | Phase 0 | Independently re-verified forensic baseline |
| `ML-001-R2-TRADINGVIEW-MANUAL-TEST-GUIDE.md` (extended) | Phase 9 | New Section 6 (golden dataset table + PARITY TEST FIXTURE MODE instructions), Section 7 (GBPUSD repeat), governance reminder |

**Deliberately not built**: any Pine translation of RF-R2-001 (no artifact exists — Section 5).

---

## 2. Architecture: five layers, not collapsed

`core/ml_r2/simulator_r2.py` keeps the five layers genuinely separate:

- **A. Feature Engine** — thin wrapper over the unmodified
  `core.features.fe_r2_001.build_feature_matrix` (Python FE-R2-002
  remains the sole source of truth; hash-verified unchanged, Section 6).
- **B. Model Output** — `ModelOutputProvider` ABC. Exactly two
  implementations exist: `NullModelProvider` (fails closed — Section 5)
  and `FixtureProbabilityProvider` (`MODEL_PARITY_TEST_FIXTURE_ONLY`,
  rejects being relabeled, rejects unaligned timestamps — see
  `TestLayerSeparation` in the new test file). No third implementation,
  fake or otherwise, exists anywhere in this codebase.
- **C. Signal Decision** — `decide_signal()` (pure, stateless, spec §10
  threshold logic) + `SignalDecisionEngine` (adds `feature_valid`
  gating). Independently unit-tested at the exact `0.55`/`0.45`
  boundaries (strict inequality, `FLAT` at the boundary itself).
- **D. Position/Risk Engine** + **E. Execution Engine** — reuse
  `core.ml_r2.backtest_r2.run_backtest` rather than a second,
  potentially-divergent reimplementation of the same §10 mechanics that
  module already implements correctly and had its own pre-existing test
  suite (`tests/test_ml_001_r2_backtest.py`). `simulator_r2.py`
  translates its `Trade` objects into the canonical trade-event
  vocabulary (`ENTER_LONG`, `ENTER_SHORT`, `EXIT_STOP`, `EXIT_TP`,
  `EXIT_MAX_HOLD`, `EXIT_SIGNAL_REVERSAL`) and a per-bar `position_state`
  series.

---

## 3. Golden dataset: eight scenarios, each verified against the real simulator

Built iteratively (`/tmp/.../generate_golden_dataset.py`, not part of
the repo — a scratch script), using the **real**
`core.features.fe_r2_001.build_feature_matrix` to read back the actual
`atr_14` value before sizing each scenario's trigger bars (never
hand-guessed), and the **real** `core.ml_r2.simulator_r2.run_simulation`
to confirm each scenario actually produced its intended outcome (never
hand-traced).

**A genuine bug was caught and fixed during construction**: the first
draft supplied each scenario's probability at the *same* bar it also
used as the "entry bar," collapsing signal-bar and entry-bar into one
index — contradicting T+1 timing. A second bug (the entry bar's own
±0.05%-of-price wick exceeding the actual ~0.03%-of-price stop-loss
distance) caused the entry bar to self-trigger its own stop before the
intended trigger bar was reached. Both were found by *running the real
simulator* and inspecting actual output, not by inspection — exactly the
kind of error this project's evidentiary discipline exists to catch.
Fixed by (1) keying each scenario's probability to the last
already-appended bar rather than a not-yet-appended one, and (2) sizing
the entry bar's own wick as a small fraction of the computed SL/TP
distance rather than a fixed price-relative amount.

Final, verified trade-event sequence (`tests/test_ml_001_r2_simulator.py::TestGoldenDatasetRegression::test_trade_event_sequence_exact`, locked in as a regression test):

| bar | event | bar | event | scenario |
|---|---|---|---|---|
| 699 | ENTER_LONG | 700 | EXIT_STOP | 1: long → stop-loss |
| 731 | ENTER_LONG | 732 | EXIT_TP | 2: long → take-profit |
| 763 | ENTER_SHORT | 764 | EXIT_STOP | 3: short → stop-loss |
| 795 | ENTER_SHORT | 796 | EXIT_TP | 4: short → take-profit |
| 827 | ENTER_LONG | 851 | EXIT_MAX_HOLD | 5: max-hold (holding=24 exactly) |
| 883 | ENTER_LONG | 884 | EXIT_STOP | 6: exit-priority conflict (both SL and TP breached same bar — **STOP_LOSS wins**, proving SL>TP priority) |
| 915 | ENTER_LONG | 939 | EXIT_MAX_HOLD | 7: position limit (signals at 916, 934 while open produce **no** additional trade) |
| — | — | — | — | 8: boundary (`p=0.55`, `p=0.45` exactly at bars 970/975 → no trade) |

**Exactly 7 trades total** (not 9 — scenario 7's two extra signals correctly produced zero additional entries).

---

## 4. Pine-side replay: PARITY TEST FIXTURE MODE

`strategy.entry()`/`strategy.exit()` always fill against the chart's
*real* bars — there is no Pine mechanism to make the order engine
replay a synthetic price series independent of the actual chart. So,
unlike the feature-debug script's self-contained array replay (which
needs no external data), genuine position/risk parity testing in Pine
requires the human to import `ML-001-R2-GOLDEN-OHLCV-FIXTURE.csv` as a
TradingView custom data feed, so the chart's own `bar_index`/OHLC
exactly matches the Python golden dataset. `ML_001_R2_STRATEGY.pine`
then only needs to embed the 11 supplied probabilities (keyed by
`bar_index`) — `atr_14`, order fills, and SL/TP breach checks are all
computed natively by Pine against the imported real bars, through the
same canonical feature block already verified byte-identical across
this project's three `.pine` files
(`tests/test_pine_parity.py::TestCanonicalFeatureBlockTextIdentity`,
re-run after this phase's edit — still passing, Section 6).

This is real, honestly-scoped, human-executable evidence — not a claim
that it has been executed. See Section 8 for what remains
`HUMAN_VERIFICATION_REQUIRED`.

---

## 5. Model artifact status (Phase 6, re-confirmed)

```
MODEL_ARTIFACT = NONE
PINE_MODEL_STATUS = BLOCKED_BY_MISSING_MODEL_ARTIFACT
```

Independently re-verified this phase (Phase 0 forensic baseline): no
trained RF-R2-001 artifact exists in the repo, its git history, or any
gitignored local path; the only `.pkl` files anywhere on the filesystem
are third-party test fixtures (numpy/joblib's own).

`core/ml_r2/pine_model_exporter_r2.py::export_model_to_pine()` is the
architecture stub spec §13 calls for: given a nonexistent artifact path
it raises `ModelArtifactMissingError("MODEL_ARTIFACT_MISSING: ...")`
(tested); given a path that exists but was never produced by a real
training run, it proceeds past the missing-file check and raises
`NotImplementedError` at the (intentionally unwritten) tree-translation
step — it never falls through to generating placeholder or approximate
Pine model code under any circumstance (also tested).

---

## 6. Structural / hash verification (re-run, not assumed)

```
core/features/fe_r2_001.py            unchanged: 1d8ce135daaafedd8c085b243f41beeb1b8aafb165f7169d3722dc6e99ffd3dd
pine/ml_001_r2_features.pine          unchanged: dcfc8c04f18906ba973092e894b1a8105543d193ae33fd22673e8b406773cad8
pine/ML_001_R2_FEATURE_DEBUG.pine     unchanged: 615eb426890b96072f57259693dba554bdd0c603ebe20fb20a7e32954d559b2b
pine/ML_001_R2_STRATEGY.pine          CHANGED (PARITY TEST FIXTURE MODE added): bb07c63ae57e76a26d0344b6100568130b615e7fcf355b0efd4bda7e1d07b0f2
```

The canonical feature block inside `ML_001_R2_STRATEGY.pine` was **not**
touched — only the signal/risk section after it — and remains
byte-identical to the other two files
(`tests/test_pine_parity.py`, re-run after this edit, still 20/20 passing).

Python `FE-R2-002` (`fe_r2_001.py`) was not modified — governance rule
10 ("Python FE-R2-002 remains the source of truth") and rule 9 ("do not
alter the canonical Python feature implementation merely to make Pine
match") both hold, confirmed by hash-diff, not merely by intent.

---

## 7. No-repaint / timing audit (Phase 8) — explicit evidentiary classification

| Claim | Classification | Basis |
|---|---|---|
| No `request.security()` used anywhere in any `.pine` file | **PROVEN** (by source grep — an absence claim, directly checkable) | grep across all three files: zero matches |
| No negative-index (future-bar) reference | **SOURCE_VERIFIED** | every historical reference is `close[n]`/`high[n]`/`low[n]` for `n ≥ 0`; manually audited, not exhaustively machine-checked |
| `calc_on_every_tick=false` prevents intrabar/partial-bar signal evaluation | **SOURCE_VERIFIED** | declared in `strategy()` call, read directly from source |
| `process_orders_on_close=false` gives native T+1 fill timing | **SOURCE_VERIFIED** (documented Pine platform behavior) — **HUMAN_VERIFICATION_REQUIRED** for actual confirmed fill timestamps in a live chart | Pine's own semantics for this setting are well-documented, but this project has no way to execute Pine and observe an actual fill timestamp |
| PARITY TEST FIXTURE MODE reproduces the golden vector's exact 7-trade sequence in TradingView's own Strategy Tester | **HUMAN_VERIFICATION_REQUIRED** | cannot be executed in this environment (no Pine compiler); Section 4/Section 6 of the manual test guide gives the exact procedure and expected result |
| `atr_14` computed by Pine (via the canonical block) numerically matches Python's `atr_14` beyond the previously-tested 160-bar window (i.e., through bar ~940, where the golden dataset's scenarios run) | **HUMAN_VERIFICATION_REQUIRED** | the earlier Fixture Replay Mode test only directly verified bars 0–159; this is the same recurrence continuing forward with no reason to expect divergence, but that expectation itself is unverified past bar 160 |
| RF-R2-001 model parity | **BLOCKED** | no artifact exists (Section 5) |

No claim above is asserted as `PROVEN` beyond what a static source read
actually establishes. Executing Pine in an actual TradingView session
is required to move any `HUMAN_VERIFICATION_REQUIRED` row to `PROVEN`
or `FAIL`.

---

## 8. Tests (Phase 11)

All counts independently re-run this phase, not carried over from a prior report:

```
Full repository suite:              533 / 533 passing, 0 failed, 0 skipped
R2 + Pine-parity + simulator suite:  231 / 231 passing, 0 failed, 0 skipped
  (186 pre-existing R2 tests + 20 Pine structural/fixture/adversarial
   tests + 25 new simulator tests)
```

New this phase (`tests/test_ml_001_r2_simulator.py`, 25 tests):
layer-separation tests (7), model-exporter fail-closed tests (2), a
small hand-traceable long→stop-loss scenario (1), golden-dataset
regression tests (7, including the exact 14-event trade sequence, the
exit-priority-conflict resolution, the position-limit enforcement, and
a full-bar-table vs. committed-CSV equality check), and a genuine
fresh-process reproducibility test (1, spawning two separate Python
interpreter subprocesses and diffing their trade-event output
byte-for-byte).

No existing assertion was weakened or deleted to make this phase's work
pass.

---

## 9. Final verdict table

| Field | Verdict | Basis |
|---|---|---|
| `FEATURE_PARITY` | **PASS** | unchanged from prior report; canonical block re-verified byte-identical after this phase's edit |
| `RSI_PARITY` | **PASS** (formula-level) | unchanged from prior report |
| `ATR_PARITY` | **PASS** (formula-level) | unchanged from prior report |
| `VOLATILITY_REGIME_PARITY` | **PASS** (formula-level, one open assumption) | unchanged from prior report |
| `SIGNAL_PARITY` | **BLOCKED** | depends on `p`, which requires a model that does not exist |
| `TIMING_PARITY` | **PASS** (source-verified) | Section 7 |
| `POSITION_LOGIC_PARITY` | **PASS** (translated AND now scenario-tested in Python; Pine-side execution is `HUMAN_VERIFICATION_REQUIRED`) | Sections 3–4, upgraded from the prior report's "translated, unreachable" — the mechanics are no longer merely present in source, they are exercised end-to-end by 25 passing tests against 8 engineered scenarios |
| `MODEL_PARITY` | **BLOCKED** | no trained artifact exists (Section 5) |
| `TRADE_SEQUENCE_PARITY` | **PASS (Python side, regression-locked)** / **HUMAN_VERIFICATION_REQUIRED (Pine side)** | exact 14-event, 7-trade sequence locked in as an automated regression test; the equivalent TradingView Strategy Tester run has not been performed |
| `NO_REPAINT` | **PASS** (source-verified) | Section 7 |
| `OVERALL_SIMULATOR_PARITY` | **BLOCKED** | **Per the explicit governing rule carried forward unchanged from the prior report: if the model artifact is missing, `MODEL_PARITY = BLOCKED` and the overall verdict is `BLOCKED`, even though every feature, timing, and position/risk-mechanics check above passes. This is not weakened by the added scenario coverage.** |
| `ECONOMIC_VALIDITY` | **UNPROVEN** | unchanged; no economic claim is made anywhere in this phase's work |
| `PRODUCTION` | **BLOCKED** | unchanged |

---

## 10. Phase 12 — Final governance gate

**Q1: Are the five Python features and Pine features structurally identical?**
Yes — the canonical feature block is byte-identical across all three
`.pine` files (automated diff test), and each Python formula has
exactly one Pine counterpart (established in the prior report, re-
confirmed unchanged this phase).

**Q2: Are their numerical outputs proven identical in an actual TradingView runtime?**
No. Numerical agreement is proven for the fixture-embed transcription
(Python-computed expected values vs. the array literals committed into
the Pine source, 0 mismatches >5e-7) and for the golden-dataset
mechanics in Python (25 passing tests). It has **not** been proven by
an actual TradingView execution — no Pine compiler is available in this
environment. This remains `HUMAN_VERIFICATION_REQUIRED`.

**Q3: Is the signal logic proven identical?**
Not applicable in the sense the question implies — there is no real
signal to compare, since there is no model. The *threshold/timing/
position-limit/exit-priority mechanics* that would apply once a
probability exists are proven identical in Python (regression-tested)
and mechanically translated to Pine (source-verified, not yet
TradingView-executed).

**Q4: Is the RF-R2-001 model available?**
No. Confirmed by independent forensic search this phase (Section 5),
consistent with every prior phase's finding.

**Q5: Can model parity be proven?**
No — there is nothing to compare. `MODEL_PARITY = BLOCKED`.

**Q6: Can the complete strategy be manually tested in TradingView?**
The *feature layer* and the *position/risk mechanics* (via PARITY TEST
FIXTURE MODE, using the golden OHLCV CSV as an imported chart) can be —
instructions are in
`ML-001-R2-TRADINGVIEW-MANUAL-TEST-GUIDE.md`. The *complete strategy*
(i.e., with a real model producing real signals) cannot be, because no
model exists to produce a signal to test.

**Q7: Has economic validity been established?**
No. `ECONOMIC_VALIDITY = UNPROVEN`. Nothing in this phase's work
attempts to establish it — the golden dataset is explicitly synthetic
and engineered to hit specific mechanical edge cases, not to resemble
real market behavior, and is never used as economic evidence anywhere
in this report or its tests.

**Q8: Is production authorized?**
No. `PRODUCTION = BLOCKED`.

---

## 11. Governance state (unchanged by this phase)

```
ECONOMIC_VALIDITY = UNPROVEN
PRODUCTION        = BLOCKED
ML-001-R2         = RESEARCH_ONLY / NOT_AUTHORIZED
```

No PURE_HOLDOUT was opened. No broker order was submitted. No Random
Forest model was invented, fabricated, or substituted. No model
probability was fabricated and presented as real — every supplied
probability in this phase's work is labeled
`MODEL_PARITY_TEST_FIXTURE_ONLY` at every point it appears in code,
tests, CSVs, and Pine source, and `FixtureProbabilityProvider` actively
rejects being relabeled (tested). No synthetic result in this report is
offered as economic evidence.

---

**REPORT COMPLETE — MODEL_PARITY BLOCKED — OVERALL_SIMULATOR_PARITY BLOCKED — NO PRODUCTION AUTHORIZATION — NO ECONOMIC CLAIM MADE**
