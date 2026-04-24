"""
Multi-Agent Chat Schemas — 多 Agent 协作问答系统的数据模型。

定义：
  - Intent: 意图枚举
  - RouteDecision: Supervisor 路由决策
  - MultiAgentChatEvent: SSE 事件（支持多 Agent 协作场景）
  - AgentResponse: 各 Agent 的通用响应格式
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel

from .chat import RAGSource


# ─── Intent 分类 ──────────────────────────────────────────────────────────────


class Intent(str, Enum):
    """用户问题的意图分类（由 Supervisor Agent 判定）。"""

    KNOWLEDGE = "knowledge"      # 知识库问答（GitIntel 分析经验、技术建议）
    CODE = "code"               # 代码相关问题（具体代码片段、算法、调试）
    ANALYSIS = "analysis"        # 分析结果查询（查看已有分析的结论）
    GENERAL = "general"         # 通用问题（闲聊、使用说明、项目无关问题）
    MIXED = "mixed"             # 混合意图（需要多个 Agent 协作回答）


# ─── Route Decision ────────────────────────────────────────────────────────────


class RouteDecision(BaseModel):
    """Supervisor Agent 的路由决策。"""

    intent: Intent
    confidence: float          # 置信度 0.0~1.0
    reason: str               # 判定理由
    primary_agent: str        # 主要负责的 Agent 名称
    secondary_agent: Optional[str] = None  # 辅助 Agent（mixed 场景）
    context_hints: dict[str, Any] = {}     # 传递给 Agent 的额外上下文


# ─── Multi-Agent Chat Events (SSE) ───────────────────────────────────────────


class MultiAgentChatEvent(BaseModel):
    """多 Agent 协作 SSE 事件格式。

    与原有的单一 Agent SSE 格式完全兼容，新增字段：
      - agent_name: 实际处理当前事件的 Agent
      - supervisor_reason: Supervisor 的路由判定理由（仅 route 事件）
      - sources: RAG 检索结果（仅首次 sources 事件）
    """

    type: str                               # "route" | "sources" | "token" | "error" | "done"
    agent: str                              # "supervisor" | "knowledge" | "code" | "analysis" | "general"
    agent_name: str                         # 当前事件来源的 Agent 名称
    message: Optional[str] = None           # 状态消息
    delta: Optional[str] = None            # 增量文本（token 事件）
    full_text: Optional[str] = None        # 截止目前的完整回答
    percent: Optional[int] = None          # 进度 0~100
    data: Optional[dict[str, Any]] = None   # 附加数据（route / done 事件）
    sources: Optional[list[RAGSource]] = None  # RAG 检索结果
    supervisor_reason: Optional[str] = None # Supervisor 判定理由（route 事件）
    confidence: Optional[float] = None     # 置信度（route 事件）

    model_config = {"arbitrary_types_allowed": True}

    def to_sse_dict(self) -> dict[str, Any]:
        """转换为 SSE JSON 字典（去除 None 字段）。"""
        out = {"type": self.type, "agent": self.agent, "agent_name": self.agent_name}
        if self.message is not None:
            out["message"] = self.message
        if self.delta is not None:
            out["delta"] = self.delta
        if self.full_text is not None:
            out["full_text"] = self.full_text
        if self.percent is not None:
            out["percent"] = self.percent
        if self.data is not None:
            out["data"] = self.data
        if self.sources is not None:
            out["sources"] = [s.model_dump(mode="json") if hasattr(s, "model_dump") else s for s in self.sources]
        if self.supervisor_reason is not None:
            out["supervisor_reason"] = self.supervisor_reason
        if self.confidence is not None:
            out["confidence"] = self.confidence
        return out


# ─── Agent Response ────────────────────────────────────────────────────────────


class AgentResponse(BaseModel):
    """各 Agent 的统一响应格式。"""

    answer: str
    agent_name: str
    sources: list[RAGSource] = []
    extra_data: dict[str, Any] = {}   # Agent 特有的附加数据
    used_knowledge: bool = False     # 是否使用了知识库检索


# ─── Conversation Context ───────────────────────────────────────────────────────


class ConversationContext(BaseModel):
    """跨 Agent 共享的对话上下文（用于多轮对话）。"""

    session_id: str
    user_id: Optional[str] = None
    history: list[dict[str, str]] = []  # [{"role": "user", "content": "..."}, ...]
    current_repo_url: Optional[str] = None  # 当前会话关联的仓库 URL
    recent_intents: list[Intent] = []     # 最近几次的意图记录
    analysis_results_cache: dict[str, Any] = {}  # 已加载的分析结果缓存

    model_config = {"arbitrary_types_allowed": True}
