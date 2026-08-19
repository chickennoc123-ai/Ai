# ML-001 — OGD-4: Independent Evidence Governance Decision

**Date**: August 19, 2026
**Status**: DECISION FRAMEWORK (implementation follows in Phase 2+)
**Governs**: Future candidate evaluation via independent evidence

---

## Executive Summary

This document establishes the formal governance framework that decides whether a dataset qualifies as **independent evidence** for evaluating a new strategy candidate. OGD-4 was opened by Generation 6 (Phase 4) because PURE_HOLDOUT (consumed in Generation 4) has no ready replacement, and the Factory must not generate candidates without proven independent evaluation rigor.

The decision framework answers 20 critical questions that define "independent evidence" in machine-checkable terms.

---

## Question 1: What qualifies as independent evaluation evidence?

**Definition:**

Evidence is **independent** if and only if:

1. **Temporal Independence** (LEVEL_3+): The dataset covers a time period that was **not visible** during hypothesis design, feature engineering, parameter tuning, or candidate development.
   
   - LEVEL_3: Genuinely unseen time period (e.g., 2022-2026 data, if all hypothesis work used 2021 or earlier)
   - LEVEL_4: Different instrument/market
   - LEVEL_5: Independently sourced from unrelated provider
   - LEVEL_6: Forward observation in real time
   
   **NOT Independent:**
   - Data from the same historical period used in training (LEVEL_2)
   - Repartitioned data from the same observations (LEVEL_1)
   - Same raw bars with different processing (LEVEL_0)

2. **Research Exposure** (NONE): The dataset was **never** used to:
   - Generate or select hypotheses
   - Design features
   - Tune parameters
   - Justify candidate design
   - Inform rejection/prioritization decisions
   - Analyze post-mortems

3. **Source Quality** (VERIFIED): The data comes from a legitimate, reachable source with documented provenance.

4. **Integrity** (PASSED): The data has been validated for completeness, no duplicates, no gaps, no corruption.

5. **Immutability** (SEALED): The dataset is cryptographically sealed before any evaluation access. Post-seal mutation is detectably prevented.

---

## Question 2: What makes a dataset "pre-sealed"?

**Definition:**

A dataset is **pre-sealed** if and only if:

1. **Acquisition is Complete**: All raw data has been downloaded/obtained in full.

2. **Provenance is Verified**: The source, timestamp, and chain-of-custody are documented and auditable.

3. **Integrity Checked**: Checksums (row count, duplicate detection, gap analysis) have been computed and recorded.

4. **Seal is Applied BEFORE Research Exposure**: 
   - The seal is computed and recorded in the Evidence Vault
   - **Then** the Factory proceeds to candidate research
   - The seal is locked (immutable from that point forward)

5. **Seal Hash is Reproducible**: A fresh process can independently compute the same seal given the same data + metadata.

**What is NOT pre-sealed:**

- Datasets downloaded after hypothesis work has begun
- Datasets with metadata modified after download
- Datasets where raw files were accessed before seal computation
- Datasets that existed but were not formally sealed at a specific timestamp
- Datasets where the seal computation involved process-local state

---

## Question 3: What constitutes research exposure?

**Definition:**

A dataset is **research-exposed** if the Factory accessed it for any of:

- **Hypothesis Generation**: Data used to justify mechanism or falsification condition
- **Hypothesis Selection**: Data used to rank/prioritize hypotheses
- **Feature Design**: Data used to engineer features or validate feature formulas
- **Parameter Design**: Data used to select/tune parameters or ranges
- **Candidate Development**: Any intermediate work toward creating the candidate spec
- **Post-Mortem Analysis**: Data used to understand why a previous candidate failed
- **Research Prioritization**: Data used to decide which research avenue to pursue next
- **Failure-Library Updates**: Data used to classify or understand failure modes

**Legitimate Use (not exposure):**

- Metadata inspection (dataset exists, has X bars, covers Y period)
- Checksum verification (data integrity, not data content)
- Seal verification (immutability proof, not observation inspection)
- Lineage queries (which source this came from, not its values)
- Eligibility gate audit (verification that it's sealed, not access to observations)

---

## Question 4: What constitutes candidate exposure?

**Definition:**

A candidate is **exposed** to a dataset if:

1. Any of its **design elements** (mechanism, features, parameters) were informed by observing that dataset's price bars or derived statistics.

2. Its **evaluation results** have been examined before the candidate was frozen.

3. Its **spec** has been modified after evaluation against that dataset (optimization after feedback).

**Exposure is Permanent:**

Once a candidate has accessed a dataset for evaluation, the candidate is marked as having "consumed" that dataset. Further evaluation against the same dataset (for the same candidate) may be auditable but reuses the evidence.

**Exposure Timing Matters:**

- Candidate spec frozen **before** dataset seal → acceptable (no design exposure)
- Candidate spec modified **after** dataset seal but **before** evaluation → research exposure (invalidates independence claim)
- Candidate spec modified **after** evaluation → **forbidden** (non-negotiable principle #13)

---

## Question 5: What constitutes temporal independence?

**Definition:**

A dataset is **temporally independent** if its coverage period is **entirely outside** the time window used for hypothesis/feature/parameter development.

**Precise Definition:**

Let:
- T_dev_start = earliest timestamp any data was accessed during research (hypothesis phase start)
- T_dev_end = latest timestamp any data was accessed during research
- T_eval_start = dataset coverage start
- T_eval_end = dataset coverage end

Temporal independence requires:

- **NO** T_eval ∈ [T_dev_start, T_dev_end] (no overlap)
- **AND** T_eval_start > T_dev_end (evaluation data is strictly later)

**Examples:**

✓ Development: 2000-2021 H1 EURUSD  
✓ Evaluation: 2022-2026 H1 EURUSD  
✓ **Independent** (2022 is after 2021 cutoff)

✗ Development: 2000-2021 H1 EURUSD  
✗ Evaluation: 2021-2022 H1 EURUSD  
✗ **NOT independent** (overlap at 2021)

✗ Development: 2000-2021 H1 EURUSD  
✗ Evaluation: 2000-2021 (different processor)  
✗ **NOT independent** (same time window, different processing is LEVEL_1, not LEVEL_3+)

**LEVEL_3 minimum**: Later time period with same instrument/timeframe.

---

## Question 6: What constitutes cross-market independence?

**Definition:**

Two instruments have **cross-market independence** if their price movements are uncorrelated enough that success in one does **not** automatically imply success in the other.

**Classification:**

| Relationship | Independence | Notes |
|---|---|---|
| **SAME_MARKET** | NONE | EURUSD vs EURUSD → NOT independent |
| **RELATED_MARKET** | WEAK | Same currency pair, different timeframe (e.g., H1 vs D1) → NOT independent |
| **CROSS_CURRENCY** | MODERATE | Same base (EURUSD vs EURJPY) → possible cross-market validation, but not primary independence |
| **CORRELATED_MARKET** | WEAK | ρ > 0.7 (GBPUSD vs EURUSD correlate 0.8) → NOT independent enough |
| **DISTINCT_MARKET** | STRONG | Different asset classes (EURUSD vs SPY) → independent for robustness testing |

**UNKNOWN = NOT_ELIGIBLE:**

If correlation is unknown, classify as UNKNOWN and mark the dataset as **not independently eligible**.

**Cross-Market Does Not Replace Temporal Independence:**

A dataset in a different market (DISTINCT_MARKET) at an overlapping time period is NOT an independent holdout. It provides cross-market robustness evidence, not temporal independence evidence.

---

## Question 7: What constitutes source independence?

**Definition:**

Two datasets have **source independence** if they originate from different, unrelated data providers and cannot be traced back to a common upstream source.

**Independent Sources:**

- Dukascopy vs HistData (different brokers, different data processes)
- Yahoo Finance vs Dukascopy (different business models, different collection)
- FRED vs proprietary broker data (macro indicators vs price data)
- Manually-constructed vs API-downloaded (different collection methods)

**NOT Independent Sources:**

- Dukascopy raw + Dukascopy aggregated (same provider)
- Yahoo data resold through another vendor (same upstream)
- Broker A's data → Broker B acquires Broker A (circular dependency)
- Any dataset derived from the same base historical period

**Source Verification:**

Every source must be verified for:
- Reachability (not blocked by network policy)
- Legitimacy (not a proxy, mirror, or unauthorized scrape)
- Provenance (documented origin)
- Legal authorization (correctly licensed or public domain)

---

## Question 8: What constitutes unknown overlap?

**Definition:**

Overlap is **UNKNOWN** if:

1. The datasets share the same time period, but we cannot definitively determine if their price bars are identical.

2. Checksums are not available or not comparable.

3. Timestamp/OHLC matching was not performed.

4. The relationship between datasets cannot be determined from metadata alone.

**Treatment of UNKNOWN:**

UNKNOWN overlap = **NOT_ELIGIBLE**

Conservative rule: If we cannot prove no overlap, we must assume overlap.

This prevents silent acceptance of datasets that might share observations without explicit proof.

**How to Move from UNKNOWN to DETERMINED:**

1. Compare checksums (byte-for-byte comparison)
2. Compare timestamp ranges (detect overlaps)
3. Spot-check OHLC values (identify identical price bars)
4. Verify source (confirm different providers or different time periods)

---

## Question 9: What happens when provenance is incomplete?

**Definition:**

Provenance is **incomplete** if:

- Source is documented as "UNKNOWN"
- Download timestamp is not recorded
- Timezone is ambiguous
- File path/checksum is missing
- Chain of custody is broken
- Intermediate processing steps are undocumented

**Treatment of Incomplete Provenance:**

Incomplete → **INELIGIBLE**

Do not guess or reconstruct provenance retroactively. If the chain of custody is broken, the dataset cannot be a reliable independent holdout.

**What Counts as Complete Provenance:**

- Source: documented, verified, reachable
- Download timestamp: recorded with timezone
- Download method: explicit (API call, file download, etc.)
- Checksum: computed immediately upon receipt
- File path: documented, immutable
- Processing: any derivation steps recorded
- Legal status: authorization confirmed (public domain, creative commons, licensed purchase, etc.)

---

## Question 10: What happens when source access becomes unavailable?

**Definition:**

Source access is **unavailable** if:

- The host is unreachable (network error, timeout)
- Network policy blocks access (proxy denial, CONNECT failure)
- The source is taken down or moved
- Authentication fails (credentials expired)
- The specific data period is delisted/removed
- Terms of service prohibit access

**Treatment:**

If a source becomes unavailable **after** dataset acquisition and sealing:
- The dataset remains sealed and eligible (data is already acquired)
- The seal hash is still reproducible (by re-verifying the stored bytes)

If a source is unavailable **before** acquisition:
- Record ACCESS_FAILED
- Do not fabricate a substitute
- Do not use cached/mirror data without explicit documentation
- Leave the decision to governance: accept the gap or attempt alternative sources

---

## Question 11: What happens if the dataset was downloaded before sealing?

**Definition:**

A dataset is **downloaded-before-sealed** if:

- Raw bytes exist on disk
- Checksum was not computed at download time
- Seal was computed later

**Risk:**

If the factory already knew the dataset existed before the seal was applied, was any research exposure possible?

**Treatment:**

Downloaded-before-sealed is **allowed** if:

1. **Seal Computation Timing is Documented**: Exactly when was the checksum/seal computed? Before or after any hypothesis work?

2. **No Earlier Access**: Can we prove that the factory's observation code never read the file before seal time?

3. **File Integrity**: Has the file been modified since download? (checksum unchanged)

If we cannot definitively prove the file was never accessed before seal time, mark the dataset:

PROVENANCE = INCOMPLETE

and make it **INELIGIBLE**.

---

## Question 12: What happens if metadata was visible but observations were not?

**Definition:**

Metadata visibility without observation access occurs when:

- The factory knows a dataset exists, its ID, its coverage period, its checksum
- But the factory code is architecturally prevented from accessing the OHLC price bars

**Example:**

```python
metadata = sealed_store.get_metadata("EVAL_2022_EURUSD")
# metadata returns: dataset_id, coverage, checksum, instrument, timeframe
# but sealed_store.get_observations("EVAL_2022_EURUSD") raises PermissionError
```

**Treatment:**

Metadata visibility without observation access is **ACCEPTABLE** because:

1. The factory cannot accidentally optimize against the data.
2. Hypothesis research proceeds without data knowledge.
3. The seal can be verified before access is authorized.
4. Observation access is deferred to evaluation phase (governed separately).

This is the intended architecture: metadata always visible, observations locked until authorization.

---

## Question 13: Can a previously visible dataset ever become eligible?

**Definition:**

A previously visible dataset is one where:

- The factory code previously read its observations
- Features were designed based on it
- Parameters were tuned based on it
- Results were analyzed based on it

**Treatment:**

Previously visible datasets are **PERMANENTLY INELIGIBLE**.

Once a dataset has been "seen," it cannot be unsealed and recast as independent evidence.

**Example:**

```
2022: Factory uses 2021 EURUSD for feature design
      (now research-exposed)

2026: Someone proposes: "use 2021 EURUSD as holdout"
      
NO. 2021 EURUSD is research-exposed.
    It cannot become independent evidence.
    The Factory already knows its behavior.
```

---

## Question 14: What does ONE-TIME evaluation mean?

**Definition:**

ONE-TIME evaluation means:

1. **Unsealing is Authorized**: A specific governance authorization (with timestamp, candidate ID, authorization code) is required.

2. **Observation Access is Granted Once**: The evaluation code can read the dataset's price bars exactly one time.

3. **Result is Locked**: Once evaluation completes, the result is recorded and the dataset is marked CONSUMED.

4. **Resealing is Forbidden**: The dataset cannot be re-sealed and evaluated again, even against the same candidate.

5. **Retesting is Forbidden**: The same candidate cannot re-evaluate against the same dataset.

**What ONE-TIME Does NOT Allow:**

- Multiple candidates evaluating against the same dataset (without explicit multiple-testing accounting)
- The same candidate re-evaluating against the same dataset
- Post-evaluation optimization using the results
- Candidate spec modification after evaluation

---

## Question 15: What permanently consumes an evidence dataset?

**Definition:**

An evidence dataset is **permanently consumed** when:

1. **Authorization is Granted**: Governance authorizes evaluation access.

2. **Evaluation Executes**: The candidate's strategy is run against the dataset's price bars.

3. **Result is Recorded**: Metrics (PnL, drawdown, Sharpe, etc.) are computed and stored.

4. **Consumption is Marked**: The dataset's internal state transitions from SEALED to CONSUMED.

5. **No Further Access Allowed**: Attempting to unseal the dataset again raises an error.

**Consumption Prevents:**

- Re-evaluation of the same candidate against the same dataset
- Evaluation of a different candidate against the same dataset (unless governed)
- Any modification to the dataset before/after evaluation
- Dataset resealing

---

## Question 16: Can a failed candidate consume the dataset?

**Definition:**

A failed candidate is one that:

- Evaluated against the independent dataset
- Did not pass the economic validation gate
- Was rejected

**Treatment:**

A failed candidate's evaluation **does** consume the dataset.

Once ANY candidate has evaluated against a sealed dataset, the dataset is consumed, regardless of the outcome.

**Rationale:**

The dataset provides evidence either way (pass or fail). If the candidate fails, using the same dataset for a new candidate introduces multiple-testing complications. The safe default is to mark it consumed.

**Exception (requires explicit governance):**

If the Factory's governance explicitly allows multiple candidates to evaluate against one sealed dataset, multiple-testing accounting must be activated to track and correct for the additional trials.

---

## Question 17: Can multiple candidates share one independent holdout?

**Definition:**

Multiple candidates sharing one holdout occurs when:

- Candidate A evaluates against Dataset X
- Candidate B evaluates against Dataset X
- Both results are used to validate their respective designs

**Treatment:**

Multiple candidates sharing one holdout is **ALLOWED** but **REQUIRES GOVERNANCE**:

1. **Multiple-Testing Accounting**: The system must track that Dataset X has been used for 2 trials.

2. **Statistical Correction**: Any subsequent statistical claims must account for the increased trials. (Bonferroni correction, family-wise error rate, etc.)

3. **Explicit Authorization**: Governance must explicitly approve the multi-candidate usage before the first evaluation.

4. **Clear Disclosure**: Reports must disclose "Candidate A and B were both evaluated against the same holdout; results are not independent."

**Default (no explicit governance):**

One candidate per dataset. Reuse requires decision.

---

## Question 18: If multiple candidates share it, how is multiple-testing handled?

**Definition:**

Multiple-testing adjustment accounts for the fact that if we evaluate many candidates against the same holdout, we increase the false-positive rate.

**Mechanism:**

The Factory maintains a cumulative trial counter:

```
TRIALS_AGAINST_DATASET_X = 2 (Candidate A, Candidate B)
CUMULATIVE_TRIALS_THIS_FACTORY = 2 + 2 (from prior generations) = 4
```

Any statistical significance claim must include:

- Unadjusted p-value (what the raw result shows)
- Adjusted p-value (accounting for multiple trials)
- Bonferroni-adjusted threshold (0.05 / 4 trials = 0.0125)
- Family-wise error rate

**No Silent Increases:**

The system must not accumulate trials silently. Every evaluation against a holdout that counts toward multiple-testing is explicitly recorded.

---

## Question 19: Can the dataset ever be resealed?

**Definition:**

Resealing means:

- Taking a consumed dataset
- Computing a new seal
- Attempting to use it again

**Treatment:**

Resealing is **FORBIDDEN**.

Once a dataset is consumed (seal transitioned from SEALED → CONSUMED), it remains CONSUMED permanently. No new seal, no re-evaluation, no second chance.

**Rationale:**

If we allowed resealing, the one-time constraint is violated. The multiple-testing accounting breaks down. The audit trail becomes ambiguous.

---

## Question 20: Can the raw data ever be modified after sealing?

**Definition:**

Post-seal modification is any change to:

- OHLC price bars
- Timestamps
- File bytes
- Intermediate processing
- Checksum

**Treatment:**

Post-seal modification is **FORBIDDEN** and **DETECTABLY PREVENTED**.

Verification:
1. Recompute the checksum of the stored file
2. Compare to the seal's recorded checksum
3. If they differ, the data has been modified
4. Reject any evaluation attempt

The seal acts as a tamper-evident seal. If the seal hash does not match, the data is corrupted/modified and the dataset is rejected.

---

## Summary: OGD-4 Decision Framework

**Independent Evidence Definition (Compact):**

```
INDEPENDENT EVIDENCE = 

  (TEMPORAL_INDEPENDENCE ≥ LEVEL_3)
  AND (RESEARCH_EXPOSURE = NONE)
  AND (CANDIDATE_EXPOSURE = NONE)
  AND (SOURCE_VERIFIED)
  AND (INTEGRITY_PASSED)
  AND (SEALED_BEFORE_RESEARCH)
  AND (CHECKSUM_MATCHES)
  AND (OVERLAP ≠ UNKNOWN)
  AND (PROVENANCE_COMPLETE)
```

**Key Rules (Do Not Invert):**

1. **UNKNOWN = NOT_ELIGIBLE**
2. **LATER_TIMESTAMP ≠ AUTOMATIC_INDEPENDENCE**
3. **ONCE_CONSUMED = NEVER_AGAIN**
4. **ONE_CANDIDATE_DEFAULT** (multiple requires governance)
5. **RESEALING_FORBIDDEN**
6. **POST_SEAL_MUTATION_FORBIDDEN**

---

## What This Enables

Once OGD-4 is formally established and implemented in code:

**Generation 7 can proceed IF:**

1. An independent dataset is acquired and sealed
2. The seal is verified
3. The dataset passes the eligibility gate
4. Governance authorizes candidate evaluation
5. Candidate evaluation is performed
6. Results are recorded
7. Dataset is marked consumed
8. Lineage is recorded

OR

**Generation 7 does NOT proceed:**

If no dataset satisfies the OGD-4 criteria, report honestly and do not generate candidates.

This framework ensures that future candidates are validated against evidence that is genuinely independent, not merely different or later or convenient.
