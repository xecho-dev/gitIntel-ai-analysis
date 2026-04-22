"use client";

import React from "react";
import type { ChatMessage as ChatMessageType, RAGSource } from "@/lib/types";
import { Bot, User, ExternalLink, BookOpen } from "lucide-react";

interface ChatBubbleProps {
  message: ChatMessageType;
}

export const ChatBubble = ({ message }: ChatBubbleProps) => {
  const isUser = message.role === "user";

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      {/* Avatar */}
      <div
        className={`w-8 h-8 rounded-lg shrink-0 flex items-center justify-center ${
          isUser ? "bg-blue-500" : "bg-emerald-500/20 border border-emerald-500/30"
        }`}
      >
        {isUser ? (
          <User size={14} className="text-white" />
        ) : (
          <Bot size={14} className="text-emerald-400" />
        )}
      </div>

      <div
        className={`flex flex-col gap-1 max-w-[75%] ${isUser ? "items-end" : "items-start"}`}
      >
        {/* Content */}
        <div
          className={`px-4 py-3 rounded-2xl text-sm leading-relaxed ${
            isUser
              ? "bg-blue-500 text-white rounded-tr-sm"
              : "bg-white/[0.05] border border-white/[0.08] text-slate-200 rounded-tl-sm"
          }`}
        >
          <div className="whitespace-pre-wrap">{message.content}</div>
        </div>

        {/* RAG Sources */}
        {!isUser && message.rag_context && message.rag_context.length > 0 && (
          <div className="mt-2 w-full">
            <div className="flex items-center gap-1.5 mb-2">
              <BookOpen size={11} className="text-slate-500" />
              <span className="text-[10px] text-slate-500 font-bold tracking-widest uppercase">
                参考知识库
              </span>
            </div>
            <div className="flex flex-col gap-1.5">
              {message.rag_context.map((source, i) => (
                <SourceCard key={i} source={source} />
              ))}
            </div>
          </div>
        )}

        {/* Timestamp */}
        <span className="text-[10px] text-slate-600 px-1">
          {new Date(message.created_at).toLocaleTimeString("zh-CN", {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>
    </div>
  );
};

const SourceCard = ({ source }: { source: RAGSource }) => (
  <a
    href={source.repo_url}
    target="_blank"
    rel="noopener noreferrer"
    className="group block glass-card rounded-lg p-3 hover:border-blue-500/30 transition-all cursor-pointer"
  >
    <div className="flex items-start gap-2">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span
            className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
              source.priority === "high"
                ? "bg-red-500/20 text-red-400"
                : source.priority === "medium"
                ? "bg-yellow-500/20 text-yellow-400"
                : "bg-slate-500/20 text-slate-400"
            }`}
          >
            {source.category}
          </span>
          <span className="text-[10px] text-slate-600 truncate">{source.title}</span>
        </div>
        <p className="text-[11px] text-slate-500 leading-relaxed line-clamp-2">
          {source.content}
        </p>
      </div>
      <ExternalLink
        size={12}
        className="text-slate-600 group-hover:text-blue-400 transition-colors shrink-0 mt-0.5"
      />
    </div>
  </a>
);
