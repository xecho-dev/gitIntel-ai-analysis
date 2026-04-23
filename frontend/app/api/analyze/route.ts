import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

// BFF 只做鉴权和透传，SSE 直接从后端流向客户端
// 历史保存由后端分析完成后自动写入数据库
export async function POST(request: NextRequest) {
  const session = await auth();

  if (!session) {
    return NextResponse.json({ error: "未登录" }, { status: 401 });
  }

  // 从请求头获取原始的 Authorization token，透传到后端用于解密获取用户 GitHub token
  const authHeader = request.headers.get("Authorization");
  const userId = session.user?.id ?? session.user?.sub ?? "";

  const body = await request.json();
  const repoUrl = body.repoUrl ?? body.repo_url;
  const branch = body.branch;
  const skipCache = body.skip_cache ?? false;

  const upstream = await fetch(`${API_BASE}/api/analyze`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": userId,
      ...(authHeader ? { "Authorization": authHeader } : {}),
    },
    body: JSON.stringify({ repo_url: repoUrl, branch, skip_cache: skipCache }),
  });

  if (!upstream.ok) {
    return NextResponse.json(
      { error: `后端请求失败: ${upstream.status}` },
      { status: upstream.status }
    );
  }

  if (!upstream.body) {
    return NextResponse.json({ error: "响应体为空" }, { status: 500 });
  }

  // 直接透传后端 SSE 流，不再自己处理流
  const stream = upstream.body;

  return new NextResponse(stream, {
    status: upstream.status,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
