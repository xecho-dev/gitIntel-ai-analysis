"""
ChatAgent 基类 — 多 Agent 协作系统中各专业 Agent 的统一基类。

设计原则：
  - 统一消息格式
  - 每个 Agent 实现 answer() 同步方法（返回文本 + RAGSource）
  - 每个 Agent 实现 answer_stream() 异步流式方法（用于 SSE）
  - Supervisor 通过路由决策将 question 分发给对应 Agent
"""

import logging
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from schemas.chat import RAGSource
from schemas.multi_agent import AgentResponse
from utils.llm_factory import get_llm_with_tracking

_logger = logging.getLogger("gitintel")


class ChatAgent(ABC):
    """多 Agent 协作系统中专业 Agent 的基类。"""

    name: str                       # Agent 唯一标识
    intent_targets: list[str] = []  # 该 Agent 负责处理的意图列表

    COMMON_SYSTEM_PROMPT = """你是一个专业的代码分析与架构优化助手，基于 GitIntel 的分析知识库回答用户问题。

你的知识来自 GitIntel 对 GitHub 仓库的深度分析，包括架构拓扑、代码质量、依赖风险、优化建议等洞察。

回答规则：
1. 优先基于检索到的知识库内容回答；如果没有相关内容，坦诚告知用户
2. 结合代码分析场景，用专业但易懂的语言解释
3. 可以引用具体的分析建议和改进方向
4. 保持简洁，突出关键信息
"""

    @abstractmethod
    def answer(
        self,
        question: str,
        context_docs: list[RAGSource] | None = None,
        history: list[dict] | None = None,
        **kwargs,
    ) -> AgentResponse:
        """同步回答（返回文本 + RAGSource）。"""
        ...

    @abstractmethod
    async def answer_stream(
        self,
        question: str,
        context_docs: list[RAGSource] | None = None,
        history: list[dict] | None = None,
        **kwargs,
    ) -> AsyncGenerator[tuple[str, list[RAGSource], str], None]:
        """异步流式回答，yield (delta_text, rag_sources, full_text)。

        - delta_text: 本次新增的文本片段
        - rag_sources: 检索到的源文档（只在首次 yield 时非空）
        - full_text: 截止目前的完整回答

        流结束后，最后一次 yield 以 delta_text == "" 表示结束。
        """
        ...

    def get_system_prompt(self) -> str:
        """生成该 Agent 的完整 system prompt。"""
        return self.COMMON_SYSTEM_PROMPT.strip()

    def _build_messages(
        self,
        question: str,
        context_docs: list[RAGSource],
        history: list[dict],
        extra_system: str = "",
    ) -> list:
        """组装 LangChain 消息列表。"""
        from langchain_core.messages import HumanMessage, SystemMessage

        system_content = self.get_system_prompt()
        if extra_system:
            system_content += f"\n\n{extra_system.strip()}"

        if context_docs:
            context_blocks = []
            for i, doc in enumerate(context_docs, 1):
                context_blocks.append(
                    f"[知识文档 {i}] 来自 {doc.repo_url}（{doc.category}）\n"
                    f"标题：{doc.title}\n内容：{doc.content}"
                )
            context_text = "\n\n".join(context_blocks)
            system_content += f"\n\n---\n参考知识库文档：\n{context_text}\n---"

        messages = [SystemMessage(content=system_content)]

        for turn in history[-6:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=f"用户：{content}"))
            else:
                messages.append(SystemMessage(content=f"助手：{content}"))

        messages.append(HumanMessage(content=f"用户问题：{question}"))
        return messages

    def retrieve_knowledge(
        self,
        question: str,
        top_k: int = 5,
        category: str | None = None,
    ) -> tuple[list[RAGSource], list[dict]]:
        """封装 DashVector RAG 检索，返回 (sources, raw_results)。"""
        from memory.dashvector_store import DashVectorStore

        store = DashVectorStore()
        if not store.is_available:
            _logger.warning(f"[{self.name}] DashVector 不可用，跳过知识检索")
            return [], []

        raw = store.retrieve_similar(question, top_k=top_k, category=category)

        sources = [
            RAGSource(
                repo_url=r.repo_url,
                category=r.category,
                title=r.title,
                content=r.content,
                score=r.score,
                priority=r.priority,
            )
            for r in raw
        ]

        raw_dicts = [
            {
                "repo_url": r.repo_url,
                "category": r.category,
                "title": r.title,
                "content": r.content,
                "score": r.score,
                "priority": r.priority,
                "code_fix": getattr(r, "code_fix", {}),
                "tech_stack": getattr(r, "tech_stack", []),
                "languages": getattr(r, "languages", []),
                "issue_type": getattr(r, "issue_type", ""),
            }
            for r in raw
        ]

        _logger.info(f"[{self.name}] RAG 检索到 {len(sources)} 条文档")
        return sources, raw_dicts

    def _call_llm(self, messages: list, temperature: float = 0.3) -> str:
        """同步调用 LLM，返回文本。"""
        llm = get_llm_with_tracking(agent_name=self.name, temperature=temperature)
        if llm is None:
            return "抱歉，AI 服务暂时不可用。"

        try:
            response = llm.ainvoke(messages)
            return response.content if hasattr(response, "content") else str(response)
        except Exception as exc:
            _logger.error(f"[{self.name}] LLM 调用失败: {exc}")
            return "抱歉，回答生成过程中出现错误。"
