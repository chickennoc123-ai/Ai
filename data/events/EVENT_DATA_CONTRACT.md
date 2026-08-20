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
