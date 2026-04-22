"""统一的 LLM 工厂模块，支持 LangSmith 追踪 token 消耗。

使用方式:
    from utils.llm_factory import get_llm

    llm = get_llm()
    response = await llm.ainvoke([HumanMessage(content="...")])
"""
import logging
import os
from functools import lru_cache
from typing import Any

_logger = logging.getLogger("gitintel")

# ─── Token 使用量追踪 ────────────────────────────────────────────────────────

_total_input_tokens: int = 0
_total_output_tokens: int = 0
_total_calls: int = 0


class TokenTrackingCallback:
    """LangChain-compatible callback handler，统计每次 LLM 调用的 token 消耗。

    关键接口：
      - run_inline = False  → LangChain CallbackManager 据此决定是否内联处理
      - on_llm_end()        → LLM 调用完成时提取 usage_metadata 并累加
    """

    # LangChain CallbackManager 会检查此属性
    run_inline: bool = False
    # LangChain 内部回调管理器期望的属性（用于过滤和错误处理）
    ignore_chat_model: bool = False
    ignore_llm: bool = False
    ignore_retriever: bool = True
    ignore_custom: bool = True
    raise_error: bool = False

    def __init__(self, agent_name: str = "unknown"):
        self.agent_name = agent_name

    def on_chat_model_start(
        self, serialized: Any, messages: Any, **kwargs: Any
    ) -> None:
        """LangChain 要求：记录 chat model 启动事件。"""

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        """LLM 调用完成时提取 token 使用量。"""
        global _total_input_tokens, _total_output_tokens, _total_calls
        try:
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                usage = response.usage_metadata
                input_toks = usage.get("input_tokens", 0)
                output_toks = usage.get("output_tokens", 0)
            elif hasattr(response, "llm_output") and response.llm_output:
                usage = response.llm_output.get("token_usage", {})
                input_toks = usage.get("prompt_tokens", 0)
                output_toks = usage.get("completion_tokens", 0)
            else:
                input_toks = 0
                output_toks = 0

            _total_input_tokens += input_toks
            _total_output_tokens += output_toks
            _total_calls += 1

            _logger.debug(
                f"[TokenTracker][{self.agent_name}] "
                f"input={input_toks}, output={output_toks}, "
                f"total_session={_total_input_tokens + _total_output_tokens}"
            )
        except Exception as e:
            _logger.debug(f"[TokenTracker] 提取 usage 失败: {e}")

    def on_llm_error(self, error: Exception, **kwargs: Any) -> None:
        _logger.warning(f"[TokenTracker][{self.agent_name}] LLM 调用失败: {error}")


def get_token_stats() -> dict:
    """获取当前会话的 token 使用量统计。"""
    return {
        "total_input_tokens": _total_input_tokens,
        "total_output_tokens": _total_output_tokens,
        "total_tokens": _total_input_tokens + _total_output_tokens,
        "total_calls": _total_calls,
    }


def reset_token_stats():
    """重置 token 计数器（在每个新分析请求开始时调用）。"""
    global _total_input_tokens, _total_output_tokens, _total_calls
    _total_input_tokens = 0
    _total_output_tokens = 0
    _total_calls = 0


def _configure_langsmith_env():
    """配置 LangSmith 环境变量。"""
    tracing_enabled = os.getenv("LANGSMITH_TRACING", "").lower() in ("true", "1", "yes")
    api_key = os.getenv("LANGSMITH_API_KEY", "").strip()

    if not tracing_enabled or not api_key:
        return

    os.environ.setdefault("LANGSMITH_ENDPOINT", os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"))
    os.environ.setdefault("LANGSMITH_PROJECT", os.getenv("LANGSMITH_PROJECT", "default"))
    os.environ.setdefault("LANGSMITH_API_KEY", api_key)
    os.environ.setdefault("LANGSMITH_TRACING", "true")

    _logger.info(f"[LLMFactory] LangSmith 追踪已配置，项目: {os.getenv('LANGSMITH_PROJECT')}")


def _make_chatopenai(
    model: str | None,
    temperature: float,
    api_key: str,
    base_url: str | None,
    max_tokens: int | None,
):
    """创建 ChatOpenAI 实例（共享逻辑）。"""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model or os.getenv("OPENAI_MODEL", "qwen-plus-2025-04-28"),
        temperature=temperature,
        openai_api_key=api_key,
        base_url=base_url or os.getenv(
            "OPENAI_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        max_tokens=max_tokens,
        max_retries=10,
        timeout=120.0,
    )


def _resolve_max_tokens(max_tokens: int | None) -> int | None:
    if max_tokens is not None:
        return max_tokens
    env_max = os.getenv("MAX_OUTPUT_TOKENS", "").strip()
    return int(env_max) if env_max else 1024


@lru_cache
def get_llm(
    model: str | None = None,
    temperature: float = 0.2,
    base_url: str | None = None,
    max_tokens: int | None = None,
):
    """创建统一的 LLM 实例（单例模式）。"""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        _logger.debug("[LLMFactory] OPENAI_API_KEY 未配置，LLM 将不可用")
        return None

    _configure_langsmith_env()

    try:
        return _make_chatopenai(
            model=model,
            temperature=temperature,
            api_key=api_key,
            base_url=base_url,
            max_tokens=_resolve_max_tokens(max_tokens),
        )
    except Exception as exc:
        _logger.error(f"[LLMFactory] LLM 初始化失败: {exc}")
        return None


class LLMWithTracking:
    """带 Token 使用量追踪的 LLM 封装。

    通过 .with_config(callbacks=[TokenTrackingCallback(...)] 注入回调，
    用法与普通 ChatOpenAI 完全一致：
        llm = LLMWithTracking("ReActRepoLoader")
        result = await llm.bind_tools(tools).ainvoke(messages)
        result = await llm.ainvoke(messages)
    """

    def __init__(
        self,
        agent_name: str,
        model: str | None = None,
        temperature: float = 0.2,
        base_url: str | None = None,
        max_tokens: int | None = None,
    ):
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            self._llm = None
            self._callback = None
            return

        _configure_langsmith_env()

        self._llm = _make_chatopenai(
            model=model,
            temperature=temperature,
            api_key=api_key,
            base_url=base_url,
            max_tokens=_resolve_max_tokens(max_tokens),
        )
        self._callback = TokenTrackingCallback(agent_name=agent_name)

    def bind_tools(self, tools: list, **kwargs: Any):
        """绑定工具（支持 function calling）。

        Args:
            tools: LangChain tool 列表
            **kwargs: 透传给 bind_tools（如 strict=False 适配 DashScope 代码模型）
        """
        if self._llm is None:
            raise RuntimeError("LLM 不可用")
        kwargs.setdefault("strict", False)
        return self._llm.bind_tools(tools, **kwargs).with_config(
            callbacks=[self._callback]
        )

    async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
        """异步直接调用（无工具绑定）。"""
        if self._llm is None:
            raise RuntimeError("LLM 不可用")
        return await self._llm.with_config(callbacks=[self._callback]).ainvoke(
            messages, **kwargs
        )


def get_llm_with_tracking(
    agent_name: str,
    model: str | None = None,
    temperature: float = 0.2,
    base_url: str | None = None,
    max_tokens: int | None = None,
):
    """创建带 Token 使用量追踪的 LLM 实例。

    返回 LLMWithTracking 封装对象，用法与 ChatOpenAI 完全一致。
    如果 OPENAI_API_KEY 未配置，返回 None。
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    return LLMWithTracking(
        agent_name=agent_name,
        model=model,
        temperature=temperature,
        base_url=base_url,
        max_tokens=max_tokens,
    )


def get_llm_with_callback(callback_handler, model: str | None = None,
                            temperature: float = 0.2, max_tokens: int | None = None):
    """创建带自定义 callback 的 LLM 实例。"""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    _configure_langsmith_env()

    try:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model or os.getenv("OPENAI_MODEL", "qwen-plus-2025-04-28"),
            temperature=temperature,
            openai_api_key=api_key,
            base_url=os.getenv(
                "OPENAI_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            max_tokens=_resolve_max_tokens(max_tokens),
            callbacks=[callback_handler],
            max_retries=10,
            timeout=120.0,
        )
    except Exception:
        return None
