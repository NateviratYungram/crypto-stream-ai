#!/bin/bash
# infrastructure/init_db.sh
# PostgreSQL bootstrap: auto-create 'airflow' database on first container start.
# This script runs automatically via /docker-entrypoint-initdb.d/ on first boot only.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE airflow'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow')\gexec

    GRANT ALL PRIVILEGES ON DATABASE airflow TO "$POSTGRES_USER";
EOSQL

echo "init_db.sh: 'airflow' database ready."

