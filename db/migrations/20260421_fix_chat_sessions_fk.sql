-- ============================================================
-- Fix: chat_sessions FK references auth.users instead of public.users
-- ============================================================
-- The chat_sessions.user_id FK was incorrectly set to auth.users(id),
-- but application users live in public.users. This migration drops
-- the bad constraint and re-adds it pointing to the correct table.

-- Step 1: Drop the old (wrong) FK constraint
-- First we need to find the constraint name (Supabase auto-names it)
DO $$
DECLARE
    cons_name TEXT;
BEGIN
    SELECT conname INTO cons_name
    FROM pg_constraint
    WHERE conrelid = 'public.chat_sessions'::regclass
      AND confrelid = 'auth.users'::regclass;
    IF cons_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE chat_sessions DROP CONSTRAINT %I', cons_name);
        RAISE NOTICE 'Dropped constraint: %', cons_name;
    ELSE
        RAISE NOTICE 'No auth.users FK constraint found on chat_sessions (may already be fixed)';
    END IF;
END;
$$;

-- Step 2: Re-add the FK pointing to public.users
-- This is idempotent (uses IF NOT EXISTS for the constraint name)
DO $$
BEGIN
    ALTER TABLE chat_sessions
        ADD CONSTRAINT chat_sessions_user_id_public_users_fkey
        FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;
    RAISE NOTICE 'Added FK constraint: chat_sessions_user_id_public_users_fkey';
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'FK constraint already exists, skipping';
END;
$$;
