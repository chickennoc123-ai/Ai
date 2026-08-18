# ML-001 — Holdout / WFA State-Machine Governance Decision

**Date**: August 18, 2026 (original analysis); **resolved** August 18, 2026 (same day, follow-up task).
**Status**: `SPECIFICATION_DECISION_REQUIRED = FALSE` — **RESOLVED**. §1-§6 below are the original analysis, preserved verbatim as the historical record of the reasoning (per this project's discipline of never deleting prior evidence): they correctly found that no document *in this repository* granted authority to pick between Options A/B/C unilaterally, and none did. What changed is that the product owner — the only party who *does* hold that authority — explicitly directed the resolution in a follow-up task ("ML-001 — CLOSE STRATEGY FACTORY GOVERNANCE BEFORE STRAT-000002"), which is itself now the authorizing instruction. See §7 for the resolution and what was actually implemented.

---

## §0. Resolution (read this first)

**Option A/C's shape was adopted**: holdout is the final gate, immediately preceded by an explicit `CANDIDATE_FREEZE` (`FROZEN`) checkpoint, itself preceded by an explicit `MULTIPLE_TESTING_REVIEWED` accounting gate. The new, formalized forward spine (`core/factory/state_machine.py`):

```
GENERATED → DATA_VALIDATED → TRAINED → OOS_TESTED → WFA_TESTED → ROBUSTNESS_TESTED
→ COST_TESTED → STATISTICALLY_VALIDATED → MULTIPLE_TESTING_REVIEWED → FROZEN
→ HOLDOUT_TESTED → EVG_REVIEW → RESEARCH_CANDIDATE → PAPER_VALIDATION → LIVE_CANDIDATE
```

This is Option C in spirit — holdout last, with the naming/ordering ambiguity from §1 additionally closed by making `MULTIPLE_TESTING_REVIEWED` (§7's accounting) and `FROZEN` (§4/§5's immutability checkpoint) explicit, separately-gated states rather than folding that discipline into documentation alone. Full specification: `ML-001-STRATEGY-FACTORY-SPEC.md` §2-§9. Implementation details:

- `core/factory/state_machine.py`: `_FORWARD_SPINE` reordered; `MULTIPLE_TESTING_REVIEWED` added as a new state.
- `core/factory/registry.py`: `_FROZEN_OR_LATER` now starts at `OOS_TESTED` (spec-swap immutability, unchanged in spirit from before — it always included `OOS_TESTED`) and additionally covers `MULTIPLE_TESTING_REVIEWED`; `transition()` raises `MultipleTestingAccountingRequiredError` if a candidate attempts `MULTIPLE_TESTING_REVIEWED` before `set_search_space()` has ever been called on that registry.
- `STRAT-000001` is unaffected: its real history (`GENERATED → DATA_VALIDATED → TRAINED → REJECTED`) uses only states that kept their name and did not move relative to each other, so it remains 100% legal and unmodified under the new spine — no migration was needed or performed.
- Tests: `tests/test_factory_state_machine.py`, `tests/test_factory_registry.py`, `tests/test_factory_holdout_governance.py` updated/extended; new `tests/test_factory_hypothesis.py`, `tests/test_factory_provenance_metadata.py` added. Full suite green (see the consolidated final report for the current count).

**Why C over plain A**: §3's comparison already found C strictly more defensive than A at a small additional cost (the extra rename/clarification work). Given the resolution was going to require a code change either way (A alone was never going to be free), paying that small additional cost to also close the interpretive ambiguity was judged worth it — consistent with, not contradicting, the original analysis.

---

## 1. The conflict, precisely stated

`core/factory/state_machine.py::_FORWARD_SPINE` currently orders:

```
... TRAINED → FROZEN → HOLDOUT_TESTED → OOS_TESTED → WFA_TESTED → ROBUSTNESS_TESTED → COST_TESTED → STATISTICALLY_VALIDATED → EVG_REVIEW → ...
```

i.e. the state machine's declared forward path opens `PURE_HOLDOUT` (`HOLDOUT_TESTED`) *before* out-of-sample/walk-forward evaluation (`OOS_TESTED`/`WFA_TESTED`), robustness testing, cost stress, and statistical validation.

This is in tension with a principle this project has independently, repeatedly established as load-bearing, prior to and independent of this state machine's authorship:

- `ML-001-R2-CLEAN-REBUILD-SPEC.md` §8, requirement 4: *"PURE_HOLDOUT is opened **exactly once**, after the model, features, and hyperparameters are fully frozen."*
- `core/provenance_enforcement.py`'s `DataState.PURE_HOLDOUT` access matrix: the only allowed action is `FINAL_EVALUATION`, and `ProvenanceEnforcer` tracks `holdout_accessed` to enforce the "exactly once" rule at runtime.
- This session's own leakage audit (`ML-001-R2-REAL-DATA-LEAKAGE-PROVENANCE-AUDIT.md` §6–7) and `STRAT-000001`'s actual rejection path (`TRAINED → REJECTED`, deliberately bypassing `HOLDOUT_TESTED` so that a real, unfavorable WFA result could be recorded without ever opening holdout).

The spec text says holdout must be opened *after freezing*, but does not explicitly say whether it must also be opened *after* WFA/robustness/cost/statistics, or *before* them. The state machine's spine answers that question one specific way (holdout first) without any accompanying rationale in the code, tests, or commit history explaining why.

---

## 2. Search for authority to resolve this unilaterally

Both `core/factory/state_machine.py` and `core/factory/candidate.py`/`registry.py` cite "the roadmap Section 6/16/19/20" in their docstrings as the source of this ordering and the broader Factory design. That document was searched for directly:

```
grep -rn "roadmap" *.md   →  only informal references inside OTHER reports
                              (ML-001-REAL-MARKET-GAP-SEMANTICS-AUDIT.md,
                              ML-001-PHASE-1A-TEMPORAL-SEMANTICS-CONTRACT.md),
                              never the roadmap document itself
```

**No file named or resembling "ML-001 Strategy Factory roadmap" exists anywhere in this repository.** The docstrings' section citations (6, 10, 16, 19, 20) cannot be independently checked against source text — they may describe a document that existed in a prior session's working context but was never committed, or that exists only as an oral/prompt-level specification passed to the concurrent session that authored `core/factory/*`. Either way, **this repository does not currently contain authoritative text that specifies the intended HOLDOUT_TESTED/WFA_TESTED ordering**, only the state machine's own (uncommented, unjustified-in-code) choice of ordering.

`ML-001-R2-CLEAN-REBUILD-SPEC.md` — the one document that *is* present and *is* authoritative for ML-001-R2 — addresses holdout timing (§8) and WFA timing (§9) in separate sections without cross-referencing each other's relative order, and does not mention a candidate state machine at all (the Factory is a later, separate piece of infrastructure layered on top of the R2 spec, not described by it).

**Conclusion: no in-repository specification grants authority to resolve this conflict by picking an option.** Per the task's explicit instruction ("do not invent authority... otherwise set `SPECIFICATION_DECISION_REQUIRED = TRUE`"), this document stops short of a recommendation and instead lays out the option space precisely enough for whoever does have that authority to decide quickly.

---

## 3. Options

### Option A — Holdout last (after robustness/cost/stats/freeze)

`... FROZEN → OOS_TESTED → WFA_TESTED → ROBUSTNESS_TESTED → COST_TESTED → STATISTICALLY_VALIDATED → HOLDOUT_TESTED → EVG_REVIEW → ...`

Holdout becomes the final gate before EVG review — the "one last check" a candidate faces only after every cheaper, reusable-data test has already passed.

| Dimension | Assessment |
|---|---|
| Leakage risk | Lowest. Holdout is accessed only once, at the very end, by construction. |
| Selection risk | Lowest. No opportunity exists to let a holdout result influence any earlier decision, because no earlier decision has holdout available to it. |
| Holdout contamination risk | Lowest. Matches this project's own repeatedly-stated discipline (spec §8.4) most literally. |
| Early-rejection ability | Worst of the three options. A candidate that would obviously fail must still pass through every intermediate gate (WFA, robustness, cost, stats) before the state machine lets it reach holdout — expensive if those gates are costly to run, though `STRAT-000001` shows a candidate can still be rejected *without* reaching holdout via the always-legal `TRAINED → REJECTED` bypass, so "early rejection" is already possible outside the holdout gate specifically. |
| WFA compatibility | Natural — WFA is explicitly a VALIDATION-period activity (spec §9), and holdout is defined as strictly later in time (spec §8) than VALIDATION; running WFA before holdout matches the data's own temporal order, not just the state machine's. |
| Immutable-version compatibility | Fully compatible — `FROZEN` already occurs before any of these states, so the "spec is immutable from FROZEN onward" guarantee (`registry.py::_FROZEN_OR_LATER`) is unaffected regardless of internal ordering after `FROZEN`. |
| Multiple-testing compatibility | Best. Every non-holdout gate can filter out weak candidates using only DEVELOPMENT/VALIDATION data, so by the time holdout is finally opened, the "family" of hypotheses that could have influenced the holdout-tested candidate is smallest and best-documented. |
| EVG consequences | Cleanest possible signal to feed EVG — holdout result reflects a candidate that has already survived every reusable-data check on its own merits. |
| Registry consequences | None — `_FROZEN_OR_LATER` set already includes both `HOLDOUT_TESTED` and `WFA_TESTED`/etc., so spec-immutability enforcement is identical under any reordering. |

### Option B — Holdout immediately after training, before WFA (current state machine's ordering)

`... TRAINED → FROZEN → HOLDOUT_TESTED → OOS_TESTED → WFA_TESTED → ...` (status quo)

| Dimension | Assessment |
|---|---|
| Leakage risk | Higher than A. If any test between `HOLDOUT_TESTED` and `EVG_REVIEW` (WFA, robustness, cost, stats) were ever allowed to trigger a spec change or a "try again" loop back to an earlier state, holdout information would already be in the researcher's head — even without formally reopening the state, the human/process could be influenced. The state machine's own no-backward-transition rule mitigates but does not eliminate this (a human reading a bad holdout result could still informally decide to abandon the candidate and start a *new* one with tweaked features, which the registry cannot detect as holdout-influenced). |
| Selection risk | Higher than A, for the same reason — a candidate's WFA/robustness/cost/stats results occur *after* the researcher already knows the holdout outcome, undermining the claim that those later gates are "independent" evidence. |
| Holdout contamination risk | Highest of the three. This is the crux of the conflict identified in §1 — it appears to directly contradict spec §8.4's "opened exactly once, after model/features/hyperparameters are frozen" if that clause is read as also implying "opened only once every other gate has been passed," which is the most natural reading given how this project has used holdout everywhere else. |
| Early-rejection ability | Best of the three — a hopeless candidate is caught immediately after training, before spending compute on WFA/robustness/cost/stats. |
| WFA compatibility | Awkward — WFA windows are chronologically confined to VALIDATION (spec §9), which by construction all precede PURE_HOLDOUT in time. Running `HOLDOUT_TESTED` before `WFA_TESTED` in *state-machine order* while the underlying *data* used by WFA is chronologically earlier than the data used by holdout is not a data-integrity problem (no future leakage — holdout data is never used to train the WFA windows), but it is a conceptual mismatch: the state name suggests "already evaluated on the final, hardest test" before the candidate has even seen the standard OOS/WFA gauntlet. |
| Immutable-version compatibility | Compatible (same as A — `FROZEN` already precedes both). |
| Multiple-testing compatibility | Weakest. If a researcher can see a holdout result before running WFA/robustness/cost, and the process allows abandoning the candidate afterward (via `derive_new_version` or a fresh `register()`), the holdout has effectively been used for selection even though no single candidate's state was ever illegally mutated — the risk lives at the human/process level, not something this state machine alone can prevent. |
| EVG consequences | Weakest. An EVG reviewer cannot be fully confident the WFA/robustness/cost/stats evidence for a `HOLDOUT_TESTED`-then-later-gated candidate was generated in true ignorance of the holdout outcome. |
| Registry consequences | None structurally different from A — `_FROZEN_OR_LATER` doesn't care about the internal order past `FROZEN`. |

**Note**: this is the option the current code implements, but "already implemented" is not evidence of authorization — nothing in the commit history or docstrings explains *why* this order was chosen, and it was very plausibly a modeling oversight by whichever process wrote the spine (a natural-seeming but not obviously deliberate placement of `HOLDOUT_TESTED` right after `FROZEN` since both are conceptually "the model is now locked").

### Option C — Separate "validation WFA" from "final holdout"

Introduce a semantic distinction the state names currently elide: `WFA_TESTED` (and `OOS_TESTED`) always mean "evaluated on VALIDATION-period data via walk-forward" — a *repeatable*, non-holdout-consuming activity that can inform iteration — while `HOLDOUT_TESTED` is reserved, unambiguously, for the literal single PURE_HOLDOUT access, and the spine is reordered so `HOLDOUT_TESTED` is last (structurally identical to Option A), but additionally the state machine or its documentation is amended to make this semantic distinction explicit (e.g. a renamed state or an added docstring clarifying "WFA/OOS operate on VALIDATION, never on PURE_HOLDOUT, by construction").

| Dimension | Assessment |
|---|---|
| Leakage risk | Same as A (holdout last) — this option **is** A, with the addition of clearer naming/documentation to prevent the ambiguity in §1 from recurring. |
| Selection risk | Same as A. |
| Holdout contamination risk | Same as A — lowest. |
| Early-rejection ability | Same as A. |
| WFA compatibility | Best of the three — this option is the only one that also fixes the *naming* mismatch, not just the ordering, making it explicit in the state machine itself (not just in a separate spec document) that WFA/OOS are VALIDATION-period, repeatable activities distinct from the one-time holdout event. This directly matches what `STRAT-000001`'s own actual evidence already looks like: 65 WFA windows, all within DEVELOPMENT∪VALIDATION, zero holdout access — Option C would make the state machine describe that shape accurately by name, not just by convention. |
| Immutable-version compatibility | Same as A. |
| Multiple-testing compatibility | Same as A (best), with the added benefit that a `search_history` audit reading the state name `WFA_TESTED` can trust it never implies holdout access, closing the ambiguity a future auditor of this registry could otherwise hit. |
| EVG consequences | Same as A, plus: an EVG reviewer reading candidate history no longer has to cross-reference an external document to know whether `WFA_TESTED` risked touching holdout. |
| Registry consequences | Requires no change to `_FROZEN_OR_LATER` or any registry logic — purely a state-machine/documentation change (rename or clarify, reorder). |

---

## 4. Comparative summary

| | A (holdout last) | B (holdout first, current) | C (holdout last + renamed/clarified) |
|---|---|---|---|
| Matches spec §8.4's most natural reading | Yes | Ambiguous/arguably no | Yes |
| Matches `STRAT-000001`'s actual, already-taken path | Yes (TRAINED→REJECTED bypassed holdout entirely, consistent with "holdout is a late, still-unreached gate") | Partially (bypass still legal, but the *intended* path implies holdout would have come next) | Yes |
| Requires code change | Yes (reorder `_FORWARD_SPINE`) | No | Yes (reorder + rename/document) |
| Requires new authority to adopt | Yes | No (status quo) | Yes |
| Eliminates the naming ambiguity in §1 | No (order fixed, meaning of "WFA_TESTED never touches holdout" still implicit) | No | Yes |

Options A and C carry the same structural risk profile; C is strictly more defensive because it also removes the interpretive ambiguity, at the cost of a slightly larger change (rename/clarify, not just reorder).

---

## 5. What this document deliberately does not do

- Does not edit `core/factory/state_machine.py::_FORWARD_SPINE`.
- Does not pick A, B, or C.
- Does not add a fourth, "obviously correct" option framed to look pre-selected.
- Does not claim `STRAT-000001`'s rejection is invalidated by this ambiguity — it isn't: `TRAINED → REJECTED` is legal under **all three** options above (none of them touch the `X → REJECTED` transitions, which remain available from every non-terminal, non-`LIVE_CANDIDATE` state per `_ALLOWED_TRANSITIONS`), so the rejection stands regardless of how this question is eventually resolved.

## 6. Interim operating rule — superseded by §0

*(Historical: this section originally described a process-only stopgap, "behave as if Option A/C were already adopted, even though the state machine does not yet enforce that ordering," while the decision remained open. That stopgap is no longer interim — §0 records that the state machine itself now enforces this ordering directly, so this section is preserved for its historical reasoning only, not as current operating guidance.)*

Until a decision is made, any future candidate in this Factory should follow the same discipline `STRAT-000001` already followed **de facto**: never transition through `HOLDOUT_TESTED` until WFA/robustness/cost/statistical validation are complete and the candidate looks like a genuine EVG candidate on VALIDATION-period evidence alone — i.e., behave as if Option A/C were already adopted, even though the state machine does not yet enforce that ordering. This is a process discipline, not a code change, and does not require touching `state_machine.py`.

```
SPECIFICATION_DECISION_REQUIRED = FALSE   (resolved -- see §0)
OPTIONS_PRESENTED = [A, B, C]
OPTION_ADOPTED = C (holdout last + explicit MULTIPLE_TESTING_REVIEWED/FROZEN gates)
AUTHORIZED_BY = explicit product-owner direction ("ML-001 — CLOSE STRATEGY FACTORY
                 GOVERNANCE BEFORE STRAT-000002" task), not invented by this document
STATE_MACHINE_MODIFIED = TRUE (core/factory/state_machine.py, core/factory/registry.py)
CANONICAL_SPEC = ML-001-STRATEGY-FACTORY-SPEC.md §2-§9
STRAT-000001_AFFECTED = FALSE (its history uses only unchanged-position states; no
                         migration needed)
```
