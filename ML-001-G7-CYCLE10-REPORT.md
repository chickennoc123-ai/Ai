# ML-001 — GEN 7 CYCLE 10: DATA ACQUISITION ONLY

**Date**: 2026-08-20
**Cycle**: `CYCLE-10-CROSSASSET-DATA-ACQUISITION`
**Outcome**: **Power bottleneck NOT resolved.** Two real sources acquired and audited; neither closes the gap this project needs; a third instrument (US10Y) was not found at all.
**No discovery/backtest ran.** No holdout price touched. No SC mechanism modified. No ledger change.

---

## 1. Self-critique — before searching for anything

Two things needed stating up front, both confirmed true and material to the
result:

1. **This cycle's scope (SPX500, US10Y, WTI) can only fully fix 2 of the 6
   underpowered combinations even in the best case.** `discovery/cycle8_intraday.py`
   routes EURUSD/GBPUSD/XAUUSD through `M1Series` for *every* window,
   including 60/120/240 minutes — not just the sub-hourly ones. Extending
   only the **driver** series (SPX500/US10Y/WTI) without also extending
   **FX** M1 data (EURUSD/GBPUSD/XAUUSD) would leave 4 of the 6 promising
   combinations (`EURUSD/US10Y`, `GBPUSD/US10Y`, `XAUUSD/SPX500`,
   `XAUUSD/WTICO`) still capped at 2020-05, since the FX leg — not just the
   driver leg — is the limiting series for those four. Only `USDJPY/SPX500`
   and `USDCHF/SPX500` would fully benefit from a driver-only extension,
   because USDJPY/USDCHF already use existing H1 dev data (which extends to
   2023) for their leg. **This report flags this rather than silently
   treating "driver data acquired" as "problem solved."**

2. **The event calendar itself only extends to 2023.** Even a fully-solved
   driver/FX data problem through 2026 would be useless for *this*
   mechanism without NFP/CPI/ADP event data for 2024 onward, which does not
   exist in this project yet. Any acquired price data past 2023 cannot
   currently feed a single additional SC trade.

Both points turned out to matter: what was found sits entirely on the wrong
side of point 2.

---

## 2. Search conducted

| Attempt | Result |
|---|---|
| Direct hosts (stooq, Dukascopy, Yahoo Finance, Investing.com, Nasdaq Data Link, `getdata.finance` itself, its GitHub Pages mirror) | **All blocked** — connection code `000` at every host, consistent with every prior cycle's finding. Confirmed again, not assumed. |
| `FutureSharks/financial-data` (Cycles 7-9's source) | Re-checked: still ends 2020-05. No new branches, tags, or commits since the shallow clone's single commit. |
| Forks of `FutureSharks/financial-data` | 2 forks found (`Chao-Chen-2004`, `hugogobato`); the more recently-touched one (updated July 2025) was cloned and checked — **identical data, no extension**. The 2025 "activity" was metadata only. |
| `getdata-finance/spx500-1m-ohlcv-index-historical-data` | **Real vendor, real data** — see §3. |
| `getdata-finance/usoil-1m-ohlcv-commodities-historical-data` | **Real vendor, real data** — see §3. |
| `getdata-finance` org, US10Y-equivalent | **Not found.** 8 plausible repo names tried directly (`us10y-1m-*`, `ust10y-1m-*`, `tnx-1m-*`, etc.) — all 404. Org-level search filtered by `"10y"` and `"bond"` across all 307 repos — zero matches. |
| `philipperemy/FX-1-Minute-Data` (re-checked from Cycle 8) | Confirmed still an API client calling the blocked `histdata.com`, not a data repository. |

---

## 3. What was found — real, but doesn't close the gap

`getdata.finance` is a genuine commercial vendor with a working GitHub
lead-generation pattern: each instrument gets its own repo containing a
**rolling 6-month "evaluation sample"** (refreshed every Saturday), while the
**full historical archive** (2008–2026, millions of rows) is sold separately
on their own website — which is network-blocked from this environment, same
as every other direct financial-data host.

| | SPX500 | USOIL (WTI) |
|---|---|---|
| GitHub sample window | 2026-02-01 → 2026-07-31 | 2026-02-01 → 2026-07-31 |
| Sample rows | 177,911 | 176,824 |
| Full archive (claimed, blocked) | 2008-08-19 → 2026-07-30, 5,782,916 rows | 2008-09-10 → 2026-07-30, 5,948,540 rows |
| **Bad OHLC rows** | **0** | **0** |
| Gaps > 1h | 129 | 128 |
| Gaps > 24h | 25 | 25 |

25 multi-day gaps over a 6-month sample is consistent with ~26 weekly
weekend rollovers for an index/commodity CFD product (one ~49h gap most
Fridays→Sundays, one longer ~73h gap around an early-April holiday cluster)
— not a data-quality problem. **Both samples pass integrity audit cleanly.**

**But the window is wrong.** The event calendar
(`data/events/raw/forexfactory_2010_2023.csv`) ends in 2023. This sample
starts 2026-02 — **a roughly 5.5-year gap (2020-06 through 2026-01) remains
completely uncovered**, and that gap is exactly where the SC mechanism's
event pool lives.

**US10Y: not found at any date past 2020-05, from any source tried.**

---

## 4. A governance flag for later, not acted on now

The acquired 2026-02..2026-07 window overlaps the **sealed holdout period**
for five of six FX symbols:

| Symbol | Holdout window | Overlaps the sample? |
|---|---|---|
| EURUSD | 2024-01-01 → **2026-01-30** | **No** — sealed window ends just before the sample starts |
| GBPUSD / USDCAD / USDCHF / USDJPY / XAUUSD | → **2026-08-20** | **Yes** |

If cross-asset M1 data is ever acquired covering this window paired with a
GBPUSD/USDCAD/USDCHF/USDJPY/XAUUSD price move, using it would be
functionally equivalent to touching that symbol's price holdout, even though
the SPX500/USOIL data itself was never formally sealed. **Any future use of
this specific sample against those five FX legs requires the same GEN 14
authorization discipline as touching their price holdout directly.** Recorded
here for future cycles; nothing was done with this fact in Cycle 10 beyond
recording it, per the "no experiments after acquisition" instruction.

---

## 5. Power bottleneck: NOT resolved

```
power_bottleneck_resolved: false
```

**Nothing acquired this cycle raises any SC validation count past n=30.**
The Cycle 9 shortfall stands exactly as reported: ~510–540 total events
needed across the six affected combinations (~30–36% more than the 393
currently available), and the binding constraint remains the 2020-05 cutoff
of every genuinely accessible M1 source for these instruments.

---

## 6. What is still missing — precisely

1. **SPX500/WTI M1 (or better) covering 2020-06 through 2023-12** specifically
   — not 2024-2026. This is the temporal window the event calendar can
   actually use today. No free, network-accessible source for this specific
   window was found.
2. **US10Y M1 (or any sub-daily resolution) at any date past 2020-05** —
   no source found at all, free or paid, reachable or blocked.
3. **EURUSD/GBPUSD/XAUUSD M1 covering the same 2020-06→2023-12 window** —
   out of this cycle's explicit scope, but required in addition to #1/#2
   before 4 of the 6 affected combinations could actually benefit (see §1).
4. **Event calendar coverage for 2024 onward** — a separate, currently
   unaddressed gap; even a fully solved #1–#3 would not unlock any
   additional SC trades without this.

None of these four gaps can be closed with the acquisition channels already
proven to work in this environment (anonymous GitHub reads). Closing them
requires either a paid data source becoming reachable, or the user supplying
the data directly.

---

## 7. Compliance

| Rule | Status |
|---|---|
| Real historical data only | PASS — both acquired files are genuine, vendor-attributed, integrity-audited |
| No synthetic/intraday reconstruction | PASS — nothing was resampled, interpolated, or invented |
| Original timestamps and provenance preserved | PASS — files stored with vendor README and source URLs alongside |
| Timezone audited | PASS — all timestamps confirmed tz-aware ISO-8601 UTC |
| OHLC integrity audited | PASS — 0 violations in both files |
| Coverage and gaps recorded exactly | PASS — §3 |
| Cross-checked against known prices/events | PARTIAL — internal consistency (gap pattern, OHLC) checked; no independent second source exists for 2026-02..2026-07 to cross-validate against, unlike Cycle 6's gold check — stated honestly, not glossed over |
| SC mechanism not modified | PASS — no file under `discovery/cycle8_intraday.py` or `discovery/cycle9_power.py` touched |
| Holdout not touched | PASS — 0 new vault authorizations/consumptions (verified by test; the 4 pre-existing terminal C2-NFP consumptions from before this cycle are unchanged) |
| Multiple-testing ledger unchanged | PASS — no new cycle record added (verified by test) |
| No experiments after acquisition | PASS — no SC evaluation, no backtest, ran this cycle |
| Report exactly what's missing if insufficient | PASS — §6 |
| Self-critique first | PASS — §1, written before the search began |

---

## 8. Files

```
data/crossasset/raw_2026_sample/SPX500_1m_20260201_20260731.csv   12MB, 177,911 rows
data/crossasset/raw_2026_sample/USOIL_1m_20260201_20260731.csv    11MB, 176,824 rows
data/crossasset/raw_2026_sample/*_getdata_finance_README.md       vendor documentation, preserved verbatim
scripts/audit_crossasset_2026_sample.py                           integrity + governance audit
reports/factory/discovery_cycles/cycle_10_crossasset_2026_audit.json
tests/test_cycle10_acquisition.py                                 18 tests
```

---

**Bottom line**: two real data sources were found and honestly audited; both
sit on the wrong side of a calendar gap this project can't currently use.
The SC mechanism remains exactly where Cycle 9 left it — genuinely
promising, genuinely unresolved, and now with one more closed door
documented rather than silently retried.
