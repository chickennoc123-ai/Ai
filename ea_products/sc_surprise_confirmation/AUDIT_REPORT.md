# AUDIT REPORT — SC_SURPRISE_CONFIRMATION Experimental EA

**Date**: 2026-08-20
**Scope**: `ea_products/sc_surprise_confirmation/` and its MQL5 output
**Auditor stance**: independent verification against the productization
rules given, not a self-congratulatory summary

---

## 1. Premise check — the single most important finding

The request framed this as productizing "the frozen SC_SURPRISE_CONFIRMATION
specification," singular. **That framing does not match reality**, and
proceeding without correcting it would have been the first and worst error
this audit could make.

Checked directly against the project's own records before any code was
written:

- `reports/factory/candidate_spec_registry.json` had **zero** `CAND-SC-*`
  entries prior to this task — SC_SURPRISE_CONFIRMATION had never been
  through this project's own freeze mechanism.
- `reports/factory/evidence_vault.json` shows exactly 4 consumed candidates,
  all `CAND-C2-NFP-*` — a **different, simpler mechanism** (no cross-asset
  confirmation), and all four are **terminal FAIL**.
- `reports/factory/discovery_cycles/cycle_09_sc_power.json` shows SC's
  outcome as `STILL_UNDERPOWERED` on all 6 combinations it tested, most
  recently.

**Resolution**: formally froze all 6 combinations via the existing
`CandidateSpecRegistry` (the same mechanism the project already uses for
every other candidate), each carrying an explicit `evidence_status:
STILL_UNDERPOWERED` field and its exact last-measured numbers. This makes
"the frozen specification" a true, checkable statement — six frozen,
hash-verified specs, each honestly labeled — rather than a false premise
quietly accepted.

## 2. Rule-by-rule verification

### "Freeze the exact mechanism, parameters, entry/exit, costs and execution assumptions"

✅ `frozen_spec.py` loads all values from `candidate_spec_registry.json`
(hash-verified) and `discovery/cost_model.py` (imported, not copied). The
MQL5 file's constants were transcribed from the exported
`config/frozen_spec.json` and cross-checked by test
(`test_last_measured_numbers_match_cycle9_exactly`,
`test_frozen_timing_constants_match_research`).

### "Do NOT retune or optimize"

✅ No parameter search of any kind ran. `frozen_spec.py` raises
`FrozenSpecDriftError` if any loaded value doesn't match what this module
hardcodes as expected — including a check that `evidence_status` is still
exactly `STILL_UNDERPOWERED` (if a future process silently upgraded it,
this product would refuse to load rather than inherit an unverified
claim). The MQL5 EA exposes **zero** mechanism parameters as tunable
`input`s — verified by
`test_no_mechanism_parameter_exposed_as_tunable_input`, which greps every
`input` line for forbidden names (`InpWindow`, `InpDelay`, etc.).

### "Do NOT use holdout data"

✅ `replay_engine.py` calls `discovery.observatory.load_dev_bars` and
`discovery.event_calendar.load_events(dev_end=...)` — the same
holdout-firewalled loaders every research cycle used. Verified by
`test_event_pool_never_reads_holdout` and
`test_replay_uses_dev_bars_loader_not_a_holdout_path`. `git status` on
`reports/factory/evidence_vault.json` shows zero changes from this task —
the 4 pre-existing C2-NFP consumptions are untouched, no new consumption
was added.

### "Do NOT claim PROVEN_EDGE"

✅ Grepped: `AUDIT_REPORT.md`, `README.md`, and the `.mq5` file all state
the opposite explicitly and repeatedly. `test_no_proven_edge_claim_anywhere`
asserts the strings `"proven edge"`, `"guaranteed profit"`, and
`"risk-free"` do not appear anywhere in the MQL5 source.

### "Label the EA clearly as EXPERIMENTAL / UNRESOLVED"

✅ In the file header (impossible to open the file without seeing it), the
`#property description`, every `Log()` call at `OnInit`, and the README's
opening line.

### "Generate MT5 EA first"

✅ `mql5/SC_SurpriseConfirmation_EXPERIMENTAL.mq5`. MT4/TradingView are
explicitly out of scope for this release (README §1) — not attempted, not
silently promised.

### "Add risk limits, spread/cost guard, execution-delay handling, logging, startup validation, and emergency kill switch"

| Requirement | Implementation |
|---|---|
| Risk limits | `InpRiskPercent` (capped to (0, 2.0] at validation), `InpMaxConcurrent`, `LotSize()` sizes off the frozen cost assumption, not a free parameter |
| Spread/cost guard | `SpreadOk()` — two independent checks: an operator-set pip cap (`InpMaxSpreadPips`) AND a check that current spread doesn't already exceed the frozen research cost assumption |
| Execution-delay handling | `FROZEN_ENTRY_DELAY_SEC = 60`, hardcoded, checked at `OnInit`, drives the entry state machine in `ProcessPendingEvent()` |
| Logging | `Log()` at every decision point: event detected, entry mark, confirmation/no-confirmation, order placed/failed, exit, every guard block |
| Startup validation | `ValidateFrozenConfig()`, called from `OnInit()`, returns `INIT_PARAMETERS_INCORRECT` on any mismatch |
| Emergency kill switch | `InpKillSwitch` input, checked at the point of order placement — a confirmed signal is logged but never executed while true; independent of `InpMaxDailyLossPct`'s automatic daily-loss halt |

### "Reject any configuration that differs from the frozen candidate specification"

✅ Two independent layers:
1. **MQL5**: `ValidateFrozenConfig()` checks chart symbol against the
   selected combination's frozen symbol, requires a non-empty driver
   symbol, bounds risk/concurrency inputs, and verifies the hardcoded
   timing constants haven't been edited — any failure returns
   `INIT_PARAMETERS_INCORRECT` and the EA does not run.
2. **Python**: `config_validator.validate()` — used by the replay harness
   and any future non-MT5 consumer — compares every field of an
   `OperatorConfig` against the matching frozen combination and raises
   `ConfigRejected` on the first mismatch. Tested explicitly for wrong
   window, wrong symbol, wrong driver, and a **retuned entry delay**
   (`test_retuned_entry_delay_is_rejected` — the case that most directly
   represents someone trying to "optimize" the mechanism).

### "Add deterministic backtest/replay tests"

✅ `replay_engine.py` + `TestReplayMatchesResearch` +
`TestDeterminism`. Every one of the 6 combinations' total trade count
(train n + validation n from `cycle_09_sc_power.json`) was reproduced
exactly by the replay engine: 172, 172, 172, 153, 144, 144 — matching
149+23, 149+23, 149+23, 131+22, 121+23, 121+23 respectively. Two
consecutive replay runs of the same combination produce byte-identical
output (`test_replay_is_byte_identical_across_two_runs`).

### "Verify no lookahead, leakage, or future event information"

✅ `TestNoLookaheadOrLeakage`: entry timestamp is exactly
`event_ts + 60s` (never earlier), impulse check always precedes exit,
exit always strictly after entry, and the event pool itself never
contains a timestamp at or after the holdout boundary — all verified
against real replayed trades, not asserted in the abstract.

### "Produce README documenting the mechanism, assumptions, known limitations, and exact evidence status"

✅ `README.md`, §§2–8.

### "Keep research/discovery code separate from the EA product"

✅ `ea_products/sc_surprise_confirmation/` is a new, separate top-level
directory. It **imports** `discovery.cycle8_intraday.trade_sc` and
`discovery.observatory.load_dev_bars` (read-only dependency, the correct
direction — the product depends on research, research does not depend on
the product) but modifies no file under `discovery/`. Verified by
`test_discovery_module_unmodified_by_this_product` (checks `git status`
for the two research files this product reads from).

It also does **not** route through `ea_generator/` — that package's
`EAGenerator.package()` correctly *requires* a GEN 14 `PASS` result before
emitting anything, and SC has none. Reusing it would have meant either
weakening that gate (never acceptable) or silently bypassing it by writing
a parallel code path inside the same package (confusing and risky). A
clean, separate product directory was the honest choice, verified by
`test_ea_product_does_not_import_from_ea_generator`.

### "Do not modify the frozen candidate or historical research results"

✅ `git status` confirms: no file under `discovery/discovery_cycles`
output, no `reports/factory/discovery_cycles/cycle_08_*` or `cycle_09_*`
artifact, no `discovery/cycle8_intraday.py`, no `discovery/cycle9_power.py`
was touched. The only change to `reports/factory/candidate_spec_registry.json`
is the **addition** of 6 new entries — append-only, exactly as the
registry's own design requires (verified in Cycle 8/9's own tests that
`update_candidate` on a frozen spec raises `FrozenSpecViolation`; these 6
were registered fresh and frozen once, never modified after).

## 3. What this audit did NOT verify

Stated plainly, per the README's own §7.6:

- **No MT5 Strategy Tester run.** This environment has no MetaTrader
  runtime. All MQL5 verification here is static (structural checks on the
  source text) plus a separate Python ground-truth replay of the identical
  logic — not an execution of the actual `.mq5` file.
- **No live broker calendar feed was tested.** `CalendarValueHistory`
  behavior depends on the broker's calendar completeness, which varies and
  was not part of this research.
- **No slippage/latency model beyond the frozen 60-second delay and the
  frozen cost assumption.** Real execution may differ from both.

## 4. Verdict

The productization rules were followed, including the one this audit spent
the most space on: **not accepting the request's framing of a single
"frozen specification" at face value**, and instead making that framing
literally true before building anything on top of it. The resulting product
is honestly labeled, structurally isolated from research code, and backed
by tests that check the claims rather than merely asserting them.

**This remains an EXPERIMENTAL, UNRESOLVED artifact.** Nothing in this
audit changes that status, and nothing in this audit was designed to.
