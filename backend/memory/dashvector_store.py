"""
DashVector 向量存储实现 — GitIntel RAG 记忆层。

支持：
  - 存储分析洞察（suggestions）到向量数据库
  - 检索相似记忆（跨仓库经验 + 知识库）
  - 按仓库、类别、优先级过滤检索

环境变量：
  DASHVECTOR_API_KEY: DashVector API 密钥
  DASHVECTOR_ENDPOINT: DashVector 服务地址（默认 dashvector.aliyuncs.com）
  DASHVECTOR_COLLECTION: Collection 名称（默认 gitintel_knowledge）
"""

import os
import json
import logging
import hashlib
from typing import Optional
from dataclasses import dataclass, field

import dashvector

from .embeddings import DashScopeEmbedder

_logger = logging.getLogger("gitintel")


# ─── 常量 ────────────────────────────────────────────────────────────────────

DIMENSION = DashScopeEmbedder.DIMENSION  # 1536


# ─── 数据模型 ────────────────────────────────────────────────────────────────

@dataclass
class RAGDocument:
    """RAG 文档：可存储到向量库的分析洞察。"""

    repo_url: str
    category: str
    title: str
    content: str
    priority: str = "medium"
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_text(self) -> str:
        """转换为用于生成向量的文本。"""
        parts = [f"[{self.category}] {self.title}", self.content]
        if self.tags:
            parts.append(f"标签: {', '.join(self.tags)}")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "repo_url": self.repo_url,
            "category": self.category,
            "title": self.title,
            "content": self.content,
            "priority": self.priority,
            "tags": ",".join(self.tags) if self.tags else "",
            "metadata": json.dumps(self.metadata) if isinstance(self.metadata, dict) else str(self.metadata),
        }


@dataclass
class SearchResult:
    """检索结果。"""

    id: str
    score: float
    repo_url: str
    category: str
    title: str
    content: str
    priority: str
    tags: list[str]
    metadata: dict

    @classmethod
    def from_dashvector_doc(cls, doc: "dashvector.Doc", score: float) -> "SearchResult":
        fields = doc.fields or {}
        tags_str = fields.get("tags", "")
        return cls(
            id=doc.id or "",
            score=score,
            repo_url=fields.get("repo_url", ""),
            category=fields.get("category", ""),
            title=fields.get("title", ""),
            content=fields.get("content", ""),
            priority=fields.get("priority", "medium"),
            tags=tags_str.split(",") if tags_str else [],
            metadata=fields.get("metadata", {}),
        )


# ─── DashVector Store ────────────────────────────────────────────────────────

class DashVectorStore:
    """
    基于 DashVector 的向量存储实现。

    功能：
      - get_or_create_collection(): 获取或创建 Collection
      - upsert_documents(): 批量存储文档
      - retrieve_similar(): 向量相似度检索
      - retrieve_by_repo(): 检索同一仓库的历史记忆
      - retrieve_by_category(): 按类别检索
      - delete_by_repo(): 删除某仓库的所有记忆
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        collection_name: Optional[str] = None,
        embedder: Optional[DashScopeEmbedder] = None,
    ):
        """
        初始化 DashVector Store。

        Args:
            api_key: DashVector API 密钥，默认从环境变量读取
            endpoint: DashVector 服务地址，默认 dashvector.aliyuncs.com
            collection_name: Collection 名称，默认 gitintel_knowledge
            embedder: Embedder 实例，默认创建新的 DashScopeEmbedder
        """
        self.api_key = api_key or os.getenv("DASHVECTOR_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.endpoint = endpoint or os.getenv("DASHVECTOR_ENDPOINT")
        self.collection_name = collection_name or os.getenv("DASHVECTOR_COLLECTION")
        self.embedder = embedder or DashScopeEmbedder(api_key=os.getenv("OPENAI_API_KEY"))

        if not self.api_key:
            _logger.warning("[DashVectorStore] 未配置 DASHVECTOR_API_KEY，RAG 功能将不可用")
            self._client: Optional[dashvector.Client] = None
        else:
            self._client = dashvector.Client(api_key=self.api_key, endpoint=self.endpoint)
            _logger.info(
                f"[DashVectorStore] 初始化完成: endpoint={self.endpoint}, "
                f"collection={self.collection_name}"
            )

    @property
    def is_available(self) -> bool:
        """检查是否可用（已配置 API 密钥且 Embedder 可用）。"""
        return self._client is not None and self.embedder.is_available

    # ─── Collection 管理 ──────────────────────────────────────────────────────

    def get_or_create_collection(self) -> Optional[dashvector.Collection]:
        """获取或创建 Collection（自动处理不存在的情况）。"""
        if not self._client:
            return None

        try:
            collection = self._client.get(self.collection_name)
            _logger.debug(f"[DashVectorStore] 获取 Collection: {self.collection_name}")
            return collection
        except dashvector.DashVectorException:
            _logger.info(f"[DashVectorStore] Collection 不存在，创建: {self.collection_name}")
            return self._create_collection()

    def _create_collection(self) -> Optional[dashvector.Collection]:
        """创建新的 Collection。"""
        if not self._client:
            return None

        try:
            collection = self._client.create(
                name=self.collection_name,
                dimension=DIMENSION,
                metric="cosine",
                fields_schema={
                    "repo_url": "str",
                    "category": "str",
                    "title": "str",
                    "content": "str",
                    "priority": "str",
                    "tags": "str",
                    "metadata": "str",
                },
            )
            _logger.info(f"[DashVectorStore] Collection 创建成功: {self.collection_name}")
            return collection
        except Exception as exc:
            _logger.error(f"[DashVectorStore] Collection 创建失败: {exc}")
            return None

    def _ensure_collection(func):
        """装饰器：确保 Collection 存在，必要时自动创建。"""
        def wrapper(self, *args, **kwargs):
            if not self.is_available:
                return None
            collection = self.get_or_create_collection()
            if collection is None:
                _logger.warning(f"[DashVectorStore] 无法获取 Collection: {self.collection_name}")
                return None
            return func(self, collection, *args, **kwargs)
        return wrapper

    # ─── 文档存储 ─────────────────────────────────────────────────────────────

    @_ensure_collection
    def upsert_documents(self, collection: dashvector.Collection, docs: list[RAGDocument]) -> int:
        """
        批量存储文档（upsert，根据 doc_id 去重）。

        Args:
            collection: DashVector Collection
            docs: RAGDocument 列表

        Returns:
            成功存储的文档数量
        """
        if not docs:
            return 0

        # 生成向量
        texts = [doc.to_text() for doc in docs]
        vectors = self.embedder.embed(texts)

        # 构建 dashvector.Doc
        dv_docs = []
        for doc, vector in zip(docs, vectors):
            doc_id = self._make_doc_id(doc)
            dv_doc = dashvector.Doc(
                id=doc_id,
                vector=vector,
                fields=doc.to_dict(),
            )
            dv_docs.append(dv_doc)

        try:
            collection.insert(dv_docs)
            _logger.info(f"[DashVectorStore] 存储了 {len(dv_docs)} 个文档")
            return len(dv_docs)
        except Exception as exc:
            _logger.error(f"[DashVectorStore] 存储文档失败: {exc}")
            return 0

    def store_suggestions(
        self,
        repo_url: str,
        suggestions: list[dict],
        category: str = "suggestion",
    ) -> int:
        """
        便捷方法：将分析建议存储为 RAG 文档。

        Args:
            repo_url: 仓库 URL
            suggestions: SuggestionAgent 返回的 suggestions 列表
            category: 文档类别，默认 suggestion

        Returns:
            成功存储的数量
        """
        if not suggestions:
            return 0

        docs = []
        for idx, sug in enumerate(suggestions):
            doc = RAGDocument(
                repo_url=repo_url,
                category=category,
                title=sug.get("title", f"Suggestion {idx}"),
                content=sug.get("description", ""),
                priority=sug.get("priority", "medium"),
                tags=[sug.get("category", ""), sug.get("type", "")],
                metadata={
                    "id": sug.get("id"),
                    "type": sug.get("type"),
                    "category": sug.get("category"),
                    "index": idx,
                },
            )
            docs.append(doc)

        return self.upsert_documents(docs)

    # ─── 检索 ─────────────────────────────────────────────────────────────────

    @_ensure_collection
    def retrieve_similar(
        self,
        collection: dashvector.Collection,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> list[SearchResult]:
        """
        向量相似度检索。

        Args:
            collection: DashVector Collection
            query: 查询文本
            top_k: 返回数量
            category: 可选，按类别过滤
            priority: 可选，按优先级过滤

        Returns:
            SearchResult 列表（按相似度降序）
        """
        # 生成向量
        query_vector = self.embedder.embed_one(query)

        # 构建过滤表达式
        filter_expr = self._build_filter(category=category, priority=priority)

        try:
            response = collection.query(
                vector=query_vector,
                topk=top_k,
                filter=filter_expr,
                output_fields=["repo_url", "category", "title", "content", "priority", "tags", "metadata"],
            )

            results = []
            if response and response.output:
                for doc in response.output:
                    score = 1 - doc.score
                    results.append(SearchResult.from_dashvector_doc(doc, score))

            _logger.debug(f"[DashVectorStore] 检索 query='{query}', 返回 {len(results)} 条")
            return results

        except Exception as exc:
            _logger.error(f"[DashVectorStore] 检索失败: {exc}")
            return []

    def retrieve_by_repo(
        self,
        repo_url: str,
        top_k: int = 10,
    ) -> list[SearchResult]:
        """
        检索同一仓库的历史记忆。

        Args:
            repo_url: 仓库 URL
            top_k: 返回数量

        Returns:
            SearchResult 列表
        """
        return self.retrieve_similar(
            query=f"repo:{repo_url} analysis suggestion",
            top_k=top_k,
        )

    def retrieve_best_practices(self, top_k: int = 3) -> list[SearchResult]:
        """
        检索最佳实践类记忆。

        Returns:
            SearchResult 列表
        """
        return self.retrieve_similar(
            query="best practice optimization architecture",
            top_k=top_k,
            category="best_practice",
        )

    # ─── 删除 ─────────────────────────────────────────────────────────────────

    @_ensure_collection
    def delete_by_repo(self, collection: dashvector.Collection, repo_url: str) -> bool:
        """
        删除某仓库的所有记忆。

        Args:
            collection: DashVector Collection
            repo_url: 仓库 URL

        Returns:
            是否成功
        """
        try:
            # 检索所有匹配的文档 ID
            all_ids = []
            top_k = 100
            offset = 0

            while True:
                response = collection.query(
                    vector=[0.0] * DIMENSION,
                    topk=top_k,
                    filter=f'repo_url == "{repo_url}"',
                    output_fields=["id"],
                )
                if not response or not response.output:
                    break

                ids = [doc.id for doc in response.output if doc.id]
                all_ids.extend(ids)

                if len(ids) < top_k:
                    break
                offset += top_k

            if all_ids:
                collection.delete(ids=all_ids)
                _logger.info(f"[DashVectorStore] 删除仓库 {repo_url} 的 {len(all_ids)} 条记忆")

            return True

        except Exception as exc:
            _logger.error(f"[DashVectorStore] 删除记忆失败: {exc}")
            return False

    # ─── 工具方法 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _make_doc_id(doc: RAGDocument) -> str:
        """根据文档内容生成唯一 ID。"""
        raw = f"{doc.repo_url}:{doc.category}:{doc.title}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _build_filter(category: Optional[str] = None, priority: Optional[str] = None) -> Optional[str]:
        """构建 DashVector 过滤表达式。"""
        parts = []
        if category:
            parts.append(f'category == "{category}"')
        if priority:
            parts.append(f'priority == "{priority}"')
        return " and ".join(parts) if parts else None
