"""
AnalysisAgent — 分析结果查询 Agent。

职责：回答关于具体仓库分析结果的查询（架构、质量、依赖、建议等）。
"""

import logging
from typing import AsyncGenerator

from langchain_core.messages import HumanMessage

from schemas.chat import RAGSource
from schemas.multi_agent import AgentResponse
from utils.llm_factory import get_llm_with_tracking

from .base_chat_agent import ChatAgent

_logger = logging.getLogger("gitintel")

ANALYSIS_AGENT_PROMPT = """
## AnalysisAgent 专业能力

你专注于展示 GitIntel 对具体仓库的分析结果。

你可能从以下来源获取数据：
1. 已缓存的分析结果（analysis_results_cache）
2. 从向量库检索到的历史分析文档
3. 综合上述数据生成总结性回答

你的专长：
1. 解读架构评估结果（拓扑结构、模块关系、架构模式）
2. 解读代码质量评分（复杂度、可维护性、测试覆盖率等）
3. 解读依赖风险（过时依赖、安全漏洞、可升级建议）
4. 解读优化建议（按优先级、类别组织）

回答风格：
- 先给出一个总览（overall summary）
- 再分维度展开（架构 / 质量 / 依赖 / 建议）
- 突出关键问题和优先建议
- 使用结构化格式（如列表、小标题）让信息清晰

注意：如果没有找到相关分析结果，坦诚告知用户并建议先发起一次分析。
"""


class AnalysisAgent(ChatAgent):
    """分析结果查询 Agent。"""

    name = "analysis"
    intent_targets = ["analysis"]

    def get_system_prompt(self) -> str:
        return self.COMMON_SYSTEM_PROMPT.strip() + "\n\n" + ANALYSIS_AGENT_PROMPT.strip()

    def answer(
        self,
        question: str,
        context_docs: list[RAGSource] | None = None,
        history: list[dict] | None = None,
        repo_url: str | None = None,
        analysis_cache: dict | None = None,
        **kwargs,
    ) -> AgentResponse:
        docs = context_docs or []
        extra_context = self._build_repo_context(repo_url, analysis_cache)
        messages = self._build_messages(question, docs, history or [])
        if extra_context:
            messages.append(HumanMessage(content=f"附加上下文（分析结果）：\n{extra_context}"))

        answer_text = self._call_llm(messages, temperature=0.3)
        return AgentResponse(
            answer=answer_text,
            agent_name=self.name,
            sources=docs,
            used_knowledge=len(docs) > 0,
            extra_data={"repo_url": repo_url, "has_cache": analysis_cache is not None},
        )

    async def answer_stream(
        self,
        question: str,
        context_docs: list[RAGSource] | None = None,
        history: list[dict] | None = None,
        repo_url: str | None = None,
        analysis_cache: dict | None = None,
        **kwargs,
    ) -> AsyncGenerator[tuple[str, list[RAGSource], str], None]:
        docs = context_docs or []
        yield ("", docs, "")

        extra_context = self._build_repo_context(repo_url, analysis_cache)
        messages = self._build_messages(question, docs, history or [])
        if extra_context:
            messages.append(HumanMessage(content=f"附加上下文（分析结果）：\n{extra_context}"))

        llm = get_llm_with_tracking(agent_name=self.name, temperature=0.3)
        if llm is None:
            yield ("抱歉，AI 服务暂时不可用。", [], "抱歉，AI 服务暂时不可用。")
            return

        full_text = ""
        try:
            async for chunk in llm.astream(messages):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                full_text += token
                yield (token, [], full_text)
        except Exception as exc:
            _logger.error(f"[AnalysisAgent] LLM 流式调用失败: {exc}")
            yield ("抱歉，回答生成过程中出现错误。", [], full_text)
            return

        yield ("", [], full_text)

    def _build_repo_context(self, repo_url: str | None, analysis_cache: dict | None) -> str:
        if not repo_url and not analysis_cache:
            return ""
        parts = []
        if repo_url:
            parts.append(f"目标仓库：{repo_url}")
        if analysis_cache:
            parts.append("\n--- 已缓存的分析结果 ---\n")
            parts.append(self._format_cache(analysis_cache))
        return "\n".join(parts)

    def _format_cache(self, cache: dict) -> str:
        lines = []

        arch = cache.get("architecture") or cache.get("architecture_result")
        if arch:
            lines.append("\n## 架构分析")
            if isinstance(arch, dict):
                if arch.get("concerns"):
                    lines.append("关注点：")
                    for c in arch["concerns"][:5]:
                        lines.append(f"  - {c}")
                if arch.get("patterns"):
                    lines.append("架构模式：")
                    for p in arch["patterns"][:3]:
                        lines.append(f"  - {p}")

        quality = cache.get("quality") or cache.get("quality_result")
        if quality:
            lines.append("\n## 代码质量")
            if isinstance(quality, dict):
                if quality.get("complexity"):
                    lines.append(f"  复杂度：{quality['complexity']}")
                if quality.get("maintainability"):
                    lines.append(f"  可维护性：{quality['maintainability']}")
                if quality.get("health_score"):
                    lines.append(f"  健康分：{quality['health_score']}")

        dep = cache.get("dependency") or cache.get("dependency_result")
        if dep:
            lines.append("\n## 依赖风险")
            if isinstance(dep, dict):
                risky = dep.get("risky_deps", [])
                if risky:
                    lines.append("高危依赖：")
                    for d in risky[:3]:
                        lines.append(f"  - {d.get('name', 'unknown')}: {d.get('risk_level', '')}")
                outdated = dep.get("outdated_deps", [])
                if outdated:
                    lines.append("过时依赖：")
                    for d in outdated[:3]:
                        lines.append(f"  - {d.get('name', 'unknown')}")

        suggestion = cache.get("suggestion") or cache.get("suggestion_result")
        if suggestion:
            lines.append("\n## 优化建议")
            if isinstance(suggestion, dict):
                suggestions = suggestion.get("suggestions", [])
                for s in suggestions[:5]:
                    if isinstance(s, dict):
                        lines.append(f"  - [{s.get('priority', '?')}] {s.get('title', s.get('description', ''))}")

        return "\n".join(lines) if lines else ""
