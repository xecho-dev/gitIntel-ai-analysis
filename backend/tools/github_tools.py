"""
GitHub 工具集 — 封装所有 GitHub API 操作，供 Agent 通过 Function Calling 调用。

工具列表：
  - get_repo_info:        获取仓库基本信息
  - get_file_tree:       获取完整文件树（递归）
  - read_file_content:    读取单个文件内容
  - get_file_blobs:       批量读取多个文件（并发，更高效）
  - search_code:          在仓库中搜索代码（GitHub Code Search）
  - get_commit_history:   获取最近提交历史
  - get_pull_requests:    获取 PR 列表

所有工具都是 async 函数，通过 LangChain @tool 装饰器暴露给 Agent。
"""
import asyncio
import base64
import json
import logging
import os
import re
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger("gitintel")

GITHUB_API_BASE = "https://api.github.com"


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


async def _get_repo_info_impl(owner: str, repo: str) -> dict[str, Any]:
    async with __import__("httpx").AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}",
            headers=_get_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "owner": owner,
            "repo": repo,
            "default_branch": data.get("default_branch", "main"),
            "description": data.get("description", ""),
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "watchers": data.get("watchers_count", 0),
            "language": data.get("language", ""),
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
        # 重试逻辑：处理速率限制和临时错误
        for attempt in range(3):
            resp = await client.get(
                f"{GITHUB_API_BASE}/search/code",
                params={"q": q, "per_page": "20"},
                headers=_get_headers(),
            )

            if resp.status_code == 200:
                return resp.json().get("items", [])[:20]

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
    import asyncio

    async def _run():
        return json.dumps(await _get_repo_info_impl(owner, repo), ensure_ascii=False)

    result = asyncio.run(_run())
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
    import asyncio

    async def _run():
        tree = await _get_file_tree_impl(owner, repo, ref)
        return json.dumps(tree, ensure_ascii=False)

    result = asyncio.run(_run())
    logger.info(f"[github_tools] get_file_tree({owner}/{repo}@{ref}) -> {len(json.loads(result))} items")
    return result


@tool
def read_file_content(owner: str, repo: str, path: str, ref: str) -> str:
    """读取 GitHub 仓库中单个文件的完整内容。

    用途：Agent 需要查看某个文件的实际代码内容时调用。
    适用于读取配置文件、入口文件、核心业务逻辑文件等。

    Args:
        owner: 仓库所有者
        repo:  仓库名
        path:  文件在仓库中的路径（如 "src/app.py"、"package.json"）
        ref:   分支名或 SHA

    Returns:
        文件内容字符串。如果文件过大（> 500KB），自动截断到前 500KB。
    """
    import asyncio

    async def _run():
        content = await _read_file_content_impl(owner, repo, path, ref)
        if len(content) > 512 * 1024:
            content = content[:512 * 1024] + f"\n... [文件过大，已截断到 512KB，原始大小 {len(content)} 字节]"
        return content

    result = asyncio.run(_run())
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

    async def _run():
        blobs = await _get_file_blobs_impl(owner, repo, paths, ref)
        # 截断过大的文件内容
        for k, v in blobs.items():
            if len(v) > 200 * 1024:
                blobs[k] = v[:200 * 1024] + f"\n... [已截断到 200KB]"
        return json.dumps(blobs, ensure_ascii=False)

    result = asyncio.run(_run())
    loaded = len(json.loads(result))
    logger.info(f"[github_tools] get_file_blobs({owner}/{repo}) -> {loaded} files")
    return result


@tool
def search_code(owner: str, repo: str, query: str, language: str = "") -> str:
    """在 GitHub 仓库中搜索代码（使用 GitHub Code Search API）。

    用途：Agent 可以主动搜索关键词，快速定位与特定概念相关的代码文件。
    例如：搜索 "authentication" 找到认证相关文件，搜索 "api" 找到 API 相关文件。

    Args:
        owner:    仓库所有者
        repo:     仓库名
        query:    搜索关键词（支持简单正则，如 "class User"、"def auth"）
        language: 可选，限定编程语言（如 "python", "typescript", "go"）

    Returns:
        JSON 数组字符串，每个元素包含 path, sha, text_matches 等信息，最多 20 条。
    """
    import asyncio

    async def _run():
        return json.dumps(await _search_code_impl(owner, repo, query, language), ensure_ascii=False)

    result = asyncio.run(_run())
    items = json.loads(result)
    logger.info(f"[github_tools] search_code({owner}/{repo}, '{query}') -> {len(items)} results")
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
    import asyncio

    async def _run():
        return json.dumps(
            await _get_commit_history_impl(owner, repo, ref, min(limit, 100)),
            ensure_ascii=False,
        )

    result = asyncio.run(_run())
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
    import asyncio

    async def _run():
        return json.dumps(
            await _get_pull_requests_impl(owner, repo, state, min(limit, 100)),
            ensure_ascii=False,
        )

    result = asyncio.run(_run())
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
    import asyncio

    async def _run():
        return await _get_default_branch_impl(owner, repo)

    result = asyncio.run(_run())
    logger.debug(f"[github_tools] get_default_branch({owner}/{repo}) -> {result}")
    return result
