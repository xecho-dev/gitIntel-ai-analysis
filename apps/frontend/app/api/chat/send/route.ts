import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session) return NextResponse.json({ error: "未登录" }, { status: 401 });

  const userId = session.user?.id ?? session.user?.sub ?? "";

  const res = await fetch(`${API_BASE}/api/chat/send`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": userId,
    },
    body: await request.text(),
  });

  if (!res.ok) {
    return NextResponse.json(
      { error: `后端请求失败: ${res.status}` },
      { status: res.status }
    );
  }

  // SSE 流：直接将后端的 ReadableStream 转发给前端
  if (!res.body) {
    return NextResponse.json({ error: "后端返回空响应" }, { status: 502 });
  }

  const stream = new ReadableStream({
    async start(controller) {
      const reader = res.body!.getReader();
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          controller.enqueue(value);
        }
        controller.close();
      } catch (e) {
        controller.error(e);
      }
    },
  });

  return new Response(stream, {
    status: res.status,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
