/**
 * GitIntel API Client
 *
 * 所有请求通过前端 BFF 层（/api/*）代理，
 * BFF 会自动从 NextAuth Session 中注入用户身份。
 */
/**
 * 从 NextAuth session 中提取用户身份标识
 * 优先用 session.user.id（标准字段），fallback 到 sub（兼容自定义字段）
 */
export function getUserId(
  session: { user?: { id?: string; sub?: string; [key: string]: unknown } }
): string {
  return session.user?.id ?? session.user?.sub ?? "";
}

/**
 * 发起仓库分析请求（支持 SSE 流式响应）
 * @param repoUrl  仓库地址
 * @param branch   分支名（可选）
 * @param userId   当前登录用户 ID（必填，由调用方从 session 获取后传入）
 * @param onEvent  每个 SSE 事件的回调
 */
export async function analyzeRepo(
  repoUrl: string,
  branch: string | undefined,
  userId: string,
  onEvent?: (data: unknown) => void
) {
  // 注意：后端 AnalyzeRequest 使用 snake_case，所以字段名必须是 repo_url
  const body: { repo_url: string; branch?: string } = { repo_url: repoUrl };
  if (branch) body.branch = branch;

  const res = await fetch(`/api/analyze`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      "X-User-Id": userId,
    },
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

