"""
Holdout firewall for the discovery layer.

The sealed independent holdout lives under data/holdout/. Nothing in
GEN 7-11 may ever read it. guard_path() is called by every data loader in
this package; it raises before a single byte is read.
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
