import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export async function POST(request: NextRequest) {
  const session = await auth();

  if (!session) {
    return NextResponse.json({ error: "未登录" }, { status: 401 });
  }

  const body = await request.json();
  const { repo_url, branch, result_data } = body;

  if (!repo_url || !result_data) {
    return NextResponse.json({ error: "缺少必要参数" }, { status: 400 });
  }

  const upstream = await fetch(`${API_BASE}/api/export/pdf`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": session.user?.id ?? session.user?.sub ?? "",
    },
    body: JSON.stringify({ repo_url, branch: branch ?? "main", result_data }),
  });

  if (!upstream.ok) {
    return NextResponse.json(
      { error: `后端请求失败: ${upstream.status}` },
      { status: upstream.status }
    );
  }

  const pdfBuffer = await upstream.arrayBuffer();
  const fileName =
    upstream.headers.get("Content-Disposition")?.match(/filename=(.+)/)?.[1] ??
    "gitintel-report.pdf";

  return new NextResponse(pdfBuffer, {
    status: 200,
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": `attachment; filename="${fileName}"`,
      "Content-Length": String(pdfBuffer.byteLength),
    },
  });
}
