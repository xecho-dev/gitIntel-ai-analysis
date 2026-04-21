"""
Legacy Agents — 旧版渐进式加载 Agent（保留但不再使用）。

这些 Agent 基于预设的 P0/P1/P2 渐进式加载流程，
由 LangGraph 工作流中的 `fetch_tree_classify → load_p0 → ... → code_parser_final`
链路驱动。

已迁移至 `react/` 的 ReAct 版本替代：
  - ReActRepoLoaderAgent   替代 RepoLoaderAgent
  - ReActSuggestionAgent  替代 SuggestionAgent
  - ExplorerOrchestrator  替代 TechStackAgent / QualityAgent / DependencyAgent

目录结构：
  legacy/
  ├── __init__.py          # 本文件
  ├── base_agent.py        # 共享基类（复制自 ../base_agent.py）
  ├── prompts.py           # LangChain Prompt 模板
  ├── repo_loader.py       # RepoLoaderAgent — P0/P1/P2 渐进加载
  ├── code_parser.py       # CodeParserAgent — tree-sitter AST 解析
  ├── tech_stack.py        # TechStackAgent — 技术栈识别
  ├── quality.py           # QualityAgent — 代码质量评分
  ├── suggestion.py        # SuggestionAgent — LLM 驱动的优化建议
  ├── dependency.py        # DependencyAgent — 依赖风险分析
  ├── architecture.py      # ArchitectureAgent — 架构评估
  └── optimization.py      # OptimizationAgent — 优化建议（委托 SuggestionAgent）
"""

from .base_agent import BaseAgent, AgentEvent, _make_event
from .repo_loader import RepoLoaderAgent, GitHubPermissionError
from .code_parser import CodeParserAgent
from .tech_stack import TechStackAgent
from .quality import QualityAgent
from .dependency import DependencyAgent
from .suggestion import SuggestionAgent
from .architecture import ArchitectureAgent
from .optimization import OptimizationAgent

__all__ = [
    "BaseAgent",
    "AgentEvent",
    "_make_event",
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
