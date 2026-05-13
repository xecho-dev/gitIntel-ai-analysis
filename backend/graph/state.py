"""
SharedState — LangGraph 工作流中所有 Agent 共享的状态结构。

当前流程（ReAct 纯模式）：
  1. react_loader: ReActRepoLoaderAgent 自主探索加载文件
  2. explorer: ExplorerOrchestrator 并行驱动多个 Explorer
  3. architecture: 基于 explorer 结果做架构评估
  4. react_suggestion: ReActSuggestionAgent 生成优化建议
"""
from typing import Annotated, Optional

from typing_extensions import TypedDict
from operator import add


class SharedState(TypedDict, total=False):
    # ─── 入口参数 ─────────────────────────────────────────────
    repo_url: str
    branch: str
    auth_user_id: Optional[str]
    repo_info: dict               # 仓库基本信息（来自 get_repo_info，包含 default_branch, languages 等）

    # ─── Stage 1: 仓库加载（ReAct 模式）──────────────────────
    file_contents: dict[str, str]          # 已加载的文件内容（path -> content）
    loaded_files: dict[str, str]           # 同 file_contents（ReActAgent 写入）
    loaded_paths: list[str]                # 已加载的文件路径列表
    repo_sha: Optional[str]                 # 当前 commit SHA
    file_summaries: dict                  # 文件提炼摘要（path -> FileSummary，大幅减少 Explorer token）
    repo_languages: list[str]              # GitHub API 代码语言（前3，来自 get_repo_info）
    all_tree_paths: list[str]             # 原始文件树所有文件路径（用于前端展示文件数）
    total_tree_files: int                 # 原始文件总数（all_tree_paths.length）

    # ─── ReAct 探索元数据 ─────────────────────────────────────
    react_events: list[dict]               # 推理步骤和事件（流式透传到 SSE）
    react_summary: str                      # ReAct 探索总结
    react_iterations: int                  # ReAct 探索轮次

    # ─── Stage 2: 代码结构解析 ────────────────────────────────
    code_parser_result: Optional[dict]       # CodeParserAgent 结果

    # ─── Stage 3: 并行 Explorer ──────────────────────────────
    explorer_result: Optional[dict]         # ExplorerOrchestrator 汇总结果
    explorer_events: list[dict]             # Explorer 中间事件（流式透传）
    tech_stack_result: Optional[dict]        # TechStackExplorer 结果
    quality_result: Optional[dict]          # QualityExplorer 结果
    dependency_result: Optional[dict]       # DependencyAgent 结果

    # ─── Stage 4: 架构评估 ───────────────────────────────────
    architecture_result: Optional[dict]      # ArchitectureAgent 结果
    architecture_events: list[dict]          # 架构评估中间事件

    # ─── Stage 5: 优化建议 ───────────────────────────────────
    suggestion_result: Optional[dict]        # 建议结果（别名：optimization_result）
    optimization_result: Optional[dict]        # 同上（optimization agent 使用）
    optimization_events: list[dict]          # 建议生成中间事件

    # ─── 最终聚合结果 ─────────────────────────────────────────
    final_result: Optional[dict]            # 全部结果打包，供前端展示

    # ─── Stage 6: 反思机制 ─────────────────────────────────────
    reflection_enabled: bool                # 是否启用反思机制
    reflection_round: int                   # 当前反思轮次
    reflection_history: list[dict]         # 反思历史记录
    reflection_results: dict[str, dict]    # 各节点的反思结果 {node_name: reflection_result}
    reflection_enabled_nodes: list[str]     # 需要反思的节点列表
    needs_reflection: bool                 # 是否需要进行反思
    last_reflection_confidence: float      # 上次反思的整体置信度

    # ─── 错误与元数据 ─────────────────────────────────────────
    errors: Annotated[list[str], add]       # 支持并行追加
    finished_agents: Annotated[list[str], add]  # 支持并行追加
