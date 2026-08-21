"""Research Space Evolution Engine (Phase 9).

Decides WHAT to research next, not HOW TO MAKE A HYPOTHESIS PASS.

Reuses, rather than duplicates, the existing Idea Machine infrastructure:
  * governance   -> idea_machine.governance.guard (the one GovernanceViolation authority)
  * epistemic    -> idea_machine.core.epistemic (UNKNOWN/KNOWN/TESTED/SURVIVED/REFUTED/
                    BLOCKED/UNDERPOWERED), plus one local addition: UNEXPLORED
  * storage      -> idea_machine.core.store.AppendOnlyStore
  * identity     -> idea_machine.core.ids (content-addressed, deterministic)
  * world model  -> idea_machine.research_memory.ResearchMemory (Phase 3)
  * novelty      -> idea_machine.ea_code_intel.novelty_engine + idea_machine.semantic_novelty (Phase 3-4)
  * real Factory -> idea_machine.real_factory_integration.RealFactoryIntegrator (Phase 8, proven live in Cycle 13)

See PHASE9_IMPLEMENTATION_PLAN.md for the full audit this package's design is based on.
"""
