"""
GitIntel 分析 Pipeline — LangGraph 工作流 + SSE 流式输出（ReAct 纯模式）。

整体 Pipeline（线性，ReAct 自主探索）：

    react_loader ──► explorer ──► architecture ──► react_suggestion ──► END

流程说明：
  1. react_loader: ReActRepoLoaderAgent 通过 Thought→Action→Observation 循环，
     自主决定加载哪些文件（替代旧版的 fetch_tree_classify + 渐进加载链）
  2. explorer: ExplorerOrchestrator 并行驱动 TechStackExplorer / QualityExplorer /
     ArchitectureExplorer 自主探索
  3. architecture: 基于 explorer 结果 + code_parser 做架构评估
  4. react_suggestion: ReActSuggestionAgent 通过工具验证每个问题，生成精确可执行的 code_fix

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

logger = logging.getLogger("gitintel")

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END

from agents import (
    ReActRepoLoaderAgent,
    ReActSuggestionAgent,
    ExplorerOrchestrator,
)
from .state import SharedState
from .executor import (
    format_sse_event,
    format_sse_error,
    parse_repo_url,
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


def node_react_loader(state: SharedState) -> dict:
    """节点 1：ReAct 模式的智能仓库加载。

    ReActRepoLoaderAgent 通过 Thought → Action → Observation 循环自主探索：
      1. Agent 先获取仓库信息和文件树
      2. 自主决定调用什么工具、加载什么文件
      3. 直到达到 max_files (50) 或 agent 认为足够

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
    result_ref: list[dict] = []

    def run_react():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def consume():
                agent = ReActRepoLoaderAgent()
                result = await agent.explore(owner, repo, branch)

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

                    if call.tool_name in ("get_file_blobs", "read_file_content"):
                        react_events.append({
                            "type": "progress",
                            "agent": "react_loader",
                            "message": f"加载: {call.observation[:60]}",
                            "percent": min(50, 30 + len(result.loaded_paths) * 0.8),
                            "data": {"loaded_count": len(result.loaded_paths)},
                        })

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

    all_events: list[dict] = []
    while True:
        item = q.get()
        if item is None:
            break
        all_events.append(item)

    loaded_files: dict[str, str] = {}
    loaded_paths: list[str] = []
    repo_sha = branch
    if result_ref:
        loaded_files = result_ref[0].get("loaded_files", {})
        loaded_paths = result_ref[0].get("loaded_paths", [])
        repo_sha = result_ref[0].get("repo_sha", branch)

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
        logger.warning(f"[node_react_loader] ReAct 无结果")
        return {
            "errors": exc_info + ["ReAct 无结果"],
            "react_events": all_events,
            "react_summary": summary,
            "react_iterations": iterations,
            "finished_agents": [],
            "repo_sha": repo_sha,
        }


def node_explorer(state: SharedState) -> dict:
    """节点 2：并行 ReAct 探索。

    ExplorerOrchestrator 并行驱动多个子 Explorer：
      - TechStackExplorer:   技术栈识别
      - QualityExplorer:     质量热点发现
      - ArchitectureExplorer: 架构模式识别
      - DependencyExplorer:  依赖关系分析

    同时在主线程中执行代码解析（code_parser_result）和依赖分析（dependency_result），
    供 architecture 节点使用。

    SSE 事件：explorer_events 透传到前端，显示每个 Agent 的探索进度。
    """
    import queue as _q_module
    import threading

    repo_url = state.get("repo_url", "")
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {"errors": ["node_explorer: 无法解析 repo_url"]}

    owner, repo = parsed
    branch = state.get("branch", "main")
    file_contents = state.get("loaded_files") or {}

    logger.info(f"[node_explorer] 入参: file_contents={len(file_contents) if file_contents else 0} 个文件")

    q: Any = _q_module.Queue()
    exc_info: list = []
    explorer_events: list[dict] = []
    code_parser_result: dict = {}
    dependency_result: dict | None = None

    # ── 代码解析 ──────────────────────────────────────────────────────
    if file_contents:
        try:
            from agents.legacy import CodeParserAgent
            files = [{"path": path, "content": content} for path, content in file_contents.items()]
            if files:
                code_parser_result = asyncio.run(
                    CodeParserAgent()._analyze_inmemory_files(files)
                )
                logger.info(f"[node_explorer] 代码解析完成: {len(files)} 个文件")
        except Exception as e:
            logger.warning(f"[node_explorer] 代码解析失败: {e}")
            exc_info.append(str(e))

    # ── 依赖分析 ──────────────────────────────────────────────────────
    try:
        loop2 = asyncio.new_event_loop()
        asyncio.set_event_loop(loop2)

        async def run_dep():
            from agents.legacy import DependencyAgent
            agent = DependencyAgent()
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

    # ── 并行 ReAct 探索 ───────────────────────────────────────────────
    def run_explorers():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def consume():
                explorer_events.append({
                    "type": "status",
                    "agent": "explorer",
                    "message": "并行探索启动：TechStack / Quality / Architecture",
                    "percent": 50,
                    "data": None,
                })

                results = await ExplorerOrchestrator().explore_all(
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

    all_events: list[dict] = []
    while True:
        item = q.get()
        if item is None:
            break
        all_events.append(item)

    all_events = explorer_events + all_events

    result: dict = {}
    for event in all_events:
        if event.get("type") == "result":
            result = event.get("data") or {}

    return_val: dict = {
        "explorer_result": result,
        "explorer_events": all_events,
        "errors": exc_info,
    }

    if file_contents:
        return_val["file_contents"] = file_contents

    if code_parser_result:
        return_val["code_parser_result"] = code_parser_result

    if dependency_result is not None:
        logger.info(f"[node_explorer] 写入 dependency_result 到状态: {dependency_result}")
        return_val["dependency_result"] = dependency_result

    # Explorer 结果映射到对应字段（供后续节点使用）
    if result:
        if "TechStackExplorer" in result:
            ts_data = result["TechStackExplorer"]
            return_val["tech_stack_result"] = ts_data.get("findings", ts_data) if isinstance(ts_data, dict) else ts_data
        if "QualityExplorer" in result:
            q_data = result["QualityExplorer"]
            return_val["quality_result"] = q_data.get("findings", q_data) if isinstance(q_data, dict) else q_data
        if "ArchitectureExplorer" in result:
            arch_data = result["ArchitectureExplorer"]
            return_val["architecture_result"] = arch_data.get("findings", arch_data) if isinstance(arch_data, dict) else arch_data

    return return_val


def node_architecture(state: SharedState) -> dict:
    """节点 3：架构评估。

    ArchitectureAgent 综合代码结构、依赖关系、技术栈特征，给出架构评估。

    流式执行：
      1. 后台线程驱动 ArchitectureAgent.stream() 异步迭代器
      2. 所有中间事件收集到 architecture_events
      3. SSE 层通过 _yield_sse_for_node 将事件逐个透传到前端
    """
    import queue as _queue_module
    import threading

    repo_url = state.get("repo_url", "")
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {"errors": ["node_architecture: 无法解析 repo_url"]}

    owner, repo = parsed
    branch = state.get("branch", "main")
    loaded_paths = state.get("loaded_paths") or []
    total_tree_files = len(loaded_paths)

    q: Any = _queue_module.Queue()
    exc_info: list = []

    def run_stream():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def consume():
                from agents.legacy import ArchitectureAgent
                agent = ArchitectureAgent()
                async for event in agent.stream(
                    f"{owner}/{repo}",
                    branch,
                    code_parser_result=state.get("code_parser_result"),
                    tech_stack_result=state.get("tech_stack_result"),
                    quality_result=state.get("quality_result"),
                    total_tree_files=total_tree_files,
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


def node_react_suggestion(state: SharedState) -> dict:
    """节点 4：ReAct 模式的优化建议生成。

    ReActSuggestionAgent 通过工具验证每个问题，生成精确可执行的 code_fix：
      1. 构建分析上下文（技术栈/质量/依赖/架构数据）
      2. RAG 检索历史经验
      3. ReAct 循环：Agent 调用工具验证问题（搜索代码/读文件/解析 AST）
      4. 基于验证结果生成精确建议
      5. 存储高优先级建议到 RAG

    构建 final_result 打包所有分析数据，供前端展示。
    """
    import queue as _q_module
    import threading

    repo_url = state.get("repo_url", "")
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {"errors": ["node_react_suggestion: 无法解析 repo_url"]}

    owner, repo = parsed
    branch = state.get("branch", "main")
    repo_id = f"{owner}/{repo}"
    file_contents = state.get("loaded_files") or {}

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

    # 如果 ReActSuggestionAgent 返回空结果，生成兜底建议
    if not result or not result.get("suggestions"):
        logger.warning("[node_react_suggestion] ReActSuggestionAgent 返回空结果，使用兜底建议")
        fallback = _generate_fallback_suggestions(state)
        if fallback:
            result = fallback
            all_events.append({
                "type": "result",
                "agent": "optimization",
                "message": "兜底建议生成完成",
                "percent": 100,
                "data": result,
            })

    # repo_sha 从 react_loader 节点已写入 state
    repo_sha = state.get("repo_sha", branch)
    final_result = {
        "repo_loader": {
            "owner": owner,
            "repo": repo,
            "branch": branch,
            "repo_sha": repo_sha,
            "total_files": len(state.get("loaded_files", {})),
            "loaded_count": len(state.get("loaded_paths", [])),
        },
        "code_parser": state.get("code_parser_result"),
        "tech_stack": state.get("tech_stack_result"),
        "quality": _normalize_explorer_result(state.get("quality_result") or {}),
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


def _generate_fallback_suggestions(state: SharedState) -> dict:
    """基于已有分析数据生成兜底建议。"""
    from agents.react.suggestion_agent import _quality_suggestions_impl, _dependency_suggestions_impl

    suggestions = []
    _id = [1]

    def next_id():
        v = _id[0]
        _id[0] += 1
        return v

    quality_result = state.get("quality_result")
    if quality_result and isinstance(quality_result, dict):
        try:
            suggestions.extend(_quality_suggestions_impl(quality_result, next_id))
        except Exception as e:
            logger.warning(f"[_generate_fallback_suggestions] _quality_suggestions_impl 失败: {e}")

    dependency_result = state.get("dependency_result")
    if dependency_result and isinstance(dependency_result, dict):
        try:
            suggestions.extend(_dependency_suggestions_impl(dependency_result, next_id))
        except Exception as e:
            logger.warning(f"[_generate_fallback_suggestions] _dependency_suggestions_impl 失败: {e}")

    architecture_result = state.get("architecture_result")
    if architecture_result and isinstance(architecture_result, dict):
        concerns = architecture_result.get("concerns", [])
        for concern in concerns[:3]:
            suggestions.append({
                "id": next_id(),
                "type": "architecture",
                "title": "架构优化建议",
                "description": str(concern),
                "priority": "medium",
                "category": "architecture",
                "source": "fallback",
            })

    if not suggestions:
        suggestions.append({
            "id": next_id(),
            "type": "general",
            "title": "项目分析完成",
            "description": "分析已完成，未检测到需要紧急处理的问题。",
            "priority": "low",
            "category": "general",
            "source": "fallback",
        })

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


# ─── 构建 LangGraph ─────────────────────────────────────────────────────


def _build_graph() -> StateGraph:
    """构建并编译 LangGraph 工作流（ReAct 纯模式）。

    图结构：
      react_loader ──► explorer ──► architecture ──► react_suggestion ──► END

    线性流程，无条件分支，每个节点执行完后直接进入下一个节点。
    """
    graph = StateGraph(state_schema=SharedState)

    # 节点注册
    graph.add_node("react_loader", node_react_loader)
    graph.add_node("explorer", node_explorer)
    graph.add_node("architecture", node_architecture)
    graph.add_node("react_suggestion", node_react_suggestion)

    # 线性流程
    graph.set_entry_point("react_loader")
    graph.add_edge("react_loader", "explorer")
    graph.add_edge("explorer", "architecture")
    graph.add_edge("architecture", "react_suggestion")
    graph.add_edge("react_suggestion", END)

    return graph


# 编译后的工作流（全局单例）
_workflow = _build_graph().compile(checkpointer=_checkpointer)


# ══════════════════════════════════════════════════════════════════════════
#  SSE 流式输出层
#
#  使用 _workflow.astream() 按顺序遍历每个节点，
#  每次节点完成后通过 get_state() 获取最新状态快照，
#  根据节点名称和状态内容，显式 yield 对应的 SSE 事件。
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
) -> Generator[str, None, None]:
    """SSE 流式接口：LangGraph 工作流 + 实时 SSE 事件（ReAct 纯模式）。

    流程：react_loader ──► explorer ──► architecture ──► react_suggestion

    Args:
        repo_url: GitHub 仓库 URL
        branch: 分支名（默认 main）
        thread_id: 可选的 thread ID（用于 LangGraph checkpoint 断点续传）
    """
    logger.info(f"[stream_analysis_sse] 开始: repo={repo_url}, branch={branch}, thread={thread_id}")

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

    initial_state = build_initial_state(repo_url, branch)

    yield format_sse_event({
        "type": "status",
        "agent": "pipeline",
        "message": f"正在连接分析引擎，repo={owner}/{repo}...",
        "percent": 1,
        "data": {"repo_url": repo_url, "branch": branch},
    })

    status_sent: set[str] = set()
    result_sent: set[str] = set()

    try:
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
                    q.put(None)

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

        # 分析完成，保存到缓存
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

        final_state = _workflow.get_state(config).values
        final_result = final_state.get("final_result") or {}

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
    """将 astream 迭代的 chunk 分发为 SSE 事件。"""
    if isinstance(chunk, dict):
        chunk_type = chunk.get("type", "")
        if chunk_type == "updates":
            node_data_map = chunk.get("data", {})
            if isinstance(node_data_map, dict):
                for node_name, node_output in node_data_map.items():
                    for sse in _yield_sse_for_node(node_name, node_output, config, owner, repo, status_sent, result_sent):
                        yield sse
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
                    yield sse
        else:
            for node_name, node_output in chunk.items():
                for sse in _yield_sse_for_node(node_name, node_output, config, owner, repo, status_sent, result_sent):
                    yield sse
    else:
        try:
            if len(chunk) == 2:
                node_name, node_output = chunk
                for sse in _yield_sse_for_node(node_name, node_output, config, owner, repo, status_sent, result_sent):
                    yield sse
        except (TypeError, ValueError):
            logger.warning(f"[stream_analysis_sse] 无法解析 chunk: {type(chunk)}")


def _normalize_explorer_result(data: dict) -> dict:
    """将不同 Agent 格式的输出标准化为前端期望的字段名。

    QualityExplorer → QualityAgentCard 期望：
      complexity → qualityComplexity
      maintainability → qualityMaintainability
      test_coverage → test_coverage_estimate
      health_score / llmPowered / maint_score / comp_score / dup_score / test_score / coup_score

    如果这些字段缺失（QualityExplorer 未返回），则从已有数据推导默认值。
    所有其他 explorer 保持原样。
    """
    if not isinstance(data, dict):
        return data

    # 标准化字段名（legacy QualityAgent 用旧名，Explorer 用新名）
    # 只在源字段存在时才覆盖，避免 Explorer 已返回正确字段名却被 None 覆盖
    normalized = {k: v for k, v in data.items()}
    if "complexity" in data:
        normalized["qualityComplexity"] = data["complexity"]
    if "maintainability" in data:
        normalized["qualityMaintainability"] = data["maintainability"]
    if "test_coverage" in data:
        normalized["test_coverage_estimate"] = data["test_coverage"]

    # 补全前端依赖但 Explorer 可能缺失的字段
    if "health_score" not in normalized:
        normalized["health_score"] = 75.0
    if "llmPowered" not in normalized:
        normalized["llmPowered"] = False
    if "maint_score" not in normalized:
        normalized["maint_score"] = 70
    if "comp_score" not in normalized:
        normalized["comp_score"] = 70
    if "dup_score" not in normalized:
        dup = data.get("duplication", {})
        dup_score = dup.get("score", 0) if isinstance(dup, dict) else 0
        normalized["dup_score"] = round(100 - dup_score, 1)
    if "test_score" not in normalized:
        normalized["test_score"] = 30
    if "coup_score" not in normalized:
        normalized["coup_score"] = 70

    return normalized


def _state_to_sse_events(
    node_name: str,
    state: dict,
    owner: str,
    repo: str,
    status_sent: set[str],
    result_sent: set[str],
) -> list[str]:
    """将 LangGraph 状态快照转换为 SSE 事件列表。"""
    events: list[str] = []

    # ── react_loader ────────────────────────────────────────────────────
    if node_name == "react_loader":
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

        for ev in react_events:
            if ev.get("type") == "progress":
                events.append(format_sse_event({
                    "type": "progress",
                    "agent": ev.get("agent", "react_loader"),
                    "message": ev.get("message", ""),
                    "percent": ev.get("percent", 50),
                    "data": ev.get("data"),
                }))

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
                        "repo_sha": state.get("repo_sha"),
                    },
                }))

    # ── explorer ──────────────────────────────────────────────────────
    elif node_name == "explorer":
        explorer_result = state.get("explorer_result") or {}

        if "explorer" not in status_sent:
            status_sent.add("explorer")
            events.append(format_sse_event({
                "type": "status",
                "agent": "explorer",
                "message": "并行探索启动：TechStack / Quality / Architecture...",
                "percent": 50,
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
                    "percent": 76,
                    "data": explorer_result,
                }))

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
            q_normalized = _normalize_explorer_result(q_result)
            msg_q_done = "代码质量分析完成"
            if msg_q_done not in status_sent:
                status_sent.add(msg_q_done)
                events.append(format_sse_event({
                    "type": "progress",
                    "agent": "quality",
                    "message": msg_q_done,
                    "percent": 85,
                    "data": q_normalized,
                }))
            if "quality" not in result_sent:
                result_sent.add("quality")
                events.append(format_sse_event({
                    "type": "result",
                    "agent": "quality",
                    "message": "代码质量分析完成",
                    "percent": 85,
                    "data": q_normalized,
                }))

        dep_result = state.get("dependency_result")
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

        arch_events: list[dict] = state.get("architecture_events") or []
        for ev in arch_events:
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

    # ── react_suggestion ──────────────────────────────────────────────
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

        if opt_result and "react_suggestion" not in result_sent:
            result_sent.add("react_suggestion")
            events.append(format_sse_event({
                "type": "result",
                "agent": "optimization",
                "message": f"ReAct 生成了优化建议",
                "percent": 98,
                "data": opt_result,
            }))

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


# ─── 同步执行接口 ──────────────────────────────────────────────────────


def run_analysis_sync(
    repo_url: str,
    branch: str = "main",
    thread_id: str | None = None,
) -> dict:
    """同步运行 LangGraph 工作流，直接返回最终结果。"""
    config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id or f"{repo_url}::{branch}",
        }
    }

    initial_state = build_initial_state(repo_url, branch)
    final_state = _workflow.invoke(initial_state, config=config)
    return final_state.get("final_result") or {}


def build_initial_state(
    repo_url: str,
    branch: str = "main",
) -> SharedState:
    """构建 LangGraph 初始状态。

    所有字段使用默认值，表示从头开始执行。
    如果 thread_id 已有 checkpoint，invoke 时会从 checkpoint 恢复而非用此初始状态。
    """
    return SharedState(
        repo_url=repo_url,
        branch=branch,
        file_contents={},
        loaded_files={},
        loaded_paths=[],
        repo_sha=None,
        code_parser_result=None,
        tech_stack_result=None,
        quality_result=None,
        dependency_result=None,
        suggestion_result=None,
        optimization_result=None,
        final_result=None,
        errors=[],
        finished_agents=[],
        react_events=[],
        react_summary="",
        react_iterations=0,
        explorer_result=None,
        explorer_events=[],
        architecture_result=None,
        architecture_events=[],
    )
