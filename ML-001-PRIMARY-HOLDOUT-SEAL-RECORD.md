# ML-001 Primary Holdout Seal Record

**Date**: August 19, 2026
**Status**: **NOT SEALED — BLOCKED ON DATA ACQUISITION**

This document is the seal record required by
`ML-001-OGD4-GOVERNANCE-CLOSURE.md` Phase 6. It exists to record the
current, honest state of sealing: **no seal has been performed**, because
the approved dataset does not exist in this environment and cannot
currently be acquired.

---

## Approved Dataset Identity (Governance-Approved, Not Yet Instantiated)

Per `ML-001-OGD4-GOVERNANCE-CLOSURE.md`:

```
source              = Dukascopy Bank SA (or HistData as documented
                       secondary source of the same market/period, per
                       ML-001-OGD4-CANDIDATE-EVALUATION.md)
instrument           = EURUSD
timeframe            = H1
coverage_start       = 2022-01-01 (approved period start)
coverage_end         = 2026-12-31 (approved period end)
```

These are the parameters a future `register_dataset_unsealed()` /
`seal_dataset()` call must use — verbatim, not silently substituted —
once acquisition succeeds.

## Fields Required But Not Yet Determinable

The following seal-record fields cannot be populated because no file
exists to compute them from:

```
dataset_id            = UNASSIGNED
file_checksum          = UNCOMPUTED
content_checksum        = UNCOMPUTED
row_count              = UNKNOWN (actual bar count depends on the acquired file)
download_timestamp      = N/A (no download has occurred)
download_method         = N/A
SEAL_ID                = NONE
SEAL_TIMESTAMP           = NONE
CONTENT_CHECKSUM         = NONE
METADATA_CHECKSUM        = NONE
SCHEMA_VERSION           = 1.0 (fixed by EvidenceVault; ready when needed)
PROVENANCE_RECORD        = NONE
GOVERNANCE_DECISION_ID    = ML-001-OGD4-GOVERNANCE-CLOSURE.md (2026-08-19)
```

## Why Sealing Did Not Proceed

### 1. No file exists anywhere in this repository or environment

A full search of the working tree and filesystem found no Dukascopy or
HistData file, and no file covering any part of 2022-2026 for EURUSD. The
only EURUSD data present is `data/csv/EURUSD_H1.csv`
(coverage 2012-11-16 to 2022-03-05, source KOMO135 — the DEVELOPMENT
dataset, not eligible to serve as its own holdout).

### 2. Network access to the approved sources is blocked

Re-tested directly (not assumed from a prior report):

```
$ curl -s -m 10 -I https://www.dukascopy.com/swiss/english/marketwatch/historical/
HTTP/1.1 403 Forbidden

$ curl -s -m 10 -I https://datafeed.dukascopy.com/datafeed/EURUSD/2022/00/01/BID_candles_hour_1.bi5
HTTP/1.1 403 Forbidden

$ curl -s -m 10 -o /dev/null -w "HTTP_CODE:%{http_code}\n" https://www.histdata.com
HTTP_CODE:000 (connection refused/blocked before a response)
```

This is consistent with the outbound network policy for this environment
(not a Dukascopy- or HistData-side failure) and matches what the prior
OGD-4 dataset audit already found and reported.

### 3. What this task explicitly forbids as a workaround

This task's own boundaries rule out every substitute that could make
"sealed" true today:

- "Do NOT bypass network restrictions."
- "Do NOT use fabricated mirrors."
- "Do NOT silently substitute data."
- "Do not synthesize missing observations."
- "If identity is ambiguous: STOP."

Given the approved dataset cannot be reached, and no legitimate,
governance-approved substitute exists, the correct action is to **not
seal**, and to say so plainly — not to seal a different dataset under the
same governance decision ID.

## Disposition

```
SEAL_STATUS                 = NOT_SEALED
SEAL_BLOCKER                = DATA_ACQUISITION_UNAVAILABLE (network policy: HTTP 403)
DATA_ACQUISITION_STATUS     = BLOCKED
```

**The Evidence Vault is ready.** Its persistence layer, cryptographic
sealing, pre-research firewall, and one-time-consumption enforcement are
all implemented and tested (`core/factory/evidence_vault.py`,
`tests/test_ogd4_evidence_vault.py`, 23/23 passing). The instant a
genuine copy of the approved dataset (Dukascopy or HistData EURUSD H1,
2022-2026, matching the identity above) becomes available in this
environment, sealing is a mechanical operation:

```python
from core.factory.evidence_vault import EvidenceVault

vault = EvidenceVault()  # persists to reports/factory/evidence_vault.json
vault.register_dataset_unsealed(
    dataset_id="PRIMARY_HOLDOUT_EURUSD_H1_2022_2026",
    instrument="EURUSD",
    timeframe="H1",
    source="dukascopy",  # or "histdata", matching the actual acquired file
    source_url="<actual source URL>",
    coverage_start=<actual first bar timestamp>,
    coverage_end=<actual last bar timestamp>,
    row_count=<actual bar count>,
    timezone="UTC",
    price_type="OHLC",
    download_timestamp=<actual download time>,
    download_method="<actual method>",
    source_verified=True,
)
vault.seal_dataset(
    dataset_id="PRIMARY_HOLDOUT_EURUSD_H1_2022_2026",
    data_bytes=<actual file bytes>,
    research_exposure="UNEXPOSED",
    independence_level="LEVEL_3",
)
```

This must be run only after the Phase 3-5 revalidation steps in the
original task instructions (provenance, integrity, temporal-overlap,
research-exposure checks) are actually performed against the real
acquired file — none of those checks can be meaningfully performed against
data that does not exist, so they have not been claimed as complete here.

## What Remains Locked

Because no seal was performed:

```
OBSERVATIONS_VISIBLE          = N/A (no observations exist to be visible or hidden)
EVALUATION_AUTHORIZED         = FALSE
CONSUMPTION_STATUS            = N/A (nothing to consume)
GENERATION_7_STATUS           = NOT_STARTED
STRAT_000003_STATUS           = NOT_CREATED
```

Nothing in this document, or in the governance closure it accompanies,
opens any path to Generation 7 or to candidate creation. The blocker is
data acquisition, not governance — the governance question is resolved.

## Next Step (Not Taken In This Task)

Acquiring the approved dataset requires either:

1. A change to this environment's network policy to permit reaching
   Dukascopy/HistData (a decision outside this task's scope), or
2. The dataset being supplied directly (file upload, alternate authorized
   channel) and its provenance verified before sealing, or
3. A different, already-reachable source that can be shown to satisfy the
   same governance-approved identity (same instrument, timeframe, and
   period) — which would itself need explicit governance sign-off, since
   it would not literally be "Dukascopy" as named in the closure decision.

None of these were pursued in this task, consistent with the instruction
to perform governance closure and seal preparation only, and to stop
rather than route around a genuine blocker.
