"""
Agents — GitIntel Agent 层统一导出。

目录结构：
  agents/
  ├── __init__.py          # 本文件（统一导出）
  ├── base_agent.py        # 共享基类
  ├── react/               # ReAct 模式 Agent（当前主力）
  │   ├── repo_loader_agent.py  # ReActRepoLoaderAgent
  │   ├── suggestion_agent.py   # ReActSuggestionAgent
  │   └── explorers.py          # ExplorerOrchestrator
  └── legacy/              # 旧版渐进式加载 Agent（保留，不再使用）
      ├── repo_loader.py        # RepoLoaderAgent
      ├── code_parser.py       # CodeParserAgent
      ├── tech_stack.py        # TechStackAgent
      ├── quality.py           # QualityAgent
      ├── suggestion.py        # SuggestionAgent
      ├── dependency.py        # DependencyAgent
      ├── architecture.py      # ArchitectureAgent
      └── optimization.py      # OptimizationAgent

优先使用 ReAct 模式 Agent。
"""

# ─── 共享基类 ────────────────────────────────────────────────────────────────

from .base_agent import BaseAgent, AgentEvent, _make_event

# ─── ReAct 模式 Agent（主力）──────────────────────────────────────────────────

from .react import (
    ReActRepoLoaderAgent,
    ReActSuggestionAgent,
    ExplorerOrchestrator,
)

# ─── Legacy Agent（保留，不再使用）────────────────────────────────────────────

from .legacy import (
    RepoLoaderAgent,
    GitHubPermissionError,
    CodeParserAgent,
    TechStackAgent,
    QualityAgent,
    DependencyAgent,
    SuggestionAgent,
    ArchitectureAgent,
    OptimizationAgent,
)

__all__ = [
    # 共享
    "BaseAgent",
    "AgentEvent",
    "_make_event",
    # ReAct 模式
    "ReActRepoLoaderAgent",
    "ReActSuggestionAgent",
    "ExplorerOrchestrator",
    # Legacy
    "RepoLoaderAgent",
    "GitHubPermissionError",
    "CodeParserAgent",
    "TechStackAgent",
    "QualityAgent",
    "DependencyAgent",
    "SuggestionAgent",
    "ArchitectureAgent",
    "OptimizationAgent",
]
