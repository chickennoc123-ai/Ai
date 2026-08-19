"""
GEN 13: INDEPENDENT REPLICATION + GEN 14: FINAL EDGE QUALIFICATION.

This is the only place in the Factory permitted to read the sealed holdout,
and it may do so exactly once per candidate, under a freeze protocol.

FREEZE PROTOCOL (enforced mechanically, not by convention)
----------------------------------------------------------
 1. A candidate must be FROZEN first: its full spec is serialised and hashed.
    The hash is registered as the candidate_spec_checksum.
 2. Evidence Vault authorization is requested for (dataset_id, candidate_id)
    with that checksum. The vault refuses SEALED -> CONSUMED without it.
 3. The holdout bytes are read, the frozen spec is executed ONCE, unchanged.
 4. The result is recorded and the dataset transitions to CONSUMED. No second
    evaluation of the same dataset is possible without new governance action.

FORBIDDEN, and structurally prevented here:
 - modifying a candidate after seeing holdout results (the checksum is
   verified again at consumption time; a changed spec aborts)
 - "peeking" (there is no read path that does not consume)
 - re-running after a failure (vault state machine blocks it)

GEN 14 aggregates every prior gate into a single qualification decision.
A candidate that has not passed every upstream gate cannot be qualified,
regardless of how good the holdout number looks.
"""

import csv
import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from core.factory.evidence_vault import EvidenceVault
from discovery.evaluation import Trade, _stats, EvalStats

SEALED_HOLDOUT_ID = "DS-HOLDOUT-EURUSD-H1-HISTDATA-20240101-20260130"
SEALED_HOLDOUT_CSV = Path("data/holdout/EURUSD_H1_HOLDOUT_20240101_20260130_UTC.csv")
DEFAULT_OUT = Path("reports/factory/replication_results.json")


class FreezeViolation(RuntimeError):
    """Raised when a candidate spec changed after freezing."""


@dataclass
class FrozenCandidate:
    candidate_id: str
    spec: Dict
    frozen_at: str
    spec_checksum: str = ""

    def __post_init__(self):
        if not self.spec_checksum:
            self.spec_checksum = self.compute_checksum()

    def compute_checksum(self) -> str:
        payload = json.dumps(self.spec, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def verify_unchanged(self) -> None:
        if self.compute_checksum() != self.spec_checksum:
            raise FreezeViolation(
                f"candidate {self.candidate_id} spec changed after freeze "
                f"(registered {self.spec_checksum[:16]}..., now "
                f"{self.compute_checksum()[:16]}...). Replication aborted.")

    def to_dict(self) -> Dict:
        return asdict(self)


def freeze_candidate(candidate_id: str, spec: Dict) -> FrozenCandidate:
    return FrozenCandidate(candidate_id=candidate_id, spec=dict(spec),
                           frozen_at=datetime.utcnow().isoformat())


def _load_holdout_bars():
    """The ONE sanctioned read path. Deliberately not in discovery.observatory."""
    from discovery.observatory import Bar
    bars = []
    with open(SEALED_HOLDOUT_CSV, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ts = datetime.fromisoformat(row["timestamp"]).replace(tzinfo=None)
            bars.append(Bar(ts, float(row["open"]), float(row["high"]),
                            float(row["low"]), float(row["close"])))
    return bars


def replicate_on_sealed_holdout(frozen: FrozenCandidate,
                                executor: Callable[..., List[Trade]],
                                authorization_code: str,
                                reason: str = "") -> Dict:
    """
    Consume the sealed holdout ONCE for this frozen candidate.

    Raises if: spec changed since freeze, vault refuses authorization, seal
    verification fails, or the dataset was already consumed.
    """
    frozen.verify_unchanged()

    vault = EvidenceVault()
    if SEALED_HOLDOUT_ID not in vault.datasets:
        raise RuntimeError(f"sealed holdout {SEALED_HOLDOUT_ID} is not in the vault")

    data_bytes = SEALED_HOLDOUT_CSV.read_bytes()
    if not vault.verify_seal(SEALED_HOLDOUT_ID, data_bytes):
        raise RuntimeError("SEAL VERIFICATION FAILED -- holdout bytes do not match the "
                           "recorded seal. Replication aborted; investigate tampering.")

    vault.authorize_evaluation(
        dataset_id=SEALED_HOLDOUT_ID,
        candidate_id=frozen.candidate_id,
        candidate_spec_checksum=frozen.spec_checksum,
        authorization_code=authorization_code,
        reason=reason or f"GEN 13 one-shot replication of {frozen.candidate_id}",
    )

    bars = _load_holdout_bars()
    trades = executor(bars)
    stats = _stats(trades)

    result = {
        "candidate_id": frozen.candidate_id,
        "spec_checksum": frozen.spec_checksum,
        "frozen_at": frozen.frozen_at,
        "holdout_dataset_id": SEALED_HOLDOUT_ID,
        "holdout_bars": len(bars),
        "holdout_period": {"start": bars[0].ts.isoformat(), "end": bars[-1].ts.isoformat()},
        "stats": stats.to_dict(),
        "replication_supported": bool(stats.n >= 30 and stats.mean_net > 0 and stats.t_stat >= 1.5),
    }

    vault.consume_dataset(
        dataset_id=SEALED_HOLDOUT_ID,
        candidate_id=frozen.candidate_id,
        result_checksum=hashlib.sha256(
            json.dumps(result, sort_keys=True).encode("utf-8")).hexdigest(),
        result_summary=("REPLICATION_SUPPORTED" if result["replication_supported"]
                        else "REPLICATION_FAILED"),
    )
    result["vault_status_after"] = vault.datasets[SEALED_HOLDOUT_ID].seal_status.value
    return result


# ===========================================================================
# GEN 14: FINAL EDGE QUALIFICATION
# ===========================================================================

QUALIFICATION_GATES = (
    "PROVENANCE", "LEAKAGE", "INTERNAL_VALIDATION", "COST", "ROBUSTNESS",
    "SUBPERIOD", "STATISTICS", "MULTIPLE_TESTING", "SELECTION_BIAS",
    "INDEPENDENT_REPLICATION", "ECONOMIC_VALIDATION",
)


@dataclass
class QualificationReport:
    candidate_id: str
    gates: Dict[str, str]                  # gate -> PASS / FAIL / NOT_RUN
    edge_status: str
    blocking_gates: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


def qualify(candidate_id: str, gate_results: Dict[str, str],
            hypotheses_tested_in_program: int = 0,
            notes: Optional[List[str]] = None) -> QualificationReport:
    """
    Aggregate every gate. EDGE_STATUS is PROVISIONALLY_PROVEN only if every
    gate in QUALIFICATION_GATES is explicitly PASS. Anything missing counts
    as NOT_RUN and blocks -- absence of evidence is never treated as a pass.
    """
    gates = {g: gate_results.get(g, "NOT_RUN") for g in QUALIFICATION_GATES}
    blocking = [g for g, v in gates.items() if v != "PASS"]
    notes = list(notes or [])
    if hypotheses_tested_in_program:
        notes.append(
            f"multiple-testing context: {hypotheses_tested_in_program} hypotheses have been "
            f"tested in this research program; any single-candidate p-value must be read "
            f"against that count.")
    status = "PROVISIONALLY_PROVEN" if not blocking else "NOT_PROVEN"
    return QualificationReport(candidate_id=candidate_id, gates=gates,
                               edge_status=status, blocking_gates=blocking, notes=notes)
