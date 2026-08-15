"""Create (or reset) the database schema.

Usage::

    python scripts/init_db.py            # create missing tables
    python scripts/init_db.py --reset    # drop everything first
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.database import Base, get_database  # noqa: E402
from utils.config import get_config  # noqa: E402
from utils.logger import get_logger, setup_logging_from_config  # noqa: E402


def main() -> int:
    """Create the schema and report the tables.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="Initialise the EA Factory Pro database")
    parser.add_argument("--reset", action="store_true", help="Drop all tables before creating them")
    arguments = parser.parse_args()

    config = get_config()
    setup_logging_from_config(config)
    logger = get_logger("init_db")

    database = get_database(config)
    logger.info("Connecting to the database", url=database.url.split("@")[-1])

    if arguments.reset:
        confirmation = input("This deletes every stored row. Type 'yes' to continue: ")
        if confirmation.strip().lower() != "yes":
            logger.info("Reset cancelled")
            return 1
        database.drop_all()

    database.create_all()
    health = database.health()
    logger.info("Schema ready", **health)
    print(f"Database: {database.url.split('@')[-1]}")
    print(f"Dialect : {health.get('dialect')}")
    print(f"Tables  : {', '.join(sorted(Base.metadata.tables))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
