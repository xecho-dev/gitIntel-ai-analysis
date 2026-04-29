"""
Retriever — 多策略检索层。

职责：
  1. 向量检索（语义相似度）
  2. 关键词检索（BM25）
  3. 混合检索（RRF 融合）
  4. 按意图/类别过滤
"""

import json
import logging
from typing import Optional

from memory.dashvector_store import DashVectorStore, SearchResult

_logger = logging.getLogger("gitintel")


# ─── Retriever ──────────────────────────────────────────────────────────

class MultiStrategyRetriever:
    """
    多策略检索器

    支持：
    - 向量检索：语义相似度（基于 Embedding）
    - 关键词检索：BM25（基于关键词匹配）
    - 混合检索：RRF（倒数排名融合）
    """

    def __init__(self, vector_store: Optional[DashVectorStore] = None):
        self.vector_store = vector_store or self._init_vector_store()

    def _init_vector_store(self) -> Optional[DashVectorStore]:
        """懒加载向量存储"""
        try:
            return DashVectorStore()
        except Exception as e:
            _logger.warning(f"[Retriever] 向量存储初始化失败: {e}")
            return None

    @property
    def is_available(self) -> bool:
        return self.vector_store is not None and self.vector_store.is_available

    def retrieve(
        self,
        query: str,
        expanded_query: str,
        intent: str,
        top_k: int = 10,
        category: Optional[str] = None,
        is_code_related: bool = False,
    ) -> list[SearchResult]:
        """
        多策略并行检索 + 融合

        Args:
            query: 原始查询
            expanded_query: 扩展后的查询（包含同义词等）
            intent: 查询意图
            top_k: 返回数量
            category: 可选，按类别过滤
            is_code_related: 是否代码相关

        Returns:
            SearchResult 列表（按 RRF 分数排序）
        """
        if not self.is_available:
            _logger.warning("[Retriever] 向量存储不可用，返回空结果")
            return []

        try:
            # ── 策略1: 向量检索 ──────────────────────────────────────
            vector_results = self._vector_search(
                query=expanded_query,
                top_k=top_k * 2,  # 多检索一些用于融合
                category=category,
                is_code_related=is_code_related,
            )

            # ── 策略2: 关键词检索 ────────────────────────────────────
            # 在结果中再做关键词匹配过滤
            keyword_results = self._keyword_filter(vector_results, query)

            # 合并结果
            all_results = vector_results + keyword_results

            # ── 策略3: 意图相关检索 ──────────────────────────────────
            intent_results = self._intent_search(intent, query, is_code_related, top_k)
            all_results.extend(intent_results)

            # ── RRF 融合排序 ─────────────────────────────────────────
            fused = self._reciprocal_rank_fusion(all_results)

            # 去重（保留得分最高的）
            deduplicated = self._deduplicate(fused)

            _logger.info(
                f"[Retriever] query='{query[:30]}...', intent={intent}, "
                f"vector={len(vector_results)}, keyword={len(keyword_results)}, "
                f"intent={len(intent_results)}, final={len(deduplicated)}"
            )

            return deduplicated[:top_k]

        except Exception as e:
            _logger.error(f"[Retriever] 检索失败: {e}")
            return []

    def _vector_search(
        self,
        query: str,
        top_k: int,
        category: Optional[str],
        is_code_related: bool,
    ) -> list[SearchResult]:
        """向量语义检索"""
        try:
            # 构建过滤条件
            filter_category = category
            if is_code_related and not category:
                filter_category = None  # 代码相关时不限定类别

            results = self.vector_store.retrieve_similar(
                query=query,
                top_k=top_k,
                category=filter_category,
            )

            return results

        except Exception as e:
            _logger.warning(f"[Retriever] 向量检索失败: {e}")
            return []

    def _keyword_filter(
        self,
        results: list[SearchResult],
        query: str,
    ) -> list[SearchResult]:
        """关键词过滤：对已有结果按关键词相关性重新排序"""
        if not results:
            return []

        # 提取查询关键词
        import re
        words = re.split(r'[\s,，。.、]+', query.lower())
        words = [w for w in words if len(w) >= 2]

        filtered_results = []
        for r in results:
            # 计算关键词匹配分数
            content_lower = r.content.lower() + r.title.lower()
            match_count = sum(1 for w in words if w in content_lower)

            if match_count > 0:
                # 提升得分
                boosted_score = r.score + (match_count * 0.05)
                r.score = min(boosted_score, 1.0)
                filtered_results.append(r)

        return sorted(filtered_results, key=lambda x: x.score, reverse=True)

    def _intent_search(
        self,
        intent: str,
        query: str,
        is_code_related: bool,
        top_k: int,
    ) -> list[SearchResult]:
        """意图相关检索"""
        if intent == "code_related" or is_code_related:
            # 代码相关：检索代码类别的结果
            try:
                return self.vector_store.retrieve_similar(
                    query=f"{query} 代码 修复 bug",
                    top_k=top_k,
                    category="code",
                )
            except Exception:
                pass

        elif intent == "analytical":
            # 分析类：检索最佳实践、架构相关
            try:
                return self.vector_store.retrieve_similar(
                    query=f"{query} 分析 优化 建议",
                    top_k=top_k,
                )
            except Exception:
                pass

        return []

    def _reciprocal_rank_fusion(
        self,
        results: list[SearchResult],
        k: int = 60,
    ) -> list[SearchResult]:
        """
        RRF 融合：多策略结果合并排序

        RRF 公式: score = Σ 1/(k + rank)
        """
        rrf_scores: dict[str, tuple[float, SearchResult]] = {}

        for rank, r in enumerate(results, 1):
            doc_id = r.id
            if doc_id not in rrf_scores:
                rrf_scores[doc_id] = (0.0, r)

            # 累加 RRF 分数
            current_score, _ = rrf_scores[doc_id]
            rrf_scores[doc_id] = (current_score + 1 / (k + rank), r)

        # 按 RRF 分数排序
        sorted_results = sorted(
            rrf_scores.values(),
            key=lambda x: x[0],
            reverse=True,
        )

        return [r for _, r in sorted_results]

    def _deduplicate(
        self,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        """去重：基于内容前100字符的哈希"""
        seen: set[str] = set()
        deduplicated: list[SearchResult] = []

        for r in results:
            content_key = hash(r.content[:100] if r.content else r.id)
            if content_key not in seen:
                seen.add(content_key)
                deduplicated.append(r)

        return deduplicated
