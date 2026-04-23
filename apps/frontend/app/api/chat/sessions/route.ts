import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function GET() {
  const session = await auth();
  if (!session) return NextResponse.json({ error: "未登录" }, { status: 401 });

  const res = await fetch(`${API_BASE}/api/chat/sessions`, {
    headers: { "X-User-Id": session.user?.id ?? session.user?.sub ?? "" },
  });

  if (!res.ok) {
    return NextResponse.json({ error: `后端请求失败: ${res.status}` }, { status: res.status });
  }

  return NextResponse.json(await res.json());
}

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session) return NextResponse.json({ error: "未登录" }, { status: 401 });

  const body = await request.json();

  const res = await fetch(`${API_BASE}/api/chat/sessions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": session.user?.id ?? session.user?.sub ?? "",
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    return NextResponse.json({ error: `后端请求失败: ${res.status}` }, { status: res.status });
  }

  return NextResponse.json(await res.json());
}
