"""
Context Processor — 上下文处理层。

职责：
  1. 按相关性筛选检索结果
  2. 上下文窗口扩展（包含相邻块）
  3. 去重合并
  4. Token 预算限制
  5. 格式化输出
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from .query_processor import ProcessedQuery

_logger = logging.getLogger("gitintel")


@dataclass
class ContextChunk:
    """上下文块"""
    doc_id: str
    content: str
    title: str
    category: str
    source: str  # "vector" | "keyword" | "hybrid"
    relevance_score: float
    repo_url: str = ""
    priority: str = "medium"
    code_fix: dict = field(default_factory=dict)


@dataclass
class ProcessedContext:
    """处理后的上下文"""
    chunks: list[ContextChunk]
    total_tokens: int
    total_chars: int
    has_sufficient_context: bool
    query_intent: str


# ─── Token 估算 ──────────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    """估算 token 数量（中文≈2字符/token，英文≈4字符/token）"""
    chinese_chars = len(_find_chinese(text))
    english_chars = len(_find_english(text))
    other_chars = len(text) - chinese_chars - english_chars

    return int(chinese_chars / 2 + english_chars / 4 + other_chars / 3)


def _find_chinese(text: str) -> str:
    import re
    return re.sub(r'[^\u4e00-\u9fff]', '', text)


def _find_english(text: str) -> str:
    import re
    return re.sub(r'[^a-zA-Z]', '', text)


# ─── 上下文处理 ───────────────────────────────────────────────────────

def process_context(
    retrieval_results: list,
    processed_query: ProcessedQuery,
    max_tokens: int = 4000,
    max_chunks: int = 8,
) -> ProcessedContext:
    """
    Context Processing 主函数

    Args:
        retrieval_results: 检索结果列表（SearchResult 对象列表）
        processed_query: 处理后的查询
        max_tokens: 最大 token 预算
        max_chunks: 最大块数

    Returns:
        ProcessedContext: 处理后的上下文
    """
    if not retrieval_results:
        return ProcessedContext(
            chunks=[],
            total_tokens=0,
            total_chars=0,
            has_sufficient_context=False,
            query_intent=processed_query.intent,
        )

    # 1. 过滤低相关性结果（阈值根据意图调整）
    threshold = _get_relevance_threshold(processed_query.intent)
    filtered = [r for r in retrieval_results if r.score >= threshold]

    # 如果过滤后太少，降低阈值重试
    if len(filtered) < 2 and retrieval_results:
        filtered = [r for r in retrieval_results if r.score >= 0.1]

    # 2. 按相关性排序
    sorted_results = sorted(filtered, key=lambda x: x.score, reverse=True)

    # 3. 构建上下文块
    chunks: list[ContextChunk] = []
    total_tokens = 0
    total_chars = 0
    seen_contents: set[str] = set()

    for result in sorted_results:
        # 去重（基于内容前100字符的哈希）
        content_hash = hash(result.content[:100] if result.content else "")
        if content_hash in seen_contents:
            continue
        seen_contents.add(content_hash)

        # 构建块
        chunk = ContextChunk(
            doc_id=result.id,
            content=result.content,
            title=result.title,
            category=result.category,
            source="hybrid",
            relevance_score=result.score,
            repo_url=result.repo_url,
            priority=result.priority,
            code_fix=result.code_fix if hasattr(result, 'code_fix') else {},
        )

        # Token 预算检查
        chunk_tokens = _estimate_tokens(chunk.content)

        if total_tokens + chunk_tokens > max_tokens:
            # 尝试截断最后一个块
            if chunks and chunk_tokens < max_tokens * 2:
                remaining_tokens = max_tokens - total_tokens
                if remaining_tokens > 500:  # 至少保留 500 tokens
                    chunk.content = _truncate_to_tokens(chunk.content, remaining_tokens)
                    chunk_tokens = _estimate_tokens(chunk.content)
                else:
                    break
            else:
                break

        chunks.append(chunk)
        total_tokens += chunk_tokens
        total_chars += len(chunk.content)

        if len(chunks) >= max_chunks:
            break

    _logger.info(
        f"[ContextProcessor] intent={processed_query.intent}, "
        f"input={len(retrieval_results)}, filtered={len(filtered)}, "
        f"output={len(chunks)} chunks, tokens≈{total_tokens}"
    )

    return ProcessedContext(
        chunks=chunks,
        total_tokens=total_tokens,
        total_chars=total_chars,
        has_sufficient_context=len(chunks) > 0,
        query_intent=processed_query.intent,
    )


def _get_relevance_threshold(intent: str) -> float:
    """根据意图返回相关性阈值"""
    thresholds = {
        "factual": 0.3,
        "code_related": 0.25,
        "analytical": 0.2,
        "conversational": 0.15,
    }
    return thresholds.get(intent, 0.2)


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """按 token 限制截断文本"""
    # 粗略估算：中文/2 + 英文/4 = tokens
    chinese_count = len(_find_chinese(text))
    english_count = len(_find_english(text))
    other_count = len(text) - chinese_count - english_count

    current_tokens = int(chinese_count / 2 + english_count / 4 + other_count / 3)

    if current_tokens <= max_tokens:
        return text

    # 二分查找合适的截断位置
    target_chars = int(max_tokens * 3)  # 粗略的字符数估算
    return text[:min(target_chars, len(text))] + "..."


# ─── 格式化 ───────────────────────────────────────────────────────────

def format_context_for_prompt(context: ProcessedContext) -> str:
    """
    将处理后的上下文格式化为 prompt 片段

    根据意图选择不同的格式化风格
    """
    if not context.chunks:
        return ""

    if context.query_intent == "code_related":
        return _format_for_code(context)
    elif context.query_intent == "analytical":
        return _format_for_analytical(context)
    else:
        return _format_for_factual(context)


def _format_for_factual(context: ProcessedContext) -> str:
    """格式化factual类型查询的上下文"""
    parts = ["【参考资料】\n"]

    for i, chunk in enumerate(context.chunks, 1):
        parts.append(f"【{i}】{chunk.title}")
        if chunk.category:
            parts.append(f"    分类: {chunk.category}")
        parts.append(chunk.content)
        parts.append("")

    return "\n".join(parts)


def _format_for_analytical(context: ProcessedContext) -> str:
    """格式化analytical类型查询的上下文"""
    # 按类别分组
    by_category: dict[str, list[ContextChunk]] = {}
    for chunk in context.chunks:
        cat = chunk.category or "other"
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(chunk)

    parts = ["【分析参考资料】\n"]

    for cat, chunks in by_category.items():
        parts.append(f"\n## {cat.upper()} 相关\n")
        for i, chunk in enumerate(chunks, 1):
            parts.append(f"【{i}】{chunk.title}")
            parts.append(chunk.content)
            parts.append("")

    return "\n".join(parts)


def _format_for_code(context: ProcessedContext) -> str:
    """格式化code_related类型查询的上下文"""
    # 优先展示有 code_fix 的结果
    with_fix = [c for c in context.chunks if c.code_fix]
    without_fix = [c for c in context.chunks if not c.code_fix]

    parts = ["【代码相关参考资料】\n"]

    # 先展示有具体代码修复的
    if with_fix:
        parts.append("\n## 具体代码修复方案\n")
        for i, chunk in enumerate(with_fix, 1):
            parts.append(f"【{i}】{chunk.title}")
            parts.append(chunk.content)
            if chunk.code_fix:
                parts.append(f"\n修复方案:")
                for key, val in chunk.code_fix.items():
                    if val and key != "reason":
                        parts.append(f"  - {key}: {str(val)[:100]}")
            parts.append("")

    # 再展示其他参考
    if without_fix:
        parts.append("\n## 其他参考\n")
        for i, chunk in enumerate(without_fix, len(with_fix) + 1):
            parts.append(f"【{i}】{chunk.title}")
            parts.append(chunk.content)
            parts.append("")

    return "\n".join(parts)


def context_to_sources(context: ProcessedContext) -> list[dict]:
    """将上下文转换为前端可用的来源列表"""
    sources = []
    for i, chunk in enumerate(context.chunks, 1):
        source = {
            "id": i,
            "title": chunk.title,
            "category": chunk.category,
            "relevance": round(chunk.relevance_score, 3),
            "score": round(chunk.relevance_score, 3),
            "priority": chunk.priority,
            "repo_url": chunk.repo_url,
            "content": chunk.content[:200],  # 只传前150字符预览
        }
        if chunk.code_fix:
            source["has_code_fix"] = True
        sources.append(source)

    return sources
