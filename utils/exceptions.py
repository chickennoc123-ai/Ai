"""Custom exception hierarchy for EA Factory Pro.

Every failure raised by the platform derives from :class:`EAFactoryError`, so
callers can catch a single base class at process boundaries while still being
able to react to specific conditions (e.g. retry only on connection errors).
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class EAFactoryError(Exception):
    """Base class for all EA Factory Pro errors.

    Attributes:
        message: Human readable error description.
        context: Structured key/value pairs describing the failure site.
    """

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context: Dict[str, Any] = context

    def __str__(self) -> str:  # pragma: no cover - trivial formatting
        if not self.context:
            return self.message
        rendered = " ".join(f"{key}={value!r}" for key, value in self.context.items())
        return f"{self.message} ({rendered})"


class ConfigurationError(EAFactoryError):
    """Raised when configuration is missing, malformed or contradictory."""


class DataError(EAFactoryError):
    """Raised when market data cannot be fetched, parsed or validated."""


class StrategyError(EAFactoryError):
    """Raised when a strategy is misconfigured or fails during signal generation."""


class ValidationFailure(EAFactoryError):
    """Raised when a candidate strategy fails the validation gate."""


class BrokerError(EAFactoryError):
    """Base class for broker-side failures."""


class BrokerConnectionError(BrokerError):
    """Raised when the broker connection cannot be established or is lost."""


class AuthenticationError(BrokerError):
    """Raised when broker credentials are rejected."""


class OrderRejectedError(BrokerError):
    """Raised when the broker rejects an order request.

    Attributes:
        reason: Broker supplied rejection reason.
    """

    def __init__(self, message: str, reason: Optional[str] = None, **context: Any) -> None:
        super().__init__(message, **context)
        self.reason = reason or message


class InsufficientMarginError(OrderRejectedError):
    """Raised when free margin is not sufficient for the requested volume."""


class PositionNotFoundError(BrokerError):
    """Raised when an operation targets a position that does not exist."""


class OrderNotFoundError(BrokerError):
    """Raised when an operation targets an order that does not exist."""


class RiskLimitExceeded(EAFactoryError):
    """Raised when an action would breach a configured risk limit."""

    def __init__(self, message: str, limit: str, value: float, threshold: float, **context: Any) -> None:
        super().__init__(message, limit=limit, value=value, threshold=threshold, **context)
        self.limit = limit
        self.value = value
        self.threshold = threshold


class AgentError(EAFactoryError):
    """Raised when an agent fails irrecoverably."""


class MessageBusError(EAFactoryError):
    """Raised when the message bus cannot deliver or receive a message."""
