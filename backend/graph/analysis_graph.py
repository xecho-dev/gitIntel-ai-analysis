"""
GitIntel 分析 Pipeline — LangGraph 工作流 + SSE 流式输出。

整体 Pipeline（线性 → 渐进式加载 → 并行分析 → 串行收尾）：

    fetch_tree_classify ──► load_p0 ──► code_parser_p0 ──► decide_p1
                                                              │
                                          needs_more? ────────┤
                                              │               │
                                              ▼ (True)         ▼ (False)
                                          load_p1        load_p2_decide
                                              │               │
                                          code_parser_p1    │
                                              │               ▼
                                              ▼         load_more_p2
                                          load_p2_decide ◄─┘  (循环，最多 3 轮)
                                              │
                                              ▼
                                      code_parser_final
                                              │
                         ┌─────────────────────┼─────────────────────┐
                         ▼                     ▼                     ▼
                   tech_stack            quality              dependency
                         │                     │                     │
                         └──────────► architecture ◄──────────────┘
                                              │
                                    merge_analysis
                                              │
                              optimization / react_suggestion / END

ReAct Agent 扩展（Phase 1-3）：
  - node_react_loader:    基于 ReAct 模式的智能仓库探索（可选，默认关闭）
  - node_react_suggestion: 基于 ReAct 模式的优化建议生成（可选，默认关闭）
  - ReActRepoLoaderAgent: 多轮 Thought→Action→Observation 循环
  - ReActSuggestionAgent: 通过工具验证每个建议的精确性

工作模式：
  - stream_analysis_sse() — SSE 流式接口（主要入口），实时推送进度
  - run_analysis_sync()  — 同步阻塞接口（向后兼容），直接返回结果
  - build_initial_state() — 构建 LangGraph 初始状态

断点续传：
  - MemorySaver（内存版），适合开发/演示
  - 生产换 PostgresSaver + RedisSaver（见下方注释）
"""

import asyncio
import logging
from typing import Any, Generator

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
from agents.repo_loader_agent import ReActRepoLoaderAgent
from agents.suggestion_agent import ReActSuggestionAgent
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


def node_react_loader(state: SharedState) -> dict:
    """节点 1.5：ReAct 模式的智能仓库加载（替代 fetch_tree_classify + 渐进加载链）。

    当 use_react_mode=True 时启用。

    与旧版流程（fetch_tree_classify → load_p0 → load_p1 → load_p2）的区别：
      - 旧版：LLM 只做"是否加载"的判断，文件选择基于硬编码的优先级
      - ReAct：Agent 自主决定调用什么工具、加载什么文件，是真正的自主推理

    工作流程：
      1. Agent 先获取仓库信息和文件树
      2. 通过 Thought → Action → Observation 循环探索
      3. 自主选择调用 GitHub 工具和代码分析工具
      4. 直到达到 max_files (50) 或 agent 认为足够

    关键改进：ReAct 的 loaded_files 会写入 state，供后续节点使用。
    """
    import queue as _q_module
    import threading

    repo_url = state.get("repo_url", "")
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {"errors": ["node_react_loader: 无法解析 URL"]}

    owner, repo = parsed
    branch = state.get("branch", "main")

    q: Any = _q_module.Queue()
    exc_info: list = []
    react_events: list[dict] = []
    result_ref: list[dict] = []  # 用于跨线程传递结果

    def run_react():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def consume():
                agent = ReActRepoLoaderAgent()
                result = await agent.explore(owner, repo, branch)

                # 将探索过程转为 SSE 事件
                for call in result.tool_calls:
                    if call.thought:
                        react_events.append({
                            "type": "progress",
                            "agent": "react_loader",
                            "message": f"[推理 {call.iteration + 1}] {call.thought[:80]}",
                            "percent": min(30 + call.iteration * 5, 80),
                            "data": {
                                "tool": call.tool_name,
                                "args": call.tool_args,
                                "observation": call.observation[:200],
                                "elapsed_ms": call.elapsed_ms,
                            },
                        })

                    # 加载文件进度
                    if call.tool_name in ("get_file_blobs", "read_file_content"):
                        react_events.append({
                            "type": "progress",
                            "agent": "react_loader",
                            "message": f"加载: {call.observation[:60]}",
                            "percent": min(50, 30 + len(result.loaded_paths) * 0.8),
                            "data": {"loaded_count": len(result.loaded_paths)},
                        })

                # 最终结果
                react_events.append({
                    "type": "result",
                    "agent": "react_loader",
                    "message": f"ReAct 探索完成: {result.total_iterations} 轮, {len(result.loaded_paths)} 个文件",
                    "percent": 100,
                    "data": {
                        "total_iterations": result.total_iterations,
                        "loaded_count": len(result.loaded_paths),
                        "loaded_paths": result.loaded_paths[:30],
                        "is_sufficient": result.is_sufficient,
                        "summary": result.summary[:500],
                        "errors": result.errors,
                    },
                })

                # 将 loaded_files 跨线程传递（通过 result_ref）
                result_ref.append({
                    "loaded_files": result.loaded_files,
                    "loaded_paths": result.loaded_paths,
                    "repo_sha": getattr(result, "sha", branch),
                })

            loop.run_until_complete(consume())
            loop.close()
        except Exception as e:
            import traceback
            logger.error(f"[node_react_loader] 线程异常: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            exc_info.append(e)
        finally:
            q.put(None)

    t = threading.Thread(target=run_react, daemon=True)
    t.start()
    t.join()

    # 收集所有事件
    all_events: list[dict] = []
    while True:
        item = q.get()
        if item is None:
            break
        all_events.append(item)

    # 从 result_ref 获取加载的文件
    loaded_files: dict[str, str] = {}
    loaded_paths: list[str] = []
    repo_sha = branch
    if result_ref:
        loaded_files = result_ref[0].get("loaded_files", {})
        loaded_paths = result_ref[0].get("loaded_paths", [])
        repo_sha = result_ref[0].get("repo_sha", branch)

    # 合并事件
    all_events = react_events + all_events

    summary = ""
    iterations = 0
    for ev in all_events:
        if isinstance(ev, dict) and ev.get("type") == "result":
            data = ev.get("data", {})
            summary = data.get("summary", "")
            iterations = data.get("total_iterations", 0)

    if loaded_files:
        logger.info(
            f"[node_react_loader] ReAct 完成: {len(loaded_files)} 个文件, "
            f"{len(loaded_paths)} 条路径, {iterations} 轮"
        )
        return {
            "loaded_files": loaded_files,
            "loaded_paths": loaded_paths,
            "repo_sha": repo_sha,
            "file_contents": loaded_files,
            "errors": exc_info,
            "react_events": all_events,
            "react_summary": summary,
            "react_iterations": iterations,
            "finished_agents": ["react_loader"],
        }
    else:
        logger.warning(f"[node_react_loader] ReAct 无结果，回退到旧版流程")
        return {
            "errors": exc_info + ["ReAct 无结果，使用已有加载流程"],
            "react_events": all_events,
            "react_summary": summary,
            "react_iterations": iterations,
            "finished_agents": [],
        }


def node_load_p0(state: SharedState) -> dict:
    """节点 2：加载 P0 核心文件（优先级最高，通常是入口/配置文件）。

    支持断点恢复：如果某些 P0 文件已加载，跳过重复加载。
    """
    if not (state.get("repo_tree") and state.get("classified_files")):
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
    """节点 3：AST 解析 P0 代码文件，提取函数/类/import 等结构信息。

    结果供后续 decide_p1 决策使用——AI 根据 P0 的代码复杂度
    判断是否需要加载更多上下文（渐进式加载的核心依据）。
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
    """节点 6：AST 解析 P1 文件，与 node_code_parser_p0 逻辑相同。"""
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

    注意：ReAct 模式下此节点不可达（流程会走 react_loader → explorer），
    这里添加保护以确保兼容性。
    """
    # ReAct 模式下不可达，跳过执行（但确保 code_parser_result 已透传）
    if state.get("use_react_mode", False):
        return {
            "code_parser_result": state.get("code_parser_result"),
            "errors": [],
            "finished_agents": [],
        }

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


def node_explorer(state: SharedState) -> dict:
    """节点 9.5（可选）：并行 ReAct 探索。

    ReAct 模式（use_react_mode=True）下的探索入口：
      - react_loader 已将 loaded_files 写入状态
      - 此节点负责：① 代码解析（生成 code_parser_result）② 多维度并行探索

    工作流程：
      1. 获取 loaded_files
      2. ReAct 模式：先 CodeParser 解析，再 ExplorerOrchestrator 探索
      3. 旧版模式：直接 ExplorerOrchestrator 探索（代码解析已在 code_parser_final 完成）

    SSE 事件：explorer_events 透传到前端，显示每个 Agent 的探索进度。
    """
    import queue as _q_module
    import threading

    repo_id, branch, _ = get_inputs_from_state(state)
    file_contents = (
        state.get("loaded_files") or
        {**state.get("loaded_p0", {}), **state.get("loaded_p1", {})}
    )
    logger.info(f"[node_explorer] 入参检查: use_react_mode={state.get('use_react_mode')}, file_contents={len(file_contents) if file_contents else 0} 个文件")

    owner, repo = parse_repo_url(state.get("repo_url", ""))
    if not owner or not repo:
        return {"errors": ["node_explorer: 无法解析 repo_url"]}

    q: Any = _q_module.Queue()
    exc_info: list = []
    explorer_events: list[dict] = []
    code_parser_result: dict = {}
    # 依赖分析结果：None 表示未执行，dict 表示执行结果
    dependency_result: dict | None = None

    # ── 依赖分析（始终执行，DependencyAgent 能自己从 GitHub 获取依赖文件）────────
    # ExplorerOrchestrator 不含 DependencyExplorer，所以在这里单独调用
    try:
        loop2 = asyncio.new_event_loop()
        asyncio.set_event_loop(loop2)

        async def run_dep():
            agent = DependencyAgent()
            if not owner or not repo:
                _logger.warning(f"[node_explorer] 无法解析 owner/repo，跳过依赖分析")
                return None
            result_data = {}
            async for ev in agent.stream(
                f"{owner}/{repo}",
                branch,
                file_contents=file_contents if file_contents else None,
            ):
                if ev.get("type") == "result":
                    result_data = ev.get("data")
            return result_data

        dependency_result = loop2.run_until_complete(run_dep())
        logger.info(f"[node_explorer] 依赖分析完成: {dependency_result}")
        loop2.close()
    except Exception as e:
        logger.warning(f"[node_explorer] 依赖分析失败: {e}")
        exc_info.append(str(e))

    # ── ReAct 模式：代码解析（依赖依赖分析完成后）─────────────────────
    if state.get("use_react_mode", False) and file_contents:
        # ReAct 模式下，react_loader 已加载文件，在这里做代码解析
        # 解析结果写入 state，供 architecture 节点使用
        try:
            files = [{"path": path, "content": content} for path, content in file_contents.items()]
            if files:
                code_parser_result = asyncio.run(
                    CodeParserAgent()._analyze_inmemory_files(files)
                )
                logger.info(f"[node_explorer] ReAct 模式代码解析完成: {len(files)} 个文件")
        except Exception as e:
            logger.warning(f"[node_explorer] ReAct 模式代码解析失败: {e}")
            exc_info.append(str(e))

    # ── 探索（并行 ReAct 探索）───────────────────────────────────
    def run_explorers():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def consume():
                from agents.explorers import ExplorerOrchestrator
                orchestrator = ExplorerOrchestrator()

                explorer_events.append({
                    "type": "status",
                    "agent": "explorer",
                    "message": "并行探索启动：TechStack / Quality / Architecture",
                    "percent": 50,
                    "data": None,
                })

                results = await orchestrator.explore_all(
                    owner, repo, branch,
                    file_contents=file_contents or None,
                )

                explorer_events.append({
                    "type": "result",
                    "agent": "explorer",
                    "message": f"并行探索完成: {len(results)} 个维度",
                    "percent": 100,
                    "data": results,
                })

            loop.run_until_complete(consume())
            loop.close()
        except Exception as e:
            import traceback
            logger.error(f"[node_explorer] 线程异常: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            exc_info.append(e)
        finally:
            q.put(None)

    t = threading.Thread(target=run_explorers, daemon=True)
    t.start()
    t.join()

    # 收集事件
    all_events: list[dict] = []
    while True:
        item = q.get()
        if item is None:
            break
        all_events.append(item)

    # 合并事件
    all_events = explorer_events + all_events

    result: dict = {}
    for event in all_events:
        if event.get("type") == "result":
            result = event.get("data") or {}

    # ── 构建返回状态 ───────────────────────────────────────────
    return_val: dict = {
        "explorer_result": result,
        "explorer_events": all_events,
        "errors": exc_info,
    }

    # 确保 file_contents 写入状态，供 tech_stack / quality / dependency 使用
    if file_contents:
        return_val["file_contents"] = file_contents

    # ReAct 模式下，将 code_parser_result 写入状态，供 architecture 节点使用
    if code_parser_result:
        return_val["code_parser_result"] = code_parser_result

    # 依赖分析始终写入状态（无论 ReAct 还是旧版模式）
    if dependency_result is not None:
        logger.info(f"[node_explorer] 写入 dependency_result 到状态: {dependency_result}")
        return_val["dependency_result"] = dependency_result

    # ReAct 模式下，将 Explorer 结果映射到对应字段（供后续节点使用）
    # 注意：ExplorerOrchestrator 返回 {ExplorerName: {findings + _meta}}，需要提取 findings
    if state.get("use_react_mode", False):
        if result:
            if "TechStackExplorer" in result:
                ts_data = result["TechStackExplorer"]
                # 提取 findings 字段，如果没有则直接使用整个数据
                return_val["tech_stack_result"] = ts_data.get("findings", ts_data) if isinstance(ts_data, dict) else ts_data
            if "QualityExplorer" in result:
                q_data = result["QualityExplorer"]
                return_val["quality_result"] = q_data.get("findings", q_data) if isinstance(q_data, dict) else q_data
            if "ArchitectureExplorer" in result:
                arch_data = result["ArchitectureExplorer"]
                return_val["architecture_result"] = arch_data.get("findings", arch_data) if isinstance(arch_data, dict) else arch_data

    return return_val


def node_merge_analysis(state: SharedState) -> dict:
    """节点 10：并行分析结果验证。

    tech_stack / quality / dependency 三个并行节点全部完成后触发。
    此节点不做实际合并（合并在 node_optimization 的 final_result 中完成），
    仅做结果存在性验证，收集错误信息。
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
    elif "error" in result:
        errors.append(f"QualityAgent: {result.get('error')}")

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
    elif "error" in result:
        errors.append(f"DependencyAgent: {result.get('error')}")

    return {
        "dependency_result": result,
        "errors": errors,
    }


def node_architecture(state: SharedState) -> dict:
    """节点 14：架构评估（基于 AST 结构 + TechStack + Quality + LLM）。

    在 tech_stack + quality + dependency 三个并行节点全部完成后执行。
    ArchitectureAgent 综合代码结构、依赖关系、技术栈特征，给出架构评估。

    流式执行：
      1. 后台线程驱动 ArchitectureAgent.stream() 异步迭代器
      2. 所有中间事件（status、progress、result）收集到 architecture_events
      3. SSE 层通过 _yield_sse_for_node 将事件逐个透传到前端

    这样前端能实时看到架构评估的进度：
      正在分析项目架构 → 检测到 N 个组件 → 调用 LLM 生成洞察 → 完成
    """
    import queue as _queue_module
    import threading

    repo_id, branch, _ = get_inputs_from_state(state)
    repo_tree = state.get("repo_tree") or []

    q: Any = _queue_module.Queue()
    exc_info: list = []

    def run_stream():
        """在子线程中运行异步 stream 迭代器，收集所有事件。"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def consume():
                agent = ArchitectureAgent()
                async for event in agent.stream(
                    repo_id,
                    branch,
                    code_parser_result=state.get("code_parser_result"),
                    tech_stack_result=state.get("tech_stack_result"),
                    quality_result=state.get("quality_result"),
                    total_tree_files=len(repo_tree),
                ):
                    q.put(dict(event))

            loop.run_until_complete(consume())
            loop.close()
        except Exception as e:
            import traceback
            logger.error(f"[node_architecture] 线程异常: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            exc_info.append(e)
        finally:
            q.put(None)

    t = threading.Thread(target=run_stream, daemon=True)
    t.start()
    t.join()

    all_events: list[dict] = []
    while True:
        item = q.get()
        if item is None:
            break
        all_events.append(item)

    result: dict = {}
    for event in all_events:
        if event.get("type") == "result":
            result = event.get("data") or {}

    if not result:
        exc_info.append("ArchitectureAgent: 执行返回空结果")

    return {
        "architecture_result": result,
        "architecture_events": all_events,
        "errors": exc_info,
    }


def node_optimization(state: SharedState) -> dict:
    """节点 15：生成优化建议（综合所有分析结果的 LLM 驱动阶段）。

    这是整个 Pipeline 的最后一个分析节点。
    SuggestionAgent 接收真实代码内容 + 所有前置分析结果
    （code_parser / tech_stack / quality / dependency / architecture），
    输出针对项目实际情况的优化建议，而非通用建议。

    RAG 流程（流式执行）：
      1. 后台线程驱动 SuggestionAgent.stream() 异步迭代器
      2. 所有中间事件（RAG 检索、LLM 调用进度、结果）收集到 optimization_events
      3. 最终 result 数据存入 optimization_result / suggestion_result
      4. SSE 层通过 _yield_sse_for_node 将 optimization_events 逐个透传到前端

    同时构建 final_result 打包所有分析数据，供前端展示。
    """
    import queue as _queue_module
    import threading

    repo_id, branch, _ = get_inputs_from_state(state)

    file_contents = (
        state.get("loaded_files") or
        {**state.get("loaded_p0", {}), **state.get("loaded_p1", {})}
    )

    q: Any = _queue_module.Queue()
    exc_info: list = []

    def run_stream():
        """在子线程中运行异步 stream 迭代器，收集所有事件。"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def consume():
                agent = SuggestionAgent()
                async for event in agent.stream(
                    repo_id,
                    branch,
                    file_contents=file_contents or None,
                    code_parser_result=state.get("code_parser_result"),
                    tech_stack_result=state.get("tech_stack_result"),
                    quality_result=state.get("quality_result"),
                    dependency_result=state.get("dependency_result"),
                ):
                    q.put(dict(event))  # 转为普通 dict 避免序列化问题

            loop.run_until_complete(consume())
            loop.close()
        except Exception as e:
            import traceback
            logger.error(f"[node_optimization] 线程异常: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            exc_info.append(e)
        finally:
            q.put(None)  # 哨兵：迭代结束

    t = threading.Thread(target=run_stream, daemon=True)
    t.start()
    t.join()  # 等待线程完成，确保所有事件已收集

    # 收集所有中间事件
    all_events: list[dict] = []
    while True:
        item = q.get()
        if item is None:
            break
        all_events.append(item)

    result: dict = {}
    for event in all_events:
        if event.get("type") == "result":
            result = event.get("data") or {}

    final_result = {
        "repo_loader": state.get("repo_loader_result"),
        "code_parser": state.get("code_parser_result"),
        "tech_stack": state.get("tech_stack_result"),
        "quality": state.get("quality_result"),
        "dependency": state.get("dependency_result"),
        "architecture": state.get("architecture_result"),
        "suggestion": result,
    }

    return {
        "optimization_result": result,
        "suggestion_result": result,
        "final_result": final_result,
        "optimization_events": all_events,
        "errors": exc_info,
    }


def node_react_suggestion(state: SharedState) -> dict:
    """节点 15b（可选）：ReAct 模式的优化建议生成。

    与 node_optimization 的区别：
      - node_optimization：一次性塞入所有上下文，code_fix 是 guesswork
      - node_react_suggestion：Agent 通过工具验证每个问题，生成精确可执行的 code_fix

    工作流程：
      1. 构建分析上下文（技术栈/质量/依赖/架构数据）
      2. RAG 检索历史经验
      3. ReAct 循环：Agent 调用工具验证问题（搜索代码/读文件/解析 AST）
      4. 基于验证结果生成精确建议
      5. 存储高优先级建议到 RAG

    适用场景：
      - 需要精确 code_fix 的场景（如 FixGeneratorAgent 需要基于此结果生成代码修改）
      - 对建议质量要求更高的分析

    注意：此节点为新能力，默认关闭。
    """
    import queue as _q_module
    import threading

    repo_id, branch, _ = get_inputs_from_state(state)
    file_contents = (
        state.get("loaded_files") or
        {**state.get("loaded_p0", {}), **state.get("loaded_p1", {})}
    )

    # ReAct 模式下 get_inputs_from_state 可能返回空的 repo_id（因为没有 repo_loader_result），
    # 需要直接从 repo_url 解析，确保 ReActSuggestionAgent 能拿到正确的 owner/repo
    owner, repo = parse_repo_url(state.get("repo_url", ""))
    if owner and repo:
        repo_id = f"{owner}/{repo}"

    q: Any = _q_module.Queue()
    exc_info: list = []

    def run_stream():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def consume():
                agent = ReActSuggestionAgent()
                async for event in agent.stream(
                    repo_id,
                    branch,
                    file_contents=file_contents or None,
                    code_parser_result=state.get("code_parser_result"),
                    tech_stack_result=state.get("tech_stack_result"),
                    quality_result=state.get("quality_result"),
                    dependency_result=state.get("dependency_result"),
                ):
                    q.put(dict(event))

            loop.run_until_complete(consume())
            loop.close()
        except Exception as e:
            import traceback
            logger.error(f"[node_react_suggestion] 线程异常: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            exc_info.append(e)
        finally:
            q.put(None)

    t = threading.Thread(target=run_stream, daemon=True)
    t.start()
    t.join()

    all_events: list[dict] = []
    while True:
        item = q.get()
        if item is None:
            break
        all_events.append(item)

    result: dict = {}
    for event in all_events:
        if event.get("type") == "result":
            result = event.get("data") or {}

    # 如果 ReActSuggestionAgent 返回空结果，使用规则引擎兜底
    if not result or not result.get("suggestions"):
        logger.warning("[node_react_suggestion] ReActSuggestionAgent 返回空结果，使用规则引擎兜底")
        fallback = _generate_rule_based_suggestions(state)
        if fallback:
            result = fallback
            # 添加兜底事件
            all_events.append({
                "type": "result",
                "agent": "optimization",
                "message": "规则引擎兜底生成建议",
                "percent": 100,
                "data": result,
            })

    final_result = {
        "repo_loader": state.get("repo_loader_result"),
        "code_parser": state.get("code_parser_result"),
        "tech_stack": state.get("tech_stack_result"),
        "quality": state.get("quality_result"),
        "dependency": state.get("dependency_result"),
        "architecture": state.get("architecture_result"),
        "suggestion": result,
    }

    return {
        "suggestion_result": result,
        "final_result": final_result,
        "optimization_events": all_events,
        "errors": exc_info,
    }


def _generate_rule_based_suggestions(state: SharedState) -> dict:
    """基于已有分析数据生成规则引擎建议。

    当 ReActSuggestionAgent 失败时作为兜底方案。
    """
    from agents.suggestion import SuggestionAgent

    suggestions = []
    _id = [1]

    def next_id():
        v = _id[0]
        _id[0] += 1
        return v

    # 从 quality_result 生成建议
    quality_result = state.get("quality_result")
    if quality_result and isinstance(quality_result, dict):
        try:
            suggestions.extend(SuggestionAgent._quality_suggestions(quality_result, next_id))
        except Exception as e:
            logger.warning(f"[_generate_rule_based_suggestions] _quality_suggestions 失败: {e}")

    # 从 dependency_result 生成建议
    dependency_result = state.get("dependency_result")
    if dependency_result and isinstance(dependency_result, dict):
        try:
            suggestions.extend(SuggestionAgent._dependency_suggestions(dependency_result, next_id))
        except Exception as e:
            logger.warning(f"[_generate_rule_based_suggestions] _dependency_suggestions 失败: {e}")

    # 从 architecture_result 生成建议（如果有的话）
    architecture_result = state.get("architecture_result")
    if architecture_result and isinstance(architecture_result, dict):
        # 架构问题建议
        concerns = architecture_result.get("concerns", [])
        if concerns:
            for concern in concerns[:3]:
                suggestions.append({
                    "id": next_id(),
                    "type": "architecture",
                    "title": "架构优化建议",
                    "description": str(concern),
                    "priority": "medium",
                    "category": "architecture",
                    "source": "rule",
                })

    # 如果仍然没有建议，生成一个通用建议
    if not suggestions:
        suggestions.append({
            "id": next_id(),
            "type": "general",
            "title": "项目分析完成",
            "description": "分析已完成，未检测到需要紧急处理的问题。",
            "priority": "low",
            "category": "general",
            "source": "rule",
        })

    # 按优先级排序
    priority_order = {"high": 0, "medium": 1, "low": 2}
    suggestions.sort(key=lambda s: priority_order.get(s.get("priority", "low"), 2))

    return {
        "suggestions": suggestions,
        "total": len(suggestions),
        "high_priority": sum(1 for s in suggestions if s.get("priority") == "high"),
        "medium_priority": sum(1 for s in suggestions if s.get("priority") == "medium"),
        "low_priority": sum(1 for s in suggestions if s.get("priority") == "low"),
        "verified_count": 0,
        "tool_calls": 0,
        "rag": {"active": False, "history_count": 0},
        "_fallback": True,
    }


# ─── 错误处理节点 ──────────────────────────────────────────────────────


def node_error(state: SharedState) -> dict:
    """错误处理兜底节点。

    当流程进入异常分支时触发，记录错误并正常结束流程。
    LangGraph 中的错误节点用于捕获未处理的异常，防止流程中断。
    """
    return {
        "errors": ["Pipeline: 进入错误处理节点"],
    }


# ─── 条件路由函数 ──────────────────────────────────────────────────────
# 这些函数接收 SharedState，返回节点名称字符串。
# LangGraph 根据返回值决定下一步执行哪个节点。


def route_after_fetch(state: SharedState) -> str:
    """fetch_tree_classify 之后：ReAct 模式下跳到 react_loader 获取智能加载结果。

    ReAct 模式不走传统 P0/P1/P2 渐进加载，直接跳到 react_loader。
    react_loader 会将 loaded_files 写入状态，后续节点直接使用。
    """
    if state.get("use_react_mode", False):
        return "react_loader"
    return "load_p0"
def route_suggestion(state: SharedState) -> str:
    """优化建议阶段路由。

    - use_react_mode=True  → react_suggestion（ReAct 模式，主动验证每个建议）
    - use_react_mode=False → optimization（旧版 SuggestionAgent）
    """
    if state.get("use_react_mode", False):
        return "react_suggestion"
    return "optimization"


def route_after_decide_p1(state: SharedState) -> str:
    """decide_p1 之后：根据 needs_more 判断是否加载 P1。

    - needs_more=True  → load_p1（加载 P1 文件后进入 code_parser_p1）
    - needs_more=False → load_p2_decide（跳过 P1，直接决策 P2）
    """
    if state.get("needs_more", False):
        return "load_p1"
    return "load_p2_decide"


def route_after_code_parser(state: SharedState) -> str:
    """code_parser_final 之后：ReAct 模式走 explorer，旧版走并行分析。

    - use_react_mode=True  → explorer（ReAct 探索，跳过独立 tech_stack/quality/dependency）
    - use_react_mode=False → fan-out 到 tech_stack / quality / dependency
    """
    if state.get("use_react_mode", False):
        return "explorer"
    return "tech_stack"


def route_to_architecture(state: SharedState) -> str:
    """Fan-in 路由：explorer / tech_stack / quality / dependency → architecture。

    通过 use_react_mode 判断哪些节点会执行，据此决定是否可以进入 architecture：
      - use_react_mode=True  → 只有 explorer 会执行 → 直接进入 architecture
      - use_react_mode=False → 只有 tech_stack/quality/dependency 会执行 → 直接进入 architecture
    这样即使有未执行的节点，LangGraph 也不会死锁等待。
    """
    return "architecture"


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

    图结构约定：
      - add_edge(A, B): A 执行完后顺序执行 B
      - add_conditional_edges(A, router, mapping): A 执行完后调用 router(state)，
        根据返回值从 mapping 中选择下一个节点
      - 从同一节点 add_edge 到多个节点 → LangGraph 自动并行执行（Fan-out），
        所有目标节点都完成后才触发下一个节点（Fan-in，等价于 join barrier）

    ReAct 模式流程（use_react_mode=True）：
      fetch_tree_classify
           │ use_react_mode?
           ▼
      ┌──── react_loader ──► explorer ──► architecture ──► merge_analysis ──► react_suggestion
      │
      └──── load_p0 ──► ... ──► code_parser_final ──► (被跳过)

    旧版流程（use_react_mode=False）：
      fetch_tree_classify ──► load_p0 ──► code_parser_p0 ──► decide_p1 ──► load_p1 ──► ...
      ──► code_parser_final ──► tech_stack / quality / dependency ──► architecture ──► optimization

    关键设计：
      - code_parser_final 用条件路由决定走 explorer（ReAct）还是 fan-out 到三个旧版节点（旧版）
      - explorer / tech_stack / quality / dependency 都用条件路由进入 architecture（避免 fan-in 死锁）
    """
    graph = StateGraph(state_schema=SharedState)

    # 节点注册
    graph.add_node("fetch_tree_classify", node_fetch_tree_classify)
    graph.add_node("react_loader", node_react_loader)
    graph.add_node("load_p0", node_load_p0)
    graph.add_node("code_parser_p0", node_code_parser_p0)
    graph.add_node("decide_p1", node_decide_p1)
    graph.add_node("load_p1", node_load_p1)
    graph.add_node("code_parser_p1", node_code_parser_p1)
    graph.add_node("load_p2_decide", node_load_p2_decide)
    graph.add_node("load_more_p2", node_load_more_p2)
    graph.add_node("code_parser_final", node_code_parser_final)
    graph.add_node("explorer", node_explorer)
    graph.add_node("tech_stack", node_tech_stack)
    graph.add_node("quality", node_quality)
    graph.add_node("dependency", node_dependency)
    graph.add_node("architecture", node_architecture)
    graph.add_node("merge_analysis", node_merge_analysis)
    graph.add_node("optimization", node_optimization)
    graph.add_node("react_suggestion", node_react_suggestion)
    graph.add_node("error", node_error)

    # ── 入口 ──────────────────────────────────────────────────────
    graph.set_entry_point("fetch_tree_classify")

    # ── 入口路由：fetch_tree_classify 之后 ─────────────────────────
    # ReAct 模式：react_loader（智能自主加载）
    # 旧版模式：load_p0（旧版渐进式加载）
    graph.add_conditional_edges(
        "fetch_tree_classify",
        route_after_fetch,
        {
            "react_loader": "react_loader",
            "load_p0": "load_p0",
        },
    )

    # ── ReAct 加载路由：react_loader 之后 ──────────────────────────
    # ── ReAct vs 旧版分流：code_parser_final / react_loader 之后 ────────────
    # react_loader 之后
    graph.add_edge("react_loader", "explorer")

    # ── 旧版渐进加载链 ───────────────────────────────────────────
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

    # code_parser_final 之后：ReAct 模式走 explorer（ReAct 探索），旧版走 fan-out（并行分析）
    # 旧版时：code_parser_final 通过条件路由到 tech_stack，同时通过 fan-out 并行触发 quality 和 dependency
    graph.add_conditional_edges(
        "code_parser_final",
        route_after_code_parser,
        {
            "explorer": "explorer",
            "tech_stack": "tech_stack",
        },
    )
    # Fan-out：旧版模式下并行触发 quality 和 dependency（与 tech_stack 同时执行）
    # 注意：tech_stack 也通过上面的条件路由触发，所以这三条 fan-out 一起构成旧版的完整并行分析
    graph.add_edge("code_parser_final", "quality")
    graph.add_edge("code_parser_final", "dependency")

    # ── Fan-in：四个节点（explorer / tech_stack / quality / dependency）完成 → architecture ──
    # 每个节点的条件路由确保 LangGraph fan-in 不会死锁
    graph.add_conditional_edges("explorer", route_to_architecture, {"architecture": "architecture"})
    graph.add_conditional_edges("tech_stack", route_to_architecture, {"architecture": "architecture"})
    graph.add_conditional_edges("quality", route_to_architecture, {"architecture": "architecture"})
    graph.add_conditional_edges("dependency", route_to_architecture, {"architecture": "architecture"})

    # ── 收尾：architecture → merge_analysis ────────────────────────
    graph.add_edge("architecture", "merge_analysis")

    # ── 优化建议路由 ─────────────────────────────────────────────
    # ReAct 模式：react_suggestion（主动验证每个建议）
    # 旧版模式：optimization（传统 SuggestionAgent）
    graph.add_conditional_edges(
        "merge_analysis",
        route_suggestion,
        {
            "react_suggestion": "react_suggestion",
            "optimization": "optimization",
        },
    )

    # 结束
    graph.add_edge("optimization", END)
    graph.add_edge("react_suggestion", END)
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
    use_react_mode: bool = True,
) -> Generator[str, None, None]:
    """SSE 流式接口：LangGraph 工作流 + 实时 SSE 事件。

    Args:
        repo_url: GitHub 仓库 URL
        branch: 分支名（默认 main）
        thread_id: 可选的 thread ID（用于 LangGraph checkpoint 断点续传）
        use_react_mode: 是否使用 ReAct 模式（默认 True，启用智能自主加载）

    方案：
      1. 用 _workflow.astream() 遍历每个节点（支持断点续传）
      2. 每次节点完成后，调用 get_state() 获取最新完整状态
      3. 根据节点名 + 状态内容，显式 yield 对应的 SSE 事件
      4. tech_stack / quality / dependency / explorer 四个并行节点在
         astream() 内部真正并发执行，都完成后才进入下一节点

    ReAct 模式（use_react_mode=True）：
      fetch_tree_classify → react_loader → explorer → architecture → merge_analysis → react_suggestion

    旧版模式（use_react_mode=False）：
      fetch_tree_classify → load_p0 → ... → code_parser_final → tech_stack/quality/dependency → optimization
    """
    logger.info(f"[stream_analysis_sse] 开始: repo={repo_url}, branch={branch}, thread={thread_id}")

    # 重置 Token 计数器（每个新分析请求独立统计）
    try:
        from utils.llm_factory import reset_token_stats
        reset_token_stats()
    except ImportError:
        pass

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

    initial_state = build_initial_state(repo_url, branch, use_react_mode=use_react_mode)

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
        logger.debug(f"[stream_analysis_sse] 线程已启动，wait q.get()")

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

        # 正常结束 — 记录 Token 使用量统计
        try:
            from utils.llm_factory import get_token_stats
            stats = get_token_stats()
            logger.info(
                f"[stream_analysis_sse] 分析完成: "
                f"input_tokens={stats['total_input_tokens']}, "
                f"output_tokens={stats['total_output_tokens']}, "
                f"total={stats['total_tokens']}, "
                f"calls={stats['total_calls']}"
            )
        except Exception:
            pass

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
            msg_tree_done = f"获取文件树完成，共 {len(tree_items)} 个文件"
            if msg_tree_done not in status_sent:
                status_sent.add(msg_tree_done)
                events.append(format_sse_event({
                    "type": "progress",
                    "agent": "fetch_tree_classify",
                    "message": msg_tree_done,
                    "percent": 15,
                    "data": {"total_files": len(tree_items)},
                }))
            msg_ai_classify = "正在进行 AI 分类..."
            if msg_ai_classify not in status_sent:
                status_sent.add(msg_ai_classify)
                events.append(format_sse_event({
                    "type": "status",
                    "agent": "fetch_tree_classify",
                    "message": msg_ai_classify,
                    "percent": 20,
                    "data": None,
                }))
            msg_classify_done = f"AI 分类完成: P0={len(p0)}, P1={len(p1)}, P2={len(p2)}"
            if msg_classify_done not in status_sent:
                status_sent.add(msg_classify_done)
                events.append(format_sse_event({
                    "type": "progress",
                    "agent": "fetch_tree_classify",
                    "message": msg_classify_done,
                    "percent": 25,
                    "data": {
                        "p0": len(p0), "p1": len(p1), "p2": len(p2),
                        "total_tree_files": len(tree_items),
                    },
                }))

    # ── react_loader（ReAct 模式）────────────────────────────────────
    elif node_name == "react_loader":
        react_events: list[dict] = state.get("react_events") or []
        loaded_files = state.get("loaded_files") or {}
        loaded_paths = state.get("loaded_paths") or []

        if "react_loader" not in status_sent:
            status_sent.add("react_loader")
            events.append(format_sse_event({
                "type": "status",
                "agent": "react_loader",
                "message": "正在使用 ReAct 智能探索仓库...",
                "percent": 25,
                "data": None,
            }))

        # 透传 ReAct 推理步骤的 progress 事件
        for ev in react_events:
            if ev.get("type") == "progress":
                events.append(format_sse_event({
                    "type": "progress",
                    "agent": ev.get("agent", "react_loader"),
                    "message": ev.get("message", ""),
                    "percent": ev.get("percent", 50),
                    "data": ev.get("data"),
                }))

        # result 事件
        for ev in react_events:
            if ev.get("type") == "result":
                data = ev.get("data", {})
                events.append(format_sse_event({
                    "type": "result",
                    "agent": "react_loader",
                    "message": ev.get("message", "ReAct 探索完成"),
                    "percent": data.get("percent", 100),
                    "data": {
                        "total_iterations": data.get("total_iterations"),
                        "loaded_count": len(loaded_paths),
                        "loaded_paths": data.get("loaded_paths", []),
                        "is_sufficient": data.get("is_sufficient"),
                        "summary": data.get("summary", ""),
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

    # ── explorer ─────────────────────────────────────────────────
    elif node_name == "explorer":
        explorer_result = state.get("explorer_result") or {}

        if "explorer" not in status_sent:
            status_sent.add("explorer")
            events.append(format_sse_event({
                "type": "status",
                "agent": "explorer",
                "message": "并行探索启动：TechStack / Quality / Architecture...",
                "percent": 76,
                "data": None,
            }))
        if explorer_result:
            msg_explorer_done = "并行探索完成"
            if msg_explorer_done not in status_sent:
                status_sent.add(msg_explorer_done)
                events.append(format_sse_event({
                    "type": "progress",
                    "agent": "explorer",
                    "message": msg_explorer_done,
                    "percent": 88,
                    "data": explorer_result,
                }))

        # ReAct 模式时，ExplorerOrchestrator 内部已并行执行了 TechStackExplorer、
        # QualityExplorer，结果通过 node_explorer 写入了 state["tech_stack_result"]
        # 和 state["quality_result"]。SSE 层需要主动把它们转发出来（legacy 模式
        # 下这些字段由独立节点写入，本分支不会重复）。
        # 通过检查 state 而非 explorer_result 避免在 legacy 模式下重复发送。
        ts_result = state.get("tech_stack_result")
        if ts_result:
            msg_ts_done = "技术栈识别完成"
            if msg_ts_done not in status_sent:
                status_sent.add(msg_ts_done)
                events.append(format_sse_event({
                    "type": "progress",
                    "agent": "tech_stack",
                    "message": msg_ts_done,
                    "percent": 82,
                    "data": ts_result,
                }))
            # 添加 result 事件用于数据库持久化
            if "tech_stack" not in result_sent:
                result_sent.add("tech_stack")
                events.append(format_sse_event({
                    "type": "result",
                    "agent": "tech_stack",
                    "message": "技术栈分析完成",
                    "percent": 82,
                    "data": ts_result,
                }))

        q_result = state.get("quality_result")
        if q_result:
            msg_q_done = "代码质量分析完成"
            if msg_q_done not in status_sent:
                status_sent.add(msg_q_done)
                events.append(format_sse_event({
                    "type": "progress",
                    "agent": "quality",
                    "message": msg_q_done,
                    "percent": 85,
                    "data": q_result,
                }))
            # 添加 result 事件用于数据库持久化
            if "quality" not in result_sent:
                result_sent.add("quality")
                events.append(format_sse_event({
                    "type": "result",
                    "agent": "quality",
                    "message": "代码质量分析完成",
                    "percent": 85,
                    "data": q_result,
                }))

        # dependency 分析结果始终发送（即使为空，也告知前端分析已完成）
        dep_result = state.get("dependency_result")
        logger.info(f"[SSE] dependency 检查: dep_result={dep_result}, status_sent={status_sent}, result_sent={result_sent}")
        if dep_result is not None and "dependency" not in status_sent:
            status_sent.add("dependency")
            events.append(format_sse_event({
                "type": "status",
                "agent": "dependency",
                "message": "依赖风险分析完成",
                "percent": 87,
                "data": None,
            }))
            if "dependency" not in result_sent:
                result_sent.add("dependency")
                events.append(format_sse_event({
                    "type": "result",
                    "agent": "dependency",
                    "message": "依赖风险分析完成",
                    "percent": 87,
                    "data": dep_result or {},
                }))

    # ── architecture ────────────────────────────────────────────────
    elif node_name == "architecture":
        result = state.get("architecture_result") or {}

        # 透传 ArchitectureAgent.stream() 产生的所有中间事件
        arch_events: list[dict] = state.get("architecture_events") or []
        for ev in arch_events:
            # 跳过 status（由下面统一发），其余透传
            if ev.get("type") == "status":
                continue
            msg = ev.get("message") or "架构分析中..."
            if msg not in status_sent:
                status_sent.add(msg)
                events.append(format_sse_event({
                    "type": ev.get("type", "progress"),
                    "agent": ev.get("agent", "architecture"),
                    "message": msg,
                    "percent": ev.get("percent", 88),
                    "data": ev.get("data"),
                }))

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
            msg_done = "架构评估完成"
            if msg_done not in status_sent:
                status_sent.add(msg_done)
                events.append(format_sse_event({
                    "type": "progress",
                    "agent": "architecture",
                    "message": msg_done,
                    "percent": 91,
                    "data": result,
                }))
            if "architecture" not in result_sent:
                result_sent.add("architecture")
                events.append(format_sse_event({
                    "type": "result",
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

        # 透传 SuggestionAgent.stream() 产生的所有中间事件
        #（RAG 检索进度、LLM 调用进度等，在 node_optimization 中已收集到状态）
        opt_events: list[dict] = state.get("optimization_events") or []
        for ev in opt_events:
            # 不重复发送已发送过的 result
            if ev.get("type") == "result" and "optimization_result" in result_sent:
                continue
            # 跳过 status（已在上面统一发过），其余类型直接透传
            if ev.get("type") == "status":
                continue
            ev_type = ev.get("type", "progress")
            ev_percent = ev.get("percent", 93)
            ev_message = ev.get("message") or "生成优化建议中..."
            ev_data = ev.get("data")
            events.append(format_sse_event({
                "type": ev_type,
                "agent": ev.get("agent", "optimization"),
                "message": ev_message,
                "percent": ev_percent,
                "data": ev_data,
            }))
            if ev_type == "result":
                result_sent.add("optimization_result")

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

    # ── react_suggestion（ReAct 模式）───────────────────────────────
    elif node_name == "react_suggestion":
        opt_events: list[dict] = state.get("optimization_events") or []
        opt_result = state.get("optimization_result") or state.get("suggestion_result")
        final_result = state.get("final_result")

        if "react_suggestion" not in status_sent:
            status_sent.add("react_suggestion")
            events.append(format_sse_event({
                "type": "status",
                "agent": "optimization",
                "message": "正在使用 ReAct 生成优化建议（主动验证中）...",
                "percent": 93,
                "data": None,
            }))

        # 透传 ReActSuggestionAgent.stream() 产生的所有中间事件
        for ev in opt_events:
            if ev.get("type") == "status":
                continue
            ev_type = ev.get("type", "progress")
            ev_percent = ev.get("percent", 93)
            ev_message = ev.get("message") or "生成优化建议中..."
            ev_data = ev.get("data")
            events.append(format_sse_event({
                "type": ev_type,
                "agent": ev.get("agent", "react_suggestion"),
                "message": ev_message,
                "percent": ev_percent,
                "data": ev_data,
            }))
            if ev_type == "result":
                result_sent.add("react_suggestion_result")

        # 发送 react_suggestion result
        if opt_result and "react_suggestion" not in result_sent:
            result_sent.add("react_suggestion")
            events.append(format_sse_event({
                "type": "result",
                "agent": "optimization",
                "message": f"ReAct 生成了优化建议",
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
    use_react_mode: bool = True,
) -> dict:
    """同步运行 LangGraph 工作流，直接返回最终结果（供非 SSE 场景使用）。

    Args:
        repo_url: GitHub 仓库 URL
        branch: 分支名（默认 main）
        thread_id: 可选的 thread ID（用于 LangGraph checkpoint 断点续传）
        use_react_mode: 是否使用 ReAct 模式（默认 True）

    Returns:
        final_result: 包含所有分析结果的字典
    """
    config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id or f"{repo_url}::{branch}",
        }
    }

    initial_state = build_initial_state(repo_url, branch, use_react_mode=use_react_mode)
    final_state = _workflow.invoke(initial_state, config=config)
    return final_state.get("final_result") or {}


def build_initial_state(
    repo_url: str,
    branch: str = "main",
    use_react_mode: bool = True,
) -> SharedState:
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
        use_react_mode=use_react_mode,
        react_events=[],
        react_summary="",
        react_iterations=0,
        loaded_paths=[],
        explorer_result=None,
        explorer_events=[],
    )
