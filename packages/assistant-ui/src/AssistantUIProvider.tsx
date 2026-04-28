"use client";

import {
  AssistantRuntimeProvider,
  Suggestions,
  useAui,
  useLocalRuntime,
} from "@assistant-ui/react";
import type {
  ChatModelAdapter,
  TextMessagePart,
  ThreadUserMessage,
} from "@assistant-ui/react";
import { useInitializeSession, getCurrentSessionId } from "./runtime";

const RAGChatAdapter: ChatModelAdapter = {
  async *run({ messages, abortSignal }) {
    const userMessage = messages[messages.length - 1] as ThreadUserMessage;

    let content = "";
    if (userMessage) {
      for (const part of userMessage.content) {
        if (part.type === "text" && part.text) {
          content += part.text;
        }
      }
    }

    const sessionId = getCurrentSessionId();
    if (!sessionId) {
      yield {
        content: [{ type: "text", text: "会话未初始化，请刷新页面重试" } as TextMessagePart],
        status: { type: "complete" as const, reason: "stop" as const },
      };
      return;
    }

    try {
      const response = await fetch("/api/chat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, content }),
        signal: abortSignal,
      });

      if (!response.ok) {
        yield {
          content: [{ type: "text", text: `请求失败: ${response.status}` } as TextMessagePart],
          status: { type: "complete" as const, reason: "stop" as const },
        };
        return;
      }

      if (!response.body) {
        yield {
          content: [{ type: "text", text: "后端返回空响应" } as TextMessagePart],
          status: { type: "complete" as const, reason: "stop" as const },
        };
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalText = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6).trim();
          if (!data || data === "[DONE]") continue;

          try {
            const event = JSON.parse(data);
            if (event.type === "token" && event.full_text !== undefined) {
              finalText = event.full_text;
              yield {
                content: [{ type: "text", text: finalText } as TextMessagePart],
                status: { type: "running" as const },
              };
            } else if (event.type === "done") {
              finalText = event.answer ?? finalText;
            } else if (event.type === "error") {
              yield {
                content: [{ type: "text", text: `错误: ${event.message}` } as TextMessagePart],
                status: { type: "complete" as const, reason: "stop" as const },
              };
              return;
            }
          } catch {}
        }
      }

      yield {
        content: [{ type: "text", text: finalText } as TextMessagePart],
        status: { type: "complete" as const, reason: "stop" as const },
      };
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        yield {
          content: [{ type: "text", text: "已取消" } as TextMessagePart],
          status: { type: "complete" as const, reason: "stop" as const },
        };
      } else {
        yield {
          content: [{ type: "text", text: `发生错误: ${(err as Error).message}` } as TextMessagePart],
          status: { type: "complete" as const, reason: "stop" as const },
        };
      }
    }
  },
};

export function AssistantUIProvider({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  useInitializeSession();
  const runtime = useLocalRuntime(RAGChatAdapter);

  const aui = useAui({
    suggestions: Suggestions([
      {
        title: "代码质量",
        label: "如何提升代码质量？",
        prompt: "如何提升代码质量？",
      },
      {
        title: "架构问题",
        label: "有哪些架构问题？",
        prompt: "有哪些架构问题？",
      },
      {
        title: "依赖风险",
        label: "依赖风险有哪些？",
        prompt: "依赖风险有哪些？",
      },
      {
        title: "重构建议",
        label: "最佳重构建议？",
        prompt: "最佳重构建议？",
      },
    ]),
  });

  return (
    <AssistantRuntimeProvider aui={aui} runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
