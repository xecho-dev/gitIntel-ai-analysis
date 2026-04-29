"""
RAG Pipeline — 主流程编排器。

整合 Query Processing → Retrieval → Context → Generate → Post-Process
"""

import json
import logging
from typing import AsyncGenerator, Optional

from .query_processor import process_query, ProcessedQuery
from .retriever import MultiStrategyRetriever
from .context_processor import process_context, format_context_for_prompt, context_to_sources, ProcessedContext
from .generator import RAGGenerator
from .post_processor import post_process

_logger = logging.getLogger("gitintel")


# ─── SSE 事件类型 ────────────────────────────────────────────────────────

class SSEEventType:
    CONNECTED = "connected"
    ROUTE = "route"           # 查询处理完成，开始检索
    RETRIEVING = "retrieving" # 正在检索
    SOURCES = "sources"        # 检索结果
    GENERATING = "generating"  # 开始生成
    TOKEN = "token"           # 流式 token
    DONE = "done"             # 完成
    ERROR = "error"           # 错误


# ─── RAG Pipeline ────────────────────────────────────────────────────────

class RAGPipeline:
    """
    标准 RAG 流水线

    流程：
      Query Processing → Retrieval → Context Processing → LLM Generation → Post-Process
    """

    def __init__(
        self,
        max_context_tokens: int = 4000,
        retrieval_top_k: int = 10,
        generation_model: Optional[str] = None,
        generation_temperature: float = 0.3,
    ):
        self.retriever = MultiStrategyRetriever()
        self.generator = RAGGenerator(
            model=generation_model,
            temperature=generation_temperature,
        )
        self.max_context_tokens = max_context_tokens
        self.retrieval_top_k = retrieval_top_k

    async def chat(
        self,
        question: str,
        history: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        RAG 聊天主流程

        Args:
            question: 用户问题
            history: 对话历史

        Yields:
            SSE 事件字符串（已包含 data: 前缀）
        """
        # ── 初始化 ──────────────────────────────────────────────────
        from utils.llm_factory import reset_token_stats
        reset_token_stats()

        # ── Step 1: Query Processing ───────────────────────────────
        processed_query = self._process_query(question)
        yield self._sse_event(SSEEventType.ROUTE, {
            "intent": processed_query.intent,
            "language": processed_query.language,
            "keywords": processed_query.keywords,
            "expanded_terms": processed_query.expanded_terms,
            "is_code_related": processed_query.is_code_related,
            "is_repo_related": processed_query.is_repo_related,
            "message": "正在分析问题...",
            "percent": 10,
        })

        # ── Step 2: Retrieval Layer ───────────────────────────────
        yield self._sse_event(SSEEventType.RETRIEVING, {
            "message": "正在检索相关知识...",
            "percent": 25,
        })

        retrieval_results = await self._retrieve(processed_query)
        sources = [
            {
                "id": i + 1,
                "title": r.title,
                "category": r.category,
                "score": round(r.score, 3),
                "preview": r.content[:100] if r.content else "",
            }
            for i, r in enumerate(retrieval_results[:5])
        ]

        yield self._sse_event(SSEEventType.SOURCES, {
            "sources": sources,
            "total": len(retrieval_results),
            "message": f"找到 {len(retrieval_results)} 条相关知识",
            "percent": 40,
        })

        # ── Step 3: Context Processing ─────────────────────────────
        processed_context = self._process_context(retrieval_results, processed_query)
        context_text = format_context_for_prompt(processed_context)

        if processed_context.has_sufficient_context:
            yield self._sse_event(SSEEventType.RETRIEVING, {
                "message": f"已整理 {len(processed_context.chunks)} 条参考内容",
                "percent": 50,
            })
        else:
            yield self._sse_event(SSEEventType.RETRIEVING, {
                "message": "未找到足够相关的参考资料",
                "percent": 50,
            })

        # ── Step 4: LLM Streaming Generation ──────────────────────
        yield self._sse_event(SSEEventType.GENERATING, {
            "message": "正在生成回答...",
            "percent": 55,
        })

        full_answer = ""
        async for token, full_text in self.generator.generate_stream(
            query=question,
            context_text=context_text,
            history=history,
            intent=processed_query.intent,
        ):
            full_answer = full_text

            # 实时发送 token（每 3 个字符发一次，减少前端更新频率）
            if token and len(full_text) % 3 == 0:
                yield self._sse_event(SSEEventType.TOKEN, {
                    "delta": token,
                    "full_text": full_text,
                    "percent": min(55 + len(full_text) // 20, 90),
                })

        # 确保发送最终 token
        if full_answer:
            yield self._sse_event(SSEEventType.TOKEN, {
                "delta": "",
                "full_text": full_answer,
                "percent": 95,
            })

        # ── Step 5: Post-Processing ────────────────────────────────
        processed_answer = post_process(full_answer, processed_context)

        # ── Final: Done ───────────────────────────────────────────
        yield self._sse_event(SSEEventType.DONE, {
            "answer": full_answer,
            "full_text": full_answer,
            "citations": processed_answer.citations,
            "sources": context_to_sources(processed_context),
            "quality_score": processed_answer.quality_score,
            "intent": processed_query.intent,
            "message": "回答完成",
            "percent": 100,
        })

        _logger.info(
            f"[RAGPipeline] done: intent={processed_query.intent}, "
            f"sources={len(processed_context.chunks)}, "
            f"answer_len={len(full_answer)}, "
            f"quality={processed_answer.quality_score:.2f}"
        )

    def _process_query(self, question: str) -> ProcessedQuery:
        """Query Processing"""
        return process_query(question)

    async def _retrieve(self, query: ProcessedQuery) -> list:
        """Retrieval Layer（异步包装）"""
        import asyncio

        def sync_retrieve():
            return self.retriever.retrieve(
                query=query.original,
                expanded_query=" ".join(query.expanded_terms),
                intent=query.intent,
                top_k=self.retrieval_top_k,
                is_code_related=query.is_code_related,
            )

        return await asyncio.to_thread(sync_retrieve)

    def _process_context(
        self,
        retrieval_results: list,
        query: ProcessedQuery,
    ) -> ProcessedContext:
        """Context Processing"""
        return process_context(
            retrieval_results=retrieval_results,
            processed_query=query,
            max_tokens=self.max_context_tokens,
        )

    def _sse_event(self, event_type: str, data: dict) -> str:
        """构建 SSE 事件"""
        event = {"type": event_type}
        event.update(data)
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


# ─── 兼容层 ──────────────────────────────────────────────────────────────

async def rag_chat_stream(
    question: str,
    history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """
    RAG 聊天流式接口（兼容原有接口）

    直接使用 SSE 格式输出，前端可以直接消费
    """
    pipeline = RAGPipeline()
    async for event in pipeline.chat(question, history):
        yield event
