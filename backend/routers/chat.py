"""
Chat 相关路由 (/api/chat)
标准 RAG Pipeline（SSE 流式）
"""
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from dependencies import get_auth_user_id, get_db
from schemas.chat import SendMessageRequest, CreateSessionRequest
from rag import RAGPipeline
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
    pool = await get_db()

    user_uuid = await get_user_uuid(pool, auth_user_id)
    if not user_uuid:
        raise HTTPException(status_code=400, detail="用户未完善 GitHub 资料，请先访问账户页")

    session = await create_chat_session(pool, str(user_uuid), body.title)
    return {
        "id": session.id,
        "title": session.title,
        "created_at": session.created_at,
    }


@router.get("/sessions", response_model=dict)
async def api_list_chat_sessions(request: Request):
    """获取当前用户所有 Chat Sessions。"""
    auth_user_id = get_auth_user_id(request)
    pool = await get_db()

    user_uuid = await get_user_uuid(pool, auth_user_id)
    if not user_uuid:
        return {"items": [], "total": 0}

    sessions = await get_chat_sessions(pool, str(user_uuid))
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
    pool = await get_db()

    owner = await get_session_owner(pool, session_id)
    user_uuid = await get_user_uuid(pool, auth_user_id)
    if not owner or str(owner) != str(user_uuid):
        raise HTTPException(status_code=403, detail="无权限访问此会话")

    messages = await get_chat_messages(pool, session_id)
    return {"items": [m.model_dump(mode="json") for m in messages]}


@router.post("/send")
async def api_send_message(body: SendMessageRequest, request: Request):
    """
    发送消息，SSE 流式返回标准 RAG Pipeline 回答。

    流程（Query → Retrieval → Context → Generate → Post-Process）：
      1. Query Processing：意图分类、关键词提取、查询扩展
      2. Retrieval：多策略检索（向量 + 关键词 + RRF 融合）
      3. Context Processing：过滤、去重、Token 预算控制
      4. LLM Streaming Generation：意图感知的流式生成
      5. Post-Processing：引用提取、质量评估

    SSE 事件类型：
      - route: 查询处理完成（意图、关键词）
      - retrieving: 正在检索
      - sources: 检索结果
      - generating: 开始生成
      - token: LLM 增量输出
      - done: 回答完成
      - error: 异常
    """
    auth_user_id = get_auth_user_id(request)
    pool = await get_db()

    owner = await get_session_owner(pool, body.session_id)
    user_uuid = await get_user_uuid(pool, auth_user_id)
    if not owner or str(owner) != str(user_uuid):
        raise HTTPException(status_code=403, detail="无权限访问此会话")

    await save_chat_message(pool, body.session_id, "user", body.content)

    past_messages = await get_chat_messages(pool, body.session_id)

    collected_answer = ""
    collected_sources: list = []
    collected_intent = ""
    assistant_msg_id: str | None = None

    pipeline = RAGPipeline(
        session_id=body.session_id,
        user_id=auth_user_id,
        enable_ragas_eval=body.enable_eval,
        ragas_user_avatar=auth_user_id,
    )

    async def event_stream() -> AsyncGenerator[str, None]:
        nonlocal collected_answer, collected_sources, collected_intent, assistant_msg_id

        yield "data: {\"type\": \"connected\", \"message\": \"正在连接...\", \"percent\": 0}\n\n"

        try:
            async for event in pipeline.chat(body.content):
                if not event.startswith("data: "):
                    yield "data: " + event + "\n\n"
                else:
                    yield event

                if event.startswith("data: "):
                    raw = event[6:].strip()
                    if raw == "[DONE]":
                        continue
                    try:
                        data = json.loads(raw)
                        t = data.get("type", "")
                        if t == "done":
                            collected_answer = data.get("answer") or data.get("full_text") or ""
                            collected_sources = data.get("sources", [])
                            collected_intent = data.get("intent", "")
                        elif t == "token":
                            ans = data.get("full_text") or data.get("answer") or ""
                            if ans:
                                collected_answer = ans
                    except Exception:
                        pass

        except Exception as exc:
            logger.error(f"[/api/chat/send] RAG Pipeline 流异常: {exc}")
            import traceback
            logger.error(traceback.format_exc())
            yield "data: " + json.dumps({
                "type": "error",
                "message": f"处理异常: {str(exc)}",
            }, ensure_ascii=False) + "\n\n"

        if collected_answer:
            try:
                assistant_msg = await save_chat_message(
                    pool, body.session_id, "assistant", collected_answer,
                    rag_context=collected_sources,
                )
                assistant_msg_id = str(assistant_msg.id)
            except Exception as save_err:
                logger.error(f"[/api/chat/send] 保存消息失败: {save_err}")

        yield "data: " + json.dumps({
            "type": "done",
            "message_id": assistant_msg_id,
            "answer": collected_answer,
            "sources": collected_sources,
            "intent": collected_intent,
        }, ensure_ascii=False) + "\n\n"
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
    pool = await get_db()

    user_uuid = await get_user_uuid(pool, auth_user_id)
    if not user_uuid:
        raise HTTPException(status_code=400, detail="用户未完善 GitHub 资料")

    ok = await delete_chat_session(pool, session_id, str(user_uuid))
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在或无权限删除")
    return {"deleted": True}
