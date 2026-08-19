# ML-001-R4 — Data Eligibility Audit

**Phase:** Generation 4, Phase 2
**Run:** `G4RUN-STRAT-000002-6b1c63d014d4a7be`
**Artifact:** `reports/generation4/DATA_ELIGIBILITY.json`
**Implementation:** `core/economic_validation/data_eligibility.py`
**Verdict:** **ELIGIBLE**

---

## 1. What this audit does and does not trust

The dataset registry already carries a *declared* integrity and provenance
status from Generation 1. This audit does not trust that declaration. It
re-derives every checkable fact from the bytes on disk and compares.

The registry says `integrity_status = PASS`. That is an input to be
checked here, not a conclusion to be repeated.

---

## 2. Dataset under audit

| Field | Value |
|---|---|
| `dataset_id` | `DATASET-EURUSD-H1-KOMO135-V1` |
| File | `data/csv/EURUSD_H1.csv` |
| Source | `SRC-KOMO135-FOREX-HISTORICAL-DATA` (GitHub, raw CSV) |
| Registry `file_checksum` | `94400954ab8a91c7…` |
| **Recomputed file checksum** | `94400954ab8a91c7…` — **match** |
| Declared rows | 57,600 |
| **Observed rows** | **57,600** — match |
| Declared provenance | `VERIFIED_WITH_QUALIFICATION` |
| Declared synthetic | `false` |

---

## 3. Recomputed facts

| Check | Observed | Verdict |
|---|---|---|
| Real market data (not synthetic) | true | PASS |
| Chronology strictly increasing | true | PASS |
| Duplicate timestamps | 0 | PASS |
| NaN prices | 0 | PASS |
| Non-positive prices | 0 | PASS |
| OHLC ordering violations | 0 | PASS |
| Bars inside the market's closed window | 0 | PASS |
| Symbol matches candidate scope | EURUSD | PASS |
| Timeframe (inferred from modal bar interval) | 3600 s → H1 | PASS |
| Timezone | UTC | PASS |
| Coverage | 2012-11-16 05:00 → 2022-03-05 04:00 UTC | PASS |
| Usable bars | 57,600 (≥ 30,000 required) | PASS |
| Extreme single-bar moves (>5%) | 0 | none to classify |

Timeframe is **inferred from the data** (the modal inter-bar delta), not
read from the registry, so a mislabelled file is caught rather than
believed.

---

## 4. Real gap versus data corruption

This is the judgement the phase exists to make, and it is the one place
where a convenient definition would quietly launder a broken dataset into
an eligible one.

| Quantity | Count |
|---|---|
| Missing intervals in the series | 502 |
| Explained by market closure (weekend or enumerated holiday) | 502 |
| **Unexplained** | **0** |

The classifier used is FE-R2-003's own `_check_weekday_gaps_v3` — already
audited, already committed, and derived in
`ML-001-REAL-MARKET-GAP-SEMANTICS-AUDIT.md` from direct examination of
this dataset's real closure boundaries. A second, more permissive
definition was deliberately **not** written for this phase. Anything that
classifier does not admit is reported as unexplained and counted against
the dataset; nothing is interpolated, repaired, or reclassified.

### 4.1 Two boundaries, deliberately asymmetric

A subtlety worth stating, because it looks like an inconsistency and is
not.

FE-R2-003 treats Saturday 01:00 → Monday 05:00 UTC as the closure window
when classifying a **missing** timestamp. This audit uses a narrower
window — Saturday 05:00 → Monday 05:00 UTC — when classifying a
**present** one.

The asymmetry is required. The real weekly close drifts between Saturday
01:00 and 04:00 UTC from week to week under this dataset's disclosed
UTC-5-fixed convention, so:

* a bar *missing* at Saturday 02:00 is ordinary — the generous window is
  correct for absence;
* a bar *present* at Saturday 02:00 is also ordinary — 1,810 such
  end-of-week bars exist and are real.

Applying the generous window to presence would have condemned those 1,810
genuine bars as fabricated. Applying the strict window to absence would
have condemned every ordinary weekly close as corruption. Two questions,
two boundaries, both documented in code.

---

## 5. Qualification carried forward

`provenance_status` is `VERIFIED_WITH_QUALIFICATION`, not `VERIFIED`. The
qualification is unchanged from Generation 1 and is **not** resolved here:

> The raw source's timezone convention (UTC-5, no DST) is a documented
> assumption, not independently confirmed for this specific repository.

The dataset's price content *was* independently corroborated — the
2016-06-24 GBPUSD Brexit intraday low (~1.35233) matches the
well-documented public event. That confirms the prices are real market
prices. It does not confirm the hour labels are what they are assumed to
be.

**Effect on the Generation 4 verdict:** none. A uniform whole-series
timestamp offset would shift which hour each bar is attributed to, but the
candidate has no session, hour-of-day, or calendar condition — every rule
in `STRAT-000002` is a function of bar-to-bar sequence only. A conclusion
that depended on session timing would have had to be discounted for this;
this one does not.

---

## 6. Second instrument

`DATASET-GBPUSD-H1-KOMO135-V1` was audited under the same procedure and is
also **ELIGIBLE** (1 extreme single-bar move flagged for review — the
Brexit crash, an independently verified real event, not a data defect).

It is **not** used as evidence for `STRAT-000002`. The candidate's frozen
`research_scope` is `SINGLE_INSTRUMENT` / EURUSD; evaluating a second
instrument after freeze would be a scope change requiring a new candidate.
See `ML-001-GENERATION-4-REPORT.md` §Cross-Instrument.

---

## 7. Reproducibility

`tests/test_generation4_integration.py::test_data_eligibility_reproduces_from_the_committed_bytes`
re-runs this audit from the committed file and requires the report
checksum to match. The report checksum deliberately excludes
`audit_timestamp` — a checksum with a wall clock inside it cannot be
reproducibility evidence.
