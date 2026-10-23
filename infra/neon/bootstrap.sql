-- KnowledgeOS database bootstrap for Neon (S32). Run ONCE per branch database (staging first),
-- in the Neon SQL editor or psql, as the project's default role (e.g. neondb_owner).
--
-- Replace the three <...> placeholders with freshly generated passwords. Store them only in the
-- Hugging Face Space secrets (DATABASE_URL, DATABASE_MIGRATION_URL, DISPATCHER_DATABASE_URL);
-- never commit them. Roles are created here by SQL on purpose: roles made in the Neon console
-- join neon_superuser and get elevated privileges (session.md S32).
--
--   knowledgeos_owner       owns the schema objects; used only by Alembic migrations
--   knowledgeos_app         runtime role: NOSUPERUSER, NOBYPASSRLS, owns nothing (RLS applies)
--   knowledgeos_dispatcher  outbox dispatcher role (narrow grants and RLS policy from migrations)

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE ROLE knowledgeos_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
  PASSWORD '<owner-password>';
CREATE ROLE knowledgeos_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
  PASSWORD '<app-password>';
CREATE ROLE knowledgeos_dispatcher LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
  PASSWORD '<dispatcher-password>';

-- The bootstrap role needs membership to hand over ownership and set default privileges.
GRANT knowledgeos_owner TO CURRENT_USER;

GRANT CREATE, USAGE ON SCHEMA public TO knowledgeos_owner;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO knowledgeos_app, knowledgeos_dispatcher;

ALTER DEFAULT PRIVILEGES FOR ROLE knowledgeos_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO knowledgeos_app;
ALTER DEFAULT PRIVILEGES FOR ROLE knowledgeos_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO knowledgeos_app;

-- Check: all three must show rolsuper = false and rolbypassrls = false.
SELECT rolname, rolsuper, rolbypassrls
FROM pg_roles
WHERE rolname LIKE 'knowledgeos_%'
ORDER BY rolname;
