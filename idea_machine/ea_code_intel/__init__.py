"""
EA Code Intelligence: autonomous discovery and analysis of publicly
accessible trading-system source code and research material.

Governance (non-negotiable, enforced structurally in this package):
  - Never reads/writes discovery/, the sealed holdout, the multiple-testing
    ledger, candidate_spec_registry.json, evidence_vault.json, or
    discovery/cost_model.py.
  - Never stores full copyrighted source code verbatim -- only structural
    "Strategy DNA" tags plus a short paraphrase and a citation back to the
    original source (repo/path/url).
  - Never treats popularity (stars, forks) or a source's own performance
    claims as evidence of edge. Those fields are recorded for context only
    and are explicitly excluded from any scoring formula.
  - Every hypothesis this module produces starts at provenance SOURCE_ONLY
    or DERIVED_HYPOTHESIS. It can only reach DATA_SUPPORTED, FACTORY_TESTED,
    or SURVIVOR by actually going through the existing Factory evaluation
    pipeline (discovery/*.py), the same one every other candidate uses.
  - No automatic EA productization from source code. Ever.

Modules:
  source_registry.py       -- real, tested access status for candidate sources
  github_miner.py           -- real GitHub search + fetch (repos, README, code)
  strategy_dna.py           -- deterministic mechanism-tag extraction
  novelty_engine.py         -- read-only comparison against the Factory's
                                failure_library.json / research_family_registry.json
  provenance.py             -- enforces the 5-stage evidence ladder
  hypothesis_synthesizer.py -- DNA + novelty + data-availability -> DerivedHypothesis
"""
