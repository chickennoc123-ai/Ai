"""Database engine, session management and schema creation.

PostgreSQL is the production target; when no ``DATABASE_URL`` (or
``database.url``) is configured the engine falls back to a local SQLite file so
the platform still runs on a laptop or in CI.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from utils.config import Config, get_config
from utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_SQLITE_PATH = Path("data/ea_factory.db")


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


def build_database_url(config: Optional[Config] = None) -> str:
    """Return the SQLAlchemy URL, preferring PostgreSQL when configured."""
    cfg = config or get_config()
    explicit = str(cfg.get("database.url", "") or os.environ.get("DATABASE_URL", "")).strip()
    if explicit:
        return explicit
    host = os.environ.get("POSTGRES_HOST", "").strip()
    if host:
        user = os.environ.get("POSTGRES_USER", "eafactory")
        password = os.environ.get("POSTGRES_PASSWORD", "eafactory")
        port = os.environ.get("POSTGRES_PORT", "5432")
        name = os.environ.get("POSTGRES_DB", "eafactory")
        return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"
    DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DEFAULT_SQLITE_PATH}"


class Database:
    """Owns the engine and hands out sessions."""

    def __init__(self, url: Optional[str] = None, config: Optional[Config] = None) -> None:
        """Create the engine and the session factory."""
        self.config = config or get_config()
        self.url = url or build_database_url(self.config)
        self.engine = self._create_engine()
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        logger.info("Database engine ready", dialect=self.engine.dialect.name)

    def _create_engine(self) -> Engine:
        """Build the engine with dialect-appropriate options."""
        if self.url.startswith("sqlite"):
            engine = create_engine(
                self.url,
                echo=self.config.get_bool("database.echo", False),
                future=True,
                connect_args={"check_same_thread": False},
            )

            @event.listens_for(engine, "connect")
            def _set_sqlite_pragma(dbapi_connection: Any, _record: Any) -> None:
                """Enable WAL and foreign keys on SQLite connections."""
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

            return engine
        return create_engine(
            self.url,
            echo=self.config.get_bool("database.echo", False),
            future=True,
            pool_size=self.config.get_int("database.pool_size", 10),
            max_overflow=self.config.get_int("database.max_overflow", 20),
            pool_pre_ping=True,
        )

    def create_all(self) -> None:
        """Create every table declared on :class:`Base`."""
        # Importing the models registers them on the metadata.
        from models import account, metrics, order, position, strategy, trade  # noqa: F401

        Base.metadata.create_all(self.engine)
        logger.info("Database schema ensured", tables=len(Base.metadata.tables))

    def drop_all(self) -> None:
        """Drop every table (destructive, used by tests and ``init_db --reset``)."""
        Base.metadata.drop_all(self.engine)
        logger.warning("Database schema dropped")

    def session(self) -> Session:
        """Return a new session (the caller owns commit/close)."""
        return self.session_factory()

    def health(self) -> Dict[str, Any]:
        """Return connectivity information for the health endpoint."""
        try:
            with self.engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")
            tables = inspect(self.engine).get_table_names()
            return {"connected": True, "dialect": self.engine.dialect.name, "tables": len(tables)}
        except Exception as exc:  # noqa: BLE001 - health must never raise
            return {"connected": False, "error": str(exc), "dialect": self.engine.dialect.name}

    def dispose(self) -> None:
        """Close all pooled connections."""
        self.engine.dispose()


_database: Optional[Database] = None


def get_database(config: Optional[Config] = None) -> Database:
    """Return the process-wide :class:`Database` singleton."""
    global _database
    if _database is None:
        _database = Database(config=config)
    return _database


def set_database(database: Optional[Database]) -> None:
    """Replace the singleton (used by tests)."""
    global _database
    _database = database


@contextmanager
def session_scope(database: Optional[Database] = None) -> Iterator[Session]:
    """Provide a transactional scope around a series of operations.

    Example:
        >>> with session_scope() as session:
        ...     session.add(record)
    """
    db = database or get_database()
    session = db.session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
