"""GitHub PR Service — 通过 GitHub API 创建分支、提交代码、创建 PR。

完整流程：
  1. 解析仓库 URL 获取 owner/repo
  2. 获取 Token 对应的 GitHub 用户名
  3. 判断是否为 Fork 场景（用户 ≠ 仓库 Owner）
  4. 若为 Fork，自动 Fork 仓库
  5. 获取默认分支（base）
  6. 创建新分支（head）
  7. 获取 base 分支的最新 commit SHA
  8. 提交文件修改（一个或多个文件）
  9. 创建 Pull Request
"""

import base64
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("gitintel")


@dataclass
class PRResult:
    """PR 创建结果。"""

    success: bool
    pr_url: str = ""
    pr_number: int = 0
    pr_title: str = ""
    error: str = ""
    is_fork: bool = False  # 是否为 Fork 场景
    fork_url: str = ""  # fork 后的仓库 URL


@dataclass
class DiffResult:
    """单个文件的 Diff 结果。"""

    file: str
    type: str  # replace | insert | delete
    original: str
    updated: str
    diff_content: str  # unified diff 格式


@dataclass
class ForkResult:
    """Fork 操作结果。"""

    success: bool
    owner: str = ""  # fork 后的 owner（当前用户名）
    repo: str = ""  # fork 后的 repo 名（与原仓库同名）
    full_name: str = ""  # fork 后的完整 "owner/repo"
    url: str = ""  # fork 后的仓库 URL
    error: str = ""


def _parse_github_url(url: str) -> tuple[str, str]:
    """解析 GitHub URL 获取 owner 和 repo。"""
    # 清理 URL
    url = re.sub(r"\.git$", "", url)
    url = url.rstrip("/")

    # 支持格式：
    # https://github.com/owner/repo
    # git@github.com:owner/repo.git
    m = re.match(r"https?://github\.com/([^/]+)/([^/.]+)", url)
    if m:
        return m.group(1), m.group(2)

    m = re.match(r"git@github\.com:([^/]+)/([^/]+)", url)
    if m:
        return m.group(1), m.group(2)

    raise ValueError(f"无法解析 GitHub URL: {url}")


def _generate_branch_name(fixes: list[dict]) -> str:
    """根据修复内容生成分支名。"""
    # 基于第一个修复的类型生成描述性分支名
    if fixes:
        first_fix = fixes[0]
        fix_type = first_fix.get("type", "fix")
        file_hint = first_fix.get("file", "code").split("/")[-1].split(".")[0]
        return f"gitintel/auto-{fix_type}-{file_hint}"
    return "gitintel/auto-fix"


class GitHubPRService:
    """GitHub PR 创建服务。"""

    def __init__(self, token: str | None = None):
        self.token = token or os.getenv("GITHUB_TOKEN", "").strip()
        if not self.token:
            raise ValueError("需要设置 GITHUB_TOKEN 环境变量")
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def create_pr(
        self,
        repo_url: str,
        branch: str,
        fixes: list[dict],
        base_branch: str | None = None,
        pr_title: str | None = None,
        pr_body: str | None = None,
        commit_message: str | None = None,
    ) -> PRResult:
        """创建 Pull Request。

        Args:
            repo_url: GitHub 仓库 URL
            branch: 被分析的源分支
            fixes: 代码修改方案列表
            base_branch: PR 的目标分支（默认使用仓库默认分支）
            pr_title: PR 标题
            pr_body: PR 描述
            commit_message: 统一的 commit message（覆盖各文件自己的 reason）
        """
        try:
            owner, repo = _parse_github_url(repo_url)

            # 1. 获取当前 Token 对应的 GitHub 用户名
            gh_username = await self._get_authenticated_user()
            if not gh_username:
                raise PermissionError(
                    "无法获取 GitHub 用户信息，请确认 GITHUB_TOKEN 是否有效且具有 repo 权限。"
                )

            # 2. 判断是否为 Fork 场景
            is_fork = gh_username != owner
            effective_owner = gh_username if is_fork else owner
            effective_repo = repo

            logger.info(
                f"[GitHubPRService] 当前用户={gh_username}, 仓库Owner={owner}, "
                f"is_fork={is_fork}, effective_repo={effective_owner}/{effective_repo}"
            )

            # 3. 若为 Fork，自动创建 Fork
            if is_fork:
                fork_result = await self._ensure_fork_exists(owner, repo, gh_username)
                if not fork_result.success:
                    return PRResult(
                        success=False,
                        error=fork_result.error,
                        is_fork=True,
                    )
                logger.info(f"[GitHubPRService] Fork 已就绪: {fork_result.full_name}")

            # 4. 获取默认分支
            if not base_branch:
                default_branch = await self._get_default_branch(
                    effective_owner, effective_repo
                )
                base_branch = default_branch
            else:
                default_branch = base_branch

            # 5. 获取 base 分支的最新 commit SHA
            base_sha = await self._get_branch_sha(
                effective_owner, effective_repo, base_branch
            )

            # 6. 生成新分支名
            new_branch = _generate_branch_name(fixes)

            # 7. 创建新分支（基于 base_branch）
            await self._create_branch(
                effective_owner, effective_repo, new_branch, base_sha
            )

            # 8. 提交文件修改
            for fix in fixes:
                await self._commit_file(
                    effective_owner, effective_repo, new_branch, fix, commit_message
                )

            # 9. 创建 PR
            pr = await self._create_pull_request(
                effective_owner,
                effective_repo,
                head=new_branch,
                base=base_branch,
                title=pr_title
                or f"GitIntel Auto: {fixes[0].get('reason', 'Code improvements')[:50]}"
                if fixes
                else "GitIntel Auto Fix",
                body=pr_body or self._build_pr_body(fixes),
            )

            return PRResult(
                success=True,
                pr_url=pr.get("html_url", ""),
                pr_number=pr.get("number", 0),
                pr_title=pr.get("title", ""),
                is_fork=is_fork,
                fork_url=f"https://github.com/{effective_owner}/{effective_repo}"
                if is_fork
                else "",
            )

        except PermissionError:
            raise
        except Exception as exc:
            logger.error(f"[GitHubPRService] 创建 PR 失败: {exc}")
            error_msg = str(exc)
            # 提供更友好的错误提示
            if "403" in error_msg:
                if "repo" in error_msg.lower() or "ref" in error_msg.lower():
                    error_msg = (
                        "GitHub Token 权限不足。需要创建具有 'repo' 范围的 Personal Access Token：\n"
                        "1. 访问 https://github.com/settings/tokens\n"
                        "2. 创建新 Token，勾选 'repo' 权限\n"
                        "3. 更新 GITHUB_TOKEN 环境变量"
                    )
            elif "404" in error_msg:
                error_msg = (
                    f"无法创建分支。常见原因：\n"
                    f"1. Token 没有写入 '{owner}/{repo}' 的权限（需具有 repo 权限的 PAT）\n"
                    f"2. 仓库为 Fork，需先在 https://github.com/{owner}/{repo}/settings 开启写入权限\n"
                    f"3. 仓库为 Private，需在 https://github.com/settings/tokens 确认 Token 可访问"
                )
            return PRResult(success=False, error=error_msg)

    async def get_file_content(
        self, owner: str, repo: str, filepath: str, branch: str
    ) -> str | None:
        """从 GitHub API 获取文件原始内容（UTF-8）。

        Returns:
            文件内容字符串，文件不存在时返回 None。
        """
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/repos/{owner}/{repo}/contents/{filepath}",
                    headers=self.headers,
                    params={"ref": branch},
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                data = resp.json()
                # GitHub API 返回 base64 编码内容
                content_b64 = data.get("content", "")
                # 去掉可能的换行
                content_b64 = content_b64.replace("\n", "")
                try:
                    decoded = base64.b64decode(content_b64).decode("utf-8")
                    return decoded
                except Exception:
                    return None
            except Exception:
                return None

    async def _get_authenticated_user(self) -> str | None:
        """获取当前 Token 对应的 GitHub 用户登录名。"""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/user",
                headers=self.headers,
            )
            if resp.status_code in (200,):
                return resp.json().get("login")
            return None

    async def _ensure_fork_exists(
        self,
        upstream_owner: str,
        upstream_repo: str,
        gh_username: str,
    ) -> ForkResult:
        """确保用户已经 Fork 了目标仓库。

        若 Fork 已存在，直接返回；若不存在，自动创建。
        GitHub 的 Fork API 是异步的——返回 202 Accepted 后仓库仍在创建中，
        故本方法轮询等待 Fork 完成（最多 60s）。
        """
        fork_owner = gh_username
        fork_repo = upstream_repo

        # 第一步：检查 Fork 是否已存在（通过尝试读取仓库元信息）
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/repos/{fork_owner}/{fork_repo}",
                headers=self.headers,
            )
            if resp.status_code == 200:
                fork_data = resp.json()
                # 确认这确实是 upstream 的 fork（parent 字段匹配）
                parent = fork_data.get("parent", {})
                if parent.get("full_name") == f"{upstream_owner}/{upstream_repo}":
                    logger.info(
                        f"[_ensure_fork_exists] Fork 已存在: {fork_owner}/{fork_repo}"
                    )
                    return ForkResult(
                        success=True,
                        owner=fork_owner,
                        repo=fork_repo,
                        full_name=f"{fork_owner}/{fork_repo}",
                        url=fork_data.get(
                            "html_url", f"https://github.com/{fork_owner}/{fork_repo}"
                        ),
                    )
                else:
                    # 仓库存在但不是该 upstream 的 fork（名字冲突），提示用户手动处理
                    return ForkResult(
                        success=False,
                        error=(
                            f"仓库 {fork_owner}/{fork_repo} 已存在，但它不是 "
                            f"{upstream_owner}/{upstream_repo} 的 Fork。"
                            "请删除或重命名现有仓库后再试。"
                        ),
                    )

        # 第二步：Fork 不存在，触发创建
        logger.info(
            f"[_ensure_fork_exists] 正在 Fork {upstream_owner}/{upstream_repo} "
            f"到 {fork_owner}/{fork_repo}..."
        )
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base_url}/repos/{upstream_owner}/{upstream_repo}/forks",
                headers=self.headers,
                json={"organization": None},
            )

            if resp.status_code == 202:
                # 创建请求已接收，轮询等待 Fork 完成
                timeout_at = __import__("time").time() + 60
                poll_interval = 3.0

                while __import__("time").time() < timeout_at:
                    await __import__("asyncio").sleep(poll_interval)

                    check = await client.get(
                        f"{self.base_url}/repos/{fork_owner}/{fork_repo}",
                        headers=self.headers,
                    )
                    if check.status_code == 200:
                        fork_data = check.json()
                        parent = fork_data.get("parent", {})
                        if (
                            parent.get("full_name")
                            == f"{upstream_owner}/{upstream_repo}"
                        ):
                            logger.info(
                                f"[_ensure_fork_exists] Fork 创建完成: {fork_owner}/{fork_repo}"
                            )
                            return ForkResult(
                                success=True,
                                owner=fork_owner,
                                repo=fork_repo,
                                full_name=f"{fork_owner}/{fork_repo}",
                                url=fork_data.get(
                                    "html_url",
                                    f"https://github.com/{fork_owner}/{fork_repo}",
                                ),
                            )
                    elif check.status_code == 404:
                        # 还在创建中，继续等待
                        continue
                    else:
                        break

                return ForkResult(
                    success=False,
                    error=(
                        "Fork 请求已提交（202），但等待超时（60s）未能确认 Fork 创建完成。"
                        "请稍后在 GitHub 页面确认 Fork 状态后再试。"
                    ),
                )
            elif resp.status_code == 202:
                # 同上（已在上面处理）
                pass
            elif resp.status_code == 404:
                return ForkResult(
                    success=False,
                    error=(
                        f"仓库 {upstream_owner}/{upstream_repo} 不存在或无权 Fork（404）。"
                    ),
                )
            elif resp.status_code == 403:
                return ForkResult(
                    success=False,
                    error=(
                        "Fork 失败：账户可能已达到 Fork 数量上限，或 Token 权限不足。"
                        "请确认 GITHUB_TOKEN 具有 repo 权限。"
                    ),
                )
            elif resp.status_code == 409:
                # 409 通常意味着 Fork 已存在（race condition）
                # 再查一次
                retry = await client.get(
                    f"{self.base_url}/repos/{fork_owner}/{fork_repo}",
                    headers=self.headers,
                )
                if retry.status_code == 200:
                    return ForkResult(
                        success=True,
                        owner=fork_owner,
                        repo=fork_repo,
                        full_name=f"{fork_owner}/{fork_repo}",
                        url=retry.json().get(
                            "html_url", f"https://github.com/{fork_owner}/{fork_repo}"
                        ),
                    )
                return ForkResult(
                    success=False,
                    error=f"Fork 操作返回 409 但无法确认 Fork 存在: {resp.text}",
                )
            else:
                return ForkResult(
                    success=False,
                    error=f"Fork 请求失败（状态码 {resp.status_code}）: {resp.text}",
                )

        return ForkResult(
            success=False,
            error="Fork 操作异常：未能完成请求",
        )

    async def _get_default_branch(self, owner: str, repo: str) -> str:
        """获取仓库默认分支。"""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}",
                headers=self.headers,
            )
            if resp.status_code == 404:
                raise ValueError(f"仓库不存在: {owner}/{repo}")
            resp.raise_for_status()
            return resp.json().get("default_branch", "main")

    async def _get_branch_sha(self, owner: str, repo: str, branch: str) -> str:
        """获取分支的最新 commit SHA。"""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/branches/{branch}",
                headers=self.headers,
            )
            if resp.status_code == 404:
                raise ValueError(f"分支不存在: {branch}")
            resp.raise_for_status()
            return resp.json()["commit"]["sha"]

    async def _create_branch(
        self, owner: str, repo: str, branch: str, sha: str
    ) -> None:
        """创建新分支。"""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/repos/{owner}/{repo}/git/refs",
                headers=self.headers,
                json={
                    "ref": f"refs/heads/{branch}",
                    "sha": sha,
                },
            )
            # 如果分支已存在（409），忽略
            if resp.status_code == 422:
                # 分支已存在，检查 SHA 是否一致
                existing = await self._get_branch_sha(owner, repo, branch)
                if existing != sha:
                    # 需要更新 ref（先删除再创建）
                    await client.delete(
                        f"{self.base_url}/repos/{owner}/{repo}/git/refs/heads/{branch}",
                        headers=self.headers,
                    )
                    await client.post(
                        f"{self.base_url}/repos/{owner}/{repo}/git/refs",
                        headers=self.headers,
                        json={
                            "ref": f"refs/heads/{branch}",
                            "sha": sha,
                        },
                    )
            elif resp.status_code not in (200, 201):
                resp.raise_for_status()

    async def _commit_file(
        self,
        owner: str,
        repo: str,
        branch: str,
        fix: dict,
        commit_message: str | None = None,
    ) -> None:
        """提交单个文件修改。"""
        filepath = fix.get("file", "")
        fix_type = fix.get("type", "replace")
        original = fix.get("original", "")
        updated = fix.get("updated", "")

        # 生成 diff 内容
        diff_content = self._generate_diff(filepath, original, updated, fix_type)

        # 获取文件的当前 SHA（如果存在）
        file_sha = None
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/repos/{owner}/{repo}/contents/{filepath}",
                    headers=self.headers,
                    params={"ref": branch},
                )
                if resp.status_code == 200:
                    file_sha = resp.json().get("sha")
            except Exception:
                pass

            # 构建提交内容：优先用统一 commit_message，否则用 fix.reason
            if fix_type == "delete":
                content_b64 = ""
            else:
                content_b64 = base64.b64encode(updated.encode("utf-8")).decode("utf-8")

            msg = (
                commit_message
                if commit_message
                else fix.get("reason", "Auto fix by GitIntel")
            )

            commit_data: dict[str, Any] = {
                "message": msg[:72],
                "content": content_b64,
                "branch": branch,
            }
            if file_sha:
                commit_data["sha"] = file_sha

            resp = await client.put(
                f"{self.base_url}/repos/{owner}/{repo}/contents/{filepath}",
                headers=self.headers,
                json=commit_data,
            )
            resp.raise_for_status()

    def _generate_diff(
        self,
        filepath: str,
        original: str,
        updated: str,
        fix_type: str,
    ) -> str:
        """生成 unified diff 格式。"""
        if fix_type == "delete":
            return f"""---
 {filepath}
---

```diff
- {original}
```"""
        elif fix_type == "insert":
            return f"""---
 {filepath}
---

```diff
+ {updated}
```"""
        else:  # replace
            return f"""---
 {filepath}
---

```diff
- {original}
+ {updated}
```"""

    def _build_pr_body(self, fixes: list[dict]) -> str:
        """构建 PR 描述。"""
        lines = [
            "## 🤖 GitIntel 自动修复",
            "",
            "基于代码分析自动生成的修改建议：",
            "",
        ]

        for i, fix in enumerate(fixes[:10], 1):
            lines.append(f"### {i}. `{fix.get('file', '')}`")
            lines.append(f"**类型**: {fix.get('type', 'replace')}")
            if fix.get("reason"):
                lines.append(f"**原因**: {fix['reason']}")
            if fix.get("original") and fix.get("updated"):
                lines.append("```diff")
                lines.append(f"- {fix['original'][:100]}")
                lines.append(f"+ {fix['updated'][:100]}")
                lines.append("```")
            lines.append("")

        lines.extend(
            [
                "---",
                "*此 PR 由 GitIntel 自动生成*",
            ]
        )

        return "\n".join(lines)

    async def _create_pull_request(
        self,
        owner: str,
        repo: str,
        head: str,
        base: str,
        title: str,
        body: str,
    ) -> dict:
        """创建 Pull Request。"""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/repos/{owner}/{repo}/pulls",
                headers=self.headers,
                json={
                    "head": head,
                    "base": base,
                    "title": title,
                    "body": body,
                    "maintainer_can_modify": True,
                },
            )
            resp.raise_for_status()
            return resp.json()
