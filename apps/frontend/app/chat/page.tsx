"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { ChatInterface, ChatSidebar } from "@/components/chat/ChatInterface";
import type { ChatMessage, ChatSession } from "@/lib/types";
import { MessageSquare } from "lucide-react";

export default function ChatPage() {
  const { data: session, status } = useSession();
  const router = useRouter();

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [currentMessages, setCurrentMessages] = useState<ChatMessage[]>([]);

  // 未登录重定向
  useEffect(() => {
    if (status === "unauthenticated") router.push("/login");
  }, [status, router]);

  // 加载会话列表
  useEffect(() => {
    if (status !== "authenticated") return;
    const load = async () => {
      try {
        const res = await fetch("/api/chat/sessions");
        if (res.ok) {
          const data = await res.json();
          setSessions(data.items ?? []);
        }
      } catch { /* ignore */ }
    };
    load();
  }, [status]);

  // 加载指定会话的消息
  const loadMessages = useCallback(async (sessionId: string) => {
    try {
      const res = await fetch(`/api/chat/sessions/${sessionId}/messages`);
      if (res.ok) {
        const data = await res.json();
        const msgs: ChatMessage[] = (data.items ?? []).map(
          (m: Record<string, unknown>) => ({
            id: String(m.id),
            session_id: String(m.session_id),
            role: m.role as "user" | "assistant" | "system",
            content: String(m.content),
            rag_context: null,
            analysis_id: m.analysis_id as string | null,
            created_at: m.created_at as string,
          })
        );
        setCurrentMessages(msgs);
      }
    } catch { /* ignore */ }
  }, []);

  const handleSelectSession = useCallback(
    (id: string) => {
      setCurrentSessionId(id);
      loadMessages(id);
    },
    [loadMessages]
  );

  // 新建会话
  const handleNewSession = useCallback(async () => {
    const now = new Date();
    const title = `${now.toLocaleDateString("zh-CN", { month: "short", day: "numeric" })} 对话`;
    try {
      const res = await fetch("/api/chat/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      if (res.ok) {
        const data = await res.json();
        const s: ChatSession = {
          id: data.id,
          title: data.title,
          created_at: data.created_at,
          updated_at: data.created_at,
        };
        setSessions((prev) => [s, ...prev]);
        setCurrentSessionId(data.id);
        setCurrentMessages([]);
      }
    } catch { /* ignore */ }
  }, []);

  // 删除会话（functional update 避免 stale closure）
  const handleDeleteSession = useCallback(
    (id: string) => {
      setSessions((prev) => {
        const remaining = prev.filter((s) => s.id !== id);
        setCurrentSessionId((current) => {
          if (current === id) {
            if (remaining.length > 0) {
              loadMessages(remaining[0].id);
              return remaining[0].id;
            }
            setCurrentMessages([]);
            return null;
          }
          return current;
        });
        return remaining;
      });
      fetch(`/api/chat/sessions/${id}`, { method: "DELETE" }).catch(() => {/* ignore */});
    },
    [loadMessages]
  );

  if (status === "loading") {
    return (
      <div className="min-h-screen bg-[#10141a] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-blue-400/20 rounded-full border-t-blue-400 animate-spin" />
      </div>
    );
  }

  if (!session) return null;

  // 转换为 ChatInterface 所需的简化格式
  const aiMessages = currentMessages.map((m) => ({
    id: m.id,
    role: m.role,
    content: m.content,
    createdAt: new Date(m.created_at),
  }));

  return (
    <div className="bg-[#10141a]">
      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="flex gap-6 h-[calc(100vh-8rem)]">
          {/* 左侧会话列表 */}
          <div className="w-64 flex-shrink-0">
            <ChatSidebar
              sessions={sessions}
              currentSessionId={currentSessionId}
              onSelectSession={handleSelectSession}
              onDeleteSession={handleDeleteSession}
              onNewSession={handleNewSession}
            />
          </div>

          {/* 右侧聊天区 */}
          <div className="flex-1">
            {currentSessionId ? (
              <ChatInterface
                sessionId={currentSessionId}
                initialMessages={aiMessages}
                className="h-full"
              />
            ) : (
              <div className="h-full flex flex-col items-center justify-center bg-[#0d1117] border border-white/5 rounded-2xl">
                <div className="w-16 h-16 bg-purple-500/10 rounded-2xl flex items-center justify-center mb-4">
                  <MessageSquare size={28} className="text-purple-400" />
                </div>
                <h2 className="text-lg font-semibold text-slate-200 mb-2">开始新对话</h2>
                <p className="text-slate-500 text-sm mb-6 text-center max-w-xs">
                  选择左侧已有对话，或点击左上角
                  <span className="text-blue-400 mx-1">+</span>
                  新建一个会话
                </p>
                <button
                  onClick={handleNewSession}
                  className="px-5 py-2.5 bg-blue-500 hover:bg-blue-600 text-white text-sm font-medium rounded-xl transition-colors"
                >
                  新建对话
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
