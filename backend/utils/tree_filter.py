"""
文件树过滤器 — 根据代码语言和目录黑白名单过滤文件树。

供以下模块使用：
  - ReActRepoLoaderAgent: 过滤初始文件树后喂给 LLM
  - Explorer 工具: 过滤 get_file_tree 返回的完整文件树

过滤逻辑（按顺序执行）：
  1. 过滤 dot-prefix 目录（如 .cursor, .github, .vscode）
  2. 过滤低价值目录（test, stories, mock, docs, node_modules 等）
  3. 保留关键配置文件（package.json, README.md, pyproject.toml 等）
  4. 按语言扩展名过滤（根据 GitHub API 返回的前 3 语言）
"""

from __future__ import annotations

import os

# ─── 语言 → 扩展名映射 ────────────────────────────────────────────────────────

LANGUAGE_EXTENSIONS: dict[str, list[str]] = {
    "TypeScript": [".ts", ".tsx", ".d.ts"],
    "JavaScript": [".js", ".jsx", ".mjs", ".cjs"],
    "Python": [".py"],
    "Go": [".go"],
    "Rust": [".rs"],
    "Java": [".java"],
    "Kotlin": [".kt", ".kts"],
    "Swift": [".swift"],
    "Objective-C": [".m", ".mm"],
    "C": [".c", ".h"],
    "C++": [".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"],
    "C#": [".cs"],
    "Ruby": [".rb"],
    "PHP": [".php"],
    "Scala": [".scala"],
    "Elixir": [".ex", ".exs"],
    "Erlang": [".erl"],
    "Clojure": [".clj"],
    "Haskell": [".hs"],
    "Lua": [".lua"],
    "R": [".r", ".R"],
    "Dart": [".dart"],
    "Vue": [".vue"],
    "Svelte": [".svelte"],
    "CSS": [".css", ".scss", ".sass", ".less", ".styl"],
    "HTML": [".html", ".htm"],
    "Shell": [".sh", ".bash", ".zsh"],
    "Dockerfile": ["Dockerfile", ".dockerignore"],
    "Terraform": [".tf"],
    "Nix": [".nix"],
    "Vim Script": [".vim"],
    "Makefile": ["Makefile", "Makefile.am", "GNUmakefile"],
    "CMake": ["CMakeLists.txt", "*.cmake"],
}

# ─── 关键配置文件白名单 ─────────────────────────────────────────────────────────

ALWAYS_KEEP_PATTERNS: set[str] = {
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "requirements.txt",
    "pyproject.toml",
    "poetry.lock",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Gemfile",
    "Gemfile.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "gradle.properties",
    ".env",
    ".env.example",
    ".env.local",
    ".env.development",
    "tsconfig.json",
    "jsconfig.json",
    "vite.config.ts",
    "vite.config.js",
    "next.config.js",
    "next.config.ts",
    "webpack.config.js",
    "jest.config.js",
    "jest.config.ts",
    "vitest.config.ts",
    "eslint.config.js",
    ".eslintrc.js",
    ".eslintrc.json",
    ".prettierrc",
    "README.md",
    "readme.md",
    "CHANGELOG.md",
    "LICENSE",
    "NOTICE",
    ".gitignore",
    ".gitattributes",
    "renovate.json",
    ".editorconfig",
    "turbo.json",
    "pnpm-workspace.yaml",
    "lerna.json",
    "Rakefile",
    "rakefile",
    "Procfile",
    ".ruby-version",
}

# ─── 低价值目录黑名单 ──────────────────────────────────────────────────────────

LOW_VALUE_DIRS: set[str] = {
    "test",
    "tests",
    "testing",
    "__tests__",
    "spec",
    "specs",
    "__specs__",
    "stories",
    "story",
    ".storybook",
    "mock",
    "mocks",
    "mocking",
    "__mocks__",
    "fixtures",
    "fixture",
    "examples",
    "example",
    "demo",
    "demos",
    "docs",
    "doc",
    "documentation",
    ".git",
    ".github",
    ".vscode",
    ".idea",
    ".cursor",
    ".vs",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".output",
    ".cache",
    ".turbo",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".svn",
    ".hg",
    "coverage",
    ".nyc_output",
    ".coverage",
    "assets",
    "static",
    "public",
    "media",
    "images",
    "img",
    "icons",
    "font",
    "fonts",
    "video",
    "audio",
    "third_party",
    "third-party",
    "vendor",
    "vendors",
    ".venv",
    "venv",
    ".env",
    "env",
    "site",
    "html",
    "webpack",
    "proto",
    "generated",
    "bin",
    "obj",
}


def build_kept_extensions(top_languages: list[str]) -> set[str]:
    """根据前 N 个语言构建应保留的扩展名集合（包含通配符）。"""
    kept: set[str] = set()
    for lang in top_languages:
        for ext in LANGUAGE_EXTENSIONS.get(lang, []):
            kept.add(ext.lower())
    return kept


def filter_file_tree(
    tree: list[dict],
    top_languages: list[str],
) -> list[dict]:
    """根据语言扩展名和目录黑白名单过滤文件树。

    Args:
        tree:          GitHub API 返回的完整文件树（每个元素包含 path, type 等字段）
        top_languages: GitHub API 返回的前 N 个语言（如 ["TypeScript", "CSS", "HTML"]）

    Returns:
        过滤后的文件树列表（仅含 blob 类型，且路径符合语言/目录规则）
    """
    kept_exts = build_kept_extensions(top_languages) if top_languages else set()
    always_keep_lower = {p.lower() for p in ALWAYS_KEEP_PATTERNS}
    low_value_lower = {d.lower() for d in LOW_VALUE_DIRS}

    # 如果没有语言信息，只保留关键配置文件（避免过滤掉所有文件）
    has_language_info = bool(top_languages) and bool(kept_exts)

    filtered = []
    for t in tree:
        if t.get("type") != "blob":
            continue
        path = t.get("path", "")
        basename = os.path.basename(path).lower()
        dir_parts = path.lower().split("/")

        # 1. 过滤 dot-prefix 目录（如 .cursor, .github 等）
        if any(p.startswith(".") for p in dir_parts[:-1]):
            continue

        # 2. 过滤低价值目录
        if any(d in low_value_lower for d in dir_parts):
            continue

        # 3. 保留 always-keep 清单中的文件（如 package.json, README.md）
        if basename in always_keep_lower:
            filtered.append(t)
            continue

        # 4. 如果没有语言信息，直接跳过（非配置文件）
        if not has_language_info:
            continue

        # 5. 按语言扩展名过滤
        matched = False
        for ext in kept_exts:
            if ext.startswith("*"):
                if basename.endswith(ext[1:]):
                    matched = True
                    break
            elif path.lower().endswith(ext):
                matched = True
                break
        if matched:
            filtered.append(t)

    return filtered
