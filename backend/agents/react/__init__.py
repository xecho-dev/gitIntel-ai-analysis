"""
React Agents — 基于 ReAct 模式的智能 Agent。

所有 Agent 均通过 Thought → Action → Observation 循环自主探索仓库，
无需人工预设的 P0/P1/P2 流程。

目录结构：
  react/
  ├── __init__.py          # 本文件
  ├── base_agent.py        # 共享基类（复制自 ../base_agent.py）
  ├── repo_loader_agent.py # ReActRepoLoaderAgent — 智能仓库加载
  ├── suggestion_agent.py  # ReActSuggestionAgent — 可验证的优化建议
  └── explorers.py         # ExplorerOrchestrator + 子 Explorer
"""

from .base_agent import BaseAgent, AgentEvent, _make_event
from .repo_loader_agent import ReActRepoLoaderAgent
from .suggestion_agent import ReActSuggestionAgent
from .explorers import ExplorerOrchestrator

__all__ = [
    "BaseAgent",
    "AgentEvent",
    "_make_event",
    "ReActRepoLoaderAgent",
    "ReActSuggestionAgent",
    "ExplorerOrchestrator",
]
