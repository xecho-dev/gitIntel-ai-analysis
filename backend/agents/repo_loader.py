"""
RepoLoaderAgent — 智能代码仓库加载 Agent，基于 LangChain + 多轮 LLM 决策。

设计原则（Agent 思维）:
  1. 阶段一：获取仓库结构（目录树）—— 一次 API，不下载内容
  2. 阶段二：LLM 决策初始分类 —— 让大模型决定 P0/P1/P2
  3. 阶段三：加载 P0 核心文件（高优先级）
  4. 阶段四：加载 P1 重要文件
  5. 阶段五：LLM 深度决策 —— 基于已加载内容，决定是否需要更多
  6. 阶段六：按需迭代加载（最多 3 轮，每轮都调用 LLM 决策）
  7. 阶段七：语言检测（识别仓库使用的编程语言）

注意：代码语义分块已移至 CodeParserAgent，利用 tree-sitter AST 在函数/类边界拆分，
保持语义完整性。详情见 _semantic_chunk_file() 方法。

每个阶段都 yield AgentEvent，支持 SSE 实时推送。
支持从 SharedState 断点恢复（LangGraph checkpoint）。
"""
import asyncio
import base64
import json as _json
import os
import re
from typing import AsyncGenerator

import httpx

from .base_agent import AgentEvent, BaseAgent, _make_event


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
    """懒加载 LangChain LLM client，优先 Anthropic，其次 OpenAI。"""
    try:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            temperature=0.3,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            max_tokens=1024,
            base_url=os.getenv("ANTHROPIC_BASE_URL", "").strip() or None,
        )
    except Exception:
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                temperature=0.3,
                openai_api_key=os.getenv("OPENAI_API_KEY"),
                base_url=os.getenv("OPENAI_BASE_URL"),
            )
        except Exception:
            return None


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

    ENTRY_PATTERNS = (
        r"^app\.(ts|tsx|js|jsx)$",
        r"^index\.(ts|tsx|js|jsx)$",
        r"^main\.(ts|tsx|js|jsx)$",
        r"^src[/\\]app\.(ts|tsx|js|jsx)$",
        r"^src[/\\]index\.(ts|tsx|js|jsx)$",
        r"^src[/\\]main\.(ts|tsx|js|jsx)$",
        r"^(app|src|lib|packages?)[/\\]",
        r"^pages?[/\\]",
        r"^components?[/\\]",
        r"^hooks?[/\\]",
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

    async def _llm_initial_classify(
        self, owner: str, repo: str, tree_items: list[dict]
    ) -> tuple[list[dict], dict | None]:
        """使用 LLM 对文件树做初始 P0/P1/P2 分类。

        降级策略：LLM 不可用时使用规则分类。
        """
        # 过滤出 blob
        blobs = [
            {"path": item["path"], "type": item["type"], "size": item.get("size", 0)}
            for item in tree_items
            if item["type"] == "blob"
        ]

        llm = _get_llm()
        if llm is None:
            # 降级：使用规则分类
            classified = self._rule_classify(blobs)
            return classified, None

        try:
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

            response = await llm.ainvoke(
                prompt_template.invoke({"system_context": "你是一个专业的代码分析助手。"})
            )
            raw = response.content.strip()

            result = _json.loads(raw)
            p0_set = set(result.get("p0_paths", []))
            p1_set = set(result.get("p1_paths", []))
            # 其余为 P2

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

        except Exception:
            # LLM 调用失败，降级到规则分类
            classified = self._rule_classify(blobs)
            return classified, None

    async def _llm_decide(
        self,
        owner: str,
        repo: str,
        loaded: dict[str, str],
        p2_files: list[dict],
        round_num: int,
    ) -> tuple[bool, list[str]]:
        """使用 LLM 判断是否需要加载更多 P2 文件。

        降级策略：LLM 不可用时按行数加载最大的 P2。
        """
        llm = _get_llm()
        if llm is None:
            # 降级：按大小排序，取前 20 个
            sorted_p2 = sorted(p2_files, key=lambda f: f.get("size", 0), reverse=True)
            paths = [f["path"] for f in sorted_p2[:20]]
            return True, paths

        try:
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

            response = await llm.ainvoke(
                prompt_template.invoke({"system_context": "你是一个专业的代码分析助手。"})
            )
            raw = response.content.strip()

            result = _json.loads(raw)
            need_more = bool(result.get("need_more", False))
            paths: list[str] = result.get("additional_paths", [])[:30]
            return need_more, paths

        except Exception:
            # LLM 失败，降级
            sorted_p2 = sorted(p2_files, key=lambda f: f.get("size", 0), reverse=True)
            return True, [f["path"] for f in sorted_p2[:20]]

    # ── 规则分类（降级策略）────────────────────────────────────────

    @staticmethod
    def _rule_classify(blobs: list[dict]) -> list[dict]:
        """当 LLM 不可用时，使用规则对文件做 P0/P1/P2 分类。"""

        IGNORE_DIRS = frozenset({
            "node_modules", ".git", "__pycache__", ".venv",
            "venv", "dist", "build", ".next", ".nuxt",
            "target", ".pytest_cache", ".mypy_cache",
            ".ruff_cache", "site-packages",
            ".github", ".vscode", ".idea",
            ".cache", ".turbo", ".sst",
        })
        SOURCE_EXTENSIONS = frozenset({
            ".py", ".ts", ".tsx", ".js", ".jsx",
            ".go", ".rs", ".rb", ".java", ".c", ".cpp",
            ".cc", ".h", ".hpp", ".cs", ".swift", ".kt",
            ".kts", ".scala", ".php", ".zig", ".dart",
            ".json", ".yaml", ".yml", ".toml",
            ".md", ".txt", ".sh", ".dockerfile",
            ".vue", ".svelte", ".css", ".scss", ".less",
            ".html", ".xml", ".sql",
        })
        IGNORE_EXTENSIONS = frozenset({
            ".lock", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico",
            ".webp", ".svg", ".tiff", ".tif",
            ".mp4", ".mp3", ".mov", ".avi", ".webm", ".flv",
            ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z",
            ".ttf", ".otf", ".woff", ".woff2", ".eot",
            ".exe", ".dll", ".so", ".dylib",
            ".DS_Store",
        })

        def should_ignore(path: str) -> bool:
            if any(d in path for d in IGNORE_DIRS):
                return True
            for i, ch in enumerate(path):
                if ch == ".":
                    ext = path[i:].lower()
                    if ext in IGNORE_EXTENSIONS:
                        return True
            return False

        def classify_one(b: dict) -> dict | None:
            path = b["path"]
            if should_ignore(path):
                return None

            is_source = any(path.endswith(ext) for ext in SOURCE_EXTENSIONS)
            is_p0_name = path in RepoLoaderAgent.DEFAULT_P0_FILES
            is_entry = any(re.match(p, path) for p in RepoLoaderAgent.ENTRY_PATTERNS)

            if is_p0_name or is_entry:
                priority = 0
            elif is_source:
                priority = 1
            else:
                priority = 1

            return {"path": path, "priority": priority, "size": b.get("size", 0)}

        results = [_ for _ in (classify_one(b) for b in blobs) if _ is not None]
        return results  # type: ignore[return-value]

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
        if branch:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(
                        f"{GITHUB_API_BASE_URL}/repos/{owner}/{repo}/branches/{branch}",
                        headers=_build_headers(),
                    )
                    if resp.status_code == 200:
                        return resp.json().get("commit", {}).get("sha")
            except Exception:
                pass

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{GITHUB_API_BASE_URL}/repos/{owner}/{repo}",
                    headers=_build_headers(),
                )
                if resp.status_code == 200:
                    default_branch = resp.json().get("default_branch", "main")
                    target = branch or default_branch
                    branch_resp = await client.get(
                        f"{GITHUB_API_BASE_URL}/repos/{owner}/{repo}/branches/{target}",
                        headers=_build_headers(),
                    )
                    if branch_resp.status_code == 200:
                        return branch_resp.json().get("commit", {}).get("sha")
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
