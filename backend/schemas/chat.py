from datetime import datetime
from typing import Optional, Any
from uuid import UUID
from pydantic import BaseModel, field_validator


def _normalize_str(v: Any) -> str:
    if isinstance(v, UUID):
        return str(v)
    if v is None:
        return ""
    return str(v)


def _normalize_int(v: Any) -> int:
    if v is None:
        return 0
    return int(v)


# ─── Chat Sessions ───────────────────────────────────────────────────────────

class ChatSession(BaseModel):
    id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str

    @field_validator("id", "user_id", mode="before")
    @classmethod
    def _str(cls, v):
        return _normalize_str(v)

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _dt(cls, v):
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v) if v else ""


class CreateSessionRequest(BaseModel):
    title: Optional[str] = None


class CreateSessionResponse(BaseModel):
    id: str
    title: str
    created_at: str

    @field_validator("id", mode="before")
    @classmethod
    def _str(cls, v):
        return _normalize_str(v)

    @field_validator("created_at", mode="before")
    @classmethod
    def _dt(cls, v):
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v) if v else ""


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

    @field_validator("id", "session_id", "analysis_id", mode="before")
    @classmethod
    def _str(cls, v):
        return _normalize_str(v)

    @field_validator("created_at", mode="before")
    @classmethod
    def _dt(cls, v):
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v) if v else ""


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
