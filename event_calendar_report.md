# Event Calendar — Data Acquisition Report

**Date**: 2026-08-20
**Status**: `BLOCKED — NO EVENT DATA ACQUIRED`
**Contract**: `EVENT-CONTRACT-V1` (`data/events/EVENT_DATA_CONTRACT.md`)

---

## 1. Acquisition attempt

Every source in the requested priority order was tried:

| Source | Host | Result |
|---|---|---|
| ForexFactory | `www.forexfactory.com` | **403 at CONNECT** |
| ForexFactory JSON feed | `nfs.faireconomy.media` | **403 at CONNECT** |
| Trading Economics | `api.tradingeconomics.com` | **403 at CONNECT** |
| FRED (API) | `api.stlouisfed.org` | **403 at CONNECT** |
| FRED (CSV) | `fred.stlouisfed.org` | **403 at CONNECT** |
| Bloomberg | — | no access, not attempted |

The proxy's own status endpoint confirms the cause is policy, not transport:

```
"kind": "connect_rejected",
"detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)"
```

Reachability is not broken in general — package registries and GitHub answer
normally (`pypi.org` 200, `api.github.com` 200, a `pip download` succeeds).
This environment's network policy permits package/source hosts and denies
general web and data APIs.

**Recorded as FAIL-000033** (`SOURCE_ACCESS_FAILED`).

---

## 2. What can be derived without a calendar — and what cannot

| Event | Derivable? | Why |
|---|---|---|
| **NFP** | **Yes** | First Friday, 08:30 America/New_York — a deterministic rule |
| Month / quarter boundaries | Yes | Calendar arithmetic (used in Cycle 4) |
| FOMC | **No** | 8 meetings/year on irregular published dates |
| CPI | **No** | Mid-month, day varies by release schedule |
| GDP, rate decisions | **No** | Irregular |
| **Any `forecast`** | **No** | A consensus is not recoverable from price data |

The contract forbids synthesising these. Writing FOMC or CPI dates from
recollection would fabricate the primary key of the entire family, and a
`forecast` column cannot be back-filled from `actual` without inventing the
surprise the hypothesis is meant to measure.

### NFP derivation — verified

112–160 events per symbol across the development windows, with the DST split
that a correct UTC calendar must show:

```
UTC release hour distribution: {12: 69, 13: 43}
```

12:30Z under EDT, 13:30Z under EST. A calendar showing a single constant hour
year-round is rejected by gate G-E5.

---

## 3. Infrastructure delivered (runs the moment data arrives)

| Component | File |
|---|---|
| Provenance contract | `data/events/EVENT_DATA_CONTRACT.md` |
| Loader + 7 quality gates | `discovery/event_calendar.py` |
| Import audit CLI | `scripts/audit_event_calendar.py` |
| Families C1–C4 | `discovery/cycle5_events.py` |
| Tests | `tests/test_cycle5_events.py` (43 passing) |

### The seven gates

| Gate | Rule |
|---|---|
| G-E1 | all required columns present |
| G-E2 | no null / unparseable `timestamp_utc` |
| G-E3 | no duplicate `event_id` |
| G-E4 | release-minute clustering (flat distribution ⇒ import-stamped times) |
| G-E5 | DST shift present (constant UTC hour ⇒ rejected) |
| G-E6 | ≥ 80% coverage of the development window |
| G-E7 | ≥ 30 instances of at least one event type |

The loader also enforces the holdout firewall: any event at or after the
development window's end is dropped at load time, and a path containing
`holdout` raises before a byte is read.

---

## 4. To supply the data

```bash
# 1. put the file here
data/events/raw/<your-calendar>.csv

# 2. audit it
python3 scripts/audit_event_calendar.py data/events/raw/<your-calendar>.csv

# 3. if it passes, run the cycle
python3 discovery/cycle5_events.py
```

A calendar that fails any gate is left in `raw/`; nothing downstream can read
it. Required columns are listed in the contract; `actual` and `forecast` are
optional but **family C2 cannot run without both**.
