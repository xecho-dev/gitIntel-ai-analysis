"""
Embeddings 服务 — 使用 DashScope text-embedding-v1 生成文本向量。

DashScope 与 OpenAI API 兼容，通过 httpx 直连 /embeddings 端点，
与 Chat 调用路径完全一致，保证认证方式一致。
"""

import os
import logging
from typing import Optional

import httpx

_logger = logging.getLogger("gitintel")


class DashScopeEmbedder:
    """使用 DashScope text-embedding-v1 生成文本向量。"""

    MODEL_NAME = "text-embedding-v1"
    DIMENSION = 1536  # text-embedding-v1 输出维度
    EMBEDDING_URL = "/embeddings"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """
        初始化 Embedder。

        Args:
            api_key: DashScope API 密钥，默认从 OPENAI_API_KEY 读取
            base_url: DashScope 端点，默认从 OPENAI_BASE_URL 读取
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL") or "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

        if not self.api_key:
            _logger.warning("[DashScopeEmbedder] 未设置 API 密钥，向量生成将不可用")
            self._available = False
        else:
            self._available = True
            key_preview = self.api_key[:8] + "..." if len(self.api_key) > 8 else "***"
            _logger.debug(f"[DashScopeEmbedder] 初始化完成: base_url={self.base_url}, api_key={key_preview}")

    @property
    def is_available(self) -> bool:
        """检查是否可用（已配置 API 密钥）。"""
        return self._available

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        同步生成文本向量（batch）。

        Args:
            texts: 文本列表

        Returns:
            向量列表，每个元素是对应文本的 1536 维向量
        """
        if not self._available:
            _logger.warning("[DashScopeEmbedder] 未可用，返回零向量")
            return [[0.0] * self.DIMENSION for _ in texts]

        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    f"{self.base_url.rstrip('/')}{self.EMBEDDING_URL}",
                    json={
                        "model": self.MODEL_NAME,
                        "input": texts,
                    },
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )

            if response.status_code != 200:
                _logger.error(
                    f"[DashScopeEmbedder] API 错误: status={response.status_code}, "
                    f"message={response.text}"
                )
                return [[0.0] * self.DIMENSION for _ in texts]

            data = response.json()
            embeddings = [item["embedding"] for item in data["data"]]
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
        vectors = self.embed([text])
        return vectors[0] if vectors else [0.0] * self.DIMENSION

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        embed() 的别名，保持与其他 embedding 库的接口一致。
        """
        return self.embed(texts)
