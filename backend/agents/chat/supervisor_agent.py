"""
Supervisor Agent — 意图分类 + 路由决策。

职责：
  1. 分析用户问题的意图（Intent 分类）
  2. 做出路由决策（分配给哪个 Agent 处理）
  3. 支持混合意图（需要多个 Agent 协作）
  4. 提取上下文线索（repo_url、category 等）传递给下游 Agent
"""

import logging
import re
from typing import AsyncGenerator

from langchain_core.messages import HumanMessage, SystemMessage

from schemas.multi_agent import Intent, RouteDecision
from utils.llm_factory import get_llm_with_tracking

_logger = logging.getLogger("gitintel")

SUPERVISOR_SYSTEM_PROMPT = """你是一个智能路由 Agent，负责分析用户问题并将其分配给最合适的专业 Agent。

你的任务是对用户问题进行意图分类，然后决定由哪个 Agent 处理。

## 意图分类

用户问题属于以下五种意图之一：

1. **knowledge（知识库问答）**: 询问 GitIntel 分析经验、最佳实践、技术建议，不涉及特定仓库的具体分析结果。
   典型问题："React 项目常见的性能问题有哪些？""依赖风险一般怎么评估？"
   典型问题："这种架构模式适合什么场景？"

2. **code（代码相关）**: 涉及具体代码片段、算法实现、代码优化、调试问题的讨论。
   典型问题："这个函数的时间复杂度是多少？""帮我分析这段代码的逻辑"
   典型问题："为什么这段代码会有循环依赖？""这段 async 代码有问题吗？"

3. **analysis（分析结果查询）**: 用户想查看某个仓库的具体分析结果（架构、质量、依赖等）。
   典型问题："帮我看看这个仓库的分析结果""那个项目的架构怎么样？"
   典型问题："这个仓库的质量评分是多少？""有哪些高危依赖？"

4. **general（通用问题）**: 闲聊、使用说明、项目无关的通用问题。
   典型问题："你好""怎么使用这个工具？""GitIntel 是做什么的？"

5. **mixed（混合意图）**: 问题涉及多个方面，需要多个 Agent 协作回答。
   典型问题："这个仓库有什么架构问题？和同类项目比有什么优劣？"
   典型问题："这个项目的代码质量如何？有没有相关的优化经验可以参考？"

## 路由规则

- 用户提到具体仓库（URL、owner/repo 格式、仓库描述）→ analysis 或 mixed
- 用户询问最佳实践、经验分享、通用技术建议 → knowledge
- 用户贴出代码、讨论代码逻辑/算法/bug → code
- 用户打招呼、问如何使用、闲聊 → general
- 问题跨越多个类别 → mixed，primary=最相关，secondary=辅助

## 输出格式

直接输出 JSON 格式的路由决策，不需要任何前缀说明：
{
  "intent": "knowledge|code|analysis|general|mixed",
  "confidence": 0.0~1.0,
  "reason": "判定理由（1-2句话）",
  "primary_agent": "knowledge|code|analysis|general",
  "secondary_agent": "knowledge|code|analysis|general|null（mixed 时非空）",
  "context_hints": {
    "repo_url": "owner/repo（如果有）",
    "relevant_categories": ["architecture", "quality"]（如果有）
  }
}
"""


class SupervisorAgent:
    """Supervisor Agent：意图分类 + 路由决策。"""

    name = "supervisor"

    def classify(self, question: str, history: list[dict] | None = None) -> RouteDecision:
        """同步意图分类 + 路由决策。"""
        llm = get_llm_with_tracking(agent_name=self.name, temperature=0.1)
        if llm is None:
            return RouteDecision(
                intent=Intent.GENERAL,
                confidence=0.0,
                reason="LLM 不可用，降级为 general",
                primary_agent="general",
                secondary_agent=None,
                context_hints={},
            )

        messages = [
            SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
            HumanMessage(content=f"用户问题：{question}"),
        ]

        if history:
            history_text = "\n".join(
                f"{'用户' if h.get('role') == 'user' else '助手'}：{h.get('content', '')}"
                for h in history[-4:]
            )
            if history_text:
                messages.append(HumanMessage(content=f"最近对话历史：\n{history_text}"))

        try:
            response = llm.ainvoke(messages)
            raw = response.content if hasattr(response, "content") else str(response)
            decision = self._parse_json(raw)
            if decision:
                _logger.info(
                    f"[Supervisor] intent={decision.intent}, "
                    f"confidence={decision.confidence:.2f}, "
                    f"reason={decision.reason}"
                )
                return decision
        except Exception as exc:
            _logger.warning(f"[Supervisor] LLM 调用失败: {exc}")

        return self._fallback_classify(question)

    async def classify_stream(self, question: str, history: list[dict] | None = None):
        """流式意图分类（快速关键词匹配，同步返回；LLM 结果异步优化）。"""
        fallback = self._fallback_classify(question)

        try:
            llm = get_llm_with_tracking(agent_name=self.name, temperature=0.1)
            if llm:
                messages = [
                    SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
                    HumanMessage(content=f"用户问题：{question}"),
                ]
                if history:
                    history_text = "\n".join(
                        f"{'用户' if h.get('role') == 'user' else '助手'}：{h.get('content', '')}"
                        for h in history[-4:]
                    )
                    if history_text:
                        messages.append(HumanMessage(content=f"最近对话历史：\n{history_text}"))

                response = await llm.ainvoke(messages)
                raw = response.content if hasattr(response, "content") else str(response)
                decision = self._parse_json(raw)
                if decision and decision.confidence > fallback.confidence:
                    _logger.info(f"[Supervisor] LLM 修正意图: {fallback.intent} -> {decision.intent}")
                    yield decision
                    return
        except Exception as exc:
            _logger.warning(f"[Supervisor] LLM 分类失败，使用降级结果: {exc}")

        yield fallback

    def _parse_json(self, raw: str) -> RouteDecision | None:
        """从 LLM 输出中解析 RouteDecision JSON。"""
        import json

        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            raw = match.group(1)
        else:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                raw = raw[start:end]

        try:
            data = json.loads(raw)
            return RouteDecision(
                intent=Intent(data.get("intent", "general")),
                confidence=float(data.get("confidence", 0.5)),
                reason=str(data.get("reason", "")),
                primary_agent=str(data.get("primary_agent", "general")),
                secondary_agent=data.get("secondary_agent"),
                context_hints=data.get("context_hints", {}),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            _logger.warning(f"[Supervisor] JSON 解析失败: {exc}, raw={raw[:200]}")
            return None

    def _fallback_classify(self, question: str) -> RouteDecision:
        """关键词匹配降级分类。"""
        q = question.lower()

        general_keywords = [
            "你好", "hi", "hello", "嗨", "help", "help me", "怎么用",
            "是什么", "what is", "who is", "请问", "问一下",
            "介绍一下", "tell me about",
        ]
        if any(k in q for k in general_keywords):
            return RouteDecision(
                intent=Intent.GENERAL, confidence=0.9,
                reason="检测到通用问题关键词",
                primary_agent="general", secondary_agent=None, context_hints={},
            )

        code_keywords = [
            "代码", "code", "函数", "function", "算法", "algorithm",
            "复杂度", "complexity", "优化这段", "debug", "bug",
            "为什么这段", "这段代码", "实现", "implement",
            "class ", "def ", "async ", "await", "异步",
            "循环依赖", "circular", "递归", "recursive",
        ]
        code_score = sum(1 for k in code_keywords if k in q)

        knowledge_keywords = [
            "最佳实践", "best practice", "经验", "建议", "typical",
            "常见问题", "common issue", "一般怎么", "应该怎么",
            "通常", "一般", "推荐", "recommend",
        ]
        knowledge_score = sum(1 for k in knowledge_keywords if k in q)

        repo_patterns = ["github.com/", "http", "owner/repo"]
        has_repo = any(p in question for p in repo_patterns)

        analysis_keywords = [
            "分析结果", "分析报告", "架构评估", "质量评分",
            "依赖风险", "帮我看看", "这个项目", "那个项目",
            "项目分析", "仓库分析",
        ]
        has_analysis_kw = any(k in q for k in analysis_keywords)

        if code_score >= 2:
            return RouteDecision(
                intent=Intent.CODE, confidence=0.7,
                reason="检测到多个代码相关关键词",
                primary_agent="code", secondary_agent=None,
                context_hints={"repo_url": self._extract_repo_url(question)},
            )

        if has_repo or has_analysis_kw:
            primary = "analysis"
            secondary = "knowledge" if knowledge_score >= 1 else None
            return RouteDecision(
                intent=Intent.MIXED if secondary else Intent.ANALYSIS,
                confidence=0.8 if has_repo else 0.6,
                reason="检测到仓库引用或分析关键词",
                primary_agent=primary, secondary_agent=secondary,
                context_hints={"repo_url": self._extract_repo_url(question)},
            )

        if knowledge_score >= 1:
            return RouteDecision(
                intent=Intent.KNOWLEDGE, confidence=0.6,
                reason="检测到知识库相关关键词",
                primary_agent="knowledge", secondary_agent=None, context_hints={},
            )

        return RouteDecision(
            intent=Intent.GENERAL, confidence=0.5,
            reason="无明确关键词匹配，使用通用回答",
            primary_agent="general", secondary_agent=None, context_hints={},
        )

    def _extract_repo_url(self, question: str) -> str | None:
        """从问题中提取仓库 URL。"""
        m = re.search(r"github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)", question)
        if m:
            return m.group(1)
        m = re.search(r"\b([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]{2,})\b", question)
        if m:
            return m.group(1)
        return None
