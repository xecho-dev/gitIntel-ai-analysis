"""
Generator — LLM 流式生成层。

职责：
  1. 根据意图选择合适的 System Prompt
  2. 构建完整的消息（含多层记忆上下文）
  3. 调用 LLM 流式生成
  4. 实时返回 token
"""

import logging
from typing import AsyncGenerator, Optional, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from memory.multi_memory import MultiLayerMemory

from langchain_core.messages import HumanMessage, SystemMessage

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

    "conversational": """你是 GitIntel 的友好 AI 助手。你具有多轮对话记忆能力。

你的职责是结合【多层记忆上下文】中的对话历史和参考资料，自然地回答用户问题，让交互更加友好和高效。

重要规则：
1. 优先使用【多层记忆上下文】中的对话历史来回答涉及用户个人信息、偏好、历史对话相关的问题
2. 如果记忆中有用户之前说过的内容（如名字、爱好、问题），务必在回答中体现
3. 口语化表达，友好亲切
4. 如果记忆中没有相关信息，再结合参考资料或通用知识
5. 引导用户深入提问
6. 保持简洁有趣""",

    "conversational_fast": """你是 GitIntel 的友好 AI 助手，支持多轮对话。

你的职责是用口语化、友好的方式快速回答用户问题。

重要规则：
1. 简洁直接，口语化表达
2. 友好亲切，像和朋友聊天
3. 如果是闲聊，适当活泼一些
4. 如果涉及 GitIntel 功能使用，简明扼要指引用户
5. 不要啰嗦，控制回答长度
6. 不需要引用参考资料，直接回答即可""",

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

CONTEXT_HEADER = """【参考资料】
以下是与问题相关的参考资料，请结合这些内容回答。
"""


def _format_multi_layer_context(
    working: str,
    semantic: str,
    knowledge: str,
) -> str:
    """格式化多层记忆上下文"""
    parts = []

    if working:
        parts.append(f"【近期对话摘要】\n{working}")
    if semantic:
        parts.append(f"【相关对话历史】\n{semantic}")
    if knowledge:
        parts.append(f"【相关知识】\n{knowledge}")

    return "\n\n".join(parts) if parts else ""


def _format_fast_path_memory(
    short_term: str,
    long_term: str,
    profile: str,
) -> str:
    """
    格式化快速路径的多层记忆 → 供给 LLM 的自然对话风格上下文。

    输入数据（已由 memory 层净化）：
      - short_term: "用户：...\n助手：..."  （无标题）
      - long_term:  "用户名叫小熊\n用户职业是前端开发"  （无标签）
      - profile:    "用户名叫小熊"  （无标签）

    原则：
      1. short_term 完整保留（当前会话相关性最高）
      2. profile 只取 top 2（永不过期的核心身份）
      3. long_term 只取 top 3（跨会话相关记忆）
      4. 全局按内容哈希去重
      5. 只加最小化结构标签，引导 LLM 自然使用
    """
    seen: set[str] = set()
    lines: list[str] = []

    def _add(text: str) -> None:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            key = line[:25].lower()
            if key and key not in seen:
                seen.add(key)
                lines.append(line)

    # 短期记忆完整保留（当前会话窗口，相关性最高）
    if short_term:
        lines.append(short_term)

    # 画像取 top 2（核心身份）
    if profile:
        profile_lines = [l.strip() for l in profile.splitlines() if l.strip()][:2]
        _add("\n".join(profile_lines))

    # 长期记忆取 top 3（跨会话，按相关度已排序）
    if long_term:
        long_lines = [l.strip() for l in long_term.splitlines() if l.strip()][:3]
        _add("\n".join(long_lines))

    # 限制总长度（防止 prompt 爆炸）
    result = "\n".join(lines)
    if len(result) > 2000:
        result = result[:2000]

    return result


# ─── Generator ──────────────────────────────────────────────────────────

class RAGGenerator:
    """
    RAG 生成器，使用 MultiLayerMemory 提供多轮对话记忆。
    """

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.3,
        multi_layer_memory: Optional[Any] = None,
    ):
        self.model = model
        self.temperature = temperature
        self.multi_layer_memory = multi_layer_memory

    def _build_messages(
        self,
        query: str,
        context_text: str,
        intent: str,
        fast_path: bool = False,
        memory_layers: Optional[dict] = None,
    ) -> list:
        """构建完整的消息列表

        Args:
            query: 用户问题
            context_text: 格式化后的上下文
            intent: 查询意图
            fast_path: 是否为快速路径（跳过 RAG，直接生成）
            memory_layers: 快速路径时传入的记忆各层（short_term/long_term/profile）
        """
        messages = []

        if fast_path:
            # 快速路径：使用精简的 prompt，memory 格式化为自然对话风格
            system_prompt = SYSTEM_PROMPTS.get("conversational_fast", SYSTEM_PROMPTS["conversational"])
            messages.append(SystemMessage(content=system_prompt))

            # 格式化为自然对话风格后再注入
            if memory_layers:
                memory_text = _format_fast_path_memory(
                    short_term=memory_layers.get("short_term", ""),
                    long_term=memory_layers.get("long_term", ""),
                    profile=memory_layers.get("profile", ""),
                )
                if memory_text:
                    messages.append(HumanMessage(content=f"【以下是我们之前的对话记忆，请参考】\n{memory_text}\n\n用户问题：{query}"))
                else:
                    messages.append(HumanMessage(content=query))
            else:
                messages.append(HumanMessage(content=query))
            return messages

        # 标准路径：根据意图选择 System Prompt
        system_prompt = SYSTEM_PROMPTS.get(intent, SYSTEM_PROMPTS["factual"])
        messages.append(SystemMessage(content=system_prompt))

        # 记忆上下文（由 memory 层已做净化和去重）
        if memory_layers:
            memory_text = _format_fast_path_memory(
                short_term=memory_layers.get("short_term", ""),
                long_term=memory_layers.get("long_term", ""),
                profile=memory_layers.get("profile", ""),
            )
            if memory_text:
                messages.append(HumanMessage(content=f"【对话记忆】\n{memory_text}\n"))

        # Context（参考资料）
        if context_text:
            messages.append(HumanMessage(content=CONTEXT_HEADER + context_text))

        # Current Question
        messages.append(HumanMessage(content=f"【用户问题】\n{query}"))

        return messages

    async def generate_stream(
        self,
        query: str,
        context_text: str,
        intent: str = "factual",
        fast_path: bool = False,
        temperature: Optional[float] = None,
        memory_layers: Optional[dict] = None,
    ) -> AsyncGenerator[tuple[str, str], None]:
        """
        流式生成回答

        Args:
            query: 用户问题
            context_text: 格式化后的上下文
            intent: 查询意图
            fast_path: 快速路径（跳过 RAG，直接生成，适合闲聊）
            temperature: 温度参数（快速路径时使用更高温度）
            memory_layers: 快速路径时传入的记忆各层（由 chat_pipeline 传入）
        """
        from utils.llm_factory import get_llm_with_tracking

        # 快速路径使用更高温度，获得更自然的对话风格
        effective_temperature = temperature if temperature is not None else self.temperature
        if fast_path:
            effective_temperature = 0.5

        llm = get_llm_with_tracking(
            agent_name="rag_generator",
            model=self.model,
            temperature=effective_temperature,
        )

        if llm is None:
            _logger.error("[Generator] LLM 不可用")
            yield ("抱歉，AI 服务暂时不可用。", "抱歉，AI 服务暂时不可用。")
            return

        messages = self._build_messages(
            query,
            context_text,
            intent,
            fast_path=fast_path,
            memory_layers=memory_layers,
        )

        full_text = ""
        try:
            async for chunk in llm.astream(messages):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                if token:
                    full_text += token
                    yield (token, full_text)

            estimated_output = len(full_text) * (2 if full_text and ord(full_text[0]) > 127 else 0.25)
            _logger.info(
                f"[Generator] 生成完成，output_chars={len(full_text)}, "
                f"est_tokens≈{int(estimated_output)}"
            )

        except Exception as exc:
            _logger.error(f"[Generator] 流式生成失败: {exc}")
            yield (f"生成失败：{str(exc)}", full_text)
