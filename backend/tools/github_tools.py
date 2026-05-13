"""
GitHub 工具集 — 封装所有 GitHub API 操作，供 Agent 通过 Function Calling 调用。

工具列表：
  - get_repo_info:        获取仓库基本信息
  - get_file_tree:       获取完整文件树（递归）
  - read_file_content:    读取单个文件内容
  - get_file_blobs:       批量读取多个文件（并发，更高效）
  - search_code:          在仓库中搜索代码（GitHub Code Search）
  - batch_search_code:    批量搜索代码（并发执行多个搜索查询）
  - get_commit_history:   获取最近提交历史
  - get_pull_requests:    获取 PR 列表

所有工具都是 async 函数，通过 LangChain @tool 装饰器暴露给 Agent。

缓存策略：
  - get_repo_info / get_file_tree / read_file_content / get_default_branch
    使用函数级 in-memory 缓存，key = (func_name, owner, repo, ref, ...)。
    参数不变时直接返回缓存结果，避免同一分析流程中多个 Explorer 重复调用。
  - 缓存按 (owner, repo, ref) 隔离，不同仓库 / 分支互不影响。
  - 缓存在进程生命周期内有效，适合单次分析流程。
"""
import asyncio
import base64
import functools
import json
import logging
import os
import re
from typing import Any

from langchain_core.tools import tool

from utils.tool_result import ToolSuccess, ToolError, ToolWarn

logger = logging.getLogger("gitintel")

GITHUB_API_BASE = "https://api.github.com"


# ─── 工具级 In-Memory 缓存（带大小保护）───────────────────────────────────────

# 缓存容量限制，防止大仓库撑爆内存
_MAX_CACHE_ENTRIES_PER_TOOL = int(os.getenv("GITINTEL_MAX_CACHE_ENTRIES", "200"))
_MAX_CACHED_FILE_SIZE = int(os.getenv("GITINTEL_MAX_CACHED_FILE_KB", "512")) * 1024  # 超过此大小的文件内容不缓存


def _safe_async_run(coro_fn):
    """安全执行异步函数，自动适配是否有运行中的 event loop。

    在已有 loop 的环境（如 ReAct Agent 的 run_in_executor 调用栈）中，
    直接 await 协程而非启动新的 loop，避免 "asyncio.run() cannot be called
    from a running event loop" 错误。
    """
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_fn())

    # 已有 loop，在当前线程中创建 task
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        async def _wrapper():
            return await coro_fn()
        future = executor.submit(asyncio.run, _wrapper())
        return future.result()


class _ToolCache:
    """进程级工具结果缓存，按 (owner, repo, ref) 隔离，带容量保护。

    设计原则：
      - get_file_tree / get_repo_info / get_default_branch: 结果小，长期有效，多 Explorer 共享收益大
      - read_file_content: 结果可能很大，只缓存小文件（≤ _MAX_CACHED_FILE_SIZE）
      - search_code: 每次查询结果不同，语义化 key 难碰撞，不缓存
      - get_commit_history / get_pull_requests: 体积中等但 value 每次不同，不缓存

    容量保护：
      - 每种工具最多 _MAX_CACHE_ENTRIES_PER_TOOL 条记录，超出时淘汰最早的
      - 单个文件内容超过 _MAX_CACHED_FILE_SIZE 不缓存（直接放行，走原 API）
      - LRU 淘汰：每次 set 时检查，超量则移除最老的同类型记录
    """

    def __init__(self):
        self._data: dict[str, Any] = {}
        # 记录插入顺序，用于 LRU 淘汰
        self._insertion_order: list[str] = []

    def _make_key(self, tool_name: str, owner: str, repo: str, ref: str, **extra: Any) -> str:
        parts = [tool_name, owner, repo, ref]
        for k in sorted(extra.keys()):
            parts.append(f"{k}={extra[k]}")
        return "|".join(parts)

    def _evict_if_needed(self, key: str) -> None:
        """超过容量时淘汰最早的同工具记录。"""
        tool_name = key.split("|", 1)[0]
        same_tool_keys = [k for k in self._insertion_order if k.startswith(tool_name + "|")]
        if len(same_tool_keys) >= _MAX_CACHE_ENTRIES_PER_TOOL:
            oldest = same_tool_keys[0]
            self._data.pop(oldest, None)
            self._insertion_order.remove(oldest)

    def get(self, tool_name: str, owner: str, repo: str, ref: str, **extra: Any) -> Any:
        key = self._make_key(tool_name, owner, repo, ref, **extra)
        return self._data.get(key)

    def set(self, tool_name: str, owner: str, repo: str, ref: str, value: Any, **extra: Any) -> None:
        key = self._make_key(tool_name, owner, repo, ref, **extra)
        # 大文件内容不缓存（避免单个大文件撑爆内存）
        if isinstance(value, str) and len(value) > _MAX_CACHED_FILE_SIZE:
            return
        self._evict_if_needed(key)
        self._data[key] = value
        if key not in self._insertion_order:
            self._insertion_order.append(key)

    def clear(self) -> None:
        self._data.clear()
        self._insertion_order.clear()

    def stats(self) -> dict:
        """返回缓存统计信息，用于调试和监控。"""
        tool_counts: dict[str, int] = {}
        for k in self._insertion_order:
            tool = k.split("|", 1)[0]
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
        return {
            "total_entries": len(self._data),
            "by_tool": tool_counts,
        }


_tool_cache = _ToolCache()


def _cached_call(tool_name: str, owner: str, repo: str, ref: str,
                  uncached_fn: callable, **extra: Any) -> Any:
    """检查缓存，miss 时调用 uncached_fn 并存入缓存。"""
    hit = _tool_cache.get(tool_name, owner, repo, ref, **extra)
    if hit is not None:
        logger.info(f"[github_tools:cache] HIT {tool_name}({owner}/{repo}@{ref})")
        return hit
    result = uncached_fn()
    _tool_cache.set(tool_name, owner, repo, ref, result, **extra)
    logger.info(f"[github_tools:cache] MISS {tool_name}({owner}/{repo}@{ref}), stored")
    return result


# ─── 工具实现（内部 async 函数）───────────────────────────────────────────────


def _get_headers() -> dict:
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "GitIntel/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ─── 工具实现（内部 async 函数）───────────────────────────────────────────────


async def _get_branch_sha_impl(owner: str, repo: str, branch: str) -> str:
    """获取指定分支的当前 SHA。用于智能缓存比对。"""
    async with __import__("httpx").AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/branches/{branch}",
            headers=_get_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("commit", {}).get("sha", "")


def get_branch_sha(owner: str, repo: str, branch: str) -> str:
    """同步封装：获取指定分支的当前 SHA。"""
    return _safe_async_run(lambda: _get_branch_sha_impl(owner, repo, branch))


async def _get_repo_info_impl(owner: str, repo: str) -> dict[str, Any]:
    async with __import__("httpx").AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}",
            headers=_get_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

        # languages 需要单独调用 /repos/{owner}/{repo}/languages 端点获取
        languages: dict[str, int] = {}
        try:
            lang_resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/languages",
                headers=_get_headers(),
            )
            if lang_resp.status_code == 200:
                languages = lang_resp.json()
        except Exception:
            pass  # languages 获取失败不影响主流程

        return {
            "owner": owner,
            "repo": repo,
            "default_branch": data.get("default_branch", "main"),
            "description": data.get("description", ""),
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "watchers": data.get("watchers_count", 0),
            "language": data.get("language", ""),
            "languages": languages,  # dict: {"TypeScript": 12345, "Python": 6789}
            "topics": data.get("topics", []),
            "license": (data.get("license") or {}).get("name", ""),
            "created_at": data.get("created_at", ""),
            "pushed_at": data.get("pushed_at", ""),
            "open_issues_count": data.get("open_issues_count", 0),
        }


async def _get_file_tree_impl(owner: str, repo: str, ref: str) -> list[dict]:
    async with __import__("httpx").AsyncClient(timeout=60.0) as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/{ref}",
            params={"recursive": "1"},
            headers=_get_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("truncated", False):
            logger.warning(f"[github_tools] 文件树被截断，仓库可能过大: {owner}/{repo}")
        return data.get("tree", [])


async def _read_file_content_impl(
    owner: str, repo: str, path: str, ref: str
) -> str:
    async with __import__("httpx").AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref},
            headers=_get_headers(),
        )
        # 处理 404（文件不存在），返回空字符串而不是抛异常
        if resp.status_code == 404:
            logger.warning(f"[github_tools] 文件不存在: {owner}/{repo}/{path}@{ref}")
            return f"[文件不存在] {path}"
        resp.raise_for_status()
        data = resp.json()
        if "content" in data and data.get("encoding") == "base64":
            decoded = base64.b64decode(data["content"].replace("\n", ""))
            return decoded.decode("utf-8", errors="replace")
        return data.get("content", "")


async def _get_file_blobs_impl(
    owner: str, repo: str, paths: list[str], ref: str
) -> dict[str, str]:
    semaphore = asyncio.Semaphore(10)

    async def fetch_one(path: str) -> tuple[str, str]:
        async with semaphore:
            try:
                content = await _read_file_content_impl(owner, repo, path, ref)
                return path, content
            except Exception as e:
                logger.warning(f"[github_tools] 读取文件失败 {path}: {e}")
                return path, ""

    results = await asyncio.gather(
        *[fetch_one(p) for p in paths[:50]],
        return_exceptions=True,
    )
    return {
        path: content
        for path, content in results
        if not isinstance((path, content), BaseException)
    }


async def _search_code_impl(
    owner: str, repo: str, query: str, language: str = ""
) -> list[dict]:
    """在 GitHub 仓库中搜索代码。

    GitHub Code Search 有以下限制：
    - 需要仓库至少有代码索引（新建仓库可能没有）
    - 查询长度限制在 256 字符以内
    - 不支持通配符
    - 小仓库可能没有索引
    """
    import httpx

    # 清理查询，移除可能导致 422 的特殊字符
    clean_query = query.strip().replace("*", "").replace("?", "")[:200]
    if not clean_query:
        return []

    q = f"{clean_query} repo:{owner}/{repo}"
    if language:
        q += f" language:{language}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 重试逻辑：处理速率限制、临时错误和网络异常
        for attempt in range(3):
            try:
                resp = await client.get(
                    f"{GITHUB_API_BASE}/search/code",
                    params={"q": q, "per_page": "20"},
                    headers=_get_headers(),
                )
            except httpx.ConnectError as e:
                if attempt < 2:
                    import asyncio
                    logger.warning(
                        f"[github_tools] search_code ConnectError (attempt {attempt + 1}/3): {e}, 重试中..."
                    )
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise  # 第三次失败才上抛

            if resp.status_code == 200:
                items = resp.json().get("items", [])[:20]
                # 只保留分析所需的字段，去掉巨大的 repository 对象和 text_matches
                return [
                    {
                        "name": it.get("name", ""),
                        "path": it.get("path", ""),
                        "sha": (it.get("sha") or "")[:12],
                        "url": it.get("html_url", ""),
                    }
                    for it in items
                ]

            if resp.status_code == 404:
                # 仓库太小或没有索引，不可搜索
                if attempt == 0:
                    logger.warning(
                        f"[github_tools] search_code: q='{q}', 仓库可能太小或代码未被索引"
                    )
                return []

            if resp.status_code == 422:
                # 查询无效（可能是查询太复杂或仓库不支持）
                if attempt == 0:
                    logger.warning(
                        f"[github_tools] search_code 422: q='{q}', 查询可能无效或仓库不支持代码搜索"
                    )
                return []

            if resp.status_code == 403:
                # 可能是速率限制，稍后重试
                if attempt < 2:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)  # 指数退避
                    continue
                logger.warning(f"[github_tools] search_code 403: q='{q}', 速率限制")
                return []

            # 其他错误
            if attempt < 2:
                continue
            logger.warning(f"[github_tools] search_code {resp.status_code}: q='{q}'")
            return []

        return []


async def _batch_search_code_impl(
    owner: str, repo: str, queries: list[dict]
) -> list[dict]:
    """并发执行多个搜索查询。

    每个元素格式：{"query": str, "language": str, "index": int}
    返回：同顺序的结果列表，每个元素包含 index、results、query、language。
    """
    semaphore = asyncio.Semaphore(5)

    async def fetch_one(item: dict) -> dict:
        async with semaphore:
            query = item.get("query", "")
            language = item.get("language", "")
            index = item.get("index", 0)
            try:
                results = await _search_code_impl(owner, repo, query, language)
            except Exception as e:
                logger.warning(
                    f"[github_tools] batch_search_code query='{query}' failed: {e}"
                )
                results = []
            return {
                "index": index,
                "query": query,
                "language": language,
                "results": results,
            }

    tasks = [fetch_one(item) for item in queries[:20]]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    results: list[dict] = []
    for item in gathered:
        if isinstance(item, BaseException):
            logger.warning(f"[github_tools] batch_search_code task failed: {item}")
            results.append({"index": -1, "query": "", "language": "", "results": []})
        else:
            results.append(item)

    results.sort(key=lambda x: x.get("index", 0))
    return results


async def _get_commit_history_impl(
    owner: str, repo: str, ref: str = "main", limit: int = 30
) -> list[dict]:
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/commits",
            params={"sha": ref, "per_page": str(limit)},
            headers=_get_headers(),
        )
        resp.raise_for_status()
        commits = resp.json()
        return [
            {
                "sha": c.get("sha", "")[:7],
                "message": c.get("commit", {}).get("message", "").split("\n")[0],
                "author": c.get("commit", {}).get("author", {}).get("name", ""),
                "date": c.get("commit", {}).get("author", {}).get("date", ""),
            }
            for c in commits
        ]


async def _get_pull_requests_impl(
    owner: str, repo: str, state: str = "open", limit: int = 20
) -> list[dict]:
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls",
            params={"state": state, "per_page": str(limit)},
            headers=_get_headers(),
        )
        resp.raise_for_status()
        prs = resp.json()
        return [
            {
                "number": pr.get("number"),
                "title": pr.get("title", ""),
                "state": pr.get("state", ""),
                "user": pr.get("user", {}).get("login", ""),
                "created_at": pr.get("created_at", ""),
                "url": pr.get("html_url", ""),
                "draft": pr.get("draft", False),
                "labels": [l.get("name", "") for l in pr.get("labels", [])],
            }
            for pr in prs
        ]


async def _get_default_branch_impl(owner: str, repo: str) -> str:
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}",
            headers=_get_headers(),
        )
        resp.raise_for_status()
        return resp.json().get("default_branch", "main")


# ─── LangChain @tool 装饰器包装 ────────────────────────────────────────────────


@tool
def get_repo_info(owner: str, repo: str) -> str:
    """获取 GitHub 仓库的基本信息。

    用途：作为分析的第一步，快速了解仓库的基本情况。
    返回的信息包括：默认分支、描述、star 数、语言、topics 等。

    Args:
        owner: 仓库所有者的用户名
        repo:  仓库名称（不含 owner）

    Returns:
        JSON 格式的仓库基本信息字符串
    """

    def _uncached():
        return _safe_async_run(lambda: _get_repo_info_impl(owner, repo))

    try:
        data = _cached_call("get_repo_info", owner, repo, "", _uncached)
        result = ToolSuccess(data).to_str()
    except Exception as e:
        result = ToolError(f"获取仓库信息失败: {e}").to_str()

    logger.info(f"[github_tools] get_repo_info({owner}/{repo}) -> {len(result)} chars")
    return result


@tool
def get_file_tree(owner: str, repo: str, ref: str) -> str:
    """获取 GitHub 仓库的完整文件树（递归）。

    用途：Agent 需要了解仓库的整体文件结构时调用。
    返回所有文件和目录的列表，包含路径、类型、大小等信息。

    Args:
        owner: 仓库所有者
        repo:  仓库名
        ref:   分支名、SHA 或 tag（如 "main", "master", "abc123"）

    Returns:
        JSON 数组字符串，每个元素包含 path, type (blob/tree), size, sha
    """

    def _uncached():
        return _safe_async_run(lambda: _get_file_tree_impl(owner, repo, ref))

    try:
        data = _cached_call("get_file_tree", owner, repo, ref, _uncached)
        result = ToolSuccess(data).to_str()
    except Exception as e:
        result = ToolError(f"获取文件树失败: {e}").to_str()

    tree_len = len(data) if isinstance(data, list) else 0
    logger.info(f"[github_tools] get_file_tree({owner}/{repo}@{ref}) -> {tree_len} items")
    return result


@tool
def read_file_content(path: str, owner: str = "", repo: str = "", ref: str = "") -> str:
    """读取 GitHub 仓库中单个文件的完整内容。

    ⚠️ 【重要】owner/repo/ref 由系统自动注入，调用时【不要】传递这些参数！
    如果你传递了 owner/repo/ref，它们会被系统忽略，使用当前仓库的上下文。

    用途：Agent 需要查看某个文件的实际代码内容时调用。
    适用于读取配置文件、入口文件、核心业务逻辑文件等。

    Args:
        path:  文件在仓库中的路径（如 "src/app.py"、"package.json"）
        owner: 【系统自动注入，不要传递】仓库所有者
        repo:  【系统自动注入，不要传递】仓库名
        ref:   【系统自动注入，不要传递】分支名或 SHA

    Returns:
        文件内容字符串。如果文件过大（> 500KB），自动截断到前 500KB。

    正确调用示例：
        ✅ read_file_content(path="src/index.js")
        ✅ read_file_content(path="package.json")
        ❌ read_file_content(owner="facebook", repo="react", path="README.md")  ← 不要这样！
    """

    def _uncached():
        return _safe_async_run(lambda: _read_file_content_impl(owner, repo, path, ref))

    try:
        content = _cached_call("read_file_content", owner, repo, ref, _uncached, path=path)
        if len(content) > 512 * 1024:
            content = content[:512 * 1024] + f"\n... [文件过大，已截断到 512KB，原始大小 {len(content)} 字节]"
        result = ToolSuccess(content).to_str()
    except Exception as e:
        result = ToolError(f"读取文件失败: {e}").to_str()

    logger.debug(f"[github_tools] read_file_content({owner}/{repo}/{path}@{ref}) -> {len(result)} chars")
    return result


@tool
def get_file_blobs(owner: str, repo: str, paths: list[str], ref: str) -> str:
    """批量读取多个文件内容（并发，更高效）。

    用途：当 Agent 需要一次性读取多个文件时使用，比逐个调用 read_file_content
    效率更高（10 个并发）。

    Args:
        owner: 仓库所有者
        repo:  仓库名
        paths: 文件路径列表，最多 50 个
        ref:   分支名或 SHA

    Returns:
        JSON 对象字符串，key 为文件路径，value 为文件内容。
        单个文件内容超过 200KB 时截断。
    """
    import asyncio

    # 逐个文件检查缓存，未命中才请求
    paths_to_fetch = []
    result_map = {}
    for p in paths[:50]:
        hit = _tool_cache.get("read_file_content", owner, repo, ref, path=p)
        if hit is not None:
            result_map[p] = hit
        else:
            paths_to_fetch.append(p)

    if paths_to_fetch:
        async def _fetch_missing():
            return await _get_file_blobs_impl(owner, repo, paths_to_fetch, ref)

        blobs = _safe_async_run(_fetch_missing)
        for k, v in blobs.items():
            _tool_cache.set("read_file_content", owner, repo, ref, v, path=k)
            result_map[k] = v

    # 截断过大内容
    for k, v in list(result_map.items()):
        if len(v) > 200 * 1024:
            result_map[k] = v[:200 * 1024] + f"\n... [已截断到 200KB]"

    result = ToolSuccess(result_map).to_str()
    logger.info(f"[github_tools] get_file_blobs({owner}/{repo}) -> {len(result_map)} files ({len(paths_to_fetch)} fresh)")
    return result


@tool
def search_code(query: str, language: str = "", owner: str = "", repo: str = "") -> str:
    """在当前仓库中搜索代码（使用 GitHub Code Search API）。

    ⚠️ 【重要】owner 和 repo 由系统自动注入，调用时【不要】传递这两个参数！
    如果你传递了 owner/repo，它们会被系统忽略，使用当前仓库的上下文。

    用途：快速定位与特定概念相关的代码文件。
    例如：搜索 "useEffect" 找到 React Hook 使用位置。

    Args:
        query:    搜索关键词（支持简单正则，如 "class User"、"def auth"、"useState"）
        language: 可选，限定编程语言（如 "python", "typescript", "javascript"）
        owner:    【系统自动注入，不要传递】仓库所有者
        repo:     【系统自动注入，不要传递】仓库名

    Returns:
        JSON 数组字符串，每个元素包含 path, sha, url 等基本信息，最多 20 条。

    正确调用示例：
        ✅ search_code(query="useEffect", language="javascript")
        ✅ search_code(query="def authenticate", language="python")
        ❌ search_code(owner="facebook", repo="react", query="useEffect")  ← 不要这样！

    错误处理：
        - query 为空：返回错误提示，请提供有效的搜索关键词
        - 搜索结果为空：可能关键词不匹配，尝试更通用的词
    """
    import asyncio

    try:
        async def _run():
            return await _search_code_impl(owner, repo, query, language)

        items = _safe_async_run(_run)
        result = ToolSuccess(items).to_str()
    except Exception as e:
        result = ToolError(f"搜索代码失败: {e}").to_str()
        items = []

    logger.info(f"[github_tools] search_code({owner}/{repo}, '{query}') -> {len(items)} results")
    return result


@tool
def batch_search_code(queries: list[dict], owner: str = "", repo: str = "") -> str:
    """批量搜索代码（并发执行多个搜索查询，更高效）。

    ⚠️ 【重要】owner 和 repo 由系统自动注入，调用时【不要】传递这两个参数！

    用途：当需要同时搜索多个关键词时使用，比逐个调用 search_code 效率更高。
    例如：同时搜索多个技术栈关键词，快速定位相关代码文件。

    Args:
        queries:  查询列表，每个元素为 dict，包含：
            - query (str, 必填): 搜索关键词
            - language (str, 可选): 限定编程语言，如 "python", "typescript"
        owner:   【系统自动注入，不要传递】仓库所有者
        repo:    【系统自动注入，不要传递】仓库名

    Returns:
        JSON 数组字符串，每个元素对应一个查询，包含：
        - index: 查询在原列表中的顺序
        - query: 搜索关键词
        - language: 限定语言（无则为空字符串）
        - results: 该查询的结果列表（最多 20 条，每条含 path, sha, url）

    正确调用示例：
        ✅ batch_search_code(queries=[{"query": "useEffect", "language": "javascript"}, {"query": "useState", "language": "javascript"}])
        ✅ batch_search_code(queries=[{"query": "def auth"}, {"query": "class User"}, {"query": "async def"}])
        ❌ batch_search_code(queries=[...], owner="facebook", repo="react")  ← 不要这样！

    限制：
        - queries 最多 20 个查询
        - 每个查询内部逻辑与 search_code 一致（256 字符限制，无通配符等）
        - 并发上限为 5，超过 5 个的查询会排队
    """
    try:
        indexed = [
            {"query": q.get("query", ""), "language": q.get("language", ""), "index": i}
            for i, q in enumerate(queries[:20])
        ]

        async def _run():
            return await _batch_search_code_impl(owner, repo, indexed)

        data = _safe_async_run(_run)
        result = ToolSuccess(data).to_str()
    except Exception as e:
        result = ToolError(f"批量搜索失败: {e}").to_str()

    logger.info(f"[github_tools] batch_search_code({owner}/{repo}) -> {len(queries[:20])} queries")
    return result


@tool
def get_commit_history(owner: str, repo: str, ref: str = "main", limit: int = 30) -> str:
    """获取仓库的最近提交历史。

    用途：Agent 可以了解仓库的开发活跃度和最近的变更重点。
    特别适合分析：项目是否活跃、最近主要在改什么。

    Args:
        owner: 仓库所有者
        repo:  仓库名
        ref:   分支名或 SHA，默认 main
        limit: 返回的提交数量，默认 30，最多 100

    Returns:
        JSON 数组字符串，每条包含 sha, message, author, date
    """
    try:
        async def _run():
            return await _get_commit_history_impl(owner, repo, ref, min(limit, 100))

        data = _safe_async_run(_run)
        result = ToolSuccess(data).to_str()
    except Exception as e:
        result = ToolError(f"获取提交历史失败: {e}").to_str()

    return result


@tool
def get_pull_requests(owner: str, repo: str, state: str = "open", limit: int = 20) -> str:
    """获取仓库的 Pull Request 列表。

    用途：Agent 可以了解仓库的协作状态和开放的问题。
    state 可选：open / closed / all

    Args:
        owner: 仓库所有者
        repo:  仓库名
        state: PR 状态过滤，open | closed | all，默认 open
        limit: 返回的 PR 数量，默认 20

    Returns:
        JSON 数组字符串，每条包含 number, title, state, user, labels 等
    """
    try:
        async def _run():
            return await _get_pull_requests_impl(owner, repo, state, min(limit, 100))

        data = _safe_async_run(_run)
        result = ToolSuccess(data).to_str()
    except Exception as e:
        result = ToolError(f"获取 PR 列表失败: {e}").to_str()

    return result


@tool
def get_default_branch(owner: str, repo: str) -> str:
    """获取仓库的默认分支名称。

    用途：当只知道 owner/repo 但不知道默认分支时调用。
    通常是 "main" 或 "master"。

    Args:
        owner: 仓库所有者
        repo:  仓库名

    Returns:
        默认分支名称字符串（如 "main"）
    """
    def _uncached():
        return _safe_async_run(lambda: _get_default_branch_impl(owner, repo))

    try:
        result = _cached_call("get_default_branch", owner, repo, "", _uncached)
        result = ToolSuccess(result).to_str()
    except Exception as e:
        result = ToolError(f"获取默认分支失败: {e}").to_str()

    logger.debug(f"[github_tools] get_default_branch({owner}/{repo}) -> {result}")
    return result
