# ML-001 Primary Holdout Acquisition — Validation Report

**Date**: August 19, 2026
**Status**: NOT APPLICABLE — no artifact was acquired to validate

---

## Why This Report Is Empty of Findings

Phase 6 of the acquisition workflow (`ML-001-PRIMARY-HOLDOUT-ACQUISITION-SPEC.md`)
requires validating an acquired artifact's timestamp monotonicity,
duplicate timestamps, OHLC consistency, price positivity, timezone,
weekend behavior, symbol identity, timeframe identity, coverage, missing
bars, unexplained gaps, corruption, and file checksum.

**No artifact was acquired** (see
`ML-001-PRIMARY-HOLDOUT-ACQUISITION-BLOCKER.md` for the full account of
every source attempted and why each failed). There is nothing to run
these checks against, and running them against nothing — or against a
placeholder — would produce a report that looks like validation occurred
when it did not. That is exactly the outcome Rule 15-17 of the governing
task forbid ("DO NOT seal an empty, partial, placeholder, synthetic, or
unverified payload"; "DO NOT claim SEAL_STATUS = SEALED until actual bytes
have been independently verified").

## What Is Actually Ready

The validation logic itself is implemented and tested independently of
any specific artifact, so that the moment a real candidate artifact
exists, this report can be regenerated honestly and immediately:

- `core/factory/holdout_acquisition.py::validate_artifact_integrity()` —
  implements monotonicity, duplicate-timestamp, OHLC-consistency,
  non-positive-price, and synthetic-flag checks.
- `core/factory/holdout_acquisition.py::check_independence()` — implements
  temporal-overlap and research-exposure checks against known prior
  research periods (DEVELOPMENT: 2012-11-16 to 2022-03-05; PURE_HOLDOUT:
  2021-01-01 to 2021-12-31).
- `core/factory/holdout_acquisition.py::decide_primary_holdout_eligibility()`
  — combines source verification, integrity, and independence into a
  single ELIGIBLE/REJECTED decision, gated on instrument, timeframe,
  timezone, and coverage sufficiency as well.
- `tests/test_holdout_acquisition.py` — 22 tests proving this logic
  correctly rejects synthetic data, incomplete data, wrong
  instrument/timeframe/timezone, unknown/failed provenance, and temporal
  overlap, while correctly accepting a genuinely clean candidate. All 22
  passing.

## Disposition

```
DATA_INTEGRITY_STATUS = NOT_APPLICABLE (no artifact acquired)
VALIDATION_LOGIC_STATUS = IMPLEMENTED_AND_TESTED (ready for a real artifact)
```

This report will be superseded by a real validation report the moment
Phase 4 (acquisition) of the workflow actually succeeds. Until then,
recording "PASS" here would be false.
