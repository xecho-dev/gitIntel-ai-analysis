"use client";

import React from "react";
import { useChatStore } from "@/store/useChatStore";
import { Trash2, MessageSquare, Plus } from "lucide-react";

interface ChatSidebarProps {
  onNewChat: () => void;
}

export const ChatSidebar = ({ onNewChat }: ChatSidebarProps) => {
  const { sessions, currentSessionId, setCurrentSessionId, removeSession } =
    useChatStore();

  const handleDelete = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    if (!confirm("确定删除此对话？")) return;

    try {
      await fetch(`/api/chat/sessions/${sessionId}`, { method: "DELETE" });
      removeSession(sessionId);
    } catch {
      // ignore
    }
  };

  return (
    <aside className="w-64 shrink-0 flex flex-col border-r border-white/5 bg-[#0d1117] h-full">
      {/* Header */}
      <div className="p-4 border-b border-white/5">
        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-blue-500 hover:bg-blue-600 text-black font-bold text-sm transition-all"
        >
          <Plus size={16} />
          新对话
        </button>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto py-2">
        {sessions.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <MessageSquare size={24} className="mx-auto text-slate-600 mb-2" />
            <p className="text-xs text-slate-500">暂无对话记录</p>
          </div>
        ) : (
          sessions.map((session) => (
            <div
              key={session.id}
              onClick={() => setCurrentSessionId(session.id)}
              className={`group mx-2 my-0.5 px-3 py-2.5 rounded-lg cursor-pointer flex items-center gap-2 transition-all ${
                currentSessionId === session.id
                  ? "bg-blue-500/10 border border-blue-500/20"
                  : "hover:bg-white/5 border border-transparent"
              }`}
            >
              <MessageSquare
                size={14}
                className={
                  currentSessionId === session.id
                    ? "text-blue-400 shrink-0"
                    : "text-slate-500 shrink-0"
                }
              />
              <span
                className={`flex-1 text-xs truncate ${
                  currentSessionId === session.id
                    ? "text-blue-300 font-medium"
                    : "text-slate-400"
                }`}
              >
                {session.title}
              </span>
              <button
                onClick={(e) => handleDelete(e, session.id)}
                className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-500/20 transition-all shrink-0"
                title="删除对话"
              >
                <Trash2 size={12} className="text-red-400" />
              </button>
            </div>
          ))
        )}
      </div>

      {/* Footer hint */}
      <div className="p-4 border-t border-white/5">
        <p className="text-[10px] text-slate-600 text-center leading-relaxed">
          基于知识库的 RAG 问答
          <br />
          分析结果将作为上下文参考
        </p>
      </div>
    </aside>
  );
};
