"""
GEN 14 sealed-holdout access -- the ONLY door to reserved evaluation data.

This module lives OUTSIDE the discovery package on purpose. Everything in
discovery/ (GEN 7-13) is behind discovery._guards, which raises on any path
containing "holdout". This module is the single audited exception, and it
opens only when all four conditions hold:

    1. the candidate's specification is FROZEN (candidate_spec_registry)
    2. an explicit GEN 14 authorization exists (holdout_authorization)
    3. the authorization's spec hash still matches the frozen spec
    4. no terminal result has been recorded for that candidate yet

Consumption is one-way. Once a PASS/FAIL is recorded, the same candidate can
never open this door again -- not with new parameters, not after retuning.
"""

import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.observatory import Bar
from discovery.holdout_authorization import HoldoutAuthorizationGate
from discovery.candidate_spec_registry import CandidateSpecRegistry

HOLDOUT_DIR = REPO_ROOT / "data/holdout"


class HoldoutAccessDenied(RuntimeError):
    """Raised when GEN 14 preconditions for sealed-holdout access are unmet."""


def _holdout_csv(symbol: str) -> Path:
    matches = sorted(HOLDOUT_DIR.glob(f"{symbol}_H1_HOLDOUT_*.csv"))
    if not matches:
        raise HoldoutAccessDenied(f"no sealed holdout file for {symbol}")
    return matches[-1]


def open_sealed_holdout(candidate_id: str, symbol: str,
                        registry: CandidateSpecRegistry,
                        gate: HoldoutAuthorizationGate) -> List[Bar]:
    """
    Return the sealed holdout bars for `symbol`, or raise HoldoutAccessDenied.

    All four governance preconditions are checked before a byte is read.
    """
    spec = registry.get_candidate(candidate_id)
    if spec is None:
        raise HoldoutAccessDenied(f"{candidate_id} is not in the specification registry")
    if not spec.is_frozen():
        raise HoldoutAccessDenied(
            f"{candidate_id} specification is not frozen; GEN 14 may only evaluate "
            f"a candidate whose complete spec and parameters are frozen")
    if not gate.is_gen14_authorized(candidate_id):
        raise HoldoutAccessDenied(
            f"{candidate_id} has no GEN 14 authorization; reserved holdout access "
            f"requires explicit authorization")
    if gate.has_gen14_result(candidate_id):
        raise HoldoutAccessDenied(
            f"{candidate_id} already has a terminal GEN 14 result; the holdout is "
            f"consumed for this candidate and can never be reused by it")
    auth = gate.authorizations[candidate_id]
    if auth.spec_hash != spec.spec_hash:
        raise HoldoutAccessDenied(
            f"{candidate_id} spec hash does not match its authorization; the "
            f"specification changed after authorization")

    path = _holdout_csv(symbol)
    bars: List[Bar] = []
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ts = datetime.fromisoformat(row["timestamp"]).replace(tzinfo=None)
            bars.append(Bar(ts, float(row["open"]), float(row["high"]),
                            float(row["low"]), float(row["close"])))
    if not bars:
        raise HoldoutAccessDenied(f"sealed holdout {path} is empty")
    return bars
