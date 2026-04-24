"""
Chat 相关路由 (/api/chat)
RAG 问答功能
"""
from fastapi import APIRouter, Request, HTTPException

from dependencies import get_auth_user_id, get_sb_client
from schemas.chat import SendMessageRequest, CreateSessionRequest
from services.rag_chat_service import rag_chat as do_rag_chat
from services.database import (
    create_chat_session,
    get_chat_sessions,
    get_chat_messages,
    save_chat_message,
    delete_chat_session,
    get_session_owner,
    get_user_uuid,
)

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


@router.post("/send", response_model=dict)
async def api_send_message(body: SendMessageRequest, request: Request):
    """发送消息并获取 RAG 回答。"""
    auth_user_id = get_auth_user_id(request)
    sb = get_sb_client()

    # 权限校验
    owner = get_session_owner(sb, body.session_id)
    user_uuid = get_user_uuid(sb, auth_user_id)
    if not owner or str(owner) != str(user_uuid):
        raise HTTPException(status_code=403, detail="无权限访问此会话")

    # 1. 保存用户消息
    user_msg = save_chat_message(sb, body.session_id, "user", body.content)

    # 2. RAG 问答
    answer, rag_sources = do_rag_chat(body.content)

    # 3. 保存 Assistant 回答
    assistant_msg = save_chat_message(
        sb, body.session_id, "assistant", answer,
        rag_context=[s.model_dump(mode="json") for s in rag_sources],
    )

    return {
        "message": assistant_msg.model_dump(mode="json"),
        "answer": answer,
        "rag_sources": [s.model_dump(mode="json") for s in rag_sources],
    }


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
