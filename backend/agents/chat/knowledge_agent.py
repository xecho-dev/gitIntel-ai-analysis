"""
KnowledgeAgent — 知识库问答 Agent。

职责：回答关于 GitIntel 分析经验、最佳实践、技术建议类问题。
"""

import logging
from typing import AsyncGenerator

from schemas.chat import RAGSource
from schemas.multi_agent import AgentResponse
from utils.llm_factory import get_llm_with_tracking

from .base_chat_agent import ChatAgent

_logger = logging.getLogger("gitintel")


class KnowledgeAgent(ChatAgent):
    """知识库问答 Agent。"""

    name = "knowledge"
    intent_targets = ["knowledge"]

    system_prompt_suffix = """
## KnowledgeAgent 专业能力

你专注于 GitIntel 知识库中的分析经验、最佳实践和技术建议。

你的专长：
1. 解读 GitIntel 分析结果中的优化建议和经验教训
2. 对比不同技术栈、规模的项目的分析结论
3. 给出架构设计、质量改进、依赖管理的通用建议
4. 结合具体案例（从知识库中）说明最佳实践

回答风格：
- 先给出核心结论
- 再引用 1-2 个具体案例
- 最后给出可操作的建议
- 保持专业但易懂，避免过度技术术语
"""

    def get_system_prompt(self) -> str:
        return self.COMMON_SYSTEM_PROMPT.strip() + "\n\n" + self.system_prompt_suffix.strip()

    def answer(
        self,
        question: str,
        context_docs: list[RAGSource] | None = None,
        history: list[dict] | None = None,
        **kwargs,
    ) -> AgentResponse:
        docs = context_docs or []
        messages = self._build_messages(question, docs, history or [])
        answer_text = self._call_llm(messages, temperature=0.3)
        return AgentResponse(
            answer=answer_text,
            agent_name=self.name,
            sources=docs,
            used_knowledge=len(docs) > 0,
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

        llm = get_llm_with_tracking(agent_name=self.name, temperature=0.3)
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
            _logger.error(f"[KnowledgeAgent] LLM 流式调用失败: {exc}")
            yield ("抱歉，回答生成过程中出现错误。", [], full_text)
            return

        yield ("", [], full_text)
