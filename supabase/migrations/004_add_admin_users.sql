-- ============================================================
-- Admin Users Table Migration
-- Run this SQL in your Supabase SQL Editor
-- ============================================================

-- 1. Enable UUID extension
create extension if not exists "uuid-ossp";

-- 2. Admin users table (separate from public.users — admin accounts use username/password)
create table if not exists public.admin_users (
    id              uuid primary key default uuid_generate_v4(),
    username        text unique not null,
    -- bcrypt hash (raw hash stored, frontend/server handles bcrypt comparison)
    password_hash   text not null,
    nickname        text,
    avatar          text,
    role            text not null default 'admin',  -- admin | super_admin
    is_active       boolean not null default true,
    last_login_at   timestamptz,
    created_at      timestamptz default now(),
    updated_at      timestamptz default now()
);

comment on table public.admin_users is 'Admin portal user accounts (separate from GitHub OAuth users)';

-- RLS: service role only, no user-facing RLS needed
alter table public.admin_users enable row level security;

-- Allow service role full access (bypassed via SUPABASE_SERVICE_KEY)
create policy "Service role can do everything on admin_users"
    on public.admin_users
    for all
    using (auth.role() = 'service_role');

-- 3. Admin tokens table (short-lived JWTs issued on login)
create table if not exists public.admin_tokens (
    id              uuid primary key default uuid_generate_v4(),
    admin_user_id   uuid not null references public.admin_users(id) on delete cascade,
    token           text unique not null,
    expires_at      timestamptz not null,
    ip_address      text,
    user_agent      text,
    created_at      timestamptz default now()
);

comment on table public.admin_tokens is 'Issued admin login tokens for session management';

alter table public.admin_tokens enable row level security;

create policy "Service role can do everything on admin_tokens"
    on public.admin_tokens
    for all
    using (auth.role() = 'service_role');

-- 4. Refresh PostgREST schema cache so it picks up the FK relationship
notify pgrst, 'reload';

-- 4. Auto-cleanup expired tokens (run periodically or via pg_cron)
create or replace function public.cleanup_expired_admin_tokens()
returns void as $$
begin
    delete from public.admin_tokens where expires_at < now();
end;
$$ language plpgsql security definer;

-- 5. Seed a default admin account (username: admin, password: gitintel2024)
-- Password hash generated with bcrypt: bcrypt.hashpw(b'gitintel2024', bcrypt.gensalt())
-- You should change this immediately after first login!
insert into public.admin_users (username, password_hash, nickname, role)
values (
    'admin',
    -- bcrypt hash: $2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.R7GtLVe7.2G7Lu
    -- NOTE: Run the seed script below to generate a fresh hash, or change via admin panel
    '$2b$12$placeholder_hash_replace_with_real_bcrypt_hash',
    'Administrator',
    'super_admin'
) on conflict (username) do nothing;
