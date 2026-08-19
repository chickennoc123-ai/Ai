# ML-001 OGD-4: Governance Closure

**Date**: August 19, 2026
**Classification**: Governance Decision Record
**Status**: OWNER DECISION RECORDED; SEAL BLOCKED ON DATA ACQUISITION

---

## Owner Governance Decision (Recorded Verbatim)

The project owner has resolved the open question raised in
`ML-001-OGD4-DATASET-SELECTION-DECISION-PACK.md` (Option A / Option E family):

```
OWNER_DECISION                          = APPROVED

PRIMARY_HOLDOUT_SOURCE                  = DUKASCOPY
PRIMARY_HOLDOUT_SYMBOL                  = EURUSD
PRIMARY_HOLDOUT_TIMEFRAME               = H1
PRIMARY_HOLDOUT_PERIOD                  = 2022-2026

INDEPENDENCE_LEVEL                      = LEVEL_3 (TEMPORAL INDEPENDENCE)

GOVERNANCE_INTERPRETATION:
    Temporal independence is SUFFICIENT for PRIMARY HOLDOUT eligibility.
    Market independence is NOT REQUIRED for the primary holdout.

    The primary holdout answers exactly one question:
    "Does a strategy developed using historical research survive on a
     genuinely later, previously unseen period of the SAME instrument?"

    Cross-market independence (EURUSD vs. a distinct asset class) is a
    SEPARATE, future validation dimension. It must not be conflated with
    primary-holdout eligibility, and it is not required to close OGD-4.
```

This resolves the governance question left open at the end of the prior
audit (`ML-001-OGD4-DATASET-SELECTION-DECISION-PACK.md`, Part 5): "Is
LEVEL_3 temporal independence sufficient, or is market independence also
required?" — **Answer: temporal independence is sufficient for the primary
holdout.** Market independence remains a distinct, separately-tracked
validation dimension for future work, not a gating requirement here.

---

## Full Governance Rule Set (as Approved)

```
OWNER_DECISION                                       = APPROVED
PRIMARY_HOLDOUT_SOURCE                               = DUKASCOPY
PRIMARY_HOLDOUT_SYMBOL                                = EURUSD
PRIMARY_HOLDOUT_TIMEFRAME                             = H1
PRIMARY_HOLDOUT_PERIOD                                = 2022-2026
INDEPENDENCE_LEVEL                                    = LEVEL_3
TEMPORAL_INDEPENDENCE                                 = REQUIRED_AND_SATISFIED
MARKET_INDEPENDENCE                                   = NOT_REQUIRED
SOURCE_INDEPENDENCE                                   = SUPPORTING_EVIDENCE_ONLY
RESEARCH_EXPOSURE                                     = MUST_BE_ZERO
OBSERVATION_ACCESS_BEFORE_SEAL                        = FORBIDDEN
OBSERVATION_ACCESS_AFTER_SEAL_BEFORE_AUTHORIZATION    = FORBIDDEN
EVALUATION_ACCESS                                     = ONE_TIME_ONLY
RESEALING                                             = FORBIDDEN
POST_SEAL_MUTATION                                    = FORBIDDEN
HOLDOUT_REPLACEMENT                                   = FORBIDDEN_AFTER_RESEARCH_BEGINS
CROSS_MARKET_VALIDATION                               = SEPARATE_FUTURE_DIMENSION
GENERATION_7                                          = NOT_STARTED
STRAT-000003                                          = NOT_CREATED
```

Each rule's meaning, in the context of this Factory:

- **TEMPORAL_INDEPENDENCE = REQUIRED_AND_SATISFIED** — Verified in the prior
  audit (`ML-001-OGD4-CANDIDATE-EVALUATION.md`, Candidate 1): the approved
  2022-2026 period is strictly after DEVELOPMENT (2012-11-16 to 2022-03-05)
  and PURE_HOLDOUT (2021-01-01 to 2021-12-31), with zero calendar overlap.
- **MARKET_INDEPENDENCE = NOT_REQUIRED** — This is the governance
  interpretation adopted today. It does not retroactively make the prior
  audit's dimension-H finding wrong (Dukascopy EURUSD 2022-2026 genuinely
  is the SAME_MARKET as DEVELOPMENT); it changes which finding is
  gating. Market independence remains explicitly tracked as a limitation
  (see §"Explicit Limitation," below), not silently dropped.
- **SOURCE_INDEPENDENCE = SUPPORTING_EVIDENCE_ONLY** — Dukascopy differs
  from KOMO135 (the DEVELOPMENT source). This strengthens the case but is
  not, on its own, what makes the holdout valid — temporal independence is
  what makes it valid.
- **RESEARCH_EXPOSURE = MUST_BE_ZERO** — Enforced in code: the Evidence
  Vault's `authorize_evaluation()` raises `ValueError` if
  `research_exposure == "EXPOSED"` at authorization time. This governance
  closure does not relax that enforcement.
- **HOLDOUT_REPLACEMENT = FORBIDDEN_AFTER_RESEARCH_BEGINS** — Once
  STRAT-000003 (or any future candidate) begins using this governance
  decision as its basis, the approved dataset identity (Dukascopy EURUSD
  H1 2022-2026) cannot be silently substituted for a different one.

---

## Explicit Limitation (Not Silently Dropped)

Approving OPTION A does not erase the finding from the prior audit. It is
carried forward explicitly:

> Dukascopy EURUSD H1 2022-2026 is the **SAME MARKET** as the DEVELOPMENT
> data (EURUSD). A future candidate validated against this holdout has
> **not** been shown to generalize across markets — only across time,
> within the same instrument. Cross-market generalization is a distinct,
> unresolved question, deliberately out of scope for OGD-4.

---

## Phase 0 Re-Verification (Not Trusted From Prior Reports)

Before recording this closure, the current repository state was
re-derived from disk, not assumed from the prior session's summary:

| Check | Result |
|---|---|
| `git status` | clean tree, correct branch (`claude/ea-factory-pro-system-bc9jaa`) |
| `STRAT-000001` / `STRAT-000002` | both `REJECTED` (registry, re-read) |
| `HYP-000001` / `HYP-000002` | `REFUTED`; `HYP-000003` blocked (unchanged) |
| Generation 7 boundary test | `test_generation7_has_not_started` — PASSING |
| Full test suite (pre-work) | 1060/1060 PASSING |
| PURE_HOLDOUT consumption | exactly 1 access (Generation 4, STRAT-000002), terminal |
| Evidence Vault module | present, but **no disk persistence** (see finding below) |
| Approved dataset on disk | **absent** — no Dukascopy/HistData 2022-2026 file anywhere in the repo |
| Network access to Dukascopy/HistData | **HTTP 403** under current network policy (re-tested, matches prior audit) |

### Discrepancy Found and Documented (Not Silently Reconciled)

Two genuine gaps were found and are recorded here rather than worked
around silently:

1. **The approved dataset does not exist anywhere in this environment**,
   and the two most direct sources for it (Dukascopy, HistData) both
   return `HTTP 403` under the current network policy. This is not an
   identity-ambiguity problem (multiple candidate files to choose between)
   — it is a **non-existence** problem. Per this task's own Phase 0/2
   instructions ("If anything differs from the reported state: STOP... If
   identity is ambiguous: STOP"), fabricating a substitute, downloading a
   different instrument/period, or synthesizing bytes was ruled out.
   **This blocks sealing.** See `ML-001-PRIMARY-HOLDOUT-SEAL-RECORD.md` for
   the full disposition.

2. **`core/factory/evidence_vault.py` had no disk-persistence method.**
   Every other registry in this codebase (`DatasetRegistry`,
   `StrategyRegistry`, `HypothesisRegistry`, `ResearchLedger`) persists to
   a JSON file under `reports/factory/`, so state survives across
   sessions. The Evidence Vault did not — a seal recorded in one Python
   process would vanish the instant that process exited, which would make
   "the holdout remains LOCKED after this task" unverifiable in any later
   session. This was fixed mechanically (same atomic-write pattern as
   `DatasetRegistry`; no governance semantics changed) so that a future
   seal, once data acquisition succeeds, will actually be durable and
   independently re-verifiable. See commit history for the diff.

   A second, related gap was fixed at the same time: `consume_dataset()`
   could previously be called directly against a `SEALED` dataset without
   ever passing through `authorize_evaluation()` — i.e. the code allowed
   `SEALED → CONSUMED` directly, silently skipping the `AUTHORIZED` state
   the enum itself defines and this task's own Phase 8 requires
   (`SEALED → AUTHORIZED → CONSUMED`, never skipping a step). This is now
   enforced: `consume_dataset()` requires a matching prior
   `authorize_evaluation()` call for the exact `(dataset_id, candidate_id)`
   pair. This is a code-correctness fix, not a governance change — nothing
   about what is *permitted* changed; what changed is that a real gap in
   *enforcement* was closed.

Neither gap is a governance-state change. Both are documented here rather
than fixed silently, per Phase 0's explicit instruction.

---

## What This Closure Does and Does Not Do

**Does:**
- Records the owner's explicit decision on the independence-interpretation
  question left open by the prior audit.
- Establishes the full governance rule set that will apply once the
  approved dataset is actually sealed.
- Fixes a mechanical persistence gap in the Evidence Vault so a future
  seal will be durable and independently verifiable.
- Fixes a mechanical state-machine gap so consumption can never skip
  authorization.

**Does not:**
- Does not seal any dataset (no such dataset exists on disk; see
  `ML-001-PRIMARY-HOLDOUT-SEAL-RECORD.md`).
- Does not create STRAT-000003 or any new candidate.
- Does not generate any new hypothesis.
- Does not access, inspect, or compute anything from holdout observations
  (none exist locally to access).
- Does not start Generation 7.
- Does not modify STRAT-000001, STRAT-000002, or PURE_HOLDOUT.

---

## Status

```
OGD4_STATUS                    = GOVERNANCE_APPROVED_PENDING_DATA_ACQUISITION
OWNER_DECISION                 = APPROVED
SEAL_STATUS                    = NOT_SEALED (BLOCKED_ON_DATA_ACQUISITION)
GENERATION_7_STATUS            = NOT_STARTED
STRAT_000003_STATUS            = NOT_CREATED
NEW_HYPOTHESES                 = 0
NEW_CANDIDATES                 = 0
PURE_HOLDOUT_REUSE             = 0
```

See `ML-001-PRIMARY-HOLDOUT-CONTRACT.md` for the durable governance
contract that will bind this holdout once sealed, and
`ML-001-PRIMARY-HOLDOUT-SEAL-RECORD.md` for the exact acquisition
blocker and what is needed to unblock it.
