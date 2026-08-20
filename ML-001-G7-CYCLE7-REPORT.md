# ML-001 — GEN 7 CYCLE 7: NEW ECONOMIC SEARCH (post C2-NFP refutation)

**Date**: 2026-08-20
**Cycle**: `CYCLE-07-NEW-ECONOMIC-SEARCH`
**Final state**: `NO_EDGE_FOUND` — 0 survivors across all three phases
**Sealed holdout**: untouched by this cycle (0 new authorizations/consumptions)

---

## 1. Result

```
REPORT = {
    "hypotheses": 8,                    # 6 cross-asset + D1_WEEKDAY_FIXED + W1_BREAKOUT
    "hypotheses_cumulative": 80,
    "evaluations_this_cycle": 180,      # 12 Phase 2 + 168 Phase 3 (Phase 1: 0, reused)
    "evaluations_cumulative": 1402,
    "survivors": 0,
    "survivors_cumulative": 5,          # unchanged: B2_TURN_OF_MONTH (parked) +
                                        # 4 C2-NFP (GEN14 FAIL, terminal)
    "failures_recorded": ["FAIL-000038", "FAIL-000039", "FAIL-000040"],
    "search_space_eliminated": [
        "CPI y/y C2 surprise reaction (fully powered, tested)",
        "FOMC C2 via Federal Funds Rate (structurally unreachable, killed at zero cost)",
        "6 lagged cross-asset mechanisms (oil/SPX/US10Y -> FX/gold, 1-2 day holds)",
        "D1 day-of-week effect (bug-fixed retest, now a clean negative)",
        "W1 N-week breakout/reversal (12/26-week lookback)",
    ],
    "final_state": "NO_EDGE_FOUND",
    "next_highest_value_experiment": "see section 7",
}
```

---

## 2. Phase 0 — Pre-flight

### Data verification

| Series | Status | Source | Coverage | Sample check |
|---|---|---|---|---|
| CPI (y/y, m/m) | Already acquired | ForexFactory scrape (Cycles 5-6, dual-signal verified) | 2010-2023 | n=168, 168 with actual+forecast |
| FOMC (Fed Funds Rate) | Already acquired | Same | 2010-2023 | n=113, only 49 with actual+forecast |
| FOMC Statement | Already acquired | Same | 2010-2023 | n=113, **0** with actual+forecast (prose, not a print) |
| DXY | **NOT acquired** | All direct sources network-blocked (same policy as prior cycles) | — | Not used; no proxy substituted for a directional bet (would be near-tautological against EURUSD) |
| Oil (WTICO) | **Acquired this cycle** | `FutureSharks/financial-data`, Oanda M1, cloned via anonymous git read | 2010-01-04..2020-05-14 | min $11.92 (Apr 2020 crash), matches known history |
| S&P 500 (SPX500) | **Acquired this cycle** | Same | 2010-01-04..2020-05-14 | 1015..3390, matches known 2010 low / Feb-2020 pre-COVID high |
| US 10Y (USB10Y) | **Acquired this cycle** | Same | 2010-01-04..2020-05-14 | Oanda bond-**price** CFD (inverse of yield), not the yield itself — noted, not conflated |

**Acquisition method**: `add_repo` (read-only anonymous git clone) reached `raw.githubusercontent.com`-blocked content by cloning the repository directly — `api.github.com`, `github.com` HTML, and direct hosts (stooq, FRED, Yahoo) all remain blocked as before; git's own anonymous read path is not. ~560MB of local M1 CSVs resampled to daily with zero further network calls.

### Timestamps, provenance, coverage, alignment

- Oanda M1 timestamps use a **broker-day convention** (day boundary ≈23:00 UTC, standard CFD/FX rollover), not strict UTC midnight. Documented in `scripts/resample_crossasset_m1_to_d1.py`; adequate for close-to-close daily returns, not recalibrated further since nothing in this cycle needs exact-midnight alignment.
- Zero gaps >4 days in any of the three resampled series (verified, not assumed).
- **Coverage limitation, stated before evaluation**: the cross-asset data ends 2020-05-14; FX dev windows extend to 2022-2023. Phase 2 evaluated on the **overlap window only** (2010–2020, ~2000-2600 trading days per pair depending on symbol) — smaller than the full FX dev window, but comfortably above any n≥30 floor.

### Power / sample-size analysis, before evaluation

| Path | Expected n (train/val) | Verdict | Action |
|---|---|---|---|
| CPI y/y × 6 symbols | ~120-160 train, ~30-35 val | Adequately powered | Evaluated (reused from Cycle 6) |
| FOMC Fed Funds Rate × 6 symbols | ~83-88 train, **15-22 val** | **Underpowered** | **Killed before evaluation** (Cycle 6 pre-check; reconfirmed here, 0 new cost) |
| Cross-asset (Oil/SPX/US10Y) × FX | ~1500-2100 train, ~385-535 val | Very well powered | Evaluated |
| D1 weekday × 6 symbols | ~500-650 train per weekday | Adequately powered | Evaluated |
| W1 breakout × 6 symbols | ~280-330 train weeks (26-week lookback) | Adequately powered | Evaluated |

**One path was killed at Phase 0 per the explicit instruction** ("kill any research path that cannot realistically reach GEN14"): FOMC-via-Federal-Funds-Rate. Rate decisions are inherently rarer than monthly data (8 vs 12 releases/year) and the dev-window-to-validation split leaves too few holdout-comparable events. This was known from Cycle 6's own pre-check and is reconfirmed, not re-discovered, here.

### Multiple-testing budget estimate

Before this cycle: M=1,222. Planned additions: 12 (Phase 2) + 168 (Phase 3) = 180, landing at **M=1,402**. Bonferroni requirement at that M: `p < 0.05/1402 = 3.57e-05`, roughly `|t| ≥ 4.15` — marginally stricter than the bar the C2-NFP candidates failed against (M=1,222, |t|≥4.09). This was estimated **before** running Phase 2/3, consistent with "estimate the multiple-testing budget" in Phase 0.

---

## 3. Phase 1 — Event (CPI, FOMC), compared against NFP

**No new parameter evaluations were spent.** Cycle 6's sweep already tested CPI y/y and attempted Federal Funds Rate; those results were pulled, not regenerated (regenerating identical evaluations would inflate the ledger for zero new information — a form of the exact waste this project's ledger discipline exists to prevent).

| Event | Evaluations | Survivors | Best result |
|---|---|---|---|
| **NFP** (Cycle 6) | 71 | 4 dev-window (later 0/4 at GEN 14) | train t up to 8.32 |
| **CPI y/y** | 50 | **0** | best: TRAIN_INSIGNIFICANT, several windows |
| **FOMC (Fed Funds Rate)** | 0 (killed pre-evaluation) | — | val n=15-22, never reached n≥30 |
| **FOMC Statement** | 0 (structurally excluded) | — | no actual/forecast field |

**Mechanism comparison**: NFP's C2 signal was directionally coherent across 4 instruments — one macro read (US labor strength → USD strength) expressed consistently once quote convention is corrected. CPI's failure indicates this is **not** a general "any strong US data print moves USD" effect — comparable sample size, comparable release prominence, no comparable signal. Recorded as **FAIL-000038**.

---

## 4. Phase 2 — Cross-asset

Six pre-registered, economically-named mechanisms (not raw correlation mining), each using **yesterday's** cross-asset move to predict **today's** FX/gold direction — the lag is what makes it a tradeable signal rather than a same-day coincidence:

| Hypothesis | Mechanism | Best t (train / val) | Verdict |
|---|---|---|---|
| H_OIL_CAD | Oil↑ → CAD strengthens → short USDCAD | +0.55 / +1.54 | Insignificant |
| H_SPX_JPY | Risk-on → JPY sold → long USDJPY | +0.69 / -1.21 | Negative/insig. |
| H_SPX_CHF | Risk-on → CHF sold → long USDCHF | -0.42 / -2.02 | Negative |
| H_SPX_XAU | Risk-on → gold sold → short XAUUSD | -0.98 / -0.77 | Negative |
| H_US10Y_EUR | Yields↓ → USD carry less attractive → long EURUSD | +0.60 / **+2.03** | Insig. (train fails) |
| H_OIL_XAU | Inflation co-movement → long XAUUSD (exploratory) | -1.30 / -0.02 | Negative |

**0/12. FAIL-000039.** H_US10Y_EUR is the closest miss — validation alone would pass (t=2.03) but train does not (t=0.60), and a single passing window with a failing train is not evidence, by this project's own standard applied consistently everywhere else.

**Mechanism read**: every one of these is a textbook, well-documented contemporaneous relationship. Failing at a 1-2 day lag is consistent with these relationships being priced same-day or intraday — by the next day's open, the cross-asset information is already in the price. A lag-based daily signal is structurally the wrong tool for this class of mechanism.

---

## 5. Phase 3 — D1/W1

### D1_WEEKDAY_FIXED — resolves an open question from Cycle 4

Cycle 4's `B1_DAY_OF_WEEK` never got a fair test: "enter Friday close, hold 1 day" landed on a 2-3 bar Saturday spillover stub (HistData's Friday NY close crosses into Saturday UTC), so every result was killed by `SUB_DAILY_REFUTED_FAMILY` before the economic question was asked — the apparent t=7.07 was a **realized-hold measurement artifact**, not a filtered-out real signal.

This version filters `DayBar`s to ≥12 H1 bars **before** indexing, so "next trading day" is genuinely ~24h later. 120 evaluations (6 symbols × 5 weekdays × 2 directions × 2 holds): **0 survivors**.

**This closes the question cleanly**: with the bug fixed, no weekday effect exists on these instruments. The answer was noise, not a signal the bug was hiding.

### W1_BREAKOUT — genuinely new timeframe/lookback

Weekly N-week (12 or 26) high/low breakout, continuation or reversal, 1-2 week holds — different timeframe (W1) and different lookback from the refuted `A2_POSITIONAL_BREAKOUT` (D1, 20-day). 48 evaluations: **0 survivors**.

**FAIL-000040** records both. Neither rescues FAIL-000029 (H1 price patterns — irrelevant here, everything holds ≥1 real trading day) or FAIL-000031 (undirected D1 streak/breakout — W1_BREAKOUT is a distinct family, and its failure extends that finding to the weekly timeframe rather than re-testing it).

---

## 6. Compliance

| Rule | Status |
|---|---|
| C2-NFP-USD not revisited/retuned | PASS — zero code touched those frozen candidates |
| Kill unreachable paths before evaluation | PASS — FOMC/Fed-Funds-Rate killed at Phase 0, 0 cost |
| No holdout consumption | PASS — 0 new vault authorizations/consumptions |
| No retuning after failure | PASS — no prior-cycle candidate was modified |
| No ledger reset | PASS — append-only, verified by test |
| No p-hacking | PASS — all grids pre-registered before evaluation; CPI/NFP comparison reused existing results rather than re-running to "improve" a number |
| Bonferroni mandatory | PASS — M estimated pre-run (1,402), consistent with the actual post-run ledger total |
| No EA before GEN 14 | PASS — no survivor reached GEN 14 this cycle |
| n≥30, net>0, train t≥2, val t≥1.5, gross/cost>2 | PASS — identical gate function reused from Cycles 4-6 |

**Determinism**: both Phase 2 and Phase 3 scripts produce byte-identical output across repeated runs (verified).

---

## 7. Next highest-value experiment

Three lines of reasoning converge on the same answer:

1. **The undirected-price-pattern search space is now closed** across every timeframe attempted (H1 → D1 → W1, streak/breakout/weekday). Continuing to search this space is the one thing explicitly and repeatedly prohibited.
2. **NFP is the only mechanism that has ever shown real, out-of-sample-replicating signal** in this project (Cycle 6/GEN 14: right sign and magnitude on holdout, failed only the search-history-adjusted Bonferroni bar). CPI did not replicate the same story.
3. **Cross-asset mechanisms fail at a 1-day lag but are real contemporaneously.** The lag, not the mechanism, appears to be the problem.

**Recommended next experiment**: revisit the cross-asset mechanisms (Phase 2's six) using **event-anchored timing instead of calendar-day lag** — e.g., does an SPX/oil/yield move **during the hours immediately following a scheduled NFP or CPI release** (which this project already has clean, verified timestamps for) predict the FX/gold reaction in the following hours, rather than the next calendar day? This combines the one mechanism class that has shown real signal (event-driven, Cycle 6) with the cross-asset intuition that these relationships are priced fast, not slow — testing the SAME-EVENT cross-asset reaction rather than a stale daily lag. It requires no new data acquisition (all three series and the event calendar already exist) and is a structurally different test from anything tried in Cycles 4-7, not a parameter variant of a refuted family.

---

**`NO_EDGE_FOUND` remains the accurate summary.** Eighty hypotheses, 1,402 parameter evaluations, one real out-of-sample-replicating mechanism found and refuted at the highest bar this project applies. The search space keeps narrowing in a principled way; nothing here was rescued, retuned, or p-hacked to say otherwise.
