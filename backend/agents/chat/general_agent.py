"""
GeneralAgent — 通用问题 Agent。

职责：回答闲聊、使用说明、项目无关的通用问题。
"""

import logging
from typing import AsyncGenerator

from schemas.chat import RAGSource
from schemas.multi_agent import AgentResponse
from utils.llm_factory import get_llm_with_tracking

from .base_chat_agent import ChatAgent

_logger = logging.getLogger("gitintel")

GENERAL_AGENT_PROMPT = """
## GeneralAgent 专业能力

你是一个友好、专业的 AI 助手，回答 GitIntel 平台相关的通用问题。

你的专长：
1. 介绍 GitIntel 功能和使用方法
2. 回答平台使用相关问题
3. 提供一般性的代码分析和架构设计建议
4. 处理闲聊和用户问候

回答风格：
- 友好、简洁，专业
- 避免过度使用技术术语
- 积极引导用户使用 GitIntel 的核心功能
- 如用户询问具体分析功能，引导其发起仓库分析

关于 GitIntel：
- GitIntel 是一个 GitHub 仓库智能分析平台
- 支持架构分析、代码质量评估、依赖风险检测、优化建议生成
- 基于 AI 深度分析代码库，生成可操作的改进建议
- 用户只需提供一个 GitHub 仓库 URL，即可获得完整的分析报告
"""


class GeneralAgent(ChatAgent):
    """通用问题 Agent。"""

    name = "general"
    intent_targets = ["general"]

    def get_system_prompt(self) -> str:
        return self.COMMON_SYSTEM_PROMPT.strip() + "\n\n" + GENERAL_AGENT_PROMPT.strip()

    def answer(
        self,
        question: str,
        context_docs: list[RAGSource] | None = None,
        history: list[dict] | None = None,
        **kwargs,
    ) -> AgentResponse:
        docs = context_docs or []
        messages = self._build_messages(question, docs, history or [])
        answer_text = self._call_llm(messages, temperature=0.5)
        return AgentResponse(
            answer=answer_text,
            agent_name=self.name,
            sources=docs,
            used_knowledge=False,
        )

    async def answer_stream(
        self,
        question: str,
        context_docs: list[RAGSource] | None = None,
        history: list[dict] | None = None,
        **kwargs,
    ) -> AsyncGenerator[tuple[str, list[RAGSource], str], None]:
        docs = context_docs or []
        yield ("", docs, "")

        messages = self._build_messages(question, docs, history or [])

        llm = get_llm_with_tracking(agent_name=self.name, temperature=0.5)
        if llm is None:
            yield ("抱歉，AI 服务暂时不可用。", [], "抱歉，AI 服务暂时不可用。")
            return

        full_text = ""
        try:
            async for chunk in llm.astream(messages):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                full_text += token
                yield (token, [], full_text)
        except Exception as exc:
            _logger.error(f"[GeneralAgent] LLM 流式调用失败: {exc}")
            yield ("抱歉，回答生成过程中出现错误。", [], full_text)
            return

        yield ("", [], full_text)
