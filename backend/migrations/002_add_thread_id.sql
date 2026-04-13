-- migration: add thread_id to analysis_history
-- run this in Supabase SQL Editor or via Supabase CLI

ALTER TABLE analysis_history
ADD COLUMN IF NOT EXISTS thread_id TEXT;

CREATE INDEX IF NOT EXISTS idx_analysis_history_thread_id
ON analysis_history(thread_id);
