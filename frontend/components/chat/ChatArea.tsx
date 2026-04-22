"use client";

import React, { useEffect, useRef } from "react";
import { useChatStore } from "@/store/useChatStore";
import { ChatBubble } from "./ChatBubble";
import { ChatInput } from "./ChatInput";
import { MessageSquarePlus } from "lucide-react";

interface ChatAreaProps {
  onSend: (message: string) => Promise<void>;
  isLoading: boolean;
}

export const ChatArea = ({ onSend, isLoading }: ChatAreaProps) => {
  const { messages } = useChatStore();
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async (message: string) => {
    await onSend(message);
  };

  if (messages.length === 0) {
    return (
      <div className="flex flex-col h-full">
        <EmptyState />
        <div className="mt-auto border-t border-white/5">
          <ChatInput onSend={handleSend} isLoading={isLoading} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Message list */}
      <div ref={containerRef} className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
        {messages.map((msg) => (
          <ChatBubble key={msg.id} message={msg} />
        ))}
        {isLoading && <LoadingIndicator />}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <ChatInput onSend={handleSend} isLoading={isLoading} />
    </div>
  );
};

const EmptyState = () => (
  <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
    <div className="w-16 h-16 rounded-2xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center mb-6">
      <MessageSquarePlus size={28} className="text-blue-400" />
    </div>
    <h3 className="text-xl font-bold text-white mb-3">知识库问答</h3>
    <p className="text-sm text-slate-500 leading-relaxed max-w-sm">
      基于你历史分析结果构建的 RAG 知识库，可以询问关于代码架构、质量、依赖风险等任何问题。
    </p>
    <div className="mt-8 flex flex-wrap justify-center gap-2">
      {[
        "如何提升代码质量？",
        "这个仓库有哪些架构问题？",
        "依赖风险有哪些？",
        "最佳重构建议是什么？",
      ].map((q) => (
        <button
          key={q}
          onClick={() => {
            // Trigger send via keyboard - dispatch a custom event
            window.dispatchEvent(new CustomEvent("chat:quickask", { detail: q }));
          }}
          className="px-3 py-1.5 text-xs rounded-lg bg-white/5 border border-white/8 text-slate-400 hover:text-slate-200 hover:bg-white/10 transition-all"
        >
          {q}
        </button>
      ))}
    </div>
  </div>
);

const LoadingIndicator = () => (
  <div className="flex gap-3 items-start">
    <div className="w-8 h-8 rounded-lg bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center shrink-0">
      <div className="w-3 h-3 rounded-full bg-emerald-400 animate-pulse" />
    </div>
    <div className="px-4 py-3 rounded-2xl rounded-tl-sm bg-white/[0.05] border border-white/[0.08]">
      <div className="flex gap-1">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="w-2 h-2 rounded-full bg-slate-500 animate-bounce"
            style={{ animationDelay: `${i * 150}ms` }}
          />
        ))}
      </div>
    </div>
  </div>
);
