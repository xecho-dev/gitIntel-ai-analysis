"""
GitIntel RAG Memory 模块 — 基于 Chroma 的向量存储和检索。

架构：
  - embeddings.py: 使用 LangChain DashScopeEmbeddings 生成文本向量
  - chromadb_store.py: Chroma 向量存储实现（基于 LangChain 集成）
  - multi_memory.py: 多层记忆系统（Working + Semantic + Knowledge）

两个 Collection 的职责：
  - gitintel_knowledge: RAG 知识库，存分析结果、建议、洞察（供检索生成用）
  - gitintel_memory:    聊天记忆，存 AI 助手对话历史（按 session_id 隔离）

环境变量：
  CHROMA_DATA_DIR: Chroma 数据持久化目录（默认 ./data/chroma）
  CHROMA_COLLECTION_KNOWLEDGE: 知识库 Collection 名称（默认 gitintel_knowledge）
  CHROMA_COLLECTION_MEMORY: 记忆 Collection 名称（默认 gitintel_memory）
  DASHSCOPE_API_KEY: DashScope API 密钥（用于 Embedding）
"""

from .embeddings import DashScopeEmbedder
from .chromadb_store import (
    ChromaStore,
    RAGDocument,
    SearchResult,
    COLLECTION_KNOWLEDGE,
    COLLECTION_MEMORY,
)
from .multi_memory import (
    MultiLayerMemory,
    ShortTermMemory,
    LongTermMemory,
    MemoryResult,
    ExtractedFact,
    FactType,
    UserProfile,
    UserProfileManager,
    create_multi_layer_memory,
    clear_short_term_cache,
    # 向后兼容别名
    WorkingMemory,
    SemanticMemory,
    KnowledgeMemory,
)

__all__ = [
    "DashScopeEmbedder",
    "ChromaStore",
    "RAGDocument",
    "SearchResult",
    "COLLECTION_KNOWLEDGE",
    "COLLECTION_MEMORY",
    # 多层记忆
    "MultiLayerMemory",
    "ShortTermMemory",
    "LongTermMemory",
    "MemoryResult",
    "ExtractedFact",
    "FactType",
    "UserProfile",
    "UserProfileManager",
    "create_multi_layer_memory",
    "clear_short_term_cache",
    # 向后兼容
    "WorkingMemory",
    "SemanticMemory",
    "KnowledgeMemory",
]
