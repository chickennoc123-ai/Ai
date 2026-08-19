# ML-001 Primary Holdout Acquisition Spec

**Date**: August 19, 2026
**Status**: ACTIVE — defines the acquisition contract; does not itself
constitute acquisition
**Governs**: acquisition of the dataset approved in
`ML-001-OGD4-GOVERNANCE-CLOSURE.md`

---

## 1. Approved Identity

```
instrument                 = EURUSD
timeframe                  = H1
period                     = 2022-01-01 through 2026-12-31, or the exact
                              available 2022-2026 coverage as actually
                              acquired -- the acquired file's real
                              coverage_start/coverage_end must be recorded
                              verbatim, never rounded to the nominal range
preferred_source            = Dukascopy Bank SA (primary)
documented_secondary_source  = HistData (per ML-001-OGD4-CANDIDATE-EVALUATION.md,
                              functionally equivalent audit outcome to
                              Dukascopy; not a fallback to be silently
                              substituted -- see §3)
```

## 2. Source Identity vs. File Location vs. Mirror Location

These three concepts are frequently conflated and must not be:

- **SOURCE_IDENTITY** — who actually produced the observations (e.g.
  "Dukascopy Bank SA, as a regulated tier-1 FX liquidity provider,
  publishing its own execution data"). This is a claim about *origin*.
- **FILE_LOCATION** — where the specific bytes were fetched from (a URL, a
  local path, an API endpoint). A file can be *located* somewhere without
  that location having produced the data itself.
- **MIRROR_LOCATION** — a location that redistributes data whose
  SOURCE_IDENTITY is claimed to be elsewhere. A mirror's FILE_LOCATION
  being reachable says nothing about whether its SOURCE_IDENTITY claim is
  true.

**Consequence**: a file fetched from `raw.githubusercontent.com` (a
FILE_LOCATION / MIRROR_LOCATION) that is *named* or *labeled* "Dukascopy
EURUSD 2022-2026" does not thereby have Dukascopy as its verified
SOURCE_IDENTITY. The filename is not evidence. See §3 and Rule 10 of the
governing task boundaries.

## 3. Required Provenance

Provenance is `VERIFIED` only if there is `actual_origin_evidence` —
something concrete, not the claim restated. Acceptable forms of evidence
(non-exhaustive):

- A reproducible download performed directly against the claimed
  publisher's own documented endpoint, with the request/response captured.
- A checksum match against an independently obtained, already-verified
  artifact covering an overlapping period from the same claimed publisher.
- A documented chain of custody (e.g. an open-source downloader's own
  code, run against the publisher's real API, with logs).

Not acceptable: a filename, a repository description, a claim in a
README, or "this is commonly used for X data" without a specific,
checkable link back to the publisher.

`core/factory/holdout_acquisition.py::evaluate_source_candidate()`
implements this rule mechanically: `claimed_origin` alone never sets
`provenance_status = VERIFIED`; only `actual_origin_evidence` being
non-empty and substantive can.

## 4. Required Timezone

`UTC`, explicitly. Any artifact whose declared timezone is not exactly
`"UTC"` fails the eligibility gate (`decide_primary_holdout_eligibility()`
checks `claimed_timezone == approved_timezone`). If the source only
publishes in a different timezone (e.g. broker-local time), the
conversion must be performed and documented as a transformation (§6 of
the sealing workflow, see `ML-001-PRIMARY-HOLDOUT-CONTRACT.md` §16 on
versioning) — never silently assumed.

## 5. Required Price Type

`OHLC`, mid-price basis (matching the existing DEVELOPMENT dataset's
`price_type` field in `data/csv/PROVENANCE_MANIFEST.json`). If the
acquired source publishes bid/ask instead, the mid conversion must be
recorded as an explicit, checked transformation.

## 6. Required OHLC Semantics

Standard hourly candle construction: `open` = first trade price in the
hour, `close` = last trade price in the hour, `high`/`low` = extrema
within the hour, all in the declared timezone's hour boundaries. Bars
must satisfy `high >= max(open, close)`, `low <= min(open, close)`,
`high >= low`, and all four values must be strictly positive and finite.

## 7. Required Checksums

- **File checksum**: `SHA256` of the exact bytes as downloaded, before any
  normalization.
- **Content checksum**: `SHA256` of the parsed/normalized OHLCV content
  (post-transformation, if any transformation was necessary), kept
  separate from the file checksum so tampering during normalization is
  independently detectable.

Both are `hexdigest()` strings, recorded verbatim — never truncated,
never re-derived from a different byte sequence than the one actually
sealed.

## 8. Required Acquisition Timestamp

`UTC`, ISO-8601, recorded at the moment the download actually completed —
not backdated to the coverage period, not left blank.

## 9. Required Transformation Log

If any transformation (timezone conversion, column renaming, format
conversion, deduplication) is performed between the original downloaded
artifact and the artifact that is eventually sealed, the log must record:

- original file checksum
- derived file checksum
- transformation code version/commit
- transformation parameters
- exact description of what changed (timezone shift amount, columns
  dropped/renamed, rows removed and why)
- confirmation that **no OHLC values were altered** by the transformation
  (only representation, never content) — per the governing task's Phase 5
  instruction: "If normalization changes OHLC values: STOP and reject
  unless the transformation is explicitly permitted by the holdout
  contract." No such permission exists in
  `ML-001-PRIMARY-HOLDOUT-CONTRACT.md`; therefore no transformation may
  alter OHLC values, full stop.

## 10. Required Row Count, Duplicate Count, Gap Report, Integrity Report

Produced by `core/factory/holdout_acquisition.py::validate_artifact_integrity()`:
row count, duplicate-timestamp count, OHLC-consistency-violation count,
non-positive-price count, and a gap report. See
`ML-001-PRIMARY-HOLDOUT-ACQUISITION-VALIDATION.md` for the disposition of
this requirement given no artifact currently exists to validate.

## 11. Required Source Identity Record

Every acquisition attempt is recorded as a `SourceCandidate` (see
`core/factory/holdout_acquisition.py`) with `source_id`, `source_name`,
`source_url`, `source_type` (`primary` / `documented_secondary` /
`unverified_mirror` / `user_provided`), `publisher`, `claimed_origin`,
`actual_origin_evidence`, `access_status`, `network_status`,
`license_status`, `download_method`, `download_timestamp`, and the
computed `provenance_status` / `identity_status` / `eligibility_status`.

## 12. Required Synthetic Flag

`SYNTHETIC = FALSE` must be explicitly asserted, backed by the
authenticity evidence in §3 — never defaulted to `FALSE`, never inferred
from "the numbers look plausible." `synthetic_flag=None` (undeclared) is
treated identically to `synthetic_flag=True` by
`validate_artifact_integrity()` — undeclared is not innocent.

---

## User-Provided Data Path (Acquisition Spec Phase 10)

The owner may supply the real dataset manually (file upload or another
authorized channel) instead of, or in addition to, automated acquisition.
This is a **legitimate** acquisition path, not a fallback of lesser
rigor — a manually supplied file receives **exactly** the same scrutiny as
a downloaded one.

### Expected Artifact Interface

**Accepted file formats**: CSV (preferred, matching the existing
`data/csv/EURUSD_H1.csv` convention) or Parquet. Compressed archives
(`.zip`, `.gz`) are acceptable if the compression is standard and the
uncompressed content is one of the above.

**Required columns** (CSV header or Parquet schema):
`timestamp, open, high, low, close` — `volume` is accepted if present but
not required. Column names are matched case-insensitively; ambiguous or
missing required columns cause immediate `ACCESS_FAILED`-equivalent
rejection (the artifact cannot be parsed into `CandidateArtifact.rows`).

**Required metadata** (supplied alongside the file, not inferred from it):
- claimed instrument, timeframe, timezone, price type
- claimed source / publisher
- claimed coverage start/end (must be corroborated against the actual
  parsed timestamps, not merely trusted)
- explicit `synthetic` declaration (`true`/`false`)
- a description of how the file was obtained (the `actual_origin_evidence`
  field of a `SourceCandidate` with `source_type = "user_provided"`)

**Checksum procedure**: `SHA256` of the file as supplied, computed by this
Factory's own code upon receipt — never trusted from a checksum the
supplier claims without independent recomputation.

**Provenance declaration**: the supplier must state, in writing, how they
obtained the file (direct download from the named publisher, a specific
tool, a specific date). This becomes the `actual_origin_evidence`. A bare
"trust me, it's Dukascopy data" does not satisfy §3.

**Source declaration**: which of Dukascopy (preferred) or HistData
(documented secondary) — or, if neither, an explicit statement that this
would constitute a **new** governance decision per
`ML-001-PRIMARY-HOLDOUT-CONTRACT.md` §16 (versioning rules), not a
substitution under the existing one.

**License declaration**: confirmation the data may legitimately be used
for this purpose (matches Dukascopy's own terms for research/personal use,
or the equivalent for whatever source is actually named).

### Processing a User-Provided File

1. Compute `SHA256` of the file immediately upon receipt; record it before
   any other processing.
2. Parse into `CandidateArtifact.rows`; if parsing fails, the artifact is
   rejected at that point (equivalent to `ACCESS_FAILED`) — it does not
   fall through to eligibility scoring with an empty row list silently
   treated as "no data to invalidate."
3. Run `evaluate_source_candidate()` against the supplied provenance
   declaration exactly as for any automated source — `source_type =
   "user_provided"` does not exempt it from the "claim alone is not
   evidence" rule in §3.
4. Run `validate_artifact_integrity()`, `check_independence()`, and
   `decide_primary_holdout_eligibility()` exactly as documented above.
5. Only on `ELIGIBLE` may the artifact proceed to sealing
   (`ML-001-PRIMARY-HOLDOUT-PRESEAL-PACK.md`, then `EvidenceVault`).

No shortcut exists for user-provided data. This is deliberate: the
scientific risk from an unverified but well-intentioned manual upload is
identical to the risk from an unverified automated download.
