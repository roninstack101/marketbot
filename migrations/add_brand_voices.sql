-- Migration: add brand_voices table
-- Run once:  psql -U claudbot -d claudbot -f migrations/add_brand_voices.sql

CREATE TABLE IF NOT EXISTS brand_voices (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_name      VARCHAR(100) NOT NULL UNIQUE,   -- slug: lowercase-hyphenated
    display_name    VARCHAR(200) NOT NULL,
    tone            TEXT         NOT NULL,
    personality     TEXT,
    target_audience TEXT,
    dos             JSONB        NOT NULL DEFAULT '[]',
    donts           JSONB        NOT NULL DEFAULT '[]',
    example_phrases JSONB        NOT NULL DEFAULT '[]',
    extra_notes     TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brand_voices_brand_name ON brand_voices(brand_name);

DROP TRIGGER IF EXISTS set_brand_voices_updated_at ON brand_voices;
CREATE TRIGGER set_brand_voices_updated_at
    BEFORE UPDATE ON brand_voices
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
