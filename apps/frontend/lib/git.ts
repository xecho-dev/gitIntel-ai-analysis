/**
 * Git Commit API Client
 */

export interface StagedDiff {
  filename: string;
  diff: string;
}

export interface GitStatus {
  is_repo: boolean;
  current_branch: string;
  staged_files: string[];
  unstaged_files: string[];
  untracked_files: string[];
  clean: boolean;
  staged_diffs: StagedDiff[];
}

export interface CommitResult {
  success: boolean;
  commit_hash: string;
  message: string;
  staged_diffs: StagedDiff[];
}

/** 获取当前 git 状态和 staged diff */
export async function fetchGitStatus(): Promise<GitStatus> {
  const res = await fetch("/api/git/status");
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: "未知错误" }));
    throw new Error(err.error ?? `请求失败: ${res.status}`);
  }
  return res.json() as Promise<GitStatus>;
}

/** 执行 git commit */
export async function commitGit(message: string): Promise<CommitResult> {
  const res = await fetch("/api/git/commit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error ?? "提交失败");
  }
  return data as Promise<CommitResult>;
}
