"""
Git Commit Service
提供 git status / staged diff / commit 功能，由前端 BFF 调用。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class GitStatus:
    is_repo: bool
    staged_files: list[str]
    unstaged_files: list[str]
    untracked_files: list[str]
    clean: bool
    current_branch: str


@dataclass
class StagedFileDiff:
    filename: str
    diff: str  # unified diff string


@dataclass
class CommitResult:
    success: bool
    commit_hash: str
    message: str
    error: Optional[str] = None


def check_git_repo(repo_path: str = ".") -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except Exception:
        return False


def get_git_status(repo_path: str = ".") -> GitStatus:
    """
    返回当前 git 仓库状态。
    """
    try:
        # 获取当前分支
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        current_branch = branch_result.stdout.strip()

        # git status --porcelain=v1
        status_result = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )

        staged: list[str] = []
        unstaged: list[str] = []
        untracked: list[str] = []

        for line in status_result.stdout.strip().splitlines():
            if not line:
                continue
            # format: XY filename
            index_status = line[0]
            worktree_status = line[1]
            filename = line[3:]

            if index_status == "?":
                untracked.append(filename)
            else:
                staged.append(filename)

            if worktree_status not in (" ", "?"):
                unstaged.append(filename)

        clean = not (staged or unstaged or untracked)

        return GitStatus(
            is_repo=True,
            staged_files=staged,
            unstaged_files=unstaged,
            untracked_files=untracked,
            clean=clean,
            current_branch=current_branch,
        )
    except Exception:
        return GitStatus(
            is_repo=False,
            staged_files=[],
            unstaged_files=[],
            untracked_files=[],
            clean=True,
            current_branch="",
        )


def get_staged_diff(repo_path: str = ".") -> list[StagedFileDiff]:
    """
    返回每个 staged 文件的 unified diff。
    """
    try:
        status = get_git_status(repo_path)
        if not status.staged_files:
            return []

        diffs: list[StagedFileDiff] = []
        for filename in status.staged_files:
            result = subprocess.run(
                ["git", "diff", "--cached", "--", filename],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            diff_text = result.stdout if result.returncode == 0 else ""
            diffs.append(StagedFileDiff(filename=filename, diff=diff_text))

        return diffs
    except Exception:
        return []


def run_git_commit(message: str, repo_path: str = ".") -> CommitResult:
    """
    执行 git commit（所有 staged 文件）。
    """
    try:
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            # 提取 commit hash
            hash_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            commit_hash = hash_result.stdout.strip()[:8]
            return CommitResult(
                success=True,
                commit_hash=commit_hash,
                message=result.stdout.strip(),
                error=None,
            )
        else:
            return CommitResult(
                success=False,
                commit_hash="",
                message="",
                error=result.stderr.strip() or result.stdout.strip(),
            )
    except Exception as e:
        return CommitResult(
            success=False,
            commit_hash="",
            message="",
            error=str(e),
        )
