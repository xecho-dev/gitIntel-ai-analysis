"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  useLocalRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";

interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

// Store for managing chat session
let currentSessionId: string | null = null;
export function getCurrentSessionId() {
  return currentSessionId;
}
let sessionPromise: Promise<ChatSession | null> | null = null;

async function getOrCreateSession(): Promise<ChatSession | null> {
  if (currentSessionId) {
    return { id: currentSessionId, title: "", created_at: "", updated_at: "" };
  }

  if (sessionPromise) {
    return sessionPromise;
  }

  sessionPromise = (async () => {
    try {
      const res = await fetch("/api/chat/sessions");
      if (!res.ok) return null;
      const data = await res.json();

      if (data.items?.length > 0) {
        currentSessionId = data.items[0].id;
        return data.items[0];
      }

      // Create new session
      const createRes = await fetch("/api/chat/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "知识库问答" }),
      });
      if (!createRes.ok) return null;
      const newSession = await createRes.json();
      currentSessionId = newSession.id;
      return newSession;
    } catch {
      return null;
    } finally {
      sessionPromise = null;
    }
  })();

  return sessionPromise;
}

// Custom adapter that connects to backend RAG chat API
const RAGChatAdapter: ChatModelAdapter = {
  async run({ messages, abortSignal }) {
    const userMessage = messages[messages.length - 1];
    const content =
      typeof userMessage.content === "string"
        ? userMessage.content
        : "";

    let sessionId = currentSessionId;
    if (!sessionId) {
      const session = await getOrCreateSession();
      sessionId = session?.id ?? "";
    }

    if (!sessionId) {
      return {
        content: [
          {
            type: "text" as const,
            text: "无法创建会话，请刷新页面重试。",
          },
        ],
      };
    }

    try {
      const response = await fetch("/api/chat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, content }),
        signal: abortSignal,
      });

      if (!response.ok) {
        return {
          content: [
            {
              type: "text" as const,
              text: `请求失败: ${response.status}`,
            },
          ],
        };
      }

      const data = await response.json();
      const assistantContent = data.message?.content ?? "抱歉，发生了错误。";

      return {
        content: [{ type: "text" as const, text: assistantContent }],
      };
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        return {
          content: [{ type: "text" as const, text: "已取消" }],
        };
      }
      return {
        content: [
          { type: "text" as const, text: `发生错误: ${(err as Error).message}` },
        ],
      };
    }
  },
};

export function useRAGRuntime() {
  return useLocalRuntime(RAGChatAdapter);
}

export function useInitializeSession() {
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    getOrCreateSession().then((session) => {
      if (session) {
        currentSessionId = session.id;
        setIsReady(true);
      }
    });
  }, []);

  return isReady;
}

/**
 * Returns the AUI client for use with AuiProvider.
 * Must be called inside an AuiProvider tree (or establishes its own via useLocalRuntime).
 */
export function useRAGAui() {
  const runtime = useRAGRuntime();
  return runtime.__aiClient;
}
