# ML-001-R2 — Real-Market Gap-Semantics Audit

**Date**: 2026-08-18
**Scope**: Phase 1 / Phase 1A of the ML-001 Strategy Factory roadmap — audit of
`core/features/fe_r2_001.py::_check_weekday_gaps` against the real EURUSD/GBPUSD
H1 data obtained this project (`data/csv/EURUSD_H1.csv`, `data/csv/GBPUSD_H1.csv`,
see `DATASET_VALIDATION_REPORT.md` for acquisition/authenticity evidence).
**Verdict**: `SPECIFICATION_DECISION_REQUIRED = TRUE`. The invariant is not a bug —
it is a deliberately-tested, zero-tolerance design choice — but it was authored and
tested exclusively against synthetic, perfectly-continuous fixtures, and the
spec's own §7 rests on an assumption (a licensed tier-1 vendor feed) that the
data source actually obtainable in this network environment does not meet. This
audit does not resolve the decision; it characterizes it precisely enough for
someone with the authority in §0.2/§33 to decide.

---

## 1. The invariant, exactly as it exists today

`core/features/fe_r2_001.py::_check_weekday_gaps` (lines ~104–130): for every
consecutive pair of bars, if the gap between them exceeds one H1 bar, every
missing expected hourly timestamp in between must fall inside the declared
Fri 22:00 UTC – Sun 22:00 UTC weekend-closure window. If even one missing
timestamp falls outside that window, the **entire frame is rejected** with
`FeatureEngineeringError`, and no feature matrix is produced.

This is not an oversight or a stray default — it is deliberately encoded in
`ML-001-R2-CLEAN-REBUILD-SPEC.md` §7:

> Missing-bar policy: Weekday gaps >1 bar during normal trading hours are
> treated as a **data-quality violation** requiring investigation — never
> silently forward-filled or interpolated.
>
> Weekend policy: FX market closed Fri 22:00 UTC – Sun 22:00 UTC; this window
> is excluded from continuity checks, not treated as missing data.

And it is locked in by dedicated, passing tests
(`tests/test_ml_001_r2_data_quality.py`, `tests/test_ml_001_r2_adversarial.py`)
that assert a single weekday gap **must** raise. Every one of those tests was
written and has only ever been run against synthetic, perfectly-spaced
fixtures — until this session, real data has never existed in this repository
to test it against.

## 2. Underlying assumption the invariant rests on

Spec §17 ("Open Questions") states the data-source vendor is unresolved but
explicitly asserts this does **not** make §7 ambiguous:

> Real market-data vendor/source ... Blocks spec completeness? No — the data
> *protocol* (§7) is fully specified; vendor selection is a procurement action
> item, not a design ambiguity.

Read together with §7's own requirement ("Must be a real, **licensed**
market-data vendor. The old synthetic dataset is explicitly forbidden as a
substitute"), the invariant's zero-tolerance design implicitly assumes the
eventual data source would be a licensed, tier-1-quality feed with continuous
weekday ticks — the kind of feed where an unexplained weekday gap genuinely
would indicate feed corruption or an outage worth investigating and probably
rejecting.

## 3. What the real data obtained this session actually is

Per `DATASET_VALIDATION_REPORT.md`: EURUSD/GBPUSD H1, 2012-11-16 to
2022-03-05, sourced from `raw.githubusercontent.com/komo135/forex-historical-data`
— a free, unlicensed, community-published GitHub mirror. Its own upstream
provenance beyond GitHub is **not self-documented**. Authenticity (i.e., "this
is real recorded price history, not fabricated") was independently
corroborated via the 2016 Brexit GBPUSD flash-crash event reproducing to the
pip — strong evidence the *prices* are genuine — but this says nothing about
whether the feed's *tick-recording completeness* matches what a licensed
tier-1 vendor would provide. It plausibly does not: retail/aggregator feeds
are well known to drop bars during near-zero-liquidity hours rather than
record a flat/zero-volume candle.

Re-verified independently in this audit (not merely re-citing the prior
report):

| Symbol | Weekday violation events | Longest fully-compliant contiguous span |
|---|---|---|
| EURUSD | 501 | ~4 days 23 hours (≈ one trading week) |
| GBPUSD | 499 | ~4 days 23 hours |

Verified via direct execution of `_check_weekday_gaps`'s own logic against
both CSVs (same algorithm, independently re-run, not assumed from the prior
report). The missing-hour distribution concentrates in UTC hours 0–4 and
21–23 and on Sunday/Monday — i.e., the lowest-liquidity windows of the FX
week — not scattered randomly, which is the signature of a feed that drops
ticks under thin liquidity rather than one that is corrupted or reordered.

**This data source therefore fails the invariant's implicit precondition on
two, separable grounds:**

1. It is not a licensed vendor feed (§7's own explicit requirement) — an
   independent reason this specific source may not be an authorized
   substitute for what §7 actually calls for, regardless of the gap question.
2. Even setting (1) aside, its observed gap pattern is denser and more
   frequent than a zero-tolerance weekday-continuity policy allows for, in a
   way that (per the distribution above) looks like genuine low-liquidity
   non-recording rather than corruption — but "looks like" is a judgment
   call about acceptable data-quality risk, not a fact the code can verify on
   its own.

## 4. Is the invariant semantically wrong? — Determination

**No defect was found in the invariant's logic.** It does exactly what §7 and
its own tests specify, correctly and deterministically. The question is not
"is the code broken" but **"does §7's zero-tolerance weekday-gap policy, as
written, remain the correct policy once real, only-realistically-obtainable
retail-aggregated data is the input — or was it only ever intended to gate a
licensed feed this project does not currently have network access to
procure?"** That is a policy question about acceptable evidentiary standards,
not a code-correctness question, and it is explicitly reserved from
unilateral resolution by this mission's own governing rules (§0.2, §33: "You
are NOT authorized to unilaterally decide ... unresolved temporal semantics
where the specification is genuinely absent").

`SPECIFICATION_DECISION_REQUIRED = TRUE`.

See the companion `ML-001-PHASE-1A-TEMPORAL-SEMANTICS-CONTRACT.md` for the
formal temporal-continuity definitions this decision feeds into, and the
Decision Pack (delivered to the user directly) for the options, consequences,
and recommendation.
