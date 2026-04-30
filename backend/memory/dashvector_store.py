"""
DashVector 向量存储实现 — GitIntel RAG 记忆层。

基于 LangChain 集成，提供优雅的向量存储和检索功能：
  - 存储分析洞察（suggestions）到向量数据库
  - 检索相似记忆（跨仓库经验 + 知识库）
  - 按仓库、类别、优先级过滤检索

使用 LangChain DashVector 的优势：
  - 统一的 VectorStore 接口
  - 自动化的集合管理和 schema 处理
  - 与 LangChain 生态无缝集成
"""

import os
import json
import logging
import hashlib
from typing import Optional, Any
from dataclasses import dataclass, field

from langchain_community.vectorstores import DashVector as LCDashVector
from langchain_community.embeddings import DashScopeEmbeddings

from .embeddings import DashScopeEmbedder

_logger = logging.getLogger("gitintel")


# ─── 常量 ────────────────────────────────────────────────────────────────────

DIMENSION = DashScopeEmbedder.DIMENSION  # 1536


# ─── 数据模型 ───────────────────────────────────────────────────────────────

@dataclass
class RAGDocument:
    """RAG 文档：可存储到向量库的分析洞察。

    支持多维度检索：
      - 按技术栈检索（React 项目、Python 项目）
      - 按问题类型检索（安全问题、性能问题）
      - 按场景检索（迁移经验、优化经验）
      - 按仓库检索（同一项目的历史分析）
    """

    repo_url: str
    category: str  # security | performance | architecture | dependency | testing | ...
    title: str
    content: str
    priority: str = "medium"

    # ── 技术栈维度（元数据）────────────────────────────────────
    tech_stack: list[str] = field(default_factory=list)  # ["react", "typescript", "next.js"]
    languages: list[str] = field(default_factory=list)   # ["TypeScript", "Python"]
    project_scale: str = ""  # small | medium | large

    # ── 核心价值：code_fix（精确修改方案）────────────────────
    code_fix: dict = field(default_factory=dict)
    # {
    #     "file": "src/utils/auth.ts",
    #     "type": "replace|add|remove",
    #     "original": "const password = 'hardcoded';",
    #     "updated": "const password = process.env.DB_PASSWORD;",
    #     "reason": "避免硬编码密码"
    # }

    # ── 问题上下文（帮助理解适用场景）─────────────────────────
    issue_type: str = ""      # N+1查询 | 硬编码密码 | 循环依赖 | ...
    verified: bool = False    # 是否经过工具验证

    # ── 标签与元数据 ──────────────────────────────────────────
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_text(self) -> str:
        """转换为用于生成向量的文本（保留完整语义）。"""
        parts = []

        # 1. 技术栈上下文（帮助向量检索到相似项目）
        if self.tech_stack:
            parts.append(f"技术栈: {', '.join(self.tech_stack)}")
        if self.languages:
            parts.append(f"语言: {', '.join(self.languages)}")
        if self.project_scale:
            parts.append(f"项目规模: {self.project_scale}")

        # 2. 核心内容（category + title + content）
        parts.append(f"[{self.category}] {self.title}")
        parts.append(self.content)

        # 3. code_fix（最有价值的部分）
        if self.code_fix:
            fix = self.code_fix
            parts.append("修改方案:")
            if fix.get("file"):
                parts.append(f"  文件: {fix.get('file')}")
            if fix.get("original"):
                parts.append(f"  原代码: {fix.get('original')[:100]}")
            if fix.get("updated"):
                parts.append(f"  修改后: {fix.get('updated')[:100]}")
            if fix.get("reason"):
                parts.append(f"  原因: {fix.get('reason')}")

        # 4. 问题类型（帮助检索）
        if self.issue_type:
            parts.append(f"问题类型: {self.issue_type}")

        # 5. 标签
        if self.tags:
            parts.append(f"标签: {', '.join(self.tags)}")

        return "\n".join(parts)

    def to_metadata(self) -> dict:
        """转换为元数据字典，用于 DashVector 存储。"""
        return {
            "repo_url": self.repo_url,
            "category": self.category,
            "title": self.title,
            "content": self.content,
            "priority": self.priority,
            # 技术栈维度
            "tech_stack": ",".join(self.tech_stack) if self.tech_stack else "",
            "languages": ",".join(self.languages) if self.languages else "",
            "project_scale": self.project_scale,
            # code_fix
            "code_fix": json.dumps(self.code_fix) if isinstance(self.code_fix, dict) else str(self.code_fix),
            "verified": "true" if self.verified else "false",
            # 问题上下文
            "issue_type": self.issue_type,
            # 标签与元数据
            "tags": ",".join(self.tags) if self.tags else "",
            "metadata": json.dumps(self.metadata) if isinstance(self.metadata, dict) else str(self.metadata),
        }

    def to_dict(self) -> dict:
        """to_metadata() 的别名，保持向后兼容。"""
        return self.to_metadata()


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

    # ── 新增字段 ──────────────────────────────────────────────
    tech_stack: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    project_scale: str = ""
    code_fix: dict = field(default_factory=dict)
    verified: bool = False
    issue_type: str = ""

    @classmethod
    def from_langchain_doc(cls, doc: Any, score: float) -> "SearchResult":
        """从 LangChain Document 对象转换。"""
        metadata = doc.metadata or {}

        # 解析 code_fix
        code_fix_raw = metadata.get("code_fix", "{}")
        if isinstance(code_fix_raw, str):
            try:
                code_fix = json.loads(code_fix_raw)
            except json.JSONDecodeError:
                code_fix = {}
        else:
            code_fix = code_fix_raw or {}

        # 解析 tags
        tags_str = metadata.get("tags", "")
        tags = tags_str.split(",") if tags_str else []

        # 解析技术栈
        tech_stack_str = metadata.get("tech_stack", "")
        tech_stack = tech_stack_str.split(",") if tech_stack_str else []

        languages_str = metadata.get("languages", "")
        languages = languages_str.split(",") if languages_str else []

        # 解析 verified
        verified_str = metadata.get("verified", "false")
        verified = verified_str.lower() == "true" if isinstance(verified_str, str) else bool(verified_str)

        return cls(
            id=metadata.get("id", doc.id) if hasattr(doc, "id") else str(hash(doc.page_content[:50])),
            score=score,
            repo_url=metadata.get("repo_url", ""),
            category=metadata.get("category", ""),
            title=metadata.get("title", ""),
            content=doc.page_content or metadata.get("content", ""),
            priority=metadata.get("priority", "medium"),
            tags=tags,
            metadata=metadata.get("metadata", {}),
            tech_stack=tech_stack,
            languages=languages,
            project_scale=metadata.get("project_scale", ""),
            code_fix=code_fix,
            verified=verified,
            issue_type=metadata.get("issue_type", ""),
        )


# ─── DashVector Store ────────────────────────────────────────────────────────

class DashVectorStore:
    """
    基于 DashVector 的向量存储实现（使用 LangChain 集成）。

    功能：
      - get_or_create_collection(): 获取或创建 Collection
      - upsert_documents(): 批量存储文档
      - retrieve_similar(): 向量相似度检索
      - retrieve_by_repo(): 检索同一仓库的历史记忆
      - retrieve_by_category(): 按类别检索
      - delete_by_repo(): 删除某仓库的所有记忆

    LangChain 集成优势：
      - 简化的 API（无需手动管理向量和 doc）
      - 自动化的 embedding 处理
      - 更清晰的代码结构
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
        self.api_key = api_key or os.getenv("DASHVECTOR_API_KEY")
        self.endpoint = endpoint or os.getenv("DASHVECTOR_ENDPOINT", "https://dashvector.aliyuncs.com")
        self.collection_name = collection_name or os.getenv("DASHVECTOR_COLLECTION", "gitintel_knowledge")
        self.embedder = embedder or DashScopeEmbedder()

        # LangChain VectorStore 实例（懒加载）
        self._vectorstore: Optional[LCDashVector] = None

        if not self.api_key:
            _logger.warning("[DashVectorStore] 未配置 DASHVECTOR_API_KEY，RAG 功能将不可用")
        else:
            _logger.info(
                f"[DashVectorStore] 初始化完成: endpoint={self.endpoint}, "
                f"collection={self.collection_name}"
            )

    @property
    def is_available(self) -> bool:
        """检查是否可用（已配置 API 密钥且 Embedder 可用）。"""
        return bool(self.api_key) and self.embedder.is_available

    def _get_vectorstore(self) -> Optional[LCDashVector]:
        """获取或初始化 LangChain VectorStore。"""
        if not self.is_available:
            return None

        if self._vectorstore is None:
            try:
                # 获取或创建 DashVector Collection
                from dashvector import Client, Collection

                client = Client(api_key=self.api_key, endpoint=self.endpoint)
                collection = client.get(self.collection_name)

                if collection is None:
                    # 创建新 Collection
                    collection = client.create(
                        name=self.collection_name,
                        dimension=DIMENSION,
                        metric="cosine",
                        fields_schema={
                            "repo_url": "str",
                            "category": "str",
                            "title": "str",
                            "content": "str",
                            "priority": "str",
                            "tech_stack": "str",
                            "languages": "str",
                            "project_scale": "str",
                            "code_fix": "str",
                            "verified": "str",
                            "issue_type": "str",
                            "tags": "str",
                            "metadata": "str",
                        },
                    )
                    _logger.info(f"[DashVectorStore] Collection 创建成功: {self.collection_name}")

                # 使用 LangChain DashVector 包装
                self._vectorstore = LCDashVector(
                    client=client,
                    collection_name=self.collection_name,
                    embedding=self.embedder._embeddings,  # 使用 LangChain Embeddings
                )

            except Exception as exc:
                _logger.error(f"[DashVectorStore] VectorStore 初始化失败: {exc}")
                return None

        return self._vectorstore

    # ─── Collection 管理 ──────────────────────────────────────────────────────

    def get_or_create_collection(self) -> Optional[Any]:
        """获取或创建 Collection（返回底层 dashvector.Collection）。"""
        if not self.api_key:
            return None

        try:
            from dashvector import Client

            client = Client(api_key=self.api_key, endpoint=self.endpoint)
            collection = client.get(self.collection_name)

            if collection is None:
                collection = client.create(
                    name=self.collection_name,
                    dimension=DIMENSION,
                    metric="cosine",
                    fields_schema={
                        "repo_url": "str",
                        "category": "str",
                        "title": "str",
                        "content": "str",
                        "priority": "str",
                        "tech_stack": "str",
                        "languages": "str",
                        "project_scale": "str",
                        "code_fix": "str",
                        "verified": "str",
                        "issue_type": "str",
                        "tags": "str",
                        "metadata": "str",
                    },
                )
                _logger.info(f"[DashVectorStore] Collection 创建成功: {self.collection_name}")

            return collection

        except Exception as exc:
            _logger.error(f"[DashVectorStore] Collection 获取/创建失败: {exc}")
            return None

    # ─── 文档存储 ─────────────────────────────────────────────────────────────

    def upsert_documents(self, docs: list[RAGDocument]) -> int:
        """
        批量存储文档（upsert，根据 doc_id 去重）。

        Args:
            docs: RAGDocument 列表

        Returns:
            成功存储的文档数量
        """
        if not docs:
            return 0

        collection = self.get_or_create_collection()
        if collection is None:
            return 0

        try:
            # 准备文本和元数据
            texts = [doc.to_text() for doc in docs]
            metadatas = [doc.to_metadata() for doc in docs]
            ids = [self._make_doc_id(doc) for doc in docs]

            # 使用 LangChain DashVector 的 add_texts 方法
            lc_store = self._get_vectorstore()
            if lc_store is None:
                return 0

            lc_store.add_texts(
                texts=texts,
                metadatas=metadatas,
                ids=ids,
            )

            _logger.info(f"[DashVectorStore] 存储了 {len(docs)} 个文档")
            return len(docs)

        except Exception as exc:
            _logger.error(f"[DashVectorStore] 存储文档失败: {exc}")
            return 0

    def store_suggestions(
        self,
        repo_url: str,
        suggestions: list[dict],
        category: str = "suggestion",
        tech_stack: list[str] = None,
        languages: list[str] = None,
        project_scale: str = "",
    ) -> int:
        """
        便捷方法：将分析建议存储为 RAG 文档（支持多维度）。

        Args:
            repo_url: 仓库 URL
            suggestions: SuggestionAgent 返回的 suggestions 列表
            category: 文档类别，默认 suggestion
            tech_stack: 技术栈列表（如 ["react", "typescript"]）
            languages: 语言列表（如 ["TypeScript", "Python"]）
            project_scale: 项目规模（small | medium | large）

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
                tech_stack=tech_stack or [],
                languages=languages or [],
                project_scale=project_scale,
                code_fix=sug.get("code_fix", {}),
                verified=sug.get("verified", False),
                issue_type=sug.get("type", ""),
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

    def store_analysis_result(
        self,
        repo_url: str,
        analysis_result: dict,
    ) -> dict:
        """
        综合存储完整分析结果（多维度批量存储）。

        存储内容：
          1. 优化建议（suggestion）— 每条建议独立存储
          2. 架构洞察（architecture）— concerns + patterns
          3. 依赖风险（dependency）— 高危依赖信息
          4. 技术栈特征（tech_stack）— 框架+语言+基础设施

        Args:
            repo_url: 仓库 URL
            analysis_result: final_result 完整分析结果

        Returns:
            {"success": bool, "counts": {"suggestions": int, "architecture": int, ...}}
        """
        total_stored = 0
        counts = {"suggestions": 0, "architecture": 0, "dependency": 0, "tech_stack": 0}

        # 提取元数据（各类型文档共用）
        tech_stack_data = analysis_result.get("tech_stack", {}) or {}
        code_parser_data = analysis_result.get("code_parser", {}) or {}

        # 解析技术栈
        tech_stack = self._extract_tech_stack(tech_stack_data)
        languages = tech_stack_data.get("languages", []) or []
        if isinstance(languages, list) and languages and not isinstance(languages[0], str):
            languages = [l.get("name", "") for l in languages if l.get("name")]

        # 项目规模
        total_files = code_parser_data.get("total_files", 0)
        project_scale = self._calc_project_scale(total_files)

        # ── 1. 存储优化建议 ──────────────────────────────────────
        suggestion_data = analysis_result.get("suggestion", {}) or {}
        suggestions = suggestion_data.get("suggestions", [])
        if suggestions:
            stored = self.store_suggestions(
                repo_url=repo_url,
                suggestions=suggestions,
                category="suggestion",
                tech_stack=tech_stack,
                languages=languages,
                project_scale=project_scale,
            )
            counts["suggestions"] = stored
            total_stored += stored

        # ── 2. 存储架构洞察 ─────────────────────────────────────
        arch_data = analysis_result.get("architecture", {}) or {}
        if arch_data:
            arch_docs = self._extract_architecture_insights(
                repo_url, arch_data, tech_stack, project_scale
            )
            if arch_docs:
                stored = self.upsert_documents(arch_docs)
                counts["architecture"] = stored
                total_stored += stored

        # ── 3. 存储依赖风险 ─────────────────────────────────────
        dep_data = analysis_result.get("dependency", {}) or {}
        if dep_data:
            dep_docs = self._extract_dependency_insights(
                repo_url, dep_data, tech_stack, languages, project_scale
            )
            if dep_docs:
                stored = self.upsert_documents(dep_docs)
                counts["dependency"] = stored
                total_stored += stored

        _logger.info(f"[DashVectorStore] 综合存储完成: repo={repo_url}, 共 {total_stored} 条")
        return {"success": True, "counts": counts, "total": total_stored}

    # ─── 辅助方法 ─────────────────────────────────────────────────────────────

    def _extract_tech_stack(self, tech_stack_result: dict) -> list[str]:
        """从 tech_stack_result 提取技术栈列表。"""
        techs = []
        frameworks = tech_stack_result.get("frameworks", []) or []
        if frameworks and isinstance(frameworks[0], dict):
            techs.extend([f.get("name", "") for f in frameworks if f.get("name")])
        else:
            techs.extend([str(f) for f in frameworks if f])

        infra = tech_stack_result.get("infrastructure", []) or []
        if isinstance(infra, list) and infra:
            if isinstance(infra[0], dict):
                techs.extend([i.get("name", "") for i in infra if i.get("name")])
            else:
                techs.extend([str(i) for i in infra if i])

        return [t for t in techs if t]

    def _calc_project_scale(self, total_files: int) -> str:
        """根据文件数量计算项目规模。"""
        if total_files > 500:
            return "large"
        elif total_files > 100:
            return "medium"
        else:
            return "small"

    def _extract_architecture_insights(
        self,
        repo_url: str,
        arch_data: dict,
        tech_stack: list[str],
        project_scale: str,
    ) -> list[RAGDocument]:
        """从架构分析结果中提取可存储的洞察。"""
        docs = []

        concerns = arch_data.get("concerns", []) or []
        for concern in concerns:
            if isinstance(concern, str):
                title = concern[:50] if len(concern) > 50 else concern
                content = concern
            elif isinstance(concern, dict):
                title = concern.get("title", concern.get("description", ""))[:50]
                content = concern.get("description", str(concern))
            else:
                continue

            if len(content) > 10:
                docs.append(RAGDocument(
                    repo_url=repo_url,
                    category="architecture",
                    title=f"架构问题: {title}",
                    content=content,
                    priority="medium",
                    tech_stack=tech_stack,
                    project_scale=project_scale,
                    issue_type="architecture",
                    verified=True,
                    tags=["architecture", "concern"],
                    metadata={"source": "architecture_analysis"},
                ))

        patterns = arch_data.get("patterns", []) or []
        for pattern in patterns:
            if isinstance(pattern, str):
                title = pattern[:50]
                content = pattern
            elif isinstance(pattern, dict):
                title = pattern.get("name", pattern.get("title", ""))[:50]
                content = pattern.get("description", str(pattern))
            else:
                continue

            if len(content) > 10:
                docs.append(RAGDocument(
                    repo_url=repo_url,
                    category="architecture",
                    title=f"架构模式: {title}",
                    content=content,
                    priority="low",
                    tech_stack=tech_stack,
                    project_scale=project_scale,
                    issue_type="pattern",
                    verified=True,
                    tags=["architecture", "pattern"],
                    metadata={"source": "architecture_analysis"},
                ))

        return docs

    def _extract_dependency_insights(
        self,
        repo_url: str,
        dep_data: dict,
        tech_stack: list[str],
        languages: list[str],
        project_scale: str,
    ) -> list[RAGDocument]:
        """从依赖分析结果中提取可存储的洞察。"""
        docs = []

        risky_deps = dep_data.get("risky_deps", []) or []
        if not risky_deps:
            all_deps = dep_data.get("deps", []) or []
            risky_deps = [
                d for d in all_deps
                if isinstance(d, dict) and d.get("risk_level") in ("high", "高危")
            ]

        for dep in risky_deps[:5]:
            if isinstance(dep, dict):
                name = dep.get("name", "unknown")
                version = dep.get("version", "*")
                risk = dep.get("risk_level", "unknown")
                reason = dep.get("reason", dep.get("description", ""))

                docs.append(RAGDocument(
                    repo_url=repo_url,
                    category="dependency",
                    title=f"高危依赖: {name}@{version}",
                    content=f"依赖 {name}@{version} 被标记为 {risk}。{reason}",
                    priority="high" if risk in ("high", "高危") else "medium",
                    tech_stack=tech_stack,
                    languages=languages,
                    project_scale=project_scale,
                    issue_type="vulnerable_dependency",
                    verified=True,
                    tags=["dependency", "security", "vulnerability"],
                    metadata={
                        "package": name,
                        "version": version,
                        "risk_level": risk,
                        "source": "dependency_analysis",
                    },
                ))

        outdated_deps = dep_data.get("outdated_deps", []) or []
        for dep in outdated_deps[:3]:
            if isinstance(dep, dict):
                name = dep.get("name", "")
                suggestion = dep.get("suggestion", dep.get("alternative", ""))

                docs.append(RAGDocument(
                    repo_url=repo_url,
                    category="dependency",
                    title=f"过时依赖: {name}",
                    content=f"依赖 {name} 已过时。迁移建议: {suggestion}",
                    priority="medium",
                    tech_stack=tech_stack,
                    languages=languages,
                    project_scale=project_scale,
                    issue_type="outdated_dependency",
                    verified=True,
                    tags=["dependency", "outdated", "migration"],
                    metadata={
                        "package": name,
                        "source": "dependency_analysis",
                    },
                ))

        return docs

    # ─── 检索 ─────────────────────────────────────────────────────────────────

    def retrieve_similar(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> list[SearchResult]:
        """
        向量相似度检索。

        Args:
            query: 查询文本
            top_k: 返回数量
            category: 可选，按类别过滤
            priority: 可选，按优先级过滤

        Returns:
            SearchResult 列表（按相似度降序）
        """
        collection = self.get_or_create_collection()
        if collection is None:
            return []

        try:
            # 使用 LangChain 的 similarity_search_with_score
            lc_store = self._get_vectorstore()
            if lc_store is None:
                return []

            # 构建过滤条件
            filter_dict = {}
            if category:
                filter_dict["category"] = category
            if priority:
                filter_dict["priority"] = priority

            # 执行检索
            if filter_dict:
                docs_and_scores = lc_store.similarity_search_with_score(
                    query,
                    k=top_k,
                    filter=filter_dict if filter_dict else None,
                )
            else:
                docs_and_scores = lc_store.similarity_search_with_score(
                    query,
                    k=top_k,
                )

            results = []
            for doc, score in docs_and_scores:
                results.append(SearchResult.from_langchain_doc(doc, score))

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
        collection = self.get_or_create_collection()
        if collection is None:
            return []

        try:
            # 使用 repo_url 作为过滤条件
            lc_store = self._get_vectorstore()
            if lc_store is None:
                return []

            docs_and_scores = lc_store.similarity_search_with_score(
                f"repo:{repo_url} analysis suggestion",
                k=top_k,
                filter={"repo_url": repo_url},
            )

            results = []
            for doc, score in docs_and_scores:
                results.append(SearchResult.from_langchain_doc(doc, score))

            return results

        except Exception as exc:
            _logger.error(f"[DashVectorStore] 按仓库检索失败: {exc}")
            return []

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

    def delete_by_repo(self, repo_url: str) -> bool:
        """
        删除某仓库的所有记忆。

        Args:
            repo_url: 仓库 URL

        Returns:
            是否成功
        """
        collection = self.get_or_create_collection()
        if collection is None:
            return False

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
