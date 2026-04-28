/**
 * BFF 流式路由 — 代理后端 Multi-Agent SSE
 *
 * 前端 ChatDrawer 发送 POST 请求到这里，格式为：
 *   { sessionId, content }
 *
 * 转发给后端 /api/chat/send，把 session_id 和 content 透传。
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "未登录" }, { status: 401 });
  }

  const userId = session.user?.id ?? session.user?.sub ?? "";
  const body = await request.json();

  const { sessionId, content } = body;

  if (!sessionId || !content) {
    return NextResponse.json(
      { error: "缺少 sessionId 或 content" },
      { status: 400 }
    );
  }

  const res = await fetch(`${API_BASE}/api/chat/send`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": userId,
    },
    body: JSON.stringify({ session_id: sessionId, content }),
  });

  if (!res.ok) {
    return NextResponse.json(
      { error: `后端请求失败: ${res.status}` },
      { status: res.status }
    );
  }

  if (!res.body) {
    return NextResponse.json({ error: "后端返回空响应" }, { status: 502 });
  }

  // 直接透传后端的 SSE 流
  return new Response(res.body, {
    status: res.status,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
