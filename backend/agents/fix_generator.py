"""FixGeneratorAgent — 基于优化建议生成代码修改方案。

核心流程：
  SuggestionAgent 结果（含 code_fix: {original, updated, file, type, reason}）
       ↓
  FixGeneratorAgent（直接使用已有 code_fix；必要时调用 LLM 补充）
       ↓
  返回 CodeFix[]:
    - file: 文件路径
    - type: replace | insert | delete
    - original: 原代码
    - updated: 修改后代码
    - reason: 修改原因
"""
import json
import logging
import os
import re
from typing import AsyncGenerator

from .base_agent import AgentEvent, _make_event

_logger = logging.getLogger("gitintel")


def _get_llm():
    """懒加载 LLM client（通过统一工厂，支持 LangSmith 追踪）。"""
    from utils.llm_factory import get_llm
    return get_llm(temperature=0.2)


class CodeFix:
    """单个文件代码修改方案。"""

    def __init__(
        self,
        file: str,
        type: str,  # replace | insert | delete
        original: str,
        updated: str,
        reason: str = "",
        line_start: int | None = None,
        line_end: int | None = None,
    ):
        self.file = file
        self.type = type
        self.original = original
        self.updated = updated
        self.reason = reason
        self.line_start = line_start
        self.line_end = line_end


class FixGeneratorAgent:
    """基于优化建议生成代码修改方案的 Agent。"""

    name = "fix_generator"

    async def stream(
        self,
        repo_path: str,
        branch: str,
        suggestions: list[dict],
        file_contents: dict | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """生成代码修改方案。

        Args:
            repo_path: 仓库路径（用于定位文件）
            branch: 当前分支
            suggestions: SuggestionAgent 返回的建议列表（含 code_fix）
            file_contents: 文件内容字典 {filepath: content}
        """
        yield _make_event(
            self.name, "status",
            "正在分析优化建议，生成代码修改方案…", 10, None
        )

        # 过滤出可执行的建议（排除 general 类型）
        actionable = [
            s for s in suggestions
            if s.get("type") not in ("general", "testing", "infrastructure")
            and s.get("priority") in ("high", "medium")
        ]

        if not actionable:
            yield _make_event(
                self.name, "result",
                "没有可执行的代码修改建议",
                100,
                {"fixes": [], "message": "当前建议不需要代码修改"}
            )
            return

        yield _make_event(
            self.name, "progress",
            f"正在生成 {len(actionable)} 个代码修改…", 30, None
        )

        # 调用 LLM 生成修改方案
        llm = _get_llm()
        if not llm:
            yield _make_event(
                self.name, "error",
                "未配置 LLM API，无法生成代码修改",
                0, None
            )
            return

        try:
            fixes = await self._generate_fixes(llm, repo_path, branch, actionable, file_contents)

            yield _make_event(
                self.name, "result",
                f"生成了 {len(fixes)} 个代码修改方案",
                100,
                {
                    "fixes": [
                        {
                            "file": f.file,
                            "type": f.type,
                            "original": f.original,
                            "updated": f.updated,
                            "reason": f.reason,
                        }
                        for f in fixes
                    ],
                    "total": len(fixes),
                }
            )
        except Exception as exc:
            _logger.error(f"[FixGeneratorAgent] 生成失败: {exc}")
            yield _make_event(
                self.name, "error",
                f"生成代码修改失败: {exc}",
                0, None
            )

    async def _generate_fixes(
        self,
        llm,
        repo_path: str,
        branch: str,
        suggestions: list[dict],
        file_contents: dict | None,
    ) -> list[CodeFix]:
        """基于优化建议生成代码修改方案。

        策略：
        1. 直接使用 suggestions 中已有的 code_fix（SuggestionAgent 已生成）
        2. 仅在 code_fix 为空时调用 LLM（传入 file_contents 作为上下文）
        3. 不再用关键词猜测文件路径（之前方案会产生大量 404）
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        fixes: list[CodeFix] = []
        need_llm: list[dict] = []

        for s in suggestions[:5]:
            existing = s.get("code_fix") or {}
            original = str(existing.get("original", "")).strip()
            updated = str(existing.get("updated", "")).strip()

            if original or updated:
                fixes.append(CodeFix(
                    file=str(existing.get("file", "")),
                    type=str(existing.get("type", "replace")),
                    original=original,
                    updated=updated,
                    reason=str(existing.get("reason", "")),
                ))
            else:
                need_llm.append(s)

        if not need_llm:
            return fixes

        # 构建上下文：直接用 file_contents（由 SuggestionAgent 传入的完整文件内容）
        context_parts = [f"仓库: {repo_path}@{branch}\n"]
        if file_contents:
            for fpath, content in list(file_contents.items())[:10]:
                fname = fpath.split("/")[-1]
                context_parts.append(f"\n-- [{fname}] --")
                context_parts.append(content[:3000])

        for i, s in enumerate(need_llm, 1):
            context_parts.append(f"\n【建议 {i}】")
            context_parts.append(f"  标题: {s.get('title', '')}")
            context_parts.append(f"  描述: {s.get('description', '')[:200]}")

        context = "\n".join(context_parts)

        system_prompt = """你是一位资深软件工程师，正在根据代码审查建议生成代码修改方案。

请分析以下优化建议，返回 JSON 格式的代码修改方案数组。

返回格式（直接返回 JSON 数组，不要 markdown 包裹）：
```json
[
  {
    "file": "src/utils/helper.ts",
    "type": "replace",
    "original": "// 原代码（精确字符串）",
    "updated": "// 修改后的代码",
    "reason": "修改原因说明"
  }
]
```

type 可选值：
- replace: 替换一段代码
- insert: 在指定位置后插入新代码
- delete: 删除指定代码

重要规则：
1. original 必须是文件中存在的精确代码字符串，用于定位修改位置
2. 如果不确定精确代码，type 使用 "insert"，original 写空字符串
3. 只返回有把握的修改，不要猜测
4. 确保 JSON 格式正确"""

        user_prompt = f"""请为以下优化建议生成代码修改方案：

{context}

直接返回 JSON 数组（最多 {len(need_llm)} 个修改）："""

        try:
            response = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ])
            llm_fixes = self._parse_fixes(response.content.strip())
            fixes.extend(llm_fixes)
        except Exception as exc:
            _logger.warning(f"[FixGeneratorAgent] LLM 生成失败，降级保留已有 fixes: {exc}")

        return fixes

    def _parse_fixes(self, content: str) -> list[CodeFix]:
        """解析 LLM 返回的 JSON 修改方案。"""
        text = content.strip()

        # 尝试直接解析
        if text.startswith("["):
            try:
                data = json.loads(text)
                if isinstance(data, list):
                    return self._normalize_fixes(data)
            except json.JSONDecodeError:
                pass

        # 尝试从 markdown 代码块中提取
        match = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", text)
        if match:
            try:
                data = json.loads(match.group(1))
                if isinstance(data, list):
                    return self._normalize_fixes(data)
            except json.JSONDecodeError:
                pass

        # 尝试提取所有完整对象
        try:
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
                fixes = []
                for obj_str in complete_objs:
                    try:
                        obj = json.loads(obj_str)
                        if isinstance(obj, dict) and obj.get("file"):
                            fixes.append(obj)
                    except Exception:
                        pass
                if fixes:
                    return self._normalize_fixes(fixes)
        except Exception:
            pass

        return []

    def _normalize_fixes(self, raw: list) -> list[CodeFix]:
        """标准化修改方案列表。"""
        fixes = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            file = item.get("file", "").strip()
            if not file:
                continue

            fix_type = item.get("type", "replace")
            if fix_type not in ("replace", "insert", "delete"):
                fix_type = "replace"

            fixes.append(CodeFix(
                file=file,
                type=fix_type,
                original=str(item.get("original", "")),
                updated=str(item.get("updated", "")),
                reason=str(item.get("reason", "")),
            ))

        return fixes
