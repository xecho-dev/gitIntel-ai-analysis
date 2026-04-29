"""
Post-Processor — 后处理层。

职责：
  1. 提取引用标注
  2. 构建来源列表
  3. 答案质量评估
  4. 输出格式化
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

from .context_processor import ProcessedContext

_logger = logging.getLogger("gitintel")


@dataclass
class ProcessedAnswer:
    """处理后的回答"""
    answer: str
    citations: list[int]  # 引用编号列表
    sources: list[dict]  # 来源详情
    quality_score: float  # 0-1
    context_used: int  # 使用的上下文块数
    tokens_used: int


def post_process(answer: str, context: ProcessedContext) -> ProcessedAnswer:
    """
    Post-processing 主函数

    Args:
        answer: LLM 生成的回答
        context: 处理后的上下文

    Returns:
        ProcessedAnswer: 处理后的回答
    """
    # 1. 提取引用
    citations = _extract_citations(answer)

    # 2. 构建来源列表
    sources = _build_sources(context, citations)

    # 3. 答案质量评估
    quality_score = _assess_quality(answer, context, citations)

    return ProcessedAnswer(
        answer=answer,
        citations=citations,
        sources=sources,
        quality_score=quality_score,
        context_used=len(context.chunks),
        tokens_used=context.total_tokens,
    )


def _extract_citations(answer: str) -> list[int]:
    """提取引用编号"""
    # 匹配【1】【2】或 [1] [2] 格式
    patterns = [
        r'【(\d+)】',  # 【1】【2】
        r'\[(\d+)\]',  # [1] [2]
        r'^(\d+)[\s.。:：]',  # 1. 2.
    ]

    citations: set[int] = set()
    for pattern in patterns:
        matches = re.findall(pattern, answer)
        for m in matches:
            idx = int(m)
            if 1 <= idx <= 20:  # 合理的引用范围
                citations.add(idx)

    return sorted(list(citations))


def _build_sources(context: ProcessedContext, citations: list[int]) -> list[dict]:
    """构建来源列表"""
    sources = []
    for idx in citations:
        if 1 <= idx <= len(context.chunks):
            chunk = context.chunks[idx - 1]
            source = {
                "id": idx,
                "title": chunk.title,
                "category": chunk.category,
                "priority": chunk.priority,
                "relevance": round(chunk.relevance_score, 3),
                "score": round(chunk.relevance_score, 3),
                "repo_url": chunk.repo_url if chunk.repo_url else None,
                "preview": chunk.content[:200],  # 预览
                "has_code_fix": bool(chunk.code_fix),
            }
            if chunk.code_fix:
                source["code_fix"] = chunk.code_fix
            sources.append(source)

    return sources


def _assess_quality(
    answer: str,
    context: ProcessedContext,
    citations: list[int],
) -> float:
    """评估回答质量（0-1）"""
    score = 0.5  # 基础分

    # 1. 有上下文且有引用 +0.2
    if context.has_sufficient_context and citations:
        score += 0.2

    # 2. 有足够的引用 +0.1
    if len(citations) >= 2:
        score += 0.1

    # 3. 回答长度合理（不是太短也不是太长） +0.1
    answer_len = len(answer)
    if 100 <= answer_len <= 2000:
        score += 0.1

    # 4. 没有明显的"不知道"或"无法回答"等降级回答 +0.1
    refusal_phrases = ["不知道", "无法回答", "没有相关", "无法确定", "信息不足"]
    if not any(phrase in answer for phrase in refusal_phrases):
        score += 0.1

    # 5. 使用了 markdown 格式 +0.05（如果有代码相关内容）
    if context.query_intent == "code_related":
        if "```" in answer or "`" in answer:
            score += 0.05

    return min(score, 1.0)


def format_sse_event(
    event_type: str,
    data: Optional[dict] = None,
) -> str:
    """格式化 SSE 事件"""
    event = {"type": event_type}
    if data:
        event.update(data)
    return json.dumps(event, ensure_ascii=False)
