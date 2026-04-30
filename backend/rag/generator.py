"""
Generator — LLM 流式生成层。

职责：
  1. 根据意图选择合适的 System Prompt
  2. 构建完整的消息
  3. 调用 LLM 流式生成
  4. 实时返回 token
"""

import json
import logging
from typing import AsyncGenerator, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from utils.llm_factory import get_llm_with_tracking

_logger = logging.getLogger("gitintel")


# ─── System Prompts（根据意图选择）───────────────────────────────────────

SYSTEM_PROMPTS: dict[str, str] = {
    "factual": """你是 GitIntel 的知识库问答助手，专门帮助用户解答关于代码仓库分析的相关问题。

你的职责是基于提供的参考资料，准确、专业地回答用户问题。

回答规则：
1. 仅基于参考资料回答，不要编造信息
2. 如果参考资料不足以回答，明确说明
3. 引用时标注【1】【2】等来源编号
4. 保持客观、准确、简洁
5. 使用 markdown 格式化回答""",

    "analytical": """你是 GitIntel 的技术分析助手，专门帮助用户深入分析代码仓库的架构、质量和优化方向。

你的职责是结合参考资料，提供深入的技术洞见和分析。

回答规则：
1. 不仅描述"是什么"，更要分析"为什么"
2. 对比不同参考资料中的观点
3. 指出潜在问题和建议
4. 结构化输出，使用标题和列表
5. 适当引用参考资料【1】【2】等""",

    "conversational": """你是 GitIntel 的友好 AI 助手，专门帮助用户理解和分析代码仓库。

你的职责是结合参考资料，自然地回答用户问题，让交互更加友好和高效。

回答规则：
1. 口语化表达，友好亲切
2. 适当引用参考资料
3. 如果没有相关资料，用通用知识回答
4. 引导用户深入提问
5. 保持简洁有趣""",

    "code_related": """你是 GitIntel 的代码分析助手，专门帮助用户分析、理解和优化代码。

你的职责是分析用户关于代码的问题，提供专业的代码级建议。

回答规则：
1. 代码问题要给出具体的代码示例（使用 markdown 代码块）
2. 解释代码逻辑和原理
3. 指出潜在的 bug 和改进建议
4. 如果有具体的代码修复方案，优先展示
5. 使用 markdown 代码块格式化代码""",
}


# ─── 辅助 Prompts ──────────────────────────────────────────────────────

HISTORY_TEMPLATE = """【对话历史】
{history}
【历史结束】

"""

CONTEXT_HEADER = """【参考资料】
以下是与问题相关的参考资料，请结合这些内容回答。
"""


def _format_history(history: list[dict]) -> str:
    """格式化对话历史"""
    if not history:
        return ""

    lines = []
    for h in history[-6:]:  # 最近6条
        role = "用户" if h.get("role") == "user" else "助手"
        content = h.get("content", "")
        # 截断过长的历史
        if len(content) > 300:
            content = content[:300] + "..."
        lines.append(f"{role}：{content}")

    return HISTORY_TEMPLATE.format(history="\n".join(lines))


# ─── Generator ──────────────────────────────────────────────────────────

class RAGGenerator:
    """RAG 生成器"""

    def __init__(self, model: Optional[str] = None, temperature: float = 0.3):
        self.model = model
        self.temperature = temperature

    def _build_messages(
        self,
        query: str,
        context_text: str,
        history: list[dict] | None,
        intent: str,
    ) -> list:
        """构建完整的消息列表"""
        messages = []

        # 1. System Prompt（根据意图选择）
        system_prompt = SYSTEM_PROMPTS.get(intent, SYSTEM_PROMPTS["factual"])
        messages.append(SystemMessage(content=system_prompt))

        # 2. Context
        if context_text:
            messages.append(HumanMessage(content=CONTEXT_HEADER + context_text))

        # 3. History
        history_text = _format_history(history)
        if history_text:
            messages.append(HumanMessage(content=history_text))

        # 4. Current Question
        messages.append(HumanMessage(content=f"用户问题：{query}"))

        return messages

    async def generate_stream(
        self,
        query: str,
        context_text: str,
        history: list[dict] | None = None,
        intent: str = "factual",
    ) -> AsyncGenerator[tuple[str, str], None]:
        """
        流式生成回答

        Args:
            query: 用户问题
            context_text: 格式化后的上下文
            history: 对话历史
            intent: 查询意图

        Yields:
            (token, full_text): 增量 token 和当前完整文本
        """
        llm = get_llm_with_tracking(
            agent_name="rag_generator",
            model=self.model,
            temperature=self.temperature,
        )

        if llm is None:
            _logger.error("[Generator] LLM 不可用")
            yield ("抱歉，AI 服务暂时不可用。", "抱歉，AI 服务暂时不可用。")
            return

        messages = self._build_messages(query, context_text, history, intent)

        full_text = ""
        try:
            async for chunk in llm.astream(messages):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                if token:
                    full_text += token
                    yield (token, full_text)

            _logger.info(f"[Generator] 生成完成，length={len(full_text)}")

        except Exception as exc:
            _logger.error(f"[Generator] 流式生成失败: {exc}")
            yield (f"生成失败：{str(exc)}", full_text)
