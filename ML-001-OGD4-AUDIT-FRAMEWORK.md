# OGD-4 Dataset Audit Framework

**Date**: August 19, 2026  
**Purpose**: Rigorous evaluation of candidate datasets against OGD-4 independence contract  
**Methodology**: 20-dimensional classification (PASS/FAIL/UNKNOWN/NOT_APPLICABLE)

---

## Core Principle

**PREFER: No dataset**  
**OVER: A questionable dataset**

If a dataset cannot achieve PASS on all 20 dimensions, it is NOT_ELIGIBLE.

UNKNOWN = NOT_ELIGIBLE (unless existing governance explicitly permits).

---

## The 20 Audit Dimensions

### A. PROVENANCE (Can we verify data origin?)

**Definition**: Complete documented chain from original source to ML-001  
**Criteria**:
- Source explicitly identified
- Download method documented
- Download timestamp recorded
- Source URL accessible
- Source still operational

**Classifications**:
- **PASS**: Source verified; chain complete; URL accessible
- **FAIL**: Source cannot be verified; chain broken
- **UNKNOWN**: Source partially documented; access unclear
- **NOT_APPLICABLE**: N/A for synthetic data

---

### B. AUTHENTICITY (Is this real market data or synthetic?)

**Definition**: Data represents actual market execution, not simulation/derivation  
**Criteria**:
- Data comes from real market (exchange, broker, aggregator)
- NOT generated from model
- NOT filled-gap synthetic
- NOT imputed missing values
- NOT interpolated prices

**Classifications**:
- **PASS**: Confirmed real market data
- **FAIL**: Synthetic, simulated, or fabricated
- **UNKNOWN**: Origin unclear; could be synthetic
- **NOT_APPLICABLE**: For synthetic data (intentional)

---

### C. SYNTHETIC STATUS (Has this dataset been explicitly evaluated as real?)

**Definition**: Dataset has passed formal data-authenticity audit  
**Criteria**:
- No synthetic claim in metadata
- Integrity audit passed
- Real market eligibility confirmed
- Gap classification documented

**Classifications**:
- **PASS**: Confirmed NOT synthetic
- **FAIL**: Confirmed synthetic
- **UNKNOWN**: Status not explicitly determined
- **NOT_APPLICABLE**: N/A if by design synthetic

---

### D. DATA INTEGRITY (Are the OHLC bars clean?)

**Definition**: No duplicates, gaps, or anomalies that would skew evaluation  
**Criteria**:
- No duplicate timestamps
- No missing bars (or documented gaps)
- No implausible prices (e.g., zero)
- No timezone shifts mid-series
- Checksum stable across copies

**Classifications**:
- **PASS**: Integrity audit passed; gaps documented
- **FAIL**: Duplicates, missing bars, or corruption detected
- **UNKNOWN**: Integrity not verified
- **NOT_APPLICABLE**: N/A for non-OHLC data

---

### E. TEMPORAL INDEPENDENCE (Does this data NOT overlap prior ML-001 usage?)

**Definition**: No observation used in hypothesis/feature/parameter/model work  
**Criteria**:
- Coverage does NOT overlap DEVELOPMENT (2012-11-16 to 2022-03-05)
- Coverage does NOT overlap VALIDATION (subset of above)
- Coverage does NOT overlap PURE_HOLDOUT (2021-01-01 to 2021-12-31)
- NO gaps that could create accidental overlap
- Later timestamp alone is INSUFFICIENT

**Classifications**:
- **PASS**: Complete temporal separation confirmed
- **FAIL**: Overlap detected
- **UNKNOWN**: Overlap status unclear
- **NOT_APPLICABLE**: N/A for same-period data

---

### F. RESEARCH EXPOSURE (Were observations used in hypothesis generation?)

**Definition**: Dataset was NOT exposed to research decisions  
**Criteria**:
- Observations NOT reviewed during hypothesis creation
- Observations NOT analyzed during feature engineering
- Observations NOT consulted during parameter tuning
- Observations NOT used in strategy design
- Metadata exposure does NOT count (metadata is public knowledge)

**Classifications**:
- **PASS**: No research exposure documented or inferred
- **FAIL**: Exposure confirmed; dataset contaminated
- **UNKNOWN**: Exposure status unclear
- **NOT_APPLICABLE**: N/A for synthetic/theoretical datasets

---

### G. CANDIDATE EXPOSURE (Were observations known during STRAT development?)

**Definition**: Dataset was NOT revealed or accessible during candidate design  
**Criteria**:
- Candidate specification was finalized BEFORE seal
- Candidate spec NOT modified post-seal
- Candidate author(s) did NOT access observations
- Candidate result was NOT reviewed pre-release against this data

**Classifications**:
- **PASS**: No candidate exposure; sealed before candidate work
- **FAIL**: Exposure confirmed
- **UNKNOWN**: Exposure status unclear
- **NOT_APPLICABLE**: N/A for generic datasets

---

### H. MARKET INDEPENDENCE (Is this a different market, not just a different symbol?)

**Definition**: Dataset represents a market distinct from DEVELOPMENT market  
**Criteria**:
- **SAME_MARKET**: Same currency pair (EURUSD vs EURUSD) = NOT independent
- **CROSS_CURRENCY**: Different base/quote (EURUSD vs EURJPY) = RELATED, not fully independent
- **DISTINCT_MARKET**: Different asset class (EURUSD vs SPY) = Market independent
- **CORRELATED_MARKET**: Correlated but separate (different stocks) = Requires analysis

**Classifications**:
- **PASS**: Confirmed distinct market (different asset class or traded venue)
- **FAIL**: Same market
- **UNKNOWN**: Market relationship unclear
- **NOT_APPLICABLE**: N/A for cross-market testing

---

### I. SOURCE INDEPENDENCE (Is this from a different provider/feed?)

**Definition**: Data NOT from the same data provider as DEVELOPMENT  
**Criteria**:
- Provider explicitly different from KOMO135 (used in DEVELOPMENT)
- Provider network distinct (not same vendor re-branded)
- Data processing pipeline different
- Checksum different (different source → different bytes)

**Classifications**:
- **PASS**: Different provider confirmed
- **FAIL**: Same provider
- **UNKNOWN**: Provider relationship unclear
- **NOT_APPLICABLE**: N/A if single provider is acceptable

---

### J. TIMEZONE CERTAINTY (Is the timezone unambiguous and documented?)

**Definition**: All timestamps have explicit timezone; no conversion errors  
**Criteria**:
- Timezone explicitly stated (UTC, EST, etc.)
- Bar timestamps are consistent
- Session boundaries are correct for market
- No hidden daylight-saving shifts
- Documentation matches implementation

**Classifications**:
- **PASS**: Timezone explicit and verified
- **FAIL**: Timezone ambiguous or incorrect
- **UNKNOWN**: Timezone not documented
- **NOT_APPLICABLE**: N/A for UTC-only data

---

### K. SCHEMA COMPATIBILITY (Do bars fit the expected format?)

**Definition**: OHLC bar structure matches ML-001 economic model expectations  
**Criteria**:
- Contains open, high, low, close
- Contains volume (or documented as N/A)
- Contains timestamp
- Price type consistent (e.g., bid/ask vs mid)
- Bar construction method documented

**Classifications**:
- **PASS**: Schema matches; no transformation needed
- **FAIL**: Schema incompatible
- **UNKNOWN**: Schema not documented
- **NOT_APPLICABLE**: N/A for non-OHLC data

---

### L. COST-MODEL COMPATIBILITY (Can ML-001's cost model apply?)

**Definition**: Dataset has documented spread/commission assumptions compatible with economics model  
**Criteria**:
- Instrument has known spread or spread model
- Commission structure documented
- Slippage model applies
- Market microstructure understood

**Classifications**:
- **PASS**: Cost model applies; assumptions clear
- **FAIL**: Cost assumptions incompatible
- **UNKNOWN**: Cost model not established
- **NOT_APPLICABLE**: N/A for hypothetical testing

---

### M. INSTRUMENT COMPATIBILITY (Is the traded instrument compatible with ML-001?)

**Definition**: Instrument is tradeable under ML-001's scope  
**Criteria**:
- Instrument matches scope (EURUSD primary, cross-rates secondary, equities tertiary)
- Hours of operation documented
- Liquidity sufficient for entry/exit
- Contract specification stable

**Classifications**:
- **PASS**: Instrument fully compatible
- **FAIL**: Instrument out of scope
- **UNKNOWN**: Compatibility unclear
- **NOT_APPLICABLE**: N/A for scope expansion testing

---

### N. TIMEFRAME COMPATIBILITY (Is the bar size/frequency compatible?)

**Definition**: Timeframe (H1, D1, M5, etc.) is consistent with ML-001's model  
**Criteria**:
- Timeframe explicitly specified
- Bar construction consistent across data
- Session semantics correct
- No gap-filling or interpolation

**Classifications**:
- **PASS**: Timeframe matches expectations
- **FAIL**: Timeframe incompatible
- **UNKNOWN**: Timeframe not specified
- **NOT_APPLICABLE**: N/A if multiple timeframes acceptable

---

### O. COVERAGE SUFFICIENCY (Is there enough data for rigorous evaluation?)

**Definition**: Dataset contains sufficient bars for statistical power  
**Criteria**:
- Minimum 200 days (4800 hours at H1) recommended
- Sufficient to generate 50-100+ trades in backtests
- Covers multiple market regimes (trending, ranging, volatile)
- Recent enough to reflect current market conditions

**Classifications**:
- **PASS**: Coverage sufficient for evaluation
- **FAIL**: Insufficient coverage; statistically weak
- **UNKNOWN**: Coverage length not specified
- **NOT_APPLICABLE**: N/A for spot checks

---

### P. REPRODUCIBILITY (Can we rebuild the dataset from checksum?)

**Definition**: Dataset is bit-reproducible from stable source  
**Criteria**:
- Checksum stable across downloads
- Source data does not change retroactively
- Download method is reproducible
- Verification possible in fresh process

**Classifications**:
- **PASS**: Fully reproducible
- **FAIL**: Source unstable; checksum changes
- **UNKNOWN**: Reproducibility not verified
- **NOT_APPLICABLE**: N/A for live data streams

---

### Q. CRYPTOGRAPHIC SEALABILITY (Can the Evidence Vault seal this?)

**Definition**: Dataset can be cryptographically sealed without mutation  
**Criteria**:
- Data bytes stable (no hidden encoding changes)
- Metadata can be deterministically serialized
- Checksum can be computed and stored
- Verification code can recompute checksum

**Classifications**:
- **PASS**: Readily sealable
- **FAIL**: Data too volatile or complex
- **UNKNOWN**: Sealability not tested
- **NOT_APPLICABLE**: N/A for live streaming

---

### R. ONE-TIME ACCESS FEASIBILITY (Can the Vault enforce single use?)

**Definition**: Architecture supports loading data once and blocking re-access  
**Criteria**:
- Data can be loaded into memory (or mmap)
- Vault can store parsed observations
- Observations can be cleared after consumption
- No re-download mechanism exists

**Classifications**:
- **PASS**: One-time access enforced
- **FAIL**: Architecture requires repeated access
- **UNKNOWN**: Architecture not specified
- **NOT_APPLICABLE**: N/A for online learning

---

### S. MULTIPLE-TESTING IMPLICATIONS (Can multiple candidates share this holdout?)

**Definition**: Dataset can be used by multiple candidates with proper statistical correction  
**Criteria**:
- Size sufficient for Bonferroni correction
- Independent across candidate evaluations
- Can track cumulative trials
- Multiple-testing accounting clear

**Classifications**:
- **PASS**: Multiple use is feasible with accounting
- **FAIL**: Single-use only
- **UNKNOWN**: Implications unclear
- **NOT_APPLICABLE**: N/A for single-candidate design

---

### T. GOVERNANCE CONTAMINATION RISK (Could choosing this dataset introduce bias?)

**Definition**: Dataset selection itself does not leak information about strategy  
**Criteria**:
- Dataset selection is NOT based on strategy performance
- Dataset selection is NOT based on future results
- Dataset selection is NOT optimized toward passing
- Governance decision is independent of research outcomes

**Classifications**:
- **PASS**: Selection is independent
- **FAIL**: Selection appears strategically motivated
- **UNKNOWN**: Motivation unclear
- **NOT_APPLICABLE**: N/A for pre-selected datasets

---

## Summary

For a dataset to be **ELIGIBLE**, it must achieve:

- A = PASS or NOT_APPLICABLE
- B = PASS
- C = PASS
- D = PASS or UNKNOWN (gaps documented acceptable)
- E = PASS
- F = PASS
- G = PASS or NOT_APPLICABLE (for generic datasets)
- H = PASS (not FAIL)
- I = PASS
- J = PASS or UNKNOWN (timezone correctable)
- K = PASS
- L = PASS or UNKNOWN (cost model adaptable)
- M = PASS or NOT_APPLICABLE (if scope expansion approved)
- N = PASS
- O = PASS
- P = PASS or UNKNOWN (reproducibility testable)
- Q = PASS
- R = PASS
- S = PASS or NOT_APPLICABLE
- T = PASS

**Any FAIL in dimensions B, C, E, F, or T → NOT_ELIGIBLE (governance contamination is terminal)**

Any dimension = UNKNOWN (except J, L) → NOT_ELIGIBLE (default conservative)

This framework ensures that datasets are evaluated rigorously, not chosen by convenience.
