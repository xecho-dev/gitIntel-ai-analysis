import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export async function GET() {
  const session = await auth();

  if (!session) {
    return NextResponse.json({ error: "未登录" }, { status: 401 });
  }

  const userId = session.user?.id ?? session.user?.sub ?? "";

  const upstream = await fetch(`${API_BASE}/api/git/status`, {
    method: "GET",
    headers: {
      "X-User-Id": userId,
    },
  });

  if (!upstream.ok) {
    return NextResponse.json(
      { error: `后端请求失败: ${upstream.status}` },
      { status: upstream.status }
    );
  }

  const data = await upstream.json();
  return NextResponse.json(data);
}
