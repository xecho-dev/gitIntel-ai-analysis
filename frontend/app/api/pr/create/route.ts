import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

/**
 * POST /api/pr/create
 * 创建 GitHub Pull Request
 */
export async function POST(request: NextRequest) {
  const session = await auth();

  if (!session) {
    return NextResponse.json({ error: "未登录" }, { status: 401 });
  }

  const body = await request.json();
  const { repo_url, branch, fixes, base_branch, pr_title, commit_message } = body;

  if (!repo_url || !fixes) {
    return NextResponse.json(
      { error: "缺少必要参数: repo_url, fixes" },
      { status: 400 }
    );
  }

  const userId = session.user?.id ?? session.user?.sub ?? "";

  const upstream = await fetch(`${API_BASE}/api/pr/create`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": userId,
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
