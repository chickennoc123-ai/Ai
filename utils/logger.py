"""Structured logging with contextual binding.

Loggers created via :func:`get_logger` accept arbitrary context (``agent_id``,
``strategy_id``, ``correlation_id`` ...) which is attached to every record and
rendered either as ``key=value`` pairs (console) or as JSON (production).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, MutableMapping, Optional, Tuple

_CONTEXT_KEY = "ea_context"
_configured = False

correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)

_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "message", "module", "msecs", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "thread", "threadName", "taskName", _CONTEXT_KEY,
}


class ContextFilter(logging.Filter):
    """Inject the ambient correlation id into every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        context: Dict[str, Any] = dict(getattr(record, _CONTEXT_KEY, {}) or {})
        correlation_id = correlation_id_var.get()
        if correlation_id and "correlation_id" not in context:
            context["correlation_id"] = correlation_id
        setattr(record, _CONTEXT_KEY, context)
        return True


class KeyValueFormatter(logging.Formatter):
    """Human readable formatter appending ``key=value`` context."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        context: Dict[str, Any] = getattr(record, _CONTEXT_KEY, {}) or {}
        if not context:
            return base
        rendered = " ".join(f"{key}={value}" for key, value in sorted(context.items()))
        return f"{base} | {rendered}"


class JsonFormatter(logging.Formatter):
    """Machine readable one-line JSON formatter."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(getattr(record, _CONTEXT_KEY, {}) or {})
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload.setdefault(key, value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class BoundLogger(logging.LoggerAdapter):
    """Logger adapter carrying immutable structured context."""

    #: Keyword arguments understood by :mod:`logging` itself.
    _LOGGING_KWARGS = ("exc_info", "stack_info", "stacklevel", "extra")

    def process(self, msg: Any, kwargs: MutableMapping[str, Any]) -> Tuple[Any, MutableMapping[str, Any]]:
        """Fold ad-hoc keyword arguments into the record's structured context."""
        extra = dict(kwargs.get("extra") or {})
        context = dict(self.extra or {})
        context.update(extra.pop(_CONTEXT_KEY, {}) or {})
        # Any keyword that logging does not understand becomes context.
        for key in [name for name in kwargs if name not in self._LOGGING_KWARGS]:
            context[key] = kwargs.pop(key)
        for key in list(extra.keys()):
            context[key] = extra.pop(key)
        extra[_CONTEXT_KEY] = context
        kwargs["extra"] = extra
        return msg, kwargs

    def bind(self, **context: Any) -> "BoundLogger":
        """Return a new logger with additional context merged in."""
        merged = dict(self.extra or {})
        merged.update(context)
        return BoundLogger(self.logger, merged)


def setup_logging(
    level: str = "INFO",
    fmt: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    json_logs: bool = False,
    log_file: Optional[str] = None,
    force: bool = False,
) -> None:
    """Configure root logging handlers once per process.

    Args:
        level: Logging level name (``DEBUG``, ``INFO`` ...).
        fmt: ``logging`` format string used by the console formatter.
        json_logs: Emit JSON lines instead of human readable text.
        log_file: Optional rotating file destination.
        force: Reconfigure even when logging was already initialised.
    """
    global _configured
    if _configured and not force:
        return

    root = logging.getLogger()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter: logging.Formatter = JsonFormatter() if json_logs else KeyValueFormatter(fmt)
    context_filter = ContextFilter()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.addFilter(context_filter)
    root.addHandler(console)

    if log_file:
        path = Path(log_file)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=20 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            file_handler.addFilter(context_filter)
            root.addHandler(file_handler)
        except OSError:  # pragma: no cover - read-only filesystem
            root.warning("Unable to open log file %s, continuing with console only", path)

    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    _configured = True


def setup_logging_from_config(config: Any) -> None:
    """Configure logging using a :class:`utils.config.Config` instance."""
    setup_logging(
        level=config.get("logging.level", "INFO"),
        fmt=config.get("logging.format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
        json_logs=config.get_bool("logging.json", False),
        log_file=config.get("logging.file"),
    )


def get_logger(name: str, **context: Any) -> BoundLogger:
    """Return a context-bound logger.

    Args:
        name: Logger name, typically ``__name__`` or ``"agent.risk"``.
        **context: Structured fields attached to every emitted record.
    """
    if not _configured:
        setup_logging()
    return BoundLogger(logging.getLogger(name), dict(context))


def set_correlation_id(correlation_id: Optional[str]) -> None:
    """Bind a correlation id to the current async/thread context."""
    correlation_id_var.set(correlation_id)
