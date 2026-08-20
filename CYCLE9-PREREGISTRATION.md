# GEN 7 CYCLE 9 — PRE-REGISTRATION (frozen before any evaluation runs)

**Purpose**: resolve `VALIDATION_UNDERPOWERED` on `SC_SURPRISE_CONFIRMATION`
(FAIL-000042). Not a new strategy — the identical mechanism from Cycle 8,
tested once against a larger, already-verified event pool.

Everything below is fixed **before** `discovery/cycle9_power.py` is run. Any
later change to any line here is a violation of this cycle's own rules and
must be reported as such, not silently made.

---

## Self-critique on the pool-expansion choice

Two ways to grow n were available: extend the calendar's usable year range,
or add more event types. **Year range is already maxed out**: the FX/driver
M1 data (Oanda, via `FutureSharks/financial-data`) covers 2005–2020, but the
event calendar itself only starts 2010, and the M1 data's own 2020 coverage
ends 2020-05 (a real data limit, not a code restriction). NFP and CPI y/y in
Cycle 8 already used the full 2010–2020-05 overlap. There is no room to
extend on that axis without a **new acquisition**, which was not attempted
this cycle because a second lever was available first (below) and using it
avoids introducing yet another unverified source when a verified one
already covers the need.

**Event-type expansion, using already-verified data**: the calendar file
(`data/events/raw/forexfactory_2010_2023.csv`) passed all 7 EVENT-CONTRACT-V1
gates and a dual-signal timezone verification in Cycle 6, for its *entire*
contents — not only the NFP rows Cycle 5–8 happened to use. Using more
already-verified rows is not a new acquisition; it is using more of what was
already acquired and audited. This is stated explicitly so it cannot later be
mistaken for skipping the "acquire" step.

**Risk accepted, stated plainly**: pooling NFP + CPI + ADP into one test
dilutes a real but event-type-specific signal if only one type actually
carries it. The alternative — testing each type separately — simply
reproduces Cycle 6–8's per-type underpowered problem. Cycle 9 pools by
design, per the task's explicit instruction to grow the pool feeding the
*same* mechanism, not to run three smaller separate tests.

---

## 1. Event types (frozen)

| Event | In-range count (2010–2020-05) | With actual+forecast | Included? |
|---|---|---|---|
| Non-Farm Employment Change | 129 | 129 | **Yes** |
| CPI y/y | 125 | 125 | **Yes** |
| ADP Non-Farm Employment Change | 132 | 132 | **Yes** — genuinely independent release, 1-3 days before NFP, not simultaneous with any other included type (checked: median 2-day gap) |
| Federal Funds Rate | 84 | 34 | **No** — verified before this pre-registration: **zero** of the 34 rows have `actual != forecast` in this window. The Fed did not surprise on the headline rate 2010–2020-05. Contributes structurally zero trades; excluding it is a power finding, not an arbitrary drop (same discipline as Cycle 7's Federal-Funds-Rate exclusion). |
| FOMC Statement | — | 0 | **No** — no actual/forecast field (prose, not a print); unchanged from every prior cycle's finding. |

**Frozen pool: 386 events**, all USD, HIGH impact, all currently in
`data/events/raw/forexfactory_2010_2023.csv` (no file changes needed).

## 2. Symbols / assets (unchanged from Cycle 8)

EURUSD, GBPUSD, XAUUSD — real Oanda M1 (`FutureSharks/financial-data`), all
6 windows. USDJPY, USDCHF — H1 dev data only, `[60, 120, 240]` minutes;
5/15/30 remain `BLOCKED_NO_INTRADAY_DATA` (re-verified: no new intraday
source was found or searched for this cycle, since nothing about the
USDJPY/USDCHF data situation changed since Cycle 8's confirmed dead end).

## 3. Reaction windows (unchanged, identical object)

`[5, 15, 30, 60, 120, 240]` minutes (M1 symbols), `[60, 120, 240]` (H1-only).

## 4. Surprise definition (unchanged)

`sign(actual - forecast)`, direction mapped through `SURPRISE_FX_DIR`
(quote-convention-aware, identical to Cycle 6/8): EURUSD/GBPUSD/XAUUSD = −1
per positive-USD-surprise, USDJPY/USDCHF = +1.

## 5. Driver-confirmation rule (unchanged)

Same six `(symbol, driver)` pairings as Cycle 8: `EURUSD/US10Y`,
`GBPUSD/US10Y`, `XAUUSD/SPX500`, `XAUUSD/WTICO`, `USDJPY/SPX500`,
`USDCHF/SPX500`. A trade fires only when the driver's own 5-minute impulse
move agrees in sign with the surprise-implied FX direction — identical
`trade_sc()` logic, reused unmodified from `discovery/cycle8_intraday.py`.

## 6. Costs + execution delay (unchanged)

Frozen per-symbol `roundtrip_cost()` (`discovery/cost_model.py`, untouched
since Cycle 3). 60-second entry delay, identical to Cycle 8.

## 7. Gates (unchanged)

`n ≥ 30`, `gross/cost ≥ 2.0`, train `mean_net > 0` and `t ≥ 2.0`, validation
`mean_net > 0` and `t ≥ 1.5`. Identical `gate()` function, imported not
reimplemented.

## 8. Multiple testing (mandatory, computed after run, not before)

Current cumulative ledger before this cycle: **86 hypotheses, 1,522
parameter evaluations, 5 survivors** (append-only, unchanged by this
document). This cycle adds exactly the SC-only evaluations it runs — no
DC/DR/RI re-run, since only SC is being re-tested per the task's explicit
scope. Bonferroni bar computed post-run against the resulting M.

## 9. Decision rule (frozen, not adjustable after seeing results)

- Any `(symbol, driver, window)` combination reaching `DISCOVERY_SURVIVOR` →
  freeze that specific candidate → GEN 12 → GEN 13 → request GEN 14
  authorization (not executed automatically; requires explicit sign-off).
- If every combination fails on train/validation significance (not on `n`)
  → `SC_SURPRISE_CONFIRMATION` is **REFUTED**, recorded with a
  mechanism-specific failure record superseding FAIL-000042.
- If any combination still shows `VALIDATION_UNDERPOWERED` after this
  expansion → **STOP**, report the exact remaining shortfall (symbol,
  window, n achieved vs. n required), and do not attempt a third
  expansion inside this cycle.

**No combination will be cherry-picked for a second look. The result, once
computed, is read once and reported as-is.**
