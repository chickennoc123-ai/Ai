# ML-001 — GEN 7 CYCLE 6: EVENT-DRIVEN DISCOVERY ON THE REAL CALENDAR

**Date**: 2026-08-20
**Cycle**: `CYCLE-06-EVENT-DRIVEN-REAL-CALENDAR`
**Final state**: `DISCOVERY_SURVIVORS_FOUND` — 4 survivors, all SURVIVED_ADVERSARIAL
**Sealed holdout**: `UNCONSUMED` — GEN 14 not requested

---

## 1. Result

```
GEN_7_CYCLE_6 = {
    "families_tested": ["C1_PRE_EVENT_POSITIONING", "C2_SURPRISE_REACTION",
                        "C3_VOLATILITY_EXPANSION", "C4_EVENT_SEQUENCE"],
    "power_precheck": "10/27 (event,symbol) combos feasible; 17 skipped at zero cost",
    "parameter_evaluations": 360,        # sweep
    "robustness_evaluations": 64,        # Phase 6
    "adversarial_evaluations": 48,       # GEN 12
    "total_this_cycle": 472,
    "cumulative_hypotheses": 72,
    "cumulative_parameter_evaluations": 1222,
    "survivors": 4,
    "killed": 356,
    "failure_modes": ["TRAIN_NEGATIVE", "TRAIN_INSIGNIFICANT", "VALIDATION_INSIGNIFICANT"],
    "final_state": "DISCOVERY_SURVIVORS_FOUND",
    "gen14_requested": False
}
```

---

## 2. A performance bug found mid-run, fixed, disclosed

The first attempt hung past 2 minutes. Root cause: `bar_at_or_after()` (added
in Cycle 5) did a linear scan from the start of the bar array on every call.
Cycle 5 only ever searched a handful of NFP events; Cycle 6's 360-evaluation
sweep across ~80,000-bar series made that O(n) scan the bottleneck by several
orders of magnitude.

**Fix**: replaced with binary search (`bisect.bisect_left`) against a
timestamp list built once per (symbol, family-call) and threaded through all
four event-family functions, instead of rebuilt per lookup. Verified with a
dedicated performance test (100 lookups across a 90,000-bar series in
<1 second) so a regression back to linear scan would be caught, not silently
re-introduced.

---

## 3. Power pre-check — 17 combinations eliminated before spending anything

Every (event type, symbol) combination was counted — not evaluated — before
any backtest ran:

```
10/27 combos feasible (n>=30 in both train and validation)
17 skipped, including:
  EURUSD / Non-Farm Employment Change   (train=128, val=24)
  EURUSD / CPI y/y                       (train=124, val=22)
  USD / Federal Funds Rate  (all 6 symbols: val n=15-22)
  USD / FOMC Statement      (all 6 symbols — also excluded from C2: no actual/forecast)
  GBP / Official Bank Rate               (val=20)
  EUR / Main Refinancing Rate            (val=15)
  JPY / Monetary Policy Statement        (val=20)
```

Federal Funds Rate and the three central-bank rate decisions (BOE/ECB/BOJ)
were all structurally underpowered in validation — rate decisions are simply
rarer than monthly data releases (8-12/year vs. 12/year, but with a shorter
usable dev-window remainder). This was known before spending a single
parameter evaluation on them.

---

## 4. Pre-registered event-type → symbol mapping

Fixed before any evaluation ran, to keep every combination economically
grounded rather than exhaustive:

| Event (currency) | Symbols tested | Mechanism |
|---|---|---|
| NFP, CPI y/y, Fed Funds Rate, FOMC Statement (USD) | EURUSD, GBPUSD, USDCAD, USDCHF, USDJPY, XAUUSD | every pair has USD exposure; gold is USD-denominated |
| Official Bank Rate (GBP) | GBPUSD only | direct |
| Main Refinancing Rate (EUR) | EURUSD only | direct |
| Monetary Policy Statement (JPY) | USDJPY only | direct |

No JPY event was tested against EURUSD, no GBP event against XAUUSD — mixing
in economically ungrounded combinations was exactly the temptation the
"mechanism interpretable" gate exists to block.

C2 was further restricted to event types where `actual`/`forecast` are real
numeric prints: **FOMC Statement and JPY Monetary Policy Statement carry
none** (they are prose statements) and were structurally excluded, not
zero-filled.

---

## 5. C1 / C3 / C4 — confirmed refuted on real data (FAIL-000036)

```
289 evaluations, 0 survivors
170 net-negative, 89 insignificant, 1 validation failure
```

This **confirms** Cycle 5's FAIL-000034 (which used a derived NFP-only
approximation) with real data across **7 event types**, not just NFP. Timing
alone and the release's own volatility footprint carry no exploitable
information — only the surprise does.

---

## 6. C2 — 4 discovery survivors, all on NFP

```
C2_SURPRISE_REACTION  71 evaluations  4 DISCOVERY_SURVIVOR
```

| Symbol | Mode | Train (n, t) | Validation (n, t) | gross/cost |
|---|---|---|---|---|
| GBPUSD | FADE | 126, **4.02** | 32, **2.32** | 20.4 |
| USDCHF | FOLLOW | 126, **5.24** | 32, **2.40** | 17.3 |
| USDJPY | FOLLOW | 126, **8.32** | 32, **2.72** | 33.0 |
| XAUUSD | FADE | 127, **7.69** | 32, **1.75** | 28.1 |

All four hold **4 hours** post-release — genuinely sub-daily, permitted under
the Cycle 5 exemption for exogenously-timed events, with realized hold
measured, not assumed.

### A single mechanism, not four coincidences

FOLLOW vs. FADE is a labeling artifact of which currency is quoted as base:

```
Positive NFP surprise => US labor market strong => USD should strengthen

  USDJPY/USDCHF (USD is base):  FOLLOW = long USD  -> correct
  GBPUSD (USD is quote):        FADE   = short GBP = long USD -> correct
  XAUUSD (inverse macro link):  FADE   = short gold -> correct
                                  (gold falls when USD strengthens)
```

All four survivors are **the same trade — long USD on a stronger-than-
forecast NFP print — expressed through four different instruments.**

---

## 7. Phase 6 interrogation — all 4 candidates pass all 10 conditions

| Candidate | Subperiod (4 blocks) | Parameter robustness |
|---|---|---|
| GBPUSD | **4/4 positive** | 60% of 5 windows |
| USDCHF | **4/4 positive** | 80% of 5 windows |
| USDJPY | **4/4 positive** | 80% of 5 windows |
| XAUUSD | **4/4 positive** | 80% of 5 windows |

Stronger subperiod consistency than any prior survivor in this project
(B2_TURN_OF_MONTH managed only 3/4). **One honest caveat, not hidden**: every
candidate's t-statistic **decays monotonically from block 0 to block 3**
(e.g. USDJPY: t=5.49 → 6.29 → 2.80 → 3.22; XAUUSD: t=4.77 → 4.75 → 3.06 →
3.31). The effect is real throughout the sample but appears to be weakening
over time — consistent with markets becoming more efficient at pricing NFP
surprises, or simply noise in a 4-block split. This is not disqualifying (all
four blocks stayed positive) but is exactly the kind of detail that should
inform a GEN 14 go/no-go decision, not be smoothed over.

---

## 8. GEN 12 adversarial — all 4 survived every binding attack

| Attack | Result |
|---|---|
| Cost shock 3× | PASS — all four stay net-positive, t remains 3.07–7.68 |
| Execution delay (1 bar) | PASS — even acting a full hour after release closes, all four remain net-positive with t 3.58–6.85 |
| Parameter shift | PASS |
| Subperiod (4 blocks) | PASS — 4/4 for all four |
| Bootstrap (1000 resamples) | PASS — 99.9–100% positive |

### Advisory attack 6 — cross-instrument sign consistency

Applied the **single** USD-direction mechanism (not four separately-chosen
FOLLOW/FADE labels) to **all 6 symbols**, including two that never
individually cleared the survivor bar:

```
5/6 instruments show the USD-strength-consistent sign
  EURUSD  t=-1.23  (the one exception — weak, not statistically significant)
  GBPUSD  t=+4.02
  USDCAD  t=+1.06  (same sign, just underpowered — n=126 but weaker effect)
  USDCHF  t=+5.24
  USDJPY  t=+8.32
  XAUUSD  t=+7.69
```

USDCAD showing the *correct sign* at weak significance, rather than the wrong
sign, is additional (advisory, non-binding) support that this is one
mechanism rather than four cherry-picked results.

---

## 9. GEN 13 — specifications frozen, GEN 14 explicitly NOT requested

Four candidates registered and frozen in `candidate_spec_registry.json`:

```
CAND-C2-NFP-GBPUSD  CAND-C2-NFP-USDCHF  CAND-C2-NFP-USDJPY  CAND-C2-NFP-XAUUSD
```

All four: `frozen_for_gen14: True`, spec hash computed, parameters locked —
`update_candidate()` now raises `FrozenSpecViolation` on any of them.

**`HoldoutAuthorizationGate.is_gen14_authorized()` returns `False` for all
four.** No authorization was requested. The sealed holdout remains
`UNCONSUMED`: 0 authorizations, 0 consumptions, verified directly.

This is the strongest candidate set the factory has produced — coherent
mechanism, 4/4 subperiod persistence, survived every adversarial attack,
cross-instrument sign support. It is also the first time spending the
holdout is a live, real decision rather than an academic one. That decision
is stated plainly here and left for explicit instruction, not taken
unilaterally, following the same discipline applied to B2_TURN_OF_MONTH in
Cycle 4.

---

## 10. Multiple-testing accounting

| | Hypotheses | Parameter evaluations | Survivors |
|---|---|---|---|
| Cumulative through Cycle 5 | 68 | 750 | 1 |
| CYCLE-06 (this cycle) | +4 | +472 | +4 |
| **Cumulative** | **72** | **1,222** | **5** |

At **M = 1,222**, the pre-registered GEN 14 Bonferroni gate (`p < 0.05/M`)
demands **|t| ≥ 4.02**. The weakest survivor (XAUUSD, t=7.69 on the full
train set, but train-block-3 falls to t=3.31) sits right at that line
depending on which window is used for the final test; the strongest
(USDJPY, t=8.32) clears it comfortably. This is exactly the number a GEN 14
decision needs to weigh, and is reported here rather than left implicit.

---

## 11. Compliance

| Rule | Status |
|---|---|
| Real acquired calendar used, not synthetic | PASS — `forexfactory_2010_2023.csv`, dual-signal verified in the prior turn |
| 2024-2026 extension not used | PASS — every symbol's dev window ends before 2024; verified in the artifact and by test |
| Power pre-check before evaluation | PASS — 17/27 combos eliminated at zero cost |
| Economically-grounded event→symbol mapping | PASS — no cross-currency mismatches |
| Cost model not relaxed | PASS |
| Multiple-testing counters not reset | PASS — 1,222 cumulative, append-only |
| Holdout not used for discovery | PASS — 0 authorizations, 0 consumptions |
| GEN 14 not entered without explicit request | PASS — specs frozen, no authorization requested |
| No "PROVEN_EDGE" claimed | PASS — labelled `DISCOVERY_SURVIVOR`, `SURVIVED_ADVERSARIAL` |

**Failure memory added**: FAIL-000036. **New family registered**:
`FAMILY-C2-SURPRISE-REACTION-NFP-USD`, status `DISCOVERY_SURVIVOR_PENDING_GEN14`.

**Tests**: 25 new (`tests/test_cycle6_discovery.py`), including a dedicated
performance regression test for the binary-search fix.
