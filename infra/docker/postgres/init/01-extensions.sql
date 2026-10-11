-- Runs once, as the superuser, when the data volume is first created.
-- Extensions are created here because creating them needs elevated privileges;
-- Alembic migration 0001 repeats them with IF NOT EXISTS (a no-op locally).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
