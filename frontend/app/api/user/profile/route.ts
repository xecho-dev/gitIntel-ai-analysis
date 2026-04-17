import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import type { UserProfile } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export async function GET() {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "未登录" }, { status: 401 });
  }

    const upstream = await fetch(`${API_BASE}/api/user/profile`, {
    headers: {
      "X-User-Id": session.user?.id ?? session.user?.sub ?? "",
    },
  });

  if (!upstream.ok) {
    return NextResponse.json(
      { error: `后端请求失败: ${upstream.status}` },
      { status: upstream.status }
    );
  }

  const data: UserProfile = await upstream.json();
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "未登录" }, { status: 401 });
  }

  // 先读取原始 text，避免空 body 时 request.json() 抛 SyntaxError
  const rawBody = await request.text();
  if (!rawBody.trim()) {
    return NextResponse.json({ error: "请求体为空" }, { status: 400 });
  }

  let body: Record<string, unknown>;
  try {
    body = JSON.parse(rawBody);
  } catch {
    return NextResponse.json({ error: "无效的 JSON 格式" }, { status: 400 });
  }

  const upstream = await fetch(`${API_BASE}/api/user/profile`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": session.user?.id ?? session.user?.sub ?? "",
    },
    body: JSON.stringify(body),
  });

  if (!upstream.ok) {
    return NextResponse.json(
      { error: `后端请求失败: ${upstream.status}` },
      { status: upstream.status }
    );
  }

  const data: UserProfile = await upstream.json();
  return NextResponse.json(data);
}
