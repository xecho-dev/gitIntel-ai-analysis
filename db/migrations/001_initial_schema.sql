-- ============================================================
-- GitIntel PostgreSQL Schema (Native, no Supabase dependencies)
-- ============================================================

-- 1. UUID extension
create extension if not exists "uuid-ossp";

-- ============================================================
-- Table: users
-- GitHub OAuth 用户基本信息（从 NextAuth session 同步）
-- ============================================================
create table if not exists public.users (
    id              uuid primary key default uuid_generate_v4(),
    auth_user_id    text unique not null,
    github_id       text unique,
    login           text,
    email           text,
    avatar_url      text,
    name            text,
    bio             text,
    company         text,
    location        text,
    blog            text,
    public_repos    integer default 0,
    followers       integer default 0,
    following       integer default 0,
    created_at      timestamptz default now(),
    updated_at      timestamptz default now()
);

create index if not exists idx_users_auth_user_id on public.users(auth_user_id);
create index if not exists idx_users_github_id on public.users(github_id);

-- ============================================================
-- Table: analysis_history
-- 记录每次仓库分析的元数据
-- ============================================================
create table if not exists public.analysis_history (
    id                  uuid primary key default uuid_generate_v4(),
    user_id             uuid not null references public.users(id) on delete cascade,
    repo_url            text not null,
    repo_name           text not null,
    branch              text default 'main',
    repo_sha            text,
    health_score        numeric(5,2),
    quality_score       text,
    risk_level          text,
    risk_level_color    text,
    risk_level_bg       text,
    border_color        text,
    result_data         jsonb,
    langsmith_trace_id  text,
    thread_id           text,
    created_at          timestamptz default now()
);

create index if not exists idx_analysis_history_user_id
    on public.analysis_history(user_id, created_at desc);
create index if not exists idx_analysis_history_repo_cache
    on public.analysis_history(user_id, repo_url, branch, repo_sha);
create index if not exists idx_analysis_history_langsmith_trace_id
    on public.analysis_history(langsmith_trace_id);
create index if not exists idx_analysis_history_thread_id
    on public.analysis_history(thread_id);

-- ============================================================
-- Table: admin_users
-- Admin 门户账户（与 GitHub OAuth 用户分开，使用用户名+密码登录）
-- ============================================================
create table if not exists public.admin_users (
    id              uuid primary key default uuid_generate_v4(),
    username        text unique not null,
    password_hash   text not null,
    nickname        text,
    avatar          text,
    role            text not null default 'admin',
    is_active       boolean not null default true,
    last_login_at   timestamptz,
    created_at      timestamptz default now(),
    updated_at      timestamptz default now()
);

-- ============================================================
-- Table: admin_tokens
-- Admin 登录令牌（短生命周期）
-- ============================================================
create table if not exists public.admin_tokens (
    id              uuid primary key default uuid_generate_v4(),
    admin_user_id   uuid not null references public.admin_users(id) on delete cascade,
    token           text unique not null,
    expires_at      timestamptz not null,
    ip_address      text,
    user_agent      text,
    created_at      timestamptz default now()
);

create index if not exists idx_admin_tokens_token on public.admin_tokens(token);
create index if not exists idx_admin_tokens_expires on public.admin_tokens(expires_at);

-- 自动清理过期令牌
create or replace function public.cleanup_expired_admin_tokens()
returns void as $$
begin
    delete from public.admin_tokens where expires_at < now();
end;
$$ language plpgsql security definer;

-- ============================================================
-- Table: chat_sessions
-- 用户每次对话（Session）
-- ============================================================
create table if not exists public.chat_sessions (
    id          uuid primary key default uuid_generate_v4(),
    user_id     uuid not null references public.users(id) on delete cascade,
    title       text default '新对话',
    created_at  timestamptz default now(),
    updated_at  timestamptz default now()
);

create index if not exists idx_chat_sessions_user_id on public.chat_sessions(user_id);
create index if not exists idx_chat_sessions_created_at on public.chat_sessions(created_at desc);

-- 自动更新 updated_at
create or replace function update_chat_sessions_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

create trigger update_chat_sessions_updated_at
    before update on public.chat_sessions
    for each row execute function update_chat_sessions_updated_at();

-- ============================================================
-- Table: chat_messages
-- 每条对话消息（User 或 Assistant）
-- ============================================================
create table if not exists public.chat_messages (
    id              uuid primary key default uuid_generate_v4(),
    session_id      uuid not null references public.chat_sessions(id) on delete cascade,
    role            text not null check (role in ('user', 'assistant', 'system')),
    content         text not null,
    rag_context     jsonb,
    analysis_id     uuid references public.analysis_history(id) on delete set null,
    created_at      timestamptz default now()
);

create index if not exists idx_chat_messages_session_id on public.chat_messages(session_id);
create index if not exists idx_chat_messages_created_at on public.chat_messages(created_at asc);

-- ============================================================
-- Seed: 默认 Admin 账户
-- Username: admin
-- Password: gitintel2024
-- （bcrypt hash: $2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.R7GtLVe7.2G7Lu）
-- ============================================================
insert into public.admin_users (username, password_hash, nickname, role)
values (
    'admin',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.R7GtLVe7.2G7Lu',
    'Administrator',
    'super_admin'
) on conflict (username) do nothing;
