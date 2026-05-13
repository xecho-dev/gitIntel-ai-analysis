"""
并行探索 Agent — 多个 Tool Use Agent 并行工作，探索仓库不同维度。

基于 LangChain `create_agent`（底层是 LangGraph）实现，充分利用 LangChain 的：
  - create_agent: 标准化 ReAct Agent（LangGraph StateGraph）
  - astream_events: 流式事件捕获（工具调用、LLM 推理等）
  - StructuredTool: 统一的工具接口
  - 预构建的 ToolNode: 自动工具执行循环

每个子 Agent 负责一个维度：
  - TechStackExplorer:     技术栈识别
  - QualityExplorer:       代码质量热点发现
  - ArchitectureExplorer:   架构模式识别

用法：
    results = await ExplorerOrchestrator().explore_all("owner", "repo", "main")
"""
import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage, trim_messages
from langchain_core.runnables import Runnable
from langchain_core.tools import StructuredTool

from agents.react.error_loop_detector import ErrorLoopDetector
from agents.react.tool_wrapper import inject_context, ToolLoopInterrupt

logger = logging.getLogger("gitintel")

# ─── Token 预算配置 ───────────────────────────────────────────────────────────

_MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "2048"))
_EXPLORER_MAX_ITERATIONS = int(os.getenv("EXPLORER_MAX_ITERATIONS", "3"))
_EXPLORER_MIN_TOOL_CALLS = int(os.getenv("EXPLORER_MIN_TOOL_CALLS", "1"))  # 降低到 1，小仓库配置文件已提供足够信息
_TOOL_RESULT_TRUNCATE = int(os.getenv("TOOL_RESULT_TRUNCATE", "1500"))

# ─── 上下文压缩配置 ───────────────────────────────────────────────────────────
# 保留最近 N 次工具调用结果（超出则压缩为摘要）
_MAX_COMPRESSED_TOOL_RESULTS = int(os.getenv("MAX_COMPRESSED_TOOL_RESULTS", "6"))
# 压缩后每个工具结果的字符数
_COMPRESSED_RESULT_CHARS = int(os.getenv("COMPRESSED_RESULT_CHARS", "400"))
# 消息历史最大 token 数（约）
_MAX_HISTORY_TOKENS = int(os.getenv("MAX_HISTORY_TOKENS", "6000"))


# ─── 工具工厂 ────────────────────────────────────────────────────────────────

def _get_explorer_tools(
    owner: str, repo: str, branch: str,
    languages: list[str] | None = None,
) -> list[StructuredTool]:
    """构建带 owner/repo/branch 注入的 Explorer 工具列表。"""
    from tools.github_tools import batch_search_code
    from tools.code_tools import detect_code_smells

    base_tools = [
        batch_search_code,
        detect_code_smells,
    ]
    return [inject_context(t, owner=owner, repo=repo, ref=branch, languages=languages) for t in base_tools]


# ─── System Prompts ───────────────────────────────────────────────────────────

_UNIFIED_EXPLORER_PROMPT = """## 角色
你是一名{role}，通过自主探索来完成任务。

## 任务目标
{mission}

## 核心原则
{principles}

## 硬性约束
- 每个结论必须有证据支撑，无证据的结论降低 confidence 或标注 unknown
- 如果信息不足，不要猜测，诚实标注 unknown
- 结论的 confidence 必须反映验证程度：代码验证过 [0.8-1.0]，仅配置文件 [0.3-0.5]

## 行动指南
你可以自主决定探索顺序和策略。常用的探索流程供参考：

### 工具参数规则 ⚠️ 【重要】
- **batch_search_code**: 只需要传 `queries`（查询列表），【不要】传 owner/repo！
  - ✅ 正确：`batch_search_code(queries=[{{"query": "useEffect", "language": "javascript"}}])`
  - ❌ 错误：`batch_search_code(queries=[{{"query": "useEffect"}}], owner="facebook", repo="react")`

### 探索流程
1. 根据上下文中的文件结构，选择关键文件进行探索
2. 用 batch_search_code 批量验证代码特征（如 import 语句、API 使用）
3. 用 detect_code_smells 对可疑文件进行深度分析
4. 随时评估是否已收集足够信息，够了就输出结论

## 输出格式
必须输出有效的 JSON 格式：
```json
{output_schema}
```"""

_TECH_STACK_EXPLORER_INSTRUCTIONS = _UNIFIED_EXPLORER_PROMPT.format(
    role="技术架构师，负责识别 GitHub 仓库的技术栈",
    mission="识别仓库的：①编程语言 ②框架/库 ③基础设施 ④包管理器 ⑤部署方式",
    principles="- **配置文件是直接证据**：requirements.txt/pyproject.toml/package.json 列出依赖 = 有效证据\n"
               "- **代码验证是补充验证**：import 语句可以提升 confidence，但非必须\n"
               "- **高效工作流**：分析配置文件 → 补充代码验证（如有必要）→ 输出结论\n"
               "- **小仓库简化**：少于 20 个文件时，配置文件信息通常足够，无需过度代码搜索\n"
               "- **批量操作**：一次工具调用完成多个任务",
    output_schema="""{
  "languages": [{"name": "...", "confidence": 0.0-1.0, "evidence": ["..."]}],
  "frameworks": [{"name": "...", "confidence": 0.0-1.0, "status": "confirmed|unconfirmed", "evidence": ["..."]}],
  "infrastructure": [{"name": "...", "evidence": ["..."]}],
  "dev_tools": ["..."],
  "package_manager": "...",
  "deployment": ["..."],
  "config_files_found": ["..."],
  "overall_confidence": 0.0-1.0,
  "summary": "一句话描述",
  "unverified_claims": ["..."]
}"""
)


_QUALITY_EXPLORER_INSTRUCTIONS = _UNIFIED_EXPLORER_PROMPT.format(
    role="代码审计专家，负责发现代码质量问题和潜在风险",
    mission="发现：①代码异味 ②安全问题 ③性能隐患 ④测试覆盖不足 ⑤可维护性问题",
    principles="- **每个 hotspot 必须有精确位置**：file + line\n"
               "- **每个建议必须可执行**：不是\"建议优化\"，而是\"在 xxx.py:23 将 yyy 改为 zzz\"\n"
               "- **没有发现问题也是有效结论**：输出 positive_patterns\n"
               "- evidence 驱动评分，禁止主观臆断",
    output_schema="""{
  "hotspots": [{"type": "security|smell|performance", "file": "...", "line": 42, "severity": "high|medium|low", "description": "...", "suggestion": "...", "evidence": "..."}],
  "quality_score": 0-100,
  "test_coverage_estimate": "Low|Medium|High",
  "main_concerns": ["..."],
  "positive_patterns": ["..."],
  "qualityComplexity": "Low|Medium|High",
  "qualityMaintainability": "Low|Medium|High",
  "llmPowered": true
}"""
)


_ARCHITECTURE_EXPLORER_INSTRUCTIONS = _UNIFIED_EXPLORER_PROMPT.format(
    role="软件架构专家，负责识别仓库的架构模式和设计决策",
    mission="识别：①架构风格 ②设计模式 ③分层架构 ④模块组织 ⑤组件关系",
    principles="- **components 必须有依赖链**：每个组件必须明确 depends_on\n"
               "- **架构风格必须有目录/文件证据**\n"
               "- **组件关系必须可追溯**：找到具体的 import 语句",
    output_schema="""{
  "architecture_style": "单体|分层|微服务|CleanArchitecture|DDD",
  "style_evidence": "根据 [具体目录/文件] 推断为 [架构风格]",
  "components": [{"name": "...", "responsibility": "...", "depends_on": ["..."], "file_path": "...", "dependency_evidence": "..."}],
  "design_patterns": [{"pattern": "...", "location": "...", "evidence": "..."}],
  "layers": [{"name": "...", "files": ["..."], "description": "..."}],
  "complexity": "Low|Medium|High",
  "maintainability": "A|B|C|D|E",
  "summary": "深度架构描述",
  "strengths": ["..."],
  "concerns": ["..."]
}"""
)


# ─── 结果结构 ───────────────────────────────────────────────────────────────

@dataclass
class ExplorerResult:
    explorer_type: str = ""
    findings: dict = field(default_factory=dict)
    reasoning: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    error: str = ""
    duration_ms: float = 0.0

    @property
    def tool_call_count(self) -> int:
        return len(self.tool_calls)

    @property
    def verification_status(self) -> str:
        if not self.tool_calls:
            return "no_tools"
        if len(self.tool_calls) < _EXPLORER_MIN_TOOL_CALLS:
            return "insufficient"
        findings_str = str(self.findings).lower()
        if "unverified" in findings_str or "warning" in findings_str:
            return "partially_verified"
        return "fully_verified"


# ─── 工具调用事件收集器（带上下文压缩）────────────────────────────────────────

class ToolCallCollector(ErrorLoopDetector, BaseCallbackHandler):
    """通过 LangChain astream_events 收集工具调用记录，并自动压缩上下文。

    继承 ErrorLoopDetector，防止 LLM 在错误上反复重试导致死循环。
    支持 LangChain 的 trim_messages 进行消息历史压缩。
    """

    def __init__(
        self,
        max_tool_results: int = _MAX_COMPRESSED_TOOL_RESULTS,
        compressed_chars: int = _COMPRESSED_RESULT_CHARS,
        max_history_tokens: int = _MAX_HISTORY_TOKENS,
    ):
        super().__init__()
        BaseCallbackHandler.__init__(self)
        self.tool_calls: list[dict] = []  # 压缩后的调用记录（用于上下文）
        self._raw_tool_calls: list[dict] = []  # 原始记录（用于审计）
        self.messages: list[BaseMessage] = []  # 对话历史
        self._in_tool = False
        self._current_tool_name = ""
        self._current_inputs: dict = {}
        self._current_output: str = ""
        # 压缩配置
        self._max_tool_results = max_tool_results
        self._compressed_chars = compressed_chars
        self._max_history_tokens = max_history_tokens

    def _compress_tool_result(self, raw_result: str, tool_name: str) -> str:
        """将工具结果压缩为摘要，减少上下文占用。"""
        if not raw_result:
            return "[空结果]"

        # 目录结构：压缩为统计摘要
        if tool_name == "get_file_tree":
            lines = [l for l in raw_result.strip().split('\n') if l.strip()]
            return f"[目录] {len(lines)} 个条目，顶级: {', '.join(l.split('/')[0] if '/' in l else l for l in lines[:3])}"

        # 代码搜索：压缩为匹配数
        if tool_name == "batch_search_code":
            # 提取匹配数量
            total_match = 0
            total_queries = 0
            try:
                import json
                data = json.loads(raw_result)
                for r in data:
                    total_match += len(r.get("results", []))
                    total_queries += 1
            except Exception:
                pass
            match = re.search(r'(\d+)\s*(?:match|result|matche?s?)', raw_result, re.I)
            count = str(total_match) if total_match else (match.group(1) if match else "?")
            # 提取前几个匹配的文件名
            file_matches = re.findall(r'[\w/.-]+\.(py|js|ts|tsx|jsx|go|java|rs)[^\n]*', raw_result)
            files = ", ".join(set(file_matches[:3])) if file_matches else ""
            return f"[批量搜索] {total_queries} 查询, ~{count} 处匹配{f' ({files})' if files else ''}"

        # 文件读取：保留前几行
        if tool_name in ("read_file_content", "get_file_blobs"):
            lines = raw_result.strip().split('\n')
            preview = '\n'.join(lines[:8])
            suffix = f"\n... ({len(lines)} 行)" if len(lines) > 8 else ""
            truncated = preview[:self._compressed_chars]
            return (truncated + "..." + suffix) if len(preview) > self._compressed_chars else truncated + suffix

        # AST 解析：只保留关键信息
        if tool_name in ("parse_file_ast", "detect_code_smells"):
            # 提取函数/类数量等关键统计
            func_count = len(re.findall(r'def\s+\w+', raw_result))
            class_count = len(re.findall(r'class\s+\w+', raw_result))
            return f"[分析] {func_count} 函数, {class_count} 类: {raw_result[:self._compressed_chars]}"

        # 默认截断
        return raw_result[:self._compressed_chars] + ("..." if len(raw_result) > self._compressed_chars else "")

    async def on_tool_start(
        self, serialized: dict, input: Any = "",
        *, run_id: str | None = None, parent_run_id: str | None = None, **kwargs
    ):
        name = serialized.get("name", "unknown")
        self._current_tool_name = name
        self._current_inputs = input if isinstance(input, dict) else {}
        self._in_tool = True
        self._current_output = ""

    async def on_tool_end(
        self, output: Any, *, run_id: str | None = None, parent_run_id: str | None = None, **kwargs
    ):
        if self._in_tool:
            # 提取原始结果
            if hasattr(output, "content"):
                raw_result = str(output.content)
            else:
                raw_result = str(output)

            # 保存原始记录（用于审计）
            self._raw_tool_calls.append({
                "iteration": len(self._raw_tool_calls) + 1,
                "tool": self._current_tool_name,
                "args": self._current_inputs,
                "raw_result": raw_result[:_TOOL_RESULT_TRUNCATE],
            })

            # 压缩结果用于上下文
            compressed_result = self._compress_tool_result(raw_result[:_TOOL_RESULT_TRUNCATE], self._current_tool_name)
            iteration = len(self.tool_calls) + 1
            self.tool_calls.append({
                "iteration": iteration,
                "tool": self._current_tool_name,
                "args": self._current_inputs,
                "result": compressed_result,
                "elapsed_ms": 0,
            })

            # 周期性压缩工具调用历史
            if len(self.tool_calls) > self._max_tool_results:
                self._trim_tool_calls()

            self._check_error_pattern(compressed_result, self._current_tool_name, self.tool_calls)
        self._in_tool = False

    def _trim_tool_calls(self):
        """压缩工具调用历史，只保留最近的调用。"""
        if len(self.tool_calls) > self._max_tool_results:
            # 生成历史摘要
            summary_parts = []
            for tc in self.tool_calls[:-self._max_tool_results]:
                summary_parts.append(f"[{tc['tool']}] {tc['result'][:80]}...")

            # 保留摘要记录
            summary = f"[早期探索摘要 ({len(self.tool_calls) - self._max_tool_results} 次调用)]: " + "; ".join(summary_parts)
            self.tool_calls = self.tool_calls[-self._max_tool_results:]
            # 将摘要作为最后一条记录（可被后续覆盖）
            logger.debug(f"压缩了 {len(summary_parts)} 条早期工具调用为摘要")

    async def on_tool_error(self, error: str, **kwargs):
        if self._in_tool:
            error_str = str(error)[:200]
            self.tool_calls.append({
                "iteration": len(self.tool_calls) + 1,
                "tool": self._current_tool_name,
                "args": self._current_inputs,
                "error": error_str,
                "result": "",
            })
            self._check_error_pattern(error_str, self._current_tool_name, self.tool_calls)
        self._in_tool = False

    async def on_chat_model_end(self, output, **kwargs):
        try:
            content = output.content if hasattr(output, 'content') else str(output)
            self.messages.append(AIMessage(content=content))

            # 使用 LangChain 的 trim_messages 压缩消息历史
            if len(self.messages) > 8:
                try:
                    self.messages = trim_messages(
                        self.messages,
                        strategy="last",
                        max_tokens=self._max_history_tokens,
                        token_counter=self._get_token_counter(),
                        include_system=False,
                    )
                except Exception as e:
                    # 如果 token 计数失败，回退到简单的数量限制
                    logger.debug(f"trim_messages 失败，回退到数量限制: {e}")
                    self.messages = self.messages[-8:]

        except Exception:
            pass

    def _get_token_counter(self):
        """获取 token 计数器（使用简单的字符估算）。"""
        # 简单估算：中文约 1.5 token/字符，英文约 4 token/字符，平均约 2.5 token/字符
        def simple_token_counter(messages: list[BaseMessage]) -> int:
            total = 0
            for msg in messages:
                content = getattr(msg, "content", "") or ""
                # 粗略估算
                total += len(content) // 2
            return total
        return simple_token_counter

    def get_compressed_context(self) -> str:
        """生成压缩后的上下文摘要，用于调试和日志。"""
        lines = [
            f"工具调用: {len(self.tool_calls)} 次",
            f"消息历史: {len(self.messages)} 条",
        ]
        for tc in self.tool_calls[-5:]:  # 最近 5 次
            lines.append(f"  [{tc['iteration']}] {tc['tool']}: {tc.get('result', tc.get('error', ''))[:60]}")
        return "\n".join(lines)



# ─── 基础 Explorer ─────────────────────────────────────────────────────────

class BaseExplorerAgent:
    """所有探索 Agent 的基类——基于 LangChain create_agent。

    利用 LangChain 的：
      - create_agent: 标准化的 ReAct Agent（底层是 LangGraph）
      - astream_events: 完整的事件流（工具调用、LLM 推理等）
      - StructuredTool: 统一的工具接口
    """

    max_iterations = _EXPLORER_MAX_ITERATIONS
    min_tool_calls = _EXPLORER_MIN_TOOL_CALLS

    # 子类覆盖
    system_prompt: str = ""
    agent_name: str = "Explorer"

    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self._agent_runnable: Runnable | None = None

    def _get_tools(self, owner: str, repo: str, branch: str, languages: list[str] | None = None) -> list[StructuredTool]:
        return _get_explorer_tools(owner, repo, branch, languages=languages)

    async def explore(
        self,
        owner: str,
        repo: str,
        branch: str = "main",
        file_contents: dict[str, str] | None = None,
        file_summaries: dict | None = None,
        languages: list[str] | None = None,
    ) -> ExplorerResult:
        """基于 LangChain create_agent 执行探索。

        Args:
            owner: 仓库所有者
            repo: 仓库名
            branch: 分支名
            file_contents: 原始文件内容（已废弃，优先使用 file_summaries）
            file_summaries: 提炼后的文件摘要（推荐，大幅减少 token）
            languages: GitHub API 返回的前 N 个语言，用于过滤 get_file_tree 结果
        """
        import time
        t0 = time.time()

        result = ExplorerResult(explorer_type=self.__class__.__name__)

        # 分支修正
        actual_branch = await self._resolve_branch(owner, repo, branch)
        if actual_branch and actual_branch != branch:
            logger.info(f"[{self.__class__.__name__}] 分支修正: {branch} -> {actual_branch}")
            branch = actual_branch

        try:
            # 构建任务上下文（优先使用提炼摘要）
            task_context = self._build_task_context(owner, repo, branch, file_contents, file_summaries)
            full_prompt = f"{self.system_prompt}\n\n{task_context}"

            # 获取工具（已注入 owner/repo/branch/languages，get_file_tree 结果会被过滤）
            tools = self._get_tools(owner, repo, branch, languages=languages)

            # 构建 Agent
            agent = create_agent(
                model=self.llm,
                tools=tools,
                system_prompt=full_prompt,
            )

            # 事件收集器
            collector = ToolCallCollector()

            # 运行 Agent 并收集结果
            # create_agent 返回 CompiledStateGraph，支持 ainvoke
            # 构建 Explorer 专用的 run_name，便于 LangSmith 追踪
            explorer_run_name_map = {
                "TechStackExplorer": "技术栈识别",
                "QualityExplorer": "代码质量分析",
                "ArchitectureExplorer": "架构模式探索",
            }
            explorer_run_name = explorer_run_name_map.get(
                self.__class__.__name__, self.agent_name
            )

            try:
                response = await agent.with_config(run_name=explorer_run_name).ainvoke(
                    {"messages": [HumanMessage(content=task_context)]},
                    config={"callbacks": [collector], "max_iterations": self.max_iterations},
                )
            except ToolLoopInterrupt as e:
                logger.warning(
                    f"[{self.__class__.__name__}] Agent 循环被打断（{e.tool_name} ×{e.count}），"
                    f"已完成 {len(collector.tool_calls)} 次工具调用"
                )
                result.tool_calls = collector.tool_calls
                result.findings = self._force_reduce_confidence(
                    result.findings,
                    f"因错误循环提前中断，已完成 {len(collector.tool_calls)} 次工具调用"
                )
                result.error = "explorer_stopped_due_to_error_loop"
                return result

            # 检查是否因迭代次数或错误循环而提前停止
            _stopped_early = False  # ainvoke 会内部处理迭代限制
            if collector._stop_due_to_loop:
                logger.warning(
                    f"[{self.__class__.__name__}] 因错误循环提前终止，"
                    f"已完成 {len(collector.tool_calls)} 次工具调用"
                )
                result.tool_calls = collector.tool_calls
                result.findings = self._force_reduce_confidence(
                    result.findings,
                    f"因错误循环提前终止，只完成 {len(collector.tool_calls)} 次工具调用"
                )
                result.error = "explorer_stopped_due_to_error_loop"

            # 解析最终消息（若未提前停止才执行）
            final_text = ""
            if not collector._stop_due_to_loop:
                final_messages = response.get("messages", [])
                for msg in reversed(final_messages):
                    content = getattr(msg, "content", None) or ""
                    if content and isinstance(content, str) and len(content) > 10:
                        final_text = content
                        break
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                final_text = block.get("text", "")
                                break

            result.reasoning = self._extract_reasoning(final_text)
            result.findings = self._extract_json(final_text)
            result.findings = self._anchor_evidence(result.findings, collector.tool_calls)
            result.tool_calls = collector.tool_calls

            # 如果没有收集到工具调用（LLM 直接返回了结论），强制要求
            if len(result.tool_calls) < self.min_tool_calls:
                logger.warning(
                    f"[{self.__class__.__name__}] 工具调用不足 "
                    f"({len(result.tool_calls)}/{self.min_tool_calls})，结论 confidence 降低"
                )
                result.findings = self._force_reduce_confidence(
                    result.findings,
                    f"工具调用不足，只完成 {len(result.tool_calls)}/{self.min_tool_calls}"
                )

        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] 探索异常: {e}", exc_info=True)
            result.error = str(e)

        result.duration_ms = (time.time() - t0) * 1000
        logger.info(
            f"[{self.__class__.__name__}] 完成: {result.duration_ms:.0f}ms, "
            f"tools={result.tool_call_count}, verification={result.verification_status}"
        )
        return result

    # Token 限制配置
    _MAX_CONTEXT_TOKENS = int(os.getenv("EXPLORER_MAX_CONTEXT_TOKENS", "4000"))
    _MAX_SUMMARY_ITEMS = int(os.getenv("EXPLORER_MAX_SUMMARY_ITEMS", "20"))
    _MAX_CONTEXT_CHARS = int(os.getenv("EXPLORER_MAX_CONTEXT_CHARS", "8000"))  # 硬截断字符数

    def _build_task_context(
        self, owner: str, repo: str, branch: str,
        file_contents: dict[str, str] | None = None,
        file_summaries: dict | None = None,
    ) -> str:
        """构建任务上下文。

        优先使用 file_summaries（提炼后的结构化摘要），
        如果没有则使用 file_contents（原始文件内容，已废弃）。
        包含硬字符截断，防止超出 LLM 上下文窗口。
        """
        parts = [f"## 探索任务\n仓库: {owner}/{repo}@{branch}\n"]

        # ── 优先使用提炼后的摘要 ──────────────────────────────────────────────
        if file_summaries and len(file_summaries) > 0:
            # Token 限制：只保留最重要的文件
            max_items = self._MAX_SUMMARY_ITEMS
            if len(file_summaries) > max_items:
                # 按复杂度排序，优先保留高复杂度文件
                def get_complexity_score(s) -> int:
                    comp = getattr(s, "complexity", "low")
                    if comp == "high":
                        return 3
                    elif comp == "medium":
                        return 2
                    else:
                        return 1

                sorted_summaries = sorted(
                    file_summaries.items(),
                    key=lambda x: get_complexity_score(x[1]),
                    reverse=True
                )
                file_summaries = dict(sorted_summaries[:max_items])
                parts.append(
                    f"\n⚠️ **文件较多（{len(file_summaries)} 个），已筛选最复杂的 {max_items} 个进行分析**\n"
                )

            parts.append(f"\n## 文件摘要（共 {len(file_summaries)} 个，已提炼）\n")
            parts.append(
                "ℹ️ 以下是每个文件的**提炼摘要**，包含结构信息但不包含完整代码。\n\n"
            )

            # 按用途分组展示
            by_purpose: dict[str, list] = {}
            for path, summary in file_summaries.items():
                purpose = getattr(summary, "purpose", "unknown")
                if purpose not in by_purpose:
                    by_purpose[purpose] = []
                by_purpose[purpose].append(summary)

            # 展示摘要（精简版）
            for purpose in ["main", "config", "api", "service", "model", "test", "util", "middleware", "unknown"]:
                if purpose in by_purpose:
                    parts.append(f"### {purpose.upper()} ({len(by_purpose[purpose])} 个)\n")
                    for summary in by_purpose[purpose][:5]:  # 每个分类最多 5 个
                        path = getattr(summary, "path", "unknown")
                        lang = getattr(summary, "language", "?")
                        lines = getattr(summary, "lines", 0)
                        complexity = getattr(summary, "complexity", "?")
                        classes = getattr(summary, "classes", [])
                        functions = getattr(summary, "functions", [])
                        imports = getattr(summary, "imports", [])
                        insight = getattr(summary, "key_insight", "")

                        parts.append(f"**{path}** ({lang}, {lines}行)\n")
                        if classes:
                            parts.append(f"  类: {', '.join(classes[:3])}\n")
                        if functions:
                            parts.append(f"  函数: {', '.join(functions[:5])}\n")
                        if insight:
                            parts.append(f"  {insight}\n")
                    if len(by_purpose[purpose]) > 5:
                        parts.append(f"  ... 等共 {len(by_purpose[purpose])} 个\n")
                    parts.append("\n")

            # 检查是否有配置文件已加载
            config_files = ["requirements.txt", "pyproject.toml", "package.json", "package-lock.json", "go.mod", "Gemfile", "Cargo.toml"]
            has_config = any(
                any(cfg in path for cfg in config_files)
                for path in file_summaries.keys()
            )

            if has_config:
                parts.append(
                    "\n✅ **配置文件已加载**：可直接从文件摘要中提取依赖信息，无需重复读取。\n"
                )

            parts.append(
                "\n📌 **高效行动指南**：\n"
                "1. **直接分析**：基于文件摘要中的 imports 字段提取依赖信息\n"
                "2. **快速验证**：如需代码证据，用 batch_search_code 批量搜索关键词\n"
                f"3. **精简工具调用**：目标 1-2 次工具调用即可给出结论\n"
            )

        # ── 回退：使用原始文件内容（已废弃）───────────────────────────────────
        elif file_contents and len(file_contents) > 0:
            parts.append(f"\n## 文件列表（{len(file_contents)} 个）\n")
            parts.append(
                "⚠️ 以下仅列出文件路径，请通过工具调用读取完整内容进行验证。\n\n"
            )

            by_dir: dict[str, list[str]] = {}
            for p in sorted(file_contents.keys()):
                parts_list = p.split("/")
                dir_name = parts_list[0] if len(parts_list) > 1 else "."
                if dir_name not in by_dir:
                    by_dir[dir_name] = []
                by_dir[dir_name].append(parts_list[-1])

            for dir_name in sorted(by_dir.keys()):
                files = by_dir[dir_name]
                parts.append(f"### {dir_name}/\n")
                for f in sorted(files):
                    parts.append(f"- {f}\n")
                parts.append("\n")

            parts.append(
                "\n📌 **行动指南**：\n"
                "1. 基于文件路径，识别可能的技术方向\n"
                "2. 用 batch_search_code 验证猜测\n"
                f"3. **get_file_tree 已无需调用（系统已过滤低价值目录）**\n"
                f"4. 至少完成 {self.min_tool_calls} 次工具调用\n"
            )
        else:
            parts.append(
                "\n📌 **行动指南**：\n"
                "1. 用 batch_search_code 验证猜测\n"
                f"2. 至少完成 {self.min_tool_calls} 次工具调用\n"
            )

        result = "".join(parts)
        # 硬截断：防止上下文超长导致 400 错误
        if len(result) > self._MAX_CONTEXT_CHARS:
            logger.warning(
                f"[{self.__class__.__name__}] 上下文过长 ({len(result)} chars)，"
                f"截断至 {self._MAX_CONTEXT_CHARS} chars"
            )
            result = result[:self._MAX_CONTEXT_CHARS] + "\n\n[⚠️ 上下文已截断]"
        return result

    def _extract_reasoning(self, text: str) -> str:
        patterns = [
            r"##\s*推理过程\s*([\s\S]+?)(?=```json|$)",
            r"##\s*Reasoning\s*([\s\S]+?)(?=```json|$)",
            r"##\s*分析\s*([\s\S]+?)(?=```json|$)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    def _extract_json(self, text: str) -> dict:
        text = text.strip()
        if text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass

        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return {}

    def _anchor_evidence(self, findings: dict, tool_calls_log: list[dict]) -> dict:
        """证据锚定验证。"""
        if not tool_calls_log:
            return self._force_reduce_confidence(findings, "没有任何工具调用验证")

        tool_results: dict[str, list[str]] = {}
        for tc in tool_calls_log:
            tool_name = tc.get("tool", "")
            result_preview = tc.get("result", "")[:200]
            if tool_name not in tool_results:
                tool_results[tool_name] = []
            tool_results[tool_name].append(result_preview)

        # 检查 frameworks
        if "frameworks" in findings and isinstance(findings["frameworks"], list):
            for fw in findings["frameworks"]:
                if not isinstance(fw, dict):
                    continue
                evidence = fw.get("evidence", [])
                if not evidence:
                    continue
                verified, unverified = [], []
                for e in evidence:
                    if isinstance(e, str) and self._verify_evidence(e, tool_results):
                        verified.append(e)
                    else:
                        unverified.append(e)

                if unverified and not verified:
                    fw["confidence"] = round(fw.get("confidence", 1.0) * 0.3, 2)
                    fw["status"] = "unverified"
                    fw["unverified_evidence"] = unverified
                elif unverified:
                    fw["status"] = "partially_verified"
                    fw["unverified_evidence"] = unverified

        if findings.get("overall_confidence") and len(tool_calls_log) < _EXPLORER_MIN_TOOL_CALLS:
            findings["overall_confidence"] = round(
                findings.get("overall_confidence", 1.0) * 0.5, 2
            )
            findings["verification_warning"] = (
                f"只完成了 {len(tool_calls_log)}/{_EXPLORER_MIN_TOOL_CALLS} 次工具调用"
            )

        return findings

    def _verify_evidence(self, evidence: str, tool_results: dict[str, list[str]]) -> bool:
        if not evidence or not tool_results:
            return False
        evidence_lower = evidence.lower()
        for results in tool_results.values():
            for result in results:
                if self._evidence_matches_result(evidence, result):
                    return True
        return False

    def _evidence_matches_result(self, evidence: str, result: str) -> bool:
        markers = []
        if "'" in evidence or '"' in evidence:
            quoted = re.findall(r"['\"]([^'\"]+)['\"]", evidence)
            markers.extend([m.lower() for m in quoted])
        if " in " in evidence.lower():
            match = re.search(r"in\s+([^\s,:\]]+)", evidence, re.IGNORECASE)
            if match:
                markers.append(match.group(1).lower())
        for marker in markers:
            if marker and len(marker) > 2:
                if marker in result.lower():
                    return True
        return False

    def _force_reduce_confidence(self, findings: dict, reason: str) -> dict:
        findings["verification_warning"] = reason
        if "frameworks" in findings and isinstance(findings["frameworks"], list):
            for fw in findings["frameworks"]:
                if isinstance(fw, dict):
                    fw["confidence"] = round(fw.get("confidence", 1.0) * 0.3, 2)
                    fw["status"] = "unverified"
        if "confidence" in findings:
            findings["confidence"] = round(findings.get("confidence", 1.0) * 0.3, 2)
        if "overall_confidence" in findings:
            findings["overall_confidence"] = round(
                findings.get("overall_confidence", 1.0) * 0.3, 2
            )
        return findings

    async def _resolve_branch(self, owner: str, repo: str, branch: str) -> str:
        if branch not in ("main", ""):
            return branch
        try:
            from tools.github_tools import _get_default_branch_impl
            result = await _get_default_branch_impl(owner, repo)
            return result if result else "main"
        except Exception as e:
            logger.warning(f"[{self.__class__.__name__}] 获取默认分支失败: {e}")
            return "main"


# ─── 具体 Explorer ───────────────────────────────────────────────────────────

class TechStackExplorer(BaseExplorerAgent):
    def __init__(self, llm: BaseChatModel):
        super().__init__(llm)
        self.system_prompt = _TECH_STACK_EXPLORER_INSTRUCTIONS
        self.agent_name = "技术栈识别"


class QualityExplorer(BaseExplorerAgent):
    def __init__(self, llm: BaseChatModel):
        super().__init__(llm)
        self.system_prompt = _QUALITY_EXPLORER_INSTRUCTIONS
        self.agent_name = "代码质量探索"


class ArchitectureExplorer(BaseExplorerAgent):
    def __init__(self, llm: BaseChatModel):
        super().__init__(llm)
        self.system_prompt = _ARCHITECTURE_EXPLORER_INSTRUCTIONS
        self.agent_name = "架构模式探索"


# ─── 编排器 ────────────────────────────────────────────────────────────────

class ExplorerOrchestrator:
    """并行探索编排器。

    使用 LangChain create_agent 并行运行多个 Explorer。
    """

    def __init__(self):
        from utils.llm_factory import get_llm_with_tracking
        self.llm = get_llm_with_tracking(agent_name="Explorer", max_tokens=_MAX_OUTPUT_TOKENS)
        if self.llm is None:
            raise RuntimeError("LLM 不可用，请确保 OPENAI_API_KEY 或 ANTHROPIC_API_KEY 已配置。")

    async def explore_all(
        self,
        owner: str,
        repo: str,
        branch: str = "main",
        file_contents: dict[str, str] | None = None,
        file_summaries: dict | None = None,
        languages: list[str] | None = None,
    ) -> dict[str, dict]:
        """并行运行所有 Explorer。

        Args:
            owner: 仓库所有者
            repo: 仓库名
            branch: 分支名
            file_contents: 原始文件内容（已废弃）
            file_summaries: 提炼后的文件摘要（推荐，大幅减少 token）
            languages: GitHub API 返回的前 N 个语言，用于过滤 get_file_tree 结果
        """
        logger.info(f"[ExplorerOrchestrator] 开始并行探索: {owner}/{repo}, summaries={len(file_summaries) if file_summaries else 0}, languages={languages}")

        explorers = [
            TechStackExplorer(self.llm),
            QualityExplorer(self.llm),
            ArchitectureExplorer(self.llm),
        ]

        tasks = [
            _safe_explore(explorer, owner, repo, branch, file_contents, file_summaries, languages)
            for explorer in explorers
        ]

        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for explorer, outcome in zip(explorers, outcomes):
            name = explorer.__class__.__name__
            if isinstance(outcome, Exception):
                logger.error(f"[{name}] 异常: {outcome}")
                output[name] = {"error": str(outcome)}
            else:
                result: ExplorerResult = outcome
                output[name] = {
                    **result.findings,
                    "_reasoning": result.reasoning,
                    "_meta": {
                        "duration_ms": round(result.duration_ms, 1),
                        "error": result.error,
                        "tool_calls": result.tool_calls,
                        "tool_call_count": result.tool_call_count,
                        "verification_status": result.verification_status,
                        "min_tool_calls_required": _EXPLORER_MIN_TOOL_CALLS,
                    },
                }

        logger.info(f"[ExplorerOrchestrator] 全部探索完成: {list(output.keys())}")
        return output


async def _safe_explore(
    explorer: BaseExplorerAgent,
    owner: str, repo: str, branch: str,
    file_contents: dict[str, str] | None,
    file_summaries: dict | None,
    languages: list[str] | None,
) -> ExplorerResult:
    """执行单个 Explorer，捕获所有异常确保 orchestrator 不崩溃。"""
    try:
        return await explorer.explore(owner, repo, branch, file_contents, file_summaries, languages=languages)
    except Exception as e:
        logger.error(f"[{explorer.__class__.__name__}] explore 异常: {e}", exc_info=True)
        return ExplorerResult(explorer_type=explorer.__class__.__name__, error=str(e))
