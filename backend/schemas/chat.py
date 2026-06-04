from typing import Optional
from pydantic import BaseModel


# ─── Chat Sessions ───────────────────────────────────────────────────────────


class ChatSession(BaseModel):
    id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str


class CreateSessionRequest(BaseModel):
    title: Optional[str] = None


class CreateSessionResponse(BaseModel):
    id: str
    title: str
    created_at: str


# ─── Chat Messages ──────────────────────────────────────────────────────────


class RAGSource(BaseModel):
    repo_url: str
    category: str
    title: str
    content: str
    score: float
    priority: str


class ChatMessage(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    rag_context: Optional[list[RAGSource]] = None
    analysis_id: Optional[str] = None
    created_at: str


class SendMessageRequest(BaseModel):
    session_id: str
    content: str
    enable_eval: bool = False  # 设为 True 时，对回复进行 RAGAS 评测


class SendMessageResponse(BaseModel):
    message: ChatMessage
    answer: str
    rag_sources: list[RAGSource]


# ─── Session List ───────────────────────────────────────────────────────────


class SessionListResponse(BaseModel):
    items: list[ChatSession]
    total: int
