#!/usr/bin/env bash
# docker/init-db.sh
# Multi-database initializer for PostgreSQL container (used on initial volume boot)
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE viai_qa;
    GRANT ALL PRIVILEGES ON DATABASE viai_qa TO "$POSTGRES_USER";
EOSQL
