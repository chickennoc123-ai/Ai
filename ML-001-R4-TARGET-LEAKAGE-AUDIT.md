# ML-001-R4 — Target / Label Leakage Audit

**Phase:** Generation 4, Phase 4 (with the Phase 3 feature audit summarised in §2)
**Run:** `G4RUN-STRAT-000002-6b1c63d014d4a7be`
**Artifacts:** `reports/generation4/TARGET_LEAKAGE_AUDIT.json`,
`reports/generation4/FEATURE_TEMPORAL_AUDIT.json`
**Implementation:** `core/economic_validation/target_audit.py`,
`core/economic_validation/feature_temporal_audit.py`

| Result | Verdict |
|---|---|
| `FEATURE_TEMPORAL_SAFETY` | **PASS** |
| `TARGET_LEAKAGE_STATUS` | **PASS** |
| `LEAKAGE_STATUS` | **PASS** |

---

## 1. What "target" means for a candidate with no label

`STRAT-000002` specifies no model, so it has no learned label. That does
not remove the leakage question; it moves it. The thing whose sign and
magnitude the entire economic verdict rests on is the **realised net P&L
of each trade**, and the leakage questions are the same questions asked of
the trade record instead of a label column:

1. Does the decision to enter use anything from after the decision bar?
2. Does the realised outcome use anything from after the exit bar?
3. Do outcomes overlap, so one price move is counted twice?
4. Does the horizon match the frozen specification?
5. Is a trade still open at the end of the data counted as a result?

---

## 2. Feature temporal safety (Phase 3)

Audited features: `rsi_14`, `atr_14` (the two the candidate uses).
Cut points: 12 evenly spaced positions across the usable range, chosen
deterministically from the row count — never chosen by looking at where a
feature happens to behave well.

| Test | `rsi_14` | `atr_14` |
|---|---|---|
| Truncation invariance | PASS | PASS |
| Future perturbation invariance | PASS | PASS |
| Same-timestamp (next-bar) leakage | PASS | PASS |

Violations found: **none**.

### 2.1 Why these three tests and not a code review

Documenting that a feature "uses a rolling window and is therefore causal"
proves nothing — the entire class of bugs this phase exists to catch
consists of features whose author believed exactly that. So the property
is tested directly on the real series:

* **Truncation invariance.** For a causal feature,
  `f(data[0..T])[t] == f(data[0..t])[t]`. If the value at `t` changes when
  bars after `t` are deleted, it depended on them.
* **Future perturbation invariance.** Replace every bar after `t` with
  materially different prices (a 10–40% multiplicative shock applied
  uniformly to O/H/L/C so the bars stay OHLC-valid) and require `f[t]`
  bit-identical. This catches a feature that reads the future only when
  the future has particular values, which truncation alone would miss.
* **Same-timestamp leakage.** Alter *only* bar `t+1` and require `f[t]`
  unchanged. A one-bar lookahead is by far the most common real leakage
  bug and gets its own named result rather than being averaged into a
  general sweep.

Comparison is exact, not approximate. A tolerance would hide small leaks.

### 2.2 Per-feature dependency records

| | `rsi_14` | `atr_14` |
|---|---|---|
| Source columns | `close` | `high`, `low`, `close` |
| Lookback | 14 | 14 |
| Warmup | per `WARMUP_BARS` | per `WARMUP_BARS` |
| Alignment | right (recursive average ending at `t`) | right |
| Availability | bar close of `t` | bar close of `t` |
| Window semantics | seeded Wilder recurrence over `close.diff()`; expanding backward | seeded Wilder recurrence over true range |
| Shift semantics | `close.shift(+1)` | `close.shift(+1)` inside true range |
| Missing data | internal NaN after seed → `WilderSmoothingError` (fails closed) | same |
| Forward fill | none | none |
| Cross-symbol | none | none |
| Normalisation | bounded 0–100 by construction; no fitted scaler | none |

### 2.3 Two whole leakage classes are structurally absent

* **Cross-symbol leakage.** `build_feature_matrix` takes exactly one
  symbol's OHLCV frame and has no parameter, import, or global through
  which another symbol's data could reach it.
* **Scaler / imputation leakage.** FE-R2-003 fits no scaler and performs
  no imputation. Warmup rows are set to NaN and later dropped by
  alignment; they are never filled. There is no fit/transform object whose
  fitted state could span a train/test boundary. `test_12` asserts this by
  grepping the feature module for `StandardScaler`, `MinMaxScaler`,
  `fit_transform`, `fillna(method=` and `bfill`.

---

## 3. Target construction as executed

| Element | Value |
|---|---|
| Target type | `REALIZED_TRADE_PNL` |
| Learned label | none |
| Signal timestamp | bar close of `t` (features from bars ≤ `t` only) |
| Decision timestamp | bar close of `t` — identical to signal |
| Entry timestamp | **open of bar `t+1`** |
| Exit timestamp | first bar at which stop-loss, take-profit, or max-hold fires |
| Forecast horizon | 12 bars (frozen `max_hold_bars`) |
| Overlap policy | one open position at a time |

---

## 4. Findings

| Check | Result | Evidence |
|---|---|---|
| Signal→entry lag | exactly 1 bar for **every** trade (min 1, max 1) | `signal_to_entry_lag_bars` |
| Horizon conformance | PASS — no trade exceeds 12 bars | `horizon_conformance` |
| Overlap | PASS — zero overlapping pairs | `overlap_check` |
| Unclosed trades counted | PASS — none | `unclosed_trade_handling` |
| Post-exit perturbation | PASS | `post_exit_perturbation` |
| Post-signal decision invariance | PASS | `post_signal_decision_invariance` |
| Boundary (final bar) | PASS | `boundary_check` |

Trades audited: 488 (DEVELOPMENT partition). Violations: **none**.

### 4.1 The two empirical checks

Static timestamp checks would pass for an engine that reads future prices
through some path the timestamps do not reveal. Two perturbation checks
close that gap, on a deterministic sample of 25 real trades:

* **Post-exit perturbation.** For each sampled trade, multiply every bar
  strictly after its exit bar by 1.3 and re-execute. The trade's P&L and
  exit timestamp must be unchanged. If the outcome moved, the outcome was
  reading past its own exit.
* **Post-signal decision invariance.** For each sampled trade, multiply
  every bar strictly after its signal bar by 1.15 and re-execute. The same
  signal must still be acted on. The entry *price* legitimately comes from
  the next bar's open and is expected to move; the *decision* must not.

Both passed for every sampled trade.

---

## 5. One honest discrepancy, recorded rather than corrected

`HYP-000001` states its target as "forward return over **12 bars**". The
frozen candidate realises this as `max_hold_bars = 12` with earlier exit
on stop or target.

These are consistent but not identical: a stopped-out trade realises a
shorter horizon than the hypothesis literally states. Roughly two-thirds
of trades exit early on a stop or target rather than at the 12-bar bound
(DEVELOPMENT: 236 stop-loss, 113 take-profit, 139 max-hold).

This is a property of the frozen specification. It is **recorded here, not
corrected** — changing the exit rule to match the hypothesis's literal
wording after evaluation began would be exactly the post-hoc rule change
the governance forbids. A future candidate could legitimately test the
unconditional 12-bar horizon as a separate, properly-lineaged experiment.

---

## 6. Verdict

`LEAKAGE_STATUS = PASS`.

No leakage was found. That is a real finding and not a formality — but it
should be read for what it is. It means the negative economic result below
is *not* an artifact of a broken pipeline. A leaking pipeline usually
produces implausibly *good* results; this one produces bad ones and is
clean. The strategy simply does not work.
