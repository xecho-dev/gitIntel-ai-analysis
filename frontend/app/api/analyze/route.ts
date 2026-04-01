import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest) {
  const session = await auth();

  if (!session) {
    return NextResponse.json({ error: "未登录" }, { status: 401 });
  }

  const body = await request.json();
  // BFF 接收两种格式：repoUrl (前端直接调用) 或 repo_url (从 api.ts 代理)
  const repoUrl = body.repoUrl ?? body.repo_url;
  const branch = body.branch;

  const upstream = await fetch(`${API_BASE}/api/analyze`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": session.user?.id ?? session.user?.sub ?? "",
    },
    body: JSON.stringify({ repo_url: repoUrl, branch }),
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

  // 收集 SSE 事件，等 stream 结束后一次性保存结果
  const stream = new ReadableStream({
    async start(controller) {
      const encoder = new TextEncoder();
      const decoder = new TextDecoder();
      const collectedEvents: Record<string, unknown>[] = [];
      let hasError = false;
      let buffer = "";
      const reader = upstream.body!.getReader();

      const processLine = (line: string): boolean => {
        if (line.startsWith("data: ")) {
          const data = line.slice(6).trim();
          if (data === "[DONE]") {
            controller.enqueue(new Uint8Array());
            return true;
          }
          try {
            const parsed = JSON.parse(data);
            collectedEvents.push(parsed);
            controller.enqueue(encoder.encode(line + "\n"));
          } catch {
            controller.enqueue(encoder.encode(line + "\n"));
          }
        }
        return false;
      };

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            if (buffer) {
              processLine(buffer);
            }
            break;
          }

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (processLine(line)) {
              hasError = true;
              break;
            }
          }
          if (hasError) break;
        }
      } catch {
        hasError = true;
      }

      // SSE stream 结束后，尝试保存结果到数据库
      if (!hasError && collectedEvents.length > 0) {
        try {
          // 构建 result_data
          const result_data: Record<string, unknown> = {};
          for (const evt of collectedEvents) {
            if (evt.type === "result" && evt.agent && evt.data) {
              result_data[evt.agent as string] = evt.data;
            }
          }
          if (Object.keys(result_data).length > 0) {
            await fetch(`${API_BASE}/api/history/save`, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-User-Id": session.user?.sub ?? "",
              },
              body: JSON.stringify({ repo_url: repoUrl, branch, result_data }),
            });
          }
        } catch {
          // 保存失败不影响主流程
        }
      }

      controller.close();
    },
  });

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
