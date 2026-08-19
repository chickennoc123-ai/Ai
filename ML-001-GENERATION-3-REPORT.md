# ML-001 — Generation 3 Report

**Date**: August 19, 2026
**Task**: "ML-001 — STRATEGY RESEARCH FACTORY — GENERATION 3 — COMPLETE EXECUTION CONTRACT"
**Verdict**: **GENERATION_3 = COMPLETE**. Real research material was ingested, transformed into traceable, falsifiable hypotheses, and — where one legitimately qualified — into one production candidate with complete lineage. **No edge is claimed anywhere.** `EDGE_STATUS` remains `NOT_PROVEN`.

---

## 0. Baseline Verification (Phase 0)

Independently re-verified at task start, not trusted from the prompt: branch `claude/ea-factory-pro-system-bc9jaa`, commit `e804da2`, clean worktree, **850/850 tests passing** (re-run live), production population exactly `STRAT-000001 = REJECTED`, counters `generated=1, tested=1, rejected=1, hypotheses_ingested=0`. Generation 1/2 reports present; frozen/canonical economic files (`core/ml_r2/*`, `core/features/fe_r2_001.py`, `data/csv/*`) confirmed untouched throughout this task (`git diff` empty on those paths at the end).

**Network reality established up front**: only `raw.githubusercontent.com` is reachable; arxiv.org, en.wikipedia.org, and papers.ssrn.com are blocked by environment network policy (curl connection failure). This constraint was recorded honestly (§2), never worked around by fabrication.

## 1. Infrastructure Built (Phases 1-21)

Eleven new/extended modules, all additive, none weakening Generation 1/2 governance — module map and contracts in `ML-001-GENERATION-3-SPEC.md` §3 and the six detail specs. Highlights, each behaviorally tested:

- **Intake/provenance**: `access_status` axis with honest `ACCESS_FAILED`; an inaccessible source structurally cannot claim a content checksum; snapshots are content-addressed, license-gated, bit-flip-tamper-evident.
- **Claims**: `SOURCE_CLAIM` / `FACT_ESTABLISHED` (evidence-required) / `HYPOTHESIS_CANDIDATE` epistemic separation; claim text frozen — strengthening is structurally impossible.
- **Hypotheses**: eight origin types; synthesis requires ≥2 preserved parents; AI hypotheses require full separated provenance both ways (AI without provenance rejected; non-AI with provenance rejected); **`SUPPORTED` requires a linked real candidate for every origin** — AI plausibility cannot become evidence.
- **Novelty/families/DNA**: deterministic signatures; RSI 10/14/20/30 provably one family; strategy DNA fingerprint + parameter-stripped family fingerprint + decomposable similarity; no auto-rejection API.
- **Prioritization/information gain**: decomposable 8-dimension score explicitly labeled "NOT economic edge probability"; information value verified against the contract's own A-vs-B example; **feedback firewall** — `ResearchKnowledge` carries counts only, a holdout metric has no field to enter through.
- **Pre-flight/failure library**: nine named cheap checks; failures recorded (never discarded); library append-only with closed category set.
- **Cache/budgets/kill switch**: full-dependency cache keys (any change ⇒ guaranteed miss); positive-integer-only budgets with check-then-increment; persistent fail-closed kill switch with no programmatic reset, preserving all evidence on trip.

## 2. Real Research Intake (Phases 22-23) — what actually happened

| Entity | Identity | Reality |
|---|---|---|
| `SRC2-000001` | je-suis-tm/quant-trading README (OPEN_SOURCE_CODE) | **Real, fetched live**, 31,556 bytes, SHA-256 `16510c4f…`, Apache-2.0 verified by fetching the repo's own LICENSE at retrieval time; full snapshot stored under `PERMISSIVE_LICENSE`; `PROVISIONALLY_VERIFIED` (content+license verified; the author's empirical assertions remain uncorroborated source claims) |
| `SRC2-000002/3` | arxiv.org / papers.ssrn.com host attempts | **`ACCESS_FAILED`, recorded honestly** — titles state explicitly that no specific paper was identified or reviewed (so they cannot function as fabricated citations); failures also in the Failure Library |
| `SRC2-000004` | `ML-001-STRAT-000001-FAILURE-FORENSIC-REPORT.md` (INTERNAL_RESEARCH_REPORT) | Own committed work, checksum re-verifiable against the working tree, `VERIFIED` |
| `CLAIM-000001` | *"It is commonly believed that RSI above 70 is overbought and RSI below 30 is oversold."* | **Verbatim quotation** (tested: the exact bytes appear in the stored snapshot); `MARKET_LORE`, `SOURCE_CLAIM` — the source's own hedge ("rather debatable") is preserved in `supporting_context` |
| `CLAIM-000002` | MACD momentum belief (verbatim with marked ellipsis) | `HEURISTIC`, `SOURCE_CLAIM`; extracted, deliberately not formalized this generation |
| `CLAIM-000003` | 1-bar horizon already tested, no signal found (internal) | `EMPIRICAL`, `FACT_ESTABLISHED` with evidence reference to the forensic report + registry |
| `HYP-000001` | RSI-oversold reversion, 12-bar horizon, EURUSD H1 | `PUBLIC_STRATEGY_DERIVED`, formalized (9 components), quality gates passed → `ELIGIBLE` |
| `HYP-000002` | RSI reversion at the *untested* 24-bar horizon | `CROSS_SOURCE_SYNTHESIS`, both parents preserved. The internal parent contributes **coverage** knowledge only ("1-bar is already-tested territory" — the Phase 16-allowed use); no performance number chose any parameter, and the ledger entry states this distinction |
| `HYP-000003` | High-volatility-regime RSI *continuation* (negative expectancy direction) | `AI_DERIVED`, full provenance: prompt text + SHA-256 prompt identity, input source/claim ids, timestamp. The generation-model field withholds the model identifier per repository policy (no model identifiers in committed artifacts) and points to the introducing commit's session trailer — an explicit, documented redaction, not missing provenance. Status `FORMALIZED`; `UNVERIFIED` as evidence; no candidate generated from it |

Priorities were scored for all three (decomposable, recorded in `reports/factory/GENERATION3_RESEARCH_AUDIT.json`), families assigned (3 hypothesis families + 1 strategy family — see Known Limitations for the wording-sensitivity note), and `HYP-000001` passed all nine pre-flight checks against the real registered EURUSD dataset.

## 3. First Real Candidate (Phase 24)

**`STRAT-000002`** — generated from `HYP-000001` + `SEARCHSPACE-000001` (8 declared combinations, checksummed, immutable):

- Complete lineage, walked in reverse by test: `STRAT-000002 → HYP-000001 → CLAIM-000001 → SRC2-000001` (snapshot checksum re-verified at each audit).
- Immutable spec, deterministic `candidate_checksum` (spec + hypothesis + search-space lineage), strategy-DNA fingerprint recorded.
- Ledger events + multiple-testing counters updated (`total_strategies_generated = 2`).
- `param_draw` was **coherence-chosen** (holding period = the hypothesis's 12-bar horizon) and is documented as such in the ledger — not presented as a random draw.
- **State: `GENERATED`. It has never been data-validated, trained, or evaluated. It is NOT validated and NOT an edge.** The accounting field `TOTAL_CANDIDATES_SURVIVING = 1` means only "not yet rejected/failed", nothing stronger.

`STRAT-000001` remains `REJECTED`, untouched (re-verified).

## 4. Verification (Phases 25-27)

- **Adversarial**: all 20 named categories covered behaviorally (`tests/test_generation3_adversarial.py`, 26 tests + 47 infrastructure tests, including: bit-flipped snapshot detected; claim strengthening impossible; AI-pretending-verified rejected both directions; exact-duplicate pre-flight failure; budget/kill-switch stops preserving evidence; ledger deletion exposed by checksum; holdout leakage attempts rejected; result-informed re-formalization refused; source substitution refused; fabricated PASS states rejected).
- **End-to-end production verification**: `tests/test_generation3_production_research.py` (17 tests, read-only) re-derives every claim of §2-§3 from the committed files — reverse lineage, verbatim-claim-in-snapshot, checksum recomputation, zero `HOLDOUT_TESTED` history entries anywhere, accounting consistency, `SELECTION_BIAS_STATUS != PASS`.
- **Phase 27 internal audit**: performed live (source provenance, claim/hypothesis/AI lineage, search space, candidate immutability — `STRAT-000001` mutation still blocked — ledger checksum, accounting, holdout protection, kill switch, failure library); all checks passed; results embedded in the session record and reproducible via the production test file.

## 5. Tests

```
python3 -m pytest --collect-only -q  →  940 tests collected
python3 -m pytest -q                 →  exit 0, zero failures, zero errors
```

940 = 850 (verified baseline) + 90 new (47 infrastructure + 26 adversarial + 17 production verification). Two pre-existing tests were updated **with documented governance reasons in their docstrings** (Phase 19 rule): the fixed `SOURCE_TYPES` count (now: original-set-preserved subset check) and the two production-population assertions (now: counters must equal counts recomputed from the actual population — strictly stronger). No test deleted; no coverage lowered. **Disclosed**: one full-suite run showed transient `test_api.py` setup timeouts under load; the suite passed 25/25 in isolation and the full suite passed clean on re-run — a resource-contention artifact, not a regression, reported rather than hidden.

## 6. Final Status

```
GENERATION_3_STATUS            = COMPLETE

REAL_SOURCE_INGESTION          = 4 sources (1 real external fetched+checksummed, 2 honest
                                  ACCESS_FAILED records, 1 internal verified)
REAL_CLAIMS                    = 3 (2 verbatim external, 1 evidence-backed internal)
REAL_HYPOTHESES                = 3 formalized (1 ELIGIBLE, 2 FORMALIZED)
AI_HYPOTHESES                  = 1 (fully provenance-separated, UNVERIFIED, no candidate)
HYPOTHESIS_FAMILIES            = 3 (+1 strategy family)
SEARCH_SPACES                  = 1 (8 combinations, checksummed, immutable)
PRODUCTION_CANDIDATES_GENERATED = 1 (STRAT-000002, state GENERATED, full lineage, NOT validated)
PRODUCTION_CANDIDATES_REJECTED  = 1 (STRAT-000001, unchanged)

SOURCE_PROVENANCE = VERIFIED   CLAIM_LINEAGE = VERIFIED
HYPOTHESIS_LINEAGE = VERIFIED  CANDIDATE_LINEAGE = VERIFIED (reverse-walked by test)

NOVELTY_ENGINE = IMPLEMENTED   PRIORITIZATION = IMPLEMENTED   INFORMATION_GAIN = IMPLEMENTED
EARLY_REJECTION = IMPLEMENTED  FAILURE_LIBRARY = IMPLEMENTED (2 real records)
STRATEGY_DNA = IMPLEMENTED     RESEARCH_CACHE = IMPLEMENTED (governed; no entries yet)
RESEARCH_BUDGET = IMPLEMENTED  RESEARCH_KILL_SWITCH = IMPLEMENTED (production state: not tripped)
SEARCH_ACCOUNTING = CONSISTENT (recomputed = stored)

HOLDOUT_INTEGRITY = PASS (zero HOLDOUT_TESTED entries anywhere; discovery never touched holdout)
TEMPORAL_INTEGRITY = PASS (fe_r2_001.py untouched; unimplemented features fail TEMPORAL_SAFE preflight)
REPRODUCIBILITY = PASS (all checksums re-derived identically, incl. cross-process in Gen2 suite)
ADVERSARIAL_TESTING = COMPLETE (20/20 categories, behavioral)
INTEGRATION = COMPLETE (real material end-to-end, verified read-only in tests)

SELECTION_BIAS_STATUS = ACCOUNTING_ONLY (never PASS)
EDGE_STATUS = NOT_PROVEN
GENERATION_4_STATUS = NOT_STARTED

TESTS = PASS   TEST_COUNT = 940/940
```

## 7. Known Limitations

1. **External access**: only `raw.githubusercontent.com` is reachable; academic hosts (arxiv, SSRN) and Wikipedia are network-policy-blocked. The seed set is therefore narrower than intended — recorded as `ACCESS_FAILED` sources + failure-library entries, per rule 13.
2. **Family assignment is wording-sensitive**: `HYP-000001`/`HYP-000002` occupy separate families because their mechanism strings differ by a parenthetical, though conceptually related. Error direction is over-splitting (never over-merging); recorded family sizes are lower bounds on relatedness; append-only membership supports a future canonicalization merge without history rewrites.
3. **AI generation-model identifier is redacted in committed artifacts** per the repository's no-model-identifiers policy; the generating session is identified via the introducing commit's session trailer. Documented in the provenance record itself.
4. **Ledger completeness is caller discipline** (unchanged Generation 2 limitation): the ledger cannot force every future caller to log; the ingestion path demonstrates the required pattern.
5. **Research cache has no production entries yet** — the contract is implemented and tested; first real use comes when Generation 4 evaluation makes recomputation expensive.
6. `CLAIM-000002` (MACD) was extracted but not formalized — deliberate scope control, available for future work.

## 8. Open Governance Decisions

None outstanding. One tension was identified and resolved *within* the existing contract rather than silently: whether `HYP-000002`'s use of internal prior results violates rule 20 ("do not use OOS performance to generate a revised hypothesis"). Resolution: the synthesis consumes only **coverage** knowledge (which horizon was already tested — the use Phase 16 explicitly allows) and no performance number informed any parameter; the hypothesis statement, ledger entry, and this report all record the distinction. Had a performance-informed variant been wanted, it would have required a STOP-and-report; it was not needed.

## 9. What Generation 3 Did NOT Do

No economic evaluation, backtest, training run, or OOS/holdout access of any kind; no edge claim; no popularity-as-evidence; no fabricated source, citation, claim, or metadata; no Internet crawling; no Generation 4 work. `STRAT-000002` awaits Generation 4's evaluation pipeline, starting (if ever) at `DATA_VALIDATED` under the full existing governance.
