"""
RAG Pipeline — 主流程编排器。

整合 Query Processing → Retrieval → Context → Generate → Post-Process
支持多层记忆系统：
  短期记忆：ConversationSummaryMemory，当前会话窗口，对话关闭即消失
  长期记忆：异步轻量抽取 + 分层向量存储 + 按需检索


检索架构：
  用户输入
      │
      ▼
  ┌─────────────────────┐
  │ 1. Query Rewrite    │  ⭐ 主力（代词消解、上下文补全）
  └──────────┬──────────┘
             │
             ▼
  ┌─────────────────────┐
  │ 2. 向量检索          │  ← 首次检索
  └──────────┬──────────┘
             │
        召回失败？
             │
         ┌───┴───┐
         │       │
        是       否
         │       │
         ▼       ▼
  ┌─────────────────┐   ┌─────────────────────┐
  │ 3. HyDE 兜底    │   │ 直接进入 Context     │
  │ （假设文档检索）  │   │ Processing          │
  └────────┬────────┘   └─────────────────────┘
            │
            ▼
  ┌─────────────────────┐
  │ 4. Context          │
  │    Processing       │
  └──────────┬──────────┘
             │
             ▼
  ┌─────────────────────┐
  │ 5. LLM Generation   │
  └──────────┬──────────┘
             │
             ▼
  ┌─────────────────────┐
  │ 6. Post-Processing  │
  └─────────────────────┘


组件	                文件位置	             职责
QueryProcessor	        query_processor.py	    意图分类、关键词扩展
MultiStrategyRetriever	retriever.py	        向量检索 + 关键词检索 + 意图路由
ContextProcessor	    context_processor.py	上下文整理、token 限制、格式转换
RAGGenerator        	generator.py	         LLM 流式生成
MultiLayerMemory    	multi_memory.py	        多层记忆系统（短期会话记忆 + 长期分层记忆）
"""

import json
import logging
from typing import AsyncGenerator, Optional

from .query_processor import process_query, ProcessedQuery
from .retriever import MultiStrategyRetriever
from .context_processor import process_context, format_context_for_prompt, context_to_sources, ProcessedContext
from .generator import RAGGenerator
from .post_processor import post_process
try:
    from memory.multi_memory import MultiLayerMemory, create_multi_layer_memory
except ImportError:
    MultiLayerMemory = None
    create_multi_layer_memory = None

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

    支持多层记忆：
      - session_id: 会话 ID，用于隔离不同用户的记忆
      - enable_multi_layer_memory: 是否启用多层记忆（默认启用）
    """

    def __init__(
        self,
        max_context_tokens: int = 4000,
        retrieval_top_k: int = 10,
        generation_model: Optional[str] = None,
        generation_temperature: float = 0.3,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        enable_multi_layer_memory: bool = True,
    ):
        self.retriever = MultiStrategyRetriever()
        self.generator = RAGGenerator(
            model=generation_model,
            temperature=generation_temperature,
        )
        self.max_context_tokens = max_context_tokens
        self.retrieval_top_k = retrieval_top_k

        # 多层记忆
        self.session_id = session_id or "default"
        self.user_id = user_id or ""
        self.enable_multi_layer_memory = enable_multi_layer_memory
        self._multi_layer_memory: Optional[MultiLayerMemory] = None

    @property
    def multi_layer_memory(self) -> Optional[MultiLayerMemory]:
        """懒加载多层记忆"""
        if self._multi_layer_memory is None and self.enable_multi_layer_memory and create_multi_layer_memory is not None:
            try:
                from memory.chromadb_store import ChromaStore
                vectorstore = ChromaStore(collection_type="memory")
                self._multi_layer_memory = create_multi_layer_memory(
                    session_id=self.session_id,
                    user_id=self.user_id,
                    vectorstore=vectorstore,
                )
                _logger.info(f"[RAGPipeline] 多层记忆初始化完成: session={self.session_id}, user_id={self.user_id}")
            except Exception as exc:
                _logger.warning(f"[RAGPipeline] 多层记忆初始化失败: {exc}")
                self._multi_layer_memory = None

        # 将 memory 实例同步给 generator（generator 在 __init__ 时还未初始化 memory）
        if self._multi_layer_memory is not None:
            self.generator.multi_layer_memory = self._multi_layer_memory

        return self._multi_layer_memory

    async def chat(
        self,
        question: str,
    ) -> AsyncGenerator[str, None]:
        """
        RAG 聊天主流程

        Args:
            question: 用户问题

        Yields:
            SSE 事件字符串（已包含 data: 前缀）
        """
        # ── 初始化 ──────────────────────────────────────────────────
        from utils.llm_factory import reset_token_stats
        reset_token_stats()

        # ── Step 1: Query Processing ─────────────────────────────────
        processed_query = await self._process_query(question)
        yield self._sse_event(SSEEventType.ROUTE, {
            "intent": processed_query.intent,
            "language": processed_query.language,
            "keywords": processed_query.keywords,
            "expanded_terms": processed_query.expanded_terms,
            "is_code_related": processed_query.is_code_related,
            "is_repo_related": processed_query.is_repo_related,
            "rewrite_query": processed_query.rewritten_query,
            "rewrite_enabled": processed_query.rewritten_query != processed_query.original,
            "message": "正在分析问题...",
            "percent": 10,
        })

        # ── Step 1.5: 获取记忆上下文（先于 RAG 检索）────────────────
        # 重要：记忆检索使用 gitintel_memory collection，与 RAG 知识库完全隔离
        memory_context = {}
        if self.multi_layer_memory:
            try:
                memory_context = self.multi_layer_memory.get_full_context(
                    query=question,
                )
                has_short = bool(memory_context.get("short_term"))
                has_long = bool(memory_context.get("long_term"))
                has_profile = bool(memory_context.get("profile"))
                if has_short or has_long or has_profile:
                    _logger.info(
                        f"[RAGPipeline] 记忆上下文已获取: short={len(memory_context.get('short_term', ''))} chars, "
                        f"long={len(memory_context.get('long_term', ''))} chars"
                    )
                else:
                    _logger.debug("[RAGPipeline] 记忆上下文为空（首次对话或无匹配记忆）")
            except Exception as exc:
                _logger.warning(f"[RAGPipeline] 获取记忆上下文失败: {exc}")

        # ── 分支：对话意图 → 快速路径（跳过 RAG，直接生成）───────
        if processed_query.intent == "conversational":
            _logger.info("[RAGPipeline] 对话意图，启用快速路径，跳过向量检索和 HyDE")

            yield self._sse_event(SSEEventType.RETRIEVING, {
                "message": "简单对话，直接回复...",
                "percent": 20,
            })

            # 直接生成，不走检索流程
            yield self._sse_event(SSEEventType.SOURCES, {
                "sources": [],
                "total": 0,
                "message": "直接回复",
                "percent": 30,
                "hyde_used": False,
            })

            # 快速路径下，将记忆上下文各层传入 generator（由 generator 格式化为自然对话历史）
            memory_layers = {
                "short_term": memory_context.get("short_term", ""),
                "long_term": memory_context.get("long_term", ""),
                "profile": memory_context.get("profile", ""),
            }

            yield self._sse_event(SSEEventType.GENERATING, {
                "message": "正在生成回答...",
                "percent": 40,
            })

            full_answer = ""
            async for token, full_text in self.generator.generate_stream(
                query=question,
                context_text="",
                intent=processed_query.intent,
                fast_path=True,
                memory_layers=memory_layers,
            ):
                full_answer = full_text
                if token and len(full_text) % 3 == 0:
                    yield self._sse_event(SSEEventType.TOKEN, {
                        "delta": token,
                        "full_text": full_text,
                        "percent": min(40 + len(full_text) // 20, 90),
                    })

            if full_answer:
                yield self._sse_event(SSEEventType.TOKEN, {
                    "delta": "",
                    "full_text": full_answer,
                    "percent": 95,
                })

            # 保存对话到记忆
            if self.multi_layer_memory and full_answer:
                try:
                    self.multi_layer_memory.add_turn(question, full_answer)
                except Exception as exc:
                    _logger.warning(f"[RAGPipeline] 保存记忆失败: {exc}")

            # 直接返回 Done（跳过 post_process，闲聊不需要）
            yield self._sse_event(SSEEventType.DONE, {
                "answer": full_answer,
                "full_text": full_answer,
                "citations": [],
                "sources": [],
                "quality_score": 1.0,
                "intent": processed_query.intent,
                "memory_layers": {
                    "working": True,
                    "semantic": True,
                    "knowledge": True,
                } if self.multi_layer_memory else None,
                "message": "回答完成",
                "percent": 100,
            })

            _logger.info(
                f"[RAGPipeline] done (fast_path): intent={processed_query.intent}, "
                f"answer_len={len(full_answer)}, memory={self.multi_layer_memory is not None}"
            )
            return

        # ── 标准路径：非对话意图，走完整 RAG 流程 ─────────────────

        # ── Step 2: Retrieval Layer ───────────────────────────────
        yield self._sse_event(SSEEventType.RETRIEVING, {
            "message": "正在检索相关知识...",
            "percent": 25,
        })

        retrieval_results = await self._retrieve(processed_query)

        # ── Step 2.5: HyDE 兜底（召回失败时触发）─────────────────
        hyde_document = None
        should_use_hyde = (
            not retrieval_results
            and processed_query.intent in ("code_related", "analytical", "factual")
            and processed_query.is_code_related
        )
        if should_use_hyde:
            _logger.info("[RAGPipeline] 向量检索无结果，启用 HyDE 兜底...")
            yield self._sse_event(SSEEventType.RETRIEVING, {
                "message": "向量检索未命中，启用假设文档检索...",
                "percent": 25,
            })
            hyde_document = await self._generate_hyde_fallback(
                processed_query.rewritten_query,
                processed_query.is_code_related,
            )
            if hyde_document:
                hyde_results = await self._retrieve_with_hyde(
                    processed_query, hyde_document
                )
                if hyde_results:
                    retrieval_results = hyde_results
                    yield self._sse_event(SSEEventType.RETRIEVING, {
                        "message": f"假设文档检索命中 {len(hyde_results)} 条",
                        "percent": 30,
                    })

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
            "hyde_used": hyde_document is not None,
        })

        # ── Step 3: Context Processing ─────────────────────────────
        processed_context = self._process_context(retrieval_results, processed_query)
        context_text = format_context_for_prompt(processed_context)

        # 注入记忆上下文（避免重复：只注入 long_term，profile 和 short_term 由 generator 处理）
        # 标准路径也传 memory_layers，由 generator._build_messages 统一格式化后注入
        # 这样记忆不会和 context_text 混在一起，也不会重复
        memory_layers = {
            "short_term": memory_context.get("short_term", ""),
            "long_term": memory_context.get("long_term", ""),
            "profile": memory_context.get("profile", ""),
        }

        if memory_layers.get("long_term") or memory_layers.get("profile"):
            _logger.info(
                f"[RAGPipeline] 记忆上下文已准备: short={len(memory_layers.get('short_term', ''))} chars, "
                f"long={len(memory_layers.get('long_term', ''))} chars, "
                f"profile={len(memory_layers.get('profile', ''))} chars"
            )

        has_memory = bool(
            memory_layers.get("short_term") or
            memory_layers.get("long_term") or
            memory_layers.get("profile")
        )
        if processed_context.has_sufficient_context or has_memory:
            msg = "已整理参考内容"
            if has_memory:
                mem_chars = (
                    len(memory_layers.get("short_term", "")) +
                    len(memory_layers.get("long_term", "")) +
                    len(memory_layers.get("profile", ""))
                )
                msg = f"已获取 {mem_chars} 字符的记忆上下文"
            yield self._sse_event(SSEEventType.RETRIEVING, {
                "message": msg,
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
            intent=processed_query.intent,
            fast_path=False,
            memory_layers=memory_layers,
        ):
            full_answer = full_text
            if token and len(full_text) % 3 == 0:
                yield self._sse_event(SSEEventType.TOKEN, {
                    "delta": token,
                    "full_text": full_text,
                    "percent": min(55 + len(full_text) // 20, 90),
                })

        if full_answer:
            yield self._sse_event(SSEEventType.TOKEN, {
                "delta": "",
                "full_text": full_answer,
                "percent": 95,
            })

        # ── Step 5: 保存对话到多层记忆 ──────────────────────────────
        if self.multi_layer_memory and full_answer:
            try:
                self.multi_layer_memory.add_turn(question, full_answer)
                yield self._sse_event(SSEEventType.RETRIEVING, {
                    "message": "对话已存入记忆",
                    "percent": 97,
                })
            except Exception as exc:
                _logger.warning(f"[RAGPipeline] 保存记忆失败: {exc}")

        # ── Step 6: Post-Processing ────────────────────────────────
        processed_answer = post_process(full_answer, processed_context)

        # ── Final: Done ───────────────────────────────────────────
        yield self._sse_event(SSEEventType.DONE, {
            "answer": full_answer,
            "full_text": full_answer,
            "citations": processed_answer.citations,
            "sources": context_to_sources(processed_context),
            "quality_score": processed_answer.quality_score,
            "intent": processed_query.intent,
            "memory_layers": {
                "working": True,
                "semantic": True,
                "knowledge": True,
            } if self.multi_layer_memory else None,
            "message": "回答完成",
            "percent": 100,
        })

        _logger.info(
            f"[RAGPipeline] done: intent={processed_query.intent}, "
            f"sources={len(processed_context.chunks)}, "
            f"answer_len={len(full_answer)}, "
            f"quality={processed_answer.quality_score:.2f}, "
            f"memory={self.multi_layer_memory is not None}"
        )

    async def _process_query(self, question: str) -> ProcessedQuery:
        """Query Processing（异步）"""
        from .query_processor import process_query
        return await process_query(question)

    async def _retrieve(self, query: ProcessedQuery) -> list:
        """Retrieval Layer（异步包装）"""
        import asyncio

        # 检索策略：使用 Query Rewrite 后的查询（代词消解、上下文补全）
        retrieval_query = query.rewritten_query if query.rewritten_query else query.original

        def sync_retrieve():
            return self.retriever.retrieve(
                query=retrieval_query,
                expanded_query=" ".join(query.keywords),
                intent=query.intent,
                top_k=self.retrieval_top_k,
                is_code_related=query.is_code_related,
            )

        return await asyncio.to_thread(sync_retrieve)

    async def _generate_hyde_fallback(
        self, query: str, is_code_related: bool
    ) -> Optional[str]:
        """HyDE 兜底：检索失败时生成假设文档"""
        try:
            from .query_processor import _generate_hyde_document
            return await _generate_hyde_document(query, is_code_related)
        except Exception as exc:
            _logger.warning(f"[RAGPipeline] HyDE 兜底失败: {exc}")
            return None

    async def _retrieve_with_hyde(
        self, query: ProcessedQuery, hyde_document: str
    ) -> list:
        """使用 HyDE 文档进行检索"""
        import asyncio

        def sync_retrieve():
            return self.retriever.retrieve(
                query=hyde_document,
                expanded_query="",
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


# ─── Pipeline 主类（已覆盖兼容层所有用法）──────────────────────────────
