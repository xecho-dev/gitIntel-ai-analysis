"""
ReActRepoLoaderAgent — 基于 ReAct 模式的智能仓库加载 Agent。

与旧版 RepoLoaderAgent 的核心区别：
  - 不再是预设的 P0/P1/P2 流程，而是 Agent 自主决策
  - 每次迭代，Agent 决定调用什么工具、加载什么文件
  - 工具调用记录作为推理过程，可解释性强
  - 支持 LangChain Function Calling，Agent 动态选择工具

基于 LangChain create_agent 基础设施：
  - create_agent: 标准化的 ReAct Agent 框架（底层 StateGraph）
  - astream_events: 完整的事件流（LLM 推理、工具调用）
  - Agent callbacks: 自动收集工具调用记录
  - with_structured_output: 强制 LLM 每轮返回结构化输出

工具集：
  GitHub:  get_repo_info, get_file_tree, read_file_content, get_file_blobs,
           batch_search_code, get_commit_history, get_pull_requests
  Code:    parse_file_ast, summarize_code_file

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
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Optional

from langchain.agents import create_agent, AgentState
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agents.react.error_loop_detector import ErrorLoopDetector
from agents.react.tool_wrapper import inject_context, ToolLoopInterrupt
from utils.tree_filter import filter_file_tree
from utils.code_parser import FileSummary, summarize_files
from tools.github_tools import (
    get_repo_info, get_file_tree, read_file_content,
    get_file_blobs, batch_search_code, get_commit_history,
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


# ─── Token 预算配置 ────────────────────────────────────────────────────────────

_MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "2048"))
_REPO_LOADER_MAX_ITERATIONS = int(os.getenv("REPO_LOADER_MAX_ITERATIONS", "5"))
_TOOL_RESULT_TRUNCATE = int(os.getenv("TOOL_RESULT_TRUNCATE", "1500"))


# ─── 工具列表 ────────────────────────────────────────────────────────────────

REACT_TOOLS = [
    get_repo_info,
    get_file_tree,
    read_file_content,
    get_file_blobs,
    batch_search_code,
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
  - get_repo_info(owner: str, repo: str): 仓库基本信息（通常只需调用一次）
  - get_file_tree(owner: str, repo: str, ref: str): 完整文件树（**已包含在初始上下文中**，通常无需重复调用）
  - get_file_blobs(owner: str, repo: str, paths: list[str], ref: str): **批量读取多个文件（优先使用）**，paths 必须是字符串列表，如 ["main.py", "package.json"]
  - read_file_content(owner: str, repo: str, path: str, ref: str): 读取单个文件，path 是字符串
  - batch_search_code(owner: str, repo: str, queries: list[dict]): 批量搜索代码，queries 是查询列表，每个元素包含 query 和可选的 language
  - get_commit_history(owner: str, repo: str, ref: str, limit: int): 提交历史，limit 是整数
  - parse_file_ast(file_path: str, content: str, language: str): AST 结构
  - summarize_code_file(content: str, max_lines: int): 文件摘要

**【重要】参数类型约束**：
  - paths 必须是 **list[str]**（如 `["a.py", "b.py"]`），禁止传字符串、数字或其他类型
  - path/query/language 必须是 **str**，禁止传数字或列表
  - limit/max_lines 必须是 **int**（如 `10`），禁止传字符串
  - 所有参数都不能为空

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
- thought: 当前推理思考（string）
- action: 工具调用（格式: {"name": "工具名", "args": {...}}），如已收集足够信息则填 null
- is_sufficient: 是否已收集足够信息（boolean）
- summary: 探索总结（**必须是纯文本 string**，如 "技术栈: Vue.js + Vuex，入口文件: main.js，主要模块: api/、components/、views/"）"""


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
    loaded_files: dict[str, str] = field(default_factory=dict)  # 原始文件内容（可选保留）
    loaded_paths: list[str] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    is_sufficient: bool = False
    summary: str = ""
    total_iterations: int = 0
    errors: list[str] = field(default_factory=list)
    all_tree_paths: list[str] = field(default_factory=list)
    # 新增：提炼后的文件摘要（供 Explorer 使用，大幅减少 token）
    file_summaries: dict[str, FileSummary] = field(default_factory=dict)
    # GitHub API 返回的代码语言（前3），直接透传到前端展示
    languages: list[str] = field(default_factory=list)


# ─── LangChain Callback Handler ───────────────────────────────────────────────

class RepoLoaderCallbackHandler(ErrorLoopDetector, AsyncCallbackHandler):
    """通过 LangChain Agent callbacks 自动收集工具调用记录。

    虽然 repo_loader 主要使用 with_structured_output 模式，
    但底层工具执行仍通过 LangChain ToolNode，
    此回调可用于收集额外的调用元数据。

    继承 ErrorLoopDetector，防止 LLM 在错误上反复重试导致死循环。
    """

    def __init__(self):
        super().__init__()
        AsyncCallbackHandler.__init__(self)
        self.tool_calls: list[dict] = []

    async def on_tool_start(
        self, serialized: dict, inputs: dict, *, run_id: str, parent_run_id: str | None = None, **kwargs
    ):
        name = serialized.get("name", "unknown")
        self.tool_calls.append({
            "event": "start",
            "tool": name,
            "inputs": inputs,
        })

    async def on_tool_end(
        self, output: str, *, run_id: str, parent_run_id: str | None = None, **kwargs
    ):
        if self.tool_calls and self.tool_calls[-1]["event"] == "start":
            output_str = str(output)[:500]
            self.tool_calls[-1]["event"] = "end"
            self.tool_calls[-1]["output"] = output_str
            self._check_error_pattern(output_str)

    async def on_tool_error(
        self, error: Exception | str, *, run_id: str, parent_run_id: str | None = None, **kwargs
    ):
        if self.tool_calls and self.tool_calls[-1]["event"] == "start":
            error_str = str(error)[:200]
            self.tool_calls[-1]["event"] = "error"
            self.tool_calls[-1]["error"] = error_str
            self._check_error_pattern(error_str)


# ─── 核心 Agent ───────────────────────────────────────────────────────────────

class ReActRepoLoaderAgent:
    """基于 ReAct 模式的仓库加载 Agent。

    特性：
      - 动态工具选择：Agent 根据当前状态自主决定调用哪个工具
      - 结构化输出：通过 with_structured_output 强制 LLM 每轮返回标准化 JSON
      - 可解释推理：每轮的 Thought/Action/Observation 都记录在案
      - 渐进式探索：从浅到深，逐步了解仓库
      - LangChain 集成：使用 create_agent 基础设施 + astream_events
      - 流式输出：支持实时 yield 中间推理步骤

    使用示例：
        agent = ReActRepoLoaderAgent()
        result = await agent.explore("owner", "repo", "main")
        print(result.loaded_files)   # 加载的文件内容
        print(result.summary)         # 探索总结
        print(result.tool_calls)      # 推理过程
    """

    MAX_ITERATIONS = _REPO_LOADER_MAX_ITERATIONS
    MAX_FILES = 50
    MAX_TOKENS_PER_STEP = 2000

    def __init__(self):
        self._llm = self._get_llm()
        self._file_contents: dict[str, str] | None = None
        self._file_tree: list[dict] | None = None
        self._wrapped_tools: list | None = None

    @staticmethod
    def _get_llm() -> BaseChatModel | None:
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
        result = ExplorationResult(owner=owner, repo=repo, branch=branch)
        max_iter = max_iterations or self.MAX_ITERATIONS
        max_f = max_files or self.MAX_FILES

        if self._llm is None:
            raise RuntimeError("[ReActRepoLoader] LLM 不可用，无法执行探索")

        try:
            result.sha = await self._get_sha(owner, repo, branch)
        except Exception as e:
            logger.warning(f"[ReActRepoLoader] 获取 SHA 失败: {e}，使用 branch 名")
            result.sha = branch

        # 预加载文件树到缓存
        info, tree = await asyncio.gather(
            _get_repo_info_impl(owner, repo),
            _get_file_tree_impl(owner, repo, result.sha or branch),
        )
        result.all_tree_paths = [t["path"] for t in tree if t.get("type") == "blob"]
        result.languages = list((info.get("languages") or {}).keys())[:3]
        self._file_tree = tree
        self._file_contents = {}

        # 包装工具时传递 languages，用于过滤 get_file_tree 返回的文件树
        wrapped_tools = self._get_wrapped_tools(owner, repo, result.sha or branch, languages=result.languages)
        self._wrapped_tools = wrapped_tools

        # 构建初始上下文（使用过滤后的文件树）
        initial_context = self._build_initial_context(owner, repo, branch, result.sha, info, tree)
        system_message = SystemMessage(content=REACT_SYSTEM_PROMPT)

        # 构建 create_agent（用于 astream_events 基础设施）
        # 注意：我们主要用 with_structured_output 模式，
        # 但仍创建 create_agent 实例以支持 astream_events
        try:
            agent = create_agent(
                model=self._llm,
                tools=wrapped_tools,
                system_prompt=REACT_SYSTEM_PROMPT,
            )
            has_create_agent = True
        except Exception as e:
            logger.warning(f"[ReActRepoLoader] create_agent 初始化失败: {e}，使用兼容模式")
            has_create_agent = False
            agent = None

        callback_handler = RepoLoaderCallbackHandler()
        llm_with_output = self._llm.with_structured_output(ExplorationOutput)

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
                    llm_with_output, agent if has_create_agent else None,
                    callback_handler,
                )
                conversation_messages.extend(step_result.get("conversation_additions", []))

                if step_result["is_sufficient"]:
                    result.is_sufficient = True
                    result.summary = step_result.get("summary", "")
                    logger.info(f"[ReActRepoLoader] Agent 认为信息足够，停止探索")
                    break

                if step_result.get("had_tool_error"):
                    if step_result.get("consecutive_errors", 0) >= 3:
                        logger.warning("[ReActRepoLoader] 连续 3 次迭代无进展，停止探索")
                        break

                # 检查是否因错误循环而提前停止
                if callback_handler._stop_due_to_loop:
                    logger.warning(
                        f"[ReActRepoLoader] 因错误循环提前终止，"
                        f"已完成 {len(result.loaded_paths)} 个文件"
                    )
                    break

            except Exception as e:
                logger.error(f"[ReActRepoLoader] 迭代 {iteration + 1} 异常: {e}")
                result.errors.append(f"迭代 {iteration + 1}: {str(e)}")
                if len(result.errors) >= 3:
                    logger.warning("[ReActRepoLoader] 错误过多，停止探索")
                    break

        if not result.summary:
            result.summary = "已加载文件但未生成总结"
            result.is_sufficient = False

        # ── 文件内容提炼 ─────────────────────────────────────────────────────
        # 将原始文件内容提炼为结构化摘要，大幅减少 Explorer 的 token 消耗
        if result.loaded_files:
            result.file_summaries = summarize_files(result.loaded_files)
            logger.info(
                f"[ReActRepoLoader] 文件提炼完成: {len(result.loaded_files)} 个文件 "
                f"→ {len(result.file_summaries)} 个摘要"
            )
            # 原始文件内容可以清空以节省内存（如果不再需要）
            # 如果后续节点需要原始内容，可以注释掉下面这行
            # result.loaded_files = {}

        logger.info(
            f"[ReActRepoLoader] 探索完成: "
            f"{result.total_iterations} 轮, "
            f"{len(result.loaded_paths)} 个文件, "
            f"sufficient={result.is_sufficient}"
        )
        return result

    async def _get_sha(self, owner: str, repo: str, branch: str) -> str:
        """获取分支的 SHA。"""
        result = await _get_branch_sha_impl(owner, repo, branch)
        return result.strip()

    def _build_initial_context(
        self, owner: str, repo: str, branch: str, sha: str,
        info: dict, tree: list[dict],
    ) -> str:
        """构建精简后的初始上下文，过滤低价值文件。"""
        languages = info.get("languages", {}) or {}
        top_languages = list(languages.keys())[:3]
        context_parts = [f"# 仓库探索任务\n目标仓库: {owner}/{repo}@{branch}\n"]

        context_parts.append(f"## 仓库基本信息\n")
        context_parts.append(f"- 默认分支: {info.get('default_branch', branch)}")
        context_parts.append(f"- 主要语言（前3）: {', '.join(top_languages) or '未知'}")
        context_parts.append(f"- Stars: {info.get('stars', 0)}")
        context_parts.append(f"- Topics: {', '.join(info.get('topics', [])[:10]) or '无'}")
        if info.get("description"):
            context_parts.append(f"- 描述: {info.get('description')}")

        filtered_blobs = filter_file_tree(tree, top_languages)
        dirs = set()
        for t in filtered_blobs:
            path = t.get("path", "")
            if "/" in path:
                dirs.add(path.split("/")[0])

        context_parts.append(f"\n## 文件树概览（已过滤）\n")
        context_parts.append(f"- 原始文件数: {len([t for t in tree if t.get('type') == 'blob'])}")
        context_parts.append(f"- 过滤后文件数: {len(filtered_blobs)}")
        context_parts.append(f"- 顶层目录: {', '.join(sorted(dirs)[:20])}")

        context_parts.append(f"\n### 文件路径清单（已过滤）:\n")
        for t in filtered_blobs[:200]:
            context_parts.append(f"- {t['path']}")
        if len(filtered_blobs) > 200:
            context_parts.append(f"- ... 等共 {len(filtered_blobs)} 个文件")

        context_parts.append(
            f"\n## 任务\n"
            f"请从上方文件路径清单中选取关键文件进行加载，理解其技术栈和架构。\n"
            f"**重要**：只能加载文件路径清单中列出的文件，禁止猜测不在清单中的文件路径！\n"
            f"当已了解足够信息时，输出 is_sufficient=true 和总结。"
        )

        return "\n".join(context_parts)

    # ─── LLM 调用（带重试和兜底解析）──────────────────────────────────────────────

    async def _call_llm(
        self,
        messages: list,
        llm_with_output,
        callback_handler,
    ) -> ExplorationOutput | None:
        """调用 LLM 并解析 ExplorationOutput。

        策略：
          1. 优先使用 with_structured_output（精确解析）
          2. 解析失败时，降级为手动 JSON 解析
          3. 仍失败时返回 None（上层会生成兜底响应）
        """
        try:
            ai_msg: Any = await llm_with_output.ainvoke(
                messages,
                config={"callbacks": [callback_handler]},
            )
            return getattr(ai_msg, "parsed", ai_msg)
        except ToolLoopInterrupt:
            # 工具层检测到错误循环，直接打断 agent
            raise
        except Exception as first_err:
            # 降级：尝试从原始 content 中手动提取 JSON
            raw_content: str = ""
            try:
                if hasattr(ai_msg, "content"):
                    raw_content = ai_msg.content or ""
            except Exception:
                pass

            if raw_content:
                raw_content = raw_content.strip()
                for _leader in ("```json", "```JSON", "```"):
                    if raw_content.startswith(_leader):
                        raw_content = raw_content[len(_leader):]
                for _trailer in ("```",):
                    if raw_content.endswith(_trailer):
                        raw_content = raw_content[: -len(_trailer)]
                raw_content = raw_content.strip()

                if raw_content.startswith("{") and '"' in raw_content:
                    try:
                        parsed = json.loads(raw_content)
                    except json.JSONDecodeError:
                        pass
                    else:
                        # 确保必需字段存在，否则拒绝降级
                        if "is_sufficient" not in parsed or "summary" not in parsed:
                            logger.warning(
                                f"[ReActRepoLoader] 降级 JSON 解析成功但缺少必需字段 "
                                f"is_sufficient/summary，原始内容: {raw_content[:200]}"
                            )
                            return None

                        # 确保 summary 是 string 类型
                        raw_summary = parsed.get("summary", "")
                        if isinstance(raw_summary, dict):
                            summary_str = json.dumps(raw_summary, ensure_ascii=False, indent=2)
                        elif isinstance(raw_summary, str):
                            summary_str = raw_summary
                        else:
                            summary_str = str(raw_summary)

                        return ExplorationOutput(
                            thought=parsed.get("thought", "解析降级"),
                            action=(
                                ToolAction(
                                    name=parsed["action"]["name"],
                                    args=parsed["action"].get("args", {}),
                                )
                                if parsed.get("action") else None
                            ),
                            is_sufficient=parsed["is_sufficient"],
                            summary=summary_str,
                        )
            logger.warning(f"[ReActRepoLoader] LLM 输出解析失败: {first_err}")
            return None

    # ─── 单步执行 ─────────────────────────────────────────────────────────────

    async def _run_single_step(
        self,
        owner: str, repo: str, branch: str, sha: str,
        result: ExplorationResult,
        system_message: SystemMessage,
        conversation_messages: list,
        iteration: int,
        llm_with_output,
        agent,
        callback_handler: RepoLoaderCallbackHandler,
    ) -> dict:
        """执行单步 ReAct 循环，使用结构化输出 + create_agent 基础设施。"""
        step_messages: list = [system_message] + list(conversation_messages)

        context = self._build_iteration_context(owner, repo, sha, result, iteration)
        step_messages.append(HumanMessage(content=context))

        structured_output = await self._call_llm(
            step_messages, llm_with_output, callback_handler
        )

        # 兜底：LLM 解析完全失败时，强制停止迭代（避免无限循环）
        if structured_output is None:
            logger.warning(f"[ReActRepoLoader] 迭代 {iteration + 1} LLM 解析失败，强制停止")
            result.is_sufficient = True
            result.summary = (
                "LLM 输出异常，分析被迫终止。请检查 LLM 输出质量。"
            )
            return {
                "is_sufficient": True,
                "summary": result.summary,
                "conversation_additions": [],
                "had_tool_error": False,
            }

        result.tool_calls.append(ToolCall(
            iteration=iteration,
            thought=structured_output.thought,
            tool_name="(reasoning)",
            tool_args={},
            observation=structured_output.summary,
        ))

        if structured_output.is_sufficient or structured_output.action is None:
            return {
                "is_sufficient": True,
                "summary": structured_output.summary,
                "conversation_additions": [],
                "had_tool_error": False,
            }

        had_tool_error = False
        consecutive_errors = 0
        tool_name = structured_output.action.name
        tool_args = structured_output.action.args

        t0 = time.time()
        try:
            raw_result = await self._execute_tool(owner, repo, sha, result, tool_name, tool_args)
            elapsed = (time.time() - t0) * 1000
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            raw_result = f"[工具执行错误] {type(e).__name__}: {str(e)}"
            result.errors.append(raw_result)
            logger.warning(f"[ReActRepoLoader] 工具执行失败: {e}")
            had_tool_error = True
            consecutive_errors = step_messages.count("error") + 1

        tool_observation = raw_result[:_TOOL_RESULT_TRUNCATE]
        result.tool_calls.append(ToolCall(
            iteration=iteration,
            thought=structured_output.thought,
            tool_name=tool_name,
            tool_args=tool_args,
            observation=tool_observation,
            elapsed_ms=round(elapsed, 1),
        ))

        return {
            "is_sufficient": False,
            "summary": structured_output.summary,
            "conversation_additions": [HumanMessage(content=context)],
            "had_tool_error": had_tool_error,
            "consecutive_errors": consecutive_errors,
        }

    async def _execute_tool(
        self,
        owner: str, repo: str, sha: str,
        result: ExplorationResult,
        tool_name: str,
        args: dict,
    ) -> str:
        """执行单个工具，使用 wrapped_tools（含上下文注入和参数标准化）。"""
        # 缓存拦截（只拦截 read_file_content，get_file_tree 必须走 inject_context 才能过滤）
        if tool_name == "read_file_content" and self._file_contents is not None:
            path = args.get("path", "")
            if path in self._file_contents:
                return self._file_contents[path]

        # 从 wrapped_tools 中查找目标工具（inject_context 已注入过滤逻辑）
        wrapped_tool = next(
            (t for t in self._wrapped_tools if t.name == tool_name), None
        )
        if wrapped_tool is None:
            return f"[未知工具] {tool_name}"

        # wrapped_invoke 内部会完成：paths 字符串→列表、owner/repo/ref 注入
        def sync_call():
            return wrapped_tool.invoke(args)

        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, sync_call)

        if tool_name == "get_file_blobs":
            try:
                blobs = json.loads(raw)
                for path, content in blobs.items():
                    if path not in result.loaded_files:
                        result.loaded_files[path] = content
                        result.loaded_paths.append(path)
                        if self._file_contents is not None:
                            self._file_contents[path] = content
                return f"成功加载 {len(blobs)} 个文件: {list(blobs.keys())[:10]}"
            except (json.JSONDecodeError, TypeError):
                return f"工具返回: {str(raw)[:500]}"
        elif tool_name == "read_file_content":
            path = args.get("path", "")
            if path and path not in result.loaded_files:
                result.loaded_files[path] = raw
                result.loaded_paths.append(path)
                if self._file_contents is not None:
                    self._file_contents[path] = raw
            return f"文件 {path} ({len(raw)} 字符)"

        return str(raw)[:_TOOL_RESULT_TRUNCATE]

    def _get_wrapped_tools(
        self, owner: str, repo: str, ref: str, languages: list[str] | None = None
    ) -> list:
        """包装所有工具：注入 owner/repo/branch + 修正参数类型错误。

        底层调用 inject_context，实现统一的参数注入和类型修正逻辑。
        languages 参数用于过滤 get_file_tree 返回的文件树。
        """
        from tools.github_tools import (
            get_repo_info, get_file_tree, read_file_content,
            get_file_blobs, batch_search_code, get_commit_history,
            get_pull_requests, get_default_branch,
        )
        from tools.code_tools import parse_file_ast, summarize_code_file

        _TOOLS = [
            get_repo_info,
            get_file_tree,
            read_file_content,
            get_file_blobs,
            batch_search_code,
            get_commit_history,
            get_pull_requests,
            get_default_branch,
            parse_file_ast,
            summarize_code_file,
        ]
        return [inject_context(t, owner=owner, repo=repo, ref=ref, languages=languages) for t in _TOOLS]

    def _build_iteration_context(
        self, owner: str, repo: str, sha: str,
        result: ExplorationResult, iteration: int
    ) -> str:
        """构建每轮迭代的上下文。"""
        parts = [f"\n## 迭代 {iteration + 1}\n"]
        parts.append(f"- 已加载文件数: {len(result.loaded_paths)} / {self.MAX_FILES}")
        parts.append(f"- 迭代轮次: {iteration + 1} / {self.MAX_ITERATIONS}")

        if result.loaded_paths:
            parts.append(f"\n### 已加载文件清单（共 {len(result.loaded_paths)} 个）:\n")
            for path in result.loaded_paths:
                parts.append(f"- {path}")

        if result.errors:
            parts.append(f"\n### 最近的错误（请注意避开这些无效路径）:\n")
            for e in result.errors[-3:]:
                parts.append(f"- {e}")

        parts.append(f"\n请决定下一步行动（调用工具）：")
        return "\n".join(parts)
