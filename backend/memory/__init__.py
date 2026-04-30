"""
GitIntel RAG Memory 模块 — 基于 DashVector 的向量存储和检索。

架构：
  - embeddings.py: 使用 LangChain DashScopeEmbeddings 生成文本向量
  - dashvector_store.py: DashVector 向量存储实现（基于 LangChain 集成）
  - rag_memory.py: 高级 RAG 记忆接口，封装存储和检索逻辑

环境变量：
  DASHVECTOR_API_KEY: DashVector API 密钥
  DASHVECTOR_ENDPOINT: DashVector 服务地址（默认 dashvector.aliyuncs.com）
  DASHVECTOR_COLLECTION: Collection 名称（默认 gitintel_knowledge）
  DASHSCOPE_API_KEY: DashScope API 密钥（用于 Embedding）
"""

from .embeddings import DashScopeEmbedder
from .dashvector_store import DashVectorStore, RAGDocument, SearchResult

__all__ = [
    "DashScopeEmbedder",
    "DashVectorStore",
    "RAGDocument",
    "SearchResult",
]
