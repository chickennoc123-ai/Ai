# SC_SURPRISE_CONFIRMATION — Experimental EA

> **⚠ EXPERIMENTAL / UNRESOLVED. NOT A PROVEN EDGE.**
> No combination in this product has cleared internal validation. None is
> authorized for GEN 14. None has been evaluated against the sealed
> holdout. Do not deploy real capital against this evidence alone.

---

## 1. What this is

A packaged, deployable implementation of the `SC_SURPRISE_CONFIRMATION`
mechanism researched in **ML-001 GEN 7 Cycles 8–9**, exactly as it was
measured — not retuned, not strengthened, not reframed as more conclusive
than it is.

**There is no single "the frozen specification."** The research produced
**six** distinct `(symbol, driver, window)` combinations that showed
train-side statistical significance. This product freezes all six,
individually, via the project's own candidate registry
(`reports/factory/candidate_spec_registry.json`, `CAND-SC-*` entries), and
ships an operator-selectable EA that can run exactly one at a time.

## 2. The mechanism

For a scheduled USD macro release (NFP, CPI y/y, or ADP Non-Farm Employment
Change):

1. Wait **60 seconds** after the release (execution-delay realism, not the
   release timestamp itself).
2. Record the FX pair's price and a **cross-asset driver's** price
   (10-year Treasury price, S&P 500, or WTI crude, depending on the
   combination) at that moment.
3. Wait until **5 minutes** after the release. Check whether the driver has
   moved, and in which direction.
4. If the driver's move **confirms** the direction implied by the release's
   surprise (`actual − forecast`, sign-mapped through each pair's quote
   convention), enter the FX pair in that direction.
5. Exit at the combination's frozen window (5, 15, or 240 minutes after the
   release).
6. If the driver does **not** confirm — or the release wasn't a surprise at
   all (`actual == forecast`) — no trade is taken.

This is **not** the same as the simpler C2 mechanism from Cycle 6 (which
just traded the surprise direction on NFP alone, with no cross-asset
confirmation). That mechanism *was* taken to GEN 14 as four frozen
candidates (`CAND-C2-NFP-GBPUSD/USDCHF/USDJPY/XAUUSD`) and **all four
returned a terminal FAIL** against the sealed holdout. SC_SURPRISE_
CONFIRMATION is a different, more restrictive mechanism that has not yet
reached that stage at all.

## 3. The six frozen combinations

| Candidate ID | Symbol | Driver | Window | Train t (n) | Val t (n, need 30) |
|---|---|---|---|---|---|
| `CAND-SC-USDJPY-SPX500-240M` | USDJPY | SPX500 | 240 min | **+7.31** (121) | +1.79 (23) |
| `CAND-SC-USDCHF-SPX500-240M` | USDCHF | SPX500 | 240 min | +5.11 (121) | +0.57 (23) |
| `CAND-SC-XAUUSD-WTICO-5M` | XAUUSD | WTICO (Oil) | 5 min | +3.57 (131) | +0.11 (22) |
| `CAND-SC-EURUSD-US10Y-5M` | EURUSD | US10Y | 5 min | +3.94 (149) | +1.07 (23) |
| `CAND-SC-GBPUSD-US10Y-5M` | GBPUSD | US10Y | 5 min | +2.92 (149) | −0.10 (23) |
| `CAND-SC-EURUSD-US10Y-15M` | EURUSD | US10Y | 15 min | +2.39 (149) | +0.44 (23) |

**Every single one failed the validation gate on sample size** (`n < 30`),
not on sign or magnitude. See `ML-001-G7-CYCLE9-REPORT.md` for the full
account, including why the underlying data window cannot currently be
extended further (`ML-001-G7-CYCLE10-REPORT.md`).

## 4. Exact evidence status

| Question | Answer |
|---|---|
| Cleared internal train gate? | Yes, all six (t ≥ 2.0) |
| Cleared internal validation gate? | **No — none of the six** (n < 30 on every one) |
| Frozen via `candidate_spec_registry.py`? | Yes, this cycle, all six |
| Authorized for GEN 14? | **No** |
| Evaluated against the sealed holdout? | **No — the holdout has not been touched for this mechanism** |
| A "proven edge"? | **No.** See §7. |

## 5. Cost and execution assumptions (frozen)

Per-symbol round-trip cost, taken verbatim from `discovery/cost_model.py`
(unchanged since Cycle 3):

| Symbol | Frozen relative round-trip cost |
|---|---|
| EURUSD | 1.00e-4 |
| GBPUSD | 1.20e-4 |
| USDCHF | 1.90e-4 |
| USDJPY | 1.00e-4 |
| XAUUSD | 2.00e-4 |

60-second execution delay, applied uniformly, is not a tunable input in the
EA — it is a hardcoded constant checked against the frozen spec at startup.

## 6. Files

```
ea_products/sc_surprise_confirmation/
  frozen_spec.py            single source of truth; loads + verifies the 6
                             frozen candidates from the project's own
                             candidate_spec_registry.json
  config_validator.py       rejects any operator config that doesn't match
                             a frozen combination exactly
  config/
    frozen_spec.json         exported snapshot the MQL5 EA's constants were
                             transcribed from
    example_config.json      one example config (informational only)
  replay/
    replay_engine.py         ground-truth Python reference; imports the
                             EXACT research trade logic
                             (discovery.cycle8_intraday.trade_sc), never
                             reimplements it
  mql5/
    SC_SurpriseConfirmation_EXPERIMENTAL.mq5
  README.md                  this file
  AUDIT_REPORT.md             independent audit against every stated rule
```

Tests: `tests/test_ea_sc_product.py` (repo-root `tests/`, per project
convention, so `pytest tests/` picks them up alongside everything else).

## 7. Known limitations — read before doing anything else

1. **Sample size, not effect size, is the open question.** Every
   combination's train-side t-statistic *strengthened* between Cycle 8 and
   Cycle 9 as the event pool grew (e.g. USDJPY/SPX500: 6.24 → 7.31) — the
   opposite pattern from a statistical fluke shrinking toward zero — but
   validation n never reached 30 on any of them. This is genuinely
   ambiguous evidence, not a disguised negative result.
2. **The data window to resolve this is not currently available.**
   Cycle 10 searched extensively for cross-asset M1 data past 2020-05 and
   found none that closes the actual gap (2020-06 through 2023, matching
   the event calendar's own extent). See `ML-001-G7-CYCLE10-REPORT.md`.
3. **Driver symbols are broker-specific.** MT5 broker symbol names for
   SPX500/US10Y/WTI vary (`US500` vs `SPX500`, `USOIL` vs `WTICOUSD`, etc.)
   — the EA requires the operator to supply the correct name for their
   broker and will refuse to start if that symbol is unavailable.
4. **The EA uses MT5's native economic calendar** (`CalendarValueHistory`),
   not the ForexFactory-derived research calendar. These are two
   *different* data sources; live behavior depends on the completeness and
   timeliness of your broker's calendar feed, which was not itself audited
   as part of this research.
5. **No cross-asset confirmation is possible without both legs streaming
   live.** If the driver symbol's feed lags or gaps, the EA will not enter
   (fails safe) but will also silently miss legitimate opportunities.
6. **This EA has never been backtested inside the MetaTrader Strategy
   Tester.** The replay/regression evidence in this repository is a Python
   reimplementation-free harness (it imports the exact research function),
   not an MT5-native backtest. Test in a demo account before considering
   live use, regardless of what this document says about the evidence.

## 8. What would change this status

- Validation `n ≥ 30` on any combination, from either a larger pre-registered
  event pool or — the currently blocked path — extended cross-asset M1 data.
- If reached, the next step is GEN 12 (adversarial destruction), GEN 13
  (freeze for holdout), then an explicit, separately-requested GEN 14
  authorization. **None of that has happened. This document will be
  updated, and the MQL5 file's evidence-status strings changed, only if and
  when it does.**
