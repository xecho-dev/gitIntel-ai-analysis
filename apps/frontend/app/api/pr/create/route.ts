import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

/**
 * POST /api/pr/create
 * 创建 GitHub Pull Request
 *
 * 需要用户的 GitHub OAuth Token（包含 repo scope）才能以用户身份创建 PR。
 * Token 通过 Authorization header 传递到后端进行解密。
 */
export async function POST(request: NextRequest) {
  const session = await auth();

  if (!session) {
    return NextResponse.json({ error: "未登录" }, { status: 401 });
  }

  // 检查用户是否授权了 repo scope
  const userGithubToken = session.accessToken;
  if (!userGithubToken) {
    return NextResponse.json(
      {
        error: "GitHub 授权不足",
        detail: "创建 PR 需要 GitHub repo 权限。请重新登录并授权 repo 权限。",
        needReauthorize: true,
      },
      { status: 403 }
    );
  }

  const body = await request.json();
  const { repo_url, branch, fixes, base_branch, pr_title, commit_message } = body;

  if (!repo_url || !fixes) {
    return NextResponse.json(
      { error: "缺少必要参数: repo_url, fixes" },
      { status: 400 }
    );
  }

  // 从请求头获取原始的 Authorization token，透传到后端用于解密获取用户 GitHub token
  const authHeader = request.headers.get("Authorization");
  const userId = session.user?.id ?? session.user?.sub ?? "";

  const upstream = await fetch(`${API_BASE}/api/pr/create`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": userId,
      "X-GitHub-Token": session.accessToken ?? "",
      ...(authHeader ? { "Authorization": authHeader } : {}),
    },
    body: JSON.stringify({ repo_url, branch, fixes, base_branch, pr_title, commit_message }),
  });

  if (!upstream.ok) {
    const err = await upstream.json().catch(() => ({ error: "创建 PR 失败" }));
    return NextResponse.json({ error: err.detail ?? "创建 PR 失败" }, { status: upstream.status });
  }

  const data = await upstream.json();
  return NextResponse.json({
    pr_url: data.pr_url,
    pr_number: data.pr_number,
    pr_title: data.pr_title,
    is_fork: data.is_fork ?? false,
    fork_url: data.fork_url ?? "",
  });
}
