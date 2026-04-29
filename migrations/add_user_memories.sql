-- User memory table: one row per remembered fact per user
CREATE TABLE IF NOT EXISTS user_memories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     VARCHAR(200) NOT NULL,
    category    VARCHAR(50)  NOT NULL DEFAULT 'fact',
    memory      TEXT         NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_user_memories_user_id ON user_memories(user_id);
