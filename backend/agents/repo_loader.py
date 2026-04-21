"""
RepoLoaderAgent — 智能代码仓库加载 Agent，基于 LangChain + 多轮 LLM 决策。

设计原则（Agent 思维）:
阶段一: 获取 SHA + 文件树
        ↓
阶段二: LLM 初始分类（P0/P1/P2）
        ↓
阶段三: 加载 P0 核心文件
        ↓
阶段四: 加载 P1 重要文件
        ↓
阶段五: LLM 深度决策（第1轮）
        ↓
阶段六: 按需加载 P2 文件
        ↓ ←←←←←←←←←←←←←←←←←
        │     ↑                  │
        │   决策                  │
        │     ↓                  │
        └── 最多 3 轮迭代         │
        ↓                        │
阶段七: 语言检测                  │
        ↓                        │
阶段八: 返回结果 ────────────────┘

每个阶段都 yield AgentEvent，支持 SSE 实时推送。
支持从 SharedState 断点恢复（LangGraph checkpoint）。


LangGraph 工作流（analysis_graph.py）
        │
        ├── node_fetch_tree_classify
        │       ├── RepoLoaderAgent().phase_fetch_tree()
        │       └── RepoLoaderAgent().phase_llm_classify()
        │
        ├── node_load_p0
        │       └── RepoLoaderAgent().phase_load_priority()
        │
        ├── node_decide_p1
        │       └── RepoLoaderAgent().phase_ai_decide_p1()
        │
        └── node_load_p2_decide
                └── RepoLoaderAgent().phase_ai_decide_p2()
"""
import asyncio
import base64
import json as _json
import os
import re
from typing import AsyncGenerator

import httpx

from .base_agent import AgentEvent, BaseAgent, _make_event

logger = __import__("logging").getLogger("gitintel")


# ─── Custom Exceptions ─────────────────────────────────────────────

class GitHubPermissionError(Exception):
    """GitHub Token 缺少 public_repo 权限，无法访问他人仓库"""
    pass


# ─── GitHub API 请求头 ────────────────────────────────────────────────

GITHUB_API_BASE_URL = os.getenv("GITHUB_API_BASE_URL", "https://api.github.com")


def _build_headers() -> dict:
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "GitIntel/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ─── LangChain LLM ───────────────────────────────────────────────────

def _get_llm():
    """懒加载 LangChain LLM client（通过统一工厂，支持 LangSmith 追踪）。"""
    from utils.llm_factory import get_llm
    return get_llm(temperature=0.3)


# ─── URL 解析 ────────────────────────────────────────────────────────

def _parse_github_url(url: str) -> tuple[str, str] | None:
    """从 GitHub URL 中提取 (owner, repo)。

    支持格式:
      https://github.com/owner/repo
      https://github.com/owner/repo.git
      git@github.com:owner/repo.git
      owner/repo
    """
    m = re.match(r"https?://github\.com/([^/]+)/([^/.]+)", url)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"^([^/]+)/([^/]+)$", url.strip())
    if m:
        return m.group(1), m.group(2)
    return None


# ─── Agent ──────────────────────────────────────────────────────────

class RepoLoaderAgent(BaseAgent):
    """通过 GitHub REST API + 多轮 LLM 决策智能加载仓库文件。"""

    name = "repo_loader"

    # 最大 LLM 迭代轮次（防止无限循环）
    MAX_DECISION_ROUNDS = 3

    # 默认优先级分类（当 LLM 不可用时的降级策略）
    DEFAULT_P0_FILES = frozenset({
        "package.json", "requirements.txt", "go.mod",
        "Cargo.toml", "Gemfile", "composer.json",
        "pyproject.toml", "Pipfile", "Makefile",
        "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
        "poetry.lock", "bun.lockb",
        "README.md", "README.rst", "README.txt",
        "tsconfig.json", "jsconfig.json",
        ".env.example", ".env.template",
        "vite.config.ts", "vite.config.js",
        "webpack.config.js", "next.config.js", "next.config.ts",
        "tailwind.config.ts", "tailwind.config.js",
        "setup.py", "setup.cfg",
        "pytest.ini", "tox.ini",
    })

    # ── 规则引擎：多语言文件分类 ───────────────────────────────────

    # 源码扩展名 → 语言名称（按优先级排序）
    SOURCE_EXTENSIONS: dict[str, str] = {
        # 前端/Node.js
        ".js": "JavaScript", ".jsx": "JavaScript",
        ".ts": "TypeScript", ".tsx": "TypeScript",
        ".vue": "Vue", ".svelte": "Svelte",
        # 后端/服务
        ".py": "Python", ".go": "Go", ".rs": "Rust",
        ".rb": "Ruby", ".java": "Java", ".kt": "Kotlin",
        ".scala": "Scala", ".cs": "C#", ".php": "PHP",
        # 系统/嵌入式
        ".c": "C", ".cpp": "C++", ".cc": "C++", ".cxx": "C++",
        ".h": "C/C++", ".hpp": "C++",
        ".swift": "Swift", ".m": "Objective-C",
        # 脚本/其他
        ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
        ".lua": "Lua", ".r": "R", ".R": "R", ".dart": "Dart",
        # 配置/数据
        ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
        ".json": "JSON", ".xml": "XML", ".ini": "INI", ".cfg": "INI",
        # 模板/样式
        ".html": "HTML", ".css": "CSS",
        ".scss": "SCSS", ".sass": "Sass", ".less": "Less",
        ".md": "Markdown", ".rst": "reStructuredText",
    }

    # 入口文件模式（匹配文件名或路径）
    ENTRY_PATTERNS = (
        r"^app\.(ts|tsx|js|jsx|vue)$",
        r"^index\.(ts|tsx|js|jsx|vue)$",
        r"^main\.(ts|tsx|js|jsx|vue|py|go|rs|java)$",
        r"^src[/\\]app\.(ts|tsx|js|jsx)$",
        r"^src[/\\]index\.(ts|tsx|js|jsx)$",
        r"^src[/\\]main\.(ts|tsx|js|jsx|py|go|java)$",
        r"^components?[/\\]",
        r"^hooks?[/\\]",
        r"^pages?[/\\]",
        r"^src[/\\]",
        r"^lib[/\\]",
        r"^api[/\\]",
        r"^server[/\\]",
        r"^internal[/\\]",
        r"^cmd[/\\]",
        r"^pkg[/\\]",
    )

    # ── 公开 SSE 接口 ──────────────────────────────────────────────

    async def stream(
        self, repo_url: str, branch: str = "main"
    ) -> AsyncGenerator[AgentEvent, None]:
        """SSE 流式接口：执行完整的多轮 LLM 决策加载流程。"""
        owner, repo = _parse_github_url(repo_url)
        if not owner or not repo:
            yield _make_event(
                self.name, "error",
                f"无法解析 GitHub 仓库 URL: {repo_url}，请确认格式为 github.com/owner/repo",
                0, None
            )
            return

        try:
            # 阶段一：获取 SHA + 文件树
            async for event in self._phase_fetch_tree(owner, repo, branch):
                yield event
                if event["type"] == "error":
                    return

            tree_items, sha = self._last_tree_items, self._last_sha  # type: ignore[attr-defined]

            # 阶段二：LLM 初始分类
            classified, llm_round0 = await self._phase_llm_classify(
                owner, repo, tree_items
            )
            for event in llm_round0:
                yield event

            # 阶段三：加载 P0
            p0_files = [f for f in classified if f["priority"] == 0]
            p1_files = [f for f in classified if f["priority"] == 1]
            p2_files = [f for f in classified if f["priority"] == 2]

            p0_contents, _ = await self._load_files(owner, repo, sha, p0_files)
            loaded = dict(p0_contents)

            yield _make_event(
                self.name, "progress",
                f"P0 核心文件加载完成: {len(p0_contents)} 个，开始加载 P1…",
                45, {"loaded": list(p0_contents.keys())}
            )

            # 阶段四：加载 P1
            p1_contents, _ = await self._load_files(owner, repo, sha, p1_files)
            loaded.update(p1_contents)

            yield _make_event(
                self.name, "progress",
                f"P1 文件加载完成: {len(p1_contents)} 个，开始 LLM 深度决策…",
                65, {"loaded": list(p1_contents.keys())}
            )

            # 阶段五 & 六：LLM 迭代决策 + 按需加载（最多 3 轮）
            all_p2 = list(p2_files)
            decision_history: list[dict] = []
            decision_rounds = 0

            while all_p2 and decision_rounds < self.MAX_DECISION_ROUNDS:
                decision_rounds += 1

                async for event in self._phase_llm_decision(
                    owner, repo, loaded, all_p2, decision_rounds
                ):
                    yield event
                    if event["type"] == "error":
                        return

                # 获取决策结果
                need_more, extra_paths = self._last_decision  # type: ignore[attr-defined]

                if not need_more or not extra_paths:
                    yield _make_event(
                        self.name, "progress",
                        f"LLM 决策（轮次 {decision_rounds}）：信息已足够，停止加载",
                        80, None
                    )
                    break

                # 按路径找 P2 文件
                extra_items = [f for f in all_p2 if f["path"] in extra_paths]
                all_p2 = [f for f in all_p2 if f["path"] not in extra_paths]

                extra_contents, _ = await self._load_files(
                    owner, repo, sha, extra_items,
                    max_concurrent=10, max_total=30
                )
                loaded.update(extra_contents)

                decision_history.append({
                    "round": decision_rounds,
                    "need_more": need_more,
                    "paths_requested": extra_paths[:30],
                    "paths_loaded": list(extra_contents.keys()),
                })

                yield _make_event(
                    self.name, "progress",
                    f"LLM 决策（轮次 {decision_rounds}）：额外加载 {len(extra_contents)} 个文件，"
                    f"剩余 {len(all_p2)} 个待选",
                    80, {"decision": decision_history[-1]}
                )

            # 阶段七：语言检测
            languages = self._infer_languages(tree_items)

            yield _make_event(
                self.name, "progress",
                f"加载完成: {len(loaded)} 个文件，"
                f"检测到语言: {', '.join(languages) if languages else '未知'}",
                95, None
            )

            # 阶段八：返回结果
            # 注意：代码语义分块已移至 CodeParserAgent，利用 tree-sitter AST
            # 在函数/类边界拆分，保持语义完整性
            yield _make_event(
                self.name, "result", "仓库加载完成",
                100,
                {
                    "owner": owner,
                    "repo": repo,
                    "branch": branch,
                    "sha": sha,
                    "total_tree_files": len(tree_items),
                    "total_loaded": len(loaded),
                    "languages": languages,
                    "file_contents": loaded,
                    "llm_decision_rounds": decision_rounds,
                    "llm_decision_history": decision_history,
                    "classified_files": classified,
                },
            )

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                yield _make_event(
                    self.name, "error",
                    "GitHub API 速率限制已达上限（403），建议设置 GITHUB_TOKEN 环境变量",
                    0, {"exception": "rate_limit_exceeded"}
                )
            elif exc.response.status_code == 404:
                yield _make_event(
                    self.name, "error",
                    f"仓库 {repo_url} 不存在或无权访问（404）",
                    0, {"exception": "not_found"}
                )
            else:
                yield _make_event(
                    self.name, "error",
                    f"GitHub API 请求失败 ({exc.response.status_code}): {exc}",
                    0, {"exception": str(exc)}
                )
        except Exception as exc:
            yield _make_event(
                self.name, "error",
                f"仓库加载失败: {exc}",
                0, {"exception": str(exc)}
            )

    # ── 断点续传专用阶段方法（供 LangGraph 节点调用）────────────

    async def phase_fetch_tree(
        self, owner: str, repo: str, branch: str = "main"
    ) -> tuple[list[dict], str | None]:
        """获取 SHA 和文件树。供 LangGraph node 调用。"""
        sha = await self._get_default_branch(owner, repo, branch)
        if not sha:
            return [], None
        tree_items = await self._fetch_tree(owner, repo, sha)
        return tree_items, sha

    async def phase_llm_classify(
        self,
        owner: str,
        repo: str,
        tree_items: list[dict],
    ) -> tuple[list[dict], dict | None]:
        """LLM 初始分类：基于文件树决定 P0/P1/P2。返回分类结果和 LLM 原始响应。"""
        return await self._llm_initial_classify(owner, repo, tree_items)

    async def phase_load_priority(
        self,
        owner: str,
        repo: str,
        sha: str,
        files: list[dict],
        max_concurrent: int = 10,
        max_total: int = 200,
    ) -> dict[str, str]:
        """加载指定优先级的文件，返回 path→content 字典。"""
        contents, _ = await self._load_files(
            owner, repo, sha, files,
            max_concurrent=max_concurrent, max_total=max_total
        )
        return contents

    async def phase_llm_decision(
        self,
        owner: str,
        repo: str,
        loaded: dict[str, str],
        pending: list[dict],
        round_num: int,
    ) -> tuple[bool, list[str]]:
        """LLM 决策一轮：判断是否需要加载更多，返回 (need_more, paths)。"""
        return await self._llm_decide(owner, repo, loaded, pending, round_num)

    async def phase_ai_decide_p1(
        self,
        owner: str,
        repo: str,
        loaded: dict[str, str],
        code_parser_result: dict | None,
        p1_files: list[dict],
        p2_files: list[dict],
    ) -> tuple[bool, list[str], str]:
        """AI 决策是否需要加载 P1。

        基于 P0 代码的解析结果，决定是否需要继续加载 P1 文件。

        注意：必须使用 LLM，不支持降级。

        Args:
            owner: 仓库所有者
            repo: 仓库名
            loaded: 已加载的 P0 文件内容
            code_parser_result: P0 文件的 AST 解析结果
            p1_files: 待加载的 P1 文件列表
            p2_files: 待加载的 P2 文件列表

        Returns:
            tuple[need_more, extra_paths, reason]
            - need_more: 是否需要加载更多文件
            - extra_paths: 需要加载的文件路径列表（此方法中为空）
            - reason: AI 决策的原因说明
        """
        llm = _get_llm()
        if llm is None:
            raise RuntimeError(
                "LLM 不可用，无法进行 P1 加载决策。请确保 OPENAI_API_KEY 或其他 LLM API Key 已配置。"
            )

        code_summary = ""
        if code_parser_result:
            func_count = code_parser_result.get("total_functions", 0)
            class_count = code_parser_result.get("total_classes", 0)
            lang_stats = code_parser_result.get("language_stats", {})
            langs = list(lang_stats.keys())[:5]
            code_summary = f"已分析 {func_count} 个函数, {class_count} 个类, 主要语言: {', '.join(langs)}"

        p1_count = len(p1_files)
        p2_count = len(p2_files)

        from .prompts import build_p1_decision_prompt

        prompt_template = build_p1_decision_prompt(
            repo_path=f"{owner}/{repo}",
            p0_summary=code_summary,
            p0_loaded_count=len(loaded),
            p1_files=[f["path"] for f in p1_files[:30]],
            p1_count=p1_count,
            p2_count=p2_count,
        )

        response = await llm.ainvoke(prompt_template.invoke({}))
        raw = response.content.strip()

        try:
            result = _json.loads(raw)
        except (_json.JSONDecodeError, Exception):
            logger.warning(f"[phase_ai_decide_p1] LLM 返回格式异常，使用默认值")
            return False, [], "LLM 不可用，默认不加载更多文件"
        need_more = bool(result.get("need_more", False))
        reason = result.get("reason", "基于代码分析的决定")

        return need_more, [], reason

    async def phase_ai_decide_p2(
        self,
        owner: str,
        repo: str,
        loaded: dict[str, str],
        code_parser_p0_result: dict | None,
        code_parser_p1_result: dict | None,
        p2_files: list[dict],
    ) -> tuple[bool, list[str], str]:
        """AI 决策 P2 文件：决定需要加载哪些 P2 文件。

        基于已加载的 P0/P1 代码分析结果，选择性地加载最有价值的 P2 文件。

        注意：必须使用 LLM，不支持降级。

        Args:
            owner: 仓库所有者
            repo: 仓库名
            loaded: 已加载的所有文件内容
            code_parser_p0_result: P0 文件的 AST 解析结果
            code_parser_p1_result: P1 文件的 AST 解析结果
            p2_files: 待加载的 P2 文件列表

        Returns:
            tuple[need_more, extra_paths, reason]
            - need_more: 是否需要加载更多文件
            - extra_paths: 需要加载的 P2 文件路径列表
            - reason: AI 决策的原因说明
        """
        llm = _get_llm()
        if llm is None:
            raise RuntimeError(
                "LLM 不可用，无法进行 P2 加载决策。请确保 OPENAI_API_KEY 或其他 LLM API Key 已配置。"
            )

        total_funcs = 0
        total_classes = 0
        all_langs = []
        for result in [code_parser_p0_result, code_parser_p1_result]:
            if result:
                total_funcs += result.get("total_functions", 0)
                total_classes += result.get("total_classes", 0)
                lang_stats = result.get("language_stats", {})
                all_langs.extend(list(lang_stats.keys())[:3])

        code_summary = f"已分析 {total_funcs} 个函数, {total_classes} 个类"

        p2_info = []
        for f in p2_files[:50]:
            p2_info.append({
                "path": f["path"],
                "size": f.get("size", 0),
            })

        from .prompts import build_p2_decision_prompt

        prompt_template = build_p2_decision_prompt(
            repo_path=f"{owner}/{repo}",
            code_summary=code_summary,
            loaded_count=len(loaded),
            p2_files=p2_info,
            max_extra=30,
        )

        response = await llm.ainvoke(prompt_template.invoke({}))
        raw = response.content.strip()

        try:
            result = _json.loads(raw)
        except (_json.JSONDecodeError, Exception):
            logger.warning(f"[phase_ai_decide_p2] LLM 返回格式异常，使用默认值")
            return False, [], "LLM 不可用，默认不加载更多文件"
        need_more = bool(result.get("need_more", False))
        extra_paths: list[str] = result.get("additional_paths", [])[:30]
        reason = result.get("reason", "基于代码分析的决定")

        return need_more, extra_paths, reason

    # ── 内部阶段实现 ────────────────────────────────────────────────

    async def _phase_fetch_tree(
        self, owner: str, repo: str, branch: str
    ) -> AsyncGenerator[AgentEvent, None]:
        """阶段一：获取 SHA + 文件树。"""
        yield _make_event(
            self.name, "status",
            f"正在获取 {owner}/{repo} 分支信息…", 5, None
        )
        sha = await self._get_default_branch(owner, repo, branch)
        if not sha:
            yield _make_event(
                self.name, "error",
                f"无法获取仓库 {owner}/{repo} 分支信息，可能仓库不存在或无权访问",
                0, None
            )
            return

        yield _make_event(
            self.name, "progress",
            f"已解析到 commit SHA: {sha[:7]}，正在获取文件树…", 10, None
        )

        tree_items = await self._fetch_tree(owner, repo, sha)
        if not tree_items:
            yield _make_event(
                self.name, "error",
                f"仓库 {owner}/{repo} 文件树为空",
                0, None
            )
            return

        self._last_tree_items = tree_items  # type: ignore[attr-defined]
        self._last_sha = sha  # type: ignore[attr-defined]

        yield _make_event(
            self.name, "progress",
            f"文件树获取完成，共 {len(tree_items)} 个文件/目录，"
            f"开始 LLM 初始分类…", 20, {"total_files": len(tree_items)}
        )

    async def _phase_llm_decision(
        self,
        owner: str,
        repo: str,
        loaded: dict[str, str],
        p2_files: list[dict],
        round_num: int,
    ) -> AsyncGenerator[AgentEvent, None]:
        """阶段六（迭代）：LLM 深度决策，判断是否需要加载更多。"""
        if not p2_files:
            return

        need_more, extra_paths = await self._llm_decide(
            owner, repo, loaded, p2_files, round_num
        )
        self._last_decision = (need_more, extra_paths)  # type: ignore[attr-defined]

        if need_more:
            yield _make_event(
                self.name, "progress",
                f"LLM（轮次 {round_num}）决定需要更多文件: {len(extra_paths)} 个",
                70 + round_num * 5, {"need_more": True, "paths": extra_paths[:10]}
            )
        else:
            yield _make_event(
                self.name, "progress",
                f"LLM（轮次 {round_num}）判断：当前信息已足够",
                70 + round_num * 5, {"need_more": False}
            )

    # ── LLM 决策 ──────────────────────────────────────────────────

    def _classify_by_rules(self, blobs: list[dict]) -> tuple[set[str], set[str]]:
        """基于规则的 P0/P1 分类，支持多语言。

        P0: 配置文件 + 入口文件 + 核心源码
        P1: 重要源码
        P2: 其他文件
        """
        p0_paths: set[str] = set()
        p1_paths: set[str] = set()

        for blob in blobs:
            path = blob["path"]
            ext = os.path.splitext(path)[1].lower()

            # 1. 配置文件 → P0
            basename = os.path.basename(path)
            if basename in self.DEFAULT_P0_FILES:
                p0_paths.add(path)
                continue

            # 2. 入口文件/核心目录 → P0
            matched = False
            for pattern in self.ENTRY_PATTERNS:
                if re.match(pattern, path):
                    p0_paths.add(path)
                    matched = True
                    break
            if matched:
                continue

            # 3. 源码文件 → P1
            if ext in self.SOURCE_EXTENSIONS:
                p1_paths.add(path)
            # 4. 配置/数据/样式文件 → P1
            elif ext in (".yaml", ".yml", ".json", ".toml", ".xml", ".ini", ".cfg",
                         ".html", ".css", ".scss", ".sass", ".less"):
                p1_paths.add(path)
            # 5. Markdown 文档 → P1（有价值，排除 node_modules）
            elif ext == ".md" and "node_modules" not in path:
                p1_paths.add(path)

        return p0_paths, p1_paths

    async def _llm_initial_classify(
        self, owner: str, repo: str, tree_items: list[dict]
    ) -> tuple[list[dict], dict]:
        """使用 LLM 对文件树做初始 P0/P1/P2 分类。

        LLM 不可用或返回格式异常时，使用规则引擎兜底（支持多语言）。
        """
        llm = _get_llm()

        blobs = [
            {"path": item["path"], "type": item["type"], "size": item.get("size", 0)}
            for item in tree_items
            if item["type"] == "blob"
        ]

        # 尝试使用 LLM
        if llm is None:
            logger.warning("[_llm_initial_classify] LLM 不可用，使用规则引擎")
            return self._classify_by_rules_fallback(tree_items)

        from .prompts import build_repo_loader_initial_prompt
        tree_list = "\n".join(
            f"- {b['path']} (~{b.get('size', 0)} bytes)"
            for b in blobs[:150]
        )
        prompt_template = build_repo_loader_initial_prompt(
            repo_path=f"{owner}/{repo}",
            tree_list=tree_list,
            total_files=len(blobs),
        )

        raw = ""
        try:
            response = await llm.ainvoke(prompt_template.invoke({}))
            raw = response.content.strip()

            # 尝试去除 markdown 代码块包裹
            cleaned = raw
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                # 跳过第一行的 ```json 或 ```
                if lines and re.match(r"^```[a-z]*$", lines[0].strip()):
                    lines = lines[1:]
                # 去掉最后一行的 ```
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                cleaned = "\n".join(lines).strip()

            # 解析 JSON（可能是数组或对象）
            parsed = _json.loads(cleaned)

            # 处理数组格式：取第一个元素
            if isinstance(parsed, list) and len(parsed) > 0:
                result = parsed[0]
            elif isinstance(parsed, dict):
                result = parsed
            else:
                raise ValueError(f"Unexpected JSON type: {type(parsed)}")
        except Exception as e:
            logger.warning(f"[_llm_initial_classify] LLM 调用或解析失败 ({e})，使用规则引擎")
            logger.debug(f"[_llm_initial_classify] LLM 原始返回: {raw[:500] if raw else '(empty)'}")
            return self._classify_by_rules_fallback(tree_items)

        p0_set = set(result.get("p0_paths", []))
        p1_set = set(result.get("p1_paths", []))

        classified: list[dict] = []
        for b in blobs:
            path = b["path"]
            if path in p0_set:
                priority = 0
            elif path in p1_set:
                priority = 1
            else:
                priority = 2
            classified.append({"path": path, "priority": priority, "size": b.get("size", 0)})

        llm_result = {
            "round": 0,
            "decision": "initial_classify",
            "p0_count": len(p0_set),
            "p1_count": len(p1_set),
            "p2_count": len(classified) - len(p0_set) - len(p1_set),
        }
        return classified, llm_result

    def _classify_by_rules_fallback(self, tree_items: list[dict]) -> tuple[list[dict], dict]:
        """规则引擎兜底：基于文件类型和路径的多语言分类。"""
        blobs = [
            {"path": item["path"], "type": item["type"], "size": item.get("size", 0)}
            for item in tree_items
            if item["type"] == "blob"
        ]
        p0_paths, p1_paths = self._classify_by_rules(blobs)

        classified: list[dict] = []
        for b in blobs:
            path = b["path"]
            if path in p0_paths:
                priority = 0
            elif path in p1_paths:
                priority = 1
            else:
                priority = 2
            classified.append({"path": path, "priority": priority, "size": b.get("size", 0)})

        llm_result = {
            "round": 0,
            "decision": "initial_classify_fallback",
            "p0_count": len(p0_paths),
            "p1_count": len(p1_paths),
            "p2_count": len(classified) - len(p0_paths) - len(p1_paths),
            "engine": "rules",
        }
        logger.info(
            f"[_classify_by_rules_fallback] 规则引擎: P0={len(p0_paths)}, "
            f"P1={len(p1_paths)}, P2={len(classified) - len(p0_paths) - len(p1_paths)}"
        )
        return classified, llm_result

    async def _llm_decide(
        self,
        owner: str,
        repo: str,
        loaded: dict[str, str],
        p2_files: list[dict],
        round_num: int,
    ) -> tuple[bool, list[str]]:
        """使用 LLM 判断是否需要加载更多 P2 文件。

        注意：必须使用 LLM，不支持降级。LLM 不可用或调用失败时抛出异常。
        """
        llm = _get_llm()
        if llm is None:
            raise RuntimeError(
                "LLM 不可用，无法进行加载决策。请确保 OPENAI_API_KEY 或其他 LLM API Key 已配置。"
            )

        from .prompts import build_repo_loader_decision_prompt

        summaries: dict[str, str] = {}
        for path, content in list(loaded.items())[:30]:
            summaries[path] = content[:300].replace("\n", " ")

        prompt_template = build_repo_loader_decision_prompt(
            repo_path=f"{owner}/{repo}",
            loaded_paths=list(loaded.keys())[:50],
            content_summaries=summaries,
            p2_files=p2_files[:50],
            max_extra=30,
        )

        response = await llm.ainvoke(prompt_template.invoke({}))
        raw = response.content.strip()

        try:
            result = _json.loads(raw)
        except (_json.JSONDecodeError, Exception):
            logger.warning(f"[_llm_decide] LLM 返回格式异常，使用默认值")
            return False, []
        need_more = bool(result.get("need_more", False))
        paths: list[str] = result.get("additional_paths", [])[:30]
        return need_more, paths

    # ── 文件加载 ────────────────────────────────────────────────────

    async def _load_files(
        self,
        owner: str,
        repo: str,
        sha: str,
        files: list[dict],
        max_concurrent: int = 10,
        max_total: int = 200,
    ) -> tuple[dict[str, str], int]:
        """并发加载文件内容，有限流控制。"""
        if not files:
            return {}, 0

        to_fetch = files[:max_total]
        skipped = max(0, len(files) - len(to_fetch))
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_one(item: dict) -> tuple[str, str]:
            async with semaphore:
                try:
                    content = await self._fetch_file_content(owner, repo, item["path"], sha)
                    return item["path"], content
                except Exception:
                    return item["path"], ""

        results = await asyncio.gather(
            *[fetch_one(item) for item in to_fetch],
            return_exceptions=True,
        )
        contents: dict[str, str] = {}
        for result in results:
            if isinstance(result, tuple):
                path, content = result
                contents[path] = content
        return contents, skipped

    # ── GitHub API ─────────────────────────────────────────────────

    async def _get_default_branch(self, owner: str, repo: str, branch: str) -> str | None:
        # 第一步：获取仓库默认分支（此 API 同时验证仓库可访问性）
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{GITHUB_API_BASE_URL}/repos/{owner}/{repo}",
                    headers=_build_headers(),
                )
                if resp.status_code == 200:
                    default_branch = resp.json().get("default_branch", "main")
                    # 用户指定了分支 → 优先使用用户指定的
                    # 用户没指定 → 使用仓库默认分支
                    target = branch if branch not in (None, "", "main") else default_branch
                    # 验证目标分支是否存在
                    branch_resp = await client.get(
                        f"{GITHUB_API_BASE_URL}/repos/{owner}/{repo}/branches/{target}",
                        headers=_build_headers(),
                    )
                    if branch_resp.status_code == 200:
                        return branch_resp.json().get("commit", {}).get("sha")
                    elif branch_resp.status_code in (401, 403):
                        raise GitHubPermissionError(
                            f"无法访问仓库 {owner}/{repo} 的分支 '{target}'（状态码 {branch_resp.status_code}），"
                            f"请检查 GITHUB_TOKEN 是否有效，以及是否具有 public_repo 权限。"
                        )
                    elif branch_resp.status_code == 404:
                        # 分支不存在，给出更清晰的提示
                        raise GitHubPermissionError(
                            f"仓库 {owner}/{repo} 中不存在分支 '{target}'。"
                            f"该仓库的默认分支为 '{default_branch}'，请确认分支名称是否正确。"
                        )
                elif resp.status_code in (401, 403):
                    raise GitHubPermissionError(
                        f"无法访问仓库 {owner}/{repo}（状态码 {resp.status_code}），"
                        f"请检查 GITHUB_TOKEN 是否有效，以及是否具有 public_repo 权限。"
                    )
                elif resp.status_code == 404:
                    raise GitHubPermissionError(
                        f"仓库 {owner}/{repo} 不存在或无权访问（状态码 404）"
                    )
        except GitHubPermissionError:
            raise
        except Exception:
            pass
        return None

    async def _fetch_tree(self, owner: str, repo: str, sha: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(
                f"{GITHUB_API_BASE_URL}/repos/{owner}/{repo}/git/trees/{sha}",
                params={"recursive": "1"},
                headers=_build_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("truncated", False):
                pass  # 超大仓库截断，尽力而为
            return data.get("tree", [])

    async def _fetch_file_content(
        self, owner: str, repo: str, path: str, ref: str
    ) -> str:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{GITHUB_API_BASE_URL}/repos/{owner}/{repo}/contents/{path}",
                params={"ref": ref},
                headers=_build_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            if "content" in data:
                encoding = data.get("encoding", "")
                if encoding == "base64":
                    content_b64 = data["content"].replace("\n", "")
                    try:
                        decoded = base64.b64decode(content_b64)
                        return decoded.decode("utf-8", errors="replace")
                    except Exception:
                        return ""
                elif not encoding:
                    return data.get("content", "")
            return ""

    @staticmethod
    def _infer_languages(tree_items: list[dict]) -> list[str]:
        LANG_EXT = {
            "Python": ".py",
            "TypeScript": (".ts", ".tsx"),
            "JavaScript": (".js", ".jsx"),
            "Go": ".go",
            "Rust": ".rs",
            "Ruby": ".rb",
            "Java": ".java",
            "C/C++": (".c", ".cpp", ".cc", ".h", ".hpp"),
            "C#": ".cs",
            "Swift": ".swift",
            "Kotlin": (".kt", ".kts"),
            "Scala": ".scala",
            "PHP": ".php",
            "Zig": ".zig",
            "Dart": ".dart",
        }
        counts: dict[str, int] = {}
        for item in tree_items:
            path = item["path"]
            for lang, exts in LANG_EXT.items():
                if isinstance(exts, tuple):
                    if any(path.endswith(e) for e in exts):
                        counts[lang] = counts.get(lang, 0) + 1
                elif path.endswith(exts):
                    counts[lang] = counts.get(lang, 0) + 1
        sorted_langs = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return [lang for lang, _ in sorted_langs[:5]]
