"""
Graph — LangGraph 工作流包。

注意：analysis_graph 的导入是 lazy 的（在 __getattr__ 中），因为它依赖 agents 层，
直接导入会触发 agents → chat → graph → analysis_graph → agents 的循环依赖。
"""
from __future__ import annotations

import sys
from typing import Any

# 直接导入（这些模块不依赖 agents 层）
from .state import SharedState
from .chat_graph import chat_stream_sse, multi_agent_chat_stream, ChatState
from .executor import (
    format_sse_event,
    format_sse_error,
    parse_repo_url,
    get_inputs_from_state,
    has_loader_result,
    run_agent_sync,
)

# analysis_graph 相关的 lazy 导入（避免循环依赖）
_LAZY_SUBMODULES = {
    "stream_analysis_sse",
    "run_analysis_sync",
    "build_initial_state",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_SUBMODULES:
        from . import analysis_graph as _ag
        return getattr(_ag, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Chat graph
    "chat_stream_sse",
    "multi_agent_chat_stream",
    "ChatState",
    # State
    "SharedState",
    # Executor utilities
    "format_sse_event",
    "format_sse_error",
    "parse_repo_url",
    "get_inputs_from_state",
    "has_loader_result",
    "run_agent_sync",
]
