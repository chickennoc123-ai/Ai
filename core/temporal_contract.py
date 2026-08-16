"""Temporal contract: contracts for time-aware dependencies in strategies.

A temporal contract specifies when a value (feature or target) is "known" relative
to the decision point. This enables auditing for future information leakage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Set

import pandas as pd


class TemporalStatus(str, Enum):
    """Temporal status of a dependency."""

    KNOWN = "known"
    UNKNOWN = "unknown"
    FUTURE = "future"


@dataclass(frozen=True)
class TemporalDependency:
    """A single dependency with its temporal characteristics."""

    source_name: str
    source_type: str
    information_time: int
    provenance: Optional[str] = None
    description: str = ""

    @property
    def status(self) -> TemporalStatus:
        """Classify the dependency's temporal status."""
        if self.information_time < 0:
            return TemporalStatus.FUTURE
        if self.provenance is None:
            return TemporalStatus.UNKNOWN
        return TemporalStatus.KNOWN


@dataclass(frozen=True)
class TemporalContract:
    """Contract specifying temporal characteristics of a feature or target."""

    entity_name: str
    entity_type: str
    decision_time: int
    dependencies: tuple[TemporalDependency, ...] = field(default_factory=tuple)
    max_information_time: int = field(default=0)
    is_future_dependent: bool = field(default=False)
    provenance_verified: bool = field(default=False)
    contract_hash: str = ""
    contract_timestamp: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self) -> None:
        """Compute derived fields."""
        if not self.max_information_time and self.dependencies:
            times = [dep.information_time for dep in self.dependencies]
            object.__setattr__(self, "max_information_time", max(times) if times else 0)

        if not self.is_future_dependent and self.dependencies:
            has_future = any(dep.information_time < 0 for dep in self.dependencies)
            object.__setattr__(self, "is_future_dependent", has_future)

    @property
    def can_be_used_at_decision(self) -> bool:
        """True if all dependencies are available at decision_time."""
        return self.max_information_time <= self.decision_time

    @property
    def has_unverifiable_dependencies(self) -> bool:
        """True if any dependency has unknown provenance."""
        return any(dep.provenance is None for dep in self.dependencies)

    def summary(self) -> Dict[str, Any]:
        """Return a summary of the contract."""
        return {
            "entity_name": self.entity_name,
            "entity_type": self.entity_type,
            "decision_time": self.decision_time,
            "max_information_time": self.max_information_time,
            "can_be_used_at_decision": self.can_be_used_at_decision,
            "is_future_dependent": self.is_future_dependent,
            "has_unverifiable_dependencies": self.has_unverifiable_dependencies,
            "dependency_count": len(self.dependencies),
        }


class TemporalContractBuilder:
    """Builder for constructing temporal contracts."""

    def __init__(self, entity_name: str, entity_type: str, decision_time: int):
        """Initialize the builder."""
        self.entity_name = entity_name
        self.entity_type = entity_type
        self.decision_time = decision_time
        self.dependencies: list[TemporalDependency] = []

    def add_dependency(
        self,
        source_name: str,
        source_type: str,
        information_time: int,
        provenance: Optional[str] = None,
        description: str = "",
    ) -> "TemporalContractBuilder":
        """Add a dependency to the contract."""
        dep = TemporalDependency(
            source_name=source_name,
            source_type=source_type,
            information_time=information_time,
            provenance=provenance,
            description=description,
        )
        self.dependencies.append(dep)
        return self

    def build(self) -> TemporalContract:
        """Build the temporal contract."""
        return TemporalContract(
            entity_name=self.entity_name,
            entity_type=self.entity_type,
            decision_time=self.decision_time,
            dependencies=tuple(self.dependencies),
        )
