"""QualityAgent — 对仓库源码进行真实代码质量分析（圈复杂度、重复率、代码异味等）。

该 Agent 综合以下数据源进行 LLM 驱动的代码质量分析：
  1. tree-sitter AST 分析（圈复杂度、文件大小、重复率、测试覆盖）
  2. LLM（可选）：生成 MAINT/COMP/DUP/TEST/COUP 五维评分及洞察

输出新增 LLM 五维评分字段：
  - maint_score: 可维护性 0-100
  - comp_score:   复杂度   0-100
  - dup_score:    独特率   0-100
  - test_score:   测试覆盖 0-100
  - coup_score:   耦合度   0-100
"""
import asyncio
import logging
import os
import re
import tree_sitter
from collections import defaultdict
from typing import AsyncGenerator

from .base_agent import AgentEvent, BaseAgent, _make_event

_logger = logging.getLogger("gitintel")


# ── tree-sitter 解析器统一加载（复用 code_parser.py 的修复策略）─────────────
_LANG_PKG: dict[str, tuple[str, str]] = {
    "python": ("tree_sitter_python", "language"),
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
    "go": ("tree_sitter_go", "language"),
    "rust": ("tree_sitter_rust", "language"),
    "java": ("tree_sitter_java", "language"),
    "c": ("tree_sitter_c", "language"),
    "cpp": ("tree_sitter_cpp", "language"),
    "ruby": ("tree_sitter_ruby", "language"),
    "swift": ("tree_sitter_swift", "language"),
    "kotlin": ("tree_sitter_kotlin", "language"),
    "scala": ("tree_sitter_scala", "language"),
    "php": ("tree_sitter_php", "language"),
    "dart": ("tree_sitter_dart", "language"),
    "zig": ("tree_sitter_zig", "language"),
    "csharp": ("tree_sitter_csharp", "language"),
}
_Q_PARSER_CACHE: dict[str, object] = {}


def _q_load_parser(language: str):
    """懒加载 tree-sitter 解析器，优先独立包，fallback tree_sitter_languages。"""
    if language in _Q_PARSER_CACHE:
        return _Q_PARSER_CACHE[language]

    if language in _LANG_PKG:
        mod_name, attr_name = _LANG_PKG[language]
        try:
            mod = __import__(mod_name, fromlist=[attr_name])
            lang_fn = getattr(mod, attr_name)
            capsule = lang_fn() if callable(lang_fn) else lang_fn
            ts_lang = tree_sitter.Language(capsule)
            parser = tree_sitter.Parser(ts_lang)
            _Q_PARSER_CACHE[language] = parser
            return parser
        except Exception:
            pass

    try:
        from tree_sitter_languages import get_parser

        parser = get_parser(language)
        _Q_PARSER_CACHE[language] = parser
        return parser
    except Exception:
        pass

    return None


# ─── LLM 懒加载 ────────────────────────────────────────────────────────

def _get_llm():
    """懒加载 LLM client（通过统一工厂，支持 LangSmith 追踪）。"""
    from utils.llm_factory import get_llm
    return get_llm(temperature=0.2)


def _build_quality_context(
    py_metrics: dict,
    ts_metrics: dict,
    duplication: dict,
    test_info: dict,
    health_score: float,
    complexity_label: str,
    maintainability: str,
) -> str:
    """从各质量指标构建 LLM 分析上下文。"""
    import json

    parts = []

    # ── 整体评分 ────────────────────────────────────────────────────
    parts.append(
        f"【整体评分】\n"
        f"  健康度: {round(health_score, 1)}/100\n"
        f"  复杂度: {complexity_label}\n"
        f"  可维护性: {maintainability}"
    )

    # ── Python 指标 ─────────────────────────────────────────────────
    if py_metrics and "error" not in py_metrics:
        parts.append(
            f"【Python 质量】\n"
            f"  函数总数: {py_metrics.get('total_functions', 0)}\n"
            f"  类总数: {py_metrics.get('total_classes', 0)}\n"
            f"  平均圈复杂度: {py_metrics.get('avg_complexity', 0)}\n"
            f"  最大圈复杂度: {py_metrics.get('max_complexity', 0)}\n"
            f"  高复杂度函数(>10): {py_metrics.get('over_complexity_count', 0)}\n"
            f"  超长函数(>50行): {len(py_metrics.get('long_functions', []))}"
        )

    # ── TypeScript 指标 ─────────────────────────────────────────────
    if ts_metrics and "error" not in ts_metrics:
        parts.append(
            f"【TypeScript 质量】\n"
            f"  函数总数: {ts_metrics.get('total_functions', 0)}\n"
            f"  类总数: {ts_metrics.get('total_classes', 0)}\n"
            f"  平均圈复杂度: {ts_metrics.get('avg_complexity', 0)}\n"
            f"  最大圈复杂度: {ts_metrics.get('max_complexity', 0)}\n"
            f"  高复杂度函数(>10): {ts_metrics.get('over_complexity_count', 0)}"
        )

    # ── 重复率 ──────────────────────────────────────────────────────
    if duplication:
        parts.append(
            f"【代码重复】\n"
            f"  重复率: {duplication.get('score', 0)}%\n"
            f"  等级: {duplication.get('duplication_level', '?')}\n"
            f"  重复块数: {duplication.get('duplicated_blocks', 0)}"
        )

    # ── 测试覆盖 ────────────────────────────────────────────────────
    if test_info:
        parts.append(
            f"【测试覆盖】\n"
            f"  估算覆盖率: {test_info.get('estimated_coverage', 0)}%\n"
            f"  测试文件数: {test_info.get('test_files', 0)}\n"
            f"  源码文件数: {test_info.get('source_files', 0)}\n"
            f"  检测框架: {', '.join(test_info.get('test_frameworks', []) or ['未检测到'])}"
        )

    return "\n\n".join(parts) if parts else "（无可用质量数据）"


# ─── Agent ──────────────────────────────────────────────────────

class QualityAgent(BaseAgent):
    """分析代码质量：圈复杂度、文件大小、重复率、测试覆盖估算。"""

    name = "quality"

    async def stream(
        self,
        repo_path: str,
        branch: str = "main",
        file_contents: dict[str, str] | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        yield _make_event(self.name, "status", "正在扫描源码文件…", 10, None)

        if file_contents is not None:
            # ── GitHub API 模式 ───────────────────────────────────
            py_contents = {p: c for p, c in file_contents.items() if p.endswith(".py")}
            ts_contents = {p: c for p, c in file_contents.items()
                          if p.endswith((".ts", ".tsx", ".js", ".jsx"))}

            yield _make_event(
                self.name, "progress",
                f"扫描完成: {len(py_contents)} 个 Python 文件, "
                f"{len(ts_contents)} 个 TypeScript 文件",
                25, None
            )

            total_files = len(py_contents) + len(ts_contents)
            py_files_count = len(py_contents)
            ts_files_count = len(ts_contents)

            try:
                py_metrics = await self._analyze_python_inmemory(py_contents)
            except Exception as exc:
                py_metrics = {"error": str(exc)}

            try:
                ts_metrics = await self._analyze_typescript_inmemory(ts_contents)
            except Exception as exc:
                ts_metrics = {"error": str(exc)}

            try:
                duplication = await self._calc_duplication_inmemory(
                    {**py_contents, **ts_contents}
                )
            except Exception:
                duplication = {"score": 0, "duplicated_blocks": 0}

            try:
                test_info = self._estimate_test_coverage_inmemory(
                    py_contents, ts_contents
                )
            except Exception:
                test_info = {"estimated_coverage": 0, "test_files": 0}

        else:
            # ── 本地磁盘模式 ─────────────────────────────────────
            py_files = await self._walk_by_lang(repo_path, [".py"])
            ts_files = await self._walk_by_lang(repo_path, [".ts", ".tsx", ".js", ".jsx"])
            all_files = await self._walk_by_lang(repo_path, None)  # 总文件数
            total_files = len(all_files)
            py_files_count = len(py_files)
            ts_files_count = len(ts_files)

            yield _make_event(
                self.name, "progress",
                f"扫描完成: {py_files_count} 个 Python 文件, "
                f"{ts_files_count} 个 TypeScript 文件, "
                f"共 {total_files} 个文件",
                25, None
            )

            try:
                py_metrics = await self._analyze_python(py_files)
            except Exception as exc:
                py_metrics = {"error": str(exc)}

            try:
                ts_metrics = await self._analyze_typescript(ts_files)
            except Exception as exc:
                ts_metrics = {"error": str(exc)}

            try:
                duplication = await self._calc_duplication(py_files + ts_files)
            except Exception:
                duplication = {"score": 0, "duplicated_blocks": 0}

            try:
                test_info = await self._estimate_test_coverage(repo_path, py_files, ts_files)
            except Exception:
                test_info = {"estimated_coverage": 0, "test_files": 0}

        yield _make_event(
            self.name, "progress",
            "正在汇总质量评分…", 80, None
        )

        # 综合评分
        health_score = self._compute_health_score(py_metrics, ts_metrics, duplication, test_info)
        complexity_label = self._calc_complexity(health_score)
        maintainability = self._calc_maintainability(health_score)

        # ── LLM 五维评分（可选）───────────────────────────────────────
        llm = _get_llm()
        llm_metrics: dict = {}
        if llm is not None:
            yield _make_event(
                self.name, "progress",
                "正在调用 LLM 生成质量评分…", 85, None
            )
            try:
                llm_metrics = await self._generate_llm_insights(
                    llm,
                    py_metrics=py_metrics,
                    ts_metrics=ts_metrics,
                    duplication=duplication,
                    test_info=test_info,
                    health_score=health_score,
                    complexity_label=complexity_label,
                    maintainability=maintainability,
                )
                _logger.info(f"[QualityAgent] LLM 五维评分成功: {llm_metrics}")
            except Exception as exc:
                _logger.error(f"[QualityAgent] LLM 质量分析失败: {exc}")
                llm_metrics = {}

        result = {
            "health_score": round(health_score, 1),
            "test_coverage": test_info.get("estimated_coverage", 0),
            "complexity": complexity_label,
            "maintainability": maintainability,
            "python_metrics": py_metrics,
            "typescript_metrics": ts_metrics,
            "duplication": duplication,
            "test_info": test_info,
            "total_files": total_files,
            "python_files": py_files_count,
            "typescript_files": ts_files_count,
            # LLM 五维评分（0-100，越高越好）
            "maint_score": llm_metrics.get("maint_score", 70),
            "comp_score": llm_metrics.get("comp_score", 70),
            "dup_score": llm_metrics.get("dup_score", round(100 - (duplication.get("score", 0) if duplication else 0), 1)),
            "test_score": llm_metrics.get("test_score", test_info.get("estimated_coverage", 0)),
            "coup_score": llm_metrics.get("coup_score", 70),
            "llmPowered": bool(llm_metrics),
        }

        yield _make_event(
            self.name, "result", "代码质量分析完成",
            100, result
        )

    # ─── Python 分析 ───────────────────────────────────────────

    @staticmethod
    async def _walk_by_lang(root: str, extensions: list[str] | None) -> list[str]:
        IGNORE = frozenset({
            "node_modules", ".git", "__pycache__", ".venv", "venv",
            "dist", "build", ".next", ".nuxt", "target",
            ".pytest_cache", ".mypy_cache", ".ruff_cache",
        })

        def _do() -> list[str]:
            files = []
            for dirpath, dirs, names in os.walk(root):
                dirs[:] = [d for d in dirs if d not in IGNORE and not d.startswith(".")]
                for name in names:
                    if extensions is None or any(name.endswith(ext) for ext in extensions):
                        files.append(os.path.join(dirpath, name))
            return files

        return await asyncio.to_thread(_do)

    @staticmethod
    async def _analyze_python(files: list[str]) -> dict:
        parser = _q_load_parser("python")
        if not parser:
            return {"error": "tree-sitter-python not available"}

        def _do() -> dict:
            total_complexity = 0
            func_count = 0
            class_count = 0
            max_complexity = 0
            over_complexity_count = 0
            long_functions: list[dict] = []
            large_files: list[dict] = []

            for fpath in files:
                try:
                    source = _read_text(fpath)
                    lines = source.count("\n") + 1
                except Exception:
                    continue

                large_files.append({"path": fpath.replace("\\", "/"), "lines": lines})

                try:
                    tree = parser.parse(bytes(source, "utf-8"))
                except Exception:
                    continue

                # 统计函数、类、复杂度
                funcs, classes, complexity = QualityAgent._walk_python(tree.root_node, [], 0)
                func_count += funcs
                class_count += classes
                total_complexity += complexity
                if complexity > max_complexity:
                    max_complexity = complexity
                if complexity > 10:
                    over_complexity_count += 1
                # 统计超过 50 行的函数
                for chunk in source.split("\n\n"):
                    if len(chunk.split("\n")) > 50 and ("def " in chunk or "async def " in chunk):
                        fname = re.search(r"def\s+(\w+)", chunk)
                        long_functions.append({
                            "file": fpath.replace("\\", "/"),
                            "function": fname.group(1) if fname else "(unknown)",
                            "lines": len(chunk.split("\n")),
                        })

            avg_complexity = total_complexity / max(func_count, 1)
            large_files.sort(key=lambda x: x["lines"], reverse=True)
            long_functions.sort(key=lambda x: x["lines"], reverse=True)

            return {
                "total_functions": func_count,
                "total_classes": class_count,
                "avg_complexity": round(avg_complexity, 2),
                "max_complexity": max_complexity,
                "over_complexity_count": over_complexity_count,  # > 10
                "long_functions": long_functions[:10],
                "large_files": large_files[:10],
            }

        return await asyncio.to_thread(_do)

    @staticmethod
    def _walk_python(node, path: list, depth: int) -> tuple[int, int, int]:
        """返回 (function_count, class_count, total_complexity)。"""
        funcs = 0
        classes = 0
        complexity = 0

        COMPLEXITY_NODES = {
            "if_statement", "elif_clause",
            "for_statement", "for_in_statement",
            "while_statement", "with_statement",
            "except_clause", "try_statement",
            "conditional_expression",
            "and_operator", "or_operator",
        }

        if node.type == "function_definition":
            local_complexity = 1
            for child in node.children:
                if child.type in COMPLEXITY_NODES:
                    local_complexity += 1
            funcs = 1
            complexity = local_complexity
        elif node.type == "class_definition":
            classes = 1

        for child in node.children:
            f, c, comp = QualityAgent._walk_python(child, path + [node.type], depth + 1)
            funcs += f
            classes += c
            complexity += comp

        return funcs, classes, complexity

    # ─── In-memory variants（GitHub API 模式） ─────────────────

    @staticmethod
    async def _analyze_python_inmemory(contents: dict[str, str]) -> dict:
        """分析内存中的 Python 文件内容（GitHub API 模式）。"""
        parser = _q_load_parser("python")
        if not parser:
            return {"error": "tree-sitter-python not available"}

        def _do() -> dict:
            total_complexity = 0
            func_count = 0
            class_count = 0
            max_complexity = 0
            over_complexity_count = 0
            long_functions: list[dict] = []
            large_files: list[dict] = []

            for fpath, source in contents.items():
                lines = source.count("\n") + 1
                large_files.append({"path": fpath.replace("\\", "/"), "lines": lines})

                try:
                    tree = parser.parse(bytes(source, "utf-8"))
                except Exception:
                    continue

                funcs, classes, complexity = QualityAgent._walk_python(tree.root_node, [], 0)
                func_count += funcs
                class_count += classes
                total_complexity += complexity
                if complexity > max_complexity:
                    max_complexity = complexity
                if complexity > 10:
                    over_complexity_count += 1

                for chunk in source.split("\n\n"):
                    if len(chunk.split("\n")) > 50 and ("def " in chunk or "async def " in chunk):
                        fname = re.search(r"def\s+(\w+)", chunk)
                        long_functions.append({
                            "file": fpath.replace("\\", "/"),
                            "function": fname.group(1) if fname else "(unknown)",
                            "lines": len(chunk.split("\n")),
                        })

            avg_complexity = total_complexity / max(func_count, 1)
            large_files.sort(key=lambda x: x["lines"], reverse=True)
            long_functions.sort(key=lambda x: x["lines"], reverse=True)

            return {
                "total_functions": func_count,
                "total_classes": class_count,
                "avg_complexity": round(avg_complexity, 2),
                "max_complexity": max_complexity,
                "over_complexity_count": over_complexity_count,
                "long_functions": long_functions[:10],
                "large_files": large_files[:10],
            }

        return await asyncio.to_thread(_do)

    @staticmethod
    async def _analyze_typescript_inmemory(contents: dict[str, str]) -> dict:
        """分析内存中的 TypeScript 文件内容（GitHub API 模式）。"""
        parser = _q_load_parser("typescript")
        if not parser:
            return {"error": "tree-sitter-typescript not available"}

        def _do() -> dict:
            total_complexity = 0
            func_count = 0
            class_count = 0
            max_complexity = 0
            over_complexity_count = 0
            large_files: list[dict] = []

            for fpath, source in contents.items():
                lines = source.count("\n") + 1
                large_files.append({"path": fpath.replace("\\", "/"), "lines": lines})

                try:
                    tree = parser.parse(bytes(source, "utf-8"))
                except Exception:
                    continue

                funcs, classes, complexity = QualityAgent._walk_ts(tree.root_node)
                func_count += funcs
                class_count += classes
                total_complexity += complexity
                if complexity > max_complexity:
                    max_complexity = complexity
                if complexity > 10:
                    over_complexity_count += 1

            avg_complexity = total_complexity / max(func_count, 1)
            large_files.sort(key=lambda x: x["lines"], reverse=True)

            return {
                "total_functions": func_count,
                "total_classes": class_count,
                "avg_complexity": round(avg_complexity, 2),
                "max_complexity": max_complexity,
                "over_complexity_count": over_complexity_count,
                "large_files": large_files[:10],
            }

        return await asyncio.to_thread(_do)

    @staticmethod
    async def _calc_duplication_inmemory(
        contents: dict[str, str], sample_limit: int = 80
    ) -> dict:
        """用简化 N-gram (3 行块) 哈希检测重复（内存模式）。"""
        def _do() -> dict:
            sampled = list(contents.items())[:sample_limit]
            line_hashes: dict[int, int] = defaultdict(int)
            total_blocks = 0

            for _, source in sampled:
                lines = [
                    l.strip()
                    for l in source.splitlines()
                    if l.strip() and not l.strip().startswith(("#", "//", "/*", "*", "*/"))
                ]
                for i in range(len(lines) - 2):
                    block = "\n".join(lines[i: i + 3])
                    h = hash(block)
                    if len(block) > 15:
                        line_hashes[h] += 1
                        total_blocks += 1

            duplicated = sum(1 for cnt in line_hashes.values() if cnt > 2)
            dup_rate = (duplicated / max(total_blocks, 1)) * 100

            return {
                "score": round(min(dup_rate, 100), 1),
                "duplicated_blocks": duplicated,
                "total_blocks_checked": total_blocks,
                "duplication_level": "Low" if dup_rate < 5 else ("Medium" if dup_rate < 15 else "High"),
            }

        return await asyncio.to_thread(_do)

    @staticmethod
    def _estimate_test_coverage_inmemory(
        py_contents: dict[str, str], ts_contents: dict[str, str]
    ) -> dict:
        """估算测试覆盖率（内存模式）。"""
        test_pattern = re.compile(
            r"(^|/)test[_\-.]|^test[s]?/|^tests?/|_test\.py|_tests\.py|"
            r"\.spec\.(ts|tsx|js|jsx)|\.test\.(ts|tsx|js|jsx)|"
            r"__tests?__/"
        )
        src_pattern = re.compile(r"(^|/)src/|^lib/|^app/|^components?/|^pages?/")

        py_test = sum(1 for f in py_contents if test_pattern.search(f))
        ts_test = sum(1 for f in ts_contents if test_pattern.search(f))
        py_src = sum(1 for f in py_contents if src_pattern.search(f))
        ts_src = sum(1 for f in ts_contents if src_pattern.search(f))

        total_src = max(py_src + ts_src, 1)
        total_test = py_test + ts_test
        ratio = (total_test / total_src) * 100
        estimated = min(round(ratio, 1), 95.0)

        frameworks: list[str] = []
        all_contents = {**py_contents, **ts_contents}
        for content in list(all_contents.values())[:20]:
            c = content[:500]
            if "pytest" in c:
                frameworks.append("pytest")
            if "unittest" in c:
                frameworks.append("unittest")
            if "@testing-library" in c:
                frameworks.append("Jest/Testing Library")
            if "vitest" in c:
                frameworks.append("Vitest")
            if "jest" in c:
                frameworks.append("Jest")

        return {
            "estimated_coverage": estimated,
            "test_files": total_test,
            "source_files": total_src,
            "test_frameworks": list(dict.fromkeys(frameworks)),
        }

    # ─── TypeScript 分析 ───────────────────────────────────────

    @staticmethod
    async def _analyze_typescript(files: list[str]) -> dict:
        parser = _q_load_parser("typescript")
        if not parser:
            return {"error": "tree-sitter-typescript not available"}

        def _do() -> dict:
            total_complexity = 0
            func_count = 0
            class_count = 0
            max_complexity = 0
            over_complexity_count = 0
            large_files: list[dict] = []

            for fpath in files:
                try:
                    source = _read_text(fpath)
                    lines = source.count("\n") + 1
                except Exception:
                    continue

                large_files.append({"path": fpath.replace("\\", "/"), "lines": lines})

                try:
                    tree = parser.parse(bytes(source, "utf-8"))
                except Exception:
                    continue

                funcs, classes, complexity = QualityAgent._walk_ts(tree.root_node)
                func_count += funcs
                class_count += classes
                total_complexity += complexity
                if complexity > max_complexity:
                    max_complexity = complexity
                if complexity > 10:
                    over_complexity_count += 1

            avg_complexity = total_complexity / max(func_count, 1)
            large_files.sort(key=lambda x: x["lines"], reverse=True)

            return {
                "total_functions": func_count,
                "total_classes": class_count,
                "avg_complexity": round(avg_complexity, 2),
                "max_complexity": max_complexity,
                "over_complexity_count": over_complexity_count,
                "large_files": large_files[:10],
            }

        return await asyncio.to_thread(_do)

    @staticmethod
    def _walk_ts(node) -> tuple[int, int, int]:
        """返回 (function_count, class_count, total_complexity)。"""
        funcs = 0
        classes = 0
        complexity = 0

        COMPLEXITY_NODES = {
            "if_statement", "else_clause",
            "for_statement", "for_in_statement", "for_of_statement",
            "while_statement", "do_statement",
            "switch_statement", "case_statement",
            "catch_clause", "try_statement",
            "conditional_expression",
            "binary_expression",  # && or ||
        }

        IS_FUNC = {
            "function_declaration", "method_declaration",
            "arrow_function", "function",
        }
        IS_CLASS = {
            "class_declaration", "class",
            "interface_declaration", "abstract_class_declaration",
        }

        if node.type in IS_FUNC:
            local_comp = 1
            for child in node.children:
                if child.type in COMPLEXITY_NODES:
                    local_comp += 1
            funcs = 1
            complexity = local_comp
        elif node.type in IS_CLASS:
            classes = 1

        for child in node.children:
            f, c, comp = QualityAgent._walk_ts(child)
            funcs += f
            classes += c
            complexity += comp

        return funcs, classes, complexity

    # ─── 重复率检测 ────────────────────────────────────────────

    @staticmethod
    async def _calc_duplication(files: list[str], sample_limit: int = 80) -> dict:
        """用简化 N-gram (3 行块) 哈希检测重复。"""
        def _do() -> dict:
            # 只采样前 sample_limit 个文件，避免太慢
            sampled = files[:sample_limit]
            line_hashes: dict[str, int] = defaultdict(int)
            block_counts: dict[str, int] = defaultdict(int)
            total_blocks = 0

            for fpath in sampled:
                try:
                    source = _read_text(fpath)
                except Exception:
                    continue
                lines = [
                    l.strip()
                    for l in source.splitlines()
                    if l.strip() and not l.strip().startswith(("#", "//", "/*", "*", "*/"))
                ]
                for i in range(len(lines) - 2):
                    block = "\n".join(lines[i : i + 3])
                    h = hash(block)
                    if len(block) > 15:  # 忽略太短的块
                        line_hashes[h] += 1
                        block_counts[block] += 1
                        total_blocks += 1

            # 出现 > 2 次的块视为重复
            duplicated = sum(1 for cnt in line_hashes.values() if cnt > 2)
            dup_rate = (duplicated / max(total_blocks, 1)) * 100

            return {
                "score": round(min(dup_rate, 100), 1),
                "duplicated_blocks": duplicated,
                "total_blocks_checked": total_blocks,
                "duplication_level": "Low" if dup_rate < 5 else ("Medium" if dup_rate < 15 else "High"),
            }

        return await asyncio.to_thread(_do)

    # ─── 测试覆盖率估算 ────────────────────────────────────────

    @staticmethod
    async def _estimate_test_coverage(
        repo_path: str, py_files: list[str], ts_files: list[str]
    ) -> dict:
        def _do() -> dict:
            # 统计测试文件数量（常见命名模式）
            test_pattern = re.compile(
                r"(^|/)test[_\-.]|^test[s]?/|^tests?/|_test\.py|_tests\.py|"
                r"\.spec\.(ts|tsx|js|jsx)|\.test\.(ts|tsx|js|jsx)|"
                r"__tests?__/"
            )
            src_pattern = re.compile(
                r"(^|/)src/|^lib/|^app/|^components?/|^pages?/"
            )

            py_test = sum(1 for f in py_files if test_pattern.search(f))
            ts_test = sum(1 for f in ts_files if test_pattern.search(f))
            py_src = sum(1 for f in py_files if src_pattern.search(f))
            ts_src = sum(1 for f in ts_files if src_pattern.search(f))

            total_src = max(py_src + ts_src, 1)
            total_test = py_test + ts_test

            # 覆盖率估算：test/src 比值 * 100，上限 95%
            ratio = (total_test / total_src) * 100
            estimated = min(round(ratio, 1), 95.0)

            # 检测测试框架
            frameworks: list[str] = []
            for f in py_files + ts_files:
                content = _read_text(f)[:500]
                if "pytest" in content:
                    frameworks.append("pytest")
                if "unittest" in content:
                    frameworks.append("unittest")
                if "@testing-library" in content:
                    frameworks.append("Jest/Testing Library")
                if "vitest" in content:
                    frameworks.append("Vitest")
                if "jest" in content:
                    frameworks.append("Jest")

            return {
                "estimated_coverage": estimated,
                "test_files": total_test,
                "source_files": total_src,
                "test_frameworks": list(dict.fromkeys(frameworks)),
            }

        return await asyncio.to_thread(_do)

    # ─── 综合评分 ───────────────────────────────────────────────

    @staticmethod
    def _compute_health_score(
        py_metrics: dict, ts_metrics: dict,
        duplication: dict, test_info: dict
    ) -> float:
        score = 100.0

        # 复杂度惩罚
        for m in [py_metrics, ts_metrics]:
            if "avg_complexity" in m:
                if m["avg_complexity"] > 10:
                    score -= min((m["avg_complexity"] - 10) * 3, 30)
                elif m["avg_complexity"] > 5:
                    score -= (m["avg_complexity"] - 5) * 1.5

        # 重复率惩罚
        dup_score = duplication.get("score", 0)
        if dup_score > 15:
            score -= min((dup_score - 15) * 1.5, 20)
        elif dup_score > 5:
            score -= (dup_score - 5) * 0.8

        # 测试覆盖惩罚
        coverage = test_info.get("estimated_coverage", 0)
        if coverage < 30:
            score -= (30 - coverage) * 0.5
        elif coverage > 80:
            score += 5  # 奖励

        return max(min(score, 100), 0)

    # ─── LLM 五维评分 ───────────────────────────────────────────────

    @staticmethod
    async def _generate_llm_insights(
        llm,
        py_metrics: dict,
        ts_metrics: dict,
        duplication: dict,
        test_info: dict,
        health_score: float,
        complexity_label: str,
        maintainability: str,
    ) -> dict:
        """调用 LLM 生成五维质量评分（可维护性/复杂度/独特率/测试覆盖/耦合度）。

        Returns:
            dict: 包含 maint_score, comp_score, dup_score, test_score, coup_score (0-100)
        """
        import json, re

        context = _build_quality_context(
            py_metrics, ts_metrics, duplication, test_info,
            health_score, complexity_label, maintainability,
        )

        prompt = (
            "你是一位资深代码质量审计专家，正在分析仓库代码质量。\n\n"
            f"质量分析数据：\n{context}\n\n"
            "请基于以上真实代码数据，生成五维质量评分（直接返回 JSON，不要 markdown 包裹）：\n"
            "{\n"
            '  "maint_score": 数字(0-100，可维护性得分，越高越好，综合考虑代码复杂度、圈复杂度、超长函数数、高复杂度函数数)，\n'
            '  "comp_score": 数字(0-100，复杂度合理度得分，越高说明复杂度越可控，参考平均圈复杂度和文件大小)，\n'
            '  "dup_score": 数字(0-100，独特率得分，由重复率推导，重复率越低得分越高，计算公式：100 - 重复率%)，\n'
            '  "test_score": 数字(0-100，测试覆盖得分，综合测试文件比例和检测到的测试框架)，\n'
            '  "coup_score": 数字(0-100，耦合度合理度得分，基于语言数量、框架数量、组件数估算，越高说明模块化越好)\n'
            "}"
        )

        try:
            from langchain_core.messages import HumanMessage
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            content = response.content.strip()

            try:
                match = re.search(r"\{[\s\S]*\}", content)
                if match:
                    return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        except Exception:
            pass

        return {}
