"""
Chat 相关路由 (/api/chat)
Multi-Agent 协作问答（SSE 流式）
"""
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from dependencies import get_auth_user_id, get_sb_client
from schemas.chat import SendMessageRequest, CreateSessionRequest
from agents.chat import multi_agent_chat_stream
from services.database import (
    create_chat_session,
    get_chat_sessions,
    get_chat_messages,
    save_chat_message,
    delete_chat_session,
    get_session_owner,
    get_user_uuid,
)


def _format_history(messages: list) -> list[dict]:
    """将数据库消息记录格式化为 Agent 所需的 history 列表。

    仅保留最近 MAX_HISTORY_MESSAGES 条，兼顾多轮记忆与上下文大小控制。
    """
    MAX_HISTORY_MESSAGES = 10  # 约 5 轮对话（user + assistant），足够覆盖追问场景
    return [
        {"role": m.role, "content": m.content}
        for m in messages
        if m.role in ("user", "assistant") and m.content
    ][-MAX_HISTORY_MESSAGES:]

logger = logging.getLogger("gitintel")
router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/sessions", response_model=dict)
async def api_create_chat_session(body: CreateSessionRequest, request: Request):
    """创建新的 Chat Session。"""
    auth_user_id = get_auth_user_id(request)
    sb = get_sb_client()

    user_uuid = get_user_uuid(sb, auth_user_id)
    if not user_uuid:
        raise HTTPException(status_code=400, detail="用户未完善 GitHub 资料，请先访问账户页")

    session = create_chat_session(sb, str(user_uuid), body.title)
    return {
        "id": session.id,
        "title": session.title,
        "created_at": session.created_at,
    }


@router.get("/sessions", response_model=dict)
async def api_list_chat_sessions(request: Request):
    """获取当前用户所有 Chat Sessions。"""
    auth_user_id = get_auth_user_id(request)
    sb = get_sb_client()

    user_uuid = get_user_uuid(sb, auth_user_id)
    if not user_uuid:
        return {"items": [], "total": 0}

    sessions = get_chat_sessions(sb, str(user_uuid))
    return {
        "items": [
            {"id": s.id, "title": s.title, "created_at": s.created_at, "updated_at": s.updated_at}
            for s in sessions
        ],
        "total": len(sessions),
    }


@router.get("/sessions/{session_id}/messages", response_model=dict)
async def api_get_chat_messages(session_id: str, request: Request):
    """获取某个 Session 的所有消息。"""
    auth_user_id = get_auth_user_id(request)
    sb = get_sb_client()

    owner = get_session_owner(sb, session_id)
    user_uuid = get_user_uuid(sb, auth_user_id)
    if not owner or str(owner) != str(user_uuid):
        raise HTTPException(status_code=403, detail="无权限访问此会话")

    messages = get_chat_messages(sb, session_id)
    return {"items": [m.model_dump(mode="json") for m in messages]}


@router.post("/send")
async def api_send_message(body: SendMessageRequest, request: Request):
    """
    发送消息，SSE 流式返回 Multi-Agent 协作回答。

    流程：
      1. Supervisor 意图分类 + 路由决策
      2. 分发到最合适的专业 Agent（Knowledge / Code / Analysis / General）
      3. 支持混合意图多 Agent 协作

    SSE 事件类型：
      - connected: 连接建立
      - route: 路由决策（Supervisor 判定意图）
      - sources: RAG 检索结果
      - token: LLM 增量输出
      - error: 异常
      - done: 回答完成
    """
    auth_user_id = get_auth_user_id(request)
    sb = get_sb_client()

    owner = get_session_owner(sb, body.session_id)
    user_uuid = get_user_uuid(sb, auth_user_id)
    if not owner or str(owner) != str(user_uuid):
        raise HTTPException(status_code=403, detail="无权限访问此会话")

    save_chat_message(sb, body.session_id, "user", body.content)

    # 加载历史消息，传入 Agent 以实现对话记忆
    past_messages = get_chat_messages(sb, body.session_id)
    history = _format_history(past_messages)

    collected_answer = ""
    collected_sources: list = []
    assistant_msg_id: str | None = None

    async def event_stream() -> AsyncGenerator[str, None]:
        nonlocal collected_answer, collected_sources, assistant_msg_id

        yield "data: {\"type\": \"connected\", \"agent\": \"supervisor\", \"message\": \"正在分析问题...\", \"percent\": 0}\n\n"

        try:
            async for raw_json in multi_agent_chat_stream(body.content, history=history):
                # 统一加 data: 前缀后转发给客户端
                yield f"data: {raw_json}\n\n"

                # 解析 answer / sources（raw_json 已是纯 JSON 字符串）
                if raw_json == "[DONE]":
                    continue
                try:
                    import json as _json
                    data = _json.loads(raw_json)
                    t = data.get("type", "")
                    if t == "sources":
                        collected_sources = data.get("sources", [])
                    elif t in ("token", "done"):
                        # 优先从顶层 answer/full_text 取，否则从 data.final_answer 取
                        ans = data.get("answer") or data.get("full_text") or ""
                        if not ans and isinstance(data.get("data"), dict):
                            ans = data["data"].get("final_answer", "")
                        if ans:
                            collected_answer = ans
                except Exception:
                    pass

        except Exception as exc:
            logger.error(f"[/api/chat/send] Multi-Agent 流异常: {exc}")
            yield f"data: {json.dumps({'type': 'error', 'agent': 'supervisor', 'message': str(exc)})}\n\n"

        # 保存 Assistant 消息
        if collected_answer:
            try:
                assistant_msg = save_chat_message(
                    sb, body.session_id, "assistant", collected_answer,
                    rag_context=collected_sources,
                )
                assistant_msg_id = str(assistant_msg.id)
            except Exception as save_err:
                logger.error(f"[/api/chat/send] 保存消息失败: {save_err}")

        yield f"data: {json.dumps({
            'type': 'done',
            'agent': 'multi_agent',
            'message_id': assistant_msg_id,
            'answer': collected_answer,
            'sources': collected_sources
        })}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/sessions/{session_id}", response_model=dict)
async def api_delete_chat_session(session_id: str, request: Request):
    """删除一个 Chat Session。"""
    auth_user_id = get_auth_user_id(request)
    sb = get_sb_client()

    user_uuid = get_user_uuid(sb, auth_user_id)
    if not user_uuid:
        raise HTTPException(status_code=400, detail="用户未完善 GitHub 资料")

    ok = delete_chat_session(sb, session_id, str(user_uuid))
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在或无权限删除")
    return {"deleted": True}
