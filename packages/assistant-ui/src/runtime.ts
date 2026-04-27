"use client";

import React, { useState, useEffect, useMemo } from "react";
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

// Track if we have pending operations
let isInitialized = false;

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
      if (!res.ok) {
        console.warn("[runtime] Failed to get sessions:", res.status);
        return null;
      }
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
      if (!createRes.ok) {
        console.warn("[runtime] Failed to create session:", createRes.status);
        return null;
      }
      const newSession = await createRes.json();
      currentSessionId = newSession.id;
      return newSession;
    } catch (err) {
      console.error("[runtime] Session error:", err);
      return null;
    } finally {
      sessionPromise = null;
    }
  })();

  return sessionPromise;
}

// Custom adapter that connects to backend RAG chat API with streaming support
const RAGChatAdapter: ChatModelAdapter = {
  async *run({ messages, abortSignal }) {
    const userMessage = messages[messages.length - 1];

    // Extract text from message parts (content is an array of parts)
    let content = "";
    if (userMessage) {
      const contentArray = userMessage.content as readonly { type: string; text?: string }[];
      for (const part of contentArray) {
        if (part.type === "text" && part.text) {
          content += part.text;
        }
      }
    }

    let sessionId = currentSessionId;
    if (!sessionId) {
      const session = await getOrCreateSession();
      sessionId = session?.id ?? "";
    }

    if (!sessionId) {
      yield {
        content: [
          {
            type: "text" as const,
            text: "无法创建会话，请先访问「账户中心」完成 GitHub 资料同步。",
          },
        ],
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
          content: [
            {
              type: "text" as const,
              text: `请求失败: ${response.status}`,
            },
          ],
          status: { type: "complete" as const, reason: "stop" as const },
        };
        return;
      }

      if (!response.body) {
        yield {
          content: [
            {
              type: "text" as const,
              text: "后端返回空响应",
            },
          ],
          status: { type: "complete" as const, reason: "stop" as const },
        };
        return;
      }

      // SSE streaming
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalText = "";
      let isComplete = false;

      while (!isComplete) {
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
              // Yield partial text while streaming
              yield {
                content: [
                  {
                    type: "text" as const,
                    text: finalText,
                  },
                ],
                status: { type: "running" as const },
              };
            } else if (event.type === "done") {
              finalText = event.answer ?? finalText;
              isComplete = true;
            } else if (event.type === "error") {
              yield {
                content: [
                  {
                    type: "text" as const,
                    text: `错误: ${event.message}`,
                  },
                ],
                status: { type: "complete" as const, reason: "stop" as const },
              };
              return;
            }
            // Skip "connected" and "sources" events
          } catch {
            // ignore parse errors
          }
        }
      }

      // Final complete message
      yield {
        content: [
          {
            type: "text" as const,
            text: finalText,
          },
        ],
        status: { type: "complete" as const, reason: "stop" as const },
      };
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        yield {
          content: [
            {
              type: "text" as const,
              text: "已取消",
            },
          ],
          status: { type: "complete" as const, reason: "stop" as const },
        };
      } else {
        yield {
          content: [
            {
              type: "text" as const,
              text: `发生错误: ${(err as Error).message}`,
            },
          ],
          status: { type: "complete" as const, reason: "stop" as const },
        };
      }
    }
  },
};

export function useRAGRuntime() {
  // Memoize the adapter to prevent recreation on every render
  const adapter = useMemo<ChatModelAdapter>(() => RAGChatAdapter, []);
  return useLocalRuntime(adapter);
}

export function useInitializeSession() {
  const [isReady, setIsReady] = useState(false);

  React.useEffect(() => {
    getOrCreateSession().then((session) => {
      if (session) {
        currentSessionId = session.id;
        setIsReady(true);
      } else {
        // Session creation failed - might need profile sync
        // Try to sync profile first, then retry session creation
        syncProfileAndRetry().then((newSession) => {
          if (newSession) {
            currentSessionId = newSession.id;
            setIsReady(true);
          }
        });
      }
    });
  }, []);

  return isReady;
}

async function syncProfileAndRetry(): Promise<ChatSession | null> {
  try {
    // Get session from useSession to access user info
    const sessionRes = await fetch("/api/auth/session");
    if (!sessionRes.ok) {
      console.warn("[runtime] Failed to get auth session:", sessionRes.status);
      return null;
    }
    const sessionData = await sessionRes.json();
    const user = sessionData?.user;
    if (!user?.login) {
      console.warn("[runtime] No user login found in session");
      return null;
    }

    // Try to sync profile
    const syncRes = await fetch("/api/user/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        login: user.login,
        name: user.name,
        email: user.email,
        avatar_url: user.image ?? null,
      }),
    });

    if (!syncRes.ok) {
      console.warn("[runtime] Failed to sync profile:", syncRes.status);
      return null;
    }

    // Retry session creation
    const res = await fetch("/api/chat/sessions");
    if (!res.ok) {
      console.warn("[runtime] Failed to get sessions after sync:", res.status);
      return null;
    }
    const data = await res.json();

    if (data.items?.length > 0) {
      return data.items[0];
    }

    const createRes = await fetch("/api/chat/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "知识库问答" }),
    });
    if (!createRes.ok) {
      console.warn("[runtime] Failed to create session after sync:", createRes.status);
      return null;
    }
    return await createRes.json();
  } catch (err) {
    console.error("[runtime] Sync profile error:", err);
    return null;
  }
}
