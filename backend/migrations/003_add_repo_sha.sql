-- migration: add repo_sha column to analysis_history for smart cache
-- run this in Supabase SQL Editor or via Supabase CLI

ALTER TABLE analysis_history
ADD COLUMN IF NOT EXISTS repo_sha TEXT;

-- index for fast SHA cache lookup
CREATE INDEX IF NOT EXISTS idx_analysis_history_repo_cache
ON analysis_history(user_id, repo_url, branch, repo_sha);
