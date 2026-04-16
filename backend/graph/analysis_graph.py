"""
GitIntel 分析 Pipeline — LangGraph 工作流 + SSE 流式输出融合版。
"""
import asyncio
import logging
import concurrent.futures
from typing import Any, Generator

# 配置日志
logger = logging.getLogger("gitintel")

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END

from agents import (
    RepoLoaderAgent,
    GitHubPermissionError,
    CodeParserAgent,
    TechStackAgent,
    QualityAgent,
    DependencyAgent,
    SuggestionAgent,
    ArchitectureAgent,
)
from .state import SharedState
from .executor import (
    format_sse_event,
    format_sse_error,
    parse_repo_url,
    get_inputs_from_state,
    has_loader_result,
    run_agent_sync,
)

# ─── 全局 Checkpoint Saver ─────────────────────────────────────────────
# MemorySaver：内存版，适合单实例开发/演示
# 生产环境换 PostgresSaver + RedisSaver 实现持久化断点续传
# 用法示例（生产）：
#   from langgraph.checkpoint.postgres import PostgresSaver
#   from langgraph.checkpoint.redis import RedisSaver
#   _checkpointer = PostgresSaver.from_conn_string(DATABASE_URL)
#   _checkpointer = RedisSaver.from_url(REDIS_URL)
_checkpointer = MemorySaver()

# ─── 辅助函数 ───────────────────────────────────────────────────────────

PHASE_TIMEOUT = 120.0  # 每个主要阶段的最大执行时间（秒）


async def _run_with_timeout(
    coro,
    timeout: float,
    error_msg: str = "操作超时",
):
    """带超时的协程执行。

    Args:
        coro: 要执行的协程
        timeout: 超时时间（秒）
        error_msg: 超时时抛出的错误信息

    Returns:
        协程的返回值

    Raises:
        asyncio.TimeoutError: 超时时抛出
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        raise asyncio.TimeoutError(f"{error_msg}（超时 {timeout}秒）")


def _has_tree_and_classified(state: SharedState) -> bool:
    """判断是否已完成文件树获取和分类（断点恢复时跳过已完成的步骤）。"""
    return bool(state.get("repo_tree") and state.get("classified_files"))


def _get_inputs(state: SharedState) -> tuple[str, str, dict]:
    """从 SharedState 提取公共输入参数，供下游 Agent 使用。

    兼容两种来源：
      - loaded_files: 早期版本的合并结果
      - loaded_p0 + loaded_p1: 渐进式加载的结果
    """
    file_contents = (
        state.get("loaded_files") or
        state.get("loaded_p0") or
        state.get("loaded_p1") or
        {}
    )
    repo_id = state.get("local_path", "")
    if not repo_id:
        rlr = state.get("repo_loader_result")
        if rlr:
            repo_id = rlr.get("repo", "")
    branch = state.get("branch", "main")
    return repo_id, branch, file_contents


# ─── LangGraph 节点函数 ─────────────────────────────────────────────────
# 重要：这些是纯计算函数，接收 SharedState，返回更新的字段字典。
# 不要在这里写 yield（yield 是 SSE 层的事）。
# LangGraph 会自动合并返回的字典到状态中。


def node_fetch_tree_classify(state: SharedState) -> dict:
    """节点 1：获取文件树 + AI 分类 P0/P1/P2。

    两个子步骤：
      1. 调用 GitHub API 获取仓库完整文件树（tree_items, sha）
      2. 调用 LLM 根据文件路径预测优先级（P0=核心文件, P1=重要文件, P2=其他）

    断点恢复：如果 state 中已有 repo_tree/repo_sha，跳过 GitHub API 调用。
    """
    agent = RepoLoaderAgent()
    repo_url = state.get("repo_url", "")
    branch = state.get("branch", "main")

    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {
            "errors": [f"无法解析仓库 URL: {repo_url}"],
        }
    owner, repo = parsed

    # 断点恢复：已有数据则跳过 GitHub API 调用
    existing_tree = state.get("repo_tree")
    existing_sha = state.get("repo_sha")
    existing_classified = state.get("classified_files")

    # 1. 获取文件树（支持断点恢复）
    if existing_tree and existing_sha:
        tree_items = existing_tree
        sha = existing_sha
    else:
        result = asyncio.run(agent.phase_fetch_tree(owner, repo, branch))
        tree_items, sha = result
        if not sha or not tree_items:
            return {
                "errors": [],
            }

    # 2. LLM 分类（支持断点恢复）
    if existing_classified:
        classified = existing_classified
    else:
        classified, _ = asyncio.run(agent.phase_llm_classify(owner, repo, tree_items))

    # 3. 按优先级分离文件列表
    p0_files = [f for f in classified if f.get("priority", 2) == 0]
    p1_files = [f for f in classified if f.get("priority", 2) == 1]
    p2_files = [f for f in classified if f.get("priority", 2) == 2]

    return {
        "repo_tree": tree_items,
        "repo_sha": sha,
        "classified_files": classified,
        "pending_p0": p0_files,
        "pending_p1": p1_files,
        "pending_p2": p2_files,
        "repo_loader_result": {
            "owner": owner,
            "repo": repo,
            "branch": branch,
            "sha": sha,
            "total_tree_files": len(tree_items),
            "p0_count": len(p0_files),
            "p1_count": len(p1_files),
            "p2_count": len(p2_files),
        },
        "errors": [],
        "finished_agents": ["fetch_tree_classify"],
    }


def node_load_p0(state: SharedState) -> dict:
    """节点 2：加载 P0 核心文件（优先级最高，通常是入口/配置文件）。

    支持断点恢复：如果某些 P0 文件已加载，跳过重复加载。
    """
    if not _has_tree_and_classified(state):
        return {"errors": ["node_load_p0: 跳过（无分类结果）"]}

    repo_url = state.get("repo_url", "")
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {"errors": ["node_load_p0: 无法解析 URL"]}

    owner, repo = parsed
    sha = state.get("repo_sha", "")
    p0_files = state.get("pending_p0", [])
    existing_p0 = state.get("loaded_p0", {})

    # 跳过已加载的文件（断点恢复时用到）
    existing_paths = set(existing_p0.keys())
    missing_p0 = [f for f in p0_files if f.get("path") not in existing_paths]

    if not missing_p0:
        return {
            "loaded_p0": existing_p0,
            "errors": [],
            "finished_agents": ["load_p0"],
        }

    p0_contents = asyncio.run(
        RepoLoaderAgent().phase_load_priority(owner, repo, sha, missing_p0)
    )

    loaded_p0 = dict(existing_p0)
    loaded_p0.update(p0_contents)

    return {
        "loaded_p0": loaded_p0,
        "errors": [],
        "finished_agents": ["load_p0"],
    }


def node_code_parser_p0(state: SharedState) -> dict:
    """节点 3：AST 解析 P0 代码文件，提取函数/类/import 信息。

    使用 tree-sitter 做语言感知的代码结构解析（非简单正则）。
    结果供后续 AI 决策（P1/P2 是否需要加载）使用。
    """
    loaded_p0 = state.get("loaded_p0", {})
    if not loaded_p0:
        return {"errors": ["node_code_parser_p0: 跳过（无 P0 文件）"]}

    files = [{"path": path, "content": content} for path, content in loaded_p0.items()]
    result = asyncio.run(CodeParserAgent()._analyze_inmemory_files(files))

    return {
        "code_parser_p0_result": result,
        "errors": [],
        "finished_agents": ["code_parser_p0"],
    }


def node_decide_p1(state: SharedState) -> dict:
    """节点 4：AI 决策是否需要加载 P1 文件。

    基于 P0 的 AST 解析结果 + 文件路径，让 LLM 判断是否需要更多上下文。
    这是"渐进式加载"的核心——小仓库可能只需要 P0，大仓库才加载更多。

    Returns:
        needs_more: 是否需要加载 P1/P2
        ai_decision_reason: LLM 的判断理由
    """
    repo_url = state.get("repo_url", "")
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {
            "needs_more": False,
            "ai_decision_reason": "无法解析 URL",
            "errors": [],
            "finished_agents": ["decide_p1"],
        }

    owner, repo = parsed
    p0_result = state.get("code_parser_p0_result")
    p1_files = state.get("pending_p1", [])
    p2_files = state.get("pending_p2", [])
    loaded_p0 = state.get("loaded_p0", {})

    if not p1_files and not p2_files:
        return {
            "needs_more": False,
            "ai_decision_reason": "没有 P1/P2 文件需要加载",
            "errors": [],
            "finished_agents": ["decide_p1"],
        }

    need_more, extra_paths, reason = asyncio.run(
        RepoLoaderAgent().phase_ai_decide_p1(
            owner, repo,
            loaded=loaded_p0,
            code_parser_result=p0_result,
            p1_files=p1_files,
            p2_files=p2_files,
        )
    )

    return {
        "needs_more": need_more,
        "ai_decision_reason": reason,
        "iteration_count": state.get("iteration_count", 0) + 1,
        "errors": [],
        "finished_agents": ["decide_p1"],
    }


def node_load_p1(state: SharedState) -> dict:
    """节点 5：加载 P1 文件（AI 判断需要时才会执行）。"""
    repo_url = state.get("repo_url", "")
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {"errors": ["node_load_p1: 无法解析 URL"]}

    owner, repo = parsed
    sha = state.get("repo_sha", "")
    p1_files = state.get("pending_p1", [])
    existing_p1 = state.get("loaded_p1", {})

    existing_paths = set(existing_p1.keys())
    missing_p1 = [f for f in p1_files if f.get("path") not in existing_paths]

    if not missing_p1:
        return {
            "loaded_p1": existing_p1,
            "errors": [],
            "finished_agents": ["load_p1"],
        }

    p1_contents = asyncio.run(
        RepoLoaderAgent().phase_load_priority(owner, repo, sha, missing_p1)
    )

    loaded_p1 = dict(existing_p1)
    loaded_p1.update(p1_contents)

    return {
        "loaded_p1": loaded_p1,
        "errors": [],
        "finished_agents": ["load_p1"],
    }


def node_code_parser_p1(state: SharedState) -> dict:
    """节点 6：AST 解析 P1 代码（与 node_code_parser_p0 相同逻辑）。"""
    loaded_p1 = state.get("loaded_p1", {})
    if not loaded_p1:
        return {"errors": ["node_code_parser_p1: 跳过（无 P1 文件）"]}

    files = [{"path": path, "content": content} for path, content in loaded_p1.items()]
    result = asyncio.run(CodeParserAgent()._analyze_inmemory_files(files))

    return {
        "code_parser_p1_result": result,
        "errors": [],
        "finished_agents": ["code_parser_p1"],
    }


def node_load_p2_decide(state: SharedState) -> dict:
    """节点 7：AI 决策是否加载 P2 文件，以及具体加载哪些。

    与 node_decide_p1 类似，但基于 P0+P1 的综合结果做更精细的选择
    （P2 文件通常很多，AI 会挑选最有分析价值的部分）。
    """
    repo_url = state.get("repo_url", "")
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {
            "needs_more": False,
            "pending_p2": state.get("pending_p2", []),
            "errors": [],
            "finished_agents": ["load_p2_decide"],
        }

    owner, repo = parsed
    p1_result = state.get("code_parser_p1_result")
    loaded_p0 = state.get("loaded_p0", {})
    loaded_p1 = state.get("loaded_p1", {})
    p2_files = state.get("pending_p2", [])
    all_loaded = {**loaded_p0, **loaded_p1}

    if not p2_files:
        return {
            "needs_more": False,
            "pending_p2": [],
            "errors": [],
            "finished_agents": ["load_p2_decide"],
        }

    need_more, extra_paths, reason = asyncio.run(
        RepoLoaderAgent().phase_ai_decide_p2(
            owner, repo,
            loaded=all_loaded,
            code_parser_p0_result=state.get("code_parser_p0_result"),
            code_parser_p1_result=p1_result,
            p2_files=p2_files,
        )
    )

    extra_set = set(extra_paths)
    remaining_p2 = [f for f in p2_files if f.get("path") not in extra_set]

    return {
        "needs_more": need_more and bool(extra_paths),
        "pending_p2": remaining_p2,
        "ai_decision_reason": reason,
        "iteration_count": state.get("iteration_count", 0) + 1,
        "errors": [],
        "finished_agents": ["load_p2_decide"],
    }


def node_load_more_p2(state: SharedState) -> dict:
    """节点 8：按需加载 P2 文件（最多 50 个/轮，最多万能 3 轮）。

    这是 LangGraph 循环节点的典型用法：
      - load_p2_decide 判断 needs_more=True → 进入此节点
      - 此节点加载一批 P2 文件后，路由回 load_p2_decide 继续判断
      - 最多 3 轮后强制进入 code_parser_final（防止无限循环）
    """
    repo_url = state.get("repo_url", "")
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {
            "loaded_files": {**(state.get("loaded_p0", {})), **(state.get("loaded_p1", {}))},
            "errors": [],
            "finished_agents": ["load_more_p2"],
        }

    owner, repo = parsed
    sha = state.get("repo_sha", "")
    p2_files = state.get("pending_p2", [])

    if not p2_files:
        return {
            "loaded_files": {**(state.get("loaded_p0", {})), **(state.get("loaded_p1", {}))},
            "errors": [],
            "finished_agents": ["load_more_p2"],
        }

    p2_contents = asyncio.run(
        RepoLoaderAgent().phase_load_priority(owner, repo, sha, p2_files[:50])
    )

    all_loaded = {
        **(state.get("loaded_p0", {})),
        **(state.get("loaded_p1", {})),
        **p2_contents,
    }

    # 如果本轮加载完了所有 P2 文件（即 p2_files[50:] 为空），
    # 则重置 needs_more=False，让下一轮路由直接进入 code_parser_final，
    # 防止因为前一轮的 needs_more=True 残留导致无限循环。
    remaining = p2_files[50:]
    return {
        "loaded_files": all_loaded,
        "pending_p2": remaining,
        "needs_more": bool(remaining),
        "errors": [],
        "finished_agents": ["load_more_p2"],
    }


def node_code_parser_final(state: SharedState) -> dict:
    """节点 9：合并 P0 + P1 + P2 的 AST 解析结果，生成统一的 code_parser_result。

    这是进入并行分析阶段前的最后一步，确保所有文件都有解析数据。
    如果 P2 文件被加载但尚未解析，这里会补充解析。
    """
    p0_result = state.get("code_parser_p0_result") or {}
    p1_result = state.get("code_parser_p1_result") or {}
    loaded_files = state.get("loaded_files") or {**state.get("loaded_p0", {}), **state.get("loaded_p1", {})}

    # 合并统计字段
    merged_result = {
        "total_files": p0_result.get("total_files", 0) + p1_result.get("total_files", 0),
        "total_functions": p0_result.get("total_functions", 0) + p1_result.get("total_functions", 0),
        "total_classes": p0_result.get("total_classes", 0) + p1_result.get("total_classes", 0),
        "language_stats": {},
        "largest_files": [],
        "chunked_files": {},
        "total_chunks": 0,
    }

    # 合并 language_stats
    all_lang_stats = {}
    for lang_stat in [p0_result.get("language_stats", {}), p1_result.get("language_stats", {})]:
        for lang, stats in lang_stat.items():
            if lang not in all_lang_stats:
                all_lang_stats[lang] = stats.copy()
            else:
                for key in ["files", "functions", "classes", "imports", "total_lines"]:
                    all_lang_stats[lang][key] += stats.get(key, 0)
    merged_result["language_stats"] = all_lang_stats

    # 合并 largest_files（取最大的 10 个）
    all_largest = []
    all_largest.extend(p0_result.get("largest_files", []))
    all_largest.extend(p1_result.get("largest_files", []))
    all_largest.sort(key=lambda x: x.get("lines", 0), reverse=True)
    merged_result["largest_files"] = all_largest[:10]

    # 合并 chunked_files
    merged_result["chunked_files"] = {
        **p0_result.get("chunked_files", {}),
        **p1_result.get("chunked_files", {}),
    }
    merged_result["total_chunks"] = len(merged_result["chunked_files"])

    # 补充解析 P2 文件（如果被加载但未解析）
    loaded_count = len(loaded_files)
    parsed_count = p0_result.get("total_files", 0) + p1_result.get("total_files", 0)
    if loaded_count > parsed_count:
        parsed_paths = set(p0_result.get("chunked_files", {}).keys()) | set(p1_result.get("chunked_files", {}).keys())
        p2_files = {k: v for k, v in loaded_files.items() if k not in parsed_paths}
        if p2_files:
            p2_result = asyncio.run(
                CodeParserAgent()._analyze_inmemory_files(
                    [{"path": k, "content": v} for k, v in p2_files.items()]
                )
            )
            merged_result["total_files"] += p2_result.get("total_files", 0)
            merged_result["total_functions"] += p2_result.get("total_functions", 0)
            merged_result["total_classes"] += p2_result.get("total_classes", 0)
            merged_result["chunked_files"].update(p2_result.get("chunked_files", {}))
            merged_result["total_chunks"] += p2_result.get("total_chunks", 0)

    return {
        "code_parser_result": merged_result,
        "file_contents": loaded_files,
        "errors": [],
        "finished_agents": ["code_parser_final"],
    }


def node_merge_analysis(state: SharedState) -> dict:
    """节点 10：合并 TechStack + Quality + Dependency 并行分析结果。

    注意：真正的并行是在 LangGraph 的图定义中通过 add_edge 从同一个节点
    分发到三个节点实现的（见下方 _build_graph）。此节点在三者都完成后执行，
    主要做结果验证和错误收集。
    """
    tech_result = state.get("tech_stack_result") or {}
    quality_result = state.get("quality_result") or {}
    errors = []
    if not tech_result:
        errors.append("MergeAnalysis: TechStackAgent 结果为空")
    if not quality_result:
        errors.append("MergeAnalysis: QualityAgent 结果为空")

    return {
        "errors": errors,
    }


def node_tech_stack(state: SharedState) -> dict:
    """节点 11：技术栈识别（LangGraph 并行分支之一）。

    与 node_quality、node_dependency 同时执行，由 LangGraph 自动调度。
    """
    if not has_loader_result(state):
        return {
            "errors": ["TechStackAgent: 跳过（无加载结果）"],
        }

    repo_id, branch, file_contents = get_inputs_from_state(state)
    errors = []
    result = run_agent_sync(TechStackAgent(), repo_id, branch, file_contents=file_contents or None)

    if not result:
        errors.append("TechStackAgent: 执行返回空结果")

    return {
        "tech_stack_result": result,
        "errors": errors,
    }


def node_quality(state: SharedState) -> dict:
    """节点 12：代码质量评分（LangGraph 并行分支之一）。"""
    if not has_loader_result(state):
        return {
            "errors": ["QualityAgent: 跳过（无加载结果）"],
        }

    repo_id, branch, file_contents = get_inputs_from_state(state)
    errors = []
    result = run_agent_sync(QualityAgent(), repo_id, branch, file_contents=file_contents or None)

    if not result:
        errors.append("QualityAgent: 执行返回空结果")

    return {
        "quality_result": result,
        "errors": errors,
    }


def node_dependency(state: SharedState) -> dict:
    """节点 13：依赖风险分析（LangGraph 并行分支之一）。

    接收所有已加载的文件（含 p0 + p1 + 条件加载的 p2），
    由 DependencyAgent 自己通过 _is_dep_file() 过滤依赖配置文件。
    """
    if not has_loader_result(state):
        return {
            "errors": ["DependencyAgent: 跳过（无加载结果）"],
        }

    repo_id, branch, file_contents = get_inputs_from_state(state)
    errors = []
    result = run_agent_sync(
        DependencyAgent(),
        repo_id,
        branch,
        file_contents=file_contents or None,
    )

    if not result:
        errors.append("DependencyAgent: 执行返回空结果")

    return {
        "dependency_result": result,
        "errors": errors,
    }


def node_architecture(state: SharedState) -> dict:
    """节点 14：架构评估（基于 AST 结构 + TechStack + Quality + LLM）。

    在 tech_stack + quality + dependency 三个并行节点都完成后执行。
    ArchitectureAgent 综合代码结构、依赖关系、技术栈特征，给出架构评估。
    """
    repo_id, branch, file_contents = get_inputs_from_state(state)
    errors = []

    result = ArchitectureAgent.parse_and_build(
        repo_id,
        branch,
        code_parser_result=state.get("code_parser_result"),
        tech_stack_result=state.get("tech_stack_result"),
        quality_result=state.get("quality_result"),
        total_tree_files=len(state.get("repo_tree") or []),
    )

    if not result:
        errors.append("ArchitectureAgent: 执行返回空结果")

    return {
        "architecture_result": result,
        "errors": errors,
    }


def node_optimization(state: SharedState) -> dict:
    """节点 15：生成优化建议（综合所有分析结果的 LLM 驱动阶段）。

    这是整个 Pipeline 的最后一个分析节点。
    SuggestionAgent 接收：
      - 真实代码内容（file_contents）
      - 所有前置分析结果（code_parser / tech_stack / quality / dependency / architecture）
    输出针对项目实际情况的优化建议，而非通用建议。
    """
    repo_id, branch, _ = get_inputs_from_state(state)
    errors = []

    file_contents = (
        state.get("loaded_files") or
        {**state.get("loaded_p0", {}), **state.get("loaded_p1", {})}
    )

    result = run_agent_sync(
        SuggestionAgent(),
        repo_id,
        branch,
        file_contents=file_contents or None,
        code_parser_result=state.get("code_parser_result"),
        tech_stack_result=state.get("tech_stack_result"),
        quality_result=state.get("quality_result"),
        dependency_result=state.get("dependency_result"),
    )

    architecture_result = state.get("architecture_result") or {}
    final_result = {
        "repo_loader": state.get("repo_loader_result"),
        "code_parser": state.get("code_parser_result"),
        "tech_stack": state.get("tech_stack_result"),
        "quality": state.get("quality_result"),
        "dependency": state.get("dependency_result"),
        "architecture": architecture_result,
        "suggestion": result,
    }

    return {
        "optimization_result": result,
        "suggestion_result": result,
        "final_result": final_result,
        "errors": errors,
    }


def node_suggestion(state: SharedState) -> dict:
    """节点 16：优化建议（向后兼容别名，实际委托给 node_optimization）。"""
    return node_optimization(state)


# ─── 错误处理节点 ──────────────────────────────────────────────────────


def node_error(state: SharedState) -> dict:
    """错误处理节点：记录错误但不中断流程（LangGraph END 前的兜底）。"""
    return {
        "errors": ["Pipeline: 进入错误处理节点"],
    }


# ─── 条件路由函数 ──────────────────────────────────────────────────────
# 这些函数接收 SharedState，返回节点名称字符串。
# LangGraph 根据返回值决定下一步执行哪个节点。


def route_after_decide_p1(state: SharedState) -> str:
    """decide_p1 之后：根据 needs_more 判断是否加载 P1。

    - needs_more=True  → load_p1（加载 P1 文件后进入 code_parser_p1）
    - needs_more=False → load_p2_decide（跳过 P1，直接决策 P2）
    """
    if state.get("needs_more", False):
        return "load_p1"
    return "load_p2_decide"


def route_after_p2_decide(state: SharedState) -> str:
    """load_p2_decide 之后：根据 needs_more 判断是否加载更多 P2。

    - needs_more=True  → load_more_p2（加载一批 P2 后回到 load_p2_decide 再判断）
    - needs_more=False → code_parser_final（结束加载，进入并行分析）
    """
    if state.get("needs_more", False):
        return "load_more_p2"
    return "code_parser_final"


def route_p2_iteration(state: SharedState) -> str:
    """P2 迭代路由：限制最多 3 轮迭代，防止无限循环。

    iteration_count 在 node_decide_p1 和 node_load_p2_decide 中递增。
    3 轮后强制进入 code_parser_final。
    """
    iteration = state.get("iteration_count", 0)
    if iteration >= 3:
        return "code_parser_final"
    if state.get("needs_more", False):
        return "load_more_p2"
    return "code_parser_final"


# ─── 构建 LangGraph ─────────────────────────────────────────────────────


def _build_graph() -> StateGraph:
    """构建并编译 LangGraph 工作流。

    图结构说明：
      - add_edge(A, B): A 执行完后顺序执行 B
      - add_conditional_edges(A, router, {key: node}): A 执行完后
        调用 router(state)，根据返回值选择下一个节点
      - 多个 add_edge(from, to) 从同一节点出发 → LangGraph 并行执行这些 to 节点
        （Fan-out）；所有 to 节点都完成后，下一个 add_edge(to, X) 才会触发 X
        （Fan-in，等价于 join barrier）

    并行分析的实现：
      code_parser_final ─┬─► tech_stack
                          ├─► quality
                          └─► dependency
                          │
                          └── tech_stack/quality/dependency 全部完成后，各自的
                              add_edge(tech_stack, architecture) 等才触发，
                              所以三个并行节点都结束后才进入 architecture。
    """
    graph = StateGraph(state_schema=SharedState)

    # 节点注册
    graph.add_node("fetch_tree_classify", node_fetch_tree_classify)
    graph.add_node("load_p0", node_load_p0)
    graph.add_node("code_parser_p0", node_code_parser_p0)
    graph.add_node("decide_p1", node_decide_p1)
    graph.add_node("load_p1", node_load_p1)
    graph.add_node("code_parser_p1", node_code_parser_p1)
    graph.add_node("load_p2_decide", node_load_p2_decide)
    graph.add_node("load_more_p2", node_load_more_p2)
    graph.add_node("code_parser_final", node_code_parser_final)
    graph.add_node("tech_stack", node_tech_stack)
    graph.add_node("quality", node_quality)
    graph.add_node("dependency", node_dependency)
    graph.add_node("architecture", node_architecture)
    graph.add_node("merge_analysis", node_merge_analysis)
    graph.add_node("optimization", node_optimization)
    graph.add_node("error", node_error)

    # 入口
    graph.set_entry_point("fetch_tree_classify")

    # 线性流程
    graph.add_edge("fetch_tree_classify", "load_p0")
    graph.add_edge("load_p0", "code_parser_p0")
    graph.add_edge("code_parser_p0", "decide_p1")

    # P1 条件分支
    graph.add_conditional_edges(
        "decide_p1",
        route_after_decide_p1,
        {
            "load_p1": "load_p1",
            "load_p2_decide": "load_p2_decide",
        },
    )
    graph.add_edge("load_p1", "code_parser_p1")
    graph.add_edge("code_parser_p1", "load_p2_decide")

    # P2 条件分支 + 循环
    graph.add_conditional_edges(
        "load_p2_decide",
        route_after_p2_decide,
        {
            "load_more_p2": "load_more_p2",
            "code_parser_final": "code_parser_final",
        },
    )
    graph.add_conditional_edges(
        "load_more_p2",
        route_p2_iteration,
        {
            "load_more_p2": "load_more_p2",
            "code_parser_final": "code_parser_final",
        },
    )

    # 真正的并行分析（Fan-out / Fan-in）
    graph.add_edge("code_parser_final", "tech_stack")
    graph.add_edge("code_parser_final", "quality")
    graph.add_edge("code_parser_final", "dependency")

    # Fan-in：三个并行节点都完成后进入 architecture
    graph.add_edge("tech_stack", "architecture")
    graph.add_edge("quality", "architecture")
    graph.add_edge("dependency", "architecture")

    # 串行收尾
    graph.add_edge("architecture", "merge_analysis")
    graph.add_edge("merge_analysis", "optimization")

    # 结束
    graph.add_edge("optimization", END)
    graph.add_edge("error", END)

    return graph


# 编译后的工作流（全局单例，编译一次，重复使用）
_workflow = _build_graph().compile(checkpointer=_checkpointer)


# ══════════════════════════════════════════════════════════════════════════
#  SSE 流式输出层
#
#  使用 _workflow.astream() 按顺序遍历每个节点，
#  每次节点完成后通过 get_state() 获取最新状态快照，
#  根据节点名称和状态内容，显式 yield 对应的 SSE 事件。
#
#  为什么不用 astream_log()？
#    astream_log() 是 LangGraph 的调试/审计 API，设计目标是记录状态变更历史，
#    不是作为主要流式输出接口。实践证明它在节点返回复杂 dict 时捕获行为不稳定。
#    用 astream() + get_state() 更可靠，且 astream() 天然支持断点续传。
# ══════════════════════════════════════════════════════════════════════════


# 节点 → SSE percent 映射
_NODE_PERCENT: dict[str, int] = {
    "fetch_tree_classify": 25,
    "load_p0": 35,
    "code_parser_p0": 45,
    "decide_p1": 50,
    "load_p1": 60,
    "code_parser_p1": 65,
    "load_p2_decide": 68,
    "load_more_p2": 70,
    "code_parser_final": 75,
    "tech_stack": 82,
    "quality": 85,
    "dependency": 87,
    "architecture": 91,
    "merge_analysis": 93,
    "optimization": 100,
    "final_result": 100,
}


def _yield_sse_for_node(
    node_name: str,
    node_output: Any,
    config: dict,
    owner: str,
    repo: str,
    status_sent: set,
    result_sent: set,
) -> list[str]:
    """处理单个节点输出，生成 SSE 事件列表。"""
    try:
        fresh_state = _workflow.get_state(config).values
        if not fresh_state:
            raise ValueError("get_state 返回空状态")
        current_state = fresh_state
    except Exception as state_err:
        logger.warning(f"[stream_analysis_sse] get_state 失败: {state_err}，使用 node_output 作为 fallback")
        if isinstance(node_output, dict):
            current_state = node_output
        elif isinstance(node_output, list) and len(node_output) == 1 and isinstance(node_output[0], dict):
            current_state = node_output[0]
        else:
            current_state = {}

    try:
        return _state_to_sse_events(
            node_name=node_name,
            state=current_state,
            owner=owner,
            repo=repo,
            status_sent=status_sent,
            result_sent=result_sent,
        )
    except Exception as sse_err:
        logger.error(f"[stream_analysis_sse] SSE 事件生成失败: {sse_err}")
        return [format_sse_error("pipeline", f"SSE 生成异常: {str(sse_err)}")]


def stream_analysis_sse(
    repo_url: str,
    branch: str = "main",
    thread_id: str | None = None,
) -> Generator[str, None, None]:
    """SSE 流式接口：LangGraph 工作流 + 实时 SSE 事件。

    方案：
      1. 用 _workflow.astream() 遍历每个节点（支持断点续传）
      2. 每次节点完成后，调用 get_state() 获取最新完整状态
      3. 根据节点名 + 状态内容，显式 yield 对应的 SSE 事件
      4. tech_stack / quality / dependency 三个并行节点在
         astream() 内部真正并发执行，都完成后才进入下一节点

    注意：必须用同步生成器（def 而非 async def），因为 _workflow.astream() 是
    同步迭代器（内部虽有异步节点，但迭代本身是同步的）。若用 async def + async for，
    会导致迭代器协议错乱，所有事件无法正确 yield 到调用方。

    SSE 事件类型：
      - status: 阶段开始
      - progress: 阶段完成（含结果数据）
      - result: 最终/关键结果
      - error: 错误（不中断流程）
    """
    logger.info(f"[stream_analysis_sse] 开始: repo={repo_url}, branch={branch}, thread={thread_id}")

    parsed = parse_repo_url(repo_url)
    if not parsed:
        logger.error(f"[stream_analysis_sse] URL 解析失败: {repo_url}")
        yield format_sse_error("pipeline", f"无法解析仓库 URL: {repo_url}")
        yield "data: [DONE]\n\n"
        return

    owner, repo = parsed

    config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id or f"{repo_url}::{branch}",
        }
    }

    initial_state = build_initial_state(repo_url, branch)

    # ── 立即发送初始事件（让客户端立刻收到响应，而非等待第一个节点完成）──
    yield format_sse_event({
        "type": "status",
        "agent": "pipeline",
        "message": f"正在连接分析引擎，repo={owner}/{repo}...",
        "percent": 1,
        "data": {"repo_url": repo_url, "branch": branch},
    })

    # 用于记录已发送过 status 的节点（避免重复）
    status_sent: set[str] = set()

    # 已发送过 result 的关键节点（避免重复发送 optimization / final_result）
    result_sent: set[str] = set()

    try:
        # _workflow.astream() 返回 async generator，必须用 asyncio.run() 在线程中驱动。
        # 线程函数把每个 chunk 放入 Queue，同步生成器从 Queue 消费并 yield 给调用方。
        import queue as _queue_module
        q: Any = _queue_module.Queue()
        exc_info: list = []

        def run():
            try:
                logger.debug(f"[stream_analysis_sse] 线程启动")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                async def consume():
                    logger.debug(f"[stream_analysis_sse] consume 开始")
                    count = 0
                    async for chunk in _workflow.astream(initial_state, config=config):
                        q.put(chunk)
                        count += 1
                        logger.debug(f"[stream_analysis_sse] 线程 yield chunk {count}: {type(chunk).__name__}")
                    logger.info(f"[stream_analysis_sse] 线程 astream 完成，共 {count} 个 chunks")
                    q.put(None)  # 哨兵：表示迭代结束

                loop.run_until_complete(consume())
                loop.close()
            except Exception as e:
                import traceback
                logger.error(f"[stream_analysis_sse] 线程异常: {type(e).__name__}: {e}\n{traceback.format_exc()}")
                exc_info.append(e)
                q.put(None)

        import threading
        logger.debug(f"[stream_analysis_sse] 创建线程...")
        t = threading.Thread(target=run, daemon=True)
        t.start()
        logger.debug(f"[stream_analysis_sse] 线程已启动，waaitq.get()")

        while True:
            chunk = q.get()
            if chunk is None:
                logger.info(f"[stream_analysis_sse] 收到哨兵，退出循环")
                break
            logger.debug(f"[stream_analysis_sse] 主线程收到 chunk: {type(chunk).__name__}")
            for sse in _dispatch_chunk(chunk, config, owner, repo, status_sent, result_sent):
                yield sse

        if exc_info:
            raise exc_info[0]

        # 正常结束
        yield "data: [DONE]\n\n"

    except Exception as e:
        logger.error(f"[stream_analysis_sse] 异常: {type(e).__name__}: {e}")
        import traceback
        logger.error(f"[stream_analysis_sse] 堆栈: {traceback.format_exc()}")
        yield format_sse_error("pipeline", f"分析异常: {type(e).__name__}: {str(e)}")
        yield "data: [DONE]\n\n"


def _dispatch_chunk(
    chunk: Any,
    config: dict,
    owner: str,
    repo: str,
    status_sent: set[str],
    result_sent: set[str],
):
    """将 astream 迭代的 chunk 分发为 SSE 事件，yield 到外层生成器。"""
    # 检测版本：新版本返回 dict（含 type 字段），旧版本返回 tuple
    if isinstance(chunk, dict):
        # 检查是否有 langgraph 标准格式的 type 字段
        chunk_type = chunk.get("type", "")
        if chunk_type == "updates":
            node_data_map = chunk.get("data", {})
            if isinstance(node_data_map, dict):
                for node_name, node_output in node_data_map.items():
                    for sse in _yield_sse_for_node(node_name, node_output, config, owner, repo, status_sent, result_sent):
                        yield sse  # type: ignore[misc]
        elif chunk_type == "values":
            current_state = chunk.get("data", {})
            if isinstance(current_state, dict):
                for sse in _state_to_sse_events(
                    node_name="__checkpoint__",
                    state=current_state,
                    owner=owner,
                    repo=repo,
                    status_sent=status_sent,
                    result_sent=result_sent,
                ):
                    yield sse  # type: ignore[misc]
        else:
            # langgraph 1.x 直接返回 {node_name: node_output} 格式的 dict
            for node_name, node_output in chunk.items():
                for sse in _yield_sse_for_node(node_name, node_output, config, owner, repo, status_sent, result_sent):
                    yield sse  # type: ignore[misc]
    else:
        try:
            if len(chunk) == 2:
                node_name, node_output = chunk
                for sse in _yield_sse_for_node(node_name, node_output, config, owner, repo, status_sent, result_sent):
                    yield sse  # type: ignore[misc]
        except (TypeError, ValueError):
            logger.warning(f"[stream_analysis_sse] 无法解析 chunk: {type(chunk)}")


def _state_to_sse_events(
    node_name: str,
    state: dict,
    owner: str,
    repo: str,
    status_sent: set[str],
    result_sent: set[str],
) -> list[str]:
    """将 LangGraph 状态快照转换为对应的 SSE 事件列表。

    事件类型规则（与旧版 stream_analysis_sse 保持一致）：
      - status: 节点开始时发送（仅第一次）
      - progress: 节点完成时发送（包含结果数据）
      - result: dependency / final_result 使用 type="result"（供 collect() 收集保存）
      - error: 错误信息
    """
    events: list[str] = []

    # ── fetch_tree_classify ───────────────────────────────────────────
    if node_name == "fetch_tree_classify":
        tree_items = state.get("repo_tree") or []
        classified = state.get("classified_files") or []
        p0 = [f for f in classified if f.get("priority") == 0]
        p1 = [f for f in classified if f.get("priority") == 1]
        p2 = [f for f in classified if f.get("priority") == 2]

        # status：首次发送
        if "fetch_tree_classify" not in status_sent:
            status_sent.add("fetch_tree_classify")
            events.append(format_sse_event({
                "type": "status",
                "agent": "fetch_tree_classify",
                "message": f"正在获取 {owner}/{repo} 文件树...",
                "percent": 5,
                "data": None,
            }))

        if tree_items:
            events.append(format_sse_event({
                "type": "progress",
                "agent": "fetch_tree_classify",
                "message": f"获取文件树完成，共 {len(tree_items)} 个文件",
                "percent": 15,
                "data": {"total_files": len(tree_items)},
            }))
            events.append(format_sse_event({
                "type": "status",
                "agent": "fetch_tree_classify",
                "message": "正在进行 AI 分类...",
                "percent": 20,
                "data": None,
            }))
            events.append(format_sse_event({
                "type": "progress",
                "agent": "fetch_tree_classify",
                "message": f"AI 分类完成: P0={len(p0)}, P1={len(p1)}, P2={len(p2)}",
                "percent": 25,
                "data": {
                    "p0": len(p0), "p1": len(p1), "p2": len(p2),
                    "total_tree_files": len(tree_items),
                },
            }))

    # ── load_p0 ──────────────────────────────────────────────────────
    elif node_name == "load_p0":
        loaded_p0 = state.get("loaded_p0") or {}
        if "load_p0" not in status_sent:
            status_sent.add("load_p0")
            events.append(format_sse_event({
                "type": "status",
                "agent": "load_p0",
                "message": f"正在加载 {len(loaded_p0)} 个 P0 核心文件...",
                "percent": 30,
                "data": None,
            }))
        if loaded_p0:
            events.append(format_sse_event({
                "type": "progress",
                "agent": "load_p0",
                "message": f"P0 核心文件加载完成: {len(loaded_p0)} 个",
                "percent": 35,
                "data": {"loaded": len(loaded_p0)},
            }))

    # ── code_parser_p0 ──────────────────────────────────────────────
    elif node_name == "code_parser_p0":
        result = state.get("code_parser_p0_result") or {}
        if "code_parser_p0" not in status_sent:
            status_sent.add("code_parser_p0")
            events.append(format_sse_event({
                "type": "status",
                "agent": "code_parser_p0",
                "message": "正在解析 P0 代码结构...",
                "percent": 40,
                "data": None,
            }))
        events.append(format_sse_event({
            "type": "progress",
            "agent": "code_parser_p0",
            "message": f"P0 代码解析完成: {result.get('total_functions', 0)} 个函数, {result.get('total_classes', 0)} 个类",
            "percent": 45,
            "data": {
                "functions": result.get("total_functions"),
                "classes": result.get("total_classes"),
            },
        }))

    # ── decide_p1 ───────────────────────────────────────────────────
    elif node_name == "decide_p1":
        reason = state.get("ai_decision_reason") or ""
        if "decide_p1" not in status_sent:
            status_sent.add("decide_p1")
            events.append(format_sse_event({
                "type": "status",
                "agent": "decide_p1",
                "message": "正在等待 AI 决策是否加载更多文件...",
                "percent": 48,
                "data": None,
            }))
        events.append(format_sse_event({
            "type": "progress",
            "agent": "decide_p1",
            "message": f"AI 决策: {reason}",
            "percent": 50,
            "data": {"needs_more": state.get("needs_more", False), "reason": reason},
        }))

    # ── load_p1 ──────────────────────────────────────────────────────
    elif node_name == "load_p1":
        loaded_p1 = state.get("loaded_p1") or {}
        if "load_p1" not in status_sent:
            status_sent.add("load_p1")
            events.append(format_sse_event({
                "type": "status",
                "agent": "load_p1",
                "message": f"正在加载 {len(loaded_p1)} 个 P1 文件...",
                "percent": 55,
                "data": None,
            }))
        if loaded_p1:
            events.append(format_sse_event({
                "type": "progress",
                "agent": "load_p1",
                "message": f"P1 文件加载完成: {len(loaded_p1)} 个",
                "percent": 60,
                "data": {"loaded": len(loaded_p1)},
            }))

    # ── code_parser_p1 ──────────────────────────────────────────────
    elif node_name == "code_parser_p1":
        result = state.get("code_parser_p1_result") or {}
        if "code_parser_p1" not in status_sent:
            status_sent.add("code_parser_p1")
            events.append(format_sse_event({
                "type": "status",
                "agent": "code_parser_p1",
                "message": "正在解析 P1 代码结构...",
                "percent": 62,
                "data": None,
            }))
        events.append(format_sse_event({
            "type": "progress",
            "agent": "code_parser_p1",
            "message": "P1 代码解析完成",
            "percent": 65,
            "data": {
                "functions": result.get("total_functions"),
                "classes": result.get("total_classes"),
            },
        }))

    # ── load_p2_decide ──────────────────────────────────────────────
    elif node_name == "load_p2_decide":
        reason = state.get("ai_decision_reason") or ""
        if "load_p2_decide" not in status_sent:
            status_sent.add("load_p2_decide")
            events.append(format_sse_event({
                "type": "status",
                "agent": "load_p2_decide",
                "message": "正在等待 AI 决策 P2 文件...",
                "percent": 66,
                "data": None,
            }))
        events.append(format_sse_event({
            "type": "progress",
            "agent": "load_p2_decide",
            "message": f"AI P2 决策: {reason}",
            "percent": 68,
            "data": {"needs_more": state.get("needs_more", False), "reason": reason},
        }))

    # ── load_more_p2 ─────────────────────────────────────────────────
    elif node_name == "load_more_p2":
        loaded_files = state.get("loaded_files") or {}
        if "load_more_p2" not in status_sent:
            status_sent.add("load_more_p2")
            events.append(format_sse_event({
                "type": "status",
                "agent": "load_more_p2",
                "message": f"正在加载 P2 文件...",
                "percent": 69,
                "data": None,
            }))
        events.append(format_sse_event({
            "type": "progress",
            "agent": "load_more_p2",
            "message": f"P2 文件加载完成: {len(loaded_files)} 个",
            "percent": 70,
            "data": {"loaded": len(loaded_files)},
        }))

    # ── code_parser_final ────────────────────────────────────────────
    elif node_name == "code_parser_final":
        result = state.get("code_parser_result") or {}
        loaded_files = state.get("loaded_files") or {}
        if "code_parser_final" not in status_sent:
            status_sent.add("code_parser_final")
            events.append(format_sse_event({
                "type": "status",
                "agent": "code_parser_final",
                "message": f"正在合并解析 {len(loaded_files)} 个代码文件...",
                "percent": 72,
                "data": None,
            }))
        events.append(format_sse_event({
            "type": "progress",
            "agent": "code_parser_final",
            "message": f"代码解析完成: {result.get('total_files', len(loaded_files))} 个文件, {result.get('total_chunks', 0)} 个语义块",
            "percent": 75,
            "data": result,
        }))

    # ── tech_stack ─────────────────────────────────────────────────
    elif node_name == "tech_stack":
        result = state.get("tech_stack_result") or {}
        if "tech_stack" not in status_sent:
            status_sent.add("tech_stack")
            events.append(format_sse_event({
                "type": "status",
                "agent": "tech_stack",
                "message": "正在识别技术栈...",
                "percent": 76,
                "data": None,
            }))
        if result:
            events.append(format_sse_event({
                "type": "progress",
                "agent": "tech_stack",
                "message": "技术栈识别完成",
                "percent": 82,
                "data": result,
            }))

    # ── quality ─────────────────────────────────────────────────────
    elif node_name == "quality":
        result = state.get("quality_result") or {}
        if "quality" not in status_sent:
            status_sent.add("quality")
            events.append(format_sse_event({
                "type": "status",
                "agent": "quality",
                "message": "正在分析代码质量...",
                "percent": 76,
                "data": None,
            }))
        if result:
            events.append(format_sse_event({
                "type": "progress",
                "agent": "quality",
                "message": "代码质量分析完成",
                "percent": 85,
                "data": result,
            }))

    # ── dependency — 使用 type="result"（供 collect() 收集保存）────
    elif node_name == "dependency":
        if "dependency" not in status_sent:
            status_sent.add("dependency")
            events.append(format_sse_event({
                "type": "status",
                "agent": "dependency",
                "message": "正在分析依赖风险...",
                "percent": 76,
                "data": None,
            }))
        if "dependency" not in result_sent and state.get("dependency_result"):
            result_sent.add("dependency")
            result = state.get("dependency_result") or {}
            events.append(format_sse_event({
                "type": "result",
                "agent": "dependency",
                "message": "依赖风险分析完成（并行）",
                "percent": 87,
                "data": result,
            }))

    # ── architecture ────────────────────────────────────────────────
    elif node_name == "architecture":
        result = state.get("architecture_result") or {}
        if "architecture" not in status_sent:
            status_sent.add("architecture")
            events.append(format_sse_event({
                "type": "status",
                "agent": "architecture",
                "message": "正在评估项目架构...",
                "percent": 88,
                "data": None,
            }))
        if result:
            events.append(format_sse_event({
                "type": "progress",
                "agent": "architecture",
                "message": "架构评估完成",
                "percent": 91,
                "data": result,
            }))

    # ── merge_analysis ──────────────────────────────────────────────
    elif node_name == "merge_analysis":
        if "merge_analysis" not in status_sent:
            status_sent.add("merge_analysis")
            events.append(format_sse_event({
                "type": "status",
                "agent": "merge_analysis",
                "message": "正在合并分析结果...",
                "percent": 92,
                "data": None,
            }))

    # ── optimization / final_result ──────────────────────────────────
    elif node_name in ("optimization", "node_optimization", "suggestion"):
        # 获取 optimization 相关结果
        opt_result = state.get("optimization_result") or state.get("suggestion_result")
        final_result = state.get("final_result")

        if "optimization" not in status_sent:
            status_sent.add("optimization")
            events.append(format_sse_event({
                "type": "status",
                "agent": "optimization",
                "message": "正在生成优化建议...",
                "percent": 93,
                "data": None,
            }))

        # 发送 optimization result（供前端的 OptimizationAgentCard 展示）
        if opt_result and "optimization" not in result_sent:
            result_sent.add("optimization")
            events.append(format_sse_event({
                "type": "result",
                "agent": "optimization",
                "message": f"生成了优化建议",
                "percent": 98,
                "data": opt_result,
            }))

        # 发送 final_result（包含所有分析数据）
        if final_result and "final_result" not in result_sent:
            result_sent.add("final_result")
            events.append(format_sse_event({
                "type": "result",
                "agent": "final_result",
                "message": "全部分析完成",
                "percent": 100,
                "data": final_result,
            }))

    return events


# ─── 同步执行接口（向后兼容，非主要入口）────────────────────────────────


def run_analysis_sync(
    repo_url: str,
    branch: str = "main",
    thread_id: str | None = None,
) -> dict:
    """同步运行 LangGraph 工作流，直接返回最终结果（供非 SSE 场景使用）。

    使用 checkpointing：同一 thread_id 的请求可以恢复之前的状态。
    推荐用 stream_analysis_sse() 代替此方法（可实时看到进度）。

    Args:
        repo_url: GitHub 仓库 URL
        branch: 分支名（默认 main）
        thread_id: 可选的 thread ID

    Returns:
        final_result: 包含所有分析结果的字典
    """
    config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id or f"{repo_url}::{branch}",
        }
    }

    initial_state = build_initial_state(repo_url, branch)
    final_state = _workflow.invoke(initial_state, config=config)
    return final_state.get("final_result") or {}


def build_initial_state(repo_url: str, branch: str = "main") -> SharedState:
    """构建 LangGraph 初始状态。

    所有字段使用默认值，表示从头开始执行。
    如果 thread_id 已有 checkpoint，invoke 时会从 checkpoint 恢复而非用此初始状态。
    """
    return SharedState(
        repo_url=repo_url,
        branch=branch,
        local_path=None,
        file_contents={},
        repo_loader_result=None,
        repo_tree=None,
        repo_sha=None,
        classified_files=None,
        loaded_files={},
        pending_files=[],
        llm_decision_rounds=0,
        llm_decision_history=[],
        current_priority=0,
        pending_p0=[],
        pending_p1=[],
        pending_p2=[],
        loaded_p0={},
        loaded_p1={},
        needs_more=False,
        ai_decision_reason="",
        iteration_count=0,
        code_parser_result=None,
        code_parser_p0_result=None,
        code_parser_p1_result=None,
        tech_stack_result=None,
        quality_result=None,
        suggestion_result=None,
        final_result=None,
        errors=[],
        finished_agents=[],
    )
