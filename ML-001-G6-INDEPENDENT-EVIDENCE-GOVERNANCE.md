# ML-001 — Generation 6: Independent Evidence & Controlled Discovery
## Phase 1-2: Data Independence Contract & Overlap Engine

**Date**: August 19, 2026
**Status**: `INDEPENDENT_EVIDENCE_STATUS = DEFINED`
**Baseline from Generation 5**: All gates remain; no new candidates until proven independent evidence exists

---

## 1. Data Independence Classification

A formal six-level classification framework for evidence independence:

| Level | Name | Definition | Example |
|-------|------|-----------|---------|
| **LEVEL_0** | Same Observations | Identical rows | PURE_HOLDOUT data (once consumed) |
| **LEVEL_1** | Different Processing | Same rows, different calculation | Same bars, different cost model |
| **LEVEL_2** | Different Split | Train/test resplit of same historical data | Same 2021 EURUSD, different partition |
| **LEVEL_3** | Unseen Time Period | Genuinely later timestamp range | 2022 data (after 2021 training cutoff) |
| **LEVEL_4** | New Instrument | Different symbol/market | GBPUSD (not EURUSD) |
| **LEVEL_5** | Independently Sourced | Unrelated data source | Dukascopy data vs broker data |
| **LEVEL_6** | Forward/Paper | Genuine forward observation | Live 2026 data (not backtest) |

**Critical rule**: LEVEL_3 is the minimum for temporal independence to serve as a holdout replacement. LEVEL_4+ provides additional diversification but cannot substitute for temporal unseen-ness alone.

## 2. Overlap Detection Engine

Machine-checkable detection of overlaps between datasets.

### 2.1 Overlap Types Detected

- **Timestamp overlap**: bars from overlapping time periods
- **Instrument overlap**: same symbol
- **Timeframe overlap**: same bar duration (H1, D1, etc.)
- **Price overlap**: identical OHLC values
- **Source overlap**: same data provider
- **Checksum identity**: byte-for-byte identical files

### 2.2 Overlap Classification

| Status | Meaning | Eligibility |
|--------|---------|-------------|
| **IDENTICAL_DATA** | Same checksums | NOT_ELIGIBLE (re-use) |
| **SUBSTANTIAL_OVERLAP** | >90% timestamp overlap | NOT_ELIGIBLE |
| **PARTIAL_OVERLAP** | 10-90% overlap | UNCERTAIN (requires governance) |
| **NO_OVERLAP** | <10% overlap | ELIGIBLE |
| **UNKNOWN** | Cannot determine | NOT_ELIGIBLE (conservative) |

**Critical rule**: UNKNOWN overlap is treated as NOT_ELIGIBLE. Unknowns do not count as "independent."

## 3. Research Exposure Tracking

Every dataset must be tracked for exposure to research decisions.

### 3.1 Exposure Types

- EXPOSED_TO_HYPOTHESIS_GENERATION
- EXPOSED_TO_HYPOTHESIS_SELECTION
- EXPOSED_TO_FEATURE_DESIGN
- EXPOSED_TO_PARAMETER_DESIGN
- EXPOSED_TO_CANDIDATE_GENERATION
- EXPOSED_TO_CANDIDATE_REJECTION
- EXPOSED_TO_POSTMORTEM
- EXPOSED_TO_RESEARCH_PRIORITIZATION

Any dataset with ANY of these exposures is marked FULLY_EXPOSED and becomes ineligible for independent validation.

### 3.2 Data Exposure Audit Trail

Every access to any dataset that influences research is recorded:

```
timestamp | dataset_id | research_phase | decision | impact
```

This prevents silent research exposure.

## 4. Sealed Evaluation Store

Once a dataset is designated for evaluation, it becomes sealed:

### 4.1 Accessibility

- **Metadata accessible**: dataset_id, checksum, coverage dates, instrument, timeframe
- **Observations NOT accessible**: research code cannot inspect price bars
- **Economic evaluation requires**: explicit authorization code + audit recording

### 4.2 Access Audit Trail

Every evaluation access creates an indelible record:

```json
{
  "dataset_id": "EVAL_2022_EURUSD",
  "candidate_id": "STRAT-000003",
  "access_timestamp": "2026-08-19T10:15:00Z",
  "access_purpose": "CANDIDATE_VALIDATION",
  "code_version": "generation6_v1",
  "results_checksum": "abc123..."
}
```

### 4.3 Single-Use Constraint

PURE_HOLDOUT remains consumed exactly once (Generation 4). No re-sealed, no re-released, no re-evaluated.

## 5. Holdout Policy

Generation 6 enforces three holdout rules:

1. **No reuse of consumed holdout**: PURE_HOLDOUT from Generation 4 is terminal
2. **No fabricated holdout**: copying/renaming/reseeding does not create independence
3. **No random re-split**: different train/test partition of same data is not independent

A new candidate requires genuinely new independent evidence from one of:
- Later time period (LEVEL_3+)
- New instrument/market (LEVEL_4+)
- Independent source (LEVEL_5)
- Forward validation (LEVEL_6)

## 6. Independent Data Eligibility Gate

All seven checks must pass:

1. ✓ PROVENANCE = VERIFIED
2. ✓ SYNTHETIC = FALSE (raw market data only)
3. ✓ DATA_INTEGRITY = PASS (no gaps, duplicates, missing bars)
4. ✓ OVERLAP = NONE or explicitly governed (never UNKNOWN)
5. ✓ RESEARCH_EXPOSURE = NONE
6. ✓ INDEPENDENCE = SUFFICIENT (LEVEL_3+)
7. ✓ CHECKSUM = VERIFIED

Failure of any check → NOT_ELIGIBLE.

## 7. Generation 5 Research Budget Enforcement

The immutable Generation 5 budget is ENFORCED:

- max_new_hypotheses = 3
- max_new_candidates = 1
- max_candidates_per_family = 1
- max_search_space_size_per_hypothesis = 50

**No silent increase.** If budget is exhausted, candidate generation stops.

## 8. Cross-Market Independence Classification

Different symbols ≠ automatic independence.

### 8.1 Market Relationships

| Relationship | Example | Independence | Notes |
|--------------|---------|--------------|-------|
| SAME_MARKET | EURUSD vs EURUSD | NO | Exact same |
| RELATED_MARKET | EURUSD vs EURUSD (diff TF) | NO | Same pair, different timeframe |
| CROSS_CURRENCY | EURUSD vs EURJPY | MODERATE | Share one currency leg |
| CORRELATED_MARKET | GBPUSD vs EURUSD (ρ=0.8) | WEAK | High correlation despite different bases |
| DISTINCT_MARKET | EURUSD vs SPY | STRONG | Different asset classes |

**Critical rule**: Correlation > 0.7 downgrades independence even if symbols differ.

## 9. Non-Negotiable Boundaries Preserved

All Generation 5 boundaries remain:

- ✓ No modification of rejected candidates (STRAT-000001, STRAT-000002)
- ✓ No resurrection of refuted hypotheses (HYP-000001, HYP-000002)
- ✓ HYP-000003 ineligible until horizon issue resolved
- ✓ No fabricated access
- ✓ No network-policy bypass
- ✓ Multiple-testing counters not reset
- ✓ No PROVEN_EDGE claims
- ✓ Generation 7 not started

## 10. Completion Criteria for Phase 1-2

- ✓ Data independence contract formally defined
- ✓ Overlap engine machine-checkable
- ✓ Research exposure tracking operational
- ✓ Sealed evaluation store implemented
- ✓ Holdout policy enforced
- ✓ Eligibility gate implemented
- ✓ Cross-market independence classified
- ✓ Adversarial tests passing (holdout reuse, overlap bypass, exposure concealment)
- ✓ All 1047 tests passing
