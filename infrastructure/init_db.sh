#!/bin/bash
# infrastructure/init_db.sh
# PostgreSQL bootstrap: auto-create 'airflow' database on first container start.
# This script runs automatically via /docker-entrypoint-initdb.d/ on first boot only.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'marquez') THEN
            CREATE ROLE marquez LOGIN PASSWORD 'marquez';
        ELSE
            ALTER ROLE marquez WITH LOGIN PASSWORD 'marquez';
        END IF;
    END
    \$\$;

    SELECT 'CREATE DATABASE airflow'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow')\gexec

    GRANT ALL PRIVILEGES ON DATABASE airflow TO "$POSTGRES_USER";

    SELECT 'CREATE DATABASE marquez OWNER marquez'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'marquez')\gexec

    SELECT 'CREATE DATABASE marquez_db'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'marquez_db')\gexec

    ALTER DATABASE marquez_db OWNER TO marquez;
    GRANT ALL PRIVILEGES ON DATABASE marquez TO marquez;
    GRANT ALL PRIVILEGES ON DATABASE marquez_db TO marquez;
    GRANT ALL PRIVILEGES ON DATABASE marquez_db TO "$POSTGRES_USER";
EOSQL

echo "init_db.sh: 'airflow', 'marquez', and 'marquez_db' databases ready."
