"""
RAG Chat Service — 标准 RAG Pipeline 模式。

用户问题 → Query Processing → Retrieval → Context → LLM Generation → Post-Process
"""

import json
import logging
from typing import AsyncGenerator

from schemas.chat import RAGSource

from rag import RAGPipeline

_logger = logging.getLogger("gitintel")


async def rag_chat_stream(
    question: str,
    history: list[dict] | None = None,
    top_k: int = 5,
) -> AsyncGenerator[tuple[str, list[RAGSource], str], None]:
    """
    流式 RAG 问答，内部使用标准 RAG Pipeline 处理。

    Yields:
        (delta_text, rag_sources, full_text)
    """
    pipeline = RAGPipeline(retrieval_top_k=top_k)

    full_text = ""
    last_sources: list = []

    async for event in pipeline.chat(question, history=history):
        # pipeline.chat() 已输出 "data: ..." 前缀
        raw = event[6:].strip() if event.startswith("data: ") else event.strip()

        if raw == "[DONE]":
            continue

        try:
            data = json.loads(raw)
            t = data.get("type", "")

            if t == "sources":
                last_sources = data.get("sources", [])

            elif t == "token":
                delta = data.get("delta", "")
                full_text = data.get("full_text", "") or full_text
                if delta:
                    yield (delta, last_sources, full_text)

            elif t == "done":
                full_text = data.get("answer", "") or data.get("full_text", "") or full_text

        except Exception:
            pass

    yield ("", last_sources, full_text)
