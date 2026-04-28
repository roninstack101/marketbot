-- ClaudBot initial schema
-- Run once against your PostgreSQL database:
--   psql -U claudbot -d claudbot -f migrations/init.sql

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Optional: enable pgvector for semantic memory search
-- Uncomment if you have installed pgvector:
-- CREATE EXTENSION IF NOT EXISTS vector;

-- ─── Tasks ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_task       TEXT        NOT NULL,
    created_by      VARCHAR(100),
    status          VARCHAR(50) NOT NULL DEFAULT 'pending',

    plan            JSONB,
    step_results    JSONB,
    agent_state     JSONB,

    final_output    TEXT,
    output_version  INTEGER     NOT NULL DEFAULT 1,
    critique        TEXT,
    error           TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tasks_status      ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at  ON tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_created_by  ON tasks(created_by);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_tasks_updated_at ON tasks;
CREATE TRIGGER set_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─── Approvals ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS approvals (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id          UUID        NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    action_type      VARCHAR(100) NOT NULL,
    action_payload   JSONB       NOT NULL,
    action_summary   TEXT,
    status           VARCHAR(50) NOT NULL DEFAULT 'pending',
    approved_by      VARCHAR(100),
    rejection_reason TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_approvals_task_id ON approvals(task_id);
CREATE INDEX IF NOT EXISTS idx_approvals_status  ON approvals(status);

-- ─── Memories ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS memories (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id        UUID,
    task_type      VARCHAR(100),
    task_summary   TEXT        NOT NULL,
    output_summary TEXT        NOT NULL,
    keywords       JSONB,
    metadata       JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memories_task_type  ON memories(task_type);
CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at DESC);

-- Full-text search index on summaries
CREATE INDEX IF NOT EXISTS idx_memories_task_summary_trgm
    ON memories USING gin(to_tsvector('english', task_summary || ' ' || output_summary));

-- Optional pgvector column – uncomment after enabling the extension:
-- ALTER TABLE memories ADD COLUMN IF NOT EXISTS embedding vector(1536);
-- CREATE INDEX IF NOT EXISTS idx_memories_embedding
--     ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
