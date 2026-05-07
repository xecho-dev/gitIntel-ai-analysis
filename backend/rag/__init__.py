"""
RAG Pipeline — 标准检索增强生成流水线。

模块：
  - query_processor: 查询处理（意图分类、关键词提取、查询扩展）
  - retriever: 多策略检索（向量 + 关键词 + RRF 融合）
  - context_processor: 上下文处理（过滤、去重、格式化）
  - generator: LLM 流式生成（意图感知）
  - post_processor: 后处理（引用提取、质量评估）
  - chat_pipeline: 主流程编排器
"""

from .query_processor import process_query, ProcessedQuery
from .retriever import MultiStrategyRetriever
from .context_processor import (
    process_context,
    ProcessedContext,
    format_context_for_prompt,
    context_to_sources,
)
from .generator import RAGGenerator
from .post_processor import post_process, ProcessedAnswer
from .chat_pipeline import RAGPipeline

__all__ = [
    # Query Processing
    "process_query",
    "ProcessedQuery",
    # Retrieval
    "MultiStrategyRetriever",
    # Context
    "process_context",
    "ProcessedContext",
    "format_context_for_prompt",
    "context_to_sources",
    # Generator
    "RAGGenerator",
    # Post-processor
    "post_process",
    "ProcessedAnswer",
    # Pipeline
    "RAGPipeline",
]
