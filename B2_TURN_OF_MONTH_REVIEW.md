# B2_TURN_OF_MONTH — Independent Review

**Candidate**: XAUUSD long, enter 1 day before month end, hold 2 days (48h realized)
**Status**: `DISCOVERY_SURVIVOR` — held, not promoted, not killed
**Holdout**: `UNCONSUMED`
**Recommendation**: **do not spend the holdout**; option (b) is blocked on data

---

## 1. What was asked, and what could be answered

| Requested | Status |
|---|---|
| Test on independent gold data | **BLOCKED** — no second gold series exists in the project |
| Understand the turn-of-month effect | Done — Q1, Q2 below |
| Assess whether an exogenous prior is needed | Done — Q3 below |
| Decide: holdout or kill | **Recommend: neither yet** — see §6 |

All probes are **diagnostic**. None can promote the candidate, and the
conditioned variants in Q3 are explicitly **not adopted** — selecting the better
split after seeing it is exactly the fitting this project exists to prevent.
All 25 probes are counted in the ledger.

---

## 2. Q1 — Is it a gold effect or a USD effect?

Same rule, every instrument:

| Symbol | n | mean net | t | gross/cost |
|---|---|---|---|---|
| EURUSD | 112 | −0.000020 | −0.04 | 45.0 |
| GBPUSD | 154 | −0.001509 | **−2.75** | 45.9 |
| USDCAD | 154 | −0.000571 | −1.07 | 34.7 |
| USDCHF | 154 | +0.000134 | +0.25 | 27.9 |
| USDJPY | 154 | +0.000155 | +0.28 | 49.8 |
| **XAUUSD** | 160 | **+0.002772** | **+2.87** | 47.8 |

**1 of 6 significant. GBPUSD is significantly *negative*.**

This is the most important finding in the review, and it cuts against the
candidate. The stated mechanism — *month-end portfolio rebalancing flow* —
predicts a cross-instrument footprint, because rebalancing touches every asset.
The data shows no such footprint.

Two readings remain: the mechanism is gold-specific for a reason not yet
articulated, or the effect is noise that happened to land on the one instrument
out of six we then selected *because* it looked good. The review cannot
distinguish them, and that is itself the problem.

---

## 3. Q2 — Is it stable through time?

**10 of 15 years net-positive. 2020 alone contributes 26% of all profit.**

2020 is the COVID gold surge. A month-end rule sampled during a year when gold
trended hard upward will book that trend as month-end alpha. Combined with the
Cycle 4 finding that 2 of 4 training blocks are flat (t = −0.13 and +0.45), the
effect is **carried by a minority of the sample**.

---

## 4. Q3 — Does an exogenous prior explain when it works?

Split by conditions measured from **other instruments only** (never gold):

| Prior month state | n | mean net | t |
|---|---|---|---|
| USD strong | 82 | +0.003291 | +2.29 |
| USD weak | 70 | +0.001891 | +1.47 |
| **Risk-off** (CHF bid) | 71 | **+0.004375** | **+2.92** |
| **Risk-on** | 81 | +0.001131 | +0.90 |

The effect is roughly **four times larger in risk-off months** and statistically
absent in risk-on months.

Read carefully, this weakens rather than strengthens the candidate. A month-end
*flow* effect should not care about risk sentiment — flows rebalance on the
calendar regardless. A *risk-off gold trend* would look exactly like this. The
conditional result is consistent with the effect being a sampling of gold's
risk-off drift at month boundaries, rather than a rebalancing mechanism.

**The conditioned variant is not adopted.** Doing so would mean picking the
better of two splits after seeing both.

---

## 5. Q4 — Independent gold data

**Not available.** The project holds one XAUUSD vendor series, already split
into development (used above) and a reserved holdout. Option (b) as framed —
"test on independent gold data before spending the holdout" — **cannot be
completed without new acquisition**.

What would satisfy it:

1. a second vendor's XAUUSD H1/D1 covering 2010–2023;
2. **gold futures (GC) settlement data** — a different instrument with
   different month-end mechanics, which makes it a genuinely independent test
   of the rebalancing story rather than a re-run of the same prices;
3. any XAUUSD history predating 2009.

Option 2 is the strongest: if month-end rebalancing flow is real, it should
appear in GC. If the effect is gold-spot-specific and absent in futures, the
mechanism story fails.

---

## 6. Recommendation

**Hold. Do not spend the holdout. Do not kill it yet.**

Against spending it:

- The stated mechanism predicts a cross-sectional footprint the data does not
  show (Q1).
- The effect is concentrated in a minority of years (Q2).
- It behaves like a risk-off gold trend, not a calendar flow (Q3).
- At **M = 750** cumulative evaluations, GEN 14's Bonferroni gate demands
  **|t| ≥ 3.99**. The candidate shows t ≈ 2.2 on development data. Spending the
  holdout would almost certainly burn it for a `FAIL`.

Against killing it:

- It survived all five binding GEN 12 attacks, including 3× cost shock.
- 10 of 15 years positive with `gross/cost ≈ 48` is not nothing.
- The decisive test (GC futures) is cheap to run and has not been tried.

**Recorded as FAIL-000035** (`PARAMETER_FRAGILITY`) with the prevention rule:

> Do not spend a sealed holdout on a candidate whose stated mechanism predicts
> a cross-sectional footprint that the data does not show. Resolve the
> mechanism question on non-sealed data first.

---

## 7. What would change the recommendation

| Evidence | Then |
|---|---|
| GC futures show the same month-end effect | Mechanism corroborated → consider GEN 14 |
| GC futures show nothing | Mechanism refuted → kill, record, move on |
| A second gold vendor reproduces it at t ≥ 3 | Strong enough to justify the holdout shot |
| Nothing new acquired | Hold indefinitely; it costs nothing to leave it parked |

The candidate is parked, fully documented, and reproducible. It is not going
anywhere, and neither is the holdout.
