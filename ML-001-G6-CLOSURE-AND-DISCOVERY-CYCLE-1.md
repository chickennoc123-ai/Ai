# ML-001 — GENERATION 6 CLOSURE + DISCOVERY CYCLE 1

**Date**: 2026-08-19
**Branch**: `claude/ea-factory-pro-system-bc9jaa`
**Scope**: close the G6 data bottleneck, stand up GEN 7–14, run one honest discovery cycle.

---

## 1. The decisive finding

**The Generation-6 blocker was a measurement error, not a data shortage.**

HistData M1 timestamps are **EST (GMT-5, fixed, no DST)**. The earlier aggregation labeled
them UTC. Under that mislabel, every ordinary forex weekend (Fri 17:00 → Sun 17:00 EST)
appeared as a *trading-hour gap*. That produced the previous verdict — "68.9% coverage,
877 trading-hour gaps, REJECT" — and blocked the Factory behind a Dukascopy download that
organizational egress policy would not allow.

Measured against the real 24/5 trading week, the same bytes cover **~96.5%** of trading hours.

Two further defects surfaced while re-auditing:

| Defect | Evidence | Resolution |
|---|---|---|
| Claimed "no DEVELOPMENT overlap" was false | file started 2022-01-02; DEVELOPMENT ends 2022-03-05. The audit phase that should have caught this had **crashed** (`can't compare offset-naive and offset-aware datetimes`) and the report recorded PASS anyway | trimmed; independence re-verified mechanically |
| 2023 source file is degraded | 322,638 M1 rows vs ~372,000 for other years; **~830 whole trading hours absent** (~13% of 2023), alternating-hour holes | 2023 quarantined `SOURCE_DEGRADED`, excluded from the holdout |

**The lesson worth keeping: a crashed verification step that still prints PASS is more
dangerous than a failing one.**

---

## 2. Sealed primary holdout

```
DATASET_ID   DS-HOLDOUT-EURUSD-H1-HISTDATA-20240101-20260130
FILE         data/holdout/EURUSD_H1_HOLDOUT_20240101_20260130_UTC.csv
BARS         12,972   (2024-01-01T22:00Z → 2026-01-30T21:00Z)
COVERAGE     99.3% of true trading hours
RESIDUAL     5 unexplained missing hours (0.04%)   [pre-registered limit: 1%]
OHLC ERRORS  0
GATES        source ELIGIBLE · integrity PASS · independence NONE+ZERO · decision ELIGIBLE
SEAL         EvidenceVault, persisted, fresh-process verified, tamper-detection confirmed
EVALUATION   NOT_AUTHORIZED — 0 authorizations, 0 consumptions
```

The economic gate (**≥95% coverage, ≤1% residual missingness**) was fixed *before*
measurement and was never loosened. The first trimming attempt (2022-03-06 start) **failed**
that gate at 96.1%/2.97% and was not sealed; only after 2023 was excluded on evidence did
the window pass at 99.3%/0.04%.

Preserved but not sealed: `EURUSD_H1_SECONDARY_20220306_20221231_UTC.csv` (5,159 clean bars),
firewalled from research. 2023 quarantined. Pre-2022-03-06 discarded (DEVELOPMENT overlap).

Dukascopy is no longer a blocker — it remains valuable later as a **LEVEL_5 source-independence
cross-check**, not as a prerequisite.

---

## 3. Discovery cycle 1 — result: NO_EDGE_FOUND

### GEN 8 Market Observatory (`discovery/observatory.py`)
36 observations on DEV data only (first 80% = 2012-11 → 2020-04; last 20% reserved).
Pre-registered significance |t| ≥ 3.5. **14 significant**, including:

| Observation | Effect | t |
|---|---|---|
| Volatility clustering (lag-1 \|returns\|) | 0.249 | +53.5 |
| Streak anti-persistence, 2 bars | P(cont)=0.458 vs 0.501 | −9.0 |
| NR7 compression persists | next range 0.71× median | −49.6 |
| Weekend gap fills ≤24 bars | 87.6% of 386 weekends | +22.4 |
| Session volatility structure (NY late) | 1.38× average range | +37.2 |

### GEN 7 Discovery Engine (`discovery/engine.py`)
8 hypotheses generated from those observations, 4 filtered. Every hypothesis records
what/why/evidence-ids/operator/priority. The **refuted-family firewall** mechanically blocks
the RSI-oversold family that killed HYP-000001–3.

### GEN 9–11 Evaluation (`discovery/evaluation.py`)
Train (80%) → internal validation (reserved 20%, untouched by GEN 7/8). Frozen 1.1-pip cost.

**0 of 8 survived.** Seven failed at the TRAIN gate; one filter-ablation was refuted.

**The dominant failure mode is economic, not statistical.** The market structure is real and
strongly significant — it is simply *smaller than the spread* at H1:

- 2-bar streak fade: gross **+0.19 pips/trade** vs **1.1 pip** cost → net −0.92 pips (t=−10.7, n=14,786)
- Weekend gap fade: gross ~0.89 pips vs 1.1 pip cost → net −0.02 pips (n=386)

Cycle-2 cost-amortization retries (longer horizons, size-conditioned gaps) also failed.

**The one honest near-miss**: large weekend gaps (>8 pips) netted **+2.67 pips/trade**
(2.4× cost) but with n=130, t=0.99 — **underpowered, not unprofitable**. It was recorded as
`STATISTICAL_FAILURE`, and deliberately **not** promoted by relaxing the gate. Weekend gaps
arrive ~52/year; no amount of re-testing this window fixes that.

---

## 4. Knowledge captured (failure library: 22 records)

Prevention rules now enforced on future cycles:

1. Require expected gross effect ≥ **2× roundtrip cost** *before* spending a test slot.
2. A conditional **probability** edge is not a signed **return** edge — magnitude asymmetry cancels it.
3. A statistically strong market **state** does not imply a profitable **filter**; require ablation proof.
4. For event-driven families, project `event_rate × years` first — if n cannot reach t≥2.0, it is
   **untestable on this data**, and should be rejected at generation time rather than consuming budget.

---

## 5. Validation machinery (GEN 12–14) — built and proven

Built now so a future survivor meets a fully-armed gauntlet, and validated against **planted
synthetic edges** rather than real research budget:

**GEN 12 Adversarial** (`discovery/adversarial.py`) — cost shock (1.5/2/3×), execution delay,
parameter perturbation (±1/±2), subperiod (≥3 of 4 blocks), seeded bootstrap (1000 resamples,
≥95% positive), symbol shift to GBPUSD (advisory), regime shift (≥2 of 3 vol terciles).
Tests confirm it **destroys** cost-marginal, period-confined, parameter-fragile, and
high-variance fakes, and **passes** a genuinely robust one.

**GEN 13 Replication** (`discovery/replication.py`) — freeze protocol: spec hashed at freeze,
re-verified at consumption, vault authorization required, seal verified against bytes, then
one-way CONSUMED. Post-freeze spec mutation raises `FreezeViolation`. There is no read path
that does not consume.

**GEN 14 Qualification** — 11 gates; `PROVISIONALLY_PROVEN` requires **every** gate explicitly
PASS. Missing gates count as `NOT_RUN` and block: absence of evidence is never a pass.

**Holdout firewall** (`discovery/_guards.py`) — any path containing "holdout" raises before a
byte is read; enforced at loader level and tested.

---

## 6. Factory status

```
GENERATION_6_STATUS              = CLOSED
OGD4_STATUS                      = AMENDED (Amendment 1, owner-authorized)
HISTDATA_STATUS                  = ACCEPTED for 2024-01-01..2026-01-30 (2023 quarantined)
DATA_PROVENANCE                  = VERIFIED (owner-supplied archives, M1 checksums recorded)
DATA_INTEGRITY                   = PASS (0 OHLC errors, monotonic, no duplicates)
ECONOMIC_COMPATIBILITY           = PASS (99.3% coverage, 0.04% residual)
INDEPENDENCE_STATUS              = LEVEL_3 verified (no DEVELOPMENT / PURE_HOLDOUT overlap)
SEAL_STATUS                      = SEALED + fresh-process verified
EVALUATION_AUTHORIZED            = FALSE (0 authorizations, 0 consumptions)
GENERATION_7_STATUS              = OPERATIONAL (cycle 1 complete)
STRAT_000003_STATUS              = NOT CREATED (no hypothesis earned it)
NEW_HYPOTHESES                   = 8 generated, 8 refuted internally
NEW_CANDIDATES                   = 0
EDGE_STATUS                      = NO_EDGE_FOUND
FACTORY_EDGE_DISCOVERY_READINESS = READY (GEN 7-14 operational end-to-end)
BLOCKERS                         = none structural; H1 EURUSD effects are sub-cost
TEST_COUNT                       = 1145 passed, 0 failed
```

---

## 7. What the next cycle should do

The evidence points somewhere specific. EURUSD H1 probability-edges are **real but smaller
than the spread**. Three routes have genuine information value; the first is strongest:

1. **Larger per-trade targets** — multi-day/positional horizons where a fixed 1.1-pip cost is
   amortized over 30–100+ pip moves, instead of fighting it at 1-bar scale.
2. **Higher-volatility instruments** — XAUUSD or indices, where per-bar range is a large
   multiple of spread. Requires new data (dev + holdout) from the owner.
3. **Cross-sectional / multi-symbol pooling** — raises `n` for low-frequency event families
   (the weekend-gap near-miss) without reusing the same observations.

GEN 15 (EA generator: MT5 + Python) is intentionally **not built**. Building a packaging
machine for an edge that does not exist is exactly the waste the anti-waste rule forbids.
It gets built when a candidate clears GEN 14.

---

## 8. Reproduction

```bash
python3 scripts/ml_001_g6_holdout_rebuild_and_seal.py   # deterministic rebuild + seal
python3 factory.py cycle                                # observe -> discover -> evaluate
python3 factory.py status                               # factory + governance state
python3 factory.py holdout status                       # metadata only, never data
python3 factory.py failures -v                          # accumulated prevention rules
python3 -m pytest tests/ -q                             # 1145 tests
```

No randomness anywhere in the research path; identical inputs produce byte-identical registries.
