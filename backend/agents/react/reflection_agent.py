"""
ReActReflectionAgent — 基于 ReAct 模式的自我反思 Agent。

核心职责：
  - 审视并验证其他 Agent 的产出（loader / explorer / architecture / suggestion）
  - 识别分析过程中的遗漏和误判
  - 生成改进建议并评估置信度
  - 决定是否需要重新执行某个 Agent

反思维度：
  1. 完整性：是否遗漏了重要的代码部分？
  2. 准确性：分析结论是否有依据？还是过度推断？
  3. 可执行性：建议是否具体可执行？还是泛泛而谈？
  4. 风险识别：是否存在误判的可能？如何验证？

基于 LangChain create_agent 实现：
  - create_agent: 标准化的 ReAct Agent（LangGraph StateGraph）
  - ainvoke: 单次执行，避免 astream_events + ainvoke 双重执行问题
  - Agent callbacks: 自动收集工具调用记录

用法：
    agent = ReActReflectionAgent()
    async for event in agent.reflect(
        analysis_type="explorer",
        analysis_result=explorer_result,
        context={"loaded_paths": [...], "file_contents": {...}}
    ):
        print(event)
"""
import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Annotated, Any, AsyncGenerator, Optional

from langchain.agents import create_agent, AgentState
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage, BaseMessage, trim_messages

from agents.react.error_loop_detector import ErrorLoopDetector
from agents.react.tool_wrapper import ToolLoopInterrupt,inject_context
from tools.github_tools import batch_search_code
from tools.code_tools import parse_file_ast, detect_code_smells

logger = logging.getLogger("gitintel")

# ── Token 预算配置 ────────────────────────────────────────────────────────────

_MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "2048"))
_REFLECTION_MAX_ITERATIONS = int(os.getenv("REFLECTION_MAX_ITERATIONS", "4"))
_TOOL_RESULT_TRUNCATE = int(os.getenv("TOOL_RESULT_TRUNCATE", "1500"))

# ─── 上下文压缩配置 ───────────────────────────────────────────────────────────
_MAX_COMPRESSED_RESULTS = int(os.getenv("REFLECTION_MAX_COMPRESSED_RESULTS", "6"))
_COMPRESSED_RESULT_CHARS = int(os.getenv("REFLECTION_COMPRESSED_CHARS", "400"))
_MAX_HISTORY_TOKENS = int(os.getenv("REFLECTION_MAX_HISTORY_TOKENS", "6000"))


# ─── 工具列表 ────────────────────────────────────────────────────────────────

# 原始工具列表（用于类型标注）
_RAW_TOOLS = [
    batch_search_code,
    parse_file_ast,
    detect_code_smells,
]


def _get_wrapped_tools(owner: str, repo: str, ref: str) -> list:
    """获取包装后的工具列表，自动注入 owner/repo/ref 上下文。"""
    return [inject_context(t, owner=owner, repo=repo, ref=ref) for t in _RAW_TOOLS]


# ─── System Prompt ─────────────────────────────────────────────────────────────

REFLECTION_SYSTEM_PROMPT = """## 角色
你是 GitIntel 系统的分析质量审查 Agent，负责审视并验证其他 Agent 的产出。

【重要】你的反思质量直接影响最终分析报告的可靠性。
不严谨的反思比没有反思更有害——它会错误地增强对错误结论的信心。

## 核心职责
1. **审视现有分析**：检查其他 Agent 生成的结论是否完整、准确、有据可依
2. **识别遗漏**：发现分析过程中可能被忽视的重要代码或问题
3. **验证结论**：通过已有上下文中的文件内容验证 Agent 声称的证据是否真实存在
4. **量化置信度**：给出每个结论的置信度评分和理由
5. **提出改进建议**：如果发现问题，明确指出应该如何改进

## 反思框架
请从以下四个维度审视分析结果：

### 1. 完整性检查 (Completeness)
- 分析是否涵盖了仓库的主要模块？
- 是否遗漏了关键的入口文件或核心业务逻辑？
- 依赖声明与实际使用是否一致？

### 2. 准确性检查 (Accuracy)
- 识别的技术栈/框架是否有代码证据支撑？
- 声称的问题位置 (file:line) 是否真实存在？
- 架构推断是否有目录结构或 import 关系证据？

### 3. 可执行性检查 (Actionability)
- 建议是否有具体的文件路径和行号？
- code_fix 是否可以直接执行？

### 4. 风险检查 (Risk Assessment)
- 是否有潜在误判的风险？
- 建议的修改是否可能引入新问题？

## 上下文使用指南
仓库信息和文件树【已在上下文中直接提供】，无需通过工具调用获取：

- **仓库基本信息**：在上下文的"仓库信息"部分，包含 owner/repo、分支、语言统计等
- **文件树结构**：在上下文的"目录结构"部分，已列出关键文件和目录
- **文件内容**：在上下文的"已加载文件内容"部分，可直接用于验证分析结论

## 验证策略
1. 先理解被审查分析的结论和关键主张
2. 在上下文中的文件内容里验证关键结论的证据
3. 根据验证结果，评估结论的置信度
4. 随时评估是否已完成足够的验证，够了就输出结论

## 输出格式
必须输出严格遵循以下 JSON 格式的结论：
```json
{
  "analysis_type": "被反思的分析类型：loader|explorer|architecture|suggestion",
  "overall_confidence": 0.0-1.0,
  "confidence_level": "high|medium|low",
  "completeness": {
    "score": 0.0-1.0,
    "issues": ["遗漏问题1", "遗漏问题2"],
    "is_complete": true|false
  },
  "accuracy": {
    "score": 0.0-1.0,
    "verified_claims": ["已验证的正确结论1", "已验证的正确结论2"],
    "unverified_claims": ["未验证的结论1（缺少证据）", "结论2（可能误判）"],
    "is_accurate": true|false
  },
  "actionability": {
    "score": 0.0-1.0,
    "actionable_suggestions": ["可执行的建议1", "可执行的建议2"],
    "vague_suggestions": ["泛泛而谈的建议1", "缺乏具体操作的建议2"],
    "is_actionable": true|false
  },
  "risk_assessment": {
    "score": 0.0-1.0,
    "risks": ["潜在风险1", "风险2"],
    "is_safe": true|false
  },
  "reflection_summary": "总结性反思结论，2-3 句话",
  "improvement_suggestions": [
    {
      "area": "completeness|accuracy|actionability|risk",
      "issue": "具体问题描述",
      "suggestion": "应该如何改进",
      "priority": "high|medium|low"
    }
  ],
  "verification_log": [
    {
      "method": "上下文验证|代码片段验证",
      "target": "验证目标",
      "finding": "验证结果",
      "confidence_impact": "positive|neutral|negative"
    }
  ],
  "needs_retry": true|false,
  "retry_reason": "如果 needs_retry=true，说明原因"
}
```

## 硬性约束
- 每个结论必须有证据支撑，无证据的结论降低 confidence 或标注 unverified
- 如果某项确实无法判断，标注 unknown 而非猜测
- 避免过度反思，不要为了体现反思而创造不存在的问题
- overall_confidence 必须是 0.0-1.0 的数字，不能省略或模糊

## 重要：利用上下文进行验证
- 仓库信息和文件树已在上下文中提供，【不要】调用工具获取
- 上下文中的文件内容已预处理，可以直接用于验证分析结论
- 如果上下文中的信息足以验证结论，就不要调用工具
- 过度依赖工具调用会导致验证效率低下，浪费 token"""


# ─── 数据结构 ────────────────────────────────────────────────────────────────

@dataclass
class ReflectionResult:
    """反思结果"""
    analysis_type: str
    overall_confidence: float
    confidence_level: str  # high / medium / low

    # 四维度评估
    completeness: dict
    accuracy: dict
    actionability: dict
    risk_assessment: dict

    # 总结
    reflection_summary: str
    improvement_suggestions: list[dict]
    verification_log: list[dict]

    # 决策
    needs_retry: bool
    retry_reason: str

    # 元数据
    tool_calls: list[dict] = field(default_factory=list)
    reasoning: str = ""
    duration_ms: float = 0.0

    @property
    def confidence_percentage(self) -> str:
        return f"{self.overall_confidence * 100:.0f}%"


# ─── LangChain Callback Handler（带上下文压缩）──────────────────────────────────

class ReflectionCallbackHandler(ErrorLoopDetector, AsyncCallbackHandler):
    """通过 LangChain Agent callbacks 自动收集工具调用记录，并自动压缩上下文。

    包含错误循环检测，防止 LLM 在错误上反复重试导致死循环。
    支持 LangChain 的 trim_messages 进行消息历史压缩。
    """

    MAX_CONSECUTIVE_SAME_ERRORS = 3

    def __init__(
        self,
        max_results: int = _MAX_COMPRESSED_RESULTS,
        compressed_chars: int = _COMPRESSED_RESULT_CHARS,
        max_history_tokens: int = _MAX_HISTORY_TOKENS,
    ):
        ErrorLoopDetector.__init__(self)
        AsyncCallbackHandler.__init__(self)
        self.tool_calls: list[dict] = []  # 压缩后的调用记录
        self._raw_tool_calls: list[dict] = []  # 原始记录（用于审计）
        self.messages: list[BaseMessage] = []  # 对话历史
        self.progress_events: list[dict] = []  # 累积进度事件
        self._in_tool = False
        self._current_tool_name = ""
        self._current_inputs: dict = {}
        # 压缩配置
        self._max_results = max_results
        self._compressed_chars = compressed_chars
        self._max_history_tokens = max_history_tokens

    def _compress_tool_result(self, raw_result: str, tool_name: str) -> str:
        """将工具结果压缩为摘要，减少上下文占用。"""
        if not raw_result:
            return "[空结果]"

        # 代码搜索：压缩为匹配数
        if tool_name == "batch_search_code":
            import json
            try:
                data = json.loads(raw_result)
                total = sum(len(r.get("results", [])) for r in data)
                return f"[批量搜索] {len(data)} 个查询, ~{total} 处匹配"
            except Exception:
                pass
            return f"[批量搜索] ~? 处匹配"

        # AST 解析：只保留关键统计
        if tool_name in ("parse_file_ast", "detect_code_smells"):
            func_count = len(re.findall(r'def\s+\w+', raw_result))
            class_count = len(re.findall(r'class\s+\w+', raw_result))
            return f"[分析] {func_count} 函数, {class_count} 类"

        # 默认截断
        return raw_result[:self._compressed_chars] + ("..." if len(raw_result) > self._compressed_chars else "")

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
            # 提取原始结果
            raw_result = str(output.content)[:_TOOL_RESULT_TRUNCATE] if hasattr(output, "content") else str(output)[:_TOOL_RESULT_TRUNCATE]
            tool_call_count = len(self.tool_calls) + 1

            # 保存原始记录（用于审计）
            self._raw_tool_calls.append({
                "iteration": tool_call_count,
                "tool": self._current_tool_name,
                "args": dict(self._current_inputs),
                "raw_result": raw_result,
            })

            # 压缩结果用于上下文
            compressed_result = self._compress_tool_result(raw_result, self._current_tool_name)
            self.tool_calls.append({
                "iteration": tool_call_count,
                "tool": self._current_tool_name,
                "args": dict(self._current_inputs),
                "result": compressed_result,
            })

            # 周期性压缩工具调用历史
            if len(self.tool_calls) > self._max_results:
                self._trim_tool_calls()

            self._check_error_pattern(compressed_result, self._current_tool_name)

            # 累积进度事件
            self.progress_events.append({
                "type": "progress",
                "agent": "reflection",
                "message": f"[反思验证] {self._current_tool_name}: {compressed_result[:80]}",
                "percent": min(15 + tool_call_count * 10, 60),
                "data": {"tool": self._current_tool_name, "finding": compressed_result[:150], "iteration": tool_call_count},
            })

        self._in_tool = False

    def _trim_tool_calls(self):
        """压缩工具调用历史，只保留最近的调用。"""
        if len(self.tool_calls) > self._max_results:
            logger.debug(f"压缩反思工具调用历史: {len(self.tool_calls)} -> {self._max_results}")
            self.tool_calls = self.tool_calls[-self._max_results:]

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
                "agent": "reflection",
                "message": f"[反思错误] {self._current_tool_name}: {error_str}",
                "percent": min(15 + tool_call_count * 10, 60),
                "data": {"tool": self._current_tool_name, "error": error_str, "iteration": tool_call_count},
            })

        self._in_tool = False

    async def on_chat_model_end(self, output, **kwargs):
        """在 LLM 输出后自动压缩消息历史。"""
        try:
            content = output.content if hasattr(output, 'content') else str(output)
            self.messages.append(AIMessage(content=content))

            # 使用 LangChain 的 trim_messages 压缩消息历史
            if len(self.messages) > 6:
                try:
                    self.messages = trim_messages(
                        self.messages,
                        strategy="last",
                        max_tokens=self._max_history_tokens,
                        token_counter=self._get_token_counter(),
                        include_system=False,
                    )
                except Exception as e:
                    logger.debug(f"trim_messages 失败，回退到数量限制: {e}")
                    self.messages = self.messages[-6:]

        except Exception:
            pass

    def _get_token_counter(self):
        """获取 token 计数器（使用简单的字符估算）。"""
        def simple_token_counter(messages: list[BaseMessage]) -> int:
            total = 0
            for msg in messages:
                content = getattr(msg, "content", "") or ""
                total += len(content) // 2
            return total
        return simple_token_counter


# ─── 核心 Agent ──────────────────────────────────────────────────────────────

class ReActReflectionAgent:
    """基于 ReAct 模式的自我反思 Agent。

    特性：
      - LangChain create_agent：标准化的 ReAct StateGraph，自动管理 Agent 循环
      - ainvoke 单次执行：避免 astream_events + ainvoke 双重执行的复杂性
      - 深度审视：检查其他 Agent 的分析是否完整、准确、可执行
      - 工具验证：通过实际工具调用验证声称的证据
      - 量化置信度：给出每个结论的可信度评分
      - 改进建议：明确指出应该如何改进分析质量

    使用示例：
        agent = ReActReflectionAgent()
        async for event in agent.reflect(
            analysis_type="suggestion",
            analysis_result=suggestion_result,
            context={"file_contents": {...}}
        ):
            print(event)
    """

    MAX_TOOL_CALLS = _REFLECTION_MAX_ITERATIONS  # 重命名：正确表达限制的是 tool_call 次数

    def __init__(self):
        self._llm: BaseChatModel | None = self._get_llm()
        self._file_contents: dict[str, str] | None = None

    @staticmethod
    def _get_llm() -> BaseChatModel | None:
        try:
            from utils.llm_factory import get_llm_with_tracking
            return get_llm_with_tracking(agent_name="反思审查", max_tokens=_MAX_OUTPUT_TOKENS)
        except ImportError:
            logger.warning("[ReActReflection] 无法导入 llm_factory")
            return None

    async def reflect(
        self,
        analysis_type: str,
        analysis_result: dict,
        context: dict | None = None,
        owner: str = "",
        repo: str = "",
        ref: str = "main",
    ) -> AsyncGenerator[dict, None]:
        """执行反思流程（使用 ainvoke 单次执行）。

        Args:
            analysis_type: 被反思的分析类型 (loader / explorer / architecture / suggestion)
            analysis_result: 被反思的 Agent 结果
            context: 额外的上下文信息 (file_contents, loaded_paths 等)

        Yields:
            SSE 事件，包含反思进度和最终结果
        """
        self._file_contents = context.get("file_contents") if context else None

        # ── Step 1: 初始化 ─────────────────────────────────────────────
        yield {
            "type": "status",
            "agent": "reflection",
            "message": f"开始反思审查: {analysis_type}",
            "percent": 5,
            "data": {"analysis_type": analysis_type},
        }

        if self._llm is None:
            yield {
                "type": "error",
                "agent": "reflection",
                "message": "LLM 不可用，无法执行反思",
                "percent": 0,
                "data": None,
            }
            return

        # ── Step 2: 获取 repo_info 和 file_tree（直接从上下文传入，不走工具调用）──
        repo_info = {}
        file_tree = []
        if context:
            repo_info = context.get("repo_info", {})
            file_tree = context.get("file_tree", [])

        # ── Step 3: 构建反思上下文 ─────────────────────────────────────
        reflection_context = self._build_reflection_context(
            analysis_type, analysis_result, context,
            repo_info=repo_info, file_tree=file_tree,
        )

        yield {
            "type": "progress",
            "agent": "reflection",
            "message": "正在构建反思上下文...",
            "percent": 10,
            "data": None,
        }

        # ── Step 4: 使用 ainvoke 执行 ReAct 反思循环（单次执行，无双重调用）──────────
        verification_log: list[dict] = []
        handler = ReflectionCallbackHandler()

        # 使用包装后的工具，自动注入 owner/repo/ref 上下文
        wrapped_tools = _get_wrapped_tools(owner, repo, ref)
        agent = create_agent(
            model=self._llm,
            tools=wrapped_tools,
            system_prompt=REFLECTION_SYSTEM_PROMPT,
        )

        input_state: AgentState = {
            "messages": [
                HumanMessage(content=reflection_context),
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
                "agent": "reflection",
                "message": "Agent 正在执行（单次 ainvoke）...",
                "percent": 15,
                "data": None,
            }

            final_state = await agent.with_config(run_name="反思审查").ainvoke(
                input_state,
                config={
                    "callbacks": [handler],
                    "max_iterations": self.MAX_TOOL_CALLS,
                },
            )
            final_messages = final_state.get("messages", [])

            # 从回调中获取所有工具调用记录
            all_tool_calls = handler.tool_calls

            logger.info(
                f"[ReActReflection] create_agent 完成: "
                f"{len(all_tool_calls)} 次工具调用"
            )

            # ── 统一 yield 所有进度事件 ─────────────────────────────────────────
            for progress_event in handler.progress_events:
                yield progress_event

            # 构建 verification_log
            verification_log = [
                {
                    "iteration": tc.get("iteration", i + 1),
                    "tool": tc.get("tool", ""),
                    "args": tc.get("args", {}),
                    "finding": tc.get("result", ""),
                    "confidence_impact": "neutral",
                }
                for i, tc in enumerate(all_tool_calls)
            ]

            # 检查是否因错误循环提前停止
            if handler._stop_due_to_loop:
                logger.warning(
                    f"[ReActReflection] 因错误循环提前终止，"
                    f"已完成 {len(all_tool_calls)} 次工具调用"
                )
                yield {
                    "type": "progress",
                    "agent": "reflection",
                    "message": f"因错误循环提前终止，已完成 {len(all_tool_calls)} 次工具调用",
                    "percent": 65,
                    "data": {"stopped_due_to_loop": True, "tool_call_count": len(all_tool_calls)},
                }

        except ToolLoopInterrupt as e:
            logger.warning(
                f"[ReActReflection] Agent 循环被打断（{e.tool_name} ×{e.count}），"
                f"已完成 {len(handler.tool_calls)} 次工具调用"
            )
            yield {
                "type": "progress",
                "agent": "reflection",
                "message": f"Agent 循环被打断（{e.tool_name} ×{e.count}），已完成 {len(handler.tool_calls)} 次工具调用",
                "percent": 75,
                "data": {"stopped_due_to_loop": True, "tool_call_count": len(handler.tool_calls)},
            }
            final_messages = []
            verification_log = [
                {
                    "iteration": tc.get("iteration", i + 1),
                    "tool": tc.get("tool", ""),
                    "args": tc.get("args", {}),
                    "finding": tc.get("result", tc.get("error", "")),
                    "confidence_impact": "neutral",
                }
                for i, tc in enumerate(handler.tool_calls)
            ]

        except Exception as e:
            logger.error(f"[ReActReflection] create_agent 执行失败: {e}", exc_info=True)
            final_messages = []
            verification_log = [
                {
                    "iteration": tc.get("iteration", i + 1),
                    "tool": tc.get("tool", ""),
                    "args": tc.get("args", {}),
                    "finding": tc.get("result", tc.get("error", "")),
                    "confidence_impact": "neutral",
                }
                for i, tc in enumerate(handler.tool_calls)
            ]

        # ── Step 5: 生成最终反思结论 ────────────────────────────────
        yield {
            "type": "progress",
            "agent": "reflection",
            "message": "正在生成反思结论...",
            "percent": 75,
            "data": None,
        }

        final_prompt = self._build_final_prompt(analysis_type, verification_log)
        messages_for_final = list(final_messages)
        messages_for_final.append(HumanMessage(content=final_prompt))

        try:
            final_response = await self._llm.ainvoke(messages_for_final)
            content = final_response.content.strip()

            # 提取推理过程
            reasoning = self._extract_reasoning(content)

            # 解析反思 JSON
            reflection_data = self._parse_reflection_json(content)

        except Exception as e:
            logger.error(f"[ReActReflection] 最终反思生成失败: {e}")
            reflection_data = self._generate_fallback_reflection(analysis_type, analysis_result)

        # ── Step 6: 评估是否需要重试 ────────────────────────────────
        needs_retry = reflection_data.get("needs_retry", False)
        retry_reason = reflection_data.get("retry_reason", "")

        if needs_retry:
            yield {
                "type": "progress",
                "agent": "reflection",
                "message": f"反思建议重试: {retry_reason}",
                "percent": 85,
                "data": {"needs_retry": True, "reason": retry_reason},
            }
        else:
            yield {
                "type": "progress",
                "agent": "reflection",
                "message": "分析质量评估完成",
                "percent": 90,
                "data": {"needs_retry": False},
            }

        # ── Step 7: 输出最终结果 ────────────────────────────────────
        yield {
            "type": "result",
            "agent": "reflection",
            "message": f"反思完成: 置信度 {reflection_data.get('overall_confidence', 0) * 100:.0f}%",
            "percent": 100,
            "data": {
                "analysis_type": analysis_type,
                "overall_confidence": reflection_data.get("overall_confidence", 0.5),
                "confidence_level": reflection_data.get("confidence_level", "medium"),
                "completeness": reflection_data.get("completeness", {}),
                "accuracy": reflection_data.get("accuracy", {}),
                "actionability": reflection_data.get("actionability", {}),
                "risk_assessment": reflection_data.get("risk_assessment", {}),
                "reflection_summary": reflection_data.get("reflection_summary", ""),
                "improvement_suggestions": reflection_data.get("improvement_suggestions", []),
                "verification_log": verification_log,
                "needs_retry": needs_retry,
                "retry_reason": retry_reason,
                "tool_calls": verification_log,
            },
        }

    def _build_reflection_context(
        self,
        analysis_type: str,
        analysis_result: dict,
        context: dict | None,
        repo_info: dict | None = None,
        file_tree: list | None = None,
    ) -> str:
        """构建反思上下文（包含仓库信息和文件树，直接注入无需工具调用）。"""
        parts = [f"# 反思审查任务\n分析类型: {analysis_type}\n"]

        # ── 仓库基本信息 ─────────────────────────────────────────────
        if repo_info:
            parts.append("\n## 仓库信息\n")
            ri = repo_info
            parts.append(f"- 仓库: {ri.get('owner', '')}/{ri.get('repo', '')}\n")
            if ri.get("description"):
                parts.append(f"- 描述: {ri['description']}\n")
            if ri.get("languages"):
                langs = ri["languages"]
                lang_str = ", ".join(f"{k} ({v})" for k, v in sorted(langs.items(), key=lambda x: x[1], reverse=True)[:5])
                parts.append(f"- 语言统计: {lang_str}\n")
            if ri.get("stars"):
                parts.append(f"- Stars: {ri['stars']}, Forks: {ri.get('forks', 0)}\n")
            parts.append(f"- 默认分支: {ri.get('default_branch', 'main')}\n")

        # ── 文件树结构 ─────────────────────────────────────────────
        if file_tree:
            parts.append("\n## 目录结构\n")
            # 只展示关键目录和文件
            dirs = sorted(set(item["path"].rsplit("/", 1)[0] for item in file_tree[:200] if "/" in item["path"]))
            files = [item["path"] for item in file_tree[:200] if "/" not in item["path"]]
            if dirs:
                parts.append(f"- 顶层目录 ({len(dirs)} 个):\n")
                for d in sorted(dirs)[:20]:
                    parts.append(f"  - {d}/\n")
            if files:
                parts.append(f"- 根目录文件:\n")
                for f in sorted(files)[:30]:
                    parts.append(f"  - {f}\n")
            if len(file_tree) > 200:
                parts.append(f"- 共 {len(file_tree)} 个文件/目录\n")

        parts.append("## 被审查的分析结果\n")
        parts.append("```json\n")
        parts.append(json.dumps(analysis_result, ensure_ascii=False, indent=2)[:5000])
        parts.append("\n```\n")

        if context:
            parts.append("\n## 已加载文件内容\n")
            parts.append("以下文件内容可直接用于验证分析结论：\n")

            if "loaded_paths" in context:
                paths = context["loaded_paths"]
                parts.append(f"- 已加载文件数: {len(paths)}\n")
                if paths:
                    parts.append("- 已加载文件路径示例:\n")
                    for p in paths[:20]:
                        parts.append(f"  - {p}\n")
                    if len(paths) > 20:
                        parts.append(f"  ... 等共 {len(paths)} 个文件\n")

            if "file_contents" in context:
                files = context["file_contents"]
                parts.append(f"- 已加载文件内容数: {len(files)}\n")
                parts.append("- 可用于验证的文件内容:\n")
                for p in list(files.keys())[:15]:
                    preview = files[p][:500].replace("\n", " ").strip() if files.get(p) else ""
                    parts.append(f"  - {p}: {preview}...\n")

            if "tech_stack_result" in context:
                ts = context["tech_stack_result"]
                parts.append("\n## 技术栈信息\n")
                parts.append(f"```json\n{json.dumps(ts, ensure_ascii=False, indent=2)[:2000]}\n```\n")

        parts.append("\n请开始反思审查，基于以上仓库信息、目录结构和文件内容验证分析结论的准确性和完整性。")
        return "".join(parts)

    def _build_final_prompt(self, analysis_type: str, verification_log: list[dict]) -> str:
        """构建最终反思 prompt。"""
        parts = ["\n## 验证日志\n"]

        if verification_log:
            for log in verification_log[-5:]:
                parts.append(f"- [{log['tool']}] {log['args']}: {log['finding'][:100]}\n")
        else:
            parts.append("- 暂无验证记录\n")

        parts.append(f"\n请基于以上验证结果，生成最终的 {analysis_type} 反思 JSON。")
        parts.append("必须包含 overall_confidence、needs_retry 和所有四个维度的评估。")
        return "".join(parts)

    def _extract_reasoning(self, content: str) -> str:
        """提取推理过程。"""
        patterns = [
            r"##\s*推理过程\s*([\s\S]+?)(?=```json|$)",
            r"##\s*Reflection\s*([\s\S]+?)(?=```json|$)",
            r"##\s*反思\s*([\s\S]+?)(?=```json|$)",
        ]
        for pat in patterns:
            m = re.search(pat, content, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:2000]
        return ""

    def _parse_reflection_json(self, content: str) -> dict:
        """解析反思 JSON。"""
        text = content.strip()

        # 尝试直接解析
        if text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

        # 尝试从代码块中提取
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 尝试提取 JSON 对象
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                if isinstance(data, dict) and "overall_confidence" in data:
                    return data
            except json.JSONDecodeError:
                pass

        return self._generate_fallback_reflection("", {})

    def _generate_fallback_reflection(self, analysis_type: str, analysis_result: dict) -> dict:
        """生成兜底反思结果。"""
        # 简单规则判断置信度
        confidence = 0.7

        if not analysis_result:
            confidence = 0.3
        elif len(str(analysis_result)) < 100:
            confidence = 0.4

        # 判断是否需要重试
        needs_retry = confidence < 0.5
        retry_reason = ""
        if not analysis_result:
            retry_reason = "分析结果为空"
        elif confidence < 0.5:
            retry_reason = "分析置信度过低，建议重新执行"

        return {
            "analysis_type": analysis_type,
            "overall_confidence": confidence,
            "confidence_level": "high" if confidence > 0.8 else ("medium" if confidence > 0.5 else "low"),
            "completeness": {
                "score": confidence,
                "issues": [] if confidence > 0.5 else ["分析结果过于简略"],
                "is_complete": confidence > 0.5,
            },
            "accuracy": {
                "score": confidence,
                "verified_claims": [],
                "unverified_claims": [] if confidence > 0.5 else ["缺少验证"],
                "is_accurate": confidence > 0.5,
            },
            "actionability": {
                "score": confidence,
                "actionable_suggestions": [],
                "vague_suggestions": [] if confidence > 0.5 else ["建议不够具体"],
                "is_actionable": confidence > 0.5,
            },
            "risk_assessment": {
                "score": 0.8,
                "risks": [],
                "is_safe": True,
            },
            "reflection_summary": f"反思完成，置信度 {confidence * 100:.0f}%。" +
                                ("分析质量良好。" if confidence > 0.5 else "建议重新执行以提高质量。"),
            "improvement_suggestions": [] if confidence > 0.5 else [
                {
                    "area": "completeness",
                    "issue": "分析结果不够完整",
                    "suggestion": "建议重新执行该分析",
                    "priority": "high",
                }
            ],
            "needs_retry": needs_retry,
            "retry_reason": retry_reason,
        }


# ─── 快速评估函数 ────────────────────────────────────────────────────────────
# 不需要完整 ReAct 循环的轻量级评估

def quick_confidence_check(analysis_type: str, analysis_result: dict) -> dict:
    """快速评估分析结果的置信度（无需 LLM）。

    用于在正式反思前快速判断是否需要完整反思。
    只有在分析结果明显不完整或为空时才触发深度反思。
    """
    result = {
        "analysis_type": analysis_type,
        "needs_deep_reflection": False,
        "quick_score": 0.7,  # 默认中等置信度
        "flags": [],
    }

    if not analysis_result:
        result["quick_score"] = 0.1
        result["flags"].append("empty_result")
        result["needs_deep_reflection"] = True
        return result

    # 检查各类型的特定字段
    if analysis_type == "loader":
        loaded_paths = analysis_result.get("loaded_paths", [])
        if len(loaded_paths) < 3:
            result["quick_score"] = 0.3
            result["flags"].append("too_few_files")
            result["needs_deep_reflection"] = True
        elif len(loaded_paths) > 0:
            result["quick_score"] = 0.8

    elif analysis_type == "explorer":
        has_findings = any([
            analysis_result.get("findings"),
            analysis_result.get("tech_stack_result"),
            analysis_result.get("quality_result"),
        ])
        if not has_findings:
            result["quick_score"] = 0.2
            result["flags"].append("no_findings")
            result["needs_deep_reflection"] = True
        else:
            # 如果有发现，默认置信度设为 0.75，不触发深度反思
            result["quick_score"] = 0.75

    elif analysis_type == "architecture":
        arch_result = analysis_result or {}
        has_components = bool(arch_result.get("components") or arch_result.get("layers"))
        has_style = bool(arch_result.get("architecture_style"))
        if has_components and has_style:
            result["quick_score"] = 0.8
        elif has_components or has_style:
            result["quick_score"] = 0.65
        else:
            result["quick_score"] = 0.4
            result["flags"].append("incomplete_architecture")
            result["needs_deep_reflection"] = True

    elif analysis_type == "suggestion":
        suggestions = analysis_result.get("suggestions", [])
        verified_count = sum(1 for s in suggestions if s.get("verified"))
        if len(suggestions) == 0:
            result["quick_score"] = 0.2
            result["flags"].append("no_suggestions")
            result["needs_deep_reflection"] = True
        elif verified_count == 0 and len(suggestions) > 0:
            # 有建议但未验证，降低分数但不触发深度反思
            result["quick_score"] = 0.55
            result["flags"].append("no_verified_suggestions")
        else:
            result["quick_score"] = 0.8

    return result
