"""
Holdout firewall for the discovery layer (OGD-4 Amendment 3).

Governance rule: GEN 7-13 (discovery/evaluation/adversarial) may access ONLY
development data. The sealed holdout (data/holdout/) is invisible to these layers.

  GEN 7-13: Development data only (holdout firewall via guard_path)
  GEN 14:   Exclusive authorized access (via holdout_authorization gate)

guard_path() is called by every data loader; it raises HoldoutFirewallViolation
before a single byte of holdout data is read by any layer before GEN 14.

Once GEN 14 evaluation completes, result is terminal (PASS/FAIL immutable).
Failed candidates cannot be re-tuned and retested against same holdout
(enforced via candidate_spec_registry freeze + holdout_authorization gates).
"""

from pathlib import Path


class HoldoutFirewallViolation(RuntimeError):
    """Raised when discovery-layer code attempts to touch sealed holdout data."""


FORBIDDEN_PARTS = ("holdout",)


def guard_path(path) -> Path:
    """Return the path if it is safe for research use; raise otherwise."""
    p = Path(path).resolve()
    for part in p.parts:
        if any(bad in part.lower() for bad in FORBIDDEN_PARTS):
            raise HoldoutFirewallViolation(
                f"discovery layer attempted to read {p} -- paths containing "
                f"{FORBIDDEN_PARTS} are sealed evaluation data and are "
                f"invisible to hypothesis/candidate generation (OGD-4)."
            )
    return p
