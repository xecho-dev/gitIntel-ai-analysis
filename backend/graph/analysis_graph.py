"""
LangGraph 工作流 — 编排 GitIntel 分析 Pipeline。

渐进式迭代流程拓扑：

  ┌─────────────────────────────────────────────────────────────┐
  │ node_fetch_tree_classify  ← 获取文件树 + AI 分类 P0/P1/P2  │
  └────────────────────────────┬──────────────────────────────┘
                               │ classified_files, repo_sha
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ node_load_p0  ← 加载 P0 核心文件                            │
  └────────────────────────────┬──────────────────────────────┘
                               │ loaded_p0
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ node_code_parser_p0  ← AST 解析 P0 代码                    │
  └────────────────────────────┬──────────────────────────────┘
                               │ code_parser_p0_result
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ node_decide_p1  ← AI 决策：是否需要加载 P1                  │
  └────────────────────────────┬──────────────────────────────┘
                    ┌──────────┴──────────┐
                   需要                   不需要
                    │                      │
                    ▼                      ▼
  ┌─────────────────────┐      ┌─────────────────────────────┐
  │ node_load_p1        │      │ node_load_p2_decide (跳过 P1)│
  │ (加载 P1 文件)       │      └─────────────┬───────────────┘
  └──────────┬──────────┘                    │
             │                               │
             ▼                               ▼
  ┌─────────────────────┐         ┌─────────────────────────────┐
  │ node_code_parser_p1 │         │ node_load_more_p2           │
  │ (AST 解析 P1)       │         │ (AI 决策后按需加载 P2)       │
  └──────────┬──────────┘         └─────────────┬───────────────┘
             │                                  │
             └──────────────┬────────────────────┘
                            ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ node_code_parser_final  ← 合并 P0+P1+P2 解析结果            │
  └────────────────────────────┬──────────────────────────────┘
                               │ code_parser_result
                               ▼
  ┌──────────────────┬──────────────────┐
  │ node_tech_stack  │  node_quality    │  ← 并行执行！
  │ (技术栈识别)      │  (代码质量评分)   │
  └────────┬─────────┴─────────┬────────┘
           │                   │
           └─────────┬──────────┘
                     ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ node_merge_analysis  ← 合并 TechStack + Quality 结果        │
  └────────────────────────────┬──────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ node_suggestion  ← 综合所有结果生成优化建议                  │
  └─────────────────────────────────────────────────────────────┘
                               ▼
                            [完成] → SSE DONE

关键特性：
  - 渐进式迭代：每个阶段由 AI 决定是否需要加载更多
  - 阶段性分析：CodeParser 在每个优先级加载后立即执行
  - 并行分析：TechStack + Quality 同时执行，节省 3-5 秒
  - 断点续传：每个节点执行后自动保存状态
  - 错误隔离：单个 Agent 失败不中断整个流程
"""
import asyncio
import json
import logging
import os
from typing import Any, AsyncGenerator, Awaitable, Coroutine, TypeVar

# 配置日志
logger = logging.getLogger("gitintel")

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END

from agents import (
    RepoLoaderAgent,
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


# ─── 全局 Checkpoint Saver（内存版，适合单实例；生产换 PostgreSQL） ───
_checkpointer = MemorySaver()


# ─── 辅助函数 ─────────────────────────────────────────────────────

T = TypeVar("T")


async def _run_with_timeout(
    coro: Coroutine[Any, Any, T],
    timeout: float,
    error_msg: str = "操作超时",
) -> T:
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
    """判断是否已完成文件树获取和分类。"""
    return bool(state.get("repo_tree") and state.get("classified_files"))


def _get_inputs(state: SharedState) -> tuple[str, str, dict]:
    """从 SharedState 提取公共输入参数。"""
    file_contents = (
        state.get("loaded_files") or
        state.get("loaded_p0") or
        state.get("loaded_p1") or
        {}
    )
    local_path = state.get("local_path", "")
    if not local_path:
        rlr = state.get("repo_loader_result")
        if rlr:
            local_path = rlr.get("repo", "")
    branch = state.get("branch", "main")
    return local_path, branch, file_contents


# ─── LangGraph 节点函数 ──────────────────────────────────────────

def node_fetch_tree_classify(state: SharedState) -> dict:
    """节点 1：获取文件树 + AI 分类 P0/P1/P2。"""
    agent = RepoLoaderAgent()
    repo_url = state.get("repo_url", "")
    branch = state.get("branch", "main")

    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {
            "errors": list(state.get("errors", [])) + [f"无法解析仓库 URL: {repo_url}"],
        }
    owner, repo = parsed

    # 检查断点状态
    existing_tree = state.get("repo_tree")
    existing_sha = state.get("repo_sha")
    existing_classified = state.get("classified_files")

    # ── 1.1: 获取文件树 ─────────────────────────────────────────
    if existing_tree and existing_sha:
        tree_items = existing_tree
        sha = existing_sha
    else:
        result = asyncio.run(agent.phase_fetch_tree(owner, repo, branch))
        tree_items, sha = result

        if not sha or not tree_items:
            return {
                "errors": list(state.get("errors", [])) + [f"无法获取 {repo_url} 的文件树"],
            }

    # ── 1.2: LLM 初始分类 ──────────────────────────────────────
    if existing_classified:
        classified = existing_classified
    else:
        classified, _ = asyncio.run(agent.phase_llm_classify(owner, repo, tree_items))

    # ── 1.3: 分离各优先级文件列表 ───────────────────────────────
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
        "errors": list(state.get("errors", [])),
        "finished_agents": list(state.get("finished_agents", [])) + ["fetch_tree_classify"],
    }


def node_load_p0(state: SharedState) -> dict:
    """节点 2：加载 P0 核心文件。"""
    if not _has_tree_and_classified(state):
        return {"errors": list(state.get("errors", [])) + ["node_load_p0: 跳过（无分类结果）"]}

    repo_url = state.get("repo_url", "")
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {"errors": list(state.get("errors", [])) + ["node_load_p0: 无法解析 URL"]}

    owner, repo = parsed
    sha = state.get("repo_sha", "")
    p0_files = state.get("pending_p0", [])
    existing_p0 = state.get("loaded_p0", {})

    # 跳过已加载的
    existing_paths = set(existing_p0.keys())
    missing_p0 = [f for f in p0_files if f.get("path") not in existing_paths]

    if not missing_p0:
        # 所有 P0 已加载
        return {
            "loaded_p0": existing_p0,
            "errors": list(state.get("errors", [])),
            "finished_agents": list(state.get("finished_agents", [])) + ["load_p0"],
        }

    p0_contents = asyncio.run(
        RepoLoaderAgent().phase_load_priority(owner, repo, sha, missing_p0)
    )

    loaded_p0 = dict(existing_p0)
    loaded_p0.update(p0_contents)

    return {
        "loaded_p0": loaded_p0,
        "errors": list(state.get("errors", [])),
        "finished_agents": list(state.get("finished_agents", [])) + ["load_p0"],
    }


def node_code_parser_p0(state: SharedState) -> dict:
    """节点 3：AST 解析 P0 代码。"""
    loaded_p0 = state.get("loaded_p0", {})
    if not loaded_p0:
        return {"errors": list(state.get("errors", [])) + ["node_code_parser_p0: 跳过（无 P0 文件）"]}

    files = [{"path": path, "content": content} for path, content in loaded_p0.items()]

    result = asyncio.run(
        CodeParserAgent()._analyze_inmemory_files(files)
    )

    return {
        "code_parser_p0_result": result,
        "errors": list(state.get("errors", [])),
        "finished_agents": list(state.get("finished_agents", [])) + ["code_parser_p0"],
    }


def node_decide_p1(state: SharedState) -> dict:
    """节点 4：AI 决策是否需要加载 P1。

    基于 P0 的解析结果，让 AI 决定是否需要加载 P1 文件。
    """
    repo_url = state.get("repo_url", "")
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {
            "needs_more": False,
            "ai_decision_reason": "无法解析 URL",
            "errors": list(state.get("errors", [])),
            "finished_agents": list(state.get("finished_agents", [])) + ["decide_p1"],
        }

    owner, repo = parsed
    p0_result = state.get("code_parser_p0_result")
    p1_files = state.get("pending_p1", [])
    p2_files = state.get("pending_p2", [])
    loaded_p0 = state.get("loaded_p0", {})

    if not p1_files and not p2_files:
        # 没有 P1/P2，跳过后续
        return {
            "needs_more": False,
            "ai_decision_reason": "没有 P1/P2 文件需要加载",
            "errors": list(state.get("errors", [])),
            "finished_agents": list(state.get("finished_agents", [])) + ["decide_p1"],
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
        "errors": list(state.get("errors", [])),
        "finished_agents": list(state.get("finished_agents", [])) + ["decide_p1"],
    }


def node_load_p1(state: SharedState) -> dict:
    """节点 5：加载 P1 文件。"""
    repo_url = state.get("repo_url", "")
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {"errors": list(state.get("errors", [])) + ["node_load_p1: 无法解析 URL"]}

    owner, repo = parsed
    sha = state.get("repo_sha", "")
    p1_files = state.get("pending_p1", [])
    existing_p1 = state.get("loaded_p1", {})

    # 跳过已加载的
    existing_paths = set(existing_p1.keys())
    missing_p1 = [f for f in p1_files if f.get("path") not in existing_paths]

    if not missing_p1:
        return {
            "loaded_p1": existing_p1,
            "errors": list(state.get("errors", [])),
            "finished_agents": list(state.get("finished_agents", [])) + ["load_p1"],
        }

    p1_contents = asyncio.run(
        RepoLoaderAgent().phase_load_priority(owner, repo, sha, missing_p1)
    )

    loaded_p1 = dict(existing_p1)
    loaded_p1.update(p1_contents)

    return {
        "loaded_p1": loaded_p1,
        "errors": list(state.get("errors", [])),
        "finished_agents": list(state.get("finished_agents", [])) + ["load_p1"],
    }


def node_code_parser_p1(state: SharedState) -> dict:
    """节点 6：AST 解析 P1 代码。"""
    loaded_p1 = state.get("loaded_p1", {})
    if not loaded_p1:
        return {"errors": list(state.get("errors", [])) + ["node_code_parser_p1: 跳过（无 P1 文件）"]}

    files = [{"path": path, "content": content} for path, content in loaded_p1.items()]

    result = asyncio.run(
        CodeParserAgent()._analyze_inmemory_files(files)
    )

    return {
        "code_parser_p1_result": result,
        "errors": list(state.get("errors", [])),
        "finished_agents": list(state.get("finished_agents", [])) + ["code_parser_p1"],
    }


def node_load_p2_decide(state: SharedState) -> dict:
    """节点 7：AI 决策 P2 文件。

    基于已加载的 P0/P1 结果，决定需要加载哪些 P2 文件。
    """
    repo_url = state.get("repo_url", "")
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {
            "needs_more": False,
            "pending_p2": state.get("pending_p2", []),
            "errors": list(state.get("errors", [])),
            "finished_agents": list(state.get("finished_agents", [])) + ["load_p2_decide"],
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
            "errors": list(state.get("errors", [])),
            "finished_agents": list(state.get("finished_agents", [])) + ["load_p2_decide"],
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

    # 过滤出需要加载的 P2 文件
    extra_set = set(extra_paths)
    remaining_p2 = [f for f in p2_files if f.get("path") not in extra_set]

    return {
        "needs_more": need_more and bool(extra_paths),
        "pending_p2": remaining_p2,
        "ai_decision_reason": reason,
        "iteration_count": state.get("iteration_count", 0) + 1,
        "errors": list(state.get("errors", [])),
        "finished_agents": list(state.get("finished_agents", [])) + ["load_p2_decide"],
    }


def node_load_more_p2(state: SharedState) -> dict:
    """节点 8：按需加载 P2 文件。"""
    repo_url = state.get("repo_url", "")
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {
            "loaded_files": {**(state.get("loaded_p0", {})), **(state.get("loaded_p1", {}))},
            "errors": list(state.get("errors", [])),
            "finished_agents": list(state.get("finished_agents", [])) + ["load_more_p2"],
        }

    owner, repo = parsed
    sha = state.get("repo_sha", "")
    p2_files = state.get("pending_p2", [])

    if not p2_files:
        return {
            "loaded_files": {**(state.get("loaded_p0", {})), **(state.get("loaded_p1", {}))},
            "errors": list(state.get("errors", [])),
            "finished_agents": list(state.get("finished_agents", [])) + ["load_more_p2"],
        }

    p2_contents = asyncio.run(
        RepoLoaderAgent().phase_load_priority(owner, repo, sha, p2_files[:50])
    )

    # 合并所有已加载文件
    all_loaded = {
        **(state.get("loaded_p0", {})),
        **(state.get("loaded_p1", {})),
        **p2_contents,
    }

    return {
        "loaded_files": all_loaded,
        "pending_p2": p2_files[50:],  # 保留未加载的
        "errors": list(state.get("errors", [])),
        "finished_agents": list(state.get("finished_agents", [])) + ["load_more_p2"],
    }


def node_code_parser_final(state: SharedState) -> dict:
    """节点 9：合并所有代码解析结果。"""
    p0_result = state.get("code_parser_p0_result") or {}
    p1_result = state.get("code_parser_p1_result") or {}
    loaded_files = state.get("loaded_files") or {**state.get("loaded_p0", {}), **state.get("loaded_p1", {})}

    # 合并统计
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

    # 合并 largest_files
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

    # 如果有 P2 文件被加载，也要包含它们的解析结果
    loaded_count = len(loaded_files)
    parsed_count = p0_result.get("total_files", 0) + p1_result.get("total_files", 0)
    if loaded_count > parsed_count:
        # 有额外的 P2 文件被加载
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
        "errors": list(state.get("errors", [])),
        "finished_agents": list(state.get("finished_agents", [])) + ["code_parser_final"],
    }


def node_merge_analysis(state: SharedState) -> dict:
    """节点 10：合并 TechStack + Quality 并行分析结果。

    TechStackAgent 和 QualityAgent 已并行执行完毕，
    此节点负责合并两者结果，供 SuggestionAgent 使用。
    """
    tech_result = state.get("tech_stack_result") or {}
    quality_result = state.get("quality_result") or {}
    errors = list(state.get("errors", []))

    # 检查是否有任何一个失败
    if not tech_result:
        errors.append("MergeAnalysis: TechStackAgent 结果为空")
    if not quality_result:
        errors.append("MergeAnalysis: QualityAgent 结果为空")

    return {
        "errors": errors,
        "finished_agents": list(state.get("finished_agents", [])) + ["merge_analysis"],
    }


def node_tech_stack(state: SharedState) -> dict:
    """节点 11：技术栈识别（并行分支）。"""
    if not has_loader_result(state):
        return {
            "errors": list(state.get("errors", [])) + ["TechStackAgent: 跳过（无加载结果）"],
            "finished_agents": list(state.get("finished_agents", [])),
        }

    repo_id, branch, file_contents = get_inputs_from_state(state)
    errors = list(state.get("errors", []))

    result = run_agent_sync(TechStackAgent(), repo_id, branch, file_contents=file_contents or None)

    if not result:
        errors.append("TechStackAgent: 执行返回空结果")

    return {
        "tech_stack_result": result,
        "errors": errors,
        "finished_agents": list(state.get("finished_agents", [])) + ["tech_stack"],
    }


def node_quality(state: SharedState) -> dict:
    """节点 12：代码质量评分（并行分支）。"""
    if not has_loader_result(state):
        return {
            "errors": list(state.get("errors", [])) + ["QualityAgent: 跳过（无加载结果）"],
            "finished_agents": list(state.get("finished_agents", [])),
        }

    repo_id, branch, file_contents = get_inputs_from_state(state)
    errors = list(state.get("errors", []))

    result = run_agent_sync(QualityAgent(), repo_id, branch, file_contents=file_contents or None)

    if not result:
        errors.append("QualityAgent: 执行返回空结果")

    return {
        "quality_result": result,
        "errors": errors,
        "finished_agents": list(state.get("finished_agents", [])) + ["quality"],
    }


def node_dependency(state: SharedState) -> dict:
    """节点 13：依赖风险分析（并行分支）。"""
    if not has_loader_result(state):
        return {
            "errors": list(state.get("errors", [])) + ["DependencyAgent: 跳过（无加载结果）"],
            "finished_agents": list(state.get("finished_agents", [])),
        }

    repo_id, branch, file_contents = get_inputs_from_state(state)
    errors = list(state.get("errors", []))

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
        "finished_agents": list(state.get("finished_agents", [])) + ["dependency"],
    }


def node_architecture(state: SharedState) -> dict:
    """节点 14：架构评估（并行分支，基于 AST + TechStack + Quality + LLM）。"""
    repo_id, branch, file_contents = get_inputs_from_state(state)
    errors = list(state.get("errors", []))

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
        "finished_agents": list(state.get("finished_agents", [])) + ["architecture"],
    }


def node_optimization(state: SharedState) -> dict:
    """节点 15：优化建议（基于 SuggestionAgent，传入真实代码内容 + 所有分析结果）。"""
    repo_id, branch, _ = get_inputs_from_state(state)
    errors = list(state.get("errors", []))

    # 合并所有已加载的代码文件内容，供 LLM 做深度分析
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

    # 聚合最终结果（含架构）
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
        "finished_agents": list(state.get("finished_agents", [])) + ["optimization"],
    }


def node_suggestion(state: SharedState) -> dict:
    """节点 16：综合所有前置结果（向后兼容，委托给 node_optimization）。"""
    return node_optimization(state)


# ─── 错误处理节点 ─────────────────────────────────────────────────

def node_error(state: SharedState) -> dict:
    """错误处理节点：记录错误但不中断流程。"""
    return {
        "errors": list(state.get("errors", [])) + ["Pipeline: 进入错误处理节点"],
    }


# ─── 条件路由函数 ─────────────────────────────────────────────────

def route_after_decide_p1(state: SharedState) -> str:
    """P1 决策后，根据 AI 判断决定下一步。"""
    if state.get("needs_more", False):
        return "load_p1"
    # 不需要 P1，跳到 P2 决策
    return "load_p2_decide"


def route_after_p2_decide(state: SharedState) -> str:
    """P2 决策后，根据是否需要加载更多决定下一步。"""
    if state.get("needs_more", False):
        return "load_more_p2"
    # 不需要更多 P2，进入最终解析
    return "code_parser_final"


def route_p2_iteration(state: SharedState) -> str:
    """P2 迭代路由：限制最多 3 轮迭代。"""
    iteration = state.get("iteration_count", 0)
    if iteration >= 3:
        return "code_parser_final"
    if state.get("needs_more", False):
        return "load_more_p2"
    return "code_parser_final"


# ─── 构建 LangGraph ───────────────────────────────────────────────

def _build_graph() -> StateGraph:
    """构建并编译带 checkpointing 的渐进式 LangGraph 工作流。

    并行优化：TechStack + Quality 节点从 code_parser_final 分支，
    两者并行执行后汇聚到 merge_analysis 节点，再进入 suggestion。
    """
    graph = StateGraph(state_schema=SharedState)

    # ── 添加节点 ──────────────────────────────────────────────────
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

    # ── 入口 ──────────────────────────────────────────────────────
    graph.set_entry_point("fetch_tree_classify")

    # ── 线性流程：fetch → load_p0 → parse_p0 ──────────────────────
    graph.add_edge("fetch_tree_classify", "load_p0")
    graph.add_edge("load_p0", "code_parser_p0")
    graph.add_edge("code_parser_p0", "decide_p1")

    # ── 条件分支：decide_p1 → load_p1 或 load_p2_decide ───────────
    graph.add_conditional_edges(
        "decide_p1",
        route_after_decide_p1,
        {
            "load_p1": "load_p1",
            "load_p2_decide": "load_p2_decide",
        },
    )

    # ── load_p1 → parse_p1 → load_p2_decide ──────────────────────
    graph.add_edge("load_p1", "code_parser_p1")
    graph.add_edge("code_parser_p1", "load_p2_decide")

    # ── 条件分支：P2 决策 ──────────────────────────────────────────
    graph.add_conditional_edges(
        "load_p2_decide",
        route_after_p2_decide,
        {
            "load_more_p2": "load_more_p2",
            "code_parser_final": "code_parser_final",
        },
    )

    # ── load_more_p2 循环回 P2 决策（最多 3 轮）────────────────────
    graph.add_conditional_edges(
        "load_more_p2",
        route_p2_iteration,
        {
            "load_more_p2": "load_more_p2",  # 继续迭代
            "code_parser_final": "code_parser_final",
        },
    )

    # ── 并行分析阶段：code_parser_final → tech_stack + quality + dependency ───
    # Fan-out: 三个节点并行执行
    graph.add_edge("code_parser_final", "tech_stack")
    graph.add_edge("code_parser_final", "quality")
    graph.add_edge("code_parser_final", "dependency")

    # Fan-in: 三个节点都完成后进入架构评估
    graph.add_edge("tech_stack", "architecture")
    graph.add_edge("quality", "architecture")
    graph.add_edge("dependency", "architecture")

    # ── 架构评估完成后合并 ─────────────────────────────────────────
    graph.add_edge("architecture", "merge_analysis")

    # ── 最终阶段 ──────────────────────────────────────────────────
    graph.add_edge("merge_analysis", "optimization")

    # ── 结束 ──────────────────────────────────────────────────────
    graph.add_edge("optimization", END)
    graph.add_edge("error", END)

    return graph


_workflow = _build_graph().compile(
    checkpointer=_checkpointer,
)


# ─── SSE 流式接口 ─────────────────────────────────────────────────

async def stream_analysis_sse(
    repo_url: str,
    branch: str = "main",
    thread_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """运行渐进式 Pipeline，以 SSE 格式流式输出每个 Agent 的事件。

    Args:
        repo_url: GitHub 仓库 URL
        branch: 分支名（默认 main）
        thread_id: 可选的 thread ID，用于 checkpointing 恢复
    """
    # 阶段超时配置（秒）
    PHASE_TIMEOUT = 120  # 每个主要阶段的最大执行时间

    logger.info(f"[stream_analysis_sse] 开始分析: repo_url={repo_url}, branch={branch}")

    try:
        async for event in _stream_analysis_impl(repo_url, branch, thread_id, PHASE_TIMEOUT):
            yield event
    except Exception as e:
        logger.error(f"[stream_analysis_sse] 未捕获异常: {type(e).__name__}: {e}")
        yield format_sse_error("pipeline", f"分析异常: {type(e).__name__}: {str(e)}")
        yield "data: [DONE]\n\n"


async def _stream_analysis_impl(
    repo_url: str,
    branch: str,
    thread_id: str | None,
    PHASE_TIMEOUT: float,
) -> AsyncGenerator[str, None]:
    """stream_analysis_sse 的内部实现，所有核心逻辑在这里。"""
    logger.info(f"[_stream_analysis_impl] 入口")

    parsed = parse_repo_url(repo_url)
    if not parsed:
        logger.error(f"[stream_analysis_sse] URL 解析失败: {repo_url}")
        yield format_sse_error("pipeline", f"无法解析仓库 URL: {repo_url}")
        yield "data: [DONE]\n\n"
        return

    owner, repo = parsed
    logger.info(f"[stream_analysis_sse] URL 解析成功: owner={owner}, repo={repo}")

    # ── Step 1: fetch_tree_classify ───────────────────────────────
    loader = RepoLoaderAgent()

    # 发送开始状态
    yield format_sse_event({
        "type": "status",
        "agent": "fetch_tree_classify",
        "message": f"正在获取 {owner}/{repo} 文件树...",
        "percent": 5,
        "data": None,
    })

    try:
        tree_items, sha = await _run_with_timeout(
            loader.phase_fetch_tree(owner, repo, branch),
            timeout=PHASE_TIMEOUT,
            error_msg="获取文件树超时"
        )
        logger.info(f"[stream_analysis_sse] 文件树获取完成: {len(tree_items)} 个文件, sha={sha}")
        yield format_sse_event({
            "type": "progress",
            "agent": "fetch_tree_classify",
            "message": f"获取文件树完成，共 {len(tree_items)} 个文件",
            "percent": 15,
            "data": {"total_files": len(tree_items)},
        })
    except Exception as e:
        logger.error(f"[stream_analysis_sse] 获取文件树异常: {e}")
        yield format_sse_error("fetch_tree_classify", f"获取文件树失败: {str(e)}")
        yield "data: [DONE]\n\n"
        return

    if not tree_items or not sha:
        yield format_sse_error("pipeline", "仓库加载失败，无法继续分析")
        yield "data: [DONE]\n\n"
        return

    # LLM 分类
    yield format_sse_event({
        "type": "status",
        "agent": "fetch_tree_classify",
        "message": "正在进行 AI 分类...",
        "percent": 20,
        "data": None,
    })

    classified, _ = await _run_with_timeout(
        loader.phase_llm_classify(owner, repo, tree_items),
        timeout=PHASE_TIMEOUT,
        error_msg="AI 分类超时"
    )
    p0 = [f for f in classified if f.get("priority") == 0]
    p1 = [f for f in classified if f.get("priority") == 1]
    p2 = [f for f in classified if f.get("priority") == 2]
    yield format_sse_event({
        "type": "progress",
        "agent": "fetch_tree_classify",
        "message": f"AI 分类完成: P0={len(p0)}, P1={len(p1)}, P2={len(p2)}",
        "percent": 25,
        "data": {"p0": len(p0), "p1": len(p1), "p2": len(p2)},
    })

    # ── Step 2: load_p0 ────────────────────────────────────────────
    p0_contents = {}
    if p0:
        yield format_sse_event({
            "type": "status",
            "agent": "load_p0",
            "message": f"正在加载 {len(p0)} 个 P0 核心文件...",
            "percent": 30,
            "data": None,
        })
        try:
            p0_contents = await _run_with_timeout(
                loader.phase_load_priority(owner, repo, sha, p0),
                timeout=PHASE_TIMEOUT,
                error_msg="P0 文件加载超时"
            )
            yield format_sse_event({
                "type": "progress",
                "agent": "load_p0",
                "message": f"P0 核心文件加载完成: {len(p0_contents)} 个",
                "percent": 35,
                "data": {"loaded": len(p0_contents)},
            })
        except Exception as e:
            yield format_sse_event({
                "type": "error",
                "agent": "load_p0",
                "message": f"P0 文件加载失败: {str(e)}，继续分析已加载内容",
                "percent": 35,
                "data": None,
            })

    # ── Step 3: code_parser_p0 ───────────────────────────────────
    p0_result = {}
    if p0_contents:
        yield format_sse_event({
            "type": "status",
            "agent": "code_parser_p0",
            "message": "正在解析 P0 代码结构...",
            "percent": 40,
            "data": None,
        })
        try:
            parser = CodeParserAgent()
            p0_result = await _run_with_timeout(
                parser._analyze_inmemory_files(
                    [{"path": k, "content": v} for k, v in p0_contents.items()]
                ),
                timeout=PHASE_TIMEOUT,
                error_msg="P0 代码解析超时"
            )
            yield format_sse_event({
                "type": "progress",
                "agent": "code_parser_p0",
                "message": f"P0 代码解析完成: {p0_result.get('total_functions', 0)} 个函数, {p0_result.get('total_classes', 0)} 个类",
                "percent": 45,
                "data": {"functions": p0_result.get("total_functions"), "classes": p0_result.get("total_classes")},
            })
        except Exception as e:
            yield format_sse_event({
                "type": "error",
                "agent": "code_parser_p0",
                "message": f"P0 代码解析失败: {str(e)}",
                "percent": 45,
                "data": None,
            })

    # ── Step 4: decide_p1 ───────────────────────────────────────
    need_more = False
    extra_paths: list[str] = []
    reason = "没有 P1/P2 文件"

    if p1 or p2:
        yield format_sse_event({
            "type": "status",
            "agent": "decide_p1",
            "message": "正在等待 AI 决策是否加载更多文件...",
            "percent": 48,
            "data": None,
        })
        need_more, extra_paths, reason = await _run_with_timeout(
            loader.phase_ai_decide_p1(
                owner, repo,
                loaded=p0_contents,
                code_parser_result=p0_result,
                p1_files=p1,
                p2_files=p2,
            ),
            timeout=PHASE_TIMEOUT,
            error_msg="P1 决策超时"
        )
        yield format_sse_event({
            "type": "progress",
            "agent": "decide_p1",
            "message": f"AI 决策: {reason}",
            "percent": 50,
            "data": {"needs_more": need_more, "reason": reason},
        })

    # ── Step 5: load_p1 (条件) ───────────────────────────────────
    p1_contents = {}
    p1_result = {}
    if need_more and p1:
        yield format_sse_event({
            "type": "status",
            "agent": "load_p1",
            "message": f"正在加载 {len(p1)} 个 P1 文件...",
            "percent": 55,
            "data": None,
        })
        try:
            p1_contents = await _run_with_timeout(
                loader.phase_load_priority(owner, repo, sha, p1),
                timeout=PHASE_TIMEOUT,
                error_msg="P1 文件加载超时"
            )
            yield format_sse_event({
                "type": "progress",
                "agent": "load_p1",
                "message": f"P1 文件加载完成: {len(p1_contents)} 个",
                "percent": 60,
                "data": {"loaded": len(p1_contents)},
            })
        except Exception as e:
            yield format_sse_event({
                "type": "error",
                "agent": "load_p1",
                "message": f"P1 文件加载失败: {str(e)}",
                "percent": 60,
                "data": None,
            })

        # code_parser_p1
        if p1_contents:
            yield format_sse_event({
                "type": "status",
                "agent": "code_parser_p1",
                "message": "正在解析 P1 代码结构...",
                "percent": 62,
                "data": None,
            })
            try:
                parser = CodeParserAgent()
                p1_result = await _run_with_timeout(
                    parser._analyze_inmemory_files(
                        [{"path": k, "content": v} for k, v in p1_contents.items()]
                    ),
                    timeout=PHASE_TIMEOUT,
                    error_msg="P1 代码解析超时"
                )
                yield format_sse_event({
                    "type": "progress",
                    "agent": "code_parser_p1",
                    "message": f"P1 代码解析完成",
                    "percent": 65,
                    "data": {"functions": p1_result.get("total_functions"), "classes": p1_result.get("total_classes")},
                })
            except Exception as e:
                yield format_sse_event({
                    "type": "error",
                    "agent": "code_parser_p1",
                    "message": f"P1 代码解析失败: {str(e)}",
                    "percent": 65,
                    "data": None,
                })

    # ── Step 6: load_p2 (条件) ───────────────────────────────────
    all_loaded = {**p0_contents, **p1_contents}
    p2_contents = {}

    if p2 and need_more:
        yield format_sse_event({
            "type": "status",
            "agent": "load_p2_decide",
            "message": "正在等待 AI 决策 P2 文件...",
            "percent": 66,
            "data": None,
        })
        need_p2, p2_paths, p2_reason = await _run_with_timeout(
            loader.phase_ai_decide_p2(
                owner, repo,
                loaded=all_loaded,
                code_parser_p0_result=p0_result,
                code_parser_p1_result=p1_result,
                p2_files=p2,
            ),
            timeout=PHASE_TIMEOUT,
            error_msg="P2 决策超时"
        )
        yield format_sse_event({
            "type": "progress",
            "agent": "load_p2_decide",
            "message": f"AI P2 决策: {p2_reason}",
            "percent": 68,
            "data": {"needs_more": need_p2, "reason": p2_reason},
        })

        if need_p2 and p2_paths:
            p2_to_load = [f for f in p2 if f.get("path") in set(p2_paths[:30])]
            yield format_sse_event({
                "type": "status",
                "agent": "load_p2",
                "message": f"正在加载 {len(p2_to_load)} 个 P2 文件...",
                "percent": 69,
                "data": None,
            })
            try:
                p2_contents = await _run_with_timeout(
                    loader.phase_load_priority(owner, repo, sha, p2_to_load),
                    timeout=PHASE_TIMEOUT,
                    error_msg="P2 文件加载超时"
                )
                all_loaded.update(p2_contents)
                yield format_sse_event({
                    "type": "progress",
                    "agent": "load_p2",
                    "message": f"P2 文件加载完成: {len(p2_contents)} 个",
                    "percent": 70,
                    "data": {"loaded": len(p2_contents)},
                })
            except Exception as e:
                yield format_sse_event({
                    "type": "error",
                    "agent": "load_p2",
                    "message": f"P2 文件加载失败: {str(e)}",
                    "percent": 70,
                    "data": None,
                })

    # ── Step 7: code_parser_final ────────────────────────────────
    code_parser_result = {}
    if all_loaded:
        logger.info(f"[code_parser_final] 开始，共 {len(all_loaded)} 个文件: {list(all_loaded.keys())}")
        yield format_sse_event({
            "type": "status",
            "agent": "code_parser_final",
            "message": f"正在合并解析 {len(all_loaded)} 个代码文件...",
            "percent": 72,
            "data": None,
        })
        try:
            final_files = [{"path": k, "content": v} for k, v in all_loaded.items()]
            parser = CodeParserAgent()
            code_parser_result = await _run_with_timeout(
                parser._analyze_inmemory_files(final_files),
                timeout=PHASE_TIMEOUT,
                error_msg="代码合并解析超时"
            )
            logger.info(f"[code_parser_final] 完成: parsed={code_parser_result.get('parsed_files', '?')}, chunks={code_parser_result.get('total_chunks', '?')}")
            yield format_sse_event({
                "type": "progress",
                "agent": "code_parser_final",
                "message": f"代码解析完成: {code_parser_result.get('parsed_files', len(all_loaded))} 个文件, {code_parser_result.get('total_chunks', 0)} 个语义块",
                "percent": 75,
                "data": code_parser_result,
            })
        except Exception as e:
            logger.error(f"[code_parser_final] 异常: {e}")
            yield format_sse_event({
                "type": "error",
                "agent": "code_parser_final",
                "message": f"代码解析失败: {str(e)}",
                "percent": 75,
                "data": None,
            })

    # ── Step 7: 加载依赖配置文件（供 DependencyAgent 使用）──────────
    # 只加载项目根目录或 src/ 下的依赖文件，排除 node_modules/ 等第三方依赖目录
    dep_file_names = {
        "package.json", "requirements.txt", "requirements-dev.txt",
        "Pipfile", "pyproject.toml", "go.mod", "Cargo.toml",
        "Gemfile", "composer.json", "pom.xml", "build.gradle",
    }
    EXCLUDED_DEP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv",
                          "dist", "build", ".next", ".nuxt", "target", "site-packages"}
    dep_files_to_load = [
        f for f in (classified or [])
        if os.path.basename(f.get("path", "")) in dep_file_names
        and not any(part in EXCLUDED_DEP_DIRS for part in f.get("path", "").split(os.sep))
    ]
    dep_file_contents: dict[str, str] = {}
    if dep_files_to_load:
        logger.info(f"[dependency_preload] 找到 {len(dep_files_to_load)} 个依赖文件")
        try:
            dep_file_contents = await _run_with_timeout(
                loader.phase_load_priority(owner, repo, sha, dep_files_to_load),
                timeout=PHASE_TIMEOUT,
                error_msg="依赖文件加载超时"
            )
            logger.info(f"[dependency_preload] 加载完成: {list(dep_file_contents.keys())}")
        except Exception as e:
            logger.error(f"[dependency_preload] 加载失败: {e}")

    # ── Step 8: tech_stack + quality + dependency 并行执行 ─────────
    tech_agent = TechStackAgent()
    quality_agent = QualityAgent()
    dependency_agent = DependencyAgent()

    logger.info(f"[parallel_agents] 启动 tech_stack + quality + dependency，文件数={len(all_loaded)}, 依赖文件数={len(dep_file_contents)}")
    yield format_sse_event({
        "type": "status",
        "agent": "tech_stack",
        "message": "正在识别技术栈...",
        "percent": 76,
        "data": None,
    })
    yield format_sse_event({
        "type": "status",
        "agent": "quality",
        "message": "正在分析代码质量...",
        "percent": 76,
        "data": None,
    })
    yield format_sse_event({
        "type": "status",
        "agent": "dependency",
        "message": "正在分析依赖风险...",
        "percent": 76,
        "data": None,
    })

    # 并行执行三个 Agent；dependency 需要包含显式加载的依赖配置文件
    dep_all_contents = {**all_loaded, **dep_file_contents}
    tech_task = tech_agent.run(repo, branch, file_contents=all_loaded)
    quality_task = quality_agent.run(repo, branch, file_contents=all_loaded)
    dependency_task = dependency_agent.run(repo, branch, file_contents=dep_all_contents)

    # 带超时的并行执行
    try:
        tech_result, quality_result, dependency_result = await _run_with_timeout(
            asyncio.gather(tech_task, quality_task, dependency_task, return_exceptions=True),
            timeout=PHASE_TIMEOUT * 2,  # 并行任务给更多时间
            error_msg="技术栈/质量/依赖分析超时"
        )
        logger.info(f"[parallel_agents] 完成: tech={type(tech_result).__name__}, quality={type(quality_result).__name__}, dependency={type(dependency_result).__name__}")
    except Exception as e:
        logger.error(f"[parallel_agents] 超时/异常: {e}")
        yield format_sse_event({
            "type": "error",
            "agent": "tech_stack",
            "message": f"并行分析超时: {str(e)}",
            "percent": 82,
            "data": None,
        })
        tech_result = {}
        quality_result = {}
        dependency_result = {}

    # 处理异常情况
    if isinstance(tech_result, Exception):
        yield format_sse_event({
            "type": "error",
            "agent": "tech_stack",
            "message": f"技术栈识别失败: {str(tech_result)}",
            "percent": 82,
            "data": None,
        })
        tech_result = {}
    else:
        yield format_sse_event({
            "type": "progress",
            "agent": "tech_stack",
            "message": "技术栈识别完成（并行）",
            "percent": 82,
            "data": tech_result,
        })

    if isinstance(quality_result, Exception):
        yield format_sse_event({
            "type": "error",
            "agent": "quality",
            "message": f"代码质量分析失败: {str(quality_result)}",
            "percent": 85,
            "data": None,
        })
        quality_result = {}
    else:
        yield format_sse_event({
            "type": "progress",
            "agent": "quality",
            "message": "代码质量分析完成（并行）",
            "percent": 85,
            "data": quality_result,
        })

    if isinstance(dependency_result, Exception):
        yield format_sse_event({
            "type": "error",
            "agent": "dependency",
            "message": f"依赖风险分析失败: {str(dependency_result)}",
            "percent": 87,
            "data": None,
        })
        dependency_result = {}
    else:
        # 使用 type: "result" 让前端 DependencyAgentCard 正确标记 finishedAgents
        yield format_sse_event({
            "type": "result",
            "agent": "dependency",
            "message": "依赖风险分析完成（并行）",
            "percent": 87,
            "data": dependency_result,
        })

    # ── Step 9: architecture — 基于 AST + TechStack + Quality + LLM ──
    logger.info(f"[architecture] 启动...")
    yield format_sse_event({
        "type": "status",
        "agent": "architecture",
        "message": "正在评估项目架构...",
        "percent": 88,
        "data": None,
    })

    try:
        arch_result = await _run_with_timeout(
            ArchitectureAgent().run(
                repo, branch,
                file_contents=all_loaded or None,
                code_parser_result=code_parser_result,
                tech_stack_result=tech_result,
                quality_result=quality_result,
                total_tree_files=len(tree_items),
            ),
            timeout=PHASE_TIMEOUT,
            error_msg="架构评估超时"
        )
        logger.info(f"[architecture] 完成")
        yield format_sse_event({
            "type": "progress",
            "agent": "architecture",
            "message": "架构评估完成",
            "percent": 91,
            "data": arch_result,
        })
    except Exception as e:
        logger.error(f"[architecture] 异常: {e}")
        yield format_sse_event({
            "type": "error",
            "agent": "architecture",
            "message": f"架构评估失败: {str(e)}",
            "percent": 91,
            "data": None,
        })
        arch_result = {}

    # ── Step 10: optimization — 真实 LLM 驱动的优化建议 ─────────────
    logger.info(f"[optimization] 启动...")
    yield format_sse_event({
        "type": "status",
        "agent": "optimization",
        "message": "正在生成优化建议...",
        "percent": 93,
        "data": None,
    })

    try:
        opt_agent = SuggestionAgent()
        opt_result = await _run_with_timeout(
            opt_agent.run(
                repo, branch,
                file_contents=all_loaded or None,
                code_parser_result=code_parser_result,
                tech_stack_result=tech_result,
                quality_result=quality_result,
                dependency_result=dependency_result or None,
            ),
            timeout=PHASE_TIMEOUT,
            error_msg="生成优化建议超时"
        )
        logger.info(f"[optimization] 完成: {len(opt_result.get('suggestions', []))} 条建议")
        yield format_sse_event({
            "type": "result",
            "agent": "optimization",
            "message": "分析完成",
            "percent": 100,
            "data": opt_result,
        })
    except Exception as e:
        logger.error(f"[optimization] 异常: {e}")
        yield format_sse_event({
            "type": "error",
            "agent": "optimization",
            "message": f"生成优化建议失败: {str(e)}，但分析已完成",
            "percent": 100,
            "data": {
                "tech_stack": tech_result,
                "quality": quality_result,
                "dependency": dependency_result,
                "architecture": arch_result,
            },
        })

    # ── Step 11: 发送 final_result SSE 事件 ──────────────────────────
    final_result_data = {
        "code_parser": code_parser_result,
        "tech_stack": tech_result,
        "quality": quality_result,
        "dependency": dependency_result,
        "architecture": arch_result,
        "suggestion": opt_result,
    }
    yield format_sse_event({
        "type": "result",
        "agent": "final_result",
        "message": "全部分析完成",
        "percent": 100,
        "data": final_result_data,
    })

    yield "data: [DONE]\n\n"


def run_analysis_sync(
    repo_url: str,
    branch: str = "main",
    thread_id: str | None = None,
) -> dict:
    """同步运行 LangGraph 工作流，直接返回最终结果。

    使用 checkpointing：同一 thread_id 的请求可以恢复之前的状态。
    """
    config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id or f"{repo_url}::{branch}",
        }
    }

    initial_state: SharedState = build_initial_state(repo_url, branch)

    final_state = _workflow.invoke(initial_state, config=config)
    return final_state.get("final_result") or {}


def build_initial_state(repo_url: str, branch: str = "main") -> SharedState:
    """构建 LangGraph 初始状态。"""
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
