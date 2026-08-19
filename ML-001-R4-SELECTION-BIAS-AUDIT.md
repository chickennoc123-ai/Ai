# ML-001-R4 — Selection Bias Audit

**Phase:** Generation 4, Phase 20
**Run:** `G4RUN-STRAT-000002-6b1c63d014d4a7be`
**Supporting artifacts:** `reports/generation4/MULTIPLE_TESTING.json`,
`reports/generation4/SEARCH_ACCOUNTING.json`,
`reports/generation4/ROBUSTNESS.json`
**Status:** `SELECTION_BIAS_STATUS = STATISTICAL_CORRECTION_APPLIED_LOW_POWER`

---

## 1. The question

Selection bias is not a property of a result; it is a property of the
*process that chose which result to report*. So the audit is a timeline,
not a statistic: for each choice, was it made **before** or **after** the
chooser could see an economic outcome?

A choice made before is a hypothesis. A choice made after is a selection,
and every selection made after must be counted.

---

## 2. Decision-by-decision trace

| # | Choice | Made | Before/after seeing economic results | Recorded in |
|---|---|---|---|---|
| 1 | Source: `SRC2-000001` (je-suis-tm README) | Gen 3 | **Before** — chosen for being reachable and permissively licensed; two other sources (arXiv, SSRN) were unreachable and their failures were retained, not hidden | `research_source_registry.json` |
| 2 | Claim: `CLAIM-000001` (RSI 70/30 lore) | Gen 3 | **Before** | `claim_registry.json` |
| 3 | Hypothesis: `HYP-000001` | Gen 3 | **Before** | `hypothesis_registry.json` |
| 4 | Search space: `SEARCHSPACE-000001` (8 combinations) | Gen 3 | **Before** | `search_space_registry.json` |
| 5 | Parameter draw → `STRAT-000002` | Gen 3 | **Before** | `strategy_registry.json` |
| 6 | Features: `rsi_14`, `atr_14` | Gen 3, implied by the claim | **Before** | candidate spec |
| 7 | Instrument: EURUSD | Gen 3 | **Before** | candidate spec |
| 8 | Timeframe: H1 | Gen 3 | **Before** | candidate spec |
| 9 | Partition boundaries 60/20/20 | 2026-08-18, Gen 1 | **Before** — committed before this candidate existed | `core/ml_r2/walkforward_r2.py` |
| 10 | Cost figures (1.6 pip / 0.2 pip / 7.00) | Pre-existing repository constants | **Before** | `core/utils.py`, `backtest_r2.py` |
| 11 | WFA window = 1 calendar month | Gen 4 | **Before** any WFA result | `walkforward.py` |
| 12 | Bootstrap block size = 20 trades | Gen 4 | **Before** any interval | `statistics.py` |
| 13 | Cost scenario ladder (8 rungs) | Gen 4 | **Before** any scenario ran | `cost_stress.py` |
| 14 | **Robustness grid (360 points)** | Gen 4 | **Before** any robustness result — but **not pre-registered before the candidate existed** | `robustness.py` — see §3 |

Choices made **after** observing an economic result: **none**.

No parameter, feature, instrument, window, seed, threshold, cost
assumption, or partition boundary was altered at any point after an
economic number was visible.

---

## 3. The one disclosed researcher degree of freedom

The robustness grid is the single item in the table that is not fully
clean, and it is disclosed rather than buried.

**What is fine:** the grid was declared as a module-level constant before
any robustness result was computed, and it is centred on the frozen
values, extending symmetrically in both directions. It fully contains the
declared `SEARCHSPACE-000001` alternatives (holding periods 12/24, stops
1.5/2.0×ATR, targets 2.0/3.0×ATR).

**What is not fine:** no robustness protocol existed before Generation 4.
Choosing the neighbourhood *during* the generation that evaluates it is a
researcher degree of freedom, even when the choice is made before seeing
the answer.

**Consequence, applied:** `RobustnessReport.pre_registered = False`, and
the report's `declaration` field states in full that its results are not
an unbiased confirmation of any hypothesis. The module deliberately
exposes no "best parameter" field.

**Why it does not change this verdict:** the grid returned **0 of 360**
points with profit factor > 1. A degree of freedom that could have been
exploited to manufacture a favourable result did not produce one anywhere
in the neighbourhood. Had a favourable point existed, this disclosure
would have mattered a great deal; here it establishes the opposite of what
an exploited freedom looks like.

---

## 4. Survivorship and instrument selection

**Survivorship bias: none available to exploit.** The rejected population
is preserved, not deleted. `STRAT-000001` (rejected, Generation 3) and
`STRAT-000002` (rejected here) both remain in the registry with full
history. The failure library holds 6 categorised failure records for
`STRAT-000002` alone. `test_23_failure_records_cannot_be_deleted` asserts
that `FailureLibrary` exposes no delete/remove/purge/update path at all.

**Instrument selection bias: structurally blocked.** GBPUSD data is
present, audited, and eligible. It was **not** evaluated for this
candidate. The frozen `research_scope` is `SINGLE_INSTRUMENT` / EURUSD,
and `verify_unchanged` raises if the candidate's `dataset_id` changes
(`test_09_instrument_cherry_picking_is_blocked_by_the_frozen_scope`).
Adding an instrument after freeze would be a scope change requiring a new
candidate.

Note what this discipline costs and why it is still right: a second
instrument would have been *informative*. But "run it on another pair and
see" is precisely how instrument shopping starts, and the boundary is only
meaningful if it holds when crossing it would be interesting.

**Time-period selection bias: none.** All 90 walk-forward windows are
retained and aggregated. There is no API on `WalkForwardReport` that
returns a filtered subset, and `test_08` asserts as much.

---

## 5. Multiple-testing accounting

| Counter | Value |
|---|---|
| `TOTAL_SOURCES` | 4 (2 accessed, 2 access-failed and retained) |
| `TOTAL_CLAIMS` | 3 |
| `TOTAL_HYPOTHESES` | 3 |
| `TOTAL_SEARCH_SPACES` | 1 |
| `TOTAL_STRATEGY_FAMILIES` | 4 |
| `TOTAL_CANDIDATES_GENERATED` | 2 |
| `TOTAL_CANDIDATES_TESTED` | 2 |
| `TOTAL_CANDIDATES_REJECTED` | 2 |
| `SEARCH_SPACE_SIZE` (enumerable) | 8 |
| **Effective trials used for deflation** | **2** |

`effective_trials` is every candidate the Factory has ever put through
economic evaluation, not just survivors. Using only the survivor would be
the exact self-deception Phase 19 exists to prevent.

The enumerable search space is 8 combinations, but only 2 were ever
evaluated. The un-drawn combinations were never tested and are not counted
as trials — inflating the count to 8 would have been *conservative* but
also fiction, and the audit prefers a defensible number to a flattering
one.

---

## 6. Status

`SELECTION_BIAS_STATUS = STATISTICAL_CORRECTION_APPLIED_LOW_POWER`

Read the whole string; the second half is not decoration. A Deflated
Sharpe correction really was computed and applied — that is an advance on
Generation 3's `ACCOUNTING_ONLY`. But over 2 evaluated candidates the
correction has almost no discriminating power. **Passing it would not have
demonstrated freedom from selection bias.** The limitation is encoded in
the status string itself so that a future reader cannot mistake
"corrected" for "shown to be unbiased", and
`test_selection_bias_status_is_not_silently_marked_pass` enforces that any
status beginning `STATISTICAL_CORRECTION_APPLIED` must carry `LOW_POWER`.

For this particular candidate the low power is moot: the observed Sharpe
is **negative** (−1.38 annualised). A multiple-testing correction can only
reduce confidence in a positive result. There was nothing here to deflate.
