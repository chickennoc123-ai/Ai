# ML-001 — GEN 7 CYCLE 4: ECONOMIC-STRUCTURE DISCOVERY

**Date**: 2026-08-20
**Cycle**: `CYCLE-04-ECONOMIC-STRUCTURE`
**Final state**: `DISCOVERY_SURVIVORS_FOUND` — 1 survivor, awaiting a GEN 14 decision
**Sealed holdout**: still `UNCONSUMED`

---

## 1. Result

```
GEN_7_CYCLE_4 = {
    "families_tested": ["A1_POSITIONAL_STREAK", "A2_POSITIONAL_BREAKOUT",
                        "B1_DAY_OF_WEEK", "B2_TURN_OF_MONTH", "B3_QUARTER_TURN",
                        "C1_NFP_CALENDAR_PROXY", "E1_CROSS_ASSET_CONVERGENCE"],
    "new_hypotheses": 7,
    "total_hypotheses_cumulative": 65,
    "parameter_evaluations": 283,
    "parameter_evaluations_cumulative": 595,
    "survivors": 1,
    "killed": 225,
    "failure_modes": ["SUB_DAILY_REFUTED_FAMILY", "TRAIN_NEGATIVE",
                      "TRAIN_INSIGNIFICANT", "VALIDATION_NEGATIVE",
                      "VALIDATION_INSIGNIFICANT", "VALIDATION_UNDERPOWERED"],
    "search_space_eliminated": ["daily positional momentum + breakout (6 symbols)",
                                "cross-asset z-spread convergence (5 pairs)",
                                "quarter-turn drift", "day-of-week (as sub-daily artifact)"],
    "candidates_forwarded_to_GEN12": 1,
    "final_state": "DISCOVERY_SURVIVORS_FOUND",
    "next_cycle_recommendation": "see section 7"
}
```

---

## 2. Phase 0 — state verification

| # | Check | Result |
|---|---|---|
| 1 | FAIL-000029 recorded | PASS (29 failures) |
| 2 | 58 cumulative hypotheses | PASS |
| 3 | Holdout intact (sealed, UNEXPOSED, 0 auth, 0 consumed) | PASS |
| 4 | OGD-4 Amendment 3 active | PASS |
| 5 | 312 cumulative parameter evaluations | PASS |
| 6 | H1 family marked REFUTED | **FAILED → FIXED** |

Check 6 was a real gap: `FAMILY-H1-PRICE-PATTERN` had never been written to the
refuted-family registry, so the GEN 7 firewall could not have blocked an H1
variant. It is now registered as `REFUTED`, `refuted_by: FAIL-000029`.

---

## 3. The bug that would have produced a fake edge

The first sweep reported **4 survivors**. Three were the same trade on three
instruments:

```
B1_DAY_OF_WEEK  USDCHF  weekday=4 dir=-1 hold=1d
   train  n=535  net=+0.000380  t=+7.07  win_rate=0.62
   val    n=133  net=+0.000409  t=+4.35  win_rate=0.68
```

`t = 7.07` with 62% win rate. It was an artifact.

HistData is EST-sourced; converting to UTC pushes the last 2–3 hours of the
Friday NY session onto **Saturday** in UTC. My calendar-day resampler therefore
emits a 2-bar Saturday stub, and **665 of 669 Fridays are followed by one**:

```
entry day  2010-08-06 Fri  bars=15  last H1 ts = 2010-08-06 23:00
exit  day  2010-08-07 Sat  bars=2   last H1 ts = 2010-08-07 01:00
REALIZED HOLD = 2 hours  --  declared as "1 day"
```

So "enter Friday close, hold one day" was really a **2-hour intraday trade** —
inside the exact space FAIL-000029 refuted.

**Root cause in my own code**: the structural guard compared
`min_hold_hours = hold * 24` — a *declared parameter* — against
`MIN_HOLDING_HOURS`. It never measured anything. The rule `MIN_HOLDING_HOURS = 24`
was pre-registered before the run; the implementation simply failed to enforce it.

**Fix**: `DayBar` now carries the timestamp of its final H1 bar, every trade
records `realized_hours`, and the gate rejects on **median measured hold**
before any other test. Re-run: those 3 became `SUB_DAILY_REFUTED_FAMILY`, along
with 21 more evaluations across B1 and C1 — **24 disguised sub-daily trades
caught in total**.

Recorded as **FAIL-000030** (`TEMPORAL_INVALIDITY`, `ARCHITECTURE_TRANSFERABLE`):

> Measure realized holding time from actual bar timestamps and gate on the
> median. Never infer holding period from a declared parameter.

---

## 4. Sweep results — 226 evaluations

| Family | Survivor | Sub-daily | Train neg. | Train insig. | Val. fail |
|---|---|---|---|---|---|
| A1 positional streak | 0 | 0 | 26 | 21 | 1 |
| A2 positional breakout | 0 | 0 | 13 | 10 | 1 |
| B1 day-of-week | 0 | **12** | 36 | 12 | 0 |
| B2 turn-of-month | **1** | 0 | 13 | 9 | 1 |
| B3 quarter-turn | 0 | 0 | 13 | 7 | 4 |
| C1 NFP calendar proxy | 0 | **12** | 13 | 10 | 2 |
| E1 cross-asset convergence | 0 | 0 | 4 | 6 | 0 |

### Cost amortization worked — and revealed a different problem

Families A1/A2 cleared `gross/cost > 2.0` comfortably at 5–10 day holds. The
cost floor from FAIL-000029 was genuinely defeated. They still failed, because
the underlying daily continuation/reversion effect **is not directionally
stable**. That is a *different* failure mode, recorded as **FAIL-000031**:

> Positional families need an exogenous directional prior (flow, positioning,
> macro state), not price history alone.

Cross-asset convergence (**FAIL-000032**) failed on economics: two legs pay two
spreads, and a 2σ daily spread is as often a regime change as a dislocation.
New rule — a two-legged structure must clear `gross/cost > 4.0`, not 2.0.

### Scope limit stated plainly

C1 uses only **calendar-derivable** events (first Friday = NFP). FOMC, CPI and
central-bank decisions need a real event feed, which this project does not have.
Family C is therefore only **partially** explored, not refuted.

---

## 5. The survivor

```
B2_TURN_OF_MONTH  XAUUSD  window=[1,1] dir=LONG hold=2 days
   train  n=127  net=+0.002434  t=+2.20  pf=1.685  gross/cost=47.9  hold=48.0h
   val    n= 33  net=+0.004072  t=+2.06  pf=2.515  gross/cost=47.6  hold=48.0h
```

Long gold from the close one day before month-end, exit two days later.
Mechanism: month-end portfolio rebalancing flow.

### All ten conditions

| # | Condition | Result |
|---|---|---|
| 1 | n ≥ 30 | PASS (127 / 33) |
| 2 | net > 0 | PASS |
| 3 | train t ≥ 2.0 | PASS (2.20) |
| 4 | val t ≥ 1.5 | PASS (2.06) |
| 5 | gross/cost > 2.0 | PASS (47.9) |
| 6 | subperiod persistence | PASS (3/4 blocks) |
| 7 | parameter robustness | PASS (80% of 15 neighbours) |
| 8 | mechanism interpretable | PASS |
| 9 | family not refuted | PASS |
| 10 | multiple-testing accounted | PASS (595 cumulative) |

### GEN 12 adversarial — survived all five binding attacks

| Attack | Result |
|---|---|
| Cost shock 1.5× / 2× / 3× | PASS — net stays positive, t = 2.77 / 2.66 / 2.46 |
| Execution delay 1 day | PASS — net +0.00126, but **t collapses to 1.19** |
| Parameter shift ±1 | PASS |
| Subperiod (4 blocks) | PASS (3/4) |
| Bootstrap 1000 resamples | PASS (100% positive) |
| Symbol shift (advisory) | 2 of 5 other instruments net-positive |

**Verdict: `SURVIVED_ADVERSARIAL`.**

### Three things I will not soften

1. **The effect is concentrated.** Blocks 1 and 2 of the training period are
   flat (t = −0.13 and +0.45). Almost all of it lives in blocks 0 and 3.
2. **Timing is fragile.** One day of entry delay drops t from 2.20 to 1.19.
   The gate only required net > 0, and it passed — but barely.
3. **It will very likely fail GEN 14.** With 595 cumulative parameter
   evaluations, the pre-registered Bonferroni gate G5 demands
   `p < 0.05/595 = 8.4e-5`, i.e. roughly **|t| ≥ 3.94**. This candidate shows
   t ≈ 2.2 on development data. For it to pass, the holdout would have to show
   a *much stronger* effect than development did.

This is not an edge. It is a `DISCOVERY_SURVIVOR`.

---

## 6. A decision that is yours, not mine

GEN 14 is one-shot and irreversible. Two facts matter:

- The XAUUSD holdout (2023-04 → 2026-08, 20,000 bars) exists but was **never
  sealed into the evidence vault** — only EURUSD was. It must be sealed and
  registered before it could legitimately be consumed.
- On the arithmetic above, consuming it most likely **burns the asset for a
  candidate that cannot clear G5**.

I have not consumed it and I will not without your instruction. The options:

**(a) Spend it.** Seal the XAUUSD holdout, freeze the spec, authorize, take the
one shot. Gets a terminal answer; probably `FAIL`; holdout gone forever.

**(b) Hold it.** Keep the candidate at `DISCOVERY_SURVIVOR`, and first reduce
the multiple-testing denominator problem — e.g. pre-register this single
mechanism and test it on *independent* gold data (a different vendor, or a
longer history) before spending the sealed holdout.

**(c) Kill it.** Judge t ≈ 2.2 with a concentrated effect and delay-fragility
insufficient to be worth a holdout shot, record it, and move to Cycle 5.

My recommendation is **(b)**: the candidate is interesting enough not to
discard, and too weak to justify spending the only independent evidence the
project owns.

---

## 7. Next cycle recommendation

1. **Acquire an event calendar.** Family C is the only one of the five that
   remains genuinely unexplored, and it is unexplorable without FOMC/CPI/NFP
   timestamps. This is the highest-value data acquisition available.
2. **Give positional families a directional prior** (FAIL-000031). Price history
   alone does not supply one.
3. **Do not widen the grid further.** Every added probe raises the Bonferroni
   bar for every future candidate. At 595 evaluations the bar is already
   |t| ≈ 3.9; at 1000 it becomes ≈ 4.1. Search breadth is not free, and the
   ledger makes the price explicit.

---

## 8. Compliance

| Rule | Status |
|---|---|
| No H1 price models continued | PASS — 24 disguised attempts caught and killed |
| Cost model not relaxed | PASS — frozen table unchanged |
| Multiple-testing counters not reset | PASS — append-only, 595 cumulative |
| No H1 variant renamed as a new family | PASS — realized-hold guard enforces this structurally |
| Holdout not used for discovery | PASS — 0 authorizations, 0 consumptions |
| No candidate passed without the economic filter | PASS |
| No "PROVEN_EDGE" claimed from backtest | PASS — labelled `DISCOVERY_SURVIVOR` |
| No EA built without a survivor | PASS — `artifacts/ea/` still empty |

**Failure memory added**: FAIL-000030, FAIL-000031, FAIL-000032.
