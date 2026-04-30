"""
Embeddings 服务 — 使用 LangChain DashScopeEmbeddings 生成文本向量。

LangChain 集成优势：
  - 统一的 Embeddings 接口，支持多种后端
  - 自动重试、超时处理
  - 与 LangChain VectorStore 无缝集成
"""

import os
import logging
from typing import Optional

from langchain_community.embeddings import DashScopeEmbeddings

_logger = logging.getLogger("gitintel")


class DashScopeEmbedder:
    """使用 LangChain DashScopeEmbeddings 生成文本向量。"""

    MODEL_NAME = "text-embedding-v1"
    DIMENSION = 1536  # text-embedding-v1 输出维度

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """
        初始化 Embedder。

        Args:
            api_key: DashScope API 密钥，默认从环境变量读取
            base_url: DashScope 端点，默认使用国际版
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")

        if not self.api_key:
            _logger.warning("[DashScopeEmbedder] 未设置 API 密钥，向量生成将不可用")
            self._embeddings = None
            self._available = False
        else:
            try:
                init_kwargs = {
                    "dashscope_api_key": self.api_key,
                }
                if self.base_url:
                    init_kwargs["dashscope_api_base"] = self.base_url

                self._embeddings = DashScopeEmbeddings(**init_kwargs)
                self._available = True
                key_preview = self.api_key[:8] + "..." if len(self.api_key) > 8 else "***"
                _logger.debug(
                    f"[DashScopeEmbedder] 初始化完成: base_url={self.base_url or 'default'}, api_key={key_preview}"
                )
            except Exception as e:
                _logger.error(f"[DashScopeEmbedder] 初始化失败: {e}")
                self._embeddings = None
                self._available = False

    @property
    def is_available(self) -> bool:
        """检查是否可用（已配置 API 密钥且 Embedder 可用）。"""
        return self._available and self._embeddings is not None

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        同步生成文本向量（batch）。

        Args:
            texts: 文本列表

        Returns:
            向量列表，每个元素是对应文本的 1536 维向量
        """
        if not self.is_available:
            _logger.warning("[DashScopeEmbedder] 未可用，返回零向量")
            return [[0.0] * self.DIMENSION for _ in texts]

        try:
            embeddings = self._embeddings.embed_documents(texts)
            _logger.debug(f"[DashScopeEmbedder] 生成 {len(embeddings)} 个向量")
            return embeddings
        except Exception as exc:
            _logger.error(f"[DashScopeEmbedder] 生成向量失败: {exc}")
            return [[0.0] * self.DIMENSION for _ in texts]

    def embed_one(self, text: str) -> list[float]:
        """
        生成单个文本的向量。

        Args:
            text: 文本内容

        Returns:
            1536 维向量
        """
        if not self.is_available:
            return [0.0] * self.DIMENSION

        try:
            return self._embeddings.embed_query(text)
        except Exception as exc:
            _logger.error(f"[DashScopeEmbedder] 生成单个向量失败: {exc}")
            return [0.0] * self.DIMENSION

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        embed() 的别名，保持与其他 embedding 库的接口一致。
        """
        return self.embed(texts)
