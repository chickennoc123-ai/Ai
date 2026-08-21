# Phase 9 (second pass): Self-Critique, Written Before the Live Cycle

Required by spec item 23. Answered against the actual built system, and
against the two real bugs already found and fixed while building it (see
`PHASE9_ADAPTIVE_SEARCH_REPORT.md` for the full account) — not against
design intent.

---

**Phase 9 có thể bị bias ở đâu?**

Two concrete bias risks, both checked:

1. *Seeding bias.* `SearchSpaceRegistry` seeds its UNEXPLORED catalog from
   `KNOWN_UNEXPLORED_DRIVERS` and `RECOMBINED_MECHANISMS` — lists this
   session itself curated across Cycles 8/13/14. Any driver I never thought
   to check (there is real Oanda M1 data for dozens of instruments this
   project has never touched) is invisible to the registry, not because it
   was rejected but because nobody looked. This is disclosed, not hidden:
   the `is_exhausted()` check only ever reports genuine exhaustion of the
   *known* catalog, never claims the whole real search space is covered.
2. *Economic-rationale bias.* `search_economic_rationale.BASE_DIR_TABLE`
   only contains 17 pairs this project has actually reasoned through. A
   proposal outside that table is skipped with `no_established_rationale`
   rather than assigned an invented direction — the honest, if narrower,
   choice.

**Exploration có thực sự mới hay chỉ là parameter variation?**

Checked structurally, not just asserted: `is_parameter_only_change()` exists
specifically to make this distinction machine-checkable, and
`ExplorationEngine.propose()` only draws from `registry.unexplored_regions()`
— which by construction never contains a region that only differs from a
tested one by a window/threshold value (windows are not a registry
dimension; they are fixed at 60m for the live cycle and never vary within a
proposal). Verified live in the CLI: `search-plan --slots 10` proposed 3
EXPLORE regions, all with a genuinely new `macro_driver` value never used in
any prior cycle.

**Search controller có đang tối ưu survivor rate không?**

No optimization target in this codebase reads a survivor count.
`AdaptiveSearchController._score()` never receives a train-t, a P&L, or a
verdict — every component is computed from evidence *status* (UNEXPLORED /
UNDERPOWERED / TESTED / REFUTED) and data availability, before any Factory
call happens. `SearchDecisionScore` has no field derivable from an
evaluation outcome.

**Diversity có thực chất không?**

Verified, and this is where the most serious bug in this pass was found: the
diversity cap groups by `(mechanism, instrument)`. Before fixing it, I
confirmed the cap is not merely decorative by constructing a
30-slot cycle and checking the actual family distribution in `selected`
(`test_duplicated_family_explosion_is_capped`) — it genuinely drops excess
proposals from an over-represented family rather than silently allowing
100% concentration.

**Có dimension nào đang bị bỏ quên?**

Yes, honestly: `event_surprise`, `market_regime`, `session`,
`volatility_state`, and `interaction_effects` (spec item 1's own list) are
NOT populated as live registry dimensions in this pass — only `instrument`,
`macro_driver`, and `mechanism` are. The registry's open dict model supports
adding them (`register_region()` takes arbitrary keys), but no engine in
this pass actually proposes a region keyed on session or volatility regime.
This is a real, disclosed gap, not a silent omission — Phase 9 (first pass,
`idea_machine/research_space/`) partially covers this via its `MARKET_SESSIONS`
and `REGIME_DIMENSIONS` catalogs, but this second-pass registry does not yet
cross those into its region model. Left for a future pass rather than faked.

**Có dữ liệu nào đang vô tình điều khiển search?**

Found and fixed one real instance of exactly this, before this document was
written: `SearchSpace.triple_status()` was letting a single, mechanism-
unspecified, driver-less REFUTED hypothesis from Cycle 11 (`HYP-IM-0003`)
silently veto EVERY future mechanism proposal on EURUSD that also happened
to specify no driver — including a brand-new recombined mechanism that had
never been tested. Fixed by refusing to apply `CycleHypothesisRecord`
evidence (which carries no mechanism field) to any mechanism-specific query;
only `CandidateRecord` evidence (which does carry a mechanism field) may now
gate a named mechanism. Regression-tested
(`test_exploitation_refutation_does_not_leak_to_an_unrelated_new_mechanism`).

**Có nguy cơ circular learning giữa Factory và Idea Machine không?**

Structurally limited: the controller never reads a Factory verdict to change
its OWN scoring formula or floor — `min_exploration_fraction` and
`MAX_SAME_FAMILY_PER_CYCLE` are fixed constants, not adjusted by outcome. The
only feedback path from Factory results back into future search is via
`ResearchMemory`/`SearchSpaceRegistry` re-reading real, already-recorded
evidence on the NEXT construction (a new region status), which is the
intended, one-way "evidence updates the map" loop, not a self-reinforcing
"reward the search policy for finding survivors" loop. No survivor-count or
win-rate feeds back into the allocator.

---

## Fixed before this cycle ran

1. `SearchSpaceRegistry.is_exhausted()` was trivially `True` immediately
   after construction (only tested triples were seeded, so coverage was
   always 100%). Fixed by also seeding the real, confirmed-present-but-never-
   tested catalog.
2. Free-text mechanism descriptions from `candidate_spec_registry.json` were
   used as raw region-dimension values, which would have minted a different
   region id for every trivial wording difference. Fixed with
   `_clean_mechanism_code()`.
3. The mechanism-leak bug described above (`triple_status` cross-contaminating
   unrelated mechanism proposals via driver-less hypotheses).

All three are disclosed in `PHASE9_ADAPTIVE_SEARCH_REPORT.md`, not omitted.
