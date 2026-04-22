-- ============================================================
-- GitIntel Chat History Migration
-- ============================================================
-- 创建时间: 2026-04-21
-- 说明: Chat 知识库问答的历史消息记录表

-- 启用 UUID 扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── chat_sessions ──────────────────────────────────────────────
-- 用户的每次对话（Session），聚合多个消息

CREATE TABLE IF NOT EXISTS chat_sessions (
    id          UUID        DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id     UUID        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    title       TEXT        DEFAULT '新对话',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- RLS
ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "chat_sessions: 用户只能操作自己的 session"
    ON chat_sessions
    FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- 索引
CREATE INDEX IF NOT EXISTS chat_sessions_user_id_idx ON chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS chat_sessions_created_at_idx ON chat_sessions(created_at DESC);


-- ── chat_messages ──────────────────────────────────────────────
-- 每条消息记录（User 或 Assistant）

CREATE TABLE IF NOT EXISTS chat_messages (
    id              UUID        DEFAULT uuid_generate_v4() PRIMARY KEY,
    session_id      UUID        NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role            TEXT        NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content         TEXT        NOT NULL,
    -- 可选：引用哪些 RAG 知识库文档（JSON 数组，存储 SearchResult 摘要）
    rag_context     JSONB       DEFAULT NULL,
    -- 可选：关联的分析历史记录 ID（FK 到 analysis_history）
    analysis_id     UUID        DEFAULT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- RLS
ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "chat_messages: 用户只能操作自己的消息"
    ON chat_messages
    FOR ALL
    USING (
        auth.uid() = (
            SELECT user_id FROM chat_sessions WHERE id = chat_messages.session_id
        )
    )
    WITH CHECK (
        auth.uid() = (
            SELECT user_id FROM chat_sessions WHERE id = chat_messages.session_id
        )
    );

-- 索引
CREATE INDEX IF NOT EXISTS chat_messages_session_id_idx ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS chat_messages_created_at_idx ON chat_messages(created_at);


-- ── 更新 chat_sessions.updated_at 触发器 ─────────────────────────

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_chat_sessions_updated_at
    BEFORE UPDATE ON chat_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
