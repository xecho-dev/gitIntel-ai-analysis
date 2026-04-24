"""
RAG Chat Service — Multi-Agent 协作问答模式。

用户问题 → Supervisor Agent（意图分类 + 路由）
                    ├── KnowledgeAgent（知识库问答）
                    ├── CodeAgent（代码相关问题）
                    ├── AnalysisAgent（分析结果查询）
                    └── GeneralAgent（通用问题）
"""

import json
import logging
from typing import AsyncGenerator

from schemas.chat import RAGSource

_logger = logging.getLogger("gitintel")


async def rag_chat_stream(
    question: str,
    top_k: int = 5,
) -> AsyncGenerator[tuple[str, list[RAGSource], str], None]:
    """
    流式 RAG 问答，内部委托 Multi-Agent 系统处理。

    Yields:
        (delta_text, rag_sources, full_text)
    """
    from agents.chat import multi_agent_chat_stream

    full_text = ""
    last_sources: list = []

    async for sse_chunk in multi_agent_chat_stream(question=question):
        if sse_chunk.startswith("data: "):
            raw = sse_chunk[6:].strip()
            if raw and raw != "[DONE]":
                try:
                    data = json.loads(raw)
                    if data.get("type") == "sources":
                        last_sources = data.get("sources", [])
                    elif data.get("type") == "token":
                        delta = data.get("delta", "")
                        full_text = data.get("full_text", "") or full_text
                        if delta:
                            yield (delta, last_sources, full_text)
                except Exception:
                    pass

    yield ("", last_sources, full_text)
