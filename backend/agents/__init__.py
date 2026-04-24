"""
Agents — GitIntel Agent 层统一导出。

目录结构：
  agents/
  ├── __init__.py              # 本文件（统一导出）
  ├── base_agent.py             # 共享基类
  ├── chat/                    # 多 Agent 协作问答系统（Supervisor + 4 专业 Agent）
  │   ├── __init__.py
  │   ├── base_chat_agent.py     # ChatAgent 基类
  │   ├── supervisor_agent.py     # Supervisor Agent（意图分类 + 路由）
  │   ├── knowledge_agent.py       # KnowledgeAgent（知识库问答）
  │   ├── code_agent.py          # CodeAgent（代码相关问题）
  │   ├── analysis_agent.py      # AnalysisAgent（分析结果查询）
  │   ├── general_agent.py       # GeneralAgent（通用问题）
  │   └── multi_agent_router.py  # 路由编排层
  ├── react/                    # ReAct 模式 Agent（当前主力）
  │   ├── repo_loader_agent.py  # ReActRepoLoaderAgent
  │   ├── suggestion_agent.py   # ReActSuggestionAgent
  │   └── explorers.py          # ExplorerOrchestrator
  └── legacy/                   # 旧版渐进式加载 Agent（保留，不再使用）
      ├── repo_loader.py        # RepoLoaderAgent
      ├── code_parser.py        # CodeParserAgent
      ├── tech_stack.py         # TechStackAgent
      ├── quality.py            # QualityAgent
      ├── suggestion.py         # SuggestionAgent
      ├── dependency.py         # DependencyAgent
      ├── architecture.py       # ArchitectureAgent
      └── optimization.py       # OptimizationAgent

优先使用 ReAct 模式 Agent（仓库分析）和 chat（问答聊天）。
"""

# ─── 共享基类 ────────────────────────────────────────────────────────────────

from .base_agent import BaseAgent, AgentEvent, _make_event

# ─── 多 Agent 协作问答系统 ──────────────────────────────────────────────────

from .chat import (
    ChatAgent,
    SupervisorAgent,
    KnowledgeAgent,
    CodeAgent,
    AnalysisAgent,
    GeneralAgent,
    MultiAgentRouter,
    multi_agent_chat_stream,
)

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
    # 多 Agent 协作问答
    "ChatAgent",
    "SupervisorAgent",
    "KnowledgeAgent",
    "CodeAgent",
    "AnalysisAgent",
    "GeneralAgent",
    "MultiAgentRouter",
    "multi_agent_chat_stream",
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
