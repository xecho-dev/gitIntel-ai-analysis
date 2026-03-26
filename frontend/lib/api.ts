/**
 * GitIntel API Client
 *
 * 所有请求通过前端 BFF 层（/api/*）代理，
 * BFF 会自动从 NextAuth Session 中注入 JWT Token。
 */

/**
 * 发起仓库分析请求（支持 SSE 流式响应）
 * @param repoUrl  仓库地址
 * @param branch   分支名（可选）
 * @param onEvent  每个 SSE 事件的回调
 */
export async function analyzeRepo(
  repoUrl: string,
  branch?: string,
  onEvent?: (data: unknown) => void
) {
  const body: { repoUrl: string; branch?: string } = { repoUrl };
  if (branch) body.branch = branch;

  const res = await fetch(`/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    throw new Error(`API 请求失败: ${res.status} ${res.statusText}`);
  }

  if (!res.body) throw new Error("响应体为空");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();

  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          const data = JSON.parse(line.slice(6));
          onEvent?.(data);
        } catch {
          // ignore parse error
        }
      }
    }
  }
}

