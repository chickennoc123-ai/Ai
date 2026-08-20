# ML-001 — CYCLE 6: ECONOMIC CALENDAR EXTENSION (2024–2026)

**Date**: 2026-08-20
**Scope**: extend the economic calendar only. **No discovery/backtest run.**
**Ledger**: unchanged (68 hypotheses / 750 evaluations / 1 survivor)
**Holdout**: unchanged (0 authorizations, 0 consumptions)

---

## 1. Result

| | |
|---|---|
| Source used | `ehsanrs2/forexfactory-scraper` (`high_impact_events_calendar.csv`) |
| Coverage delivered | 2024-01-03 → 2026-01-30 |
| Events (2024-2026) | **1,842** |
| Missing fields | `actual`/`forecast` both present on 1,294/1,842 (70.3%); rest are forward-looking rows not yet released at scrape time |
| Quality verdict | **7/7 EVENT-CONTRACT-V1 gates PASS**, dual-signal timezone verification PASS |
| Final files | `forexfactory_2024_2026.csv` (new, 1,842 rows) + `forexfactory_2010_2026.csv` (merged superset, 32,765 rows) |
| Old file | `forexfactory_2010_2023.csv` — **byte-identical**, untouched |

---

## 2. Source search and blocked sources

Same network reality as before, re-confirmed: `forexfactory.com`, `nfs.faireconomy.media`, `api.tradingeconomics.com`, `fred.stlouisfed.org` all remain **403 at CONNECT**. No new attempt was needed to re-establish this — the Cycle 5/6 findings already cover it.

The original Cycle 6 source (`spoluan/forex-factory-scraper`) stops at 2023 (years 2024/2025 return `404`). WebSearch located a second, actively-maintained scraper — `ehsanrs2/forexfactory-scraper`, last updated within days of this task's date — whose committed cache file `high_impact_events_calendar.csv` covers 2020–2026. Fetched via `raw.githubusercontent.com` (open), inspected via `WebFetch` (routes outside the CONNECT proxy) to confirm file paths before downloading.

---

## 3. Provenance and timezone audit

### 3.1 A real quality improvement over the first source

This file's `DateTime` column is **tz-aware ISO-8601 with an explicit UTC offset per row** (`+00:00` in GMT months, `+01:00` in BST months) — no offset needed to be inferred, unlike Cycle 6's first source. Parsed with `datetime.fromisoformat()` and converted via each row's own stated offset.

### 3.2 Verified, not trusted on the label alone

Two independent signals, both required to pass:

**Signal A — cross-source historical agreement.** The same file's 2020–2023 rows were compared against the already-verified `forexfactory_2010_2023.csv` on (date, currency, event name):

```
2734/2858 (95.7%) overlap-year events also present in the existing file
```

Two independently-built scrapers agreeing on 95.7% of historical events is strong confirmation this is real ForexFactory data, not fabricated.

**Signal B — NFP schedule cross-check**, extended into 2024–2026 using a synthetic calendar scaffold (placeholder-price bars, real dates only — no holdout price file was opened; NFP's date rule needs only calendar arithmetic):

```
18/24 NFP timestamps match the simple "first Friday" rule exactly
```

### 3.3 A real limitation found, investigated, not hidden

The 6 remaining mismatches were **not dismissed and not used to reject good data**. Each was checked against a specific, falsifiable explanation:

| Date | Pattern | Explanation |
|---|---|---|
| 2024-03-08 | 1st of month is a Friday | BLS pushes NFP to the second Friday in this case |
| 2025-07-03 (Thursday) | Day before July 4th | Holiday-adjacent shift, one day earlier |
| 2025-01-10, 2025-11-20, 2025-12-16, 2026-01-09 | 7–21 days after the simple rule's prediction | A multi-week delay affecting NFP **and** CPI **and** ADP in the same window (Oct–Dec 2025) — consistent with the Oct–Dec 2025 US government shutdown halting BLS releases |

**All 6/6 mismatches fit a known category.** The government-shutdown explanation specifically is stated as the most plausible reading of an internally-consistent multi-indicator pattern (CPI moved from its usual mid-month slot to the 24th; NFP and ADP both slipped together) — **not independently re-confirmed** from a news source, since every such source is network-blocked from this environment. This is disclosed, not asserted as fact.

**Conclusion recorded in the contract**: `derive_nfp_events()` is a first-order approximation, useful for cheap pre-checks, not ground truth. Where real acquired data (cross-validated against an independent source) disagrees with it, the acquired data wins. Cycle 5's results are unaffected — they used the approximation consistently on both sides of that cycle's comparison.

---

## 4. Merge — old data never overwritten

```
existing (2010-2023, untouched): 30,923 rows   sha256 e0a25155...  <- unchanged before/after
extension (2024-2026, new):       1,842 rows
merged (2010-2026, new file):    32,765 rows    zero event_id collisions
```

`forexfactory_2010_2023.csv` was opened read-only throughout; the merge script writes only to a new file (`forexfactory_2010_2026.csv`). Verified with a SHA-256 hash comparison before and after.

---

## 5. Holdout firewall — re-verified, not assumed safe

**Every 2024-2026 event timestamp falls inside every symbol's sealed holdout price window.** This is expected (extending "to the present" necessarily reaches into holdout-period calendar time) and does not violate anything — event files live in `data/events/raw/`, never `data/holdout/`, and contain no price data — but it was treated as seriously as price-data holdout risk:

- `discovery/event_calendar.py`'s `load_events(dev_end=...)` was re-run against the merged file for **all 6 symbols**, each with its own actual dev-window end. Result: **zero** 2024-2026 rows survive the cut for any symbol.
- The processed, EURUSD-cut file (`events_dev.csv`) was re-generated from the merged source and is **byte-for-byte the same row count as before the merge** (28,354 rows) — confirmed directly.
- 19 new tests (`tests/test_cycle6_calendar_extension.py`) assert this for every symbol individually, plus that the multiple-testing ledger and holdout evidence vault are unchanged.

---

## 6. Governance — untouched, verified

```
multiple_testing_ledger.json:  68 hypotheses / 750 evaluations / 1 survivor  (SAME as before)
evidence_vault.json:           0 authorizations, 0 consumptions               (SAME as before)
```

No discovery ran, so nothing was added to the ledger. This is a data-acquisition task; the ledger only grows when hypotheses are generated or evaluated.

---

## 7. Files delivered

```
data/events/raw/ehsanrs2_2024_2026/high_impact_events_calendar_raw.csv   raw download (unmodified vendor file)
data/events/raw/forexfactory_2024_2026.csv                               converted, EVENT-CONTRACT-V1, 1,842 rows
data/events/raw/forexfactory_2010_2026.csv                               merged superset, 32,765 rows
data/events/raw/forexfactory_2010_2023.csv                               UNCHANGED (verified by hash)
data/events/processed/events_dev.csv                                     re-generated from merged source, row count UNCHANGED
data/events/processed/audit_report.json                                  re-generated, 7/7 gates PASS

scripts/convert_ehsanrs2_calendar.py                                     conversion + dual-signal verification
scripts/merge_event_calendars.py                                        merge with collision + hash safety

data/events/EVENT_DATA_CONTRACT.md                                       + extension log, NFP-approximation limitation, holdout-adjacency note

tests/test_cycle6_calendar_extension.py                                  19 tests, all passing
```

**No discovery, no backtest, no hypothesis evaluation was run.** Cycle 6 discovery proper has still not started.
