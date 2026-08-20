# ML-001 — CYCLE 6 DATA ACQUISITION REPORT

**Date**: 2026-08-20
**Scope**: acquire and audit raw material only. **No discovery/backtest was run.**
**Sealed holdout**: untouched (0 authorizations, 0 consumptions)

---

## 1. Summary

| Priority | Status | Detail |
|---|---|---|
| 1. Economic calendar | ✅ **ACQUIRED, 7/7 gates PASS** | 30,923 events, 2010–2023, C2 now runnable |
| 2. Independent gold data | ✅ **ACQUIRED, 2 sources, audited** | Coverage gaps documented, not hidden |
| 3. D1 / W1 | ✅ **No acquisition needed** | Resampled from H1 already in the repo |
| 4. Cross-asset | ✅ **No acquisition needed** | All 6 instruments already in the repo |

Every primary source in the requested priority list (ForexFactory, Trading Economics, FRED, Stooq, Yahoo Finance, Investing.com, Nasdaq Data Link, Dukascopy, BLS, Federal Reserve) is **denied by this environment's network policy** — confirmed as `403` at the CONNECT layer, not a transport failure. The path that worked was `raw.githubusercontent.com`, which the proxy leaves open for any public repository. WebSearch (routed through Anthropic's own infrastructure, not the CONNECT proxy) was used to locate candidate files; every file was then fetched and verified directly, never taken on the search summary's word.

---

## 2. Economic calendar — ACQUIRED

### 2.1 Source

`github.com/spoluan/forex-factory-scraper` — 14 yearly CSVs (2010–2023), scraped from ForexFactory's calendar. Fetched via `raw.githubusercontent.com` (open), not `github.com` or `api.github.com` (both blocked/restricted).

```
65,276 raw rows downloaded, all 14 years, 0 failures
```

### 2.2 The timezone problem, and how it was resolved — not assumed

The scraper's `Time` column is ForexFactory's anonymous-guest display, and its timezone is **undocumented**. Guessing it would repeat the exact HistData EST/UTC mistake from Gen 6. Instead:

1. Cross-referenced four known release times (NFP × 3 dates across seasons, German Unemployment) and found a consistent pattern: `true_UTC = displayed_time − 8h`, in every season — meaning the display is a **fixed UTC+8 offset with no DST of its own**, while the underlying US-anchored events still show the correct DST-driven 1-hour seasonal shift in true UTC (12:30 in EDT, 13:30 in EST) once that fixed offset is removed.
2. Built this into `scripts/convert_forexfactory_calendar.py`.
3. **Did not trust step 1 as sufficient.** The script re-derives NFP timestamps from `discovery.cycle5_events.derive_nfp_events()` — whose DST arithmetic is independently unit-tested — and requires every converted NFP row to match exactly. A mismatch aborts the conversion with no file written.

```
NFP cross-check: 93/93 rows match derive_nfp_events() exactly
VERIFIED: -8h fixed-offset conversion confirmed against an independently-derived schedule.
```

This is the same discipline as the Gen 6 HistData EST fix: a falsifiable, automated check, not a one-time eyeball.

### 2.3 A second data quirk found and fixed

The scraper's own `Date` column uses a weekday-name format on leap-day rows (`"Wed Feb 29"`) that doesn't parse as ISO — this crashed the first version of the converter. Its `Combined DateTime` column is consistently ISO on every row, so the converter uses that instead. Documented in the script's docstring, not silently patched around.

### 2.4 Result — all 7 contract gates pass

```
30,923 point-in-time, real-impact rows converted (from 65,276 raw)
  dropped: 3,332 non-point-in-time markers (All Day / Tentative / "Apr Data")
  dropped: 31,021 Non-economic-impact rows (speeches, bank holidays)

G-E1 required columns present:     PASS
G-E2 no null/unparseable timestamp: PASS
G-E3 no duplicate event_id:         PASS
G-E4 release-minute clustering:     PASS
G-E5 DST shift present:             PASS
G-E6 dev-window coverage:           PASS
G-E7 >=30 instances per event type: PASS (see below)
```

Event-type counts (USD, HIGH impact) — comfortably above the n≥30 floor:

| Event | n | | Event | n |
|---|---|---|---|---|
| Unemployment Claims | 470 | | FOMC Statement | 113 |
| Non-Farm Employment Change | 174 | | CPI m/m | 108 |
| CPI y/y | 168 | | Federal Funds Rate | 76 |
| ADP Non-Farm Employment Change | 156 | | FOMC Press Conference | 73 |

**19,406 rows carry both `actual` and `forecast`** — family **C2 (surprise reaction), blocked in Cycle 5, is now runnable.**

### 2.5 Firewall check

The processed file (`data/events/processed/events_dev.csv`, cut at EURUSD's own dev boundary) contains **zero** events at or after that boundary — verified directly, not assumed. Other symbols have later dev boundaries; `discovery/event_calendar.py`'s `load_events(dev_end=...)` re-filters the raw file per symbol at actual run time, so each symbol gets its own correct cut. Nothing here ran that filtering for any symbol but EURUSD — that only happens when Cycle 6 discovery itself runs, which this task explicitly does not do.

### 2.6 Honest limitation

This is a **third-party scrape**, not ForexFactory's own export. It is internally consistent, passed a falsifiable timezone check, and its numeric fields (`actual`/`forecast`) sanity-check against known print magnitudes — but its own QA process is unknown. Treat as **real, verified data of undocumented pipeline quality**, not as ground truth beyond what was actually checked.

---

## 3. Independent gold data — ACQUIRED, with honest gaps

Two sources, deliberately kept separate because their independence is not equal.

### 3.1 Source A — CME GC futures (via Investing.com)

`github.com/Arghyadeep/Gold-and-Silver-Price-Prediction-with-Rolling-Regression-and-LSTM`

- **2,605 rows, 2008-10-28 → 2018-11-28, zero gaps over 4 days**
- **Provenance confidence: MEDIUM** — disclosed vendor (Investing.com) and disclosed instrument (CME continuous futures — genuinely different mechanism from our HistData spot series: futures roll, CME settlement, not forex-CFD spot)
- Cross-check against our own XAUUSD series: **99.91% of overlapping days within 2%**, median relative difference 0.10% — tracks tightly, consistent with real data, not garbage

### 3.2 Source B — XAUUSD daily (ejtraderLabs)

`github.com/ejtraderLabs/historical-data`

- **2,401 rows, 2012-11-14 → 2022-03-04, zero gaps over 4 days**
- **Provenance confidence: LOW** — the repo's README does not disclose the underlying broker/vendor
- Cross-check against our own series: **100% of overlapping days within 2%**, median relative difference 0.08%
- Values required a ×0.01 scale correction (raw `172497` → `1724.97`); the script sanity-checks this range before trusting it rather than assuming the scale

### 3.3 What this does — and does not — solve for B2_TURN_OF_MONTH

| | Coverage | Covers 2020 (COVID, 26% of B2's profit)? |
|---|---|---|
| GC futures | 2008–2018 | **No** |
| ejtraderLabs | 2012–2022 | **Yes** — but provenance undisclosed |
| Our HistData | 2009–2023 | full |

**Neither source alone closes the gap.** GC futures gives a genuinely independent mechanism test but misses the exact year that carries a quarter of the candidate's measured profit. ejtraderLabs covers that year but its tight tracking to our own series (median diff 0.08%) — while reassuring on data quality — also means it is a **weak test of independence**: gold spot prices across venues are naturally near-identical due to arbitrage, so close agreement day-to-day doesn't by itself confirm the *month-end* effect is real rather than shared.

**This data is acquired and audited, not yet used to re-run the B2 review.** Running Q4 properly (does the month-end effect appear in GC futures specifically, where the mechanism — futures roll vs. spot rebalancing — genuinely differs) is the natural next step, and is deliberately left for a discovery-authorized turn, per the "no discovery until quality gate" instruction.

---

## 4. D1 / W1 — no acquisition needed

Both timeframes are resamples of H1 data **already in `data/csv/`**. Added `to_weekly()` alongside the existing `to_daily()` in `discovery/cycle4_economics.py` — ISO-week aggregation, OHLC-consistent (total daily bars sum equals total weekly bars sum, verified by test), no new external dependency.

## 5. Cross-asset — no acquisition needed

All 6 instruments (EURUSD, GBPUSD, USDCAD, USDCHF, USDJPY, XAUUSD) were already acquired in Cycle 3. No further action required here.

---

## 6. Blocked sources (confirmed, not guessed)

Every host below returned **403 at CONNECT** or connection code `000` (policy denial), confirmed with `curl -v`, not inferred from a timeout:

```
forexfactory.com · nfs.faireconomy.media · api.tradingeconomics.com
fred.stlouisfed.org · api.stlouisfed.org · stooq.com · investing.com
data.nasdaq.com · finance.yahoo.com · dukascopy.com · bls.gov
federalreserve.gov · candledata.fxcorporate.com
```

`github.com` (HTML) and `codeload.github.com` (archive downloads) are also blocked; `api.github.com` is restricted to repo-scoped endpoints for repos already attached to this session. Only `raw.githubusercontent.com` is open for arbitrary public repos, and `WebFetch`/`WebSearch` route outside the CONNECT proxy entirely (confirmed: WebFetch rendered `github.com` pages that direct `curl` could not reach).

Recorded previously as **FAIL-000033**; no new failure record needed — this reconfirms the same policy boundary with a wider probe set.

---

## 7. Exactly what to upload, if you want to close the remaining gaps

Nothing is *required* — Cycle 6 discovery can proceed on what's already acquired. If you want to strengthen it further:

| Gap | What would close it |
|---|---|
| Economic calendar provenance is a scrape, not primary | A ForexFactory or Trading Economics export you download yourself and upload as CSV/JSON matching `data/events/EVENT_DATA_CONTRACT.md` |
| No independent gold data covering all of 2009–2023 | A GC futures or XAUUSD series (any vendor) spanning 2009–2023, CSV with `date,open,high,low,close` |
| ejtraderLabs' undisclosed provenance | Confirmation of its source, or a replacement series with disclosed provenance covering 2019–2023 |

None of these block Cycle 6 from starting — they would only sharpen the B2 independent-data test specifically.

---

## 8. Files delivered

```
data/events/raw/forexfactory_by_year/*.csv        14 files, raw scrape
data/events/raw/forexfactory_2010_2023.csv         converted, EVENT-CONTRACT-V1 schema
data/events/processed/events_dev.csv               EURUSD-window-filtered, gate-passed
data/events/processed/audit_report.json            full 7-gate audit output

data/independent_gold/raw/GC_futures_investingcom_2008_2018.csv
data/independent_gold/raw/XAUUSD_ejtraderlabs_d1.csv
data/independent_gold/processed/gc_futures_daily.csv
data/independent_gold/processed/ejtrader_xauusd_daily.csv
data/independent_gold/processed/audit_report.json

scripts/convert_forexfactory_calendar.py           conversion + NFP cross-check
scripts/audit_independent_gold.py                  gap/OHLC/cross-source audit

discovery/cycle4_economics.py                       + to_weekly() (no new source)

tests/test_cycle6_data_acquisition.py               17 tests, all passing
```

**No discovery, no backtest, no hypothesis evaluation was run against any of this data.** That is Cycle 6 proper, and it has not started.
