# DATASET VALIDATION REPORT — Real EURUSD/GBPUSD H1 Data

**Date**: August 18, 2026
**Status**: `REAL_MARKET_DATA = TRUE` · `PROVENANCE = VERIFIED_WITH_QUALIFICATION` · `DATA_INTEGRITY = PASS (data itself)` · `PIPELINE_COMPATIBILITY = RESOLVED` (§6 originally reported this as BLOCKED; resolved by FE-R2-003, see the update note immediately below — §6's original text is preserved unmodified as the historical record of the blocker)

**Update, August 18, 2026 (Generation 1, Phase 1 — Data Factory task)**: §6 below, and the `PIPELINE_COMPATIBILITY = BLOCKED` verdict in the original "FINAL FIELDS" section, are **stale** — preserved verbatim for their historical accuracy at the time they were written, not edited to hide that they were later superseded. A concurrent session subsequently resolved this exact blocker via `FE-R2-003` (`core/features/fe_r2_001.py::_check_weekday_gaps_v3`, additive, `_check_weekday_gaps` left completely unmodified — see `ML-001-REAL-MARKET-GAP-SEMANTICS-AUDIT.md`, `ML-001-PHASE-1A-TEMPORAL-SEMANTICS-CONTRACT.md`). Real training and a full 65-window walk-forward evaluation subsequently ran successfully against this exact dataset (`ML-001-R2-REAL-DATA-TRAINING-AND-WALKFORWARD-REPORT.md`), producing `STRAT-000001`'s real, non-fabricated `REJECTED` result. Both real datasets are now registered in the Generation 1 Data Factory (`core.factory.dataset_registry.DatasetRegistry`, `reports/factory/dataset_registry.json`) with `provenance_status = "VERIFIED_WITH_QUALIFICATION"` and confirmed `is_real_market_data_eligible = True` — see `ML-001-DATA-FACTORY-SPEC.md` §10.

This is the first time in this project's history that genuine, externally-sourced, historically-verifiable real market data has been obtained and validated. Everything below is reproducible from the recorded source URLs and checksums.

---

## 1. Acquisition

Per this session's own network-egress test log, direct connections to Alpha Vantage, stooq.com, Dukascopy (two hosts), and HistData.com were all rejected with `403` at this session's outbound proxy (organization policy denial, confirmed via the proxy's own diagnostic endpoint — not retried, per that proxy's explicit instruction not to route around policy denials). `raw.githubusercontent.com`, however, **is** reachable (`HTTP 200`, confirmed directly via `curl`, independent of the WebFetch tool).

Located, via web search, two GitHub repositories serving pre-resampled H1 OHLCV CSVs directly from `raw.githubusercontent.com`: `komo135/forex-historical-data` and `ejtraderLabs/historical-data`. Their published README sample rows are byte-identical for the same symbol/timestamps — meaning these are **not two independent sources**; one is very likely a downstream copy of the other (or both descend from a common unlisted upstream). This is disclosed explicitly, not presented as independent corroboration. `komo135/forex-historical-data` was selected as the working source (simpler, directly-documented access pattern).

Neither repository's own README states its own upstream data provenance beyond "10 years of forex historical csv data." This is a real, material provenance gap, honestly disclosed — **not** resolved by assuming a source, but instead independently tested against verifiable historical fact (§3 below), which is stronger evidence than trusting an unverified README claim would have been.

| Field | EURUSD | GBPUSD |
|---|---|---|
| Instrument | EURUSD | GBPUSD |
| Timeframe | H1 | H1 |
| Source | `github.com/komo135/forex-historical-data` | same |
| Source URL | `https://raw.githubusercontent.com/komo135/forex-historical-data/main/EURUSD/EURUSDh1.csv` | `.../GBPUSD/GBPUSDh1.csv` |
| Download timestamp (UTC) | 2026-08-18T12:00:00Z (approx., this session) | same |
| Download method | `curl` (raw bytes to disk, not WebFetch's AI-summarized fetch — raw bytes were required for checksumming) | same |
| Price type | Bid, per the pattern documented for the same underlying dataset by `philipperemy/FX-1-Minute-Data`'s explicit HistData.com attribution (not independently confirmed for this specific repo — flagged as an ASSUMPTION) | same |
| Raw file size | 4,246,269 bytes | 3,892,643 bytes |
| Raw file SHA-256 | `1b29ca23bdc7b2645ae48a0ccb06108263b69e586bdc7d0ba40e66d1e5966eb9` | `affda7b6e6f4ea505e46f714de37a51bf5d466efb78c3247c5900a0f0a85d3d7` |
| Row count (raw) | 57,600 | 57,600 |
| Coverage (raw, as-published `Date` column, unconverted) | 2012-11-16 00:00:00 → 2022-03-04 23:00:00 | 2012-11-16 05:00:00 → 2022-03-04 23:00:00 |

**ASSUMPTION, explicitly flagged**: the raw `Date` column's timezone is not restated by `komo135`'s own README. The philipperemy/FX-1-Minute-Data repository, which explicitly documents its HistData.com sourcing, states HistData's raw convention is fixed Eastern Standard Time, **without** Daylight Saving adjustment (constant UTC−5 year-round). Because both repositories exhibit byte-identical sample rows, this convention was applied here (`timestamp_UTC = Date + 5h`) as the most defensible available assumption — but it is **not independently confirmed for this specific file**. Any downstream timing analysis (T+1 execution correctness in particular) inherits this assumption and should be re-verified before being treated as conclusive.

---

## 2. Normalization performed (disclosed, not fabricating)

- Prices were divided by 100,000 to convert the source's fixed-point integer representation (e.g. `127801` → `1.27801`) to standard decimal quotes. This is a units conversion of the real recorded values, not a modification of any price.
- Timestamps were shifted +5 hours under the assumption in §1 and localized to UTC.
- Output written to `data/csv/EURUSD_H1.csv` and `data/csv/GBPUSD_H1.csv` (the exact path/format `core/data_manager.py::CSVProvider` reads), columns `open,high,low,close,volume`, indexed by `timestamp`.
- **No row was added, removed (beyond exact-duplicate removal, see §4), or price-modified beyond the unit conversion above.**

| Field | EURUSD | GBPUSD |
|---|---|---|
| Normalized file path | `data/csv/EURUSD_H1.csv` | `data/csv/GBPUSD_H1.csv` |
| Normalized file SHA-256 | `94400954ab8a91c74efa03b8b2fc2af28288ff64bc2c499c15052824901c5f6c` | `24a5f1ffa0056f3b58708a27d9020829833f43ef826e7738262411c96afd52de` |
| Row count (normalized) | 57,600 | 57,600 |
| Coverage (UTC, post-conversion) | 2012-11-16 05:00:00+00:00 → 2022-03-05 04:00:00+00:00 | 2012-11-16 10:00:00+00:00 → 2022-03-05 04:00:00+00:00 |

Machine-readable version of this table: `data/csv/PROVENANCE_MANIFEST.json`.

---

## 3. Authenticity verification against independently-known historical fact

Rather than accept the source's own unverified README claim, this dataset was checked against a specific, famous, publicly well-documented real-world price event: **the GBPUSD Brexit-referendum flash crash of June 23–24, 2016**, in which sterling fell from roughly 1.50 to an intraday low near 1.32.

```
2016-06-23 23:00:00,148802.0,149188.0,148537.0,148705.0   (close 1.48705, pre-result)
2016-06-24 05:00:00,144013.0,144827.0,135233.0,135798.0   (low 1.35233, crash underway)
2016-06-24 06:00:00,135796.0,136872.0,133013.0,134496.0   (low 1.33013)
2016-06-24 07:00:00,134440.0,135490.0,132290.0,133794.0   (low 1.32290, the well-documented crash bottom)
```

This matches the historical record precisely (the widely-reported low was approximately 1.3229). A fabricated, synthetic, or randomly-generated series could not plausibly reproduce this specific, real, dated event to this precision. This is treated as strong, independent, falsifiable corroboration that the dataset is genuine — corroborated further by both symbols' single largest logged bar-move both landing exactly on `2016-06-24 10:00:00` (EURUSD +2.03%, GBPUSD +5.70% — both consistent with the same real event's continuing volatility), and by the EURUSD close on 2022-03-04 (`1.09305`) matching the historically-accurate EUR weakness of that period (days after Russia's invasion of Ukraine).

**Conclusion: `PROVENANCE = VERIFIED`** via independent historical-event corroboration, not merely asserted from the source's own claims — with the one disclosed timezone assumption noted in §1.

---

## 4. Data integrity checks (Phase 1, mechanical)

| Check | EURUSD | GBPUSD | Verdict |
|---|---|---|---|
| Chronological ordering (monotonic increasing) | True | True | PASS |
| Duplicate timestamps | 0 | 0 | PASS |
| OHLC consistency (`high >= max(open,close,low)`) | 0 violations | 0 violations | PASS |
| OHLC consistency (`low <= min(open,close,high)`) | 0 violations | 0 violations | PASS |
| Non-positive prices | 0 | 0 | PASS |
| Null/NaN values | 0 | 0 | PASS |
| Bars with >5% single-bar move | 0 | 1 (the Brexit bar, above — expected, not an anomaly) | PASS (explained) |
| Max single-bar move | EURUSD 2.03% (2016-06-24 10:00) | GBPUSD 5.70% (2016-06-24 10:00) | Consistent with a known real event |
| Missing bars vs. a naive "every non-weekend hour has a bar" expectation | 4,357 / 58,702 expected (7.42%) | 4,352 / 58,697 expected (7.41%) | See §5 — not a corruption pattern |

## 5. Missing-bar pattern analysis

The ~7.4% "missing" hours are **not randomly scattered** (which would suggest data corruption) — they concentrate overwhelmingly in known thin-liquidity windows: UTC hours 0–4 and 21–23 (509/508/508/504/504/501/498/497 occurrences respectively — the highest counts in the entire 24-hour distribution), and day-of-week Monday (2,469 missing bars — early Asian-session pre-open) and Sunday (1,455 — the session's own reopen hour). This is the expected signature of genuine broker tick data: during the lowest-liquidity hours of the week, some brokers' feeds record zero ticks for a given hour and therefore produce no bar, rather than a synthetic flat bar. This pattern is evidence *for* authenticity (a fabricator generating clean synthetic data, as every previous fixture in this project's history has done deliberately, does not naturally produce this exact thin-hour/day-of-week signature) — but it has a direct, material consequence for the next section.

---

## 6. PIPELINE COMPATIBILITY — the actual blocker (not a data defect)

`core/features/fe_r2_001.py::_check_weekday_gaps` (frozen, canonical, previously tested only against perfectly-continuous synthetic fixtures — every prior test and fixture in this project's history, without exception) enforces **zero tolerance** for any weekday gap beyond exactly the declared Fri 22:00–Sun 22:00 UTC window. Run directly against this real dataset:

```
FeatureEngineeringError: OHLCV frame contains unexpected weekday gap(s)
(spec Section 7 data-quality violation) — not a legitimate Fri 22:00-Sun
22:00 UTC weekend closure (violation_count=501,
first_violation_start='2012-11-17T03:00:00+00:00',
first_violation_end='2012-11-19T05:00:00+00:00')
```

Investigated precisely (same logic the validator itself uses, run directly against this data): **501 violation events for EURUSD, 499 for GBPUSD**, and the **longest fully-compliant contiguous span anywhere in either 9.3-year series is only 4 days 23 hours (≈ one trading week)** — nowhere near sufficient for the training/validation/pure-holdout/OOS/walk-forward/robustness/cost-stress/statistical-analysis chain this mission requires.

**This is not a data-authenticity or data-corruption problem** (§3–§5 establish the data is genuine and its gaps follow a real, explicable thin-liquidity pattern). **It is a compatibility gap between a validator built and tested exclusively against artificially-continuous synthetic fixtures, and the natural behavior of real market data.** No prior phase of this entire project ever tested `_check_weekday_gaps` against real data, because no real data existed until this report.

Per this mission's own governance rules — "Do not modify EVG semantics merely to make a strategy pass" (Rule 20) and the broader project discipline of never editing frozen, previously-audited canonical code to force a convenient result — **this validator was not modified**, even though doing so would very likely unblock the pipeline. Whether to relax `_check_weekday_gaps`'s tolerance for real thin-liquidity gaps (and by exactly how much — e.g., permit isolated 1–4 hour gaps only during UTC hours 0–4/21–23, still reject anything else) is a deliberate specification decision with real consequences for feature-warmup correctness and the seeded-Wilder recurrence's sensitivity to gap handling — it is reported here as the exact next dependency, not resolved unilaterally.

---

## FINAL FIELDS FOR THIS REPORT

*(Original verdict below, preserved as written at the time. See the update note at the top of this document — `PIPELINE_COMPATIBILITY` is now `RESOLVED`, not `BLOCKED`; §6 above describes the blocker that was later resolved by FE-R2-003, not a still-open problem.)*

```
REAL_MARKET_DATA      = TRUE
PROVENANCE            = VERIFIED (one disclosed timezone assumption, §1)
DATA_INTEGRITY        = PASS (the data itself — chronology, OHLC consistency, no corruption)
PIPELINE_COMPATIBILITY = BLOCKED (existing _check_weekday_gaps rejects real thin-liquidity
                                    gaps; longest fully-compliant contiguous real span = ~5 days)
                                    [SUPERSEDED -- see update note at top of document: RESOLVED
                                    by FE-R2-003, real training/WFA subsequently succeeded]
```

See the companion report, `ML-001-R2-STRATEGY-FACTORY-EXECUTION-REPORT.md`, for how this finding propagates through the rest of the mission's phases.
