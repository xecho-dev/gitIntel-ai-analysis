"""
代码分析工具集 — 封装 AST 解析、复杂度计算、代码异味检测等，供 Agent 调用。

工具列表：
  - parse_file_ast:     解析文件 AST，提取函数/类/导入
  - calculate_complexity: 计算代码片段的圈复杂度（多语言支持）
  - detect_code_smells:   检测代码异味（过长函数、深度嵌套等，多语言支持）
  - summarize_code_file:  生成代码文件的核心摘要（快速了解文件，多语言支持）
  - detect_imports:       从代码中提取所有 import 语句（多语言支持）
  - detect_dependencies:  识别代码中的外部依赖使用情况（多语言支持）

这些工具让 Agent 能够动态选择分析哪些文件，而非一次性分析全部。
"""
import json
import re
from typing import Any

from langchain_core.tools import tool

# ─── Lizard 导入（多语言复杂度分析库）────────────────────────────────────────
try:
    import lizard
    _LIZARD_AVAILABLE = True
except ImportError:
    _LIZARD_AVAILABLE = False

# ─── 解析器缓存（用于 AST 解析）───────────────────────────────────────────────

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

_PARSER_CACHE: dict[str, Any] = {}


def _load_parser(language: str) -> Any | None:
    """懒加载 tree-sitter 解析器。"""
    if language in _PARSER_CACHE:
        return _PARSER_CACHE[language]

    if language in _LANG_PKG:
        mod_name, attr_name = _LANG_PKG[language]
        try:
            mod = __import__(mod_name, fromlist=[attr_name])
            lang_fn = getattr(mod, attr_name)
            capsule = lang_fn() if callable(lang_fn) else lang_fn
            ts_lang = __import__("tree_sitter").Language(capsule)
            parser = __import__("tree_sitter").Parser(ts_lang)
            _PARSER_CACHE[language] = parser
            return parser
        except Exception:
            pass

    try:
        from tree_sitter_languages import get_parser
        parser = get_parser(language)
        _PARSER_CACHE[language] = parser
        return parser
    except Exception:
        return None


# ─── 语言扩展名映射 ──────────────────────────────────────────────────────────

_EXT_TO_LANGUAGE: dict[str, str] = {
    "py": "python", "js": "javascript", "ts": "typescript",
    "tsx": "tsx", "jsx": "javascript", "go": "go",
    "rs": "rust", "java": "java", "c": "c", "cpp": "cpp",
    "cc": "cpp", "cxx": "cpp", "rb": "ruby", "swift": "swift",
    "kt": "kotlin", "kts": "kotlin", "scala": "scala",
    "php": "php", "dart": "dart", "zig": "zig", "cs": "csharp",
}

# 函数/类定义的 AST 节点关键字（多语言）
_FUNC_KEYWORDS: dict[str, list[str]] = {
    "python": ["def ", "async def "],
    "javascript": ["function ", "const ", "let ", "async "],
    "typescript": ["function ", "const ", "let ", "async "],
    "go": ["func "],
    "rust": ["fn "],
    "java": ["public ", "private ", "protected ", "void ", "int ", "String ", "boolean ", "@"],
    "cpp": ["void ", "int ", "auto ", "std::", "class ", "struct "],
    "csharp": ["public ", "private ", "void ", "async ", "Task<", "string "],
    "ruby": ["def ", "class ", "module "],
    "swift": ["func ", "class ", "struct ", "var "],
    "kotlin": ["fun ", "class ", "val ", "var "],
    "scala": ["def ", "class ", "object ", "val ", "var "],
    "php": ["function ", "class ", "public ", "private "],
    "dart": ["void ", "Future<", "class ", "final ", "var "],
    "zig": ["fn ", "pub fn ", "const ", "struct "],
}

# 导入语句的关键字（多语言）
_IMPORT_KEYWORDS: dict[str, list[str]] = {
    "python": ["import ", "from "],
    "javascript": ["import ", "require("],
    "typescript": ["import ", "require("],
    "go": ["import ("],
    "rust": ["use "],
    "java": ["import "],
    "cpp": ["#include "],
    "csharp": ["using ", "import "],
    "ruby": ["require ", "require_relative "],
    "swift": ["import "],
    "kotlin": ["import "],
    "scala": ["import "],
    "php": ["use ", "require ", "include "],
    "dart": ["import ", "export ", "part "],
    "zig": ["const ", "usingnamespace "],
}

# 标准库定义（多语言）
_STDLIB: dict[str, set[str]] = {
    "python": {
        "os", "sys", "json", "re", "math", "time", "datetime", "collections",
        "itertools", "functools", "typing", "pathlib", "requests", "urllib",
        "http", "io", "argparse", "logging", "dataclasses", "enum", "abc",
        "copy", "pickle", "sqlite3", "csv", "gzip", "zipfile", "uuid",
        "hashlib", "base64", "threading", "multiprocessing", "asyncio",
        "random", "string", "struct", "array", "weakref", "gc", "warnings",
    },
    "javascript": {
        "fs", "path", "os", "http", "https", "url", "querystring", "crypto",
        "buffer", "stream", "events", "util", "assert", "constants", "events",
        "child_process", "cluster", "dgram", "dns", "domain", "net", "readline",
        "repl", "string_decoder", "tls", "tty", "vm", "zlib", "console", "process",
    },
    "typescript": {
        "fs", "path", "os", "http", "https", "url", "querystring", "crypto",
        "buffer", "stream", "events", "util", "assert", "constants", "child_process",
        "cluster", "dgram", "dns", "domain", "net", "readline", "console", "process",
    },
    "go": {
        "fmt", "os", "io", "bufio", "strings", "strconv", "bytes", "net/http",
        "encoding/json", "errors", "sync", "time", "log", "os/exec", "flag",
        "math", "sort", "container/list", "context", "database/sql", "crypto",
        "hash", "regexp", "unicode", "unicode/utf8", "path", "path/filepath",
    },
    "rust": {
        "std", "core", "alloc", "collections", "fmt", "io", "iter", "mem",
        "option", "result", "string", "vec", "boxed", "rc", "cell", "refcell",
        "sync", "thread", "time", "path", "fs", "net", "os", "env", "process",
        "num", "convert", "marker", "task", "future", "pin", "async_await",
    },
    "java": {
        "java.lang", "java.util", "java.io", "java.nio", "java.math",
        "java.text", "java.time", "java.net", "java.sql", "java.security",
        "java.util.concurrent", "java.util.stream", "java.util.function",
        "javax.servlet", "org.springframework", "org.apache",
    },
    "cpp": {
        "iostream", "vector", "string", "map", "set", "unordered_map", "unordered_set",
        "memory", "algorithm", "functional", "numeric", "cassert", "cctype",
        "cerrno", "cfloat", "cmath", "cstdlib", "cstring", "ctime", "deque",
        "list", "stack", "queue", "fstream", "sstream", "thread", "mutex",
        "atomic", "future", "regex", "random",
    },
    "typescript_tsx": {
        "fs", "path", "os", "http", "https", "url", "querystring", "crypto",
        "buffer", "stream", "events", "util", "assert", "constants", "child_process",
        "cluster", "dgram", "dns", "domain", "net", "readline", "console", "process",
        "react", "next", "@", "styled-components", "axios", "lodash",
    },
}


def _guess_language(path: str, content: str = "") -> str:
    """根据文件扩展名猜测语言。"""
    ext = path.rsplit(".", 1)[-1] if "." in path else ""
    return _EXT_TO_LANGUAGE.get(ext, "python")


def _get_language_for_lizard(language: str) -> str:
    """将我们的语言名转换为 Lizard 支持的名称。"""
    mapping = {
        "python": "python",
        "javascript": "javascript",
        "typescript": "typescript",
        "tsx": "tsx",
        "jsx": "javascript",
        "go": "go",
        "rust": "rust",
        "java": "java",
        "c": "cpp",
        "cpp": "cpp",
        "ruby": "ruby",
        "swift": "swift",
        "kotlin": "kotlin",
        "scala": "scala",
        "php": "php",
        "dart": "dart",
        "zig": "cpp",
        "csharp": "csharp",
    }
    return mapping.get(language, "python")


def _get_file_extension(language: str) -> str:
    """获取语言对应的文件扩展名。"""
    ext_mapping = {
        "python": ".py",
        "javascript": ".js",
        "typescript": ".ts",
        "tsx": ".tsx",
        "go": ".go",
        "rust": ".rs",
        "java": ".java",
        "cpp": ".cpp",
        "ruby": ".rb",
        "swift": ".swift",
        "kotlin": ".kt",
        "scala": ".scala",
        "php": ".php",
        "dart": ".dart",
        "csharp": ".cs",
    }
    return ext_mapping.get(language, ".txt")


# ─── 工具实现 ────────────────────────────────────────────────────────────────


@tool
def parse_file_ast(file_path: str, content: str, language: str) -> str:
    """解析文件 AST，提取函数、类、导入、注释等信息。

    用途：Agent 深度分析特定文件时使用。
    可以了解文件的结构、函数签名、类定义等，用于判断文件的重要性。

    Args:
        file_path: 文件路径（用于推断语言和作为标识）
        content:   文件内容字符串
        language:  编程语言 (python/javascript/typescript/go/rust/java/c/cpp/ruby/swift/kotlin/php/dart/scala/zig/csharp)

    Returns:
        JSON 字符串，包含：
          - functions: [{name, start_line, end_line, parameters, decorators}]
          - classes:   [{name, start_line, end_line, methods}]
          - imports:   [import语句]
          - comments:  [重要注释]
          - lines:     总行数
    """
    result = _parse_ast_impl(file_path, content, language)
    return json.dumps(result, ensure_ascii=False)


@tool
def calculate_complexity(content: str, language: str) -> str:
    """计算代码片段的圈复杂度（多语言支持）。

    用途：Agent 评估代码质量时使用。
    返回平均/最大圈复杂度，以及超过阈值的函数列表。

    Args:
        content:  代码内容字符串
        language: 编程语言

    Returns:
        JSON 字符串：
          {
            "avg_complexity": float,
            "max_complexity": int,
            "over_threshold_count": int,
            "complex_functions": [{"name", "line", "complexity", "nloc"}]
          }
    """
    result = _calc_complexity_impl(content, language)
    return json.dumps(result, ensure_ascii=False)


@tool
def detect_code_smells(content: str, language: str, file_path: str = "") -> str:
    """检测代码异味（过长函数、深度嵌套、重复模式等，多语言支持）。

    用途：Agent 发现代码质量问题时使用。
    与 calculate_complexity 的区别：这里侧重于可维护性问题，不仅是圈复杂度。

    Args:
        content:   代码内容字符串
        language:  编程语言
        file_path: 文件路径（可选，用于更准确的检测）

    Returns:
        JSON 数组字符串，每项：
          {type, severity, location, description, suggestion}
        类型包括：long_function, deep_nesting, god_object,
                 magic_number, long_import, unused_code 等
    """
    result = _detect_smells_impl(content, language, file_path)
    return json.dumps(result, ensure_ascii=False)


@tool
def summarize_code_file(content: str, language: str = "", max_lines: int = 80) -> str:
    """生成代码文件的结构摘要（快速了解文件内容，多语言支持）。

    用途：Agent 需要快速了解文件但不需要完整内容时使用。
    与直接读取内容的区别：只返回关键结构，不是完整代码。

    Args:
        content:   文件完整内容
        language:  编程语言（可选，如果不提供会尝试自动检测）
        max_lines: 预览行数，默认 80

    Returns:
        文件结构摘要字符串，包含：
          - 文件大小
          - 函数/类定义列表（带行号）
          - 导入语句
          - 关键配置常量
    """
    if not language:
        language = "python"  # 默认值
    result = _summarize_impl(content, language)
    return result


@tool
def detect_imports(content: str, language: str) -> str:
    """从代码中提取所有 import/require 语句（多语言支持）。

    用途：Agent 分析依赖关系和代码结构时使用。
    可以了解文件依赖哪些外部模块。

    Args:
        content:  代码内容字符串
        language: 编程语言

    Returns:
        JSON 数组字符串，每项：
          {module, names, alias, line}
        例如 Python: {module: "os", names: ["path"], alias: None, line: 3}
    """
    result = _detect_imports_impl(content, language)
    return json.dumps(result, ensure_ascii=False)


@tool
def detect_dependencies(content: str, language: str) -> str:
    """识别代码中对外部依赖包的实际使用情况（多语言支持）。

    用途：与 dependency.py 互补——这里分析代码中实际 import/使用了的依赖，
    而非只分析配置文件。

    Args:
        content:  代码内容字符串
        language: 编程语言

    Returns:
        JSON 对象：
          {
            "used_packages": ["os", "requests", "pytest", ...],
            "suspicious_imports": [{"module", "reason"}],
            "builtin_usage": {"os.path": 3, "json": 2, ...}
          }
    """
    result = _detect_deps_impl(content, language)
    return json.dumps(result, ensure_ascii=False)


# ─── 内部实现 ────────────────────────────────────────────────────────────────


def _parse_ast_impl(file_path: str, content: str, language: str) -> dict[str, Any]:
    """解析 AST 的核心实现（多语言支持）。"""
    if not language or language == "auto":
        language = _guess_language(file_path, content)

    parser = _load_parser(language)
    if parser is None:
        return {
            "error": f"不支持的语言: {language}，或 tree-sitter 解析器未安装",
            "functions": [], "classes": [], "imports": [],
            "comments": [], "lines": len(content.splitlines()),
        }

    try:
        tree = parser.parse(bytes(content, "utf-8"))
    except Exception as e:
        return {"error": str(e), "functions": [], "classes": [], "imports": [], "comments": [], "lines": 0}

    functions: list[dict] = []
    classes: list[dict] = []
    imports: list[str] = []
    comments: list[dict] = []

    def walk(node, depth=0):
        node_type = node.type

        # 函数（多语言支持）
        if language == "python" and node_type == "function_definition":
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else ""
            decos = []
            for child in node.children:
                if child.type == "decorator":
                    decos.append(child.text.decode("utf-8", errors="replace").strip())
            params_node = node.child_by_field_name("parameters")
            params = params_node.text.decode("utf-8", errors="replace") if params_node else ""
            functions.append({
                "name": name,
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "parameters": params.strip(),
                "decorators": decos,
            })
        elif language in ("javascript", "typescript", "tsx") and node_type in ("function_declaration", "method_definition"):
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else "(anonymous)"
            functions.append({
                "name": name,
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "parameters": "",
                "decorators": [],
            })
        elif language == "go" and node_type == "function_declaration":
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else ""
            functions.append({
                "name": name,
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "parameters": "",
                "decorators": [],
            })
        elif language == "rust" and node_type == "function_item":
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else ""
            functions.append({
                "name": name,
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "parameters": "",
                "decorators": [],
            })
        elif language == "java" and node_type in ("method_declaration", "constructor_declaration"):
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else ""
            functions.append({
                "name": name,
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "parameters": "",
                "decorators": [],
            })

        # 类（多语言支持）
        if language == "python" and node_type == "class_definition":
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else ""
            bases = []
            for child in node.children:
                if child.type == "argument_list":
                    bases = [c.text.decode("utf-8", errors="replace") for c in child.children if c.type == "identifier"]
            classes.append({"name": name, "start_line": node.start_point[0] + 1, "end_line": node.end_point[0] + 1, "bases": bases})
        elif language in ("javascript", "typescript", "tsx") and node_type == "class_declaration":
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else ""
            classes.append({"name": name, "start_line": node.start_point[0] + 1, "end_line": node.end_point[0] + 1, "bases": []})
        elif language == "go" and node_type == "type_declaration":
            for child in node.children:
                if child.type == "type_spec":
                    name_node = child.child_by_field_name("name")
                    name = name_node.text.decode() if name_node else ""
                    classes.append({"name": name, "start_line": child.start_point[0] + 1, "end_line": child.end_point[0] + 1, "bases": []})
        elif language == "rust" and node_type == "impl_item":
            types = []
            for child in node.children:
                if child.type == "type_identifier":
                    types.append(child.text.decode("utf-8", errors="replace"))
            if types:
                classes.append({"name": f"impl {types[0]}", "start_line": node.start_point[0] + 1, "end_line": node.end_point[0] + 1, "bases": []})
        elif language == "java" and node_type == "class_declaration":
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else ""
            classes.append({"name": name, "start_line": node.start_point[0] + 1, "end_line": node.end_point[0] + 1, "bases": []})

        # 导入（多语言支持）
        if language == "python" and node_type in ("import_statement", "import_from_statement"):
            imports.append(node.text.decode("utf-8", errors="replace").strip())
        elif language in ("javascript", "typescript") and node_type in ("import_statement", "import_declaration"):
            imports.append(node.text.decode("utf-8", errors="replace").strip())
        elif language == "go" and node_type == "import_declaration":
            imports.append(node.text.decode("utf-8", errors="replace").strip())
        elif language == "java" and node_type == "import_declaration":
            imports.append(node.text.decode("utf-8", errors="replace").strip())
        elif language == "rust" and node_type == "use_declaration":
            imports.append(node.text.decode("utf-8", errors="replace").strip())

        # 注释
        if node_type in ("comment", "line_comment", "block_comment"):
            text = node.text.decode("utf-8", errors="replace").strip()
            if len(text) > 5 and not text.startswith("..."):
                comments.append({"line": node.start_point[0] + 1, "text": text[:100]})

        for child in node.children:
            walk(child, depth + 1)

    walk(tree.root_node)

    return {
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "comments": comments,
        "lines": len(content.splitlines()),
    }


def _calc_complexity_impl(content: str, language: str) -> dict[str, Any]:
    """计算圈复杂度的实现（使用 Lizard，支持多语言）。"""

    # 如果 Lizard 可用，使用 Lizard 进行多语言分析
    if _LIZARD_AVAILABLE:
        return _calc_complexity_with_lizard(content, language)

    # 否则使用回退实现（仅支持 Python）
    return _calc_complexity_fallback(content, language)


def _calc_complexity_with_lizard(content: str, language: str) -> dict[str, Any]:
    """使用 Lizard 计算圈复杂度（支持 15+ 种语言）。"""
    try:
        lizard_lang = _get_language_for_lizard(language)
        ext = _get_file_extension(language)
        fake_filename = f"temp{ext}"

        result = lizard.analyze_file(
            filename=fake_filename,
            code=content,
        )

        funcs: list[dict] = []
        for fn in result.function_list:
            funcs.append({
                "name": fn.name,
                "line": fn.start_line,
                "complexity": fn.cyclomatic_complexity,
                "nloc": fn.nloc,
                "parameters": fn.parameter_count,
            })

        if funcs:
            total = sum(f["complexity"] for f in funcs)
            max_comp = max(f["complexity"] for f in funcs)
            avg = total / len(funcs)
            over = sum(1 for f in funcs if f["complexity"] > 10)
            return {
                "avg_complexity": round(avg, 2),
                "max_complexity": max_comp,
                "over_threshold_count": over,
                "complex_functions": sorted(funcs, key=lambda x: x["complexity"], reverse=True)[:10],
                "language": language,
                "analyzer": "lizard",
            }

        return {
            "avg_complexity": 0.0,
            "max_complexity": 0,
            "over_threshold_count": 0,
            "complex_functions": [],
            "language": language,
            "analyzer": "lizard",
        }

    except Exception as e:
        # 如果 Lizard 失败，回退到简单实现
        return _calc_complexity_fallback(content, language)


def _calc_complexity_fallback(content: str, language: str) -> dict[str, Any]:
    """回退的复杂度计算（仅支持 Python）。"""
    COMPLEXITY_NODES: dict[str, set[str]] = {
        "python": {"if_statement", "elif_clause", "for_statement", "for_in_statement",
                    "while_statement", "with_statement", "except_clause", "try_statement",
                    "conditional_expression", "and_operator", "or_operator"},
        "javascript": {"if_statement", "else_clause", "for_statement", "for_in_statement",
                       "for_of_statement", "while_statement", "do_statement", "switch_statement",
                       "case_statement", "catch_clause", "try_statement", "conditional_expression",
                       "binary_expression"},
        "typescript": {"if_statement", "else_clause", "for_statement", "for_in_statement",
                       "for_of_statement", "while_statement", "do_statement", "switch_statement",
                       "case_statement", "catch_clause", "try_statement", "conditional_expression",
                       "binary_expression"},
        "go": {"if_statement", "for_statement", "range_statement", "switch_statement",
               "case_clause", "select_statement", "defer_statement"},
        "rust": {"if_expression", "match_expression", "for_expression", "while_expression",
                 "loop_expression"},
    }

    nodes = COMPLEXITY_NODES.get(language, COMPLEXITY_NODES.get("python", set()))

    parser = _load_parser(language)
    if parser is None:
        return {"avg_complexity": 0.0, "max_complexity": 0, "over_threshold_count": 0, "complex_functions": [], "language": language, "analyzer": "tree-sitter"}

    try:
        tree = parser.parse(bytes(content, "utf-8"))
    except Exception:
        return {"avg_complexity": 0.0, "max_complexity": 0, "over_threshold_count": 0, "complex_functions": [], "language": language, "analyzer": "tree-sitter"}

    funcs: list[dict] = []

    def walk(node, in_func=False, func_complexity=0, func_name="", func_start=0):
        if language == "python" and node.type == "function_definition":
            in_func = True
            name_node = node.child_by_field_name("name")
            func_name = name_node.text.decode() if name_node else ""
            func_start = node.start_point[0] + 1
            func_complexity = 1

        local_comp = 0
        if node.type in nodes:
            local_comp = 1

        for child in node.children:
            child_comp, child_name, child_start = walk(child, in_func, func_complexity, func_name, func_start)
            if in_func and not child_name:
                func_complexity += child_comp
            elif child_name:
                funcs.append({
                    "name": child_name,
                    "line": child_start,
                    "complexity": child_comp,
                    "nloc": 0,
                    "parameters": 0,
                })

        return local_comp, "", 0

    walk(tree.root_node)

    if funcs:
        total = sum(f["complexity"] for f in funcs)
        max_comp = max(f["complexity"] for f in funcs)
        avg = total / len(funcs)
        over = sum(1 for f in funcs if f["complexity"] > 10)
        return {
            "avg_complexity": round(avg, 2),
            "max_complexity": max_comp,
            "over_threshold_count": over,
            "complex_functions": sorted(funcs, key=lambda x: x["complexity"], reverse=True)[:10],
            "language": language,
            "analyzer": "tree-sitter",
        }
    return {"avg_complexity": 0.0, "max_complexity": 0, "over_threshold_count": 0, "complex_functions": [], "language": language, "analyzer": "tree-sitter"}


def _detect_smells_impl(content: str, language: str, file_path: str = "") -> list[dict]:
    """检测代码异味（多语言支持）。"""
    smells: list[dict] = []
    lines = content.split("\n")
    total_lines = len(lines)

    # 获取该语言的关键字
    func_keywords = _FUNC_KEYWORDS.get(language, ["def ", "function ", "func "])
    import_keywords = _IMPORT_KEYWORDS.get(language, ["import ", "require("])

    # 1. 过长的函数（多语言支持）
    in_func = False
    func_lines: list[tuple[int, str]] = []
    func_start_line = 0

    for i, line in enumerate(lines):
        stripped = line.strip()

        # 检测函数开始
        if not in_func:
            if any(stripped.startswith(kw) for kw in func_keywords if kw.strip()):
                in_func = True
                func_start_line = i + 1
                func_lines = [(i + 1, stripped)]
        else:
            # 检测函数结束（非缩进行）
            if stripped and not stripped.startswith(("#", "//", "/*", "*", "*/", "--")):
                # 缩进减少表示可能离开函数
                current_indent = len(line) - len(line.lstrip())
                if func_lines and current_indent <= 4:
                    # 检查是否是函数开始关键字
                    if any(stripped.startswith(kw) for kw in func_keywords if kw.strip()):
                        # 新函数开始，记录上一个函数
                        if len(func_lines) > 50:
                            smells.append({
                                "type": "long_function",
                                "severity": "medium",
                                "location": f"{func_lines[0][0]}-{func_lines[-1][0]}",
                                "description": f"函数 {func_lines[0][1][:40]} 长度 {len(func_lines)} 行",
                                "suggestion": "考虑拆分为更小的函数，每个函数控制在 30 行以内",
                            })
                        in_func = True
                        func_start_line = i + 1
                        func_lines = [(i + 1, stripped)]
                        continue

                    in_func = False
                    if len(func_lines) > 50:
                        smells.append({
                            "type": "long_function",
                            "severity": "medium",
                            "location": f"{func_lines[0][0]}-{func_lines[-1][0]}",
                            "description": f"函数 {func_lines[0][1][:40]} 长度 {len(func_lines)} 行",
                            "suggestion": "考虑拆分为更小的函数，每个函数控制在 30 行以内",
                        })
                else:
                    func_lines.append((i + 1, line))

    # 检查最后一个函数
    if in_func and len(func_lines) > 50:
        smells.append({
            "type": "long_function",
            "severity": "medium",
            "location": f"{func_lines[0][0]}-{func_lines[-1][0]}",
            "description": f"函数 {func_lines[0][1][:40]} 长度 {len(func_lines)} 行",
            "suggestion": "考虑拆分为更小的函数，每个函数控制在 30 行以内",
        })

    # 2. 深度嵌套（语言无关）
    max_depth = 0
    current_depth = 0
    depth_lines: dict[int, int] = {}
    nesting_keywords = ["if ", "for ", "while ", "except"]

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if any(kw in line for kw in nesting_keywords):
            if stripped.startswith(("if ", "for ", "while ", "except")):
                current_depth = indent
                if max_depth == 0 or indent <= max_depth + 4:
                    max_depth = max(max_depth, current_depth // 4 + 1)
                    depth_lines[current_depth] = i + 1

    if max_depth > 4:
        smells.append({
            "type": "deep_nesting",
            "severity": "high",
            "location": f"第 {depth_lines.get(max_depth * 4, '?')} 行",
            "description": f"嵌套深度达到 {max_depth} 层",
            "suggestion": f"嵌套深度 {max_depth} 层，建议重构，使用提前返回或提取方法",
        })

    # 3. 魔数
    magic_pattern = re.compile(r"(?<![a-zA-Z_])([0-9]{3,})(?![a-zA-Z_])")
    for i, line in enumerate(lines):
        matches = magic_pattern.findall(line)
        for _ in matches[:2]:
            if not any(k in line for k in ["url", "http", "version", "port", "timeout", "202", "404", "500"]):
                smells.append({
                    "type": "magic_number",
                    "severity": "low",
                    "location": f"第 {i + 1} 行",
                    "description": f"发现硬编码数字: {matches[0]}",
                    "suggestion": "考虑定义常量命名，提高可读性",
                })
                break

    # 4. 过大的文件
    if total_lines > 800:
        smells.append({
            "type": "god_object",
            "severity": "high",
            "location": f"共 {total_lines} 行",
            "description": f"文件过大（{total_lines} 行），可能包含过多职责",
            "suggestion": "建议按职责拆分为多个文件",
        })
    elif total_lines > 500:
        smells.append({
            "type": "large_file",
            "severity": "medium",
            "location": f"共 {total_lines} 行",
            "description": f"文件较大（{total_lines} 行）",
            "suggestion": "考虑拆分以提高可维护性",
        })

    # 5. 缺少类型注解（Python/TypeScript）
    if language in ("python", "typescript", "tsx"):
        untyped_funcs = 0
        for line in lines:
            stripped = line.strip()
            if any(stripped.startswith(kw) for kw in func_keywords):
                if language == "python" and "->" not in stripped:
                    untyped_funcs += 1
                elif language in ("typescript", "tsx") and ":" not in stripped.split("(")[0] if "(" in stripped else ":" not in stripped:
                    # TypeScript 函数通常是 typed 的
                    pass

        if untyped_funcs > 3:
            smells.append({
                "type": "missing_type_hints",
                "severity": "low",
                "location": f"{untyped_funcs} 个函数",
                "description": f"发现 {untyped_funcs} 个函数缺少类型注解",
                "suggestion": "添加类型注解以提高代码可读性和安全性",
            })

    return smells[:10]


def _summarize_impl(content: str, language: str) -> str:
    """生成文件摘要（多语言支持）。"""
    lines = content.split("\n")
    total_lines = len(lines)

    parts = [f"[文件摘要 — 共 {total_lines} 行，语言: {language}]"]

    # 获取该语言的关键字
    func_keywords = _FUNC_KEYWORDS.get(language, ["def ", "function "])
    import_keywords = _IMPORT_KEYWORDS.get(language, ["import "])

    # 提取关键结构
    structure: list[str] = []
    for i, line in enumerate(lines[:150]):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "/*", "*", "*/", "--")):
            continue

        # 函数/类定义
        if any(stripped.startswith(kw) for kw in func_keywords):
            structure.append(f"{i+1:4d}| {stripped[:80]}")

        # 导入语句（仅显示前几条）
        elif any(stripped.startswith(kw) for kw in import_keywords) and len(structure) < 50:
            structure.append(f"{i+1:4d}| {stripped[:80]}")

        # 配置文件检测
        elif any(kw in stripped for kw in ["=", ": ", "{", "}"]) and len(structure) < 60:
            # 可能是配置文件
            if 2 < len(stripped) < 100:
                structure.append(f"{i+1:4d}| {stripped[:80]}")

    if structure:
        parts.append("\n[关键结构]")
        parts.extend(structure[:30])
    else:
        parts.append("\n[无明显结构特征]")

    return "\n".join(parts)


def _detect_imports_impl(content: str, language: str) -> list[dict]:
    """提取 import 语句（多语言支持）。"""
    imports: list[dict] = []
    lines = content.split("\n")

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        if language == "python":
            if stripped.startswith("import "):
                parts = stripped[7:].strip().split(" as ", 1)
                module = parts[0].split()[0]
                alias = parts[1].strip() if len(parts) > 1 else None
                imports.append({"module": module, "names": [], "alias": alias, "line": i + 1})
            elif stripped.startswith("from "):
                m = re.match(r"from\s+([\w.]+)\s+import\s+(.+)", stripped)
                if m:
                    module = m.group(1)
                    names_str = m.group(2)
                    names = [n.strip() for n in re.split(r",\s*|as\s+\w+\s*,", names_str) if n.strip()]
                    imports.append({"module": module, "names": names, "alias": None, "line": i + 1})

        elif language in ("javascript", "typescript", "tsx"):
            # ES6 import: import xxx from 'module'
            if stripped.startswith("import "):
                m = re.match(r"import\s+(?:(?:\{[^}]+\}|[\w*]+)\s+from\s+)?['\"]([^'\"]+)['\"]", stripped)
                if m:
                    imports.append({"module": m.group(1), "names": [], "alias": None, "line": i + 1})
            # CommonJS require: const xxx = require('module')
            elif "require(" in stripped:
                m = re.search(r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", stripped)
                if m:
                    imports.append({"module": m.group(1), "names": [], "alias": None, "line": i + 1})

        elif language == "go":
            # import ( ... ) 或 import "module"
            if stripped.startswith("import"):
                if '"' in stripped:
                    m = re.search(r'"([^"]+)"', stripped)
                    if m:
                        imports.append({"module": m.group(1), "names": [], "alias": None, "line": i + 1})

        elif language == "rust":
            # use xxx::yyy;
            if stripped.startswith("use "):
                module = stripped[4:].rstrip(";").strip()
                imports.append({"module": module, "names": [], "alias": None, "line": i + 1})

        elif language == "java":
            # import package.Class;
            if stripped.startswith("import "):
                module = stripped[7:].rstrip(";").strip()
                imports.append({"module": module, "names": [], "alias": None, "line": i + 1})

        elif language == "cpp":
            # #include <xxx> 或 #include "xxx"
            if stripped.startswith("#include "):
                module = stripped[9:].strip("<>\"")
                imports.append({"module": module, "names": [], "alias": None, "line": i + 1})

        elif language == "ruby":
            # require 'xxx' 或 require_relative 'xxx'
            if stripped.startswith("require ") or stripped.startswith("require_relative "):
                m = re.search(r"['\"]([^'\"]+)['\"]", stripped)
                if m:
                    imports.append({"module": m.group(1), "names": [], "alias": None, "line": i + 1})

        elif language == "swift" or language == "kotlin":
            # import xxx
            if stripped.startswith("import "):
                module = stripped[7:].strip()
                imports.append({"module": module, "names": [], "alias": None, "line": i + 1})

        elif language == "php":
            # use Namespace\Class; require 'file.php'; include 'file.php';
            if stripped.startswith("use "):
                module = stripped[4:].rstrip(";").strip()
                imports.append({"module": module, "names": [], "alias": None, "line": i + 1})
            elif stripped.startswith("require ") or stripped.startswith("include "):
                m = re.search(r"['\"]([^'\"]+)['\"]", stripped)
                if m:
                    imports.append({"module": m.group(1), "names": [], "alias": None, "line": i + 1})

        elif language == "dart":
            # import 'xxx'; export 'xxx'; part 'xxx';
            if any(stripped.startswith(kw) for kw in ["import ", "export ", "part "]):
                m = re.search(r"['\"]([^'\"]+)['\"]", stripped)
                if m:
                    imports.append({"module": m.group(1), "names": [], "alias": None, "line": i + 1})

    return imports


def _detect_deps_impl(content: str, language: str) -> dict[str, Any]:
    """识别外部依赖的实际使用（多语言支持）。"""
    imports = _detect_imports_impl(content, language)

    # 提取模块名
    modules = []
    for imp in imports:
        if imp["module"]:
            # 取第一个部分作为主模块
            main_mod = imp["module"].split(".")[0]
            # 移除常见的前缀
            if main_mod.startswith("@"):
                main_mod = imp["module"].split("/")[0] if "/" in imp["module"] else main_mod
            modules.append(main_mod)

    module_counts: dict[str, int] = {}
    for mod in modules:
        module_counts[mod] = module_counts.get(mod, 0) + 1

    # 危险操作检测（多语言）
    suspicious: list[dict] = []
    dangerous_patterns: dict[str, list[str]] = {
        "python": ["eval", "exec", "__import__", "subprocess.run", "os.system", "pickle.loads"],
        "javascript": ["eval(", "Function(", "new Function(", "innerHTML", "document.write"],
        "typescript": ["eval(", "Function(", "new Function(", "innerHTML", "document.write"],
        "go": ["os/exec", "syscall.Exec", "os.StartProcess"],
        "rust": ["unsafe", "std::process::Command", "eval"],
    }

    for imp in imports:
        mod = imp["module"]
        patterns = dangerous_patterns.get(language, dangerous_patterns.get("python", []))
        if any(s in mod.lower() for s in patterns):
            suspicious.append({"module": mod, "reason": "可能执行任意代码或存在安全风险"})

    # 获取该语言的标准库
    stdlib = _get_stdlib(language)
    builtin_usage = {k: v for k, v in module_counts.items() if k in stdlib}
    used_packages = sorted(set(modules) - stdlib)

    return {
        "used_packages": used_packages,
        "suspicious_imports": suspicious,
        "builtin_usage": builtin_usage,
        "language": language,
    }


def _get_stdlib(language: str) -> set[str]:
    """获取指定语言的标准库集合。"""
    return _STDLIB.get(language, _STDLIB.get("python", set()))
