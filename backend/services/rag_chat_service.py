"""
RAG Chat Service — 基于 DashVector 向量检索 + LLM 生成回答。

用户提问 → 检索相关知识库文档 → 组装 prompt → LLM 生成回答 → 保存消息
"""

import logging
import os
from typing import AsyncGenerator, Optional

from utils.llm_factory import get_llm_with_tracking
from memory.dashvector_store import DashVectorStore, SearchResult
from schemas.chat import RAGSource

_logger = logging.getLogger("gitintel")

SYSTEM_PROMPT = """你是一个专业的代码分析与架构优化助手，基于 GitIntel 的分析知识库回答用户问题。

你的知识来自 GitIntel 对 GitHub 仓库的深度分析，包括架构拓扑、代码质量、依赖风险、优化建议等洞察。

回答规则：
1. 优先基于检索到的知识库内容回答；如果没有相关内容，坦诚告知用户
2. 结合代码分析场景，用专业但易懂的语言解释
3. 可以引用具体的分析建议和改进方向
4. 保持简洁，突出关键信息
"""


def _build_rag_prompt(question: str, context_docs: list[SearchResult]) -> str:
    """组装带有 RAG 上下文的 prompt。"""
    if not context_docs:
        return f"问题：{question}\n\n请回答用户的问题。"

    context_blocks = []
    for i, doc in enumerate(context_docs, 1):
        context_blocks.append(
            f"[知识文档 {i}] 来自 {doc.repo_url}（{doc.category}）\n标题：{doc.title}\n内容：{doc.content}"
        )

    context_text = "\n\n".join(context_blocks)

    return f"""基于以下知识库文档回答问题。如果没有足够的相关信息，请如实告知。

---
{context_text}
---

问题：{question}

回答："""


def rag_chat(question: str, top_k: int = 5) -> tuple[str, list[RAGSource]]:
    """
    执行一次 RAG 问答。

    Args:
        question: 用户问题
        top_k: 检索的知识文档数量

    Returns:
        (answer_text, rag_sources)
    """
    # 1. 检索相关文档
    vector_store = DashVectorStore()

    if not vector_store.is_available:
        _logger.warning("[RAGChat] DashVector 不可用，直接用 LLM 回答")
        docs: list[SearchResult] = []
    else:
        docs = vector_store.retrieve_similar(question, top_k=top_k)
        _logger.info(f"[RAGChat] 检索到 {len(docs)} 条相关文档")

    # 2. 组装 prompt
    prompt = _build_rag_prompt(question, docs)

    # 3. 调用 LLM 生成回答
    llm = get_llm_with_tracking(agent_name="RAGChat", temperature=0.3)

    if llm is None:
        return "抱歉，AI 服务暂时不可用。", []

    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    try:
        response = llm.ainvoke(messages)
        answer = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        _logger.error(f"[RAGChat] LLM 调用失败: {exc}")
        answer = "抱歉，回答生成过程中出现错误。"

    # 4. 转换 sources
    sources = [
        RAGSource(
            repo_url=doc.repo_url,
            category=doc.category,
            title=doc.title,
            content=doc.content,
            score=doc.score,
            priority=doc.priority,
        )
        for doc in docs
    ]

    return answer, sources


async def rag_chat_stream(
    question: str,
    top_k: int = 5,
) -> AsyncGenerator[tuple[str, list[RAGSource], str], None]:
    """
    流式 RAG 问答，逐 token 返回 LLM 输出。

    Yields:
        (delta_text, rag_sources, full_text)
        - delta_text: 本次新增的文本片段
        - rag_sources: 检索到的源文档（RAGSource，只在首次 yield 时非空）
        - full_text: 截止目前的完整回答

    流结束后，最后一次 yield 会以 delta_text == "" 表示结束。
    """
    vector_store = DashVectorStore()

    if not vector_store.is_available:
        _logger.warning("[RAGChatStream] DashVector 不可用，直接用 LLM 回答")
        docs: list[SearchResult] = []
    else:
        docs = vector_store.retrieve_similar(question, top_k=top_k)
        _logger.info(f"[RAGChatStream] 检索到 {len(docs)} 条相关文档")

    sources = [
        RAGSource(
            repo_url=doc.repo_url,
            category=doc.category,
            title=doc.title,
            content=doc.content,
            score=doc.score,
            priority=doc.priority,
        )
        for doc in docs
    ]

    # 立即先 yield 一次 sources（让前端先拿到引用）
    yield ("", sources, "")

    prompt = _build_rag_prompt(question, docs)

    llm = get_llm_with_tracking(agent_name="RAGChat", temperature=0.3)
    if llm is None:
        yield ("抱歉，AI 服务暂时不可用。", [], "抱歉，AI 服务暂时不可用。")
        return

    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    full_text = ""
    try:
        async for chunk in llm.astream(messages):
            token = chunk.content if hasattr(chunk, "content") else str(chunk)
            full_text += token
            yield (token, [], full_text)
    except Exception as exc:
        _logger.error(f"[RAGChatStream] LLM 流式调用失败: {exc}")
        yield ("抱歉，回答生成过程中出现错误。", [], full_text)
        return

    # 结束标记
    yield ("", [], full_text)
