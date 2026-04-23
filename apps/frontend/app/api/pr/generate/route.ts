import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

/**
 * POST /api/pr/generate
 * 基于分析建议生成代码修改方案
 */
export async function POST(request: NextRequest) {
  const session = await auth();

  if (!session) {
    return NextResponse.json({ error: "未登录" }, { status: 401 });
  }

  const body = await request.json();
  const { repo_url, branch, suggestions, file_contents } = body;

  if (!repo_url || !suggestions) {
    return NextResponse.json(
      { error: "缺少必要参数: repo_url, suggestions" },
      { status: 400 }
    );
  }

  const userId = session.user?.id ?? session.user?.sub ?? "";

  const upstream = await fetch(`${API_BASE}/api/pr/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": userId,
    },
    body: JSON.stringify({ repo_url, branch, suggestions, file_contents }),
  });

  if (!upstream.ok) {
    const err = await upstream.json().catch(() => ({ error: "生成失败" }));
    return NextResponse.json({ error: err.detail ?? "生成失败" }, { status: upstream.status });
  }

  return NextResponse.json(await upstream.json());
}
