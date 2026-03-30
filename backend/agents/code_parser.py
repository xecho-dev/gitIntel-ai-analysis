"""CodeParserAgent — 使用 tree-sitter 对仓库进行 AST 分析，提取结构化代码信息。"""
import asyncio
import os
from collections import defaultdict
from typing import AsyncGenerator

from .base_agent import AgentEvent, BaseAgent, _make_event


_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".php": "php",
    ".zig": "zig",
    ".dart": "dart",
}

# ── 跨语言的语义边界节点类型 ─────────────────────────────────────────
STRUCTURE_TYPES = {
    "function_declaration", "function_definition", "function",
    "method_declaration", "method_definition", "method",
    "class_declaration", "class_definition", "class",
    "struct_declaration", "struct", "interface_declaration", "interface",
    "module", "namespace",
    "arrow_function", "lambda_expression",
    "generator_function_declaration",
}

# ── 通用函数/类/导入节点类型（用于统计） ──────────────────────────────
FUNC_TYPES = {
    "function_declaration", "function_definition", "function",
    "method_declaration", "method_definition", "method",
    "arrow_function", "lambda_expression", "generator_function_declaration",
}
CLASS_TYPES = {
    "class_declaration", "class_definition", "class",
    "struct_declaration", "struct", "interface_declaration", "interface",
}
IMPORT_TYPES = {
    "import_statement", "import_from_statement",
    "import_declaration", "import", "require_call",
}


def _load_ts_parser(language: str):
    """懒加载 tree-sitter 语言解析器。"""
    try:
        from tree_sitter_languages import get_parser
        return get_parser(language)
    except ImportError:
        return None


class CodeParserAgent(BaseAgent):
    """遍历仓库源码文件，执行 AST 解析，提取结构化指标。"""

    name = "code_parser"

    async def stream(
        self,
        repo_path: str,
        branch: str = "main",
        file_contents: dict[str, str] | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """对仓库执行 AST 分析，yield 进度事件。

        Args:
            repo_path: 仓库标识（owner/repo）。
            branch: 分支名（仅参考）。
            file_contents: 可选，GitHub API 直接返回的文件内容字典；
                           若不提供则从 repo_path 目录读取（本地开发兼容）。
        """
        yield _make_event(
            self.name, "status",
            "正在扫描源码文件…", 10, None
        )

        files = await self._walk_source_files(repo_path)
        if not files:
            yield _make_event(
                self.name, "error",
                "未找到可分析的源码文件", 0, None
            )
            return

        yield _make_event(
            self.name, "progress",
            f"共扫描 {len(files)} 个文件，开始 AST 解析…", 30, None
        )

        if file_contents is not None:
            # ── GitHub API 模式：直接使用内存中的文件内容 ─────────────
            files = [
                {"path": path, "content": content}
                for path, content in file_contents.items()
            ]
            if not files:
                yield _make_event(self.name, "error", "未获取到任何文件内容", 0, None)
                return
            yield _make_event(
                self.name, "progress",
                f"共 {len(files)} 个文件，开始 AST 解析…", 30, None
            )
            try:
                stats = await self._analyze_inmemory_files(files)
            except Exception as exc:
                yield _make_event(
                    self.name, "error", f"AST 解析失败: {exc}", 0, {"exception": str(exc)}
                )
                return
        else:
            # ── 本地开发模式：从磁盘读取 ─────────────────────────────────
            files = await self._walk_source_files(repo_path)
            if not files:
                yield _make_event(self.name, "error", "未找到可分析的源码文件", 0, None)
                return
            yield _make_event(
                self.name, "progress",
                f"共扫描 {len(files)} 个文件，开始 AST 解析…", 30, None
            )
            try:
                stats = await self._analyze_files(files)
            except Exception as exc:
                yield _make_event(
                    self.name, "error", f"AST 解析失败: {exc}", 0, {"exception": str(exc)}
                )
                return

        yield _make_event(
            self.name, "progress",
            "AST 分析完成，正在聚合统计…", 80, None
        )

        yield _make_event(
            self.name, "result", "代码结构解析完成",
            100, stats
        )

    # ─── 内部实现 ───────────────────────────────────────────────

    @staticmethod
    async def _walk_source_files(root: str) -> list[str]:
        """返回所有可进行 AST 分析的源文件路径。"""
        IGNORE = frozenset({
            "node_modules", ".git", "__pycache__", ".venv", "venv",
            "dist", "build", ".next", ".nuxt", "target", ".pytest_cache",
            ".mypy_cache", ".ruff_cache", "site-packages",
        })

        def _do() -> list[str]:
            files: list[str] = []
            for dirpath, dirs, filenames in os.walk(root):
                dirs[:] = [d for d in dirs if d not in IGNORE and not d.startswith(".")]
                for fname in filenames:
                    ext = os.path.splitext(fname)[1]
                    if ext in _EXT_TO_LANG:
                        files.append(os.path.join(dirpath, fname))
            return files

        return await asyncio.to_thread(_do)

    @staticmethod
    async def _analyze_inmemory_files(files: list[dict], max_chunk_lines: int = 200) -> dict:
        """批量分析内存中的文件内容，提取结构化指标 + 语义分块（GitHub API 模式）。

        Args:
            files: [{"path": str, "content": str}, ...]
            max_chunk_lines: 语义分块的最大行数限制
        """
        def _do() -> dict:
            lang_stats: dict[str, dict] = defaultdict(lambda: {
                "files": 0, "functions": 0, "classes": 0,
                "imports": 0, "total_lines": 0,
            })
            total_functions = 0
            total_classes = 0
            largest_files: list[dict] = []
            chunked_files: dict[str, list[dict]] = {}

            for item in files:
                fpath = item["path"]
                content = item["content"]
                ext = os.path.splitext(fpath)[1]
                lang = _EXT_TO_LANG.get(ext)
                if not lang:
                    continue

                try:
                    source = content.encode("utf-8", errors="replace")
                    lines = source.count(b"\n") + 1
                except Exception:
                    lines = 0

                functions, classes, imports = CodeParserAgent._parse_file(source, lang)
                total_functions += functions
                total_classes += classes

                lang_stats[lang]["files"] += 1
                lang_stats[lang]["functions"] += functions
                lang_stats[lang]["classes"] += classes
                lang_stats[lang]["imports"] += imports
                lang_stats[lang]["total_lines"] += lines

                if lines > 50:
                    largest_files.append({
                        "path": fpath.replace("\\", "/"),
                        "lines": lines,
                        "functions": functions,
                        "language": lang,
                    })

                # 语义分块
                if content and content.strip() and lines > 10:
                    chunks = CodeParserAgent._semantic_chunk_file(source, lang, max_chunk_lines)
                    if chunks:
                        chunked_files[fpath.replace("\\", "/")] = chunks

            largest_files.sort(key=lambda x: x["lines"], reverse=True)
            largest_files = largest_files[:10]

            total_chunks = sum(len(v) for v in chunked_files.values())

            return {
                "total_files": len(files),
                "total_functions": total_functions,
                "total_classes": total_classes,
                "language_stats": dict(lang_stats),
                "largest_files": largest_files,
                "chunked_files": chunked_files,
                "total_chunks": total_chunks,
            }

        return await asyncio.to_thread(_do)

    @staticmethod
    async def _analyze_files(files: list[str], max_chunk_lines: int = 200) -> dict:
        """批量分析文件，提取结构化指标 + 语义分块。

        Args:
            files: 文件路径列表
            max_chunk_lines: 语义分块的最大行数限制
        """
        def _do() -> dict:
            lang_stats: dict[str, dict] = defaultdict(lambda: {
                "files": 0, "functions": 0, "classes": 0,
                "imports": 0, "total_lines": 0,
            })
            total_functions = 0
            total_classes = 0
            largest_files: list[dict] = []
            chunked_files: dict[str, list[dict]] = {}

            for fpath in files:
                ext = os.path.splitext(fpath)[1]
                lang = _EXT_TO_LANG.get(ext)
                if not lang:
                    continue

                try:
                    with open(fpath, "rb") as f:
                        source = f.read()
                except OSError:
                    continue

                try:
                    lines = source.count(b"\n") + 1
                except Exception:
                    lines = 0

                functions, classes, imports = CodeParserAgent._parse_file(source, lang)
                total_functions += functions
                total_classes += classes

                lang_stats[lang]["files"] += 1
                lang_stats[lang]["functions"] += functions
                lang_stats[lang]["classes"] += classes
                lang_stats[lang]["imports"] += imports
                lang_stats[lang]["total_lines"] += lines

                if lines > 50:
                    largest_files.append({
                        "path": fpath.replace("\\", "/"),
                        "lines": lines,
                        "functions": functions,
                        "language": lang,
                    })

                # 语义分块
                if lines > 10:
                    chunks = CodeParserAgent._semantic_chunk_file(source, lang, max_chunk_lines)
                    if chunks:
                        chunked_files[fpath.replace("\\", "/")] = chunks

            # 按行数排序，取 TOP 10
            largest_files.sort(key=lambda x: x["lines"], reverse=True)
            largest_files = largest_files[:10]

            total_chunks = sum(len(v) for v in chunked_files.values())

            return {
                "total_files": len(files),
                "total_functions": total_functions,
                "total_classes": total_classes,
                "language_stats": dict(lang_stats),
                "largest_files": largest_files,
                "chunked_files": chunked_files,
                "total_chunks": total_chunks,
            }

        return await asyncio.to_thread(_do)

    # ─── 语义分块（基于 AST 结构边界） ─────────────────────────────────

    @staticmethod
    def _semantic_chunk_file(source: bytes, lang: str, max_lines: int = 200) -> list[dict]:
        """基于 AST 结构在语义边界拆分代码，保持函数/类完整。

        策略：
        1. 优先在函数/类定义边界拆分
        2. 如果单个结构超过 max_lines，在内部自然断点（空行、注释前）拆分
        3. 保留块的元数据（函数名、起始行等）

        Args:
            source: 源代码字节串
            lang: 语言标识（python, typescript, go...）
            max_lines: 最大行数限制（单个函数超限时内部再拆分）

        Returns:
            list[dict]: [{"chunk_id", "start_line", "end_line", "content", "function_name", ...}]
        """
        parser = _load_ts_parser(lang)
        if parser is None:
            return []

        try:
            tree = parser.parse(source)
        except Exception:
            return []

        source_lines = source.split(b"\n")
        total_lines = len(source_lines)

        # 收集所有结构定义节点（函数、类等）的行号范围
        boundaries: list[tuple[int, int, str]] = []  # (start_line, end_line, node_type)

        def collect_boundaries(node):
            if node.type in STRUCTURE_TYPES:
                start = node.start_point[0] + 1  # 转为 1-indexed
                end = node.end_point[0] + 1
                boundaries.append((start, end, node.type))
            for child in node.children:
                collect_boundaries(child)

        collect_boundaries(tree.root_node)
        boundaries.sort()

        # 合并重叠的相邻边界，构建语义块
        chunks: list[dict] = []
        chunk_id = 0

        if not boundaries:
            # 无结构定义，整个文件作为单个块
            content = b"\n".join(source_lines).decode("utf-8", errors="replace")
            return [{
                "chunk_id": 0,
                "start_line": 1,
                "end_line": total_lines,
                "content": content,
                "function_name": None,
                "node_type": "file",
                "total_chunks": 1,
            }]

        # 构建块：在相邻边界之间划分
        current_start = 1

        for start, end, node_type in boundaries:
            if start > current_start:
                # 块之间有未归属的内容（import、顶域变量等），归入前一个块
                pass

            chunk_lines = source_lines[current_start - 1: end]
            content = b"\n".join(chunk_lines).decode("utf-8", errors="replace")

            # 获取函数/类名称
            func_name = CodeParserAgent._extract_node_name(tree.root_node, start, end)

            chunks.append({
                "chunk_id": chunk_id,
                "start_line": current_start,
                "end_line": end,
                "content": content,
                "function_name": func_name,
                "node_type": node_type,
            })
            chunk_id += 1
            current_start = end + 1

        # 处理末尾未归属的内容
        if current_start <= total_lines:
            chunk_lines = source_lines[current_start - 1:]
            content = b"\n".join(chunk_lines).decode("utf-8", errors="replace")
            chunks.append({
                "chunk_id": chunk_id,
                "start_line": current_start,
                "end_line": total_lines,
                "content": content,
                "function_name": None,
                "node_type": "tail",
            })
            chunk_id += 1

        # 处理超大块：递归拆分超过 max_lines 的块
        final_chunks: list[dict] = []
        for chunk in chunks:
            line_count = chunk["end_line"] - chunk["start_line"] + 1
            if line_count > max_lines:
                # 递归拆分
                sub_chunks = CodeParserAgent._split_large_chunk(chunk, max_lines)
                final_chunks.extend(sub_chunks)
            else:
                final_chunks.append(chunk)

        # 更新 total_chunks
        total = len(final_chunks)
        for c in final_chunks:
            c["total_chunks"] = total

        # 重新编号
        for i, c in enumerate(final_chunks):
            c["chunk_id"] = i

        return final_chunks

    @staticmethod
    def _extract_node_name(tree, target_start: int, target_end: int) -> str | None:
        """从 AST 中提取指定行范围内的函数/类名称。"""
        source = tree.text if hasattr(tree, "text") else b""
        lines = source.split(b"\n") if source else []

        def find_name(node):
            if node.type in STRUCTURE_TYPES:
                start = node.start_point[0] + 1
                end = node.end_point[0] + 1
                if start == target_start:
                    # 查找函数/类名（通常是第一个子节点的 text）
                    for child in node.children:
                        if child.type not in ("def", "class", "function", "async", "await", "export", "public", "private", "static", "("):
                            try:
                                name_bytes = child.text
                                return name_bytes.decode("utf-8", errors="replace")
                            except Exception:
                                pass
                    return None
            for child in node.children:
                result = find_name(child)
                if result:
                    return result
            return None

        return find_name(tree)

    @staticmethod
    def _split_large_chunk(chunk: dict, max_lines: int) -> list[dict]:
        """将超大块拆分为更小的子块，在自然断点（空行、注释）处拆分。"""
        lines = chunk["content"].split("\n")
        sub_chunks: list[dict] = []
        sub_id = 0
        current_lines: list[str] = []
        current_start = chunk["start_line"]

        for i, line in enumerate(lines):
            current_lines.append(line)
            line_num = chunk["start_line"] + i

            # 在自然断点处拆分
            should_split = (
                len(current_lines) >= max_lines and (
                    line.strip() == "" or  # 空行
                    line.strip().startswith("#") or  # 注释
                    line.strip().startswith("//") or  # 单行注释
                    line.strip().startswith("/*") or  # 块注释开始
                    line.strip().startswith("*/") or  # 块注释结束
                    line.strip().startswith('"""') or  # Python docstring
                    line.strip().startswith("'''") or
                    line.strip().startswith("}") or  # 代码块结束
                    (line.strip() and not line[0].isspace())  # 回到顶层缩进
                )
            )

            if should_split and len(current_lines) > max_lines // 2:
                sub_chunks.append({
                    "chunk_id": 0,  # 临时，稍后重新编号
                    "start_line": current_start,
                    "end_line": line_num,
                    "content": "\n".join(current_lines[:-1]),
                    "function_name": chunk.get("function_name"),
                    "node_type": chunk.get("node_type", "split"),
                })
                sub_id += 1
                current_lines = [line]
                current_start = line_num + 1

        # 处理剩余内容
        if current_lines:
            sub_chunks.append({
                "chunk_id": 0,
                "start_line": current_start,
                "end_line": chunk["end_line"],
                "content": "\n".join(current_lines),
                "function_name": chunk.get("function_name"),
                "node_type": chunk.get("node_type", "split"),
            })

        return sub_chunks

    @staticmethod
    def _parse_file(source: bytes, lang: str) -> tuple[int, int, int]:
        """使用 tree-sitter 解析单个文件，返回 (functions, classes, imports) 数量。"""
        parser = _load_ts_parser(lang)
        if parser is None:
            return 0, 0, 0

        try:
            tree = parser.parse(source)
        except Exception:
            return 0, 0, 0

        funcs = 0
        classes = 0
        imports = 0

        def walk(node):
            nonlocal funcs, classes, imports
            type_name = node.type

            if type_name in FUNC_TYPES:
                funcs += 1
            elif type_name in CLASS_TYPES:
                classes += 1
            elif type_name in IMPORT_TYPES:
                imports += 1

            for child in node.children:
                walk(child)

        walk(tree.root_node)
        return funcs, classes, imports
