"use client";

import React, { useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { ChatSidebar, ChatArea } from "@/components/chat";
import { useChatStore } from "@/store/useChatStore";
import type { ChatMessage, ChatSession } from "@/lib/types";

export default function ChatPage() {
  const { status } = useSession();
  const router = useRouter();

  const {
    sessions,
    currentSessionId,
    messages,
    isLoading,
    setSessions,
    setCurrentSessionId,
    setMessages,
    addSession,
    addMessage,
    setIsLoading,
  } = useChatStore();

  // 加载会话列表
  const loadSessions = useCallback(async () => {
    try {
      const res = await fetch("/api/chat/sessions");
      if (!res.ok) return;
      const data = await res.json();
      setSessions(data.items ?? []);
      // 如果有会话且当前没有选中，默认选第一个
      if (data.items?.length > 0 && !currentSessionId) {
        setCurrentSessionId(data.items[0].id);
      }
    } catch {
      // ignore
    }
  }, [setSessions, setCurrentSessionId, currentSessionId]);

  // 加载消息列表
  const loadMessages = useCallback(
    async (sessionId: string) => {
      try {
        const res = await fetch(`/api/chat/sessions/${sessionId}/messages`);
        if (!res.ok) return;
        const data = await res.json();
        setMessages(data.items ?? []);
      } catch {
        // ignore
      }
    },
    [setMessages]
  );

  // 初始化加载
  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/login");
      return;
    }
    if (status === "authenticated") {
      loadSessions();
    }
  }, [status, router, loadSessions]);

  // 切换会话时加载消息
  useEffect(() => {
    if (currentSessionId) {
      loadMessages(currentSessionId);
    } else {
      setMessages([]);
    }
  }, [currentSessionId, loadMessages, setMessages]);

  // 新建对话
  const handleNewChat = async () => {
    if (isLoading) return;
    try {
      const res = await fetch("/api/chat/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "新对话" }),
      });
      if (!res.ok) return;
      const data = await res.json();
      const session: ChatSession = {
        id: data.id,
        title: data.title,
        created_at: data.created_at,
        updated_at: data.created_at,
      };
      addSession(session);
      setCurrentSessionId(data.id);
      setMessages([]);
    } catch {
      // ignore
    }
  };

  // 发送消息
  const handleSend = async (content: string) => {
    if (!currentSessionId) {
      // 如果没有会话，先创建一个
      await handleNewChat();
      // 等待状态更新后再发
      return;
    }

    setIsLoading(true);

    // 先乐观添加用户消息
    const optimisticUserMsg: ChatMessage = {
      id: `temp-${Date.now()}`,
      session_id: currentSessionId,
      role: "user",
      content,
      rag_context: null,
      analysis_id: null,
      created_at: new Date().toISOString(),
    };
    addMessage(optimisticUserMsg);

    try {
      const res = await fetch("/api/chat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: currentSessionId, content }),
      });

      if (!res.ok) {
        throw new Error(`请求失败: ${res.status}`);
      }

      const data = await res.json();

      // 用后端返回的真实消息替换乐观消息（通过移除临时消息再添加）
      // 实际上我们直接添加后端返回的 assistant 消息
      if (data.message) {
        addMessage(data.message);
      }

      // 更新会话标题（用第一条用户消息的前 20 字符）
      if (content.length > 0) {
        setSessions(
          sessions.map((s) =>
            s.id === currentSessionId
              ? { ...s, title: content.slice(0, 20) + (content.length > 20 ? "..." : "") }
              : s
          )
        );
      }
    } catch (err) {
      console.error("发送消息失败:", err);
      // 可以在这里添加错误提示
    } finally {
      setIsLoading(false);
    }
  };

  // 快速提问
  useEffect(() => {
    const handler = (e: Event) => {
      const customEvent = e as CustomEvent<string>;
      handleSend(customEvent.detail);
    };
    window.addEventListener("chat:quickask", handler);
    return () => window.removeEventListener("chat:quickask", handler);
  }, [currentSessionId]);

  if (status === "loading") {
    return (
      <div className="flex items-center justify-center h-screen bg-[#10141a]">
        <div className="w-8 h-8 border-2 border-blue-400/20 rounded-full border-t-blue-400 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-[#10141a] overflow-hidden">
      <ChatSidebar onNewChat={handleNewChat} />

      <main className="flex-1 flex flex-col overflow-hidden">
        <div className="h-16 border-b border-white/5 flex items-center px-6">
          <div>
            <h1 className="text-base font-bold text-white">知识库问答</h1>
            <p className="text-xs text-slate-500">
              {currentSessionId
                ? `当前会话 · ${messages.length} 条消息`
                : "选择或创建新对话"}
            </p>
          </div>
        </div>

        <div className="flex-1 overflow-hidden">
          {currentSessionId ? (
            <ChatArea
              sessionId={currentSessionId}
              onSend={handleSend}
              isLoading={isLoading}
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <p className="text-slate-500 text-sm">
                从左侧选择一个对话，或点击「新对话」开始
              </p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
