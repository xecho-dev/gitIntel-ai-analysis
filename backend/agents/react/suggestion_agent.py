"""
ReActSuggestionAgent — 基于 ReAct 模式的优化建议生成 Agent。

基于 LangChain create_agent 实现，充分利用：
  - create_agent: 标准化的 ReAct Agent（LangGraph StateGraph）
  - ainvoke: 单次执行，避免 astream_events + ainvoke 双重执行问题
  - StructuredTool: 统一的工具接口
  - ToolNode: LangGraph 内置的工具执行节点
  - Agent callbacks: 自动收集工具调用记录

保留独有的：
  - RAG 集成
  - 多源上下文构建
  - 规则引擎兜底
  - 流式输出（SSE）
"""
import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Annotated, Any, AsyncGenerator

from langchain.agents import create_agent, AgentState
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage

from agents.react.error_loop_detector import ErrorLoopDetector
from agents.react.tool_wrapper import inject_context, ToolLoopInterrupt
from tools.github_tools import batch_search_code
from tools.code_tools import parse_file_ast, detect_code_smells, detect_imports
from tools.rag_tools import (
    rag_search_similar, rag_search_by_category, rag_store_suggestion,
    _rag_search_similar_impl, _rag_store_suggestion_impl,
)

logger = logging.getLogger("gitintel")

# ── Token 预算配置 ────────────────────────────────────────────────────────────

_MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "2048"))
_TOOL_RESULT_TRUNCATE = int(os.getenv("TOOL_RESULT_TRUNCATE", "1500"))


# ─── 工具列表 ────────────────────────────────────────────────────────────────

# 原始工具列表（用于类型标注）
# 注意：Suggestion Agent 不使用 read_file_content，避免重新读取大文件消耗 token
# 只允许：批量搜索、AST 分析、代码异味检测、依赖分析、RAG
_RAW_TOOLS = [
    batch_search_code,
    parse_file_ast,
    detect_code_smells,
    detect_imports,
    rag_search_similar,
    rag_search_by_category,
]


def _get_wrapped_tools(owner: str, repo: str, ref: str) -> list:
    """获取包装后的工具列表，自动注入 owner/repo/ref 上下文。"""
    return [inject_context(t, owner=owner, repo=repo, ref=ref) for t in _RAW_TOOLS]


# ─── System Prompt ─────────────────────────────────────────────────────────────

REACT_SUGGESTION_SYSTEM = """你是一名资深软件架构师，基于代码分析结论生成优化建议。

【关键】你【不能】使用 read_file_content 工具读取源代码！
所有分析工作已由其他 Agent 完成，你只需基于已有结论生成建议。

已完成的工作（可信赖的输入）：
  - ArchitectureAgent: 架构扫描完成
  - QualityAgent: 代码质量分析完成（hotspots 已列出问题位置和类型）
  - DependencyAgent: 依赖风险已评估
  - CodeParserAgent: 代码结构已解析（largest_files 列出大文件）

你的任务：
  1. 基于【代码质量问题】列表（已由 QualityAgent 定位），理解每个问题
  2. 使用 batch_search_code 搜索相关修复模式和最佳实践（返回简短片段）
  3. 使用 detect_code_smells 在已有代码文件上做补充分析
  4. 使用 RAG 检索类似项目的历史经验

【禁止】
  - 不要使用任何读取源码的工具（如 read_file_content）
  - 不要试图重新分析代码发现问题（问题已由 QualityAgent 定位）
  - 不要生成泛泛而谈的建议（每条必须有具体的文件位置和问题描述）

输出 JSON 数组（不要markdown包裹）：
[
  {
    "type": "security|performance|refactor|testing|complexity|architecture|general",
    "title": "中文标题，20字以内",
    "description": "详细说明80-200字，基于已有分析结论，重点说明修复方案",
    "priority": "high|medium|low",
    "category": "security|performance|maintainability|testing|architecture",
    "verified": true|false,
    "code_fix": {
      "file": "hotspots 或 largest_files 中已有的文件路径",
      "type": "replace|add|remove",
      "original": "根据问题描述推断的原始代码片段",
      "updated": "建议的修改",
      "reason": "修改原因，20字以内"
    }
  }
]

要求：返回3-6条建议按priority降序；verified=true基于已有分析结论标记；
code_fix.file 必须来自已有的 hotspots 或 largest_files，不要猜测文件路径。"""


# ─── 数据结构 ────────────────────────────────────────────────────────────────

@dataclass
class Suggestion:
    id: int
    type: str
    title: str
    description: str
    priority: str
    category: str
    source: str
    verified: bool
    code_fix: dict


@dataclass
class VerificationResult:
    tool_calls: list[dict] = field(default_factory=list)
    ast_results: dict[str, dict] = field(default_factory=dict)
    smell_results: dict[str, list] = field(default_factory=list)


# ─── LangChain Callback Handler ───────────────────────────────────────────────

class SuggestionCallbackHandler(ErrorLoopDetector, AsyncCallbackHandler):
    """通过 LangChain Agent callbacks 自动收集工具调用记录。

    继承 ErrorLoopDetector，防止 LLM 在错误上反复重试导致死循环。
    """

    def __init__(self):
        super().__init__()
        AsyncCallbackHandler.__init__(self)
        self.tool_calls: list[dict] = []
        self.progress_events: list[dict] = []  # 累积进度事件，稍后 yield
        self._in_tool = False
        self._current_tool_name = ""
        self._current_inputs: dict = {}

    async def on_tool_start(
        self, serialized: dict, input: Any = "", *, run_id: str, parent_run_id: str | None = None, **kwargs
    ):
        name = serialized.get("name", "unknown")
        self._current_tool_name = name
        self._current_inputs = input if isinstance(input, dict) else {}
        self._in_tool = True

    async def on_tool_end(
        self, output: Any, *, run_id: str, parent_run_id: str | None = None, **kwargs
    ):
        if self._in_tool:
            obs = str(output.content)[:_TOOL_RESULT_TRUNCATE] if hasattr(output, "content") else str(output)[:_TOOL_RESULT_TRUNCATE]
            tool_call_count = len(self.tool_calls) + 1
            self.tool_calls.append({
                "iteration": tool_call_count,
                "tool": self._current_tool_name,
                "args": dict(self._current_inputs),
                "result": obs[:500],
            })
            self._check_error_pattern(obs, self._current_tool_name)

            # 累积进度事件
            self.progress_events.append({
                "type": "progress",
                "agent": "optimization",
                "message": f"[验证] {self._current_tool_name}: {obs[:80]}",
                "percent": min(20 + tool_call_count * 12, 65),
                "data": {"tool": self._current_tool_name, "result": obs[:150], "iteration": tool_call_count},
            })

        self._in_tool = False

    async def on_tool_error(
        self, error: Exception | str, *, run_id: str, parent_run_id: str | None = None, **kwargs
    ):
        if self._in_tool:
            error_str = str(error)[:200]
            tool_call_count = len(self.tool_calls) + 1
            self.tool_calls.append({
                "iteration": tool_call_count,
                "tool": self._current_tool_name,
                "args": dict(self._current_inputs),
                "error": error_str,
                "result": "",
            })
            self._check_error_pattern(error_str, self._current_tool_name)

            # 累积错误进度事件
            self.progress_events.append({
                "type": "progress",
                "agent": "optimization",
                "message": f"[错误] {self._current_tool_name}: {error_str}",
                "percent": min(20 + tool_call_count * 12, 65),
                "data": {"tool": self._current_tool_name, "error": error_str, "iteration": tool_call_count},
            })

        self._in_tool = False


# ─── 核心 Agent ──────────────────────────────────────────────────────────────

class ReActSuggestionAgent:
    """基于 ReAct 模式的优化建议生成 Agent。

    特性：
      - LangChain create_agent：标准化的 ReAct StateGraph，自动管理 Agent 循环
      - ainvoke 单次执行：避免 astream_events + ainvoke 双重执行的复杂性
      - 主动验证：每个建议都经过工具验证，确保精确性
      - 精确修复：code_fix 的 original 来自真实文件内容
      - 历史增强：使用 RAG 搜索相似项目的经验
      - 流式输出：支持通过 callback yield SSE 验证进度

    使用示例：
        agent = ReActSuggestionAgent()
        async for event in agent.stream("owner/repo", "main",
                file_contents=files,
                code_parser_result=cp_result,
                tech_stack_result=ts_result,
                quality_result=q_result,
                dependency_result=dep_result):
            print(event)
    """

    MAX_TOOL_CALLS = 4  # 重命名：正确表达限制的是 tool_call 次数，而非 iteration
    MAX_SUGGESTIONS = 6
    _id_counter = 0

    def __init__(self):
        self._llm: BaseChatModel | None = self._get_llm()
        self._file_contents: dict[str, str] | None = None

    @staticmethod
    def _get_llm() -> BaseChatModel | None:
        try:
            from utils.llm_factory import get_llm_with_tracking
            return get_llm_with_tracking(agent_name="优化建议生成", max_tokens=_MAX_OUTPUT_TOKENS)
        except ImportError:
            logger.warning("[ReActSuggestion] 无法导入 llm_factory")
            return None

    @staticmethod
    def _next_id() -> int:
        ReActSuggestionAgent._id_counter += 1
        return ReActSuggestionAgent._id_counter

    async def stream(
        self,
        repo_path: str,
        branch: str = "main",
        file_contents: dict[str, str] | None = None,
        *,
        code_parser_result: dict | None = None,
        tech_stack_result: dict | None = None,
        quality_result: dict | None = None,
        dependency_result: dict | None = None,
    ) -> AsyncGenerator[dict, None]:
        """生成优化建议（使用 ainvoke 单次执行）。"""
        self._file_contents = file_contents
        owner, repo = self._parse_repo(repo_path)
        ref = branch or "main"

        if ref in ("main", ""):
            try:
                from tools.github_tools import _get_default_branch_impl
                actual_branch = await _get_default_branch_impl(owner, repo)
                if actual_branch and actual_branch != ref:
                    logger.info(f"[ReActSuggestion] 分支修正: {ref} -> {actual_branch}")
                    ref = actual_branch
            except Exception as e:
                logger.warning(f"[ReActSuggestion] 获取默认分支失败: {e}")

        # ── Step 1: 构建分析上下文 ─────────────────────────────────────────────
        yield {
            "type": "status",
            "agent": "optimization",
            "message": "正在构建分析上下文...",
            "percent": 5,
            "data": None,
        }

        context = self._build_context(
            repo_path, branch,
            file_contents=file_contents,
            code_parser_result=code_parser_result,
            tech_stack_result=tech_stack_result,
            quality_result=quality_result,
            dependency_result=dependency_result,
        )

        # ── Step 2: RAG 检索历史经验 ──────────────────────────────────────────
        rag_results = []
        rag_available = True

        try:
            def sync_rag_search():
                return _rag_search_similar_impl(
                    query=self._build_rag_query(tech_stack_result, quality_result, code_parser_result),
                    top_k=5,
                )

            rag_raw = await asyncio.get_running_loop().run_in_executor(None, sync_rag_search)
            rag_data = json.loads(rag_raw)
            rag_results = rag_data.get("results", [])
            if rag_results:
                yield {
                    "type": "progress",
                    "agent": "optimization",
                    "message": f"检索到 {len(rag_results)} 条历史经验",
                    "percent": 10,
                    "data": {"rag_count": len(rag_results)},
                }
        except Exception as e:
            logger.warning(f"[ReActSuggestion] RAG 检索失败: {e}")
            rag_available = False

        # ── Step 3: 使用 ainvoke 执行 ReAct 循环（单次执行，无双重调用）────────────
        yield {
            "type": "progress",
            "agent": "optimization",
            "message": "正在生成初始建议并验证...",
            "percent": 15,
            "data": None,
        }

        if self._llm is None:
            async for fallback_event in self._rule_based_fallback(
                owner, repo, ref,
                quality_result, dependency_result, file_contents
            ):
                yield fallback_event
            return

        verification = VerificationResult()
        # 使用包装后的工具，自动注入 owner/repo/ref 上下文
        wrapped_tools = _get_wrapped_tools(owner, repo, ref)
        agent = create_agent(
            model=self._llm,
            tools=wrapped_tools,
            system_prompt=REACT_SUGGESTION_SYSTEM,
        )

        # 回调处理器：自动收集工具调用和进度事件
        handler = SuggestionCallbackHandler()

        input_state: AgentState = {
            "messages": [
                HumanMessage(content=context),
            ],
            "jump_to": None,
            "structured_response": None,
        }

        final_messages = []

        try:
            # ── 关键改动：只使用 ainvoke 单次执行 ─────────────────────────────────
            # 不再使用 astream_events + ainvoke 双重调用
            # 不再手动 break，依赖 create_agent 内置的 max_iterations 控制
            yield {
                "type": "progress",
                "agent": "optimization",
                "message": "Agent 正在执行（单次 ainvoke）...",
                "percent": 20,
                "data": None,
            }

            final_state = await agent.with_config(run_name="优化建议生成").ainvoke(
                input_state,
                config={
                    "callbacks": [handler],
                    "max_iterations": self.MAX_TOOL_CALLS,
                },
            )
            final_messages = final_state.get("messages", [])

            # 从回调中获取所有工具调用记录
            all_tool_calls = handler.tool_calls
            verification.tool_calls = all_tool_calls

            logger.info(
                f"[ReActSuggestion] create_agent 完成: "
                f"{len(all_tool_calls)} 次工具调用"
            )

            # ── 统一 yield 所有进度事件 ─────────────────────────────────────────
            # 注意：这些事件是在 ainvoke 执行期间累积的，
            # 现在一次性 yield 给 SSE（不再是实时流，但避免了双重执行问题）
            for progress_event in handler.progress_events:
                yield progress_event

            # 检查是否因错误循环提前停止
            if handler._stop_due_to_loop:
                logger.warning(
                    f"[ReActSuggestion] 因错误循环提前终止，"
                    f"已完成 {len(all_tool_calls)} 次工具调用"
                )
                yield {
                    "type": "progress",
                    "agent": "optimization",
                    "message": f"因错误循环提前终止，已完成 {len(all_tool_calls)} 次工具调用",
                    "percent": 65,
                    "data": {"stopped_due_to_loop": True, "tool_call_count": len(all_tool_calls)},
                }

        except ToolLoopInterrupt as e:
            logger.warning(
                f"[ReActSuggestion] Agent 循环被打断（{e.tool_name} ×{e.count}），"
                f"已完成 {len(handler.tool_calls)} 次工具调用"
            )
            yield {
                "type": "progress",
                "agent": "optimization",
                "message": f"Agent 循环被打断（{e.tool_name} ×{e.count}），已完成 {len(handler.tool_calls)} 次工具调用",
                "percent": 70,
                "data": {"stopped_due_to_loop": True, "tool_call_count": len(handler.tool_calls)},
            }
            final_messages = []

        except Exception as e:
            logger.error(f"[ReActSuggestion] create_agent 执行失败: {e}", exc_info=True)
            final_messages = []

        # ── Step 4: 生成最终建议 ──────────────────────────────────────────────
        yield {
            "type": "progress",
            "agent": "optimization",
            "message": "正在生成最终建议...",
            "percent": 70,
            "data": None,
        }

        final_prompt = self._build_final_prompt(context, verification, rag_results)
        messages_for_final = list(final_messages)
        messages_for_final.append(HumanMessage(content=final_prompt))

        try:
            final_response = await self._llm.ainvoke(messages_for_final)
            content = final_response.content.strip()
            suggestions = self._parse_suggestions(content)
        except Exception as e:
            logger.error(f"[ReActSuggestion] 最终建议生成失败: {e}")
            suggestions = []

        # ── Step 5: 存储建议到 RAG ───────────────────────────────────────────
        total_loaded_files = 0
        if code_parser_result and isinstance(code_parser_result, dict):
            total_loaded_files = code_parser_result.get("total_files", 0)
        if rag_available and suggestions and total_loaded_files > 0:
            try:
                def sync_rag_store():
                    tech_stack = []
                    languages = []
                    if tech_stack_result and isinstance(tech_stack_result, dict):
                        raw_fw = tech_stack_result.get("frameworks", []) or []
                        if raw_fw:
                            if isinstance(raw_fw[0], dict):
                                tech_stack = [f.get("name", "") for f in raw_fw if f.get("name")]
                            else:
                                tech_stack = [str(f) for f in raw_fw]
                        langs = tech_stack_result.get("languages", []) or []
                        if langs:
                            if isinstance(langs[0], dict):
                                languages = [l.get("name", "") for l in langs if l.get("name")]
                            else:
                                languages = [str(l) for l in langs]

                    project_scale = "small" if total_loaded_files <= 100 else ("medium" if total_loaded_files <= 500 else "large")

                    stored = 0
                    for sug in suggestions:
                        if sug.get("priority") not in ("high", "medium"):
                            continue
                        try:
                            _rag_store_suggestion_impl(
                                repo_url=repo_path,
                                category="suggestion",
                                title=sug.get("title", ""),
                                content=sug.get("description", ""),
                                priority=sug.get("priority", "medium"),
                                tech_stack=tech_stack,
                                languages=languages,
                                project_scale=project_scale,
                                code_fix=sug.get("code_fix"),
                                verified=sug.get("verified", False),
                                issue_type=sug.get("type", ""),
                            )
                            stored += 1
                        except Exception:
                            pass
                    return stored

                stored_count = await asyncio.get_running_loop().run_in_executor(None, sync_rag_store)
                if stored_count > 0:
                    logger.info(f"[ReActSuggestion] RAG 存储了 {stored_count} 条建议")
            except Exception as e:
                logger.warning(f"[ReActSuggestion] RAG 存储失败: {e}")

        # ── Step 6: 去重 + 排序 ─────────────────────────────────────────────
        suggestions = self._dedupe_and_sort(suggestions)

        # ── Step 7: 输出最终结果 ─────────────────────────────────────────────
        yield {
            "type": "result",
            "agent": "optimization",
            "message": f"生成了 {len(suggestions)} 条优化建议",
            "percent": 100,
            "data": {
                "suggestions": suggestions,
                "total": len(suggestions),
                "high_priority": sum(1 for s in suggestions if s.get("priority") == "high"),
                "verified_count": sum(1 for s in suggestions if s.get("verified")),
                "tool_calls": len(verification.tool_calls),
                "rag": {
                    "active": rag_available and total_loaded_files > 0,
                    "history_count": len(rag_results),
                },
            },
        }

    # ── 上下文构建 ──────────────────────────────────────────────────────────

    def _build_context(
        self,
        repo_path: str,
        branch: str,
        file_contents: dict | None,
        code_parser_result: dict | None,
        tech_stack_result: dict | None,
        quality_result: dict | None,
        dependency_result: dict | None,
    ) -> str:
        """构建发送给 LLM 的分析上下文。"""
        parts = [f"# 仓库优化建议生成任务\n仓库: {repo_path}@{branch}\n"]

        if tech_stack_result and isinstance(tech_stack_result, dict):
            parts.append("【技术栈】")
            raw_langs = tech_stack_result.get('languages', []) or []
            if raw_langs and isinstance(raw_langs[0], dict):
                languages = [l.get('name', '') for l in raw_langs if l.get('name')]
            else:
                languages = [str(l) for l in raw_langs]
            parts.append(f"  语言: {', '.join(languages) if languages else '未知'}")
            raw_fw = tech_stack_result.get('frameworks', []) or []
            if raw_fw and isinstance(raw_fw[0], dict):
                fw_names = [f.get('name', '') for f in raw_fw if f.get('name')]
            else:
                fw_names = list(raw_fw) if isinstance(raw_fw, list) else []
            parts.append(f"  框架: {', '.join(fw_names) or '无'}")
            infra = tech_stack_result.get('infrastructure', []) or []
            if infra and isinstance(infra[0], dict):
                infra = [i.get('name', '') for i in infra if i.get('name')]
            parts.append(f"  基础设施: {', '.join(str(i) for i in infra) if infra else '无'}")
            dev_tools = tech_stack_result.get('dev_tools', []) or []
            parts.append(f"  开发工具: {', '.join(str(d) for d in dev_tools) if dev_tools else '无'}")
            deployment = tech_stack_result.get('deployment', []) or []
            parts.append(f"  部署方式: {', '.join(str(d) for d in deployment) if deployment else '无'}")
            config_files = tech_stack_result.get('config_files_found', []) or []
            parts.append(f"  配置文件: {', '.join(str(c) for c in config_files) if config_files else '无'}")
            parts.append("")

        if quality_result and isinstance(quality_result, dict):
            parts.append("【代码质量】")
            parts.append(f"  健康度: {quality_result.get('health_score', '?')}/100")
            parts.append(f"  测试覆盖率: {quality_result.get('test_coverage', '?')}%")
            parts.append(f"  代码质量复杂度: {quality_result.get('qualityComplexity', '?')}")
            parts.append(f"  可维护性: {quality_result.get('qualityMaintainability', '?')}")
            dup = quality_result.get("duplication")
            if dup and isinstance(dup, dict):
                parts.append(f"  重复率: {dup.get('score', 0)}% ({dup.get('duplication_level', '?')})")
            hotspots = quality_result.get("hotspots", [])
            if hotspots and isinstance(hotspots, list):
                parts.append("  代码热点问题:")
                for h in hotspots[:10]:
                    if isinstance(h, dict):
                        f = h.get("file", "unknown")
                        line = h.get("line", "?")
                        t = h.get("type", "unknown")
                        severity = h.get("severity", "?")
                        desc = h.get("description", "")[:60]
                        parts.append(f"    - [{severity}] {t} @ {f}:{line} - {desc}...")
            concerns = quality_result.get("main_concerns", [])
            if concerns and isinstance(concerns, list):
                parts.append("  主要关注:")
                for c in concerns[:5]:
                    parts.append(f"    - {c}")
            parts.append("")

        if dependency_result and isinstance(dependency_result, dict):
            parts.append("【依赖风险】")
            parts.append(f"  总依赖: {dependency_result.get('total', 0)}")
            parts.append(f"  高危: {dependency_result.get('high', 0)}，中危: {dependency_result.get('medium', 0)}")
            parts.append(f"  风险等级: {dependency_result.get('risk_level', 'unknown')}")
            deps = dependency_result.get("deps", []) or []
            risky = [d for d in deps if isinstance(d, dict) and d.get("risk_level") in ("high", "medium")][:5]
            if risky:
                parts.append("  高风险依赖:")
                for d in risky:
                    name = d.get('name', 'unknown')
                    version = d.get('version', '*')
                    risk = d.get('risk_level', 'unknown')
                    parts.append(f"    - {name}@{version} ({risk})")
            parts.append("")

        if code_parser_result and isinstance(code_parser_result, dict):
            cr = code_parser_result
            largest = cr.get("largest_files", []) or []
            parts.append("【代码结构】")
            parts.append(f"  总文件: {cr.get('total_files', 0)}")
            parts.append(f"  总函数: {cr.get('total_functions', 0)}")
            parts.append(f"  总类: {cr.get('total_classes', 0)}")
            if largest and isinstance(largest[0], dict):
                parts.append("  最大文件（可能导致性能问题）:")
                for f in largest[:5]:
                    if isinstance(f, dict):
                        path = f.get('path', 'unknown')
                        lines = f.get('lines', 0)
                        parts.append(f"    - {path} ({lines}行)")
            parts.append("")

        # 注意：不再包含 file_contents 预览，避免传递大量源码消耗 token
        # 所有问题已由 QualityAgent 定位，Suggestion Agent 基于结论生成建议即可

        parts.append("请基于以上分析结论生成优化建议，code_fix.file 必须来自上述文件列表。")
        return "\n".join(parts)

    def _build_rag_query(self, tech_stack_result, quality_result, code_parser_result=None) -> str:
        """构建 RAG 检索 query。"""
        query_parts = []

        if tech_stack_result and isinstance(tech_stack_result, dict):
            raw_fw = tech_stack_result.get("frameworks", []) or []
            if raw_fw and isinstance(raw_fw[0], dict):
                query_parts.extend([f.get('name', '') for f in raw_fw[:3] if f.get('name')])
            else:
                query_parts.extend([str(f) for f in raw_fw[:3]])
            raw_lang = tech_stack_result.get("languages", []) or []
            if raw_lang and isinstance(raw_lang[0], dict):
                query_parts.extend([l.get('name', '') for l in raw_lang[:2] if l.get('name')])
            else:
                query_parts.extend([str(l) for l in raw_lang[:2]])

        if code_parser_result and isinstance(code_parser_result, dict):
            total_files = code_parser_result.get("total_files", 0)
            if total_files > 500:
                query_parts.append("大型项目")
            elif total_files > 100:
                query_parts.append("中型项目")

        if quality_result and isinstance(quality_result, dict):
            dup = quality_result.get("duplication", {})
            if dup.get("score", 0) > 15:
                query_parts.append("高重复率")
            hotspots = quality_result.get("hotspots", [])
            if hotspots:
                issue_types = set(h.get("type", "") for h in hotspots[:5] if isinstance(h, dict))
                query_parts.extend(list(issue_types)[:2])

        return " ".join(query_parts) or "代码优化建议"

    def _build_final_prompt(
        self, context: str, verification: VerificationResult,
        rag_results: list
    ) -> str:
        """构建最终建议生成 prompt。"""
        parts = [f"\n## 工具调用结果汇总\n"]

        if verification.tool_calls:
            parts.append(f"共进行了 {len(verification.tool_calls)} 次工具调用")
            parts.append("")

        if verification.smell_results:
            total_smells = sum(len(v) for v in verification.smell_results.values())
            if total_smells > 0:
                parts.append(f"检测到的代码异味 ({total_smells} 个):")
                for path, smells in list(verification.smell_results.items())[:5]:
                    for smell in smells[:2]:
                        parts.append(f"  - [{path}] {smell.get('type', '')}: {smell.get('description', '')[:50]}")
            parts.append("")

        if rag_results:
            parts.append("## 历史经验参考\n")
            for r in rag_results[:3]:
                parts.append(f"- [{r.get('category', '')}] {r.get('title', '')}")
                parts.append(f"  {r.get('content', '')[:100]}")
            parts.append("")

        parts.append("请基于以上工具调用结果和历史经验，生成最终的优化建议 JSON 数组。")
        parts.append("每条建议的 verified=true 基于已有的分析结论，code_fix.file 必须来自 hotspots 或 largest_files。")
        return "\n".join(parts)

    # ── JSON 解析 ───────────────────────────────────────────────────────────

    def _parse_suggestions(self, content: str) -> list[dict]:
        """解析 LLM 返回的建议 JSON。"""
        text = content.strip()

        if text.startswith("["):
            try:
                return self._normalize_suggestions(json.loads(text))
            except json.JSONDecodeError:
                pass

        match = re.search(r"\[[\s\S]*\]", text)
        if match:
            try:
                return self._normalize_suggestions(json.loads(match.group(0)))
            except json.JSONDecodeError:
                pass

        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if json_match:
            try:
                return self._normalize_suggestions(json.loads(json_match.group(1).strip()))
            except json.JSONDecodeError:
                pass

        return self._parse_truncated_json(text)

    def _parse_truncated_json(self, text: str) -> list[dict]:
        """从可能被截断的文本中提取完整的 suggestion 对象。"""
        suggestions = []
        bracket_depth = 0
        obj_start = -1
        in_str = False
        escape_next = False

        for i, ch in enumerate(text):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                if bracket_depth == 0:
                    obj_start = i
                bracket_depth += 1
            elif ch == "}":
                bracket_depth -= 1
                if bracket_depth == 0 and obj_start >= 0:
                    obj_str = text[obj_start:i + 1]
                    try:
                        obj = json.loads(obj_str)
                        if isinstance(obj, dict) and obj.get("title"):
                            suggestions.append(obj)
                    except json.JSONDecodeError:
                        pass
                    obj_start = -1

        return self._normalize_suggestions(suggestions)

    def _normalize_suggestions(self, raw: list) -> list[dict]:
        """标准化建议列表。"""
        validated = []
        for s in raw:
            if not isinstance(s, dict):
                continue
            title = s.get("title", "").strip()
            if not title:
                continue

            code_fix = s.get("code_fix", {})
            normalized_fix = {
                "file": str(code_fix.get("file", "")),
                "type": str(code_fix.get("type", "replace")),
                "original": str(code_fix.get("original", "")),
                "updated": str(code_fix.get("updated", "")),
                "reason": str(code_fix.get("reason", "")),
            }

            priority = self._normalize_priority(s.get("priority"))
            validated.append({
                "id": self._next_id(),
                "type": str(s.get("type", "general")).lower()[:20],
                "title": title[:30],
                "description": str(s.get("description", ""))[:300],
                "priority": priority,
                "category": str(s.get("category", "general"))[:30],
                "source": "llm-react",
                "verified": bool(s.get("verified", False)),
                "code_fix": normalized_fix,
            })

        return validated

    def _normalize_priority(self, p: Any) -> str:
        if isinstance(p, str):
            p = p.lower().strip()
            if p in ("high", "h", "高", "高危", "critical"):
                return "high"
            if p in ("medium", "m", "中", "中等"):
                return "medium"
        return "low"

    def _dedupe_and_sort(self, suggestions: list[dict]) -> list[dict]:
        """去重 + 按 priority 排序。"""
        seen = set()
        unique = []
        for s in suggestions:
            key = s.get("title", "").strip().lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(s)

        priority_order = {"high": 0, "medium": 1, "low": 2}
        unique.sort(key=lambda s: priority_order.get(s["priority"], 2))
        return unique[:self.MAX_SUGGESTIONS]

    def _parse_repo(self, repo_path: str | None) -> tuple[str, str]:
        """从 repo_path 解析 owner/repo。"""
        if not repo_path:
            return "", ""
        parts = repo_path.strip().replace("https://github.com/", "").replace("http://github.com/", "").split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
        return "", ""

    # ── 规则引擎兜底 ────────────────────────────────────────────────────────

    async def _rule_based_fallback(
        self,
        owner: str, repo: str, ref: str,
        quality_result, dependency_result, file_contents
    ) -> AsyncGenerator[dict, None]:
        """规则引擎兜底（LLM 不可用时）。"""
        suggestions = []
        _id = [100]

        def next_id():
            v = _id[0]
            _id[0] += 1
            return v

        if quality_result and isinstance(quality_result, dict):
            try:
                suggestions.extend(_quality_suggestions_impl(quality_result, next_id))
            except Exception as e:
                logger.warning(f"[ReActSuggestion] _quality_suggestions_impl 失败: {e}")

        if dependency_result and isinstance(dependency_result, dict):
            try:
                suggestions.extend(_dependency_suggestions_impl(dependency_result, next_id))
            except Exception as e:
                logger.warning(f"[ReActSuggestion] _dependency_suggestions_impl 失败: {e}")

        if not suggestions:
            suggestions.append({
                "id": next_id(),
                "type": "general",
                "title": "项目整体状态良好",
                "description": "未检测到明显问题，建议持续关注代码质量和依赖安全。",
                "priority": "low",
                "category": "general",
                "source": "rule",
            })

        yield {
            "type": "result",
            "agent": "optimization",
            "message": f"规则引擎生成 {len(suggestions)} 条建议",
            "percent": 100,
            "data": {
                "suggestions": suggestions,
                "total": len(suggestions),
                "high_priority": sum(1 for s in suggestions if s.get("priority") == "high"),
                "verified_count": 0,
                "tool_calls": 0,
                "rag": {"active": False, "history_count": 0},
            },
        }


# ─── 规则建议实现 ──────────────────────────────────────────────────────────

def _quality_suggestions_impl(qr: dict, next_id) -> list[dict]:
    """基于代码质量数据的规则建议（LLM 兜底）。"""
    suggestions: list[dict] = []

    health = qr.get("health_score", 100)
    coverage = qr.get("test_coverage", 100)
    dup_info = qr.get("duplication", {})
    py_metrics = qr.get("python_metrics", {})
    ts_metrics = qr.get("typescript_metrics", {})

    if health < 60:
        suggestions.append({
            "id": next_id(),
            "type": "performance",
            "title": "代码健康度偏低 (< 60)",
            "description": f"当前健康度评分为 {health}，建议优先解决圈复杂度超标、代码重复率高等问题。",
            "priority": "high",
            "category": "quality",
            "source": "rule",
        })

    if coverage < 30:
        suggestions.append({
            "id": next_id(),
            "type": "performance",
            "title": "测试覆盖率严重不足 (< 30%)",
            "description": f"当前测试覆盖率仅 {coverage}%。建议使用 Jest/Vitest (JS) 或 pytest (Python) 补充单元测试。",
            "priority": "high",
            "category": "testing",
            "source": "rule",
        })
    elif coverage < 60:
        suggestions.append({
            "id": next_id(),
            "type": "performance",
            "title": "测试覆盖率偏低 (< 60%)",
            "description": f"当前测试覆盖率为 {coverage}%，建议逐步补充关键模块的测试用例。",
            "priority": "medium",
            "category": "testing",
            "source": "rule",
        })

    dup_level = dup_info.get("duplication_level", "Low")
    dup_score = dup_info.get("score", 0)
    if dup_level == "High" or dup_score > 15:
        suggestions.append({
            "id": next_id(),
            "type": "refactor",
            "title": "代码重复率较高",
            "description": f"重复率 {dup_score}%，建议将重复代码块抽取为公共函数。",
            "priority": "medium",
            "category": "readability",
            "source": "rule",
        })

    for metrics, lang_label in [(py_metrics, "Python"), (ts_metrics, "TypeScript")]:
        over_complex = metrics.get("over_complexity_count", 0)
        if over_complex > 5:
            suggestions.append({
                "id": next_id(),
                "type": "performance",
                "title": f"{lang_label}: 存在 {over_complex} 个高圈复杂度函数 (> 10)",
                "description": "建议拆分大型函数，每个函数控制在 50 行以内。",
                "priority": "medium",
                "category": "complexity",
                "source": "rule",
            })

    long_funcs = py_metrics.get("long_functions", [])
    if len(long_funcs) > 3:
        suggestions.append({
            "id": next_id(),
            "type": "refactor",
            "title": f"存在 {len(long_funcs)} 个超长 Python 函数 (> 50 行)",
            "description": "建议按职责拆分为更小的函数，提高可读性和可维护性。",
            "priority": "low",
            "category": "readability",
            "source": "rule",
        })

    return suggestions


def _dependency_suggestions_impl(dr: dict, next_id) -> list[dict]:
    """基于依赖风险数据的规则建议（LLM 兜底）。"""
    suggestions: list[dict] = []

    high = dr.get("high", 0)
    medium = dr.get("medium", 0)
    risk_level = dr.get("risk_level", "")
    deps = dr.get("deps", [])

    if risk_level == "高危" or high > 0:
        suggestions.append({
            "id": next_id(),
            "type": "security",
            "title": "存在高风险依赖",
            "description": f"检测到 {high} 个高危依赖，可能包含已知安全漏洞，建议立即更新或替换。",
            "priority": "high",
            "category": "security",
            "source": "rule",
        })

    if medium > 5:
        suggestions.append({
            "id": next_id(),
            "type": "security",
            "title": f"存在 {medium} 个中等风险依赖",
            "description": "建议使用 `npm audit` / `pip-audit` / `cargo audit` 定期扫描已知漏洞。",
            "priority": "medium",
            "category": "dependency",
            "source": "rule",
        })

    no_version = [d for d in deps if not d.get("version") or d["version"] == "*"]
    if no_version:
        suggestions.append({
            "id": next_id(),
            "type": "performance",
            "title": f"存在 {len(no_version)} 个依赖未锁定版本",
            "description": "建议使用精确版本号或语义化版本范围，避免不一致性。",
            "priority": "medium",
            "category": "dependency",
            "source": "rule",
        })

    outdated_flags = {
        "request": "request 库已废弃，建议迁移到 axios 或原生 fetch",
        "lodash": "lodash 体积较大，建议按需引入或使用原生方法替代",
        "moment": "moment 已停止维护，建议迁移到 dayjs 或 date-fns",
        "jquery": "jQuery 在现代前端项目中通常可移除",
    }
    names = {d["name"].lower() for d in deps}
    for pkg, desc in outdated_flags.items():
        if pkg in names:
            suggestions.append({
                "id": next_id(),
                "type": "refactor",
                "title": f"检测到过时依赖: {pkg}",
                "description": desc,
                "priority": "medium",
                "category": "dependency",
                "source": "rule",
            })

    return suggestions
