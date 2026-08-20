# ML-001 — GEN 7 CYCLE 5: EVENT-DRIVEN DISCOVERY

**Date**: 2026-08-20
**Cycle**: `CYCLE-05-EVENT-DRIVEN`
**Final state**: `NO_EDGE_FOUND` on the derivable subset; `BLOCKED_ON_DATA` for the rest
**Sealed holdout**: `UNCONSUMED`

---

## 1. Result

```
GEN_7_CYCLE_5 = {
    "families_runnable": ["C1_PRE_EVENT_POSITIONING", "C3_VOLATILITY_EXPANSION",
                          "C4_EVENT_SEQUENCE"],
    "families_blocked":  {"C2_SURPRISE_REACTION": "needs actual + forecast; not derivable"},
    "new_hypotheses": 3,
    "total_hypotheses_cumulative": 68,
    "parameter_evaluations": 155,          # 130 event sweep + 25 B2 diagnostic
    "parameter_evaluations_cumulative": 750,
    "survivors": 0,
    "killed": 130,
    "failure_modes": ["TRAIN_NEGATIVE", "TRAIN_INSIGNIFICANT", "VALIDATION_INSIGNIFICANT"],
    "final_state": "NO_EDGE_FOUND",
    "event_data_status": "NOT_SUPPLIED — all five sources denied by network policy"
}
```

### A correction to the state block in the request

The brief listed `hypotheses: 58, parameter_evaluations: 312`. Those are
pre-Cycle-4 figures. The append-only ledger reads:

| | Stated | Actual (before Cycle 5) | Now |
|---|---|---|---|
| Cumulative hypotheses | 58 | 65 | **68** |
| Cumulative parameter evaluations | 312 | 595 | **750** |

This matters directly: the GEN 14 Bonferroni gate is `p < 0.05/M`. At M=750
that demands **|t| ≥ 3.99**, not the 3.93 of an hour ago.

---

## 2. Event data — blocked

All five sources return **403 at CONNECT**; the proxy confirms policy denial,
not a transport fault. Package registries and GitHub are reachable, so this is
a scoped policy, not a broken network. Full detail in `event_calendar_report.md`.
Recorded as **FAIL-000033**.

Only the **NFP schedule** is deterministically derivable (first Friday,
08:30 ET). FOMC, CPI, GDP and rate decisions have irregular schedules; deriving
them from recollection would fabricate data, and the contract forbids it.
**C2 could not run at all** — a surprise requires a published consensus, which
no price series contains.

The infrastructure is complete and tested: contract, loader, seven quality
gates, audit CLI, all four families, 43 passing tests. Supplying a calendar
file is the only remaining step.

---

## 3. A power check that cost nothing

Before spending evaluations, event counts were checked against the `n ≥ 30`
floor — counting events costs zero parameter evaluations, while discovering
underpowerment by evaluating would have cost 26 per symbol *and* raised the
Bonferroni bar for every future candidate.

| Symbol | Events | Train | Validation | Verdict |
|---|---|---|---|---|
| EURUSD | 112 | 89 | **23** | **skipped — underpowered** |
| GBPUSD | 155 | 124 | 31 | run |
| USDCAD | 155 | 124 | 31 | run |
| USDCHF | 155 | 124 | 31 | run |
| USDJPY | 155 | 124 | 31 | run |
| XAUUSD | 160 | 128 | 32 | run |

EURUSD was declared out **before** evaluation, not discarded after.

---

## 4. Holding-period rule — stated before the run, not after

Cycle 4 imposed a 24-hour floor to stop H1 price patterns being relabelled as
positional trades. That guard was scoped to **price-pattern** families and does
not apply here: an event trade is keyed to an exogenous release time, not to a
price shape. Event families are therefore permitted sub-daily windows (1h, 4h,
12h as requested), in exchange for two obligations that are *not* relaxed:

1. realized holding time is **measured** from bar timestamps and reported —
   the FAIL-000030 lesson;
2. `gross/cost > 2.0` still binds, so a 1-hour window only qualifies if the
   release genuinely moves price by more than twice the round trip.

This distinction was written into the module docstring before the sweep ran.

---

## 5. Results — 130 evaluations, 0 survivors

| Family | Train negative | Train insignificant | Validation fail | Survivor |
|---|---|---|---|---|
| C1 pre-event positioning | 18 | 11 | 1 | 0 |
| C3 volatility expansion | 35 | 15 | 0 | 0 |
| C4 event sequence | 34 | 16 | 0 | 0 |

**Mechanism (FAIL-000034)**: a scheduled release large enough to move price is
anticipated by everyone, so the unconditional direction around it is not
predictable from the calendar alone. Without actual-vs-forecast the trade has
no informational input beyond *timing*, and timing alone carries no directional
content.

**Prevention rule**: do not re-test calendar-timing-only event families. An
event family needs a surprise measure to carry directional information.

Note what this does *not* say: C2 is **blocked**, not refuted. The family that
carries the actual information content has never been tested.

---

## 6. Compliance

| Rule | Status |
|---|---|
| No H1 price models | PASS — event families are exogenously keyed, and the exemption is documented |
| Cost model not relaxed | PASS — frozen table unchanged |
| Multiple-testing counters not reset | PASS — append-only, 750 cumulative |
| Holdout not used for discovery | PASS — loader drops post-dev events; 0 authorizations |
| No p-hacking | PASS — EURUSD excluded on a pre-check, not post-hoc |
| No fabricated data | PASS — FOMC/CPI not synthesised; C2 reported blocked |

**Failure memory added**: FAIL-000033, FAIL-000034, FAIL-000035.

---

## 7. Next

Acquiring a real economic calendar remains the highest-value action available.
It is the only thing standing between this project and the one hypothesis
family that still carries untested information content.

Everything needed to consume it is built and tested.
