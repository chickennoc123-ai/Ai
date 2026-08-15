"""YAML + environment based configuration loader.

Configuration is read once from ``config.yaml`` (overridable through the
``EA_FACTORY_CONFIG`` environment variable) and cached as a process wide
singleton.  Every string value supports shell style interpolation:

* ``${VAR}`` - replaced by the environment variable, empty string when unset.
* ``${VAR:-default}`` - replaced by the environment variable or ``default``.

Example:
    >>> config = get_config()
    >>> config.get("broker.xmtrading.symbols")
    ['XAUUSD', 'EURUSD', 'USDJPY', 'GBPUSD', 'AUDUSD']
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional

import yaml

from utils.exceptions import ConfigurationError

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}

_lock = threading.Lock()
_instance: Optional["Config"] = None

DEFAULT_CONFIG_PATH = Path(os.environ.get("EA_FACTORY_CONFIG", "config.yaml"))


def _interpolate(value: str) -> str:
    """Replace ``${VAR}`` / ``${VAR:-default}`` markers with env values."""

    def _replace(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        return os.environ.get(name) or (default if default is not None else "")

    return _ENV_PATTERN.sub(_replace, value)


def _resolve(node: Any) -> Any:
    """Recursively interpolate environment variables inside a config tree."""
    if isinstance(node, str):
        return _interpolate(node)
    if isinstance(node, Mapping):
        return {key: _resolve(item) for key, item in node.items()}
    if isinstance(node, list):
        return [_resolve(item) for item in node]
    return node


class Config:
    """Immutable-ish view over the configuration tree with dotted lookups."""

    def __init__(self, data: Dict[str, Any], source: Optional[Path] = None) -> None:
        self._data: Dict[str, Any] = data
        self.source = source

    # -- construction --------------------------------------------------------
    @classmethod
    def load(cls, path: Optional[Path | str] = None) -> "Config":
        """Load configuration from a YAML file.

        Args:
            path: Optional path to the YAML file. Defaults to ``config.yaml``.

        Returns:
            A fully interpolated :class:`Config` instance.

        Raises:
            ConfigurationError: If the file is missing or not a YAML mapping.
        """
        config_path = Path(path) if path else DEFAULT_CONFIG_PATH
        if not config_path.exists():
            raise ConfigurationError("Configuration file not found", path=str(config_path))
        try:
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:  # pragma: no cover - defensive
            raise ConfigurationError("Invalid YAML in configuration", path=str(config_path)) from exc
        if not isinstance(raw, dict):
            raise ConfigurationError("Configuration root must be a mapping", path=str(config_path))
        return cls(_resolve(raw), config_path)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Config":
        """Build a config from an in-memory mapping (useful for tests)."""
        return cls(_resolve(dict(data)))

    # -- access --------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        """Return a value using a dotted path such as ``"api.port"``."""
        node: Any = self._data
        for part in key.split("."):
            if isinstance(node, Mapping) and part in node:
                node = node[part]
            else:
                return default
        return node

    def require(self, key: str) -> Any:
        """Return a mandatory value or raise :class:`ConfigurationError`."""
        sentinel = object()
        value = self.get(key, sentinel)
        if value is sentinel:
            raise ConfigurationError("Missing required configuration key", key=key)
        return value

    def get_int(self, key: str, default: int = 0) -> int:
        """Return a value coerced to ``int``."""
        value = self.get(key, default)
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Return a value coerced to ``float``."""
        value = self.get(key, default)
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Return a value coerced to ``bool`` (accepts yes/no/on/off/1/0)."""
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE_VALUES:
            return True
        if text in _FALSE_VALUES:
            return False
        return default

    def get_list(self, key: str, default: Optional[List[Any]] = None) -> List[Any]:
        """Return a list value, tolerating comma separated strings."""
        value = self.get(key, None)
        if value is None:
            return list(default or [])
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return [value]

    def section(self, key: str) -> "Config":
        """Return a nested section as its own :class:`Config`."""
        value = self.get(key, {})
        if not isinstance(value, Mapping):
            raise ConfigurationError("Configuration section is not a mapping", key=key)
        return Config(dict(value), self.source)

    def as_dict(self) -> Dict[str, Any]:
        """Return a deep-ish copy of the underlying mapping."""
        return dict(self._data)

    def merged(self, overrides: Mapping[str, Any]) -> "Config":
        """Return a new config with ``overrides`` deep-merged on top."""
        return Config(_deep_merge(dict(self._data), overrides), self.source)

    # -- dunder helpers ------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self.require(key)

    def __contains__(self, key: str) -> bool:
        sentinel = object()
        return self.get(key, sentinel) is not sentinel

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Config(source={self.source}, keys={sorted(self._data)})"


def _deep_merge(base: Dict[str, Any], overrides: Mapping[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``overrides`` into ``base`` returning a new dict."""
    result = dict(base)
    for key, value in overrides.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(dict(result[key]), value)
        else:
            result[key] = value
    return result


def get_config(path: Optional[Path | str] = None) -> Config:
    """Return the process-wide configuration singleton, loading it on demand."""
    global _instance
    if _instance is None or path is not None:
        with _lock:
            if _instance is None or path is not None:
                _instance = Config.load(path)
    return _instance


def set_config(config: Config) -> None:
    """Replace the configuration singleton (used by tests and workers)."""
    global _instance
    with _lock:
        _instance = config


def reset_config() -> None:
    """Drop the cached configuration so the next call reloads from disk."""
    global _instance
    with _lock:
        _instance = None
