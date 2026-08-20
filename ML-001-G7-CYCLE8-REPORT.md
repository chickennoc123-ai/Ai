# ML-001 — GEN 7 CYCLE 8: EVENT × CROSS-ASSET INTRADAY

**Date**: 2026-08-20
**Cycle**: `CYCLE-08-EVENT-CROSSASSET-INTRADAY`
**Final state**: `NO_EDGE_FOUND` (with one INCONCLUSIVE thread, not negative — see §4)
**Sealed holdout**: untouched (0 new authorizations/consumptions)

---

## 1. Self-critique — stated before any evaluation ran

The request specifies 5m/15m/30m/1H/2H/4H windows on five FX/gold instruments.
**This project's FX dev data is H1-only.** Testing sub-hourly windows on hourly
bars would require inventing intraday prices — the exact fabrication this
project has refused at every step (FAIL-000033's discipline for event
timestamps applies identically to price data).

Real intraday data was sought, not assumed unavailable:

| Symbol | Intraday source found? | Coverage tested |
|---|---|---|
| EURUSD | **Yes** — genuine Oanda M1, `FutureSharks/financial-data` (same audited source as Cycle 7) | All 6 windows |
| GBPUSD | **Yes** — same | All 6 windows |
| XAUUSD | **Yes** — same | All 6 windows |
| USDJPY | **No** — checked, not found | 1H/2H/4H only |
| USDCHF | **No** — checked, not found | 1H/2H/4H only |

For USDJPY/USDCHF, a second search was made specifically
(`philipperemy/FX-1-Minute-Data`) and **cloned to verify**, not assumed from
its description — it turned out to be an API client that calls `histdata.com`
directly at runtime, not a repository of committed data. Since `histdata.com`
is itself network-blocked in this environment, this path is a **confirmed
dead end**, not an unexplored option. 5m/15m/30m windows for USDJPY/USDCHF
are marked `BLOCKED_NO_INTRADAY_DATA` in the result artifact — 24 combinations,
explicit and countable, not silently dropped from the grid.

**Execution delay**: every entry fills at `release_time + 60s` using the first
real M1/H1 bar at or after that instant — never at the release timestamp
itself. Stated once, applied uniformly, not tuned per symbol.

---

## 2. Four mechanisms (pre-registered)

| Code | Mechanism | Distinct from |
|---|---|---|
| **DC** | Cross-asset divergence: driver has moved by minute 5, FX hasn't followed → bet on convergence | Requires a driver leg; no H1-family or C2-NFP analog |
| **SC** | Surprise confirmation: trade the calendar surprise direction (like Cycle 6's C2), but only when the driver's own reaction confirms the same macro read | Differs from plain C2 by *which trades are taken*, not just timing |
| **DR** | Delayed reaction: follow the driver's 5-minute impulse move, entering after it — event-anchored version of Cycle 7's failed daily lag | New anchor (event, not calendar day) |
| **RI** | Reversal after impulse: fade DR's direction, testing mean-reversion of the initial cross-asset overreaction | Exact directional opposite of DR, same entry logic |

Six `(symbol, driver)` pairings, chosen for textbook economic interpretability
(reused from Cycle 7 where sensible): `EURUSD/US10Y`, `GBPUSD/US10Y`,
`XAUUSD/SPX500`, `XAUUSD/WTICO`, `USDJPY/SPX500`, `USDCHF/SPX500`.

**Event pool**: 268 USD NFP + CPI y/y releases, 2010–2020 (bounded by the M1
cross-asset data's own coverage, same limitation Cycle 7 already established
and accepted).

---

## 3. Results — 120 evaluations, 0 formal survivors

```
DC_CROSS_ASSET_DIVERGENCE    TRAIN_INSIGNIFICANT=7   TRAIN_NEGATIVE=19  TRAIN_UNDERPOWERED=4
DR_DELAYED_REACTION          TRAIN_INSIGNIFICANT=5   TRAIN_NEGATIVE=21  TRAIN_UNDERPOWERED=4
RI_REVERSAL_AFTER_IMPULSE    TRAIN_INSIGNIFICANT=14  TRAIN_NEGATIVE=12  TRAIN_UNDERPOWERED=4
SC_SURPRISE_CONFIRMATION     TRAIN_INSIGNIFICANT=15  TRAIN_NEGATIVE=9   VALIDATION_UNDERPOWERED=6
```

**DC, DR, RI are cleanly negative.** No combination, at any window, reached
even a marginal train signal. Recorded as **FAIL-000041**: anchoring the
cross-asset signal to the event's own release minute — rather than Cycle 7's
stale calendar-day lag — did not surface a signal either. This narrows the
explanation for Cycle 7's failure: the problem is not merely that a daily lag
is too slow. Cross-asset information does not appear to predict FX/gold
direction at *any* horizon from 5 minutes to 4 hours after a shared release.

---

## 4. The finding that must not be mislabeled: SC is inconclusive, not negative

**Do not manufacture a survivor — and do not manufacture a refutation either.**
Six `SC_SURPRISE_CONFIRMATION` combinations show real train-side signal:

| Pairing | Window | Train t | Train n | Val t | Val n | Verdict |
|---|---|---|---|---|---|---|
| USDJPY/SPX500 | 240m | **+6.24** | 81 | +1.39 | **15** | VALIDATION_UNDERPOWERED |
| USDCHF/SPX500 | 240m | **+4.61** | 81 | +0.43 | **15** | VALIDATION_UNDERPOWERED |
| EURUSD/US10Y | 5m | +3.75 | 93 | +0.93 | 16 | VALIDATION_UNDERPOWERED |
| XAUUSD/WTICO | 5m | +3.47 | 80 | +0.34 | 14 | VALIDATION_UNDERPOWERED |
| GBPUSD/US10Y | 5m | +2.65 | 93 | +0.27 | 16 | VALIDATION_UNDERPOWERED |
| EURUSD/US10Y | 15m | +2.48 | 93 | +0.06 | 16 | VALIDATION_UNDERPOWERED |

Every one failed on **sample size, not sign or magnitude**. The confirmation
filter (requires both a real surprise *and* driver agreement) roughly halves
an already modest 268-event pool before the 80/20 split, leaving validation at
n=14–16 against the n≥30 floor — a **structural power limit**, not evidence
against the mechanism.

This is recorded separately, as **FAIL-000042** (`INSUFFICIENT_HISTORY`, not
`NEGATIVE_EXPECTANCY`), specifically so it is never later cited as "SC was
refuted in Cycle 8" — it was not. Conflating an underpowered result with a
negative one would misinform every future cycle that reads the failure
library, which is precisely the kind of error this project's memory system
exists to prevent.

**What is explicitly not done**: no follow-up run on just these 6 promising
rows, no re-slicing the same 268 events for a better split. Both would be
p-hacking. The correct move is a pre-registered, larger event pool, evaluated
once — stated as the recommendation, not executed here.

---

## 5. Compliance

| Rule | Status |
|---|---|
| Realistic symbol-specific costs, no zero-cost assumption | PASS — frozen `cost_model.py`, unchanged |
| Non-zero execution delay | PASS — 60s, uniform, stated |
| No parameter rescue | PASS — no prior candidate touched |
| No H1-family variant disguised as new | PASS — all four mechanisms require a cross-asset driver leg absent from every refuted H1/D1/W1 family |
| Kill on n<30, net≤0, train t<2.0, gross/cost<2 | PASS — identical gate function reused from Cycles 4-7 |
| Bonferroni / cumulative ledger mandatory | PASS — append-only, M now 1,522 |
| Every survivor falsifiable/interpretable/subperiod-robust | N/A — 0 survivors reached that stage |
| C2-NFP frozen specs untouched | PASS — verified by test |
| No holdout touched | PASS — 0 new vault authorizations/consumptions |
| Self-critique first | PASS — §1, written before the first evaluation ran |

**Determinism**: verified byte-identical across two full runs.

---

## 6. Accounting

| | This cycle | Cumulative |
|---|---|---|
| Hypotheses | 6 (pairings) | 86 |
| Parameter evaluations | 120 (+24 blocked, not counted) | 1,522 |
| Survivors | 0 | 5 (unchanged: parked B2_TURN_OF_MONTH + 4 terminal-FAIL C2-NFP) |

Bonferroni at M=1,522: `p < 0.05/1522 = 3.28e-05`, roughly `|t| ≥ 4.19`.

---

## 7. Next highest-value experiment

**Not a new mechanism — the same one, properly powered.**
`SC_SURPRISE_CONFIRMATION` is the only thread from Cycles 7–8's entire
cross-asset search that shows a coherent, sizeable train-side signal (t up to
6.24) rather than flat or negative statistics. Before it can be trusted or
discarded, it needs a pre-registered event pool large enough to clear n≥30 in
validation — concretely, extending the USD event-type list beyond NFP/CPI
(subject to FAIL-000038's caution: each type must be tested on its own merits,
not assumed to inherit NFP's coherence) or extending the usable calendar year
range. This must be decided and pre-registered *before* the next evaluation,
not chosen by looking at which extension gives the best result.

---

**`NO_EDGE_FOUND` remains accurate as the formal outcome — zero candidates
reached `DISCOVERY_SURVIVOR`.** But the honest summary has two parts, not one:
DC/DR/RI are genuinely refuted; SC is unresolved and worth returning to. Both
statements are evidence, not opinion, and neither should be flattened into the
other.
