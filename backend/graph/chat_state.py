"""
ChatState — LangGraph 聊天工作流的共享状态。

每个 Agent 节点都会读写这个状态，LangGraph 自动合并节点返回值。
"""

from typing import Annotated, Optional
from typing_extensions import TypedDict
from operator import add


class ChatState(TypedDict, total=False):
    # ─── 入口 ──────────────────────────────────────────────────────────────
    question: str                       # 用户原始问题
    repo_url: Optional[str]             # 仓库 URL（从问题中提取）
    history: list[dict]                 # 对话历史（最近 6 轮）

    # ─── 路由决策 ──────────────────────────────────────────────────────────
    primary_agent: str                  # 主 Agent 名称
    secondary_agent: Optional[str]      # 辅助 Agent（mixed 时）
    intent: str                         # 意图分类结果

    # ─── RAG / 知识库 ─────────────────────────────────────────────────────
    rag_results: list[dict]            # 检索到的知识文档
    rag_queried: bool                   # 是否已查询知识库

    # ─── 分析缓存 ──────────────────────────────────────────────────────────
    analysis_cache: Optional[dict]     # 已有分析结果（repo 级别）

    # ─── 各 Agent 的 ReAct 过程 ────────────────────────────────────────────
    # format: list of {"role": "user|assistant", "content": "..."}
    # 其中 assistant 消息包含 tool_calls / tool_results
    primary_messages: list[dict]
    secondary_messages: list[dict]

    # ─── Agent 执行追踪 ────────────────────────────────────────────────────
    primary_step: int                  # 主 Agent 当前步数
    secondary_step: int                # 辅 Agent 当前步数
    primary_done: bool                 # 主 Agent 是否已完成
    secondary_done: bool               # 辅 Agent 是否已完成
    primary_finished_agents: Annotated[list[str], add]   # 已完成的 Agent 节点
    secondary_finished_agents: Annotated[list[str], add]

    # ─── 最终输出 ──────────────────────────────────────────────────────────
    primary_answer: str                # 主 Agent 最终回答
    secondary_answer: str              # 辅 Agent 补充回答
    final_answer: str                  # 合并后的最终回答
    used_knowledge: bool               # 是否使用了知识库
    sources: list[dict]                # RAG 来源列表

    # ─── 错误 ──────────────────────────────────────────────────────────────
    errors: Annotated[list[str], add]

    # ─── 路由相位（控制工作流循环）────────────────────────────────────────
    phase: str              # "primary" | "secondary"
    routed_agents: list[str]  # 已路由过的 agent（防止重复执行）
