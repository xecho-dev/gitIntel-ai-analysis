-- ============================================================
-- Migration: Deduplicate users table + add unique constraint on login
-- Run this BEFORE deploying the code fix (to clean up existing duplicates)
-- ============================================================

-- Step 1: 找出所有 login 重复的记录
-- For each duplicate login, keep the row with the latest updated_at (or latest created_at as fallback)
-- and delete the rest.

-- 先查看有哪些 login 重复了
-- SELECT login, COUNT(*) as cnt FROM public.users GROUP BY login HAVING COUNT(*) > 1;

-- Step 2: 清理重复记录，保留每组中 updated_at 最新的一条
DELETE FROM public.users a
USING public.users b
WHERE a.login = b.login
  AND a.id != b.id
  AND (
      a.updated_at < b.updated_at
      OR (a.updated_at IS NULL AND b.updated_at IS NOT NULL)
      OR (a.updated_at IS NULL AND b.updated_at IS NULL AND a.created_at < b.created_at)
      OR (a.updated_at IS NULL AND b.created_at IS NULL)
  );

-- Step 3: 验证是否还有重复
-- SELECT login, COUNT(*) as cnt FROM public.users GROUP BY login HAVING COUNT(*) > 1;

-- Step 4: 添加唯一约束（清理完毕后才执行）
-- ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_login_key;
-- ALTER TABLE public.users ADD CONSTRAINT users_login_key UNIQUE (login);
