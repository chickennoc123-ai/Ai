"""
SC_SURPRISE_CONFIRMATION -- experimental EA product.

This package is a PRODUCT, not a research module. It contains no discovery
logic and must never be imported by anything under discovery/. Its job is to
package the exact, already-frozen SC_SURPRISE_CONFIRMATION mechanism as
deployable software, and nothing more:

  - It does not run new evaluations.
  - It does not touch the sealed holdout.
  - It does not change the mechanism's parameters.
  - It does not upgrade the mechanism's evidence status. Every combination
    packaged here is frozen at STILL_UNDERPOWERED (see
    reports/factory/candidate_spec_registry.json, CAND-SC-* entries).

EVIDENCE STATUS: EXPERIMENTAL / UNRESOLVED. No combination has cleared
internal validation. None has been authorized for GEN 14. None has been
evaluated against the sealed holdout. This is not a proven edge.
"""
