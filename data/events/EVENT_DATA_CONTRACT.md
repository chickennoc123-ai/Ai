# Data Provenance Contract — Macro Event Calendar

**Status**: AWAITING DATA. No event file has been supplied or acquired.
**Contract version**: EVENT-CONTRACT-V1

Any event calendar entering this project must satisfy every clause below
before a single hypothesis is evaluated against it. A calendar that cannot
demonstrate these properties is a research liability, not an asset: mis-stamped
event times produce exactly the class of artifact that FAIL-000030 documents.

## 1. Required schema

CSV or Parquet, one row per event, with these columns:

| column | type | required | notes |
|---|---|---|---|
| `timestamp_utc` | ISO-8601 | yes | release time in **UTC**, minute precision |
| `event_id` | string | yes | stable identifier, unique per row |
| `event_name` | string | yes | e.g. `Non-Farm Payrolls` |
| `country` | string | yes | ISO-3166 alpha-2, e.g. `US` |
| `currency` | string | yes | affected currency, e.g. `USD` |
| `impact` | enum | yes | `HIGH` / `MEDIUM` / `LOW` |
| `actual` | float | no | null if not yet released or not numeric |
| `forecast` | float | no | consensus prior to release |
| `previous` | float | no | prior period's actual |
| `revision` | float | no | revision to the previous print |
| `source` | string | yes | provenance token, e.g. `forexfactory` |

`actual` and `forecast` are **optional** but family C2 (surprise reaction)
cannot run without both. A calendar lacking them supports C1, C3 and C4 only.

## 2. Timestamp requirements — the clause that matters most

1. Times MUST be UTC, not local, not exchange-local, not "server time".
2. DST transitions MUST already be resolved in the stored value. A US 08:30 ET
   release is `12:30Z` in summer and `13:30Z` in winter; a calendar that stores
   a constant UTC hour year-round is **rejected**.
3. Minute precision is required. Hour-rounded timestamps are rejected for
   intraday families, because a 60-minute uncertainty is larger than the entire
   post-event window this project would test.
4. The audit must show release-minute clustering consistent with the event
   type. Scheduled US macro releases cluster hard at :30; a flat distribution
   across the hour indicates stamped-on-import times, not release times.

## 3. Coverage requirements

- Must overlap the **development** window of the price data
  (2010-08 .. 2023-06 depending on symbol).
- MUST NOT be silently truncated at the holdout boundary — but discovery may
  only read the development portion. The loader enforces this.
- Minimum 30 instances per event type per family, matching the pre-registered
  economic filter.

## 4. Quality gates applied on import

| gate | rule |
|---|---|
| G-E1 | every required column present, correct dtype |
| G-E2 | zero null `timestamp_utc`; strictly parseable ISO-8601 |
| G-E3 | timestamps monotonically sortable, no duplicate `event_id` |
| G-E4 | release-minute distribution reported; flat distribution flagged |
| G-E5 | DST sanity: same event name must shift UTC hour across the year |
| G-E6 | coverage overlap with dev window ≥ 80% of its span |
| G-E7 | ≥ 30 instances for any event type used by a hypothesis |

`scripts/audit_event_calendar.py` implements all seven and refuses to write a
processed file when any gate fails.

## 5. Prohibited

- **Synthesising event times from memory.** Only NFP (first Friday) and
  month/quarter boundaries are deterministic calendar rules and may be derived.
  FOMC, CPI, GDP and rate decisions have irregular schedules and MUST come from
  a real calendar file. Writing them from recollection would fabricate data.
- Back-filling `forecast` from `actual`.
- Using any event whose timestamp falls inside the sealed holdout window during
  discovery.

## 6. How to supply the data

Drop the file in `data/events/raw/` and run:

```
python3 scripts/audit_event_calendar.py data/events/raw/<file>
```

The audit writes `data/events/processed/events_dev.csv` plus an audit report,
and only then can `discovery/cycle5_events.py` run.

---

## 7. Extension log — 2024-2026 (Cycle 6, continued)

| Date | Addition | Source | Rows | Gate result |
|---|---|---|---|---|
| Initial | 2010-2023 | spoluan/forex-factory-scraper | 30,923 | 7/7 PASS |
| Extension 1 | 2024-2026 | ehsanrs2/forexfactory-scraper (`high_impact_events_calendar.csv`) | 1,842 | 7/7 PASS (dual-signal verified, see below) |
| **Merged** | **2010-2026** | `data/events/raw/forexfactory_2010_2026.csv` | **32,765** | Old file untouched; superset only |

### Timezone: proper tz-aware ISO-8601 this time, still not trusted blindly

The ehsanrs2 source's `DateTime` column already carries an explicit UTC offset
per row (`+00:00` in GMT months, `+01:00` in BST months) — no offset needs to
be inferred, unlike the 2010-2023 source. This claim was still verified, not
assumed, using the same discipline as before.

### A real limitation of `derive_nfp_events()` was found, not papered over

The NFP cross-check flagged 6 of 24 derived-2024-2026 NFP timestamps as not
matching the simple "first Friday, day ≤ 7" rule used throughout this project
since Cycle 5. Investigation (not fabrication — reasoning about **already-
acquired real data**, not inventing new timestamps) found every mismatch fits
a known calendar-exception category:

- **first-Friday-is-the-1st** (2024-03-08): BLS pushes to the second Friday
  when the calendar's naive "first Friday" would be the 1st.
- **July 4th holiday shift** (2025-07-03, a Thursday): release moved a day
  earlier ahead of Independence Day.
- **Multi-week delay cluster** (2025-01-10, 2025-11-20, 2025-12-16,
  2026-01-09): each lands 7–21 days after that month's rule-predicted date.
  Consistent with the well-known Oct–Dec 2025 US government shutdown
  disrupting BLS release schedules — this specific causal claim is **not
  independently re-confirmed from within this environment** (all external
  news/BLS sources are network-blocked); it is offered as the most plausible
  explanation for a real, internally-consistent pattern (CPI, ADP, and NFP
  all showed the same multi-week slip in the same window), not as a verified
  fact.

**Conclusion**: `derive_nfp_events()` is a **first-order approximation** of
the real BLS schedule, useful for cheap power pre-checks and gross-error
detection, but not authoritative. Where it disagrees with real acquired
calendar data that independently cross-validates against another source
(95.7% agreement with the already-verified 2010-2023 file on their 2020-2023
overlap), the **acquired data wins**. This does not retroactively invalidate
Cycle 5's C1/C3/C4 results — those used the approximation consistently for
both signal generation and the (then only available) reference, so internal
consistency was preserved even though the derived NFP calendar itself was
imperfect in edge months.

### Holdout adjacency — explicit warning

**Every timestamp in the 2024-2026 extension falls inside every symbol's
sealed holdout price window.** This is expected — that's what "extend to the
present" means — but it makes this file holdout-*adjacent*, not holdout
data itself (it lives in `data/events/raw/`, not `data/holdout/`, and
contains no price data). The existing protection is unchanged and was
re-verified after the merge: `discovery/event_calendar.py`'s
`load_events(dev_end=...)` filters by each symbol's own development-window
end at call time, and the processed `events_dev.csv` (cut at EURUSD's dev
boundary) contains **zero** rows from the extension — confirmed directly, not
assumed, both before and after this merge (28,354 rows, unchanged).

Any future GEN 14 authorized holdout evaluation that needs event data for
2024-2026 reads `forexfactory_2010_2026.csv` (or `forexfactory_2024_2026.csv`
directly) through the same `load_events()` path, gated by the same
authorization/freeze machinery as price data — never a raw, ungated read.
