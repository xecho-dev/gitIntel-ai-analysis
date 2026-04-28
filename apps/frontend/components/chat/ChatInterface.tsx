"use client";

import React, { useRef, useEffect, useState, useCallback } from "react";
import { cn } from "@/lib/utils";
import {
  ChevronDown,
  ChevronUp,
  Bot,
  User,
  Send,
  Square,
  MessageSquare,
  Trash2,
} from "lucide-react";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  createdAt?: Date;
}

// ─── Markdown 渲染 ────────────────────────────────────────────────

function MarkdownContent({ content }: { content: string }) {
  const lines = content.split("\n");
  const elements: React.ReactNode[] = [];
  let codeBlock: { lang: string; content: string[] } | null = null;
  let listItems: string[] = [];
  let inList = false;

  const flushCodeBlock = () => {
    if (!codeBlock) return;
    elements.push(
      <pre
        key={`code-${elements.length}`}
        className="bg-[#1a2030] border border-white/10 rounded-lg p-4 my-3 overflow-x-auto text-sm"
      >
        <code className="text-slate-200 font-mono">{codeBlock.content.join("\n")}</code>
      </pre>
    );
    codeBlock = null;
  };

  const flushList = () => {
    if (!inList || listItems.length === 0) return;
    elements.push(
      <ul key={`list-${elements.length}`} className="list-disc pl-5 my-2 space-y-1">
        {listItems.map((item, i) => (
          <li key={i} className="text-slate-300 text-sm leading-relaxed">{item}</li>
        ))}
      </ul>
    );
    listItems = [];
    inList = false;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (line.startsWith("```")) {
      if (codeBlock) {
        flushCodeBlock();
      } else {
        flushList();
        codeBlock = { lang: line.slice(3).trim(), content: [] };
      }
      continue;
    }

    if (codeBlock) {
      codeBlock.content.push(line);
      continue;
    }

    if (line.startsWith("- ") || line.startsWith("* ")) {
      if (!inList) { flushList(); inList = true; }
      listItems.push(line.slice(2));
      continue;
    }
    flushList();

    if (line.startsWith("# ")) {
      elements.push(<h1 key={`h1-${i}`} className="text-xl font-bold text-white mt-5 mb-2">{line.slice(2)}</h1>);
    } else if (line.startsWith("## ")) {
      elements.push(<h2 key={`h2-${i}`} className="text-lg font-semibold text-slate-100 mt-4 mb-2">{line.slice(3)}</h2>);
    } else if (line.startsWith("### ")) {
      elements.push(<h3 key={`h3-${i}`} className="text-base font-medium text-slate-200 mt-3 mb-1">{line.slice(4)}</h3>);
    } else if (line.startsWith("> ")) {
      elements.push(<blockquote key={`q-${i}`} className="border-l-2 border-blue-500/40 pl-4 my-2 text-slate-400 italic text-sm">{line.slice(2)}</blockquote>);
    } else if (line.trim() === "") {
      elements.push(<div key={`sp-${i}`} className="h-1" />);
    } else {
      // Inline: `code` and **bold**
      const parts: React.ReactNode[] = [];
      let last = 0;
      const re = /`([^`]+)`|\*\*([^*]+)\*\*/g;
      let m: RegExpExecArray | null;
      while ((m = re.exec(line)) !== null) {
        if (m.index > last) parts.push(line.slice(last, m.index));
        if (m[1]) {
          parts.push(
            <code key={`ic-${m.index}`} className="bg-[#1a2030] text-blue-300 px-1.5 py-0.5 rounded text-sm font-mono">
              {m[1]}
            </code>
          );
        } else if (m[2]) {
          parts.push(<strong key={`b-${m.index}`} className="text-white font-semibold">{m[2]}</strong>);
        }
        last = m.index + m[0].length;
      }
      if (last < line.length) parts.push(line.slice(last));
      elements.push(
        <p key={`p-${i}`} className="text-slate-300 text-sm leading-relaxed">
          {parts.length > 0 ? parts : line}
        </p>
      );
    }
  }

  flushCodeBlock();
  flushList();
  return <>{elements}</>;
}

// ─── 单条气泡 ────────────────────────────────────────────────────

function ChatBubble({ message }: { message: ChatMessage; isLoading?: boolean }) {
  const isUser = message.role === "user";

  return (
    <div
      className={cn(
        "flex gap-3 w-full",
        isUser ? "flex-row-reverse animate-in slide-in-from-bottom-2" : "animate-in slide-in-from-bottom-2"
      )}
      style={{ animationDuration: "200ms" }}
    >
      <div
        className={cn(
          "flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs",
          isUser ? "bg-blue-500/20 text-blue-400" : "bg-purple-500/20 text-purple-400"
        )}
      >
        {isUser ? <User size={14} /> : <Bot size={14} />}
      </div>

      <div className={cn("flex flex-col max-w-[75%]", isUser ? "items-end" : "items-start")}>
        <div
          className={cn(
            "rounded-2xl px-4 py-3 text-sm leading-relaxed",
            isUser
              ? "bg-blue-500 text-white rounded-tr-sm"
              : "bg-[#1a2030] text-slate-200 border border-white/5 rounded-tl-sm"
          )}
        >
          <MarkdownContent content={message.content} />
        </div>
        {message.createdAt && (
          <span className="text-[10px] text-slate-600 mt-1 px-1">
            {message.createdAt.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
          </span>
        )}
      </div>
    </div>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────────

export interface ChatInterfaceProps {
  sessionId: string;
  initialMessages?: ChatMessage[];
  className?: string;
}

export function ChatInterface({
  sessionId,
  initialMessages = [],
  className,
}: ChatInterfaceProps) {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isExpanded, setIsExpanded] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // 同步外部 initialMessages 变化
  useEffect(() => {
    if (initialMessages.length > 0 && messages.length === 0) {
      setMessages(initialMessages);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialMessages]);

  // 滚动到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages]);

  // ── SSE 消费 ──────────────────────────────────────────────────

  const parseSSE = useCallback((raw: string): { type: string; delta: string; answer: string; [key: string]: unknown } | null => {
    if (raw === "[DONE]") return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }, []);

  const sendMessage = useCallback(async (content: string) => {
    if (!content.trim() || isLoading) return;

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: content.trim(),
      createdAt: new Date(),
    };

    const assistantMsgId = `asst-${Date.now()}`;
    const assistantMsg: ChatMessage = {
      id: assistantMsgId,
      role: "assistant",
      content: "",
      createdAt: new Date(),
    };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setIsLoading(true);
    setError(null);

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId, content: content.trim() }),
        signal: ctrl.signal,
      });

      if (!res.ok) {
        throw new Error(`请求失败: ${res.status}`);
      }

      if (!res.body) throw new Error("后端返回空响应");

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
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          const parsed = parseSSE(raw);
          if (!parsed) continue;

          const t = parsed.type as string;

          if (t === "error") {
            setError((parsed.message as string) ?? "发生错误");
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsgId
                  ? { ...m, content: m.content + `\n[错误] ${parsed.message ?? ""}` }
                  : m
              )
            );
            break;
          }

          if (t === "token") {
            const delta = ((parsed.delta ?? parsed.text ?? "") as string) || "";
            if (delta) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsgId
                    ? { ...m, content: m.content + delta }
                    : m
                )
              );
            }
          }

          if (t === "done") {
            const answer = ((parsed.answer ?? parsed.full_text ?? "") as string) || "";
            if (answer && messages.find((m) => m.id === assistantMsgId)?.content === "") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsgId ? { ...m, content: answer } : m
                )
              );
            }
          }
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      const msg = (err as Error).message ?? "未知错误";
      setError(msg);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsgId
            ? { ...m, content: m.content || `[网络错误] ${msg}` }
            : m
        )
      );
    } finally {
      setIsLoading(false);
      abortRef.current = null;
      textareaRef.current?.focus();
    }
  }, [isLoading, sessionId, parseSSE, messages]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setIsLoading(false);
  }, []);

  // ── 表单提交 ──────────────────────────────────────────────────

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;
    const text = input.trim();
    setInput("");
    sendMessage(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!input.trim() || isLoading) return;
      const text = input.trim();
      setInput("");
      sendMessage(text);
    }
  };

  const adjustTextareaHeight = () => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  };

  // ── 渲染 ──────────────────────────────────────────────────────

  return (
    <div
      className={cn(
        "flex flex-col bg-[#0d1117] border border-white/5 rounded-2xl overflow-hidden shadow-2xl",
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-white/5 bg-[#161b22]">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
          <span className="text-sm font-medium text-slate-200">AI 助手</span>
          <span className="text-xs text-slate-500">· 基于 Qwen</span>
        </div>
        <div className="flex items-center gap-1">
          {isLoading && (
            <button
              onClick={stop}
              className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-all"
              title="停止生成"
            >
              <Square size={14} />
            </button>
          )}
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-1.5 text-slate-500 hover:text-slate-300 hover:bg-white/5 rounded-lg transition-all"
          >
            {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="px-5 py-2 bg-red-500/10 border-b border-red-500/20 text-red-400 text-xs">
          {error}
        </div>
      )}

      {isExpanded && (
        <>
          {/* 消息列表 */}
          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4 min-h-[300px] max-h-[520px]">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full text-center space-y-3 py-12">
                <div className="w-12 h-12 bg-purple-500/10 rounded-2xl flex items-center justify-center">
                  <Bot size={24} className="text-purple-400" />
                </div>
                <p className="text-slate-300 text-sm font-medium">有什么可以帮你的？</p>
                <p className="text-slate-600 text-xs">
                  询问代码架构、依赖风险或优化建议
                </p>
              </div>
            )}

            {messages.map((msg) => (
              <ChatBubble key={msg.id} message={msg} />
            ))}

            {isLoading && messages.length > 0 && messages[messages.length - 1].role !== "assistant" && (
              <ChatBubble message={{ id: "loading", role: "assistant", content: "", createdAt: new Date() }} />
            )}

            <div ref={bottomRef} />
          </div>

          {/* 输入区 */}
          <div className="px-4 py-3 border-t border-white/5 bg-[#161b22]">
            <form onSubmit={handleSubmit} className="flex gap-2 items-end">
              <div className="flex-1 relative">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => { setInput(e.target.value); adjustTextareaHeight(); }}
                  onKeyDown={handleKeyDown}
                  placeholder="输入消息，Enter 发送，Shift+Enter 换行…"
                  rows={1}
                  disabled={isLoading}
                  className="w-full bg-[#0d1117] border border-white/10 rounded-xl px-4 py-3 text-sm text-slate-200 placeholder-slate-600 resize-none focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20 disabled:opacity-50 transition-all"
                  style={{ minHeight: "48px", maxHeight: "160px" }}
                />
              </div>

              <button
                type="submit"
                disabled={!input.trim() || isLoading}
                className="flex-shrink-0 w-10 h-10 bg-blue-500 hover:bg-blue-600 disabled:bg-slate-800 disabled:text-slate-600 text-white rounded-xl flex items-center justify-center transition-all"
              >
                <Send size={16} />
              </button>
            </form>

            <p className="text-[10px] text-slate-700 mt-2 text-center">
              AI 助手可能产生不准确的信息，请核实后再使用
            </p>
          </div>
        </>
      )}
    </div>
  );
}

// ─── 侧边栏 ─────────────────────────────────────────────────────

export interface ChatSidebarProps {
  sessions: Array<{ id: string; title: string; created_at: string; updated_at: string }>;
  currentSessionId: string | null;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  onNewSession: () => void;
}

export function ChatSidebar({
  sessions,
  currentSessionId,
  onSelectSession,
  onDeleteSession,
  onNewSession,
}: ChatSidebarProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  return (
    <div className="flex flex-col h-full bg-[#0d1117] border border-white/5 rounded-2xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-[#161b22]">
        <div className="flex items-center gap-2">
          <MessageSquare size={16} className="text-slate-400" />
          <span className="text-sm font-medium text-slate-200">对话历史</span>
        </div>
        <button
          onClick={onNewSession}
          className="w-7 h-7 bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 rounded-lg flex items-center justify-center transition-all text-lg leading-none font-light"
        >
          +
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-4 py-8">
            <MessageSquare size={28} className="text-slate-700 mb-2" />
            <p className="text-slate-600 text-xs">暂无对话记录</p>
          </div>
        ) : (
          <div className="p-2 space-y-1">
            {sessions.map((s) => (
              <div
                key={s.id}
                onMouseEnter={() => setHoveredId(s.id)}
                onMouseLeave={() => setHoveredId(null)}
                className={cn(
                  "flex items-center gap-2 px-3 py-2 rounded-xl cursor-pointer transition-all group",
                  currentSessionId === s.id
                    ? "bg-blue-500/10 border border-blue-500/20"
                    : "hover:bg-white/5 border border-transparent"
                )}
                onClick={() => onSelectSession(s.id)}
              >
                <MessageSquare
                  size={14}
                  className={cn(
                    "flex-shrink-0",
                    currentSessionId === s.id ? "text-blue-400" : "text-slate-600"
                  )}
                />
                <span
                  className={cn(
                    "flex-1 text-xs truncate",
                    currentSessionId === s.id ? "text-blue-300" : "text-slate-400"
                  )}
                >
                  {s.title}
                </span>

                {hoveredId === s.id && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onDeleteSession(s.id); }}
                    className="flex-shrink-0 p-1 text-slate-600 hover:text-red-400 hover:bg-red-500/10 rounded transition-all"
                  >
                    <Trash2 size={12} />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
