"""
Multi-Agent Router — 多 Agent 协作路由编排层。

**已迁移至 LangGraph 工作流（graph/chat_graph.py）。**

本模块保留作为兼容层，代理到新的 LangGraph 实现。
"""

import json
import logging
from typing import AsyncGenerator

from schemas.chat import RAGSource
from schemas.multi_agent import Intent, MultiAgentChatEvent, RouteDecision

from .analysis_agent import AnalysisAgent
from .base_chat_agent import ChatAgent
from .code_agent import CodeAgent
from .general_agent import GeneralAgent
from .knowledge_agent import KnowledgeAgent
from .supervisor_agent import SupervisorAgent

# 导入 LangGraph 实现（新逻辑）
# 注意：这里用延迟导入避免循环依赖，graph/chat_graph.py 不依赖 agents 层
import graph.chat_graph as _graph_chat_graph

_logger = logging.getLogger("gitintel")


class AgentRegistry:
    """专业 Agent 注册表（单例）。"""

    _instance: "AgentRegistry | None" = None

    def __init__(self):
        self._agents: dict[str, ChatAgent] = {
            "knowledge": KnowledgeAgent(),
            "code": CodeAgent(),
            "analysis": AnalysisAgent(),
            "general": GeneralAgent(),
        }

    @classmethod
    def get_instance(cls) -> "AgentRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get(self, name: str) -> ChatAgent | None:
        return self._agents.get(name)


class MultiAgentRouter:
    """多 Agent 路由编排器。"""

    def __init__(self):
        self.supervisor = SupervisorAgent()
        self.registry = AgentRegistry.get_instance()

    def classify(self, question: str, history: list[dict] | None = None) -> RouteDecision:
        """同步意图分类（快速路径）。"""
        return self.supervisor.classify(question, history)

    async def chat_stream(
        self,
        question: str,
        history: list[dict] | None = None,
        repo_url: str | None = None,
        analysis_cache: dict | None = None,
    ) -> AsyncGenerator[MultiAgentChatEvent, None]:
        """
        主入口：流式多 Agent 协作问答。

        流程：
          1. Supervisor 意图分类
          2. 主要 Agent 处理（如有需要，先做 RAG 预检索）
          3. 辅助 Agent 补充（mixed 场景）
          4. 流式 yield 事件
        """
        route: RouteDecision = self.classify(question, history)

        yield MultiAgentChatEvent(
            type="route",
            agent="supervisor",
            agent_name="supervisor",
            message=f"正在分析您的问题（{route.intent.value}）...",
            percent=5,
            data={
                "intent": route.intent.value,
                "confidence": route.confidence,
                "reason": route.reason,
                "primary_agent": route.primary_agent,
                "secondary_agent": route.secondary_agent,
            },
            supervisor_reason=route.reason,
            confidence=route.confidence,
        )

        _logger.info(
            f"[MultiAgentRouter] 路由决策: intent={route.intent.value}, "
            f"primary={route.primary_agent}, secondary={route.secondary_agent}"
        )

        primary_agent = self.registry.get(route.primary_agent)
        if primary_agent is None:
            _logger.warning(f"[MultiAgentRouter] Agent {route.primary_agent} 不存在，降级为 general")
            primary_agent = self.registry.get("general")

        preloaded_sources: list[RAGSource] = []
        if route.primary_agent in ("knowledge", "analysis") or route.secondary_agent in ("knowledge", "analysis"):
            preloaded_sources = await self._preload_knowledge(question, route)

        yield MultiAgentChatEvent(
            type="status",
            agent=route.primary_agent,
            agent_name=route.primary_agent,
            message=f"正在使用 {self._agent_display_name(route.primary_agent)} 分析您的问题...",
            percent=10,
        )

        secondary_answer = ""

        async for delta, sources, full_text in primary_agent.answer_stream(
            question=question,
            context_docs=preloaded_sources,
            history=history,
            repo_url=repo_url,
            analysis_cache=analysis_cache,
        ):
            if sources:
                yield MultiAgentChatEvent(
                    type="sources",
                    agent=route.primary_agent,
                    agent_name=route.primary_agent,
                    message="已检索相关知识",
                    sources=sources,
                    percent=15,
                )

            if delta:
                yield MultiAgentChatEvent(
                    type="token",
                    agent=route.primary_agent,
                    agent_name=route.primary_agent,
                    delta=delta,
                    full_text=full_text,
                )

        if route.secondary_agent and route.secondary_agent != route.primary_agent:
            secondary_agent = self.registry.get(route.secondary_agent)
            if secondary_agent:
                yield MultiAgentChatEvent(
                    type="status",
                    agent=route.secondary_agent,
                    agent_name=route.secondary_agent,
                    message=f"补充分析：{self._agent_display_name(route.secondary_agent)}...",
                    percent=85,
                )

                async for delta, _, full_text in secondary_agent.answer_stream(
                    question=question,
                    context_docs=preloaded_sources,
                    history=history,
                    repo_url=repo_url,
                    analysis_cache=analysis_cache,
                ):
                    if delta:
                        prefix = "\n\n" if not secondary_answer else ""
                        yield MultiAgentChatEvent(
                            type="token",
                            agent=route.secondary_agent,
                            agent_name=route.secondary_agent,
                            delta=f"{prefix}{delta}",
                            full_text=full_text,
                        )
                    secondary_answer = full_text

        yield MultiAgentChatEvent(
            type="done",
            agent=route.primary_agent,
            agent_name=route.primary_agent,
            message="回答完成",
            percent=100,
            data={
                "intent": route.intent.value,
                "primary_agent": route.primary_agent,
                "secondary_agent": route.secondary_agent,
                "used_knowledge": len(preloaded_sources) > 0,
            },
        )

    async def _preload_knowledge(
        self,
        question: str,
        route: RouteDecision,
    ) -> list[RAGSource]:
        """预加载 RAG 知识检索。"""
        category = None
        if route.context_hints:
            cats = route.context_hints.get("relevant_categories", [])
            if cats and isinstance(cats, list):
                category = cats[0] if cats else None

        try:
            from memory.dashvector_store import DashVectorStore
            store = DashVectorStore()
        except Exception as exc:
            _logger.warning(f"[MultiAgentRouter] DashVector 导入失败: {exc}")
            return []

        if store is None or not store.is_available:
            _logger.info("[MultiAgentRouter] DashVector 不可用，跳过预检索")
            return []

        try:
            docs = store.retrieve_similar(question, top_k=5, category=category)
            sources = [
                RAGSource(
                    repo_url=d.repo_url,
                    category=d.category,
                    title=d.title,
                    content=d.content,
                    score=d.score,
                    priority=d.priority,
                )
                for d in docs
            ]
            _logger.info(f"[MultiAgentRouter] 预检索到 {len(sources)} 条知识")
            return sources
        except Exception as exc:
            _logger.warning(f"[MultiAgentRouter] 预检索失败: {exc}")
            return []

    @staticmethod
    def _agent_display_name(name: str) -> str:
        names = {
            "knowledge": "知识库助手",
            "code": "代码分析助手",
            "analysis": "分析结果助手",
            "general": "通用助手",
            "supervisor": "问题分析",
        }
        return names.get(name, name)


async def multi_agent_chat_stream(
    question: str,
    history: list[dict] | None = None,
    repo_url: str | None = None,
    analysis_cache: dict | None = None,
) -> AsyncGenerator[str, None]:
    """
    主入口：yield SSE 格式字符串 "data: {...}\n\n"。

    委托给 graph/chat_graph.py 的 LangGraph 工作流实现。
    保留本函数作为兼容层，供 routers/chat.py 使用。
    """
    async for event_str in _langgraph_chat_stream(
        question=question,
        history=history,
        repo_url=repo_url,
        analysis_cache=analysis_cache,
    ):
        yield event_str

