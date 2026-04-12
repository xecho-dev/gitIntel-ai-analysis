"""SuggestionAgent — LLM 驱动的优化建议生成。

核心策略：
  1. LLM 优先：接收真实代码内容 + 分析数据，生成深度优化建议
  2. 规则引擎兜底：仅在 LLM 不可用时补充关键性建议
  3. 传真实代码片段给 LLM，而非仅传摘要
"""
import logging
import os
import re
from typing import AsyncGenerator, Optional

from .base_agent import AgentEvent, BaseAgent, _make_event

_logger = logging.getLogger("gitintel")


# ─── LLM 懒加载 ─────────────────────────────────────────────────────────────

def _get_llm():
    """懒加载 LLM client（通过统一工厂，支持 LangSmith 追踪）。"""
    from utils.llm_factory import get_llm
    return get_llm(temperature=0.3)


# ─── 代码摘要工具 ────────────────────────────────────────────────────────────

def _empty_fix() -> dict:
    """返回空 code_fix（规则引擎建议无具体代码修改时使用）。"""
    return {"file": "", "type": "replace", "original": "", "updated": "", "reason": ""}


def _summarize_code_snippet(content: str, max_lines: int = 60) -> str:
    """截取代码片段的核心部分（去除空行和过长空白）。"""
    lines = content.splitlines()
    snippet = "\n".join(lines[:max_lines])
    snippet = re.sub(r"\n{3,}", "\n\n", snippet)
    return snippet.strip()


def _build_llm_context(
    repo_path: str,
    branch: str,
    file_contents: dict | None,
    code_parser_result: dict | None,
    tech_stack_result: dict | None,
    quality_result: dict | None,
    dependency_result: dict | None,
) -> str:
    """构建发送给 LLM 的完整上下文，包含真实代码片段。"""
    import json

    parts = [f"仓库: {repo_path}@{branch}\n"]

    # ── 1. 代码结构 ──────────────────────────────────────────────────────────
    if code_parser_result:
        cr = code_parser_result
        lang_stats = cr.get("language_stats", {})
        largest = cr.get("largest_files", [])
        chunked = cr.get("chunked_files", {})

        stats_lines = [
            f"  总文件数: {cr.get('total_files', 0)}（解析了 {cr.get('parsed_files', 0)} 个源码）",
            f"  总函数: {cr.get('total_functions', 0)}，总类/结构: {cr.get('total_classes', 0)}",
            f"  语义块: {cr.get('total_chunks', 0)}",
            f"  语言分布: " + ", ".join(
                f"{lang}({s['files']}文件/{s.get('functions', 0)}函数)"
                for lang, s in sorted(lang_stats.items(), key=lambda x: x[1]["files"], reverse=True)[:5]
            ) or "无",
        ]
        parts.append("【代码结构】\n" + "\n".join(stats_lines))

        # 附上代码片段（供 LLM 生成 code_fix）
        # 优先用 file_contents（完整内容），其次用 chunked_files
        if largest:
            top_files = sorted(largest, key=lambda x: x.get("lines", 0), reverse=True)[:3]
            for f in top_files:
                fpath = f["path"]
                fname = fpath.split("/")[-1]
                # 优先取完整文件内容，其次取 chunked 内容
                content = ""
                if file_contents and fpath in file_contents:
                    content = file_contents[fpath]
                elif fpath in chunked and chunked[fpath]:
                    content = "\n".join(c.get("content", "") for c in chunked[fpath])

                if content:
                    parts.append(f"\n  -- [{fname}]({f['lines']}行) --")
                    parts.append(content[:4000])

    # ── 2. 技术栈 ────────────────────────────────────────────────────────────
    if tech_stack_result:
        parts.append(
            f"\n【技术栈】\n"
            f"  语言: {', '.join(tech_stack_result.get('languages', []) or ['未知'])}\n"
            f"  框架: {', '.join(tech_stack_result.get('frameworks', []) or ['无'])}\n"
            f"  基础设施: {', '.join(tech_stack_result.get('infrastructure', []) or ['无'])}\n"
            f"  包管理器: {tech_stack_result.get('package_manager', 'unknown')}\n"
            f"  配置文件: {', '.join(tech_stack_result.get('config_files_found', []) or [])}"
        )

    # ── 3. 代码质量 ──────────────────────────────────────────────────────────
    if quality_result:
        qr = quality_result
        parts.append(
            f"\n【代码质量】\n"
            f"  健康度: {qr.get('health_score', '?')}/100\n"
            f"  测试覆盖率: {qr.get('test_coverage', '?')}%\n"
            f"  复杂度: {qr.get('complexity', '?')}\n"
            f"  可维护性: {qr.get('maintainability', '?')}\n"
            f"  重复率: {qr.get('duplication', {}).get('duplication_level', '?')} "
            f"({qr.get('duplication', {}).get('score', 0)}%)"
        )
        py_m = qr.get("python_metrics", {})
        if py_m:
            parts.append(
                f"  Python: {py_m.get('total_functions', 0)} 函数, "
                f"{py_m.get('total_classes', 0)} 类, "
                f"{py_m.get('over_complexity_count', 0)} 个高复杂度(>10)"
            )
        ts_m = qr.get("typescript_metrics", {})
        if ts_m:
            parts.append(
                f"  TypeScript: {ts_m.get('total_functions', 0)} 函数, "
                f"{ts_m.get('total_classes', 0)} 类, "
                f"{ts_m.get('over_complexity_count', 0)} 个高复杂度(>10)"
            )

    # ── 4. 依赖风险 ─────────────────────────────────────────────────────────
    if dependency_result:
        dr = dependency_result
        parts.append(
            f"\n【依赖风险】\n"
            f"  总依赖: {dr.get('total', 0)}，已扫描: {dr.get('scanned', 0)}\n"
            f"  高危: {dr.get('high', 0)}，中危: {dr.get('medium', 0)}，低危: {dr.get('low', 0)}\n"
            f"  风险等级: {dr.get('risk_level', 'unknown')}"
        )
        risky = [d for d in dr.get("deps", []) if d.get("risk_level") in ("high", "medium")][:5]
        if risky:
            parts.append("  高风险依赖:")
            for d in risky:
                parts.append(f"    - {d['name']}@{d.get('version', '*')} ({d.get('risk_level', 'unknown')})")

    return "\n".join(parts)


class SuggestionAgent(BaseAgent):
    """基于 LLM + 真实代码内容的优化建议生成。"""

    name = "suggestion"

    async def run(
        self,
        repo_path: str,
        branch: str = "main",
        file_contents: dict | None = None,
        *,
        code_parser_result: dict | None = None,
        tech_stack_result: dict | None = None,
        quality_result: dict | None = None,
        dependency_result: dict | None = None,
    ) -> dict:
        """执行 Agent，收集并返回最终 result 数据。"""
        result = None
        async for event in self.stream(
            repo_path, branch,
            file_contents=file_contents,
            code_parser_result=code_parser_result,
            tech_stack_result=tech_stack_result,
            quality_result=quality_result,
            dependency_result=dependency_result,
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
        dependency_result: dict | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """LLM 驱动的优化建议生成。

        优先使用 LLM 分析真实代码内容；LLM 不可用时才用规则引擎兜底。
        """
        yield _make_event(
            self.name, "status",
            "正在综合分析结果，生成优化建议…", 10, None
        )

        suggestions: list[dict] = []
        _id = [1]

        def next_id() -> int:
            v = _id[0]
            _id[0] += 1
            return v

        # ── LLM 生成（核心） ─────────────────────────────────────────────────
        llm = _get_llm()
        llm_suggestions: list[dict] = []

        if llm is not None:
            yield _make_event(
                self.name, "progress",
                "正在调用 LLM 深度分析代码…", 20, None
            )
            try:
                context = _build_llm_context(
                    repo_path, branch,
                    file_contents=file_contents,
                    code_parser_result=code_parser_result,
                    tech_stack_result=tech_stack_result,
                    quality_result=quality_result,
                    dependency_result=dependency_result,
                )

                llm_suggestions = await self._generate_llm_suggestions(
                    llm, repo_path, branch, context, next_id
                )
                if llm_suggestions:
                    suggestions.extend(llm_suggestions)
                    _logger.info(f"[SuggestionAgent] LLM 生成了 {len(llm_suggestions)} 条建议")
                else:
                    _logger.warning("[SuggestionAgent] LLM 返回为空，使用规则引擎兜底")

            except Exception as exc:
                _logger.error(f"[SuggestionAgent] LLM 生成失败: {exc}")

                yield _make_event(
                    self.name, "progress",
                    f"LLM 调用失败，降级到规则引擎: {exc}", 20, None
                )
        else:
            yield _make_event(
                self.name, "progress",
                "未配置 LLM API，使用规则引擎生成建议…", 20, None
            )

        # ── 规则引擎兜底（仅在 LLM 失败或数量不足时补充关键性建议） ──────────
        rule_count = 0
        if not llm_suggestions:
            # LLM 完全不可用时，使用规则引擎
            if quality_result:
                suggestions.extend(self._quality_suggestions(quality_result, next_id))
            if dependency_result:
                suggestions.extend(self._dependency_suggestions(dependency_result, next_id))
            rule_count = len(suggestions)
        elif len(llm_suggestions) < 3:
            # LLM 结果偏少，补充关键性发现
            if quality_result:
                critical = self._quality_critical_only(quality_result, next_id)
                suggestions.extend(critical)
            if dependency_result:
                critical = self._dependency_critical_only(dependency_result, next_id)
                suggestions.extend(critical)

        # ── 去重（按 title） ─────────────────────────────────────────────────
        seen_titles = set()
        unique: list[dict] = []
        for s in suggestions:
            key = s.get("title", "").strip().lower()
            if key and key not in seen_titles:
                seen_titles.add(key)
                unique.append(s)
        suggestions = unique

        # ── 兜底空结果 ───────────────────────────────────────────────────────
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

        # 按 priority 排序
        priority_order = {"high": 0, "medium": 1, "low": 2}
        suggestions.sort(key=lambda s: priority_order.get(s["priority"], 2))

        yield _make_event(
            self.name, "result", f"生成了 {len(suggestions)} 条优化建议",
            100,
            {
                "suggestions": suggestions,
                "total": len(suggestions),
                "high_priority": sum(1 for s in suggestions if s["priority"] == "high"),
                "medium_priority": sum(1 for s in suggestions if s["priority"] == "medium"),
                "low_priority": sum(1 for s in suggestions if s["priority"] == "low"),
                "llm_powered": len(llm_suggestions) > 0,
                "rule_count": rule_count,
            },
        )

    # ─── LLM 生成 ──────────────────────────────────────────────────────────

    @staticmethod
    async def _generate_llm_suggestions(
        llm,
        repo_path: str,
        branch: str,
        context: str,
        next_id,
    ) -> list[dict]:
        """调用 LLM，基于真实代码内容生成优化建议。

        每条建议必须包含：id, type, title, description, priority, category, source
        以及 code_fix（original/updated/file/reason/type）。
        """
        from langchain_core.messages import HumanMessage

        system_prompt = (
            "你是一位资深软件架构师和代码审计专家，正在分析 GitHub 仓库。\n"
            "你的职责是根据以下真实代码分析数据，生成 4~6 条有深度、可操作的优化建议。\n"
            "每条建议必须包含以下字段（直接返回 JSON 数组，不要 markdown 包裹）：\n"
            "  - id: 整数，从 1 开始\n"
            "  - type: security | performance | refactor | general | testing | complexity\n"
            "  - title: 中文标题，20字以内，精准描述问题\n"
            "  - description: 详细说明（中文，80-200字），包含具体建议和可操作的步骤\n"
            "  - priority: high | medium | low\n"
            "  - category: security | testing | complexity | dependency | architecture | "
            "infrastructure | readability | maintenance\n"
            "  - code_fix: 必须包含，格式为 {\n"
            "      file: 目标文件路径，如 src/utils/helper.py（必须从下面提供的文件列表中选择）\n"
            "      type: replace | insert | delete\n"
            "      original: 原代码（必须是下面提供的代码中存在的精确字符串，用于定位修改位置）\n"
            "      updated: 修改后的代码\n"
            "      reason: 修改原因说明（中文，一句话）\n"
            "    }\n"
            "重要规则：\n"
            "1. code_fix.file 必须从上下文提供的文件中选择，不要自行推断文件路径\n"
            "2. code_fix.original 必须是文件中存在的精确代码字符串\n"
            "3. 如果不确定精确代码，type 改用 'insert' 并在 updated 中写新代码，original 写空字符串\n"
            "只返回 JSON 数组，不要有任何其他文字。"
        )

        user_prompt = (
            f"请分析以下仓库的代码，为其生成优化建议：\n\n{context}\n\n"
            "直接返回 JSON 数组（最多 6 条建议）："
        )

        response = await llm.ainvoke([
            HumanMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        content = response.content.strip()

        # 解析 JSON
        try:
            suggestions = SuggestionAgent._parse_llm_json(content, next_id)
            if suggestions:
                return suggestions
        except Exception as exc:
            _logger.warning(f"[SuggestionAgent] JSON 解析失败: {exc}，原始内容: {content[:200]}")

        # fallback：尝试从文本中提取
        return SuggestionAgent._parse_llm_text_fallback(content, next_id)

    @staticmethod
    def _parse_llm_json(content: str, next_id) -> list[dict]:
        """解析 LLM 返回的 JSON 数组，支持被截断的响应。"""
        import json

        text = content.strip()

        # ── 1. 直接解析 ────────────────────────────────────────────────
        if text.startswith("["):
            try:
                data = json.loads(text)
                if isinstance(data, list):
                    return SuggestionAgent._normalize_suggestions(data, next_id)
            except json.JSONDecodeError:
                pass

        # ── 2. 从 markdown 包裹中提取 ─────────────────────────────────
        import re
        match = re.search(r"\[[\s\S]*\]", text)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, list):
                    return SuggestionAgent._normalize_suggestions(data, next_id)
            except json.JSONDecodeError:
                pass

        # ── 3. 截断 JSON 兜底：提取所有完整的 suggestion 对象 ─────────
        # 当 LLM 输出被截断时，JSON 可能从中间断开，逐个提取完整对象
        try:
            # 提取所有 {...} 块
            bracket_depth = 0
            obj_start = -1
            complete_objs: list[str] = []
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
                        complete_objs.append(text[obj_start:i + 1])
                        obj_start = -1

            if complete_objs:
                suggestions: list[dict] = []
                for obj_str in complete_objs:
                    try:
                        obj = json.loads(obj_str)
                        if isinstance(obj, dict) and obj.get("title"):
                            suggestions.append(obj)
                    except Exception:
                        pass
                if suggestions:
                    return SuggestionAgent._normalize_suggestions(suggestions, next_id)
        except Exception:
            pass

        return []

    @staticmethod
    def _parse_llm_text_fallback(content: str, next_id) -> list[dict]:
        """无法解析 JSON 时，从文本内容中提取关键建议（降级方案）。"""
        suggestions: list[dict] = []
        import re

        # 匹配常见格式：1. 标题 / - 标题 / ## 标题
        patterns = [
            # "1. 标题: 描述" 或 "- 标题: 描述"
            re.compile(r"(?:^\d+[\.\)]\s*|^[-*]\s*|^##?\s*)([^\n:：]{5,40})[:：]\s*(.+)"),
            # "# 标题" 后紧跟描述
            re.compile(r"^#{1,3}\s*([^\n]{5,40})\n+(.+?)(?=^\d|^-|\Z)", re.MULTILINE | re.DOTALL),
        ]

        for para in content.split("\n\n"):
            para = para.strip()
            if len(para) < 15:
                continue
            for pattern in patterns:
                m = pattern.match(para.lstrip())
                if not m:
                    m = re.match(r"(?:^\d+[\.\)]\s*)?([^\n:：]{5,40})[:：]\s*(.+)", para.lstrip())
                if m:
                    title = m.group(1).strip()
                    desc = m.group(2).strip()
                    if len(title) > 4 and len(desc) > 10:
                        suggestions.append({
                            "id": next_id(),
                            "type": "general",
                            "title": title[:30],
                            "description": desc[:300],
                            "priority": "medium",
                            "category": "general",
                            "source": "llm-text",
                        })
                    break
            if len(suggestions) >= 5:
                break

        return suggestions

    @staticmethod
    def _normalize_suggestions(raw: list, next_id) -> list[dict]:
        """标准化 LLM 返回的建议列表，同时保留 code_fix 字段。"""
        validated: list[dict] = []
        for s in raw:
            if not isinstance(s, dict):
                continue
            title = s.get("title", "").strip()
            if not title:
                continue

            code_fix = s.get("code_fix")
            if isinstance(code_fix, dict) and (code_fix.get("original") or code_fix.get("updated")):
                normalized_fix = {
                    "file": str(code_fix.get("file", "")),
                    "type": str(code_fix.get("type", "replace")),
                    "original": str(code_fix.get("original", "")),
                    "updated": str(code_fix.get("updated", "")),
                    "reason": str(code_fix.get("reason", "")),
                }
            else:
                # LLM 未提供 code_fix，使用占位符（后续 FixGeneratorAgent 可补充）
                normalized_fix = {
                    "file": "",
                    "type": "replace",
                    "original": "",
                    "updated": "",
                    "reason": "",
                }

            item = {
                "id": next_id(),
                "type": str(s.get("type", "general")).lower()[:20],
                "title": title[:30],
                "description": str(s.get("description", ""))[:300],
                "priority": SuggestionAgent._normalize_priority(s.get("priority")),
                "category": str(s.get("category", "general"))[:30],
                "source": "llm",
                "code_fix": normalized_fix,
            }
            validated.append(item)
        return validated

    @staticmethod
    def _normalize_priority(p: str) -> str:
        """标准化 priority 字段。"""
        if isinstance(p, str):
            p = p.lower().strip()
            if p in ("high", "h", "高", "高危", "critical"):
                return "high"
            if p in ("medium", "m", "中", "中等", "normal"):
                return "medium"
            if p in ("low", "l", "低", "low", "info"):
                return "low"
        return "medium"

    # ─── 规则引擎：关键性建议（仅在 LLM 失败时全量使用，正常时仅补充） ──────

    @staticmethod
    def _quality_critical_only(qr: dict, next_id) -> list[dict]:
        """仅提取关键性质量建议（LLM 辅助时使用）。"""
        suggestions: list[dict] = []

        health = qr.get("health_score", 100)
        coverage = qr.get("test_coverage", 100)
        dup_info = qr.get("duplication", {})
        dup_score = dup_info.get("score", 0)

        if health < 50:
            suggestions.append({
                "id": next_id(),
                "type": "performance",
                "title": "代码健康度严重偏低 (< 50)",
                "description": f"健康度评分 {health}/100，存在多处质量问题急需修复。",
                "priority": "high",
                "category": "quality",
                "source": "rule",
            })

        if coverage < 20:
            suggestions.append({
                "id": next_id(),
                "type": "performance",
                "title": "测试覆盖率严重不足 (< 20%)",
                "description": f"当前覆盖率仅 {coverage}%，建议立即补充核心模块测试。",
                "priority": "high",
                "category": "testing",
                "source": "rule",
            })

        if dup_score > 20:
            suggestions.append({
                "id": next_id(),
                "type": "refactor",
                "title": "代码重复率偏高 (> 20%)",
                "description": f"重复率 {dup_score}%，建议提取公共函数减少重复。",
                "priority": "medium",
                "category": "readability",
                "source": "rule",
            })

        return suggestions

    @staticmethod
    def _dependency_critical_only(dr: dict, next_id) -> list[dict]:
        """仅提取关键性依赖建议（LLM 辅助时使用）。"""
        suggestions: list[dict] = []

        high = dr.get("high", 0)
        risk_level = dr.get("risk_level", "")

        if risk_level == "高危" or high > 0:
            suggestions.append({
                "id": next_id(),
                "type": "security",
                "title": "存在高风险依赖",
                "description": f"检测到 {high} 个高危依赖，可能包含已知安全漏洞。",
                "priority": "high",
                "category": "security",
                "source": "rule",
            })

        return suggestions

    # ─── 规则引擎：全量建议（仅 LLM 不可用时使用） ─────────────────────────

    @staticmethod
    def _quality_suggestions(qr: dict, next_id) -> list[dict]:
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
                "description": f"建议按职责拆分为更小的函数，提高可读性和可维护性。",
                "priority": "low",
                "category": "readability",
                "source": "rule",
            })

        return suggestions

    @staticmethod
    def _dependency_suggestions(dr: dict, next_id) -> list[dict]:
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
