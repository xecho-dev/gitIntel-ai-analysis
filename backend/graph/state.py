"""
SharedState — LangGraph 工作流中所有 Agent 共享的状态结构。

渐进式加载流程设计：
  1. RepoLoader 获取文件树 + AI 分类 P0/P1/P2
  2. 加载 P0 → CodeParser 分析 → AI 决策是否需要 P1
  3. 需要 P1 → 加载 P1 → CodeParser 分析 → AI 决策是否需要更多
  4. 后续 Agent (TechStack, Quality, Suggestion)
"""
from typing import Optional

from typing_extensions import TypedDict


class SharedState(TypedDict, total=False):
    # ─── 入口参数 ─────────────────────────────────────────────
    repo_url: str
    branch: str
    auth_user_id: Optional[str]

    # ─── Stage 1: 仓库加载 ─────────────────────────────────────
    local_path: Optional[str]
    file_contents: dict[str, str]
    repo_loader_result: Optional[dict]
    # RepoLoader 多轮决策中间状态（支持 LangGraph checkpoint 断点续传）
    repo_tree: Optional[list[dict]]         # GitHub API 返回的原始文件树
    repo_sha: Optional[str]                  # 当前 commit SHA
    classified_files: Optional[list[dict]]    # 分类后的文件列表（含 priority）
    loaded_files: dict[str, str]             # 已加载的文件内容
    pending_files: list[dict]                 # 待加载的文件（LLM 决策后填充）
    llm_decision_rounds: int                # LLM 决策轮次
    llm_decision_history: list[dict]          # 历次 LLM 决策记录

    # ─── 渐进式加载状态（新增）────────────────────────────────
    current_priority: int                    # 当前加载优先级 (0=P0, 1=P1, 2=P2)
    pending_p0: list[dict]                   # 待加载的 P0 文件
    pending_p1: list[dict]                   # 待加载的 P1 文件
    pending_p2: list[dict]                   # 待加载的 P2 文件
    loaded_p0: dict[str, str]                # 已加载的 P0 文件内容
    loaded_p1: dict[str, str]                # 已加载的 P1 文件内容
    needs_more: bool                         # AI 决策：是否需要加载更多
    ai_decision_reason: str                  # AI 决策原因
    iteration_count: int                      # 渐进式迭代次数

    # ─── Stage 2: 代码结构解析 ─────────────────────────────────
    code_parser_result: Optional[dict]       # {total_files, total_functions, total_classes, language_stats, largest_files}
    code_parser_p0_result: Optional[dict]    # P0 文件的解析结果
    code_parser_p1_result: Optional[dict]    # P1 文件的解析结果（渐进式）

    # ─── Stage 3: 技术栈识别 ───────────────────────────────────
    tech_stack_result: Optional[dict]  # {languages, frameworks, infrastructure, dev_tools, package_manager, ...}

    # ─── Stage 4: 代码质量分析 ─────────────────────────────────
    quality_result: Optional[dict]  # {health_score, test_coverage, complexity, maintainability, python_metrics, typescript_metrics, ...}

    # ─── Stage 5: 优化建议生成 ─────────────────────────────────
    suggestion_result: Optional[dict]  # {suggestions, total, high_priority, medium_priority, low_priority}

    # ─── 最终聚合结果 ───────────────────────────────────────────
    final_result: Optional[dict]  # 全部结果打包，供前端展示

    # ─── 错误与元数据 ───────────────────────────────────────────
    errors: list[str]
    finished_agents: list[str]  # 已完成的 agent 名称列表
