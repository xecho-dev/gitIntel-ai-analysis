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
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage
from tools.github_tools import (
    get_repo_info, get_file_tree, read_file_content,
    get_file_blobs, search_code, get_commit_history,
    get_pull_requests, get_default_branch,
    _get_repo_info_impl, _get_file_tree_impl, _get_default_branch_impl,
    _get_branch_sha_impl,
)
from tools.code_tools import parse_file_ast, summarize_code_file

logger = logging.getLogger("gitintel")


# ─── 结构化输出模型 ────────────────────────────────────────────────────────────

class ToolAction(BaseModel):
    """工具调用参数"""
    name: str = Field(description="工具名称")
    args: dict = Field(description="工具参数，包含 owner, repo, paths 等")


class ExplorationOutput(BaseModel):
    """强制 LLM 每轮返回的结构化输出"""
    thought: str = Field(description="当前推理思考，说明为什么选择这个行动")
    action: Optional[ToolAction] = Field(
        default=None,
        description="如果要调用工具，填写工具名称和参数；如已收集足够信息则填 null"
    )
    is_sufficient: bool = Field(description="是否已收集足够信息可停止探索")
    summary: str = Field(description="探索总结，必须包含：技术栈、主要模块、关键文件、架构特点")

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

**重要**：你的输出必须严格遵循以下 JSON 格式，包含四个必填字段：
- thought: 当前推理思考
- action: 工具调用（格式: {"name": "工具名", "args": {...}}），如已收集足够信息则填 null
- is_sufficient: 是否已收集足够信息
- summary: 探索总结（必须包含：技术栈、主要模块、关键文件、架构特点）"""


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
            llm = get_llm_with_tracking(agent_name="智能仓库加载", max_tokens=_MAX_OUTPUT_TOKENS)
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
        consecutive_no_progress = 0

        if self.llm is None:
            raise RuntimeError("[ReActRepoLoader] LLM 不可用，无法执行探索")

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
        system_message = SystemMessage(content=REACT_SYSTEM_PROMPT)
        conversation_messages: list = [
            HumanMessage(content=initial_context),
        ]

        for iteration in range(max_iter):
            result.total_iterations = iteration + 1

            if len(result.loaded_paths) >= max_f:
                logger.info(f"[ReActRepoLoader] 已达最大文件数 {max_f}，停止探索")
                break

            try:
                step_result = await self._run_single_step(
                    owner, repo, branch, result.sha, result,
                    system_message, conversation_messages, iteration,
                )
                # 只追加本轮次的 HumanMessage 到对话历史
                conversation_messages.extend(step_result.get("conversation_additions", []))

                if step_result["is_sufficient"]:
                    result.is_sufficient = True
                    result.summary = step_result.get("summary", "")
                    logger.info(f"[ReActRepoLoader] Agent 认为信息足够，停止探索")
                    break

                if step_result.get("had_tool_error"):
                    consecutive_no_progress += 1
                    if consecutive_no_progress >= 3:
                        logger.warning("[ReActRepoLoader] 连续 3 次迭代无进展，停止探索")
                        break
                else:
                    consecutive_no_progress = 0

            except Exception as e:
                logger.error(f"[ReActRepoLoader] 迭代 {iteration + 1} 异常: {e}")
                result.errors.append(f"迭代 {iteration + 1}: {str(e)}")
                if len(result.errors) >= 3:
                    logger.warning("[ReActRepoLoader] 错误过多，停止探索")
                    break

        # 结构化输出确保每轮都有 summary，无需降级策略
        # 如果所有迭代都未返回 is_sufficient=true，使用最后一次迭代的 summary
        if not result.summary:
            result.summary = "已加载文件但未生成总结"
            result.is_sufficient = False

        logger.info(
            f"[ReActRepoLoader] 探索完成: "
            f"{result.total_iterations} 轮, "
            f"{len(result.loaded_paths)} 个文件, "
            f"sufficient={result.is_sufficient}"
        )
        return result

    async def _get_sha(self, owner: str, repo: str, branch: str) -> str:
        """获取分支的 SHA。直接 await 底层 async impl。"""
        result = await _get_branch_sha_impl(owner, repo, branch)
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

        # 文件树 — 只展示顶层目录结构，不展开所有文件路径
        # 完整文件树太大（如 facebook/react 有 7000+ 文件），直接塞入上下文会爆 token
        blobs = [t for t in tree if t.get("type") == "blob"]
        dirs = set()
        for t in blobs:
            path = t.get("path", "")
            if "/" in path:
                dirs.add(path.split("/")[0])

        context_parts.append(f"\n## 文件树概览\n")
        context_parts.append(f"- 总文件数: {len(blobs)}")
        context_parts.append(f"- 顶层目录: {', '.join(sorted(dirs)[:20])}")

        # 按目录分组，只展示前 100 条完整路径示例（防止 token 爆炸）
        # 已加载的完整路径在每轮迭代的 _build_iteration_context 中通过 loaded_paths 追踪
        context_parts.append(f"\n### 文件路径示例（前 100 个）:\n")
        for i, t in enumerate(blobs[:100]):
            context_parts.append(f"- {t['path']}")
        if len(blobs) > 100:
            context_parts.append(f"- ... 等共 {len(blobs)} 个文件（完整清单见已加载记录）")

        context_parts.append(
            f"\n## 任务\n"
            f"请从上方文件路径示例中选取关键文件进行加载，理解其技术栈和架构。\n"
            f"**重要**：只能加载文件路径示例中列出的文件，禁止猜测不在清单中的文件路径！\n"
            f"当已了解足够信息时，输出 is_sufficient=true 和总结。"
        )

        return "\n".join(context_parts)

    async def _run_single_step(
        self,
        owner: str, repo: str, branch: str, sha: str,
        result: ExplorationResult,
        system_message: SystemMessage,
        conversation_messages: list,
        iteration: int,
    ) -> dict:
        """执行单步 ReAct 循环，使用结构化输出。

        内部维护独立的本地消息列表 step_messages，与外层 conversation_messages 完全隔离，
        保证 tool_calls/ToolMessage 配对不会被历史压缩逻辑破坏。
        """
        import time

        step_messages: list = [system_message] + list(conversation_messages)

        # 注入上下文信息（作为 HumanMessage）
        context = self._build_iteration_context(owner, repo, sha, result, iteration)
        step_messages.append(HumanMessage(content=context))

        # 使用结构化输出，强制 LLM 返回 ExplorationOutput
        llm_with_output = self.llm.with_structured_output(ExplorationOutput)
        ai_msg: Any = await llm_with_output.ainvoke(step_messages)

        # 记录推理过程
        result.tool_calls.append(ToolCall(
            iteration=iteration,
            thought=ai_msg.thought if hasattr(ai_msg, 'thought') else getattr(ai_msg, 'parsed', ai_msg).thought,
            tool_name="(reasoning)",
            tool_args={},
            observation=ai_msg.summary if hasattr(ai_msg, 'summary') else getattr(ai_msg, 'parsed', ai_msg).summary,
        ))

        # 提取 ExplorationOutput（with_structured_output 可能返回 Pydantic 实例或底座 AIMessage）
        structured_output: ExplorationOutput = getattr(ai_msg, 'parsed', ai_msg)

        # 检查是否结束
        if structured_output.is_sufficient or structured_output.action is None:
            return {
                "is_sufficient": True,
                "summary": structured_output.summary,
                "conversation_additions": [],   # 本步只追加了 HumanMessage，无状态变更
                "had_tool_error": False,
            }

        # ── 工具调用 ──────────────────────────────────────────────────────────
        had_tool_error = False
        tool_name = structured_output.action.name
        tool_args = structured_output.action.args

        t0 = time.time()
        try:
            raw_result = await self._execute_tool(
                owner, repo, sha, result, tool_name, tool_args
            )
            elapsed = (time.time() - t0) * 1000

            logger.debug(
                f"[ReActRepoLoader] 迭代 {iteration + 1}: "
                f"{tool_name} -> {len(raw_result)} chars, {elapsed:.0f}ms"
            )

        except Exception as e:
            elapsed = time.time() - t0
            error_msg = f"[工具执行错误] {type(e).__name__}: {str(e)}"
            result.errors.append(error_msg)
            raw_result = error_msg
            logger.warning(f"[ReActRepoLoader] 工具执行失败: {e}")
            had_tool_error = True

        # 记录工具调用
        tool_observation = raw_result[:_TOOL_RESULT_TRUNCATE]
        result.tool_calls.append(ToolCall(
            iteration=iteration,
            thought=structured_output.thought,
            tool_name=tool_name,
            tool_args=tool_args,
            observation=tool_observation,
            elapsed_ms=round(elapsed * 1000, 1),
        ))

        # 本步的 conversation 增量 = HumanMessage（仅限工具调用轮次）
        return {
            "is_sufficient": False,
            "summary": structured_output.summary,
            "conversation_additions": [HumanMessage(content=context)],
            "had_tool_error": had_tool_error,
        }

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

        # 仅列出已加载的文件，避免 token 浪费
        if result.loaded_paths:
            parts.append(f"\n### 已加载文件清单（共 {len(result.loaded_paths)} 个）:\n")
            for path in result.loaded_paths:
                parts.append(f"- {path}")

        # 错误反馈
        if result.errors:
            parts.append(f"\n### 最近的错误（请注意避开这些无效路径）:\n")
            for e in result.errors[-3:]:
                parts.append(f"- {e}")

        parts.append(f"\n请决定下一步行动（调用工具）：")
        return "\n".join(parts)



def _get_tool_index(tool_name: str) -> int:
    """根据工具名获取在 REACT_TOOLS 列表中的索引。"""
    for i, t in enumerate(REACT_TOOLS):
        if t.name == tool_name:
            return i
    raise ValueError(f"未知工具: {tool_name}")
