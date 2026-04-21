"""
ReActRepoLoaderAgent — 基于 ReAct 模式的智能仓库加载 Agent。

与旧版 RepoLoaderAgent 的核心区别：
  - 不再是预设的 P0/P1/P2 流程，而是 Agent 自主决策
  - 每次迭代，Agent 决定调用什么工具、加载什么文件
  - 工具调用记录作为推理过程，可解释性强
  - 支持 LangChain Function Calling，Agent 动态选择工具

工具集：
  GitHub:  get_repo_info, get_file_tree, read_file_content, get_file_blobs,
           search_code, get_commit_history, get_pull_requests
  Code:    parse_file_ast, summarize_code_file, calculate_complexity

工作流程（ReAct 循环）：
  Thought → Action → Observation → Thought → Action → ... → Response

停止条件：
  - 总加载文件数达到 MAX_FILES (50)
  - 迭代轮次达到 MAX_ITERATIONS (10)
  - Agent 认为信息足够（is_sufficient=true）
"""
import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from tools.github_tools import (
    get_repo_info, get_file_tree, read_file_content,
    get_file_blobs, search_code, get_commit_history,
    get_pull_requests, get_default_branch,
    _get_repo_info_impl, _get_file_tree_impl, _get_default_branch_impl,
)
from tools.code_tools import parse_file_ast, summarize_code_file

logger = logging.getLogger("gitintel")

# ─── Token 预算配置（可由环境变量覆盖）───────────────────────────────────────

_MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "2048"))
_REPO_LOADER_MAX_ITERATIONS = int(os.getenv("REPO_LOADER_MAX_ITERATIONS", "5"))
_TOOL_RESULT_TRUNCATE = int(os.getenv("TOOL_RESULT_TRUNCATE", "1500"))


# ─── 工具列表 ────────────────────────────────────────────────────────────────

REACT_TOOLS = [
    get_repo_info,
    get_file_tree,
    read_file_content,
    get_file_blobs,
    search_code,
    get_commit_history,
    get_pull_requests,
    get_default_branch,
    parse_file_ast,
    summarize_code_file,
]

# ─── System Prompt ─────────────────────────────────────────────────────────────

REACT_SYSTEM_PROMPT = """你是 GitIntel 系统的代码仓库探索 Agent，分析 GitHub 仓库生成报告。

你的探索质量直接影响最终分析的深度和准确性。

【重要】初始上下文已包含完整的文件树（文件树概览），请直接从中选择文件加载，
不要重复调用 get_file_tree。

工具（按需调用）：
  - get_repo_info(owner, repo): 仓库基本信息（通常只需调用一次）
  - get_file_tree(owner, repo, ref): 完整文件树（**已包含在初始上下文中**，通常无需重复调用）
  - get_file_blobs(owner, repo, paths, ref): **批量读取多个文件（优先使用）**
  - read_file_content(owner, repo, path, ref): 读取单个文件
  - search_code(owner, repo, query, language): 搜索代码（谨慎使用，GitHub API 有频率限制）
  - get_commit_history(owner, repo, ref, limit): 提交历史
  - parse_file_ast(file_path, content, language): AST 结构
  - summarize_code_file(content, max_lines): 文件摘要

**正确的工作流示例**：
  1. 第一轮：直接调用 get_file_blobs 批量加载入口文件 + 配置文件
  2. 第二轮：根据已加载的文件内容，调用 get_file_blobs 加载核心业务文件
  3. 第三轮：如有需要，补充加载路由/模型/中间件文件，然后输出 is_sufficient=true

优先级（从高到低）：
  1. 入口文件：main.py, index.ts, app.js, App.tsx, server.js, main.go
  2. 核心业务：services/, core/, domain/, handlers/, controllers/
  3. 配置文件：package.json, requirements.txt, pyproject.toml, go.mod, Dockerfile, docker-compose.yml
  4. 数据模型：models/, schemas/, types/, entities/
  5. 路由/API：routes/, api/, endpoints/
  6. 中间件/工具：middleware/, utils/, helpers/

跳过（价值低且浪费token）：
  - node_modules/, .git/, build/, dist/, .next/, __pycache__/, .venv/
  - 纯测试文件、文档文件、二进制文件

停止条件（满足任一即停止）：
  1. 已加载文件涵盖入口、配置和主要业务逻辑（通常 20-40 个文件）
  2. 总加载文件数达 45 个
  3. 迭代轮次达 8 次
  4. Agent 认为信息已足够

**注意**：初始上下文已包含完整文件树，使用 get_file_blobs 直接批量加载，不要重复获取文件树。

输出格式（每轮）：
  Thought: <思考>
  Action: {"name": "get_file_blobs", "args": {"owner": "...", "repo": "...", "paths": ["文件路径1", "文件路径2"], "ref": "..."}}
  Observation: <关键信息>

结束时输出：
  is_sufficient: true
  summary: |
    <探索总结：技术栈、主要模块及职责、关键文件清单(最多15个)、架构特点>"""


# ─── 推理记录结构 ────────────────────────────────────────────────────────────

@dataclass
class ToolCall:
    iteration: int
    thought: str
    tool_name: str
    tool_args: dict[str, Any]
    observation: str = ""
    error: str = ""
    elapsed_ms: float = 0.0


@dataclass
class ExplorationResult:
    owner: str
    repo: str
    branch: str
    sha: str = ""
    loaded_files: dict[str, str] = field(default_factory=dict)
    loaded_paths: list[str] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    is_sufficient: bool = False
    summary: str = ""
    total_iterations: int = 0
    errors: list[str] = field(default_factory=list)
    # 完整文件树路径集合（所有候选文件），供每轮迭代上下文使用
    all_tree_paths: list[str] = field(default_factory=list)


# ─── 核心 Agent ───────────────────────────────────────────────────────────────

class ReActRepoLoaderAgent:
    """基于 ReAct 模式的仓库加载 Agent。

    特性：
      - 动态工具选择：Agent 根据当前状态自主决定调用哪个工具
      - 可解释推理：每轮的 Thought/Action/Observation 都记录在案
      - 渐进式探索：从浅到深，逐步了解仓库
      - 流式输出：支持实时 yield 中间推理步骤

    使用示例：
        agent = ReActRepoLoaderAgent()
        result = await agent.explore("owner", "repo", "main")
        print(result.loaded_files)   # 加载的文件内容
        print(result.summary)         # 探索总结
        print(result.tool_calls)      # 推理过程
    """

    MAX_ITERATIONS = _REPO_LOADER_MAX_ITERATIONS  # 由环境变量控制，默认 8
    MAX_FILES = 50       # 最多加载文件数
    MAX_TOKENS_PER_STEP = 2000  # 每步最大 token 预算（控制 LLM 输出）

    def __init__(self):
        from utils.llm_factory import get_llm_with_tracking
        self.llm = self._get_llm()

    @staticmethod
    def _get_llm():
        """懒加载 LLM client（带 Token 追踪）。"""
        try:
            from utils.llm_factory import get_llm_with_tracking
            llm = get_llm_with_tracking(agent_name="ReActRepoLoader", max_tokens=_MAX_OUTPUT_TOKENS)
            if llm is None:
                logger.warning("[ReActRepoLoader] LLM 不可用，将使用规则模式")
            return llm
        except ImportError:
            logger.warning("[ReActRepoLoader] 无法导入 llm_factory")
            return None

    async def explore(
        self,
        owner: str,
        repo: str,
        branch: str = "main",
        max_iterations: int | None = None,
        max_files: int | None = None,
    ) -> ExplorationResult:
        """执行 ReAct 探索循环。

        Args:
            owner:          仓库所有者
            repo:           仓库名
            branch:         分支名
            max_iterations: 最大迭代次数（覆盖默认值）
            max_files:      最大加载文件数（覆盖默认值）

        Returns:
            ExplorationResult，包含所有加载的文件、推理过程和总结
        """
        result = ExplorationResult(
            owner=owner, repo=repo, branch=branch
        )

        max_iter = max_iterations or self.MAX_ITERATIONS
        max_f = max_files or self.MAX_FILES

        if self.llm is None:
            # LLM 不可用时，使用规则模式（基于文件树做启发式选择）
            return await self._explore_rule_based(owner, repo, branch, result, max_f)

        try:
            result.sha = await self._get_sha(owner, repo, branch)
        except Exception as e:
            logger.warning(f"[ReActRepoLoader] 获取 SHA 失败: {e}，使用 branch 名")
            result.sha = branch

        # 构建初始上下文（同时保存完整文件树供后续迭代使用）
        info, tree = await asyncio.gather(
            _get_repo_info_impl(owner, repo),
            _get_file_tree_impl(owner, repo, result.sha or branch),
        )
        result.all_tree_paths = [t["path"] for t in tree if t.get("type") == "blob"]
        initial_context = await self._build_initial_context(owner, repo, branch, result.sha, info, tree)
        messages = [
            SystemMessage(content=REACT_SYSTEM_PROMPT),
            HumanMessage(content=initial_context),
        ]

        for iteration in range(max_iter):
            result.total_iterations = iteration + 1

            if len(result.loaded_paths) >= max_f:
                logger.info(f"[ReActRepoLoader] 已达最大文件数 {max_f}，停止探索")
                break

            try:
                msg_count_before = len(messages)
                step_result = await self._run_single_step(
                    owner, repo, branch, result.sha, result, messages, iteration
                )
                # 只追加本步新增的消息（避免历史重复追加）
                messages.extend(step_result["messages"])

                # 防止消息历史无限膨胀：压缩对话历史，避免破坏 tool_calls 消息链
                # 当消息超过 8 条时，将之前的对话轮压缩为摘要 + 最近 2 轮完整对话
                # 保证 SystemMessage 之后只有 HumanMessage + AIMessage(tool_calls) + ToolMessage 结构
                if len(messages) > 8:
                    self._compress_history(messages)

                if step_result["is_sufficient"]:
                    result.is_sufficient = True
                    result.summary = step_result.get("summary", "")
                    logger.info(f"[ReActRepoLoader] Agent 认为信息足够，停止探索")
                    break

            except Exception as e:
                logger.error(f"[ReActRepoLoader] 迭代 {iteration + 1} 异常: {e}")
                # LLM 调用失败（如 400）时，_run_single_step 可能已追加了 AIMessage 和 ToolMessage，
                # 必须回滚这些部分追加的消息，避免破坏下一轮的消息链。
                messages[:] = messages[:msg_count_before]
                result.errors.append(f"迭代 {iteration + 1}: {str(e)}")
                if len(result.errors) >= 3:
                    logger.warning("[ReActRepoLoader] 错误过多，停止探索")
                    break

        if not result.summary:
            result.summary = self._build_summary(result)

        logger.info(
            f"[ReActRepoLoader] 探索完成: "
            f"{result.total_iterations} 轮, "
            f"{len(result.loaded_paths)} 个文件, "
            f"sufficient={result.is_sufficient}"
        )
        return result

    async def _get_sha(self, owner: str, repo: str, branch: str) -> str:
        """获取分支的 SHA。直接 await 底层 async impl。"""
        result = await _get_default_branch_impl(owner, repo)
        return result.strip()

    async def _build_initial_context(
        self, owner: str, repo: str, branch: str, sha: str,
        info: dict, tree: list[dict],
    ) -> str:
        """构建初始上下文。info 和 tree 由调用方预先获取，避免重复请求。"""
        context_parts = [f"# 仓库探索任务\n目标仓库: {owner}/{repo}@{branch}\n"]

        context_parts.append(f"## 仓库基本信息\n")
        context_parts.append(f"- 默认分支: {info.get('default_branch', branch)}")
        context_parts.append(f"- 语言: {info.get('language', '未知')}")
        context_parts.append(f"- Stars: {info.get('stars', 0)}")
        context_parts.append(f"- Topics: {', '.join(info.get('topics', [])[:10]) or '无'}")
        if info.get("description"):
            context_parts.append(f"- 描述: {info.get('description')}")

        # 文件树
        blobs = [t for t in tree if t.get("type") == "blob"]
        dirs = set()
        for t in blobs:
            path = t.get("path", "")
            if "/" in path:
                dirs.add(path.split("/")[0])

        context_parts.append(f"\n## 文件树概览\n")
        context_parts.append(f"- 总文件数: {len(blobs)}")
        context_parts.append(f"- 顶层目录: {', '.join(sorted(dirs)[:15])}")
        # 展示完整文件树，让 LLM 在每轮迭代时都能看到所有候选文件
        context_parts.append(f"\n### 仓库文件清单（共 {len(blobs)} 个，全部可用）:\n")
        for t in blobs:
            context_parts.append(f"- {t['path']}")

        context_parts.append(
            f"\n## 任务\n"
            f"请从上方文件清单中选取关键文件进行加载，理解其技术栈和架构。\n"
            f"**重要**：只能加载文件清单中列出的文件，禁止猜测不在清单中的文件路径！\n"
            f"当已了解足够信息时，输出 is_sufficient=true 和总结。"
        )

        return "\n".join(context_parts)

    async def _run_single_step(
        self,
        owner: str, repo: str, branch: str, sha: str,
        result: ExplorationResult,
        messages: list,
        iteration: int,
    ) -> dict:
        """执行单步 ReAct 循环。"""
        import time

        # 记录本步新增消息的起始位置（用于外层正确追加和回滚）
        start_idx = len(messages)

        # 注入上下文信息
        context = self._build_iteration_context(owner, repo, sha, result, iteration)
        messages.append(HumanMessage(content=context))

        # LLM 生成工具调用
        llm_with_tools = self.llm.bind_tools(
            REACT_TOOLS,
            parallel_tool_calls=False,  # 一次只调用一个工具（更可控）
        )

        response = await llm_with_tools.ainvoke(messages)
        messages.append(response)

        tool_calls = response.tool_calls or []
        if not tool_calls:
            # 尝试从文本 content 中解析 Action JSON（兼容不返回 tool_calls 的模型）
            content = response.content or ""
            parsed = self._parse_actions_from_text(content)
            if parsed:
                tool_calls = parsed
                # 替换 response：补上 tool_calls，使后续 ToolMessage 能正确关联
                response = AIMessage(
                    content=content,
                    tool_calls=[
                        {"name": p["name"], "args": p["args"], "id": p["id"]}
                        for p in parsed
                    ],
                )
                messages[-1] = response  # 替换掉原来的无 tool_calls 响应
                logger.info(
                    f"[ReActRepoLoader] 迭代 {iteration + 1}: "
                    f"从文本中解析到 {len(tool_calls)} 个工具调用"
                )

        if not tool_calls:
            # LLM 没有调用工具，可能是结束信号
            content = response.content or ""
            is_sufficient = "is_sufficient: true" in content.lower()
            summary = ""
            if is_sufficient:
                # 提取 summary
                m = content.lower().split("summary:")
                if len(m) > 1:
                    summary = m[1].split("is_sufficient")[0].strip()
                else:
                    summary = content
            return {
                "is_sufficient": is_sufficient,
                "summary": summary,
                "messages": messages[start_idx:],
            }

        # 执行工具调用
        for tc in tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]

            t0 = time.time()
            try:
                raw_result = await self._execute_tool(
                    owner, repo, sha, result, tool_name, tool_args
                )
                elapsed = (time.time() - t0) * 1000

                call = ToolCall(
                    iteration=iteration,
                    thought=response.content or "",
                    tool_name=tool_name,
                    tool_args=tool_args,
                    observation=raw_result[:_TOOL_RESULT_TRUNCATE],
                    elapsed_ms=round(elapsed, 1),
                )
                result.tool_calls.append(call)

                # 使用 ToolMessage 添加观察结果（Function Calling 规范要求）
                # 安全提取 tool_call_id：response.tool_calls 是 LangChain 标准化后的，
                # 每个条目有 id/name/args，优先级最高；其余兜底
                tc_id = None
                if response.tool_calls:
                    for _tc in response.tool_calls:
                        if _tc.get("name") == tool_name:
                            tc_id = _tc.get("id")
                            break
                tc_id = tc_id or tc.get("id") or f"call_{iteration}_{tool_name}"
                messages.append(
                    ToolMessage(
                        content=raw_result[:_TOOL_RESULT_TRUNCATE],
                        tool_call_id=tc_id,
                    )
                )
                logger.debug(
                    f"[ReActRepoLoader] 迭代 {iteration + 1}: "
                    f"{tool_name} -> {len(raw_result)} chars, {elapsed:.0f}ms, tc_id={tc_id}"
                )

            except Exception as e:
                elapsed = time.time() - t0
                error_msg = f"[工具执行错误] {type(e).__name__}: {str(e)}"
                result.errors.append(error_msg)
                # 工具执行失败时追加 ToolMessage（带 tool_call_id）
                tc_id = None
                if response.tool_calls:
                    for _tc in response.tool_calls:
                        if _tc.get("name") == tool_name:
                            tc_id = _tc.get("id")
                            break
                tc_id = tc_id or tc.get("id") or f"call_{iteration}_{tool_name}"
                messages.append(
                    ToolMessage(
                        content=error_msg,
                        tool_call_id=tc_id,
                    )
                )
                logger.warning(f"[ReActRepoLoader] 工具执行失败: {e}")
                result.tool_calls.append(ToolCall(
                    iteration=iteration,
                    thought=response.content or "",
                    tool_name=tool_name,
                    tool_args=tool_args,
                    error=str(e),
                    elapsed_ms=round(elapsed * 1000, 1),
                ))
                # 回滚本步新追加的 Human + AI + Tool 消息，防止破坏消息链
                messages[:] = messages[:start_idx]

        return {"is_sufficient": False, "summary": "", "messages": messages[start_idx:]}

    async def _execute_tool(
        self,
        owner: str, repo: str, sha: str,
        result: ExplorationResult,
        tool_name: str,
        args: dict,
    ) -> str:
        """执行单个工具，注入 owner/repo 参数。"""
        import time

        # 注入通用参数
        if tool_name in ("get_repo_info",):
            args = {"owner": owner, "repo": repo}
        elif tool_name in ("get_file_tree",):
            args = {"owner": owner, "repo": repo, "ref": sha or result.branch}
        elif tool_name in ("get_commit_history", "get_pull_requests"):
            args.setdefault("owner", owner)
            args.setdefault("repo", repo)
        elif tool_name == "get_file_blobs":
            args = {
                "owner": owner, "repo": repo,
                "paths": args.get("paths", []),
                "ref": sha or result.branch,
            }
        elif tool_name == "read_file_content":
            args = {
                "owner": owner, "repo": repo,
                "path": args.get("path", ""),
                "ref": sha or result.branch,
            }
        elif tool_name == "search_code":
            args = {
                "owner": owner, "repo": repo,
                "query": args.get("query", ""),
                "language": args.get("language", ""),
            }
        elif tool_name == "get_default_branch":
            args = {"owner": owner, "repo": repo}

        # 同步执行（LangChain tool.invoke 是同步的）
        t0 = time.time()

        def sync_call():
            return REACT_TOOLS[_get_tool_index(tool_name)].invoke(args)

        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, sync_call)
        elapsed = (time.time() - t0) * 1000

        # 解析并更新加载的文件
        if tool_name == "get_file_blobs":
            try:
                blobs = json.loads(raw)
                for path, content in blobs.items():
                    if path not in result.loaded_files:
                        result.loaded_files[path] = content
                        result.loaded_paths.append(path)
                return f"成功加载 {len(blobs)} 个文件: {list(blobs.keys())[:10]}"
            except (json.JSONDecodeError, TypeError):
                return f"工具返回: {str(raw)[:500]}"
        elif tool_name == "read_file_content":
            path = args.get("path", "")
            if path and path not in result.loaded_files:
                result.loaded_files[path] = raw
                result.loaded_paths.append(path)
            return f"文件 {path} ({len(raw)} 字符)"

        return str(raw)[:_TOOL_RESULT_TRUNCATE]

    def _build_iteration_context(
        self, owner: str, repo: str, sha: str,
        result: ExplorationResult, iteration: int
    ) -> str:
        """构建每轮迭代的上下文，包含完整文件树和已加载状态。"""
        parts = [f"\n## 迭代 {iteration + 1}\n"]
        parts.append(f"- 已加载文件数: {len(result.loaded_paths)} / {self.MAX_FILES}")
        parts.append(f"- 迭代轮次: {iteration + 1} / {self.MAX_ITERATIONS}")

        # 完整文件树：已加载的打勾，未加载的正常列出
        if result.all_tree_paths:
            loaded_set = set(result.loaded_paths)
            parts.append(f"\n### 仓库文件清单（共 {len(result.all_tree_paths)} 个）:\n")
            for path in result.all_tree_paths:
                marker = "✅" if path in loaded_set else "⬜"
                parts.append(f"- {marker} {path}")

        # 错误反馈
        if result.errors:
            parts.append(f"\n### 最近的错误（请注意避开这些无效路径）:\n")
            for e in result.errors[-3:]:
                parts.append(f"- {e}")

        parts.append(f"\n请决定下一步行动（调用工具）：")
        return "\n".join(parts)

    def _compress_history(self, messages: list) -> None:
        """压缩消息历史，保留 SystemMessage 和最近的完整对话轮。

        压缩策略：保留 SystemMessage + 摘要 + 最近 2 轮完整对话，
        防止消息无限增长导致 token 爆炸。
        关键：必须保留完整三元组（Human + AI(tool_calls) + ToolMessage），
        避免 dangling ToolMessage 导致下一轮 LLM 调用报 400 错误。
        """
        system = messages[0]
        # messages 结构：[SystemMsg(0), HumanMsg(1), AIMsg(2), ToolMsg(3), HumanMsg(4), AIMsg(5), ToolMsg(6), ...]
        history = messages[1:]  # 跳过 SystemMsg

        # 保留最后 6 条消息（2 轮完整对话），避免 dangling ToolMessage
        # 当 history=8 时：history[:-3]=[H1,A1,T1,H2,A2], history[-3:]=[T2,H3,A3] - T2 是 dangling
        # 改为 history[-6:] = [H2,A2,T2,H3,A3,T3] - 2 轮完整对话
        keep_count = 6
        if len(history) <= keep_count:
            return

        # 提取摘要信息：统计历史中的工具调用
        summary_lines = ["## 前期探索摘要"]
        seen = set()
        for msg in history[:-keep_count]:  # 跳过最后 6 条
            if isinstance(msg, HumanMessage):
                text = msg.content or ""
                for line in text.split("\n"):
                    stripped = line.strip()
                    if stripped.startswith("## ") or stripped.startswith("### "):
                        key = stripped[:60]
                        if key not in seen:
                            seen.add(key)
                            summary_lines.append(f"  {stripped}")
                    elif stripped.startswith("已加载"):
                        if stripped not in seen:
                            seen.add(stripped)
                            summary_lines.append(f"  {stripped}")

        summary_msg = HumanMessage(content="\n".join(summary_lines))
        # 保留 SystemMsg + 摘要 + 最后 6 条（2 轮完整的 Human + AI(tool_calls) + Tool 三元组）
        messages[:] = [system, summary_msg] + history[-keep_count:]

    @staticmethod
    def _parse_actions_from_text(content: str) -> list[dict]:
        """从 LLM 返回的文本内容中解析 Action JSON（兼容不返回 tool_calls 的模型）。

        适配通义千问等模型在 bind_tools 时仍输出纯文本而非 structured tool_calls 的情况。
        """
        import json
        import re

        _KNOWN_TOOLS = {
            "get_repo_info", "get_file_tree", "read_file_content",
            "get_file_blobs", "search_code", "get_commit_history",
            "get_pull_requests", "get_default_branch",
            "parse_file_ast", "summarize_code_file",
        }

        results: list[dict] = []

        # 从 "Action: {" 开始，用平衡括号解析整个 JSON 块
        for block_match in re.finditer(r'Action:\s*\{', content):
            brace_start = block_match.end()  # 位置在第一个 { 之后
            count = 1
            found_end = -1
            for i, c in enumerate(content[brace_start:]):
                if c == '{':
                    count += 1
                elif c == '}':
                    count -= 1
                    if count == 0:
                        found_end = i
                        break
            if found_end < 0:
                continue
            # 提取 Action 块内容（不含首尾 { }），再包上 { } 形成完整 JSON
            # found_end 是相对于 brace_start 的偏移量，本身已指向末尾 }
            inner = '{' + content[brace_start:brace_start + found_end] + '}'
            # 还原转义换行符（LLM 输出中 \n 可能被转义）
            inner_fixed = inner.replace("\\n", "\n").replace('\\"', '"')
            try:
                obj = json.loads(inner_fixed)
                name = obj.get("name", "")
                args = obj.get("args", {})
                if name in _KNOWN_TOOLS and isinstance(args, dict):
                    results.append({
                        "name": name,
                        "args": args,
                        "id": f"call_parsed_{len(results)}",
                    })
            except (json.JSONDecodeError, TypeError):
                pass

        return results

    def _build_summary(self, result: ExplorationResult) -> str:
        """从探索过程构建总结。"""
        loaded = result.loaded_paths
        if not loaded:
            return "未能加载任何文件。"

        # 从文件路径推断技术栈
        tech_indicators: dict[str, set] = {
            "语言": set(), "框架": set(), "配置": set(), "目录": set(),
        }
        for p in loaded:
            lower = p.lower()
            # 语言
            if p.endswith(".py"): tech_indicators["语言"].add("Python")
            if p.endswith(".ts") or p.endswith(".tsx"): tech_indicators["语言"].add("TypeScript")
            if p.endswith(".js") or p.endswith(".jsx"): tech_indicators["语言"].add("JavaScript")
            if p.endswith(".go"): tech_indicators["语言"].add("Go")
            if p.endswith(".rs"): tech_indicators["语言"].add("Rust")
            if p.endswith(".java"): tech_indicators["语言"].add("Java")
            if p.endswith(".rb"): tech_indicators["语言"].add("Ruby")
            if p.endswith(".kt"): tech_indicators["语言"].add("Kotlin")
            # 框架
            if "fastapi" in lower or "flask" in lower or "django" in lower: tech_indicators["框架"].add("FastAPI/Flask/Django")
            if "react" in lower: tech_indicators["框架"].add("React")
            if "next" in lower: tech_indicators["框架"].add("Next.js")
            if "vue" in lower: tech_indicators["框架"].add("Vue")
            if "angular" in lower: tech_indicators["框架"].add("Angular")
            if "langchain" in lower or "langgraph" in lower: tech_indicators["框架"].add("LangChain/LangGraph")
            if "express" in lower: tech_indicators["框架"].add("Express")
            # 配置
            if p in ("package.json", "requirements.txt", "go.mod", "Cargo.toml",
                      "Gemfile", "composer.json", "pyproject.toml"):
                tech_indicators["配置"].add(p)
            # 目录
            if "/" in p:
                d = p.split("/")[0]
                if d not in ("src", "lib", "app", "components", "pages", "tests"):
                    tech_indicators["目录"].add(d)

        summary_parts = [
            f"## 探索总结\n",
            f"探索了 {result.total_iterations} 轮，加载了 {len(loaded)} 个文件。\n",
        ]
        if tech_indicators["语言"]:
            summary_parts.append(f"**语言**: {', '.join(sorted(tech_indicators['语言']))}")
        if tech_indicators["框架"]:
            summary_parts.append(f"**框架**: {', '.join(sorted(tech_indicators['框架']))}")
        if tech_indicators["配置"]:
            summary_parts.append(f"**配置文件**: {', '.join(sorted(tech_indicators['配置']))}")
        if tech_indicators["目录"]:
            dirs = sorted(tech_indicators["目录"])[:8]
            summary_parts.append(f"**主要目录**: {', '.join(dirs)}")
        summary_parts.append(f"\n**关键文件**: {', '.join(loaded[:10])}")
        if len(loaded) > 10:
            summary_parts.append(f" ... 等 {len(loaded)} 个文件")

        return "\n".join(summary_parts)

    async def _explore_rule_based(
        self, owner: str, repo: str, branch: str,
        result: ExplorationResult, max_files: int
    ) -> ExplorationResult:
        """规则模式：当 LLM 不可用时的降级策略。"""
        logger.warning("[ReActRepoLoader] LLM 不可用，使用规则模式（启发式加载）")

        try:
            result.sha = await self._get_sha(owner, repo, branch)
            tree_raw = get_file_tree.invoke({"owner": owner, "repo": repo, "ref": result.sha})
            tree = json.loads(tree_raw)
        except Exception as e:
            result.errors.append(f"规则模式初始化失败: {e}")
            return result

        blobs = [t for t in tree if t.get("type") == "blob"]

        # 启发式优先级
        priority_patterns = [
            # P0: 入口 + 配置
            lambda p: p in ("package.json", "requirements.txt", "go.mod", "Cargo.toml",
                             "pyproject.toml", "Pipfile", "Gemfile", "composer.json",
                             "Makefile", "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
                             "tsconfig.json", "jsconfig.json", "vite.config.ts", "vite.config.js",
                             "next.config.ts", "next.config.js", "tailwind.config.ts",
                             "README.md", "README.rst"),
            # P1: 源码入口
            lambda p: any(p.startswith(x) for x in (
                "src/", "lib/", "app/", "cmd/", "internal/", "pkg/", "core/",
            )) and not any(x in p for x in ("test", "spec", "__pycache__", "node_modules")),
            # P2: 其他源码
            lambda p: not any(x in p for x in ("test", "spec", "__pycache__", "node_modules", ".git"))
                     and p.rsplit(".", 1)[-1] in ("py", "ts", "tsx", "js", "jsx", "go", "rs", "java"),
        ]

        selected: list[dict] = []
        for pattern in priority_patterns:
            for blob in blobs:
                path = blob["path"]
                if pattern(path) and path not in [b["path"] for b in selected]:
                    selected.append(blob)
                    if len(selected) >= max_files:
                        break
            if len(selected) >= max_files:
                break

        # 批量加载
        paths = [b["path"] for b in selected]
        try:
            blobs_raw = get_file_blobs.invoke({
                "owner": owner, "repo": repo,
                "paths": paths, "ref": result.sha or branch,
            })
            blobs_dict = json.loads(blobs_raw)
            result.loaded_files = blobs_dict
            result.loaded_paths = list(blobs_dict.keys())
        except Exception as e:
            result.errors.append(f"批量加载失败: {e}")

        result.is_sufficient = True
        result.summary = self._build_summary(result)
        result.total_iterations = 1

        return result


def _get_tool_index(tool_name: str) -> int:
    """根据工具名获取在 REACT_TOOLS 列表中的索引。"""
    for i, t in enumerate(REACT_TOOLS):
        if t.name == tool_name:
            return i
    raise ValueError(f"未知工具: {tool_name}")
