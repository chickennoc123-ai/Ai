# ML-001 — GEN 7 CYCLE 9: POWER EXPANSION FOR SC_SURPRISE_CONFIRMATION

**Date**: 2026-08-20
**Cycle**: `CYCLE-09-SC-POWER-EXPANSION`
**Final state**: `STILL_UNDERPOWERED` — per the pre-registered decision rule, STOP
**Sealed holdout**: untouched (0 new authorizations/consumptions)
**Pre-registration**: `CYCLE9-PREREGISTRATION.md`, written and committed before evaluation ran

---

## 1. Outcome

```
outcome: STILL_UNDERPOWERED
survivors: 0
still_underpowered: 6 (the same 6 combinations that were promising in Cycle 8)
train_failed: 24 (cleanly negative/insignificant — unchanged conclusion from Cycle 8)
```

Per the frozen decision rule (§9 of the pre-registration): **STOP.** No third
expansion was attempted inside this cycle. This report states exactly what
is missing, as instructed.

---

## 2. What changed, what didn't

**Changed**: the event pool. `Non-Farm Employment Change` + `CPI y/y` grew to
include `ADP Non-Farm Employment Change` — a genuinely independent release
(median 2-day gap from NFP, checked, not simultaneous). `Federal Funds Rate`
was considered and **excluded before running anything**: verified zero of its
34 in-window actual/forecast rows have a nonzero surprise (the Fed did not
surprise on the headline rate 2010–2020-05). This is a power finding, the
same discipline Cycle 7 used to kill FOMC before evaluation, not an arbitrary
drop.

**Unchanged, verified by test to be the identical code object**: the
`trade_sc()` mechanism function, all six `(symbol, driver)` pairings, both
window grids, the cost model, the 60-second execution delay, and every gate
threshold. `discovery/cycle9_power.py` imports these from
`discovery/cycle8_intraday.py` rather than reimplementing them — a test
(`test_trade_sc_is_the_identical_function`) asserts the imported function
*is* the same Python object, ruling out silent drift.

**No acquisition was attempted.** The larger pool came entirely from using
more of the calendar file already verified in Cycle 6 (7 quality gates + a
dual-signal timezone check applied to the whole file, not only its NFP rows).
Stated explicitly in the pre-registration so this isn't mistaken for skipping
the "acquire" step — it was a deliberate choice to use verified data over
introducing an unverified new source, made **before** running anything.

---

## 3. Results

Event pool: **393** events (up from Cycle 8's 268, +47%).

| Pairing | Window | Train t | Train n | Val t | Val n (need 30) | Verdict |
|---|---|---|---|---|---|---|
| USDJPY/SPX500 | 240m | **+7.31** | 121 | +1.79 | 23 | VALIDATION_UNDERPOWERED |
| USDCHF/SPX500 | 240m | **+5.11** | 121 | +0.57 | 23 | VALIDATION_UNDERPOWERED |
| EURUSD/US10Y | 5m | +3.94 | 149 | +1.07 | 23 | VALIDATION_UNDERPOWERED |
| XAUUSD/WTICO | 5m | +3.57 | 131 | +0.11 | 22 | VALIDATION_UNDERPOWERED |
| GBPUSD/US10Y | 5m | +2.92 | 149 | −0.10 | 23 | VALIDATION_UNDERPOWERED |
| EURUSD/US10Y | 15m | +2.39 | 149 | +0.44 | 23 | VALIDATION_UNDERPOWERED |

**Train n roughly doubled** (81–93 → 121–149), exactly as the larger pool
predicts. **Validation n grew from 14–16 to 22–23** — real progress, still
short of 30 on every one of the six combinations that showed train
significance in Cycle 8.

The other 24 tested combinations remain cleanly train-negative or
train-insignificant, unchanged in conclusion from Cycle 8 (already covered by
FAIL-000041; not re-recorded).

---

## 4. Exactly what is missing — the number this report was asked to produce

The validation-period confirmation rate (~29%) is measurably **lower** than
the train-period rate (~41%) across every affected combination — consistent,
not noise. Using each combination's own observed rate:

| Pairing / window | Val n achieved | Val n required | Est. total pool needed | Shortfall vs. 393 available |
|---|---|---|---|---|
| EURUSD/US10Y (5m, 15m) | 23 | 30 | **~513** | **+120 events (~30% more)** |
| GBPUSD/US10Y (5m) | 23 | 30 | **~513** | **+120 events (~30% more)** |
| USDJPY/SPX500 (240m) | 23 | 30 | **~513** | **+120 events (~30% more)** |
| USDCHF/SPX500 (240m) | 23 | 30 | **~513** | **+120 events (~30% more)** |
| XAUUSD/WTICO (5m) | 22 | 30 | **~536** | **+143 events (~36% more)** |

**The 2010–2020-05 window is already fully used** for every USD NFP/CPI/FOMC
event type carrying `actual`+`forecast`: NFP, CPI y/y, and ADP are all
included; Federal Funds Rate is verified to contribute zero; FOMC Statement
has no actual/forecast field at all. There is no further headroom on this
axis without a **new acquisition**:

- **Extend the M1 cross-asset window past 2020-05** — the binding constraint.
  `FutureSharks/financial-data` (Oanda M1, used for WTICO/SPX500/US10Y and for
  EURUSD/GBPUSD/XAUUSD's own M1 prices) ends there for real, not by a code
  choice. A source covering 2020-06 through the present, for **both** the FX
  legs and the three drivers, at M1 or better, would be required.
- **Or accept a materially wider event-type scope** beyond the NFP/CPI/FOMC
  family — which would no longer be an "expansion" of this pre-registration
  but a new one, since it changes what mechanism-adjacent economic story is
  being tested.

Neither was attempted this cycle, per the frozen decision rule.

---

## 5. What this is not

Per FAIL-000042/FAIL-000043's own discipline, stated once more directly: this
is **not** a refutation. Every one of the six affected combinations retained
or *strengthened* its train-side signal under a larger pool (three improved:
USDJPY/SPX500 6.24→7.31, USDCHF/SPX500 4.61→5.11, EURUSD/US10Y-5m 3.75→3.94).
A mechanism that gets *stronger* as its sample grows is the opposite pattern
from one that was a statistical fluke shrinking toward zero. It remains
exactly what it was: **unresolved**, now with a precise number attached to
what resolving it requires.

---

## 6. Compliance

| Rule | Status |
|---|---|
| Same mechanism, not a new strategy | PASS — `trade_sc` is the literal same function object (tested) |
| Frozen before evaluation: event types, symbols, windows, surprise def, confirmation rule, costs, delay, gates | PASS — `CYCLE9-PREREGISTRATION.md`, committed before the run |
| n≥30 gate | PASS — unchanged, is exactly why this cycle stopped |
| No retuning thresholds | PASS — identical `2.0`/`1.5`/`2.0` gate constants |
| No window selection after seeing results | PASS — same `[5,15,30,60,120,240]` / `[60,120,240]` objects, imported not rewritten |
| No cherry-picking events | PASS — full frozen 393-event pool used, no filtering by outcome |
| No holdout touch | PASS — 0 new vault authorizations/consumptions |
| No ledger reset | PASS — append-only, verified by test |
| No re-run of only the 6 promising combinations | PASS — all 30 evaluations (6 pairings × windows) ran, not a subset |
| Run once | PASS — the reported evaluation ran once; a second run was performed only to verify byte-identical determinism (engineering check, not a second attempt at a different outcome), and is disclosed here |
| Self-critique first | PASS — §1 of `CYCLE9-PREREGISTRATION.md`, written before the run |

**Determinism**: verified byte-identical across two runs.

---

## 7. Accounting

| | This cycle | Cumulative |
|---|---|---|
| Hypotheses | 0 (re-test, not new hypothesis generation) | 86 |
| Parameter evaluations | 30 | 1,552 |
| Survivors | 0 | 5 (unchanged: parked B2_TURN_OF_MONTH + 4 terminal-FAIL C2-NFP) |

Bonferroni at M=1,552: `p < 0.05/1552 = 3.22e-05`, roughly `|t| ≥ 4.20`.

---

**`SC_SURPRISE_CONFIRMATION` is neither qualified nor refuted.** It is
underpowered by a known, now-quantified amount, on a data window that is
fully exhausted for its current design. The single next action that could
change this cycle's outcome is acquiring cross-asset M1 data past 2020-05 —
not another attempt at squeezing more out of what already exists.
