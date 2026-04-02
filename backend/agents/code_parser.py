"""CodeParserAgent — 使用 tree-sitter 对仓库进行 AST 分析，提取结构化代码信息。"""
import asyncio
import os
import tree_sitter
from collections import defaultdict
from collections import defaultdict

from .base_agent import AgentEvent, BaseAgent, _make_event


_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
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

# 明确忽略的非源码扩展名（文件存在但不是有效源码）
_IGNORE_EXT: frozenset[str] = frozenset({
    ".ipynb",  # Jupyter Notebook — JSON 结构，tree-sitter 会无效遍历
    ".md", ".mdx",
    ".txt", ".rst",
    ".json", ".jsonc",
    ".yml", ".yaml", ".toml",
    ".xml", ".html", ".css", ".scss", ".sass", ".less",
    ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp",
    ".pdf", ".zip", ".tar", ".gz", ".rar",
    ".lock",  # package-lock.json, yarn.lock 等锁文件
    ".sh", ".bash", ".zsh",  # shell 脚本（可选，排除避免噪音）
    ".env", ".gitignore", ".dockerignore", ".editorconfig",
    ".gitmodules", ".gitattributes",
    ".csv", ".tsv",
    ".ico",
})


def _is_parseable_source(path: str) -> bool:
    """判断文件路径是否对应可解析的源码（排除常见非源码文件）。"""
    import os
    ext = os.path.splitext(path)[1].lower()
    if ext in _IGNORE_EXT:
        return False
    return True

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


# 每个语言对应独立包中的 language factory
# 格式: (模块名, 属性名)
_LANG_FACTORY: dict[str, tuple[str, str]] = {
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

# Parser 缓存（同一个 language 只创建一次）
_PARSER_CACHE: dict[str, object] = {}


def _load_ts_parser(language: str):
    """懒加载 tree-sitter 解析器，优先用独立语言包（绕过 tree_sitter_languages ABI 问题）。

    tree-sitter 0.24+ 的 language 包中每个 `language_*` 属性都是返回 tree_sitter.Language 实例的函数。
    """
    if language in _PARSER_CACHE:
        return _PARSER_CACHE[language]

    result = None

    # 方式一：独立语言包（推荐）
    if language in _LANG_FACTORY:
        mod_name, attr_name = _LANG_FACTORY[language]
        try:
            mod = __import__(mod_name, fromlist=[attr_name])
            lang_fn = getattr(mod, attr_name)
            capsule = lang_fn() if callable(lang_fn) else lang_fn
            ts_lang = tree_sitter.Language(capsule)
            parser = tree_sitter.Parser(ts_lang)
            _PARSER_CACHE[language] = parser
            return parser
        except Exception:
            pass

    # 方式二：tree_sitter_languages（fallback，可能因 ABI 不兼容而失败）
    try:
        from tree_sitter_languages import get_parser

        # get_parser 返回 tree_sitter.Parser，直接使用
        parser = get_parser(language)
        _PARSER_CACHE[language] = parser
        return parser
    except Exception:
        pass

    return None


class CodeParserAgent(BaseAgent):
    """遍历仓库源码文件，执行 AST 解析，提取结构化指标。"""

    name = "code_parser"

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
        import logging
        _logger = logging.getLogger("gitintel")

        def _do() -> dict:
            lang_stats: dict[str, dict] = defaultdict(lambda: {
                "files": 0, "functions": 0, "classes": 0,
                "imports": 0, "total_lines": 0,
            })
            total_functions = 0
            total_classes = 0
            largest_files: list[dict] = []
            chunked_files: dict[str, list[dict]] = {}
            skipped: list[str] = []

            for item in files:
                fpath = item["path"]

                # 扩展名过滤：跳过非源码文件
                if not _is_parseable_source(fpath):
                    skipped.append(fpath)
                    continue

                content = item["content"]
                ext = os.path.splitext(fpath)[1]
                lang = _EXT_TO_LANG.get(ext)
                if not lang:
                    skipped.append(fpath)
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
            _logger.debug(
                f"[code_parser] 完成：{len(files)} 个文件，"
                f"解析 {sum(s['files'] for s in lang_stats.values())} 个源码文件，"
                f"跳过 {len(skipped)} 个非源码: {skipped[:5]}"
            )

            return {
                "total_files": len(files),
                "parsed_files": sum(s["files"] for s in lang_stats.values()),
                "skipped_files": skipped,
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
        import logging
        _logger = logging.getLogger("gitintel")

        def _do() -> dict:
            lang_stats: dict[str, dict] = defaultdict(lambda: {
                "files": 0, "functions": 0, "classes": 0,
                "imports": 0, "total_lines": 0,
            })
            total_functions = 0
            total_classes = 0
            largest_files: list[dict] = []
            chunked_files: dict[str, list[dict]] = {}
            skipped: list[str] = []

            for fpath in files:
                # 扩展名过滤
                if not _is_parseable_source(fpath):
                    skipped.append(fpath)
                    continue

                ext = os.path.splitext(fpath)[1]
                lang = _EXT_TO_LANG.get(ext)
                if not lang:
                    skipped.append(fpath)
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
            _logger.debug(
                f"[code_parser] 完成：{len(files)} 个文件，"
                f"解析 {sum(s['files'] for s in lang_stats.values())} 个源码文件，"
                f"跳过 {len(skipped)} 个非源码: {skipped[:5]}"
            )

            return {
                "total_files": len(files),
                "parsed_files": sum(s["files"] for s in lang_stats.values()),
                "skipped_files": skipped,
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
