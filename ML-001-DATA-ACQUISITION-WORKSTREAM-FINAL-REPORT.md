# ML-001 Data Acquisition Workstream — Final Report

**Date**: August 19, 2026
**Scope**: Establish a legitimate acquisition path for the OGD-4-approved
primary holdout. Not Generation 7. Not candidate generation.

---

## Status Fields (Never Collapsed Into a Single PASS)

```
GOVERNANCE_STATUS                = APPROVED (ML-001-OGD4-GOVERNANCE-CLOSURE.md,
                                    unchanged by this workstream)
ACQUISITION_STATUS               = BLOCKED
PROVENANCE_STATUS                = NOT_APPLICABLE (no artifact acquired to assess)
DATA_INTEGRITY_STATUS            = NOT_APPLICABLE (no artifact acquired to assess)
INDEPENDENCE_STATUS              = NOT_APPLICABLE (no artifact acquired to assess)
SEAL_STATUS                      = NOT_SEALED
EVALUATION_AUTHORIZATION         = FALSE
CONSUMPTION_STATUS               = NOT_APPLICABLE (nothing sealed, nothing to consume)
GENERATION_7_STATUS              = NOT_STARTED
```

```
TOTAL_SOURCES_ATTEMPTED          = 11
TOTAL_SOURCES_REJECTED           = 0  (none reached a provenance-based rejection --
                                    all failed earlier, at the access stage)
TOTAL_SOURCES_ELIGIBLE           = 0
NETWORK_BLOCKED_SOURCES          = 10 (9 financial-data hosts + api.github.com)
PROVENANCE_FAILED_SOURCES        = 0  (the one reachable candidate, the existing
                                    KOMO135 GitHub mirror, failed on coverage --
                                    it does not contain 2022-2026 -- not on
                                    provenance; it was never asked to stand in
                                    for Dukascopy)
CHECKSUM_VERIFIED_ARTIFACTS      = 0
```

---

## What This Workstream Was Asked to Do

Per the task: establish a **legitimate acquisition path** for the
approved primary holdout (Dukascopy EURUSD H1 2022-2026), not to acquire
it by any means necessary. The distinction matters: a path can be
legitimate and ready while still currently blocked by circumstances
outside this task's authority to change (an organizational egress
policy).

## What Was Actually Done

### 1. Baseline re-verification (Phase 0)

Re-derived from disk, not trusted from the prior session's summary: clean
git tree at the correct branch/commit, `STRAT-000001`/`STRAT-000002` both
`REJECTED`, no `STRAT-000003`, no new hypotheses beyond `HYP-000001/2/3`,
no `evidence_vault.json` (nothing previously sealed), Generation 7
boundary test passing.

### 2. Acquisition contract defined (Phase 1)

`ML-001-PRIMARY-HOLDOUT-ACQUISITION-SPEC.md` — the complete identity,
provenance, timezone, price-type, OHLC-semantics, checksum,
transformation-log, and synthetic-flag requirements, plus an explicit
`SOURCE_IDENTITY` vs. `FILE_LOCATION` vs. `MIRROR_LOCATION` distinction
(the core of Rule 10: a mirror's reachability says nothing about whether
its origin claim is true).

### 3. Exhaustive source search (Phase 2-3)

Local filesystem, `/mnt/attach`, `/mnt/user-data`, and the repository
itself: confirmed empty of any relevant artifact. Nine financial-data
hosts (Dukascopy ×3 endpoints, HistData ×2, plus five other
generically-plausible FX/market-data APIs considered as alternates) tested
via two independent channels — proxy-routed `curl` and the first-party
`WebFetch` tool — to rule out a client-specific problem. All nine returned
explicit policy-denial responses. The egress proxy's own status endpoint
confirmed these are **organizational policy decisions**
(`"gateway answered 403 to CONNECT (policy denial or upstream failure)"`),
not transient failures or Dukascopy/HistData-side outages. The proxy's own
documentation instructs: "Do not retry or route around it — report the
blocked host." That instruction was followed.

The one reachable host in this environment, `raw.githubusercontent.com`,
was checked against the exact GitHub repository already used (with
documented, if qualified, provenance) for the existing DEVELOPMENT
dataset. Its EURUSD file ends 2022-03-04/05 — it does not extend into
2022-2026. `api.github.com` itself is blocked, so a broader search of
that account's other repositories or branches was not possible.

Full detail, including every URL and every response, in
`ML-001-PRIMARY-HOLDOUT-ACQUISITION-BLOCKER.md`.

### 4. Source verification logic built and tested (Phase 3)

`core/factory/holdout_acquisition.py::evaluate_source_candidate()`
implements the rule that a claimed origin is never self-authenticating:
`provenance_status` only becomes `VERIFIED` when concrete
`actual_origin_evidence` exists, distinctly from `claimed_origin`. A
reachable mirror named "Dukascopy ..." with no such evidence resolves to
`PROVENANCE_FAILED`, not "probably fine."

### 5. Acquisition not attempted against unverifiable data (Phase 4)

No download occurred, because every reachable path either had no data
(local/mounted) or lacked the required coverage (the one reachable GitHub
mirror). Nothing was fetched from an unverified mirror and re-labeled.

### 6. Normalization: not applicable (Phase 5)

No artifact exists to normalize. Nothing was invented to normalize.

### 7. Validation: not applicable, but the validator is built and tested (Phase 6)

`core/factory/holdout_acquisition.py::validate_artifact_integrity()`
implements monotonicity, duplicate-timestamp, OHLC-consistency,
non-positive-price, and synthetic-flag checks, all fail-closed (an
artifact with zero rows fails; an undeclared synthetic flag fails exactly
like a declared-`True` one). See
`ML-001-PRIMARY-HOLDOUT-ACQUISITION-VALIDATION.md` for the explicit
"not applicable" disposition and why fabricating a validation result was
rejected.

### 8. Independence validation: not applicable, but the checker is built and tested (Phase 7)

`core/factory/holdout_acquisition.py::check_independence()` checks
declared coverage against every known prior research period
(DEVELOPMENT: 2012-11-16 to 2022-03-05; PURE_HOLDOUT: 2021-01-01 to
2021-12-31), using the same overlap logic as the rest of OGD-4
(`core.factory.data_independence`). `research_exposure=None` (genuinely
unknown) is treated identically to confirmed exposure — never as
innocent.

### 9. Eligibility decision logic built and tested (Phase 8)

`core/factory/holdout_acquisition.py::decide_primary_holdout_eligibility()`
combines source, integrity, and independence into a single
ELIGIBLE/REJECTED decision, gated additionally on instrument, timeframe,
timezone (`UTC` required, explicitly), and minimum coverage (200 days). A
single failing dimension rejects the whole candidate — proven by
`tests/test_holdout_acquisition.py::test_one_bad_dimension_is_enough_to_reject_an_otherwise_clean_candidate`.
A fully clean synthetic-fixture candidate (never claimed as real data)
correctly reaches `ELIGIBLE`, proving the gate is discriminating, not
merely a rejection stub —
`test_fully_clean_candidate_reaches_eligible`.

### 10. Blocker documented, not routed around (Phase 9)

`ML-001-PRIMARY-HOLDOUT-ACQUISITION-BLOCKER.md` — full source-attempt
table with every `source_id`, URL, `access_status`, `network_status`, and
result. HistData recorded explicitly as `ALTERNATIVE_HOLDOUT_CANDIDATE`
(equally blocked in this session; substitution would still require fresh
owner authorization per `ML-001-PRIMARY-HOLDOUT-CONTRACT.md` §16, since
the governance closure named Dukascopy specifically).

### 11. User-provided data path documented (Phase 10)

`ML-001-PRIMARY-HOLDOUT-ACQUISITION-SPEC.md`, "User-Provided Data Path"
section: accepted formats, required columns/metadata, checksum procedure,
provenance/source/license declarations, and the explicit rule that a
manually supplied file receives identical scrutiny to a downloaded one —
no shortcut for convenience.

### 12. Pre-seal package: not created (Phase 11)

No eligible dataset was acquired, so no pre-seal package was produced.
Creating one against a placeholder would misrepresent the state of the
work.

### 13. Sealing: not performed (Phase 12)

No `EvidenceVault.seal_dataset()` call was made. `reports/factory/evidence_vault.json`
does not exist. Confirmed by direct filesystem check immediately before
writing this report.

### 14. Adversarial testing (Phase 14)

`tests/test_holdout_acquisition.py` — 22 new tests covering the
acquisition-gate-specific scenarios from the task's Phase 14 list (fake
Dukascopy filename, fake source metadata, synthetic data, incomplete
data, wrong timeframe/symbol/timezone, provenance UNKNOWN, research
exposure UNKNOWN, temporal overlap, mirror without provenance, plus
checksum-determinism sanity checks and a full clean-candidate-passes
integration test). All 22 passing.

The remaining Phase 14 scenarios (altered bytes/metadata after seal,
resealing, replacing a sealed artifact, consuming before/twice,
persistence/reload, fresh-process verification, substituted bytes against
an existing seal) are inherent to `EvidenceVault`'s state machine, not the
acquisition gate, and were already covered by the 23-test suite in
`tests/test_ogd4_evidence_vault.py` from the prior OGD-4 governance-closure
task — cross-referenced explicitly at the bottom of
`tests/test_holdout_acquisition.py` rather than duplicated.

### 15. This report (Phase 15)

---

## Non-Negotiable Rules Compliance

| Rule | Compliance |
|---|---|
| 1. No STRAT-000003 | ✓ Confirmed absent from registry |
| 2. No new hypotheses | ✓ Only `HYP-000001/2/3` exist, unchanged |
| 3. No training/validation of any strategy | ✓ None performed |
| 4. No PURE_HOLDOUT access | ✓ Untouched; its consumption history (1 access, Generation 4) is unchanged |
| 5. No governance alteration for convenience | ✓ `ML-001-OGD4-GOVERNANCE-CLOSURE.md` unmodified; Dukascopy remains the named source |
| 6-7. No synthesis/interpolation of missing data | ✓ Nothing synthesized; the acquisition gate actively rejects undeclared/positive synthetic flags |
| 8. No fabricated timestamps | ✓ N/A — no artifact acquired |
| 9. No fabricated provenance | ✓ N/A — no artifact acquired; the gate rejects unevidenced provenance claims by construction |
| 10. No unverified mirror labeled "Dukascopy" | ✓ The one reachable mirror was checked on its own coverage, never relabeled; `evaluate_source_candidate()` enforces this rule in code |
| 11. No egress bypass | ✓ Proxy's "do not route around it" instruction followed exactly |
| 12. No unauthorized credentials/services | ✓ None used |
| 13. No scraping around restrictions | ✓ None attempted |
| 14. No silent substitution | ✓ HistData recorded separately as `ALTERNATIVE_HOLDOUT_CANDIDATE`, not substituted |
| 15-17. No fabricated/placeholder seal claim | ✓ `SEAL_STATUS = NOT_SEALED`, stated plainly throughout |
| 18. Blocked → report blocker, not fabricated success | ✓ This report |

---

## Real Dataset Acquired / Provenance Verified / Holdout Sealed

```
REAL_DATASET_ACQUIRED        = NO
DATASET_PROVENANCE_VERIFIED  = NO (nothing to verify)
HOLDOUT_SEALED                = NO
GENERATION_7_STARTED          = NO
```

---

## What Is Ready for the Moment Acquisition Succeeds

1. `ML-001-PRIMARY-HOLDOUT-ACQUISITION-SPEC.md` — the full contract,
   including the user-provided-data interface.
2. `core/factory/holdout_acquisition.py` — source verification, artifact
   integrity validation, independence checking, and eligibility decision,
   all implemented and unit-tested against synthetic fixtures (22 tests).
3. `core/factory/evidence_vault.py` — cryptographic sealing, persistence,
   one-time authorization/consumption, all tested (23 tests, from the
   prior governance-closure task).
4. The full chain — source evaluation → artifact validation → independence
   check → eligibility decision → (only then) sealing — is wired and
   tested end-to-end using fixture data, so the only missing piece is the
   real bytes.

The instant a legitimately provenanced artifact becomes available (owner
upload, or a future change to network policy), acquisition can proceed
through this exact pipeline without further infrastructure work.
