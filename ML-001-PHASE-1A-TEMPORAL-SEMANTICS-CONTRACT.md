# ML-001-R2 — Phase 1A Temporal Semantics Contract

**Date**: 2026-08-18
**Status**: DRAFT — definitions below are proposed for authorization, not yet
adopted. No code changes have been made on the basis of this document.
**Purpose**: per the ML-001 Strategy Factory roadmap §5/§5A, define precisely
what "continuous data" means for FE-R2-002 before any change is made to
`_check_weekday_gaps` or any downstream feature/model code, so that whatever
gap policy is eventually authorized (see the companion gap-semantics audit
and Decision Pack) is implemented against an explicit contract rather than
an implicit one.

---

## 1. Three distinct notions of "continuity," disambiguated

| Term | Definition | Currently used by |
|---|---|---|
| **Calendar continuity** | Every wall-clock hour, with no exception, has a bar. | Nothing in FE-R2-002 — would be wrong for FX, which has no weekend trading. |
| **Market-session continuity** | Every wall-clock hour *during which the market is open* has a bar; the declared Fri 22:00–Sun 22:00 UTC closure is excluded by definition, not treated as missing. | `_check_weekday_gaps`'s intent, per spec §7. This is the correct target concept for FX. |
| **Observed-bar continuity** | Whatever bars actually exist in the row-indexed series, treated as adjacent regardless of the real wall-clock distance between them. | Every rolling/shift/ewm computation in `fe_r2_001.py` today, implicitly, because `.shift(n)` and `.rolling(window=N)` operate on row position, not on elapsed wall-clock time. |

**The defect this table exposes**: `_check_weekday_gaps` enforces
market-session continuity at the *validation* boundary (reject frames with
unexplained gaps), but every feature computed *after* that boundary passes
silently assumes observed-bar continuity — i.e., today's code has no
explicit statement that these two notions are meant to coincide, it only
achieves that coincidence as a side effect of rejecting any input where they
would diverge. If the gap policy is relaxed to admit real thin-liquidity
gaps, that side-effect protection disappears, and the divergence becomes
live and must be handled explicitly, not left implicit. This is exactly why
Phase 1A must be resolved *before* any relaxation of the validator (roadmap
§5A: "Only after this contract is defined and authorized may the validator
be changed").

## 2. Feature-by-feature consequence of a market-session gap, if admitted

Assume a real, authorized gap G (some N hours missing, N ≥ 2, entirely inside
a documented low-liquidity window) is allowed to pass validation. Its effect
on each FE-R2-002 feature, computed exactly as `fe_r2_001.py` computes it
today (row-position-based), if left unmodified:

- **`momentum_5` / `momentum_20`** (`compute_momentum`, `close.shift(n)`):
  the "n-bar" lookback silently becomes an "n-*observed*-bar" lookback. If G
  falls inside the lookback window, the computed return is measured over
  more wall-clock hours than its neighbors, without being labeled as such.
  This does not use *future* information (no look-ahead), but it silently
  changes the meaning of the feature for bars near a gap: a 5-bar momentum
  that actually spans 8 real hours is not the same statistical quantity as
  one that spans 5. **Materiality**: low-to-moderate — momentum_5/20 are
  short lookbacks, so only bars within N bars *after* a gap are affected,
  and the effect is a variance/scale distortion, not a leakage defect.

- **`rsi_14` / `atr_14`** (`_seeded_wilder_smooth`, an O(n) sequential
  recurrence over row position): this is the most exposed feature to gap
  semantics. Wilder smoothing is a running EMA-like recurrence; it has no
  concept of elapsed time between successive inputs. A gap does not corrupt
  the recurrence numerically (no NaN, no crash — the recurrence just treats
  the next observed value as if it were exactly one bar later), but it does
  mean the smoothing constant (1/14) is applied uniformly across a wall-clock
  interval that was not actually one hour, silently changing the effective
  half-life of the smoother around every gap. **Materiality**: moderate —
  this is a real, silent change in what "14-period" means near a gap, though
  it is bounded (self-correcting after ~14 subsequent bars) and does not
  constitute look-ahead.

- **`volatility_regime`** (`atr_14.rolling(window=500)` quantiles): the
  500-bar trailing window becomes a "500 observed bars" window, which per
  the gap density found in §3 of the audit (~7.4% of expected hours missing)
  will typically span slightly *more* than 500 real hours near any gap-dense
  region. **Materiality**: low — 500 bars is long enough that a handful of
  multi-hour gaps inside the window have negligible effect on a percentile
  estimate, but this should be measured, not assumed, before being certified.

**None of the above is a look-ahead defect** (§0.4): every one of these
computations only ever uses bars at or before the current row position, gap
or not. The issue is exclusively one of *silent semantic drift* — a feature
whose name implies a fixed wall-clock lookback (e.g. "momentum over the last
5 hours") no longer reliably means that near a gap — which is a data-quality
transparency issue, not a leakage issue.

## 3. Warmup semantics under a market-session gap policy

`WARMUP_BARS` (5/20/100/100/600) is currently a row-count, applied via
`_apply_warmup`'s `series.iloc[:warmup_bars] = NaN`. This correctly forces
NaN for the first N *rows* regardless of gaps — that part of the contract is
already sound and needs no change. What is **not** currently defined: whether
a bar immediately following an admitted gap should *also* be forced to NaN
(i.e., whether the warmup concept should re-trigger locally after a gap, not
just once at the start of the whole series). This project's roadmap
(§5A: "A missing bar must never accidentally become a zero return... a gap
must never silently become a synthetic candle") implies the answer should be
"the existing NaN-suppression is sufficient because no synthetic bar is ever
inserted" — no gap bar is fabricated, so there is nothing to warm up *away
from* — but this has not been explicitly ratified as policy and is proposed
here for authorization alongside the gap-tolerance decision itself, since the
two are inseparable in practice.

## 4. What this contract explicitly does NOT decide

This document defines the *vocabulary and consequences*. It does not decide:

- Whether market-session continuity should be relaxed to admit any
  particular class of real gap (that is the Decision Pack's question).
- Whether the currently-obtained GitHub-mirror dataset is an authorized
  substitute for the licensed vendor feed §7 originally contemplated (a
  separate, related question raised in the gap-semantics audit §3).
- Any numeric tolerance threshold (e.g. "gaps ≤ 4 hours inside UTC 0–4/21–23
  only") — a specific number is a policy choice with direct statistical-power
  and warmup-window consequences, not something to invent unilaterally.

## 5. Proposed authorized-implementation shape (contingent, not yet approved)

If, and only if, gap tolerance is authorized, the following implementation
shape is proposed as the mechanism (not yet implemented, not self-authorized
per §0.2/§0.9):

1. `_check_weekday_gaps` is versioned (`FEATURE_VERSION` bump, `FE-R2-003`),
   never silently edited in place under `FE-R2-002`.
2. The relaxed check classifies each weekday gap by (weekday, hour-of-day,
   gap length) against an explicit, reviewed allow-list derived from the
   audited distribution (§5 of `DATASET_VALIDATION_REPORT.md`) — not a bare
   "any gap ≤ N hours" rule, since the audit shows the real gap pattern is
   concentrated by time-of-day, not uniformly distributed.
3. Every admitted gap is logged to a structured, per-dataset gap manifest
   (timestamp span, classification, symbol) — never silently passed through
   with no record, satisfying §0.3 ("no silent data repair") by ensuring the
   *presence* of a gap remains visible even once it is no longer fatal.
4. No candle is ever synthesized to fill a gap. Rolling/lag features
   continue to operate on observed-bar position exactly as today; §2 above's
   materiality analysis is accepted as a known, bounded, disclosed property
   of observed-bar continuity — not remediated by interpolation, which
   `_check_weekday_gaps`'s own docstring and roadmap §0.3/§5A already
   forbid.
