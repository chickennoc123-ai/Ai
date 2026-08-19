# ML-001 Primary Holdout Contract

**Date**: August 19, 2026
**Status**: ACTIVE GOVERNANCE CONTRACT (binds the primary holdout once sealed)
**Applies to**: Dukascopy EURUSD H1 2022-2026 (per `ML-001-OGD4-GOVERNANCE-CLOSURE.md`)

This contract governs how the Factory may create, seal, authorize, and
consume the ML-001 primary holdout dataset. It is durable: it applies to
this holdout and to any future primary holdout approved under the same
governance pattern, until explicitly superseded.

---

## 1. Purpose

The primary holdout exists to answer exactly one question, and only that
question:

> **Does a strategy developed using historical research survive on a
> genuinely later, previously unseen period of the same instrument?**

It is a test of temporal generalization within one market. It is
deliberately not a test of cross-market generalization, cross-timeframe
generalization, or robustness to a different data provider's
microstructure. Those are legitimate future questions, but conflating them
with this one dilutes what a PASS or FAIL on the primary holdout actually
means.

## 2. Approved Instrument

EURUSD. Chosen because it is the instrument STRAT-000001 and
STRAT-000002 were developed and rejected against — the primary holdout
must test the same market the research was conducted in, or "survives on
unseen data" and "happens to work on a different market" become
indistinguishable.

## 3. Approved Timeframe

H1 (hourly bars). Matches the DEVELOPMENT and PURE_HOLDOUT timeframe. A
different timeframe would require a new economic-compatibility audit
(spread model, bar construction, session semantics) before it could serve
as a like-for-like holdout.

## 4. Independence Definition

**LEVEL_3 — Unseen time period** is the independence level this holdout
satisfies, and is sufficient for primary-holdout eligibility under this
contract. Concretely:

- The holdout's coverage period must have **zero calendar overlap** with
  any period used in DEVELOPMENT, VALIDATION, or PURE_HOLDOUT for this
  instrument.
- A later `download_timestamp` alone is **not** sufficient — the
  underlying observations' coverage period is what must be unseen, not
  merely the date the file was fetched. (This is enforced conceptually by
  requiring `independence_level` to be set explicitly at seal time, never
  inferred from `download_timestamp`.)
- `independence_level == "UNKNOWN"` is never eligible for authorization —
  enforced in code (`EvidenceVault.authorize_evaluation` raises
  `ValueError` on `UNKNOWN`).

## 5. What Market Independence Does and Does Not Mean Here

**Does not mean**: the primary holdout is not required to be, and in this
approved case is not, a different market from DEVELOPMENT. EURUSD 2022-2026
tests the same currency pair as EURUSD 2012-2022.

**Does mean**: cross-market independence (e.g., EURUSD vs. SPY, or EURUSD
vs. EURJPY) remains a real and useful concept — it is simply a **separate,
future validation dimension**, tracked independently, with its own
economic-compatibility requirements (cost model, session semantics,
timeframe). A future candidate that passes the primary holdout has
demonstrated temporal survival within EURUSD. It has demonstrated nothing
about cross-market portability. Any report that describes a
primary-holdout PASS as "the strategy generalizes" without that caveat is
misrepresenting the evidence.

## 6. Research Exposure Prohibition

Before sealing, and continuously afterward, the following must hold for
the sealed dataset's **observations** (not its metadata):

- Never read during hypothesis generation.
- Never read during feature design.
- Never read during parameter selection.
- Never read during candidate generation or rejection.
- Never read during model training.
- Never read during post-mortem or failure-library analysis.
- Never read during search prioritization or strategy selection.

Metadata (that the dataset exists, its coverage dates, its instrument, its
row count) is public and may be known freely — this is the pre-research
firewall's design (§7). It is **observation** exposure that is forbidden.

If exposure cannot be proven absent, `research_exposure` must be recorded
as `EXPOSED` (or, if genuinely unknown, the dataset is treated as
`NOT_ELIGIBLE` — never as innocent by default). This is enforced in code:
`authorize_evaluation()` rejects `research_exposure == "EXPOSED"`.

## 7. Pre-Seal Requirements

Before `seal_dataset()` may be called:

1. `register_dataset_unsealed()` must have recorded complete, honest
   metadata — source, URL, coverage, row count, timezone, price type,
   download method and timestamp. No field may be guessed.
2. Real-market provenance must be established: not synthetic, not
   interpolated, not gap-filled.
3. Data integrity must be checked: chronology, duplicates, OHLC
   consistency, implausible prices, timezone consistency.
4. None of the above steps may involve inspecting the data for anything
   other than integrity/provenance validation — no strategy-relevant
   analysis (trend detection, volatility characterization, signal
   backtesting) is permitted at this stage.

## 8. Post-Seal Restrictions

Once `seal_dataset()` succeeds:

- **Resealing is forbidden.** `seal_dataset()` raises `ValueError` if the
  dataset is not in `UNSEALED` status — this includes a dataset already
  in `SEALED` status, not merely `CONSUMED`.
- **Post-seal mutation is forbidden and detectable.** Any change to the
  underlying bytes or to the metadata fields included in the seal
  computation changes `combined_seal_hash`; `verify_seal()` against the
  original bytes will then fail. This is a structural guarantee (SHA256),
  not a policy promise.
- **Observations remain inaccessible** until an explicit
  `authorize_evaluation()` call succeeds. `get_observation_access_denied()`
  raises `PermissionError` for any status other than an active
  authorization.

## 9. One-Time Evaluation

`authorize_evaluation()` may be called for a given `(dataset_id,
candidate_id)` pair exactly once in the dataset's lifetime, and only while
the dataset is in `SEALED` status. Authorization transitions the dataset
to `AUTHORIZED`. From `AUTHORIZED`, `consume_dataset()` may be called
exactly once, transitioning to `CONSUMED` — a terminal status. There is no
path back to `SEALED` or `AUTHORIZED` from `CONSUMED`, and no path to a
second `CONSUMED` transition. This state machine is enforced in code, not
merely documented (see `core/factory/evidence_vault.py`).

## 10. Candidate Freezing Requirement

A candidate may only be authorized against this holdout after its
specification is frozen (matching the existing Generation 4 pattern:
`candidate_freeze.py`, `CANDIDATE_FREEZE_SNAPSHOT.json`). The
`candidate_spec_checksum` parameter to `authorize_evaluation()` exists to
bind the authorization to one exact, immutable specification — not to "the
current state of whatever STRAT-000003 happens to be" at authorization
time.

## 11. Multiple-Testing Accounting

The holdout itself must never become a strategy-selection tool. Before any
authorization:

- The Factory must have an accurate count of `TOTAL_STRATEGIES_TESTED`,
  `TOTAL_HYPOTHESES_TESTED`, search-space size, and family counts — the
  existing `core/factory/research_accounting.py` /
  `SEARCH_ACCOUNTING.json` machinery.
- `EvidenceConsumptionRecord.cumulative_trials` and `bonferroni_threshold`
  exist specifically so that, if this holdout is ever shared across
  multiple candidates (which requires separate, explicit governance — see
  §"Multiple-Candidate Sharing" below), the statistical correction is
  applied and recorded, not silently omitted.
- The holdout's actual observations remain hidden until authorization; a
  future holdout result may only be interpreted **after** the candidate is
  frozen, never used to iteratively pick which candidate to freeze.

### Multiple-Candidate Sharing

By default, this holdout is scoped to a single candidate
(`ONE_CANDIDATE_DEFAULT`, per `ML-001-OGD4-INDEPENDENT-EVIDENCE-DECISION.md`
Q17). Sharing it across multiple candidates requires an explicit,
separate governance decision at the time it is proposed — this contract
does not pre-authorize it.

## 12. Failure Semantics

If a candidate evaluated against this holdout fails:

- The candidate is marked `REJECTED`, exactly as STRAT-000001 and
  STRAT-000002 were.
- The `EvidenceConsumptionRecord` for that evaluation remains permanent —
  a failed evaluation still consumes the holdout. There is no "it didn't
  really count because it failed" exception (OGD-4 Q16: "Can a failed
  candidate consume the dataset? YES").
- `EDGE_STATUS` remains (or reverts to) `NO_EDGE_FOUND` unless the
  evaluation genuinely supports otherwise, per the existing EVG
  (Economic Validation Gate) contract.

## 13. Rejection Semantics

A `REJECTED` candidate's rejection is permanent under the existing Factory
contract (Non-Negotiable Principles #1-2, re-affirmed by
`test_generation7_has_not_started`). This applies identically whether the
rejection came from PURE_HOLDOUT (STRAT-000002, Generation 4) or from this
new primary holdout.

## 14. No-Rescue Rule

**This is explicit and non-negotiable:**

If a future candidate (e.g. STRAT-000003) reaches this holdout evaluation
and **fails**:

- STRAT-000003 becomes `REJECTED`.
- It may **not** be modified and re-evaluated against the same holdout.
  The holdout is `CONSUMED` at that point — `authorize_evaluation()` and
  `consume_dataset()` both refuse a second pass, enforced in code.
- Any materially changed strategy must become a new immutable candidate
  (`STRAT-000004` or later) under the Factory's existing versioning
  contract — and, per §9-11, that new candidate needs its own explicit
  evaluation-evidence plan; it does not inherit access to this now-consumed
  holdout.
- The consumed holdout can never be used to rescue the original candidate,
  regardless of how small the intended change is claimed to be.

## 15. No-Research-After-Reveal Rule

Once a candidate has been authorized against this holdout and the holdout
has been consumed, the observations that were revealed during that
evaluation may not be fed back into hypothesis generation, feature design,
or parameter tuning for any subsequent candidate. Doing so would silently
convert a "held-out" evaluation into a "used-in-development" one after the
fact — the exact contamination this entire framework exists to prevent.
Any subsequent candidate that appears to reflect knowledge of this
holdout's revealed observations must be flagged as `RESEARCH_EXPOSED`
under §6, applied retroactively to the new candidate, not just the
dataset.

## 16. Versioning Rules

- The approved dataset identity (source, instrument, timeframe, coverage
  period, checksum) is fixed at the moment of governance approval
  (`ML-001-OGD4-GOVERNANCE-CLOSURE.md`) and bound cryptographically at the
  moment of sealing. Neither may be silently changed.
- If data acquisition ultimately requires a materially different file than
  what was approved (different exact date range, different exact source
  endpoint), that is a **new** governance decision, not a substitution
  under this contract. See `ML-001-PRIMARY-HOLDOUT-SEAL-RECORD.md` for the
  current acquisition status.
- This contract itself may be superseded only by an explicit, dated,
  written governance decision — never by silent edit.

---

## Compliance Enforcement Summary

| Rule | Enforced By |
|---|---|
| No resealing | `EvidenceVault.seal_dataset()` status check |
| No post-seal mutation (undetected) | SHA256 seal computation + `verify_seal()` |
| No observation access before authorization | `get_observation_access_denied()` |
| One-time evaluation | `AUTHORIZED`/`CONSUMED` state machine |
| No consumption without authorization | `consume_dataset()` authorization-record check |
| No authorization of EXPOSED datasets | `authorize_evaluation()` exposure check |
| No authorization of UNKNOWN independence | `authorize_evaluation()` independence check |
| Seal reproducibility | `verify_seal()`, persisted vault, subprocess-verified test |

Full test coverage: `tests/test_ogd4_evidence_vault.py`.
