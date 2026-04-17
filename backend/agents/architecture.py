"""ArchitectureAgent — 基于 AST 结构 + TechStack + LLM 生成架构评估。

该 Agent 综合以下数据源进行真正的 LLM 驱动架构分析：
  1. CodeParserAgent 的 AST 结构（函数/类数量、文件大小分布、语义块）
  2. TechStackAgent 的技术栈识别结果（语言、框架、架构风格）
  3. QualityAgent 的代码质量指标（复杂度、可维护性）
  4. LLM（可选）：深度架构洞察

输出与前端 `ArchitectureResult` 类型对齐：
  - complexity: "Low" | "Medium" | "High"
  - components: number（估算的组件/模块数）
  - techStack: string[]（语言 + 框架）
  - maintainability: string（A+ ~ C-）
  - architectureStyle: string（如 Monolithic / Modular / Microservices / Serverless）
  - keyPatterns: string[]（检测到的设计模式）
  - hotSpots: string[]（潜在风险点）
  - summary: string（LLM 生成的架构摘要，200字以内）
"""
import logging
import re
from typing import AsyncGenerator

from .base_agent import AgentEvent, BaseAgent, _make_event
from utils.llm_factory import get_llm

_logger = logging.getLogger("gitintel")


# ─── LLM 懒加载 ────────────────────────────────────────────────────────

def _get_llm():
    """懒加载 LLM client（通过统一工厂，支持 LangSmith 追踪）。"""
    return get_llm(temperature=0.2)


def _build_arch_context(
    code_parser_result: dict | None,
    tech_stack_result: dict | None,
    quality_result: dict | None,
    file_contents: dict | None = None,
) -> str:
    """从各 Agent 结果构建架构分析上下文（含真实代码片段）。"""
    import json

    parts = []

    # ── 代码片段（供 LLM 深度分析）────────────────────────────────────
    if file_contents and code_parser_result:
        chunked = code_parser_result.get("chunked_files", {})
        largest = code_parser_result.get("largest_files", [])
        # 取最大的 2 个文件的代码片段
        top_files = sorted(largest, key=lambda x: x.get("lines", 0), reverse=True)[:2]
        snippets = []
        for f in top_files:
            fpath = f["path"]
            snippet = ""
            if fpath in chunked and chunked[fpath]:
                chunk = chunked[fpath][0]
                snippet = chunk.get("content", "")[:1500]
            elif fpath in file_contents:
                snippet = _summarize_for_arch(file_contents[fpath], max_lines=40)
            if snippet:
                fname = fpath.split("/")[-1]
                snippets.append(f"// {fname} ({f['lines']}行)\n{snippet[:1200]}")
        if snippets:
            parts.append("【关键代码片段】\n" + "\n\n".join(snippets))

    # ── 技术栈 ─────────────────────────────────────────────────────────
    if tech_stack_result:
        parts.append(
            f"【技术栈】\n"
            f"  语言: {', '.join(tech_stack_result.get('languages', []) or ['未知'])}\n"
            f"  框架: {', '.join(tech_stack_result.get('frameworks', []) or ['无'])}\n"
            f"  基础设施: {', '.join(tech_stack_result.get('infrastructure', []) or ['无'])}\n"
            f"  包管理器: {tech_stack_result.get('package_manager', 'unknown')}"
        )

    # ── 代码结构 ────────────────────────────────────────────────────
    if code_parser_result:
        cr = code_parser_result
        lang_stats = cr.get("language_stats", {})
        largest = cr.get("largest_files", [])

        parts.append(
            f"【代码结构】\n"
            f"  总文件数: {cr.get('total_files', 0)}\n"
            f"  解析文件: {cr.get('parsed_files', 0)}\n"
            f"  总函数: {cr.get('total_functions', 0)}\n"
            f"  总类/结构: {cr.get('total_classes', 0)}\n"
            f"  语义块: {cr.get('total_chunks', 0)}\n"
            f"  语言分布: " + ", ".join(
                f"{lang}({s['files']}文件/{s.get('functions', 0)}函数)"
                for lang, s in sorted(lang_stats.items(), key=lambda x: x[1]["files"], reverse=True)[:5]
            ) + "\n"
            f"  最大文件: " + (
                f"{largest[0]['path'].split('/')[-1]}({largest[0]['lines']}行)"
                if largest else "无"
            )
        )

    # ── 质量指标 ────────────────────────────────────────────────────
    if quality_result:
        parts.append(
            f"【质量指标】\n"
            f"  健康度: {quality_result.get('health_score', '?')}/100\n"
            f"  测试覆盖率: {quality_result.get('test_coverage', '?')}%\n"
            f"  可维护性: {quality_result.get('maintainability', '?')}\n"
            f"  重复率: {quality_result.get('duplication', {}).get('duplication_level', '?')}"
        )

    return "\n\n".join(parts) if parts else "（无可用分析数据）"


def _summarize_for_arch(content: str, max_lines: int = 40) -> str:
    """为架构分析截取代码核心部分。"""
    lines = content.splitlines()
    snippet = "\n".join(lines[:max_lines])
    snippet = re.sub(r"\n{3,}", "\n\n", snippet)
    return snippet.strip()


class ArchitectureAgent(BaseAgent):
    """基于 AST + TechStack + LLM 的架构评估 Agent。"""

    name = "architecture"

    async def run(
        self,
        repo_path: str,
        branch: str = "main",
        file_contents: dict | None = None,
        *,
        code_parser_result: dict | None = None,
        tech_stack_result: dict | None = None,
        quality_result: dict | None = None,
        total_tree_files: int = 0,
    ) -> dict:
        """执行 Agent，收集并返回最终 result 数据。"""
        result = None
        async for event in self.stream(
            repo_path, branch,
            file_contents=file_contents,
            code_parser_result=code_parser_result,
            tech_stack_result=tech_stack_result,
            quality_result=quality_result,
            total_tree_files=total_tree_files,
        ):
            if event["type"] == "result":
                result = event["data"]
        return result or {}

    async def stream(
        self,
        repo_path: str,
        branch: str = "main",
        file_contents: dict | None = None,
        *,
        code_parser_result: dict | None = None,
        tech_stack_result: dict | None = None,
        quality_result: dict | None = None,
        total_tree_files: int = 0,
    ) -> AsyncGenerator[AgentEvent, None]:
        """流式输出架构分析结果（SSE 用）。

        优先使用 LLM 生成深度架构洞察，降级到规则引擎。
        """
        yield _make_event(
            self.name, "status",
            "正在分析项目架构…", 10, None
        )

        # ── 1. 规则引擎：基于 AST 和 TechStack 生成基础指标 ─────────
        # 传入 tree 总文件数，使复杂度计算能反映真实仓库规模
        arch_data = self._rule_based_analysis(
            code_parser_result=code_parser_result,
            tech_stack_result=tech_stack_result,
            quality_result=quality_result,
            total_tree_files=total_tree_files or (
                (code_parser_result or {}).get("total_files", 0)
                or (tech_stack_result or {}).get("dependency_count", 0) * 10
            ),
        )

        yield _make_event(
            self.name, "progress",
            f"检测到 {arch_data['components']} 个组件，正在深度分析…", 40, None
        )

        # ── 2. LLM 增强：发送真实代码内容 + 分析数据给 LLM ────────────
        llm = _get_llm()
        if llm is not None:
            yield _make_event(
                self.name, "progress",
                "正在调用 LLM 生成架构洞察…", 60, None
            )
            try:
                llm_insights = await self._generate_llm_insights(
                    llm, repo_path, branch,
                    file_contents=file_contents,
                    code_parser_result=code_parser_result,
                    tech_stack_result=tech_stack_result,
                    quality_result=quality_result,
                )
                # 合并 LLM 洞察到 arch_data
                if llm_insights:
                    arch_data.update({
                        "complexity": llm_insights.get("complexity", arch_data["complexity"]),
                        "architectureStyle": llm_insights.get("architectureStyle", arch_data["architectureStyle"]),
                        "keyPatterns": llm_insights.get("keyPatterns", arch_data["keyPatterns"]),
                        "hotSpots": llm_insights.get("hotSpots", arch_data["hotSpots"]),
                        "summary": llm_insights.get("summary", arch_data["summary"]),
                        "llmPowered": True,
                    })
                    _logger.info(f"[ArchitectureAgent] LLM 架构洞察成功: style={llm_insights.get('architectureStyle')}")
            except Exception as exc:
                _logger.error(f"[ArchitectureAgent] LLM 架构分析失败: {exc}")
        else:
            arch_data["llmPowered"] = False

        # ── 3. 最终输出 ──────────────────────────────────────────
        yield _make_event(
            self.name, "result",
            f"架构分析完成 — {arch_data['complexity']} 复杂度 / "
            f"{arch_data['components']} 组件 / 可维护性 {arch_data['maintainability']}",
            100, arch_data
        )

    # ─── 规则引擎：基于 AST/质量数据生成基础架构指标 ────────────────

    def _rule_based_analysis(
        self,
        code_parser_result: dict | None,
        tech_stack_result: dict | None,
        quality_result: dict | None,
        total_tree_files: int = 0,
    ) -> dict:
        """基于 AST 结构和技术栈识别生成架构评估（不依赖 LLM）。"""
        total_funcs = code_parser_result.get("total_functions", 0) if code_parser_result else 0
        total_classes = code_parser_result.get("total_classes", 0) if code_parser_result else 0
        parsed_files = code_parser_result.get("parsed_files", 0) if code_parser_result else 0
        lang_stats = (code_parser_result or {}).get("language_stats", {})
        largest_files = (code_parser_result or {}).get("largest_files", [])

        languages = (tech_stack_result or {}).get("languages", [])
        frameworks = (tech_stack_result or {}).get("frameworks", [])
        infra = (tech_stack_result or {}).get("infrastructure", [])

        health = quality_result.get("health_score", 70) if quality_result else 70
        maintainability = quality_result.get("maintainability", "B") if quality_result else "B"
        duplication_level = (
            quality_result or {}
        ).get("duplication", {}).get("duplication_level", "Low")
        if duplication_level == "High":
            maintainability = "C"

        # ── 复杂度评估 ──────────────────────────────────────
        complexity_score = 0
        # 真实仓库规模权重（最重要）：使用 tree 总文件数或实际解析文件数
        effective_files = max(total_tree_files, parsed_files)
        complexity_score += min(effective_files / 100, 6)   # 0-6  ← 提高上限
        # AST 分析数据权重（解析越充分越准确）
        complexity_score += min(total_funcs / 100, 3)          # 0-3
        complexity_score += min(total_classes / 30, 2)        # 0-2
        # 基于最大文件大小
        if largest_files and largest_files[0]["lines"] > 500:
            complexity_score += 1
        if duplication_level == "High":
            complexity_score += 1
        # 技术栈复杂度加成
        if len(frameworks) >= 3:
            complexity_score += 1
        if len(languages) >= 3:
            complexity_score += 1

        if complexity_score <= 4:
            complexity = "Low"
        elif complexity_score <= 10:
            complexity = "Medium"
        else:
            complexity = "High"

        # ── 组件数估算 ──────────────────────────────────────
        # 策略：语言数 * 领域系数 + 框架加成
        lang_count = len(languages)
        framework_count = len(frameworks)
        # 使用真实仓库规模估算组件数（而非仅用解析的少量文件）
        effective_files = max(total_tree_files, parsed_files)
        components = max(
            lang_count * 5 + framework_count * 2,           # 语言+框架基础
            parsed_files // 20 + lang_count,                 # 解析文件密度
            effective_files // 50 + lang_count + framework_count,  # 全仓库规模
            3
        )

        # ── 技术栈汇总 ──────────────────────────────────────
        tech_stack = list(dict.fromkeys(languages + frameworks))  # 去重保留顺序

        # ── 架构风格识别 ────────────────────────────────────
        arch_style = self._detect_architecture_style(
            frameworks, infra, lang_stats, largest_files
        )

        # ── 设计模式识别 ────────────────────────────────────
        patterns = self._detect_design_patterns(
            code_parser_result, tech_stack_result, quality_result
        )

        # ── 热点/风险识别 ────────────────────────────────────
        hotspots = self._detect_hotspots(
            code_parser_result, quality_result, largest_files
        )

        return {
            "complexity": complexity,
            "components": components,
            "techStack": tech_stack,
            "maintainability": maintainability,
            "architectureStyle": arch_style,
            "keyPatterns": patterns,
            "hotSpots": hotspots,
            "summary": (
                f"该仓库使用 {', '.join(languages[:3])} 开发，包含 "
                f"{components} 个可识别组件，整体复杂度 {complexity}，"
                f"代码质量 {maintainability}。"
                + (f"检测到 {', '.join(patterns[:2])} 设计模式。"
                   if patterns else "")
                + (f"需要注意: {hotspots[0]}。" if hotspots else "")
            ),
        }

    @staticmethod
    def _detect_architecture_style(
        frameworks: list[str],
        infra: list[str],
        lang_stats: dict,
        largest_files: list[dict],
    ) -> str:
        """基于框架和基础设施推断架构风格。"""
        all_tags = set(f.lower() for f in frameworks + infra)

        if any(f in all_tags for f in ["fastapi", "django", "flask", "rails", "laravel", "spring"]):
            if any(f in all_tags for f in ["docker", "kubernetes"]):
                return "Modular Monolith"
            return "Monolithic"

        if any(f in all_tags for f in ["next.js", "nuxt", "remix", "gatsby"]):
            return "Full-stack SSR"

        if any(f in all_tags for f in ["react", "vue", "angular", "svelte"]):
            if any(f in all_tags for f in ["tailwindcss", "vite", "webpack"]):
                return "Single Page Application (SPA)"

        if any(f in all_tags for f in ["langchain", "langgraph", "anthropic", "openai"]):
            return "LLM-Powered Application"

        if any(f in all_tags for f in ["langgraph", "langgraph-sdk"]):
            return "Agentic / Graph Workflow"

        # 基于语言分布判断
        if "python" in lang_stats and "typescript" in lang_stats:
            return "Polyglot Microservices"
        if "go" in lang_stats or "rust" in lang_stats:
            return "Systems / High-performance"

        return "Modular"

    @staticmethod
    def _detect_design_patterns(
        code_parser_result: dict | None,
        tech_stack_result: dict | None,
        quality_result: dict | None,
    ) -> list[str]:
        """基于代码结构和依赖推断设计模式。"""
        patterns = []
        frameworks = set(f.lower() for f in (tech_stack_result or {}).get("frameworks", []))
        lang_stats = (code_parser_result or {}).get("language_stats", {})
        largest = (code_parser_result or {}).get("largest_files", [])

        if "react" in frameworks:
            patterns.append("Component-based UI")
        if "next.js" in frameworks:
            patterns.append("Server-Side Rendering (SSR)")
        if "langchain" in frameworks:
            patterns.append("Chain of Thought")
        if "langgraph" in frameworks:
            patterns.append("Graph-based State Machine")
        if "zustand" in frameworks or "redux" in frameworks or "pinia" in frameworks:
            patterns.append("Centralized State Management")
        if "docker" in (tech_stack_result or {}).get("infrastructure", []):
            patterns.append("Containerization")
        if any(f in frameworks for f in ["prisma", "sqlalchemy", "alembic"]):
            patterns.append("ORM / Data Access Layer")
        if any(f in frameworks for f in ["tRPC", "graphql", "@apollo/"]):
            patterns.append("API Abstraction Layer")
        if largest and largest[0]["lines"] > 300:
            patterns.append("God Object (needs refactor)")

        return patterns[:6]  # 最多 6 个

    @staticmethod
    def _detect_hotspots(
        code_parser_result: dict | None,
        quality_result: dict | None,
        largest_files: list[dict],
    ) -> list[str]:
        """识别架构热点/风险点。"""
        hotspots = []
        duplication = (quality_result or {}).get("duplication", {})
        if duplication.get("duplication_level") == "High":
            hotspots.append("高代码重复率")
        if quality_result and quality_result.get("health_score", 100) < 60:
            hotspots.append("代码健康度偏低")
        if largest_files and largest_files[0]["lines"] > 800:
            fname = largest_files[0]["path"].split("/")[-1]
            hotspots.append(f"超大文件 {fname}({largest_files[0]['lines']}行)")
        if quality_result and quality_result.get("test_coverage", 100) < 20:
            hotspots.append("测试覆盖率严重不足")
        py_metrics = (quality_result or {}).get("python_metrics", {})
        if py_metrics.get("over_complexity_count", 0) > 10:
            hotspots.append(f"{py_metrics['over_complexity_count']} 个高圈复杂度函数")
        ts_metrics = (quality_result or {}).get("typescript_metrics", {})
        if ts_metrics.get("over_complexity_count", 0) > 10:
            hotspots.append(f"{ts_metrics['over_complexity_count']} 个高圈复杂度 TypeScript 函数")

        return hotspots[:4]  # 最多 4 个

    # ─── LLM 增强生成 ────────────────────────────────────────────────

    @staticmethod
    async def _generate_llm_insights(
        llm,
        repo_path: str,
        branch: str,
        file_contents: dict | None = None,
        code_parser_result: dict | None = None,
        tech_stack_result: dict | None = None,
        quality_result: dict | None = None,
    ) -> dict:
        """调用 LLM 生成深度架构洞察（含真实代码片段）。"""
        import json, re

        context = _build_arch_context(
            code_parser_result, tech_stack_result, quality_result,
            file_contents=file_contents,
        )

        prompt = (
            f"你是一位资深软件架构师，正在分析仓库 {repo_path}@{branch}。\n\n"
            f"分析数据：\n{context}\n\n"
            "请基于以上真实代码数据，生成架构洞察（直接返回 JSON，不要 markdown 包裹）：\n"
            "{\n"
            '  "architectureStyle": "架构风格（如 Modular / Microservices / SPA / LLM-Powered 等）",\n'
            '  "complexity": "Low | Medium | High（根据仓库规模、模块数量、技术栈复杂度综合判断）",\n'
            '  "keyPatterns": ["模式1", "模式2", ...]（最多 6 个检测到的设计/架构模式），\n'
            '  "hotSpots": ["风险点1", "风险点2", ...]（最多 4 个架构风险或需要关注的地方），\n'
            '  "summary": "200字以内的中文架构摘要"\n'
            "}"
        )

        try:
            from langchain_core.messages import HumanMessage
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            content = response.content.strip()

            # 尝试解析 JSON
            try:
                # 去掉可能的 markdown 包裹
                match = re.search(r"\{[\s\S]*\}", content)
                if match:
                    return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        except Exception:
            pass

        return {}

    # ─── 公共解析方法（供 Graph 调用） ───────────────────────────────

    @staticmethod
    def parse_and_build(
        repo_path: str,
        branch: str,
        file_contents: dict | None = None,
        code_parser_result: dict | None = None,
        tech_stack_result: dict | None = None,
        quality_result: dict | None = None,
        total_tree_files: int = 0,
    ) -> dict:
        """同步构建架构分析结果（供 graph 同步调用）。

        使用 get_running_loop().run_until_complete()，兼容 LangGraph 的事件循环。

        Returns:
            dict: 架构分析结果，与 stream() 返回的 data 结构一致。
        """
        agent = ArchitectureAgent()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 无运行中的循环时用标准方式（防御性）
            return asyncio.run(agent.run(
                repo_path, branch,
                file_contents=file_contents,
                code_parser_result=code_parser_result,
                tech_stack_result=tech_stack_result,
                quality_result=quality_result,
                total_tree_files=total_tree_files,
            ))
        return loop.run_until_complete(agent.run(
            repo_path, branch,
            file_contents=file_contents,
            code_parser_result=code_parser_result,
            tech_stack_result=tech_stack_result,
            quality_result=quality_result,
            total_tree_files=total_tree_files,
        ))
