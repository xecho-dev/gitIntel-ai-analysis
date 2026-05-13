"""代码解析工具 — 提取文件结构信息（语言检测、类/函数/导入解析）。"""
import re
from dataclasses import dataclass, field


# ─── 扩展名到语言的映射 ────────────────────────────────────────────────────────

EXT_TO_LANGUAGE: dict[str, str] = {
    # JavaScript/TypeScript 生态
    "js": "javascript", "jsx": "javascript", "mjs": "javascript",
    "ts": "typescript", "tsx": "tsx", "mts": "typescript",
    "vue": "vue", "svelte": "svelte",
    # Python 生态
    "py": "python", "pyw": "python", "pyx": "python",
    # 后端语言
    "go": "go", "rs": "rust", "java": "java", "kt": "kotlin",
    "scala": "scala", "rb": "ruby", "php": "php",
    # 前端/样式
    "css": "css", "scss": "css", "sass": "css", "less": "css",
    "html": "html", "htm": "html",
    # 配置/数据
    "json": "json", "yaml": "yaml", "yml": "yaml", "toml": "toml",
    "xml": "xml", "md": "markdown", "mdx": "markdown",
    # 低级语言
    "c": "c", "cpp": "cpp", "cc": "cpp", "cxx": "cpp", "h": "c", "hpp": "cpp",
    "swift": "swift", "cs": "csharp", "dart": "dart",
    # Shell/脚本
    "sh": "shell", "bash": "shell", "zsh": "shell",
    "sql": "sql", "r": "r",
}

# 函数定义关键词
FUNC_KEYWORDS: dict[str, list[str]] = {
    "python": ["def ", "async def "],
    "javascript": ["function ", "async function ", "const ", "let ", "var "],
    "typescript": ["function ", "async function ", "const ", "let ", "var "],
    "tsx": ["function ", "async function ", "const ", "let ", "var "],
    "go": ["func "],
    "rust": ["fn ", "pub fn ", "async fn "],
    "java": ["public ", "private ", "protected "],
    "kotlin": ["fun ", "val ", "var "],
    "ruby": ["def ", "class ", "module "],
    "php": ["function ", "public ", "private ", "protected "],
    "c": ["void ", "int ", "char ", "static "],
    "cpp": ["void ", "int ", "class ", "template<"],
    "swift": ["func ", "var ", "let "],
    "csharp": ["void ", "public ", "private ", "protected ", "async "],
    "dart": ["void ", "Future ", "class ", "var ", "final "],
    "vue": ["function ", "const ", "export default"],
}

# 语言特征检测规则
LANGUAGE_CONTENT_SIGNATURES: list[tuple[str, list[str]]] = [
    ("vue", ["<template", "<script", "<style", "export default", "new Vue("]),
    ("javascript", ["const ", "let ", "var ", "function ", "=>", "require(", "module.exports", "import "]),
    ("typescript", [": string", ": number", ": boolean", "interface ", "type ", "<T>", "as const"]),
    ("python", ["def ", "import ", "from ", "class ", "if __name__", "print(", "self."]),
    ("go", ["func ", "package ", "import (", 'fmt.', " := ", "go func", "defer "]),
    ("rust", ["fn ", "let ", "mut ", "impl ", "pub ", "use ", "mod ", "-> ", "::"]),
    ("java", ["public class", "private ", "protected ", "System.out.", "void ", "import java."]),
    ("html", ["<!DOCTYPE", "<html", "<head", "<body", "<div", "<span", "<script", "<style"]),
    ("css", ["{", "}", "color:", "background:", "margin:", "padding:", "@media", ".class"]),
    ("json", ['{"', '"}', '": ', "[]"]),
    ("shell", ["#!/bin/", "echo ", "export ", "if [", "fi", "done", "source "]),
    ("sql", ["SELECT ", "FROM ", "WHERE ", "INSERT INTO", "UPDATE ", "DELETE FROM"]),
]


# ─── 文件摘要结构 ─────────────────────────────────────────────────────────────

@dataclass
class FileSummary:
    """文件提炼摘要 - 包含关键结构信息，不含完整代码"""
    path: str
    language: str
    purpose: str = "unknown"  # test/config/model/api/service/util/main/component/middleware
    lines: int = 0
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    complexity: str = "low"  # low/medium/high
    key_insight: str = ""


# ─── 工具函数 ────────────────────────────────────────────────────────────────

def get_extension_language(path: str) -> str:
    """根据文件扩展名返回语言名称。"""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return EXT_TO_LANGUAGE.get(ext, "")


def detect_language(path: str, content: str) -> tuple[str, bool]:
    """检测文件语言。

    Returns:
        (language, is_vue): 语言名称和是否是 Vue 文件
    """
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""

    # 1. 扩展名映射
    language = EXT_TO_LANGUAGE.get(ext, "")

    # 2. Vue 特殊处理
    is_vue = ext == "vue" or "<template" in content[:200]
    if is_vue:
        language = "vue"

    # 3. 内容特征检测（扩展名无法识别时）
    if not language or language == "unknown":
        language = _detect_by_content(content, ext)

    # 4. 兜底
    if not language:
        language = "unknown"

    return language, is_vue


def _detect_by_content(content: str, ext: str) -> str:
    """通过内容特征检测语言。"""
    if ext == "vue" or "<template" in content or "<script" in content:
        return "vue"

    if "<!DOCTYPE" in content or "<html" in content.lower():
        return "html"

    scores: dict[str, int] = {}
    for lang, sigs in LANGUAGE_CONTENT_SIGNATURES:
        if lang in ("vue", "html"):
            continue
        score = sum(1 for s in sigs if s in content)
        if score > 0:
            scores[lang] = score

    if scores:
        best = max(scores.items(), key=lambda x: x[1])
        if best[1] >= 2:
            return best[0]

    return "unknown"


def extract_from_vue(content: str) -> tuple[str, list[str], list[str]]:
    """从 Vue SFC 文件中提取 <script> 部分并解析导入和函数。

    Returns:
        (script_content, imports, functions)
    """
    vue_script_re = re.compile(r'<script[^>]*>(.*?)</script>', re.S)
    script_match = vue_script_re.search(content)
    script_content = script_match.group(1) if script_match else ""

    imports, functions = [], []

    for line in script_content.split('\n'):
        line = line.strip()

        # import 语句
        if line.startswith("import "):
            m = re.search(r"from\s+['\"]([^'\"]+)['\"]", line)
            if m:
                imports.append(m.group(1))
            m2 = re.search(r"import\s+\{([^}]+)\}", line)
            if m2:
                imports.append(f"{{{m2.group(1)}}}")

        # export default { ... } 形式
        if line.startswith("export default {"):
            for sub in script_content.split('\n'):
                sub = sub.strip()
                if "methods:" in sub or "data()" in sub:
                    break
                m = re.match(r"(\w+)\s*\(", sub)
                if m and len(functions) < 10:
                    functions.append(m.group(1))

        # methods: { ... } 形式
        elif "methods:" in line or line.startswith("methods = {"):
            brace_count = 0
            for sub in script_content.split('\n'):
                sub = sub.strip()
                if "}" in sub:
                    brace_count -= 1
                    if brace_count == 0:
                        break
                if "{" in sub:
                    brace_count += 1
                m = re.match(r"(\w+)\s*\(", sub)
                if m and brace_count > 0 and len(functions) < 10:
                    functions.append(m.group(1))

    return script_content, imports, functions


def infer_file_purpose(content: str, is_vue: bool, language: str) -> str:
    """推断文件用途。"""
    purpose_indicators = {
        "test": ["test_", "_test.py", "test(", ".test.", "describe(", "it(", "@test", ".spec."],
        "config": ["config", "settings", ".env", "settings.py", "config.py", "application.yml", "vue.config"],
        "model": ["model", "schema", "entity", "class Model", "class Entity", "interface State"],
        "api": ["route", "/api", "endpoint", "router", "@app.", "app.get", "app.post", "routes"],
        "service": ["service", "Service", "business", "usecase"],
        "util": ["util", "helper", "tool", "common", "utils", "compose"],
        "main": ["def main(", "if __name__", "app =", "create_app", "new Vue("],
        "component": ["<template>", "<script", "export default", "components"],
        "middleware": ["middleware", "Middleware", "@decorator", "before_request"],
    }

    purpose = "unknown"

    # Vue 默认是 component
    if is_vue and purpose == "unknown":
        purpose = "component"

    for name, indicators in purpose_indicators.items():
        if any(ind in content[:2000] for ind in indicators):
            purpose = name
            break

    return purpose


def extract_code_entities(
    content: str,
    language: str,
    is_vue: bool,
) -> tuple[list[str], list[str], list[str]]:
    """提取类、函数和导入。

    Returns:
        (classes, functions, imports)
    """
    lines = content.split("\n")
    classes, functions, imports = [], [], []

    # ── 类定义 ──
    class_patterns = [
        r"class\s+(\w+)",
        r"struct\s+(\w+)",
        r"interface\s+(\w+)",
        r"enum\s+(\w+)",
    ]
    for scan_lines in (lines[:100], lines[100:200] if len(lines) > 100 else []):
        for line in scan_lines:
            for pat in class_patterns:
                m = re.search(pat, line)
                if m and len(classes) < 10:
                    classes.append(m.group(1))

    # ── 函数定义 ──
    func_kws = FUNC_KEYWORDS.get(language, ["def ", "function "])
    scan_start = 0
    if is_vue and "<script" in content:
        script_start = content.find("<script")
        scan_start = len(content[:script_start].split("\n"))

    for line in lines[scan_start:scan_start + 150] if scan_start < len(lines) else lines[:150]:
        for kw in func_kws:
            if line.strip().startswith(kw):
                m = re.search(r"(?:async\s+)?(?:def|function|fn|func)\s+(\w+)", line)
                if m and len(functions) < 15:
                    fn_name = m.group(1)
                    if not fn_name.startswith("_") and "test" not in fn_name.lower():
                        functions.append(fn_name)
                break

    # ── 导入 ──
    import_kws = {
        "python": ["import ", "from "],
        "javascript": ["import ", "require("],
        "typescript": ["import ", "require("],
        "vue": ["import ", "require("],
    }
    kw_list = import_kws.get(language, ["import "])

    for line in lines[scan_start:scan_start + 80] if scan_start < len(lines) else lines[:80]:
        for kw in kw_list:
            if line.strip().startswith(kw) and len(imports) < 20:
                if language == "python":
                    s = line.strip()
                    if s.startswith("from "):
                        m = re.match(r"from\s+([\w.]+)\s+import", s)
                        if m:
                            imports.append(m.group(1))
                    elif s.startswith("import "):
                        m = re.match(r"import\s+([\w.]+)", s)
                        if m:
                            imports.append(m.group(1).split(" as ")[0])
                elif language in ("javascript", "typescript", "vue"):
                    if "import " in line:
                        m = re.search(r"from\s+['\"]([^'\"]+)['\"]", line)
                        if m:
                            imports.append(m.group(1))
                break

    return classes, functions, imports


def build_key_insight(classes: list, functions: list, imports: list) -> str:
    """生成一句话文件洞察。"""
    insight = ""
    if classes:
        insight = f"定义 {len(classes)} 个类: {', '.join(classes[:3])}"
    elif functions:
        insight = f"包含 {len(functions)} 个方法: {', '.join(functions[:5])}"

    if imports:
        external = [i for i in imports if not i.startswith('.') and not i.startswith('@/')]
        if external:
            suffix = f"，依赖: {', '.join(external[:5])}"
            insight = (insight + suffix) if insight else f"依赖: {', '.join(external[:5])}"
        elif imports:
            suffix = f"，引入: {', '.join(imports[:3])}"
            insight = (insight + suffix) if insight else f"引入: {', '.join(imports[:3])}"

    return insight


def summarize_file(path: str, content: str) -> FileSummary:
    """提炼单个文件为结构化摘要。"""
    language, is_vue = detect_language(path, content)
    lines = content.split("\n")
    line_count = len(lines)

    classes, functions, imports = extract_code_entities(content, language, is_vue)

    # Vue 文件：从 <script> 部分提取
    if is_vue:
        _, vue_imports, vue_funcs = extract_from_vue(content)
        if vue_imports:
            imports = vue_imports
        if vue_funcs:
            functions = vue_funcs

    purpose = infer_file_purpose(content, is_vue, language)

    # 复杂度评估
    complexity = "low"
    if line_count > 500 or len(functions) > 20:
        complexity = "high"
    elif line_count > 200 or len(functions) > 10:
        complexity = "medium"

    key_insight = build_key_insight(classes, functions, imports)

    return FileSummary(
        path=path,
        language=language,
        purpose=purpose,
        lines=line_count,
        classes=classes,
        functions=functions,
        imports=imports,
        complexity=complexity,
        key_insight=key_insight,
    )


def summarize_files(loaded_files: dict[str, str]) -> dict[str, FileSummary]:
    """批量提炼多个文件的结构化摘要。"""
    return {path: summarize_file(path, content) for path, content in loaded_files.items()}
