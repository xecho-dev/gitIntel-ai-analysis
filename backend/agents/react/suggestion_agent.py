"""
ReActSuggestionAgent — 基于 ReAct 模式的优化建议生成 Agent。

与旧版 SuggestionAgent 的核心区别：
  - 旧版：一次性把所有上下文塞给 LLM，code_fix 是 guesswork
  - 新版：Agent 可以主动调用工具验证问题、精确读取文件内容，生成可执行的 code_fix

工具集：
  GitHub:  read_file_content, get_file_blobs, search_code
  Code:    parse_file_ast, detect_code_smells, detect_imports
  RAG:     rag_search_similar, rag_search_by_category

工作流程：
  1. 基于分析数据识别潜在问题
  2. 对每个问题，调用工具验证：
     - 搜索相关代码模式确认问题存在
     - 读取具体文件确认精确位置
     - 深度分析文件了解上下文
  3. 基于验证结果，生成含精确 code_fix 的建议
  4. 存储高优先级建议到 RAG
"""
import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Annotated, Any, AsyncGenerator

from langchain_core.messages import HumanMessage, SystemMessage

from tools.github_tools import read_file_content, search_code
from tools.code_tools import parse_file_ast, detect_code_smells, detect_imports
from tools.rag_tools import (
    rag_search_similar, rag_search_by_category, rag_store_suggestion,
    _rag_search_similar_impl, _rag_store_suggestion_impl,
)

logger = logging.getLogger("gitintel")

# ─── Token 预算配置（可由环境变量覆盖）───────────────────────────────────────

_MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "2048"))
_TOOL_RESULT_TRUNCATE = int(os.getenv("TOOL_RESULT_TRUNCATE", "1500"))


# ─── 工具列表 ────────────────────────────────────────────────────────────────

SUGGESTION_TOOLS = [
    read_file_content,
    search_code,
    parse_file_ast,
    detect_code_smells,
    detect_imports,
    rag_search_similar,
    rag_search_by_category,
]

# ─── System Prompt ─────────────────────────────────────────────────────────────

REACT_SUGGESTION_SYSTEM = """你是一名资深软件架构师，为 GitIntel 系统生成优化建议。

任务：基于代码分析数据，生成可操作的优化建议，每个建议必须：(1)经过工具验证 (2)包含精确的code_fix (3)给出可落地的改进步骤。

工具使用规则：
  **重要**：read_file_content, search_code 等 GitHub 工具只需要传入 path/query 参数，
  owner/repo/ref 会自动注入，无需手动传入。

工具调用示例：
  - read_file_content(path="src/main.js")  # 自动使用当前仓库
  - search_code(query="authentication", language="python")  # 只需 query 和 language

工作流：(Step1)用search_code确认问题存在→用read_file_content精确读文件→用detect_code_smells量化分析
(Step2)code_fix.original必须是文件中实际存在的代码字符串
(Step3)评估影响范围和关联修改

关注类型：安全性(硬编码密码/Secret、SQL注入)、性能(N+1、缺少缓存)、可维护性(过长函数>50行、深度嵌套>4层)、测试覆盖、架构(循环依赖、紧耦合)。

输出 JSON 数组（不要markdown包裹）：
[
  {
    "type": "security|performance|refactor|testing|complexity|architecture|general",
    "title": "中文标题，20字以内",
    "description": "详细说明80-200字，包含步骤和原因",
    "priority": "high|medium|low",
    "category": "security|performance|maintainability|testing|architecture",
    "verified": true|false,
    "code_fix": {
      "file": "精确路径",
      "type": "replace|add|remove",
      "original": "文件中实际存在的代码（精确字符串）",
      "updated": "修改后的代码",
      "reason": "修改原因，20字以内"
    }
  }
]

要求：返回3-6条建议按priority降序；verified=true必须有工具验证记录；
code_fix.original必须是实际代码不是占位符；不要泛泛而谈，每条要有具体文件位置和修改方案。"""


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
    verified_files: dict[str, str] = field(default_factory=dict)
    ast_results: dict[str, dict] = field(default_factory=dict)
    smell_results: dict[str, list] = field(default_factory=dict)


class ReActSuggestionAgent:
    """基于 ReAct 模式的优化建议生成 Agent。

    特性：
      - 主动验证：每个建议都经过工具验证，确保精确性
      - 精确修复：code_fix 的 original 来自真实文件内容
      - 历史增强：使用 RAG 搜索相似项目的经验
      - 流式输出：支持实时 yield 验证进度

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

    MAX_ITERATIONS = 4  # 默认 4 轮，控制 token 消耗
    MAX_SUGGESTIONS = 6
    _id_counter = 0

    def __init__(self):
        from utils.llm_factory import get_llm_with_tracking
        self.llm = self._get_llm()

    @staticmethod
    def _get_llm():
        try:
            from utils.llm_factory import get_llm_with_tracking
            return get_llm_with_tracking(agent_name="ReActSuggestion", max_tokens=_MAX_OUTPUT_TOKENS)
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
        """流式生成优化建议。"""
        import httpx

        owner, repo = self._parse_repo(repo_path)
        ref = branch or "main"

        # 确保分支存在：如果用户传入 main 但仓库实际是 master，自动修正
        if ref in ("main", ""):
            try:
                from tools.github_tools import _get_default_branch_impl
                actual_branch = await _get_default_branch_impl(owner, repo)
                if actual_branch and actual_branch != ref:
                    logger.info(f"[ReActSuggestion] 分支修正: {ref} -> {actual_branch}")
                    ref = actual_branch
            except Exception as e:
                logger.warning(f"[ReActSuggestion] 获取默认分支失败: {e}")

        # ── Step 1: 构建分析上下文 ────────────────────────────────
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

        # ── Step 2: RAG 检索历史经验 ──────────────────────────────
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

        # ── Step 3: 初始建议生成（带工具调用） ──────────────────────
        yield {
            "type": "progress",
            "agent": "optimization",
            "message": "正在生成初始建议并验证...",
            "percent": 15,
            "data": None,
        }

        if self.llm is None:
            # LLM 不可用时，使用规则引擎
            async for fallback_event in self._rule_based_fallback(
                owner, repo, ref,
                quality_result, dependency_result, file_contents
            ):
                yield fallback_event
            return

        # 构建初始消息
        verification = VerificationResult()
        messages = [
            SystemMessage(content=REACT_SUGGESTION_SYSTEM),
            HumanMessage(content=context),
        ]

        suggestions: list[dict] = []
        iteration = 0

        while iteration < self.MAX_ITERATIONS:
            iteration += 1

            # ── DEBUG: 记录每次 LLM 调用前的消息结构 ──
            msg_types = [f"{type(m).__name__}" for m in messages]
            msg_summary = ",".join(msg_types)
            # 检查是否有 dangling ToolMessage（Tool 在紧跟 Human 之后，没有中间的 AI）
            has_dangling = False
            for i in range(len(messages) - 1):
                if (type(messages[i]).__name__ == "HumanMessage" and
                    type(messages[i+1]).__name__ == "ToolMessage"):
                    has_dangling = True
                    break
            logger.debug(f"[ReActSuggestion] 迭代 {iteration} 开始，消息数={len(messages)}, 结构={msg_summary}, dangling={has_dangling}")

            # LLM 生成建议（带工具调用）
            llm_with_tools = self.llm.bind_tools(
                SUGGESTION_TOOLS,
                parallel_tool_calls=True,  # 允许多个工具并行调用
            )

            try:
                response = await llm_with_tools.ainvoke(messages)
                messages.append(response)
            except Exception as e:
                logger.error(f"[ReActSuggestion] 迭代 {iteration} LLM 调用失败 (400?): {e}")
                # 移除本轮追加的 AI 消息，避免破坏消息链
                if messages and hasattr(messages[-1], "tool_calls"):
                    messages.pop()
                break

            tool_calls = response.tool_calls or []
            if not tool_calls:
                # LLM 没有调用工具，可能已完成
                break

            # 执行工具调用
            for tc in tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]

                try:
                    result = await self._execute_tool(
                        owner, repo, ref, verification, tool_name, tool_args
                    )
                    verification.tool_calls.append({
                        "tool": tool_name, "args": tool_args, "result": result[:500]
                    })

                    # 实时 yield 工具执行进度
                    yield {
                        "type": "progress",
                        "agent": "optimization",
                        "message": f"[验证 {iteration}] {tool_name}: {result[:80]}",
                        "percent": min(15 + iteration * 12, 65),
                        "data": {"tool": tool_name, "result": result[:150]},
                    }

                    # 使用 ToolMessage 添加观察结果（Function Calling 规范要求）
                    from langchain_core.messages import ToolMessage
                    tc_id = tc.get("id") or f"call_{iteration}_{tool_name}"
                    messages.append(
                        ToolMessage(
                            content=result[:_TOOL_RESULT_TRUNCATE],
                            tool_call_id=tc_id,
                        )
                    )

                except Exception as e:
                    logger.warning(f"[ReActSuggestion] 工具执行失败: {tool_name}: {e}")
                    from langchain_core.messages import ToolMessage
                    tc_id = tc.get("id") or f"call_{iteration}_{tool_name}"
                    messages.append(
                        ToolMessage(
                            content=f"[错误] {type(e).__name__}: {str(e)}",
                            tool_call_id=tc_id,
                        )
                    )

            # 防止消息历史无限膨胀：保留 SystemMessage + 初始 HumanMessage + 最近 2 轮完整对话
            # 关键：必须保留完整的三元组（Human + AI(tool_calls) + ToolMessage），
            # 避免 dangling ToolMessage 导致下一轮 LLM 调用报 400 错误。
            #
            # 策略：找到最后一个 HumanMessage 的位置（作为最后一轮的起始），
            # 保留 [最后一个 Human, AI, Tool...] + 再往前一整轮。
            if len(messages) > 8:
                system = messages[0]
                initial = messages[1]
                history = messages[2:]  # 跳过 System 和初始 Human

                if len(history) > 6:
                    # 找到最后一个 HumanMessage 的索引（最后一轮的开始）
                    last_human_idx = -1
                    for i in range(len(history) - 1, -1, -1):
                        if type(history[i]).__name__ == "HumanMessage":
                            last_human_idx = i
                            break

                    if last_human_idx >= 0:
                        # 保留: [System, Initial, Summary, 从最后一个 Human 开始的所有消息]
                        # 再往前找一整轮（找到倒数第二个 Human）
                        second_last_human_idx = -1
                        for i in range(last_human_idx - 1, -1, -1):
                            if type(history[i]).__name__ == "HumanMessage":
                                second_last_human_idx = i
                                break

                        if second_last_human_idx >= 0:
                            keep_from = second_last_human_idx
                        else:
                            keep_from = last_human_idx

                        # 提取摘要（跳过保留的部分）
                        summary_lines = ["## 前期建议摘要"]
                        seen = set()
                        for msg in history[:keep_from]:
                            if isinstance(msg, HumanMessage):
                                text = msg.content or ""
                                for line in text.split("\n"):
                                    stripped = line.strip()
                                    if stripped.startswith("## ") or stripped.startswith("### "):
                                        key = stripped[:60]
                                        if key not in seen:
                                            seen.add(key)
                                            summary_lines.append(f"  {stripped}")

                        summary_msg = HumanMessage(content="\n".join(summary_lines))
                        messages[:] = [system, initial, summary_msg] + history[keep_from:]
                        logger.debug(f"[ReActSuggestion] 压缩后消息数={len(messages)}, keep_from={keep_from}")

            # 检查是否已收集到足够的验证信息
            if len(verification.verified_files) >= 3 or len(verification.tool_calls) >= 8:
                break

        # ── Step 4: 生成最终建议 ────────────────────────────────
        yield {
            "type": "progress",
            "agent": "optimization",
            "message": "正在生成最终建议...",
            "percent": 70,
            "data": None,
        }

        # 让 LLM 基于验证结果生成精确建议
        final_prompt = self._build_final_prompt(
            context, verification, rag_results
        )
        messages.append(HumanMessage(content=final_prompt))

        try:
            final_response = await self.llm.ainvoke(messages)
            content = final_response.content.strip()

            # 解析 JSON
            suggestions = self._parse_suggestions(content)

        except Exception as e:
            logger.error(f"[ReActSuggestion] 最终建议生成失败: {e}")
            suggestions = []

        # ── Step 5: 存储建议到 RAG（多维度批量存储）──────────────
        if rag_available and suggestions:
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

                    total_files = 0
                    if code_parser_result and isinstance(code_parser_result, dict):
                        total_files = code_parser_result.get("total_files", 0)
                    project_scale = "small" if total_files <= 100 else ("medium" if total_files <= 500 else "large")

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

        # ── Step 6: 去重 + 排序 ─────────────────────────────────
        suggestions = self._dedupe_and_sort(suggestions)

        # ── Step 7: 输出最终结果 ────────────────────────────────
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
                    "active": rag_available,
                    "history_count": len(rag_results),
                },
            },
        }

    async def _execute_tool(
        self,
        owner: str, repo: str, ref: str,
        verification: VerificationResult,
        tool_name: str,
        args: dict,
    ) -> str:
        """执行单个工具。"""
        import asyncio

        # 对于需要 owner/repo 的 GitHub 工具，确保参数正确
        if tool_name in ("read_file_content", "get_file_tree", "search_code",
                         "get_file_blobs", "get_commit_history", "get_pull_requests"):
            # 优先使用全局 owner/repo，避免 LLM 混淆参数
            effective_args: dict = {"owner": owner, "repo": repo}
            # read_file_content, get_file_tree, get_commit_history 需要 ref
            if tool_name in ("read_file_content", "get_file_tree", "get_commit_history"):
                effective_args["ref"] = ref
            # 合并 LLM 传入的参数
            effective_args.update({k: v for k, v in args.items() if k in (
                "path", "paths", "query", "language", "state", "limit"
            )})
            tool_args = effective_args
        elif tool_name in ("parse_file_ast", "detect_code_smells",
                           "detect_imports", "detect_dependencies"):
            # 代码分析工具需要 content 和 language，通过 verified_files 中已读文件反查
            effective_args: dict = {}
            content = args.get("content", "")
            if not content:
                # 从已验证的文件内容中查找
                for path_key, file_content in verification.verified_files.items():
                    if path_key and path_key in (args.get("file_path") or ""):
                        content = file_content
                        break
                if not content and verification.verified_files:
                    content = next(iter(verification.verified_files.values()), "")
            effective_args["content"] = content
            effective_args["language"] = args.get("language", "")
            effective_args["file_path"] = args.get("file_path", "")
            if tool_name == "parse_file_ast":
                effective_args["language"] = args.get("language", "")
            elif tool_name == "summarize_code_file":
                effective_args["max_lines"] = args.get("max_lines", 80)
            tool_args = effective_args
        else:
            tool_args = args

        def sync_call():
            return SUGGESTION_TOOLS[_get_suggestion_tool_index(tool_name)].invoke(tool_args)

        result = await asyncio.get_running_loop().run_in_executor(None, sync_call)

        # 打印返回结果类型，方便调试
        logger.debug(f"[ReActSuggestion] {tool_name} 返回类型: {type(result).__name__}, 内容预览: {str(result)[:200]}")

        # 更新验证结果
        if tool_name == "read_file_content":
            path = tool_args.get("path", "unknown")
            verification.verified_files[path] = str(result)

        elif tool_name == "parse_file_ast":
            try:
                verification.ast_results[tool_args.get("file_path", "")] = json.loads(result)
            except json.JSONDecodeError:
                verification.ast_results[tool_args.get("file_path", "")] = {"error": "parse failed", "raw": str(result)}

        elif tool_name == "detect_code_smells":
            try:
                raw_result = result
                if isinstance(result, str):
                    try:
                        parsed = json.loads(result)
                    except json.JSONDecodeError:
                        parsed = []
                else:
                    parsed = result

                # 处理嵌套结构 {"output": "[]"} 的情况
                if isinstance(parsed, dict):
                    if "output" in parsed:
                        inner = parsed["output"]
                        if isinstance(inner, str):
                            try:
                                parsed = json.loads(inner)
                            except json.JSONDecodeError:
                                parsed = []
                        else:
                            parsed = inner
                    elif "result" in parsed:
                        inner = parsed["result"]
                        if isinstance(inner, str):
                            try:
                                parsed = json.loads(inner)
                            except json.JSONDecodeError:
                                parsed = []
                        else:
                            parsed = inner

                # 确保结果是列表（空列表 [] 也是合法的有效结果）
                if isinstance(parsed, list):
                    key = tool_args.get("file_path", "") or (
                        tool_args.get("content", "")[:50] if tool_args.get("content") else "unknown"
                    )
                    verification.smell_results[key] = parsed
                elif isinstance(parsed, dict) and "smells" in parsed:
                    # 兜底：嵌套在 smells 键下
                    key = tool_args.get("file_path", "") or "unknown"
                    verification.smell_results[key] = parsed["smells"]
                else:
                    # 其他情况（空字符串、None 等）存为空列表
                    verification.smell_results[tool_args.get("file_path", "") or "unknown"] = []
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                logger.warning(f"[ReActSuggestion] detect_code_smells 解析失败: {e}, 原始: {str(result)[:200]}")
                verification.smell_results[tool_args.get("file_path", "") or "unknown"] = []

        return str(result)[:_TOOL_RESULT_TRUNCATE]

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

        # 技术栈
        if tech_stack_result and isinstance(tech_stack_result, dict):
            parts.append("【技术栈】")
            languages = tech_stack_result.get('languages', []) or []
            parts.append(f"  语言: {', '.join(languages) if languages else '未知'}")
            # frameworks 可能是字符串列表（_rule_based_fallback）或对象列表（LLM 输出）
            raw_fw = tech_stack_result.get('frameworks', []) or []
            if raw_fw and isinstance(raw_fw[0], dict):
                fw_names = [f.get('name', '') for f in raw_fw if f.get('name')]
            else:
                fw_names = list(raw_fw) if isinstance(raw_fw, list) else []
            parts.append(f"  框架: {', '.join(fw_names) or '无'}")
            infra = tech_stack_result.get('infrastructure', []) or []
            parts.append(f"  基础设施: {', '.join(infra) if infra else '无'}")
            parts.append("")

        # 代码质量
        if quality_result and isinstance(quality_result, dict):
            parts.append("【代码质量】")
            parts.append(f"  健康度: {quality_result.get('health_score', '?')}/100")
            parts.append(f"  测试覆盖率: {quality_result.get('test_coverage', '?')}%")
            parts.append(f"  复杂度: {quality_result.get('complexity', '?')}")
            parts.append(f"  可维护性: {quality_result.get('maintainability', '?')}")
            dup = quality_result.get("duplication")
            if dup and isinstance(dup, dict):
                parts.append(f"  重复率: {dup.get('score', 0)}% ({dup.get('duplication_level', '?')})")

            # 输出 QualityExplorer 发现的问题热点
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

            # 输出主要关注点
            concerns = quality_result.get("main_concerns", [])
            if concerns and isinstance(concerns, list):
                parts.append("  主要关注:")
                for c in concerns[:5]:
                    parts.append(f"    - {c}")

            parts.append("")

        # 依赖风险
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

        # 代码结构
        if code_parser_result and isinstance(code_parser_result, dict):
            cr = code_parser_result
            lang_stats = cr.get("language_stats", {})
            largest = cr.get("largest_files", []) or []
            parts.append("【代码结构】")
            parts.append(f"  总文件: {cr.get('total_files', 0)}")
            parts.append(f"  总函数: {cr.get('total_functions', 0)}")
            parts.append(f"  总类: {cr.get('total_classes', 0)}")
            if largest and isinstance(largest[0], dict):
                first = largest[0]
                if isinstance(first, dict):
                    path_name = first.get('path', 'unknown').split('/')[-1]
                    lines = first.get('lines', 0)
                    parts.append(f"  最大文件: {path_name}({lines}行)")
            parts.append("")

        # 已加载的文件列表（包含内容预览，供工具调用参考）
        if file_contents and isinstance(file_contents, dict):
            paths = list(file_contents.keys())
            parts.append("【可用文件】（包含内容预览，可使用工具读取）")
            for p in paths[:20]:
                content_preview = file_contents[p][:200].replace("\n", " ").strip() if file_contents.get(p) else ""
                parts.append(f"  - {p}: {content_preview}...")
            if len(paths) > 20:
                parts.append(f"  ... 等 {len(paths)} 个文件")
            parts.append("")

        parts.append("请生成优化建议，对每个问题使用工具验证，并给出精确的 code_fix。")
        return "\n".join(parts)

    def _build_rag_query(self, tech_stack_result, quality_result, code_parser_result=None) -> str:
        """构建 RAG 检索 query（找相似项目的历史经验）。

        检索策略：
          1. 技术栈（核心维度）：框架 + 语言
          2. 项目规模：大型/中型/小型
          3. 问题特征：高重复率、安全问题等
        """
        query_parts = []

        # 1. 技术栈（核心维度）
        if tech_stack_result and isinstance(tech_stack_result, dict):
            raw_fw = tech_stack_result.get("frameworks", []) or []
            if raw_fw and isinstance(raw_fw[0], dict):
                query_parts.extend([f.get('name', '') for f in raw_fw[:3] if f.get('name')])
            else:
                query_parts.extend([str(f) for f in raw_fw[:3]])
            query_parts.extend(tech_stack_result.get("languages", [])[:2] or [])

        # 2. 项目规模（补充维度）
        if code_parser_result and isinstance(code_parser_result, dict):
            total_files = code_parser_result.get("total_files", 0)
            if total_files > 500:
                query_parts.append("大型项目")
            elif total_files > 100:
                query_parts.append("中型项目")

        # 3. 问题特征（补充维度）
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
        """构建最终建议生成 prompt（基于验证结果）。"""
        parts = [f"\n## 验证结果汇总\n"]

        if verification.verified_files:
            parts.append(f"已验证的文件 ({len(verification.verified_files)} 个):")
            for path in list(verification.verified_files.keys())[:10]:
                parts.append(f"  - {path}")
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

        parts.append("请基于以上验证结果和历史经验，生成最终的优化建议 JSON 数组。")
        parts.append("每条建议必须包含 verified=true，code_fix.original 必须是上述已验证文件中实际存在的代码。")
        return "\n".join(parts)

    def _parse_suggestions(self, content: str) -> list[dict]:
        """解析 LLM 返回的建议 JSON。"""
        text = content.strip()

        # 尝试直接解析
        if text.startswith("["):
            try:
                return self._normalize_suggestions(json.loads(text))
            except json.JSONDecodeError:
                pass

        # 从 markdown 中提取
        match = re.search(r"\[[\s\S]*\]", text)
        if match:
            try:
                return self._normalize_suggestions(json.loads(match.group(0)))
            except json.JSONDecodeError:
                pass

        # 尝试提取 ```json 包裹的代码块
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if json_match:
            try:
                return self._normalize_suggestions(json.loads(json_match.group(1).strip()))
            except json.JSONDecodeError:
                pass

        # 逐个提取完整对象
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


def _get_suggestion_tool_index(tool_name: str) -> int:
    for i, t in enumerate(SUGGESTION_TOOLS):
        if t.name == tool_name:
            return i
    raise ValueError(f"未知工具: {tool_name}")


# ─── 规则引擎：内联实现（不再依赖 legacy SuggestionAgent） ───────────────────


def _quality_suggestions_impl(qr: dict, next_id) -> list[dict]:
    """基于代码质量数据的规则建议（LLM 兜底，内联实现）。"""
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
            "description": f"建议按职责拆分为更小的函数，提高可读性和可维护性。",
            "priority": "low",
            "category": "readability",
            "source": "rule",
        })

    return suggestions


def _dependency_suggestions_impl(dr: dict, next_id) -> list[dict]:
    """基于依赖风险数据的规则建议（LLM 兜底，内联实现）。"""
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
