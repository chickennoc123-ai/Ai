-- ---------------------------------------------------------------------------
-- EA Factory Pro - PostgreSQL bootstrap.
-- Tables themselves are created by SQLAlchemy (scripts/init_db.py); this file
-- only prepares extensions, roles and database level settings.
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- A read-only role for dashboards and ad-hoc analysis.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eafactory_readonly') THEN
        CREATE ROLE eafactory_readonly LOGIN PASSWORD 'readonly';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE eafactory TO eafactory_readonly;
GRANT USAGE ON SCHEMA public TO eafactory_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO eafactory_readonly;

-- Reasonable defaults for a trading workload with frequent small writes.
ALTER DATABASE eafactory SET timezone TO 'UTC';
ALTER DATABASE eafactory SET statement_timeout TO '60s';
ALTER DATABASE eafactory SET idle_in_transaction_session_timeout TO '120s';
