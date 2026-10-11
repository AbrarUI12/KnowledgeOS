#!/bin/bash
# Creates the KnowledgeOS database roles (local development only).
#
#   knowledgeos_owner       owns the schema; used by Alembic migrations
#   knowledgeos_app         runtime role: NOSUPERUSER, NOBYPASSRLS, owns nothing (RLS applies)
#   knowledgeos_dispatcher  outbox dispatcher role (narrow RLS policy added in Session 16)
#
# Default privileges give the runtime roles DML on tables the owner creates later.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
  CREATE ROLE knowledgeos_owner LOGIN PASSWORD '${KOS_OWNER_PASSWORD}';
  CREATE ROLE knowledgeos_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
    PASSWORD '${KOS_APP_PASSWORD}';
  CREATE ROLE knowledgeos_dispatcher LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
    PASSWORD '${KOS_DISPATCHER_PASSWORD}';

  ALTER DATABASE "${POSTGRES_DB}" OWNER TO knowledgeos_owner;
  ALTER SCHEMA public OWNER TO knowledgeos_owner;
  REVOKE CREATE ON SCHEMA public FROM PUBLIC;
  GRANT USAGE ON SCHEMA public TO knowledgeos_app, knowledgeos_dispatcher;

  ALTER DEFAULT PRIVILEGES FOR ROLE knowledgeos_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO knowledgeos_app;
  ALTER DEFAULT PRIVILEGES FOR ROLE knowledgeos_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO knowledgeos_app;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-SQL
  CREATE ROLE keycloak LOGIN PASSWORD '${KEYCLOAK_DB_PASSWORD}';
  CREATE DATABASE keycloak OWNER keycloak;
SQL
