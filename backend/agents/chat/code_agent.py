"""
CodeAgent — 代码相关问题 Agent。

职责：回答关于代码片段、算法、调试、代码优化等具体代码相关问题。
"""

import logging
import re
from typing import AsyncGenerator

from schemas.chat import RAGSource
from schemas.multi_agent import AgentResponse
from utils.llm_factory import get_llm_with_tracking

from .base_chat_agent import ChatAgent

_logger = logging.getLogger("gitintel")

CODE_AGENT_PROMPT = """
## CodeAgent 专业能力

你专注于代码相关的深度分析，包括：
1. 代码结构与逻辑解读
2. 时间复杂度 / 空间复杂度分析
3. 代码问题诊断与调试建议
4. 代码优化与重构建议
5. 特定代码模式（设计模式、并发、异步等）的最佳实践

你接收到的 question 可能包含用户粘贴的代码片段。请：
1. 先分析代码的结构和意图
2. 指出潜在问题（如果有）
3. 提供优化建议
4. 如有必要，给出修改后的代码示例

注意：如果用户粘贴了具体代码，请针对该代码分析，不要凭空编造。
"""


class CodeAgent(ChatAgent):
    """代码相关问题 Agent。"""

    name = "code"
    intent_targets = ["code"]

    def get_system_prompt(self) -> str:
        return self.COMMON_SYSTEM_PROMPT.strip() + "\n\n" + CODE_AGENT_PROMPT.strip()

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
            _logger.error(f"[CodeAgent] LLM 流式调用失败: {exc}")
            yield ("抱歉，回答生成过程中出现错误。", [], full_text)
            return

        yield ("", [], full_text)

    def extract_code_snippets(self, question: str) -> list[str]:
        """从问题中提取代码片段。"""
        patterns = [
            r"```[\w]*\n(.*?)```",
            r"`([^`]+)`",
            r"(def \w+.*?:.*?(?=\n\n|\Z))",
            r"(class \w+.*?:.*?(?=\n\n|\Z))",
            r"(function\s+\w+.*?\{.*?\})",
        ]
        snippets = []
        for pattern in patterns:
            matches = re.findall(pattern, question, re.DOTALL | re.MULTILINE)
            snippets.extend([m.strip() for m in matches if len(m.strip()) > 20])
        return snippets
