import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export async function POST(request: NextRequest) {
  const session = await auth();

  if (!session) {
    return NextResponse.json({ error: "未登录" }, { status: 401 });
  }

  const body = await request.json();
  const { message } = body;

  if (!message?.trim()) {
    return NextResponse.json({ error: "提交信息不能为空" }, { status: 400 });
  }

  const userId = session.user?.id ?? session.user?.sub ?? "";

  const upstream = await fetch(`${API_BASE}/api/git/commit`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": userId,
    },
    body: JSON.stringify({ message }),
  });

  const data = await upstream.json();

  if (!upstream.ok) {
    return NextResponse.json({ error: data.detail ?? "提交失败" }, { status: upstream.status });
  }

  return NextResponse.json(data);
}
