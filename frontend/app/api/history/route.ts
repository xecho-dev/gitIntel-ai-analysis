import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import type { HistoryListResponse } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "未登录" }, { status: 401 });
  }

  const { searchParams } = new URL(request.url);
  const page = searchParams.get("page") ?? "1";
  const page_size = searchParams.get("page_size") ?? "20";
  const search = searchParams.get("search") ?? "";

  const upstream = await fetch(
    `${API_BASE}/api/history?page=${page}&page_size=${page_size}${search ? `&search=${encodeURIComponent(search)}` : ""}`,
    {
      headers: {
        "X-User-Id": session.user?.id ?? session.user?.sub ?? "",
      },
    }
  );

  if (!upstream.ok) {
    return NextResponse.json(
      { error: `后端请求失败: ${upstream.status}` },
      { status: upstream.status }
    );
  }

  const data: HistoryListResponse = await upstream.json();
  return NextResponse.json(data);
}
