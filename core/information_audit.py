"""Information Audit (IA-001): Detect future information leakage in hypotheses.

Audits feature and target definitions to ensure:
1. No feature depends on information from after the decision point.
2. Target-only features (future-looking) are correctly classified.
3. Provenance of all dependencies can be verified.

Verdicts:
- PASS: All dependencies are safe; no future info leakage proven.
- FAIL: Future dependency detected; audit failed.
- UNKNOWN: Provenance cannot be verified; audit blocked.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Set

import pandas as pd

from core.temporal_contract import TemporalContract, TemporalContractBuilder
from utils.exceptions import ValidationFailure
from utils.helpers import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)


class AuditVerdictType(str, Enum):
    """Audit verdict outcome."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class AuditBlockedError(ValidationFailure):
    """Raised when audit cannot proceed due to unverifiable dependencies."""

    pass


@dataclass(frozen=True)
class FeatureAudit:
    """Audit result for a single feature."""

    feature_name: str
    decision_time: int
    max_information_time: int
    is_future_dependent: bool
    has_unverifiable: bool
    verdict: Literal["PASS", "FAIL", "UNKNOWN"]
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return dictionary representation."""
        return asdict(self)


@dataclass(frozen=True)
class TargetAudit:
    """Audit result for the target variable."""

    target_name: str
    uses_future_information: bool
    verdict: Literal["PASS", "FAIL"]
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return dictionary representation."""
        return asdict(self)


@dataclass(frozen=True)
class InformationAuditResult:
    """Immutable result of an information audit."""

    hypothesis_id: str
    dataset_version: str
    methodology_version: str = "IA-001-v1.0"
    contract_hash: str = ""
    audit_timestamp: datetime = field(default_factory=utcnow)
    auditor: str = "deterministic_information_audit"
    dependency_graph_hash: str = ""
    execution_semantics: Dict[str, Any] = field(default_factory=dict)
    feature_audits: List[FeatureAudit] = field(default_factory=list)
    target_audit: Optional[TargetAudit] = None
    dependency_checks: List[Dict[str, Any]] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)
    verdict: Literal["PASS", "FAIL", "UNKNOWN"] = "UNKNOWN"

    def to_dict(self) -> Dict[str, Any]:
        """Return dictionary representation."""
        payload = asdict(self)
        payload["audit_timestamp"] = self.audit_timestamp.isoformat()
        payload["feature_audits"] = [fa.to_dict() for fa in self.feature_audits]
        if self.target_audit:
            payload["target_audit"] = self.target_audit.to_dict()
        return payload

    @property
    def is_passed(self) -> bool:
        """True if audit PASSED."""
        return self.verdict == AuditVerdictType.PASS

    @property
    def is_failed(self) -> bool:
        """True if audit FAILED."""
        return self.verdict == AuditVerdictType.FAIL

    @property
    def is_blocked(self) -> bool:
        """True if audit is BLOCKED (UNKNOWN)."""
        return self.verdict == AuditVerdictType.UNKNOWN


@dataclass(frozen=True)
class AuditCertificate:
    """Certificate granting permission to train a model on audited data."""

    hypothesis_id: str
    audit_result: InformationAuditResult
    certificate_timestamp: datetime = field(default_factory=utcnow)
    certificate_id: str = ""

    def __post_init__(self) -> None:
        """Generate certificate ID."""
        if not self.certificate_id:
            payload = f"{self.hypothesis_id}:{self.certificate_timestamp.isoformat()}"
            cert_id = hashlib.sha256(payload.encode()).hexdigest()[:12]
            object.__setattr__(self, "certificate_id", cert_id)

    def to_dict(self) -> Dict[str, Any]:
        """Return dictionary representation."""
        return {
            "hypothesis_id": self.hypothesis_id,
            "certificate_id": self.certificate_id,
            "certificate_timestamp": self.certificate_timestamp.isoformat(),
            "audit_verdict": self.audit_result.verdict,
            "audit_passed": self.audit_result.is_passed,
            "audit_blocked": self.audit_result.is_blocked,
        }


class InformationAuditor:
    """Audits hypotheses for future information leakage."""

    def __init__(self, hypothesis_id: str, dataset_version: str = "v1.0"):
        """Initialize the auditor."""
        self.hypothesis_id = hypothesis_id
        self.dataset_version = dataset_version
        self.feature_contracts: Dict[str, TemporalContract] = {}
        self.target_contract: Optional[TemporalContract] = None
        self.audit_result: Optional[InformationAuditResult] = None

    def register_feature_contract(self, contract: TemporalContract) -> None:
        """Register a feature's temporal contract."""
        self.feature_contracts[contract.entity_name] = contract

    def register_target_contract(self, contract: TemporalContract) -> None:
        """Register the target's temporal contract."""
        self.target_contract = contract

    def audit(self) -> InformationAuditResult:
        """Run the information audit."""
        logger.info(
            "Starting information audit",
            hypothesis_id=self.hypothesis_id,
            features=len(self.feature_contracts),
            has_target=self.target_contract is not None,
        )

        feature_audits: List[FeatureAudit] = []
        violations: List[str] = []
        checks: List[Dict[str, Any]] = []

        for feature_name, contract in self.feature_contracts.items():
            audit = self._audit_feature(contract)
            feature_audits.append(audit)
            checks.append(
                {
                    "feature": feature_name,
                    "decision_time": contract.decision_time,
                    "max_information_time": contract.max_information_time,
                    "verdict": audit.verdict,
                }
            )

            if audit.verdict == AuditVerdictType.FAIL:
                violations.append(f"Feature '{feature_name}' depends on future information.")
            elif audit.verdict == AuditVerdictType.UNKNOWN:
                violations.append(
                    f"Feature '{feature_name}' has unverifiable dependencies (provenance unknown)."
                )

        target_audit = None
        if self.target_contract:
            target_audit = self._audit_target(self.target_contract)
            checks.append(
                {
                    "target": self.target_contract.entity_name,
                    "uses_future": target_audit.uses_future_information,
                    "verdict": target_audit.verdict,
                }
            )

        # Determine overall verdict
        feature_verdicts = [fa.verdict for fa in feature_audits]
        if AuditVerdictType.UNKNOWN in feature_verdicts:
            overall_verdict = AuditVerdictType.UNKNOWN
            logger.warning(
                "Audit blocked: unverifiable dependencies detected",
                hypothesis_id=self.hypothesis_id,
            )
        elif AuditVerdictType.FAIL in feature_verdicts:
            overall_verdict = AuditVerdictType.FAIL
            logger.error(
                "Audit failed: future information leakage detected",
                hypothesis_id=self.hypothesis_id,
                violations=violations,
            )
        else:
            overall_verdict = AuditVerdictType.PASS
            logger.info("Audit passed", hypothesis_id=self.hypothesis_id)

        self.audit_result = InformationAuditResult(
            hypothesis_id=self.hypothesis_id,
            dataset_version=self.dataset_version,
            audit_timestamp=utcnow(),
            contract_hash=self._compute_contract_hash(),
            dependency_graph_hash=self._compute_dependency_graph_hash(),
            execution_semantics={"decision_point": "bar_close", "evaluation_order": "chronological"},
            feature_audits=feature_audits,
            target_audit=target_audit,
            dependency_checks=checks,
            violations=violations,
            verdict=overall_verdict,
        )
        return self.audit_result

    def _audit_feature(self, contract: TemporalContract) -> FeatureAudit:
        """Audit a single feature contract."""
        # Rule 1: Check for future dependencies
        if contract.is_future_dependent:
            return FeatureAudit(
                feature_name=contract.entity_name,
                decision_time=contract.decision_time,
                max_information_time=contract.max_information_time,
                is_future_dependent=True,
                has_unverifiable=False,
                verdict=AuditVerdictType.FAIL,
                reasoning="Feature has direct dependency on future data (information_time < 0).",
            )

        # Rule 2: Check for unverifiable dependencies
        if contract.has_unverifiable_dependencies:
            return FeatureAudit(
                feature_name=contract.entity_name,
                decision_time=contract.decision_time,
                max_information_time=contract.max_information_time,
                is_future_dependent=False,
                has_unverifiable=True,
                verdict=AuditVerdictType.UNKNOWN,
                reasoning="Feature has dependencies with unknown provenance. Cannot verify safety.",
            )

        # Rule 3: Check if all dependencies are available at decision time
        if not contract.can_be_used_at_decision:
            return FeatureAudit(
                feature_name=contract.entity_name,
                decision_time=contract.decision_time,
                max_information_time=contract.max_information_time,
                is_future_dependent=False,
                has_unverifiable=False,
                verdict=AuditVerdictType.FAIL,
                reasoning=f"Feature depends on data not available at decision_time. "
                f"max_information_time={contract.max_information_time} > decision_time={contract.decision_time}",
            )

        # All checks passed
        return FeatureAudit(
            feature_name=contract.entity_name,
            decision_time=contract.decision_time,
            max_information_time=contract.max_information_time,
            is_future_dependent=False,
            has_unverifiable=False,
            verdict=AuditVerdictType.PASS,
            reasoning="Feature dependencies are safe; all information available at decision time.",
        )

    def _audit_target(self, contract: TemporalContract) -> TargetAudit:
        """Audit the target variable.

        The target is allowed to use future information (it is revealed after
        the decision), but we audit to ensure this is explicit and documented.
        """
        uses_future = contract.is_future_dependent or contract.max_information_time > contract.decision_time

        return TargetAudit(
            target_name=contract.entity_name,
            uses_future_information=uses_future,
            verdict=AuditVerdictType.PASS,
            reasoning="Target audit complete. Future information usage is expected and allowed.",
        )

    def _compute_contract_hash(self) -> str:
        """Compute a hash of all contracts."""
        data = {
            "features": {
                name: {
                    "decision_time": c.decision_time,
                    "max_information_time": c.max_information_time,
                    "dep_count": len(c.dependencies),
                }
                for name, c in self.feature_contracts.items()
            },
            "has_target": self.target_contract is not None,
        }
        payload = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _compute_dependency_graph_hash(self) -> str:
        """Compute a hash of the dependency graph."""
        graph_data = []
        for name, contract in self.feature_contracts.items():
            for dep in contract.dependencies:
                graph_data.append((name, dep.source_name, dep.information_time))
        graph_data.sort()
        payload = json.dumps(graph_data, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def get_certificate(self) -> AuditCertificate:
        """Get the audit certificate (only if audit passed)."""
        if not self.audit_result:
            raise ValidationFailure("Audit has not been run yet.")

        if self.audit_result.is_blocked:
            raise AuditBlockedError(
                f"Audit is BLOCKED due to unverifiable dependencies. "
                f"Cannot issue certificate for hypothesis {self.hypothesis_id}."
            )

        if not self.audit_result.is_passed:
            raise ValidationFailure(
                f"Audit FAILED. Cannot issue certificate. "
                f"Violations: {'; '.join(self.audit_result.violations)}"
            )

        return AuditCertificate(
            hypothesis_id=self.hypothesis_id,
            audit_result=self.audit_result,
        )
