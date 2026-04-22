import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ session_id: string }> }
) {
  const session = await auth();
  if (!session) return NextResponse.json({ error: "未登录" }, { status: 401 });

  const { session_id } = await params;

  const res = await fetch(`${API_BASE}/api/chat/sessions/${session_id}/messages`, {
    headers: { "X-User-Id": session.user?.id ?? session.user?.sub ?? "" },
  });

  if (!res.ok) {
    return NextResponse.json({ error: `后端请求失败: ${res.status}` }, { status: res.status });
  }

  return NextResponse.json(await res.json());
}
