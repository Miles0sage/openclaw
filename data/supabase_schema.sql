-- ============================================
-- OpenClaw Data Layer — Supabase Schema
-- Run this in Supabase Dashboard > SQL Editor
-- ============================================

-- 1. JOBS TABLE — replaces data/jobs/jobs.jsonl
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    task TEXT NOT NULL,
    priority TEXT DEFAULT 'P1',
    status TEXT DEFAULT 'pending',
    agent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cost_usd NUMERIC(10,4) DEFAULT 0,
    result_summary TEXT,
    error TEXT,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- 2. MEMORIES TABLE — replaces JSONL memories
CREATE TABLE IF NOT EXISTS memories (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    importance INTEGER DEFAULT 5,
    tags TEXT[] DEFAULT '{}',
    remind_at TIMESTAMPTZ,
    reminded BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. COSTS TABLE — replaces data/costs/costs.jsonl
CREATE TABLE IF NOT EXISTS costs (
    id SERIAL PRIMARY KEY,
    project TEXT,
    agent TEXT,
    model TEXT,
    tokens_input INTEGER DEFAULT 0,
    tokens_output INTEGER DEFAULT 0,
    cost_usd NUMERIC(10,6) DEFAULT 0,
    job_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. REFLECTIONS TABLE — replaces data/reflections.jsonl
CREATE TABLE IF NOT EXISTS reflections (
    id SERIAL PRIMARY KEY,
    job_id TEXT,
    project TEXT,
    task TEXT,
    outcome TEXT,
    reflection TEXT,
    lessons TEXT[],
    cost_usd NUMERIC(10,4) DEFAULT 0,
    duration_seconds INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. CHECKPOINTS TABLE — replaces data/checkpoints.db
CREATE TABLE IF NOT EXISTS checkpoints (
    id SERIAL PRIMARY KEY,
    job_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    step_index INTEGER DEFAULT 0,
    tool_iteration INTEGER DEFAULT 0,
    state JSONB DEFAULT '{}'::jsonb,
    messages JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. BLACKBOARD TABLE — replaces data/blackboard.db
CREATE TABLE IF NOT EXISTS blackboard (
    key TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT 'global',
    value TEXT,
    job_id TEXT,
    agent TEXT,
    ttl_seconds INTEGER DEFAULT 86400,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (key, project)
);

-- 7. EVENTS TABLE — replaces in-memory event log
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- Indexes for query performance
-- ============================================
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_costs_project ON costs(project);
CREATE INDEX IF NOT EXISTS idx_costs_created ON costs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_costs_job ON costs(job_id);
CREATE INDEX IF NOT EXISTS idx_reflections_project ON reflections(project);
CREATE INDEX IF NOT EXISTS idx_checkpoints_job ON checkpoints(job_id);
CREATE INDEX IF NOT EXISTS idx_blackboard_project ON blackboard(project);
CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at DESC);

-- ============================================
-- Helper function: exec_sql (so agents can run SQL remotely)
-- ============================================
CREATE OR REPLACE FUNCTION exec_sql(query TEXT)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    result JSONB;
BEGIN
    EXECUTE query;
    RETURN '{"status": "ok"}'::jsonb;
EXCEPTION WHEN OTHERS THEN
    RETURN jsonb_build_object('error', SQLERRM);
END;
$$;

-- ============================================
-- Updated_at auto-trigger
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER jobs_updated_at BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER memories_updated_at BEFORE UPDATE ON memories
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER blackboard_updated_at BEFORE UPDATE ON blackboard
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================
-- Enable realtime for live dashboard
-- ============================================
ALTER PUBLICATION supabase_realtime ADD TABLE jobs;
ALTER PUBLICATION supabase_realtime ADD TABLE events;
ALTER PUBLICATION supabase_realtime ADD TABLE costs;

SELECT 'OpenClaw schema created successfully!' as result;
