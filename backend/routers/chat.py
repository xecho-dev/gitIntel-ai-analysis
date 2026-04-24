"""
Chat 相关路由 (/api/chat)
RAG 问答功能（SSE 流式）
"""
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from dependencies import get_auth_user_id, get_sb_client
from schemas.chat import SendMessageRequest, CreateSessionRequest
from services.rag_chat_service import rag_chat_stream
from services.database import (
    create_chat_session,
    get_chat_sessions,
    get_chat_messages,
    save_chat_message,
    delete_chat_session,
    get_session_owner,
    get_user_uuid,
)

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
    发送消息，SSE 流式返回 LLM 逐字输出。

    前端需要使用 EventSource 或 fetch + ReadableStream 消费此端点。
    """
    auth_user_id = get_auth_user_id(request)
    sb = get_sb_client()

    # 权限校验
    owner = get_session_owner(sb, body.session_id)
    user_uuid = get_user_uuid(sb, auth_user_id)
    if not owner or str(owner) != str(user_uuid):
        raise HTTPException(status_code=403, detail="无权限访问此会话")

    # 保存用户消息
    save_chat_message(sb, body.session_id, "user", body.content)

    collected_answer = ""
    collected_sources: list = []
    assistant_msg_id: str | None = None

    async def event_stream() -> AsyncGenerator[str, None]:
        nonlocal collected_answer, collected_sources, assistant_msg_id

        # 先发连接建立事件
        yield "data: {\"type\": \"connected\", \"agent\": \"rag_chat\", \"message\": \"正在思考...\", \"percent\": 0}\n\n"

        try:
            first_yield = True
            async for delta, sources, full_text in rag_chat_stream(body.content):
                if first_yield and sources:
                    collected_sources = sources
                    sources_data = [s.model_dump(mode="json") for s in sources]
                    yield f"data: {json.dumps({'type': 'sources', 'agent': 'rag_chat', 'sources': sources_data})}\n\n"
                    first_yield = False

                if delta:
                    collected_answer = full_text
                    yield f"data: {json.dumps({'type': 'token', 'agent': 'rag_chat', 'delta': delta, 'full_text': full_text})}\n\n"
        except Exception as exc:
            logger.error(f"[/api/chat/send] RAG 流异常: {exc}")
            yield f"data: {json.dumps({'type': 'error', 'agent': 'rag_chat', 'message': str(exc)})}\n\n"

        # 流结束，保存 Assistant 消息
        if collected_answer:
            try:
                assistant_msg = save_chat_message(
                    sb, body.session_id, "assistant", collected_answer,
                    rag_context=[s.model_dump(mode="json") for s in collected_sources],
                )
                assistant_msg_id = str(assistant_msg.id)
            except Exception as save_err:
                logger.error(f"[/api/chat/send] 保存消息失败: {save_err}")

        yield f"data: {json.dumps({
            'type': 'done',
            'agent': 'rag_chat',
            'message_id': assistant_msg_id,
            'answer': collected_answer,
            'sources': [s.model_dump(mode="json") for s in collected_sources]
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
