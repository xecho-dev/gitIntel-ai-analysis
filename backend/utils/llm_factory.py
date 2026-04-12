"""统一的 LLM 工厂模块，支持 LangSmith 追踪 token 消耗。

使用方式:
    from utils.llm_factory import get_llm

    llm = get_llm()
    response = await llm.ainvoke([HumanMessage(content="...")])
"""
import logging
import os
from functools import lru_cache

_logger = logging.getLogger("gitintel")


def _configure_langsmith_env():
    """配置 LangSmith 环境变量。

    仅当 LANGSMITH_TRACING=true 且 LANGSMITH_API_KEY 已配置时启用。
    通过设置环境变量，让 LangChain 自动启用追踪。
    """
    tracing_enabled = os.getenv("LANGSMITH_TRACING", "").lower() in ("true", "1", "yes")
    api_key = os.getenv("LANGSMITH_API_KEY", "").strip()

    if not tracing_enabled or not api_key:
        return

    # LangChain 会自动读取这些环境变量
    os.environ.setdefault("LANGSMITH_ENDPOINT", os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"))
    os.environ.setdefault("LANGSMITH_PROJECT", os.getenv("LANGSMITH_PROJECT", "default"))
    os.environ.setdefault("LANGSMITH_API_KEY", api_key)
    os.environ.setdefault("LANGSMITH_TRACING", "true")

    _logger.info(
        f"[LLMFactory] LangSmith 追踪已配置，"
        f"项目: {os.getenv('LANGSMITH_PROJECT')}"
    )


@lru_cache
def get_llm(
    model: str | None = None,
    temperature: float = 0.2,
    base_url: str | None = None,
):
    """创建统一的 LLM 实例（单例模式）。

    自动检测并启用 LangSmith 追踪（需配置 LANGSMITH_TRACING 和 LANGSMITH_API_KEY）。

    Args:
        model: 模型名称，默认从 OPENAI_MODEL 环境变量读取
        temperature: 温度参数，默认 0.2
        base_url: API base URL，默认从 OPENAI_BASE_URL 环境变量读取

    Returns:
        配置好的 ChatOpenAI 实例，支持 LangSmith 追踪（如果已启用）
        如果 OPENAI_API_KEY 未配置，返回 None
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        _logger.debug("[LLMFactory] OPENAI_API_KEY 未配置，LLM 将不可用")
        return None

    # 首次调用时配置 LangSmith
    _configure_langsmith_env()

    try:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model or os.getenv("OPENAI_MODEL", "qwen-plus"),
            temperature=temperature,
            openai_api_key=api_key,
            base_url=base_url
            or os.getenv(
                "OPENAI_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        )
    except Exception as exc:
        _logger.error(f"[LLMFactory] LLM 初始化失败: {exc}")
        return None


def get_llm_with_callback(
    callback_handler,
    model: str | None = None,
    temperature: float = 0.2,
):
    """创建带自定义 callback 的 LLM 实例。

    用于需要单独追踪特定调用的场景（如每个 Agent 独立的追踪）。
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model or os.getenv("OPENAI_MODEL", "qwen-plus"),
            temperature=temperature,
            openai_api_key=api_key,
            base_url=os.getenv(
                "OPENAI_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            callbacks=[callback_handler],
        )
    except Exception:
        return None
