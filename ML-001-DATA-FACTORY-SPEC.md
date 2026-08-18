# ML-001 — Data Factory Specification (Generation 1, Phase 1)

**Status**: IMPLEMENTED and VERIFIED against the real EURUSD/GBPUSD H1 datasets.
**Date**: August 18, 2026
**Code**: `core/factory/data_source_registry.py`, `core/factory/dataset_registry.py`
**Referenced by**: `ML-001-STRATEGY-RESEARCH-FACTORY-SPEC.md` §6.

---

## §1. Purpose

Turn raw external market data into a controlled, provenance-aware dataset layer — a stable, checkable identity for every file this project trains or evaluates against, independent of narrative claims about where it came from.

## §2. Data Source Registry

`core.factory.data_source_registry.DataSourceRecord`/`DataSourceRegistry`. A source describes *where* data can come from: `source_id`, `provider`, `source_url`, `access_method` (`HTTP_DOWNLOAD`/`API`/`MANUAL_UPLOAD`/`VENDOR_FEED`/`OTHER`), `coverage`, `supported_instruments`, `supported_timeframes`, `timezone_semantics`, `price_type`, `availability`, `license_status`, `provenance_confidence`.

**`license_status` defaults to `"UNKNOWN"`** — never inferred as permissive from a source merely being reachable, and never silently upgraded. The only way `license_status` becomes anything else is an explicit, separate assertion by whoever registers the source, on record as a specific claim. The one real source this project has registered (`SRC-KOMO135-FOREX-HISTORICAL-DATA`) is `license_status = "UNKNOWN"` today, honestly — its README does not state licensing terms, and this project has not independently established them.

`provenance_confidence` (`UNVERIFIED`/`PARTIALLY_VERIFIED`/`INDEPENDENTLY_VERIFIED`) records how much independent checking has actually been done — `SRC-KOMO135-FOREX-HISTORICAL-DATA` is `PARTIALLY_VERIFIED` (checked against one independently-known historical event, the 2016 Brexit GBPUSD flash crash — a single check, not exhaustive corroboration).

## §3. Dataset Registry

`core.factory.dataset_registry.DatasetRecord`/`DatasetRegistry`. A dataset is one specific, checksummed file: `dataset_id`, `instrument`, `timeframe`, `source_id`, `source_url`, `download_timestamp`, `timezone`, `price_type`, `coverage_start`/`coverage_end`, `row_count`, `duplicate_count`, `missing_bar_count`, `gap_report`, `checksum` (raw source file), `file_checksum` (normalized on-disk file), `download_method`, `synthetic`, `provenance_status`, `integrity_status`, `dataset_version`, `verification_method`.

## §4. Provenance Contract — enforced in code, not just documented

`DatasetRecord.__post_init__` hard-enforces (raises `DatasetSpecError` otherwise):

- `synthetic=True` requires `provenance_status="KNOWN_SYNTHETIC"`, and vice versa — a dataset can never simultaneously claim to be synthetic and to have verified real-market provenance.
- `provenance_status` in (`VERIFIED`, `VERIFIED_WITH_QUALIFICATION`) requires a non-empty `verification_method` — a bare assertion of "verified" with nothing describing how is rejected at construction time.
- `provenance_status` defaults to no value the caller doesn't explicitly choose from a closed set (`UNVERIFIED`/`VERIFIED`/`VERIFIED_WITH_QUALIFICATION`/`KNOWN_SYNTHETIC`) — an unrecognized value raises immediately.

`DatasetRecord.is_real_market_data_eligible` (a property, always recomputed, never cached/asserted) is `True` only if `synthetic=False`, `provenance_status` is `VERIFIED` or `VERIFIED_WITH_QUALIFICATION`, and `integrity_status="PASS"` — all three, every time. `assert_real_market_data_eligible()` raises `RealMarketDataEligibilityError` otherwise; every script in this project that is about to claim `REAL_MARKET_DATA = TRUE` should call it first (`tests/test_generation1_foundation_integration.py` does, in the end-to-end path).

## §5. Ingestion — what actually happened (this project's real data, not a hypothetical)

The real EURUSD/GBPUSD H1 data (`data/csv/EURUSD_H1.csv`, `data/csv/GBPUSD_H1.csv`) was acquired in a prior session (full narrative: `DATASET_VALIDATION_REPORT.md`) — deterministic `curl` download, no resampling, no silent gap-filling, one disclosed timezone assumption (UTC−5, no DST, not independently confirmed for this specific source — see §6). This task did not re-download or re-acquire anything; it **registered** the already-existing, already-validated files into the new Data Factory registries, recomputing both files' checksums fresh from disk and confirming they match the previously-recorded `PROVENANCE_MANIFEST.json` values exactly (not trusted blindly — independently re-verified, per this task's own "do not trust previous reports over current on-disk evidence" instruction).

```
EURUSD: on-disk checksum matches PROVENANCE_MANIFEST.json: True
GBPUSD: on-disk checksum matches PROVENANCE_MANIFEST.json: True
```

**Network access was not attempted for any new source in this task** — external egress remains policy-restricted per prior sessions' findings, and Phase 1's own instruction is to build the infrastructure first, not download more data. No blocker needed recording beyond what `DATASET_VALIDATION_REPORT.md` already discloses.

## §6. Dataset Identity

`dataset_id` (`DATASET-{SYMBOL}-H1-KOMO135-V1`) plus `dataset_version` distinguish same-source/same-instrument/same-timeframe files that differ by download or transformation — a re-download or a re-normalization would receive a new `dataset_version`, never overwrite the existing record (`DatasetRegistry.register()` raises `DuplicateDatasetError` on an id collision; there is no update-in-place method).

## §7. Data Quality Contract — integrates with, does not replace, existing validation

This module does not reimplement `core/features/fe_r2_001.py`'s validation (`_validate_ohlcv`, `_check_weekday_gaps`/`_check_weekday_gaps_v3`) — it catalogs the *result* of that validation (`missing_bar_count`, `gap_report`, `integrity_status`) as durable metadata. The underlying checks (monotonic timestamps, duplicates, OHLC consistency, positive prices, abnormal moves, missing bars, gaps, timezone, symbol/timeframe identity, weekend/session behavior) were already run and disclosed in `DATASET_VALIDATION_REPORT.md`/`ML-001-R2-REAL-DATA-LEAKAGE-PROVENANCE-AUDIT.md` — this registry does not silently relax any of that.

## §8. Gap Policy Audit (task 1.7)

`FE-R2-002`'s original `_check_weekday_gaps` and `FE-R2-003`'s additive `_check_weekday_gaps_v3` both still exist as distinct functions (`tests/test_feature_factory.py::TestExistingGapPolicyPreserved`, confirms neither is the other and the original still rejects an arbitrary mid-week gap exactly as before). Gap handling is deterministic (same input index always produces the same admission decision), gap policy is versioned (`FEATURE_VERSION = "FE-R2-003"`), and every admitted gap for the real data is enumerated, not summarized away, in `data/csv/GAP_ADMISSION_MANIFEST.json` (502 admitted gaps for EURUSD, individually timestamped with reasons). No missing market bar is fabricated anywhere in this pipeline — admission means "this gap is accepted as a real market closure," never "a value was invented to fill it."

## §9. Dataset Validation Report

`DATASET_VALIDATION_REPORT.md` — pre-existing, updated by this task (§ "Verdict update") to correct its stale `PIPELINE_COMPATIBILITY = BLOCKED` claim, which predated the FE-R2-003 fix that unblocked it (real training/WFA subsequently succeeded, per `ML-001-R2-REAL-DATA-TRAINING-AND-WALKFORWARD-REPORT.md`).

## §10. Phase 1 Exit Criteria — status

```
REAL_MARKET_DATA = TRUE           (DATASET-EURUSD-H1-KOMO135-V1, DATASET-GBPUSD-H1-KOMO135-V1)
PROVENANCE = VERIFIED_WITH_QUALIFICATION (qualification: source timezone convention assumed,
                                           not independently confirmed for this specific repo)
DATA_INTEGRITY = PASS
SYNTHETIC_SUBSTITUTION = NONE
ARTIFACTS_REPRODUCIBLE = TRUE (file checksums independently recomputed from disk and matched;
                                see tests/test_data_factory.py::TestRealDatasetsAreActuallyRegisteredAndEligible)
```

Both real datasets pass the complete Data Factory contract (`DatasetRecord.is_real_market_data_eligible == True` for both, verified by test against the production registry).
