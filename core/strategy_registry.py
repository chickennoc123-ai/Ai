"""Registry and factory for trading strategies.

Strategies register themselves with :func:`register_strategy`; the registry is
populated lazily by importing the :mod:`strategies` package (including the
``ai_generated`` sub-package written by the Research Agent).
"""

from __future__ import annotations

import importlib
import pkgutil
import threading
from typing import Any, Dict, Iterable, List, Mapping, Optional, Type

from core.strategy import Strategy, StrategyMetadata
from utils.exceptions import StrategyError
from utils.logger import get_logger

logger = get_logger(__name__)

_registry: Dict[str, Type[Strategy]] = {}
_loaded = False
_lock = threading.Lock()


def register_strategy(cls: Type[Strategy]) -> Type[Strategy]:
    """Class decorator registering a strategy implementation.

    Args:
        cls: Strategy subclass exposing a unique ``name``.

    Returns:
        The class unchanged, so it can be used as a decorator.
    """
    key = cls.name.upper()
    if key in _registry and _registry[key] is not cls:
        logger.warning("Overriding registered strategy", strategy=cls.name)
    _registry[key] = cls
    return cls


def _discover(package: str) -> None:
    """Import every module of ``package`` so decorators run."""
    try:
        module = importlib.import_module(package)
    except ImportError as exc:  # pragma: no cover - packaging issue
        logger.error("Unable to import strategy package", package=package, error=str(exc))
        return
    for info in pkgutil.walk_packages(module.__path__, prefix=f"{package}."):
        if info.name.rsplit(".", 1)[-1].startswith("_"):
            continue
        try:
            importlib.import_module(info.name)
        except Exception as exc:  # pragma: no cover - a broken generated file must not kill the app
            logger.error("Failed to import strategy module", module=info.name, error=str(exc))


def load_strategies(force: bool = False) -> None:
    """Populate the registry by importing all strategy modules."""
    global _loaded
    with _lock:
        if _loaded and not force:
            return
        _discover("strategies")
        _loaded = True
        logger.info("Strategy registry loaded", count=len(_registry))


def available_strategies() -> List[str]:
    """Return the sorted list of registered strategy names."""
    load_strategies()
    return sorted(cls.name for cls in _registry.values())


def get_strategy_class(name: str) -> Type[Strategy]:
    """Return the class registered under ``name``.

    Raises:
        StrategyError: If no strategy matches.
    """
    load_strategies()
    key = str(name).upper()
    if key not in _registry:
        raise StrategyError("Unknown strategy", strategy=name, available=available_strategies())
    return _registry[key]


def create_strategy(
    name: str,
    symbol: str = "EURUSD",
    timeframe: str = "H1",
    params: Optional[Mapping[str, Any]] = None,
    strategy_id: Optional[str] = None,
) -> Strategy:
    """Instantiate a strategy by name.

    Args:
        name: Registered strategy name (case insensitive).
        symbol: Instrument to trade.
        timeframe: Bar timeframe.
        params: Parameter overrides.
        strategy_id: Optional explicit identifier.

    Returns:
        A ready to use strategy instance.
    """
    cls = get_strategy_class(name)
    return cls(symbol=symbol, timeframe=timeframe, params=params, strategy_id=strategy_id)


def build_universe(
    names: Iterable[str], symbols: Iterable[str], timeframe: str = "H1"
) -> List[Strategy]:
    """Instantiate the cartesian product of ``names`` and ``symbols``."""
    universe: List[Strategy] = []
    for name in names:
        for symbol in symbols:
            try:
                universe.append(create_strategy(name, symbol, timeframe))
            except StrategyError as exc:
                logger.warning("Skipping strategy", strategy=name, symbol=symbol, error=str(exc))
    return universe


def describe_strategies(symbol: str = "EURUSD", timeframe: str = "H1") -> List[StrategyMetadata]:
    """Return metadata for every registered strategy."""
    load_strategies()
    descriptions: List[StrategyMetadata] = []
    for cls in sorted(_registry.values(), key=lambda item: item.name):
        try:
            descriptions.append(cls(symbol, timeframe).metadata())
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Unable to describe strategy", strategy=cls.name, error=str(exc))
    return descriptions


def registry_snapshot() -> Dict[str, Type[Strategy]]:
    """Return a shallow copy of the registry (mainly for tests)."""
    load_strategies()
    return dict(_registry)
