"use client";

import * as React from "react";
import { MessageCircle, X, Maximize2, Minimize2, Sparkles } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { cn } from "@gitintel/ui";
import { ArrowUpIcon } from "lucide-react";
import { useInitializeSession, getCurrentSessionId } from "./runtime";
import { MarkdownText } from "./markdown-text";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

const DRAWER_WIDTHS = {
  narrow: "max-w-sm",
  wide: "max-w-xl",
} as const;
type DrawerWidth = keyof typeof DRAWER_WIDTHS;

const WIDTH_PX = { narrow: 400, wide: 560 };

const TypingIndicator: React.FC = () => (
  <div className="flex items-center gap-1.5 px-4 py-3">
    <div className="flex size-7 items-center justify-center rounded-full bg-gradient-to-br from-violet-500/20 to-indigo-500/20 border border-violet-500/20">
      <Sparkles className="size-3.5 text-violet-400" />
    </div>
    <div className="flex items-center gap-1 rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
      {[0, 1, 2].map((i) => (
        <motion.div
          key={i}
          className="size-1.5 rounded-full bg-slate-500"
          animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1.2, 0.8] }}
          transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.2 }}
        />
      ))}
    </div>
  </div>
);

const UserBubble: React.FC<{ content: string }> = ({ content }) => (
  <div className="flex justify-end">
    <div className="flex max-w-[80%] items-end gap-2">
      <div className="rounded-2xl rounded-br-md bg-gradient-to-br from-blue-500 to-indigo-600 px-4 py-2.5 text-sm leading-relaxed text-white shadow-lg shadow-blue-500/20">
        {content}
      </div>
      <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-blue-500 text-[10px] font-semibold text-white">
        U
      </div>
    </div>
  </div>
);

const AssistantBubble: React.FC<{ content: string }> = ({ content }) => (
  <div className="flex items-start gap-2.5">
    <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-500 to-indigo-600 text-[10px] font-semibold text-white shadow-lg shadow-violet-500/20">
      <Sparkles className="size-3.5" />
    </div>
    <div className="max-w-[calc(100%-2.5rem)] rounded-2xl rounded-tl-md border border-white/10 bg-white/5 px-4 py-3 shadow-xl shadow-black/10">
      <MarkdownText content={content} />
    </div>
  </div>
);

const EmptyState: React.FC<{ onSubmit: (q: string) => void }> = ({ onSubmit }) => {
  const suggestions = [
    "如何提升代码质量？",
    "有哪些架构问题？",
    "依赖风险有哪些？",
    "最佳重构建议？",
  ];
  return (
    <div className="flex grow flex-col items-center justify-center px-6 py-12">
      <div className="mb-8 flex size-16 items-center justify-center rounded-2xl border border-white/10 bg-gradient-to-br from-violet-500/10 to-indigo-500/10 shadow-2xl shadow-violet-500/10">
        <Sparkles className="size-8 text-violet-400" />
      </div>
      <h2 className="mb-2 text-xl font-bold text-white">
        知识库问答助手
      </h2>
      <p className="mb-8 max-w-xs text-center text-sm leading-relaxed text-slate-400">
        基于你的分析历史，帮你解答代码架构、质量、依赖风险等问题
      </p>
      <div className="flex flex-wrap justify-center gap-2">
        {suggestions.map((q) => (
          <button
            key={q}
            onClick={() => onSubmit(q)}
            className="rounded-full border border-white/10 bg-white/5 px-4 py-1.5 text-xs text-slate-300 transition-all duration-200 hover:border-violet-500/30 hover:bg-violet-500/10 hover:text-violet-300 hover:shadow-lg hover:shadow-violet-500/10"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
};

const RAGChatThread: React.FC<{ drawerWidth: DrawerWidth }> = ({ drawerWidth }) => {
  const isReady = useInitializeSession();

  const [messages, setMessages] = React.useState<Message[]>([]);
  const [inputValue, setInputValue] = React.useState("");
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const viewportRef = React.useRef<HTMLDivElement>(null);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  const isEmpty = messages.length === 0;

  const scrollToBottom = React.useCallback(() => {
    if (viewportRef.current) {
      viewportRef.current.scrollTop = viewportRef.current.scrollHeight;
    }
  }, []);

  React.useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const handleSubmit = async (text: string) => {
    if (!text.trim() || isSubmitting) return;

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: text.trim(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue("");
    setIsSubmitting(true);

    // Auto-resize textarea
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }

    try {
      const response = await fetch("/api/chat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: getCurrentSessionId() ?? "",
          content: text.trim(),
        }),
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const data = await response.json();
      const assistantMessage: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: data.message?.content ?? "抱歉，发生了错误。",
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      const errorMessage: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: `错误: ${(err as Error).message}`,
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Auto-resize textarea
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputValue(e.target.value);
    const ta = e.target;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 128)}px`;
  };

  if (!isReady) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="relative">
            <div className="absolute inset-0 size-8 rounded-full bg-violet-500/30 blur-md" />
            <div className="relative size-8 rounded-full border-2 border-violet-500/30 border-t-violet-400 animate-spin" />
          </div>
          <p className="text-xs text-slate-500">正在初始化...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Message area */}
      <div
        ref={viewportRef}
        className="flex flex-1 flex-col overflow-y-auto scroll-smooth px-4 py-4"
      >
        <div className="mx-auto w-full flex-1">
          <AnimatePresence>
            {isEmpty && <EmptyState onSubmit={handleSubmit} />}
          </AnimatePresence>

          <div className="flex flex-col gap-5">
            <AnimatePresence initial={false}>
              {messages.map((msg) => (
                <motion.div
                  key={msg.id}
                  initial={{ opacity: 0, y: 12, scale: 0.97 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
                >
                  {msg.role === "user" ? (
                    <UserBubble content={msg.content} />
                  ) : (
                    <AssistantBubble content={msg.content} />
                  )}
                </motion.div>
              ))}
            </AnimatePresence>

            <AnimatePresence>
              {isSubmitting && <TypingIndicator />}
            </AnimatePresence>
          </div>
        </div>
      </div>

      {/* Input area */}
      <div className="shrink-0 border-t border-white/10 bg-[#0d1117]/80 px-4 pb-4 pt-3 backdrop-blur-xl">
        <div className="mx-auto">
          <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-[#161b22] shadow-xl shadow-black/20 transition-all focus-within:border-violet-500/40 focus-within:shadow-violet-500/5">
            {/* Subtle gradient overlay */}
            <div className="pointer-events-none absolute inset-0 rounded-2xl bg-gradient-to-br from-white/[0.03] to-transparent" />
            <div className="relative">
              <textarea
                ref={textareaRef}
                value={inputValue}
                onChange={handleInputChange}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSubmit(inputValue);
                  }
                }}
                placeholder="输入你的问题..."
                className="max-h-32 min-h-[44px] w-full resize-none bg-transparent px-4 py-3 pr-14 text-sm text-white placeholder:text-slate-600 outline-none"
                rows={1}
              />
              <button
                disabled={isSubmitting || !inputValue.trim()}
                onClick={() => handleSubmit(inputValue)}
                className={cn(
                  "absolute bottom-2 right-2 flex size-8 items-center justify-center rounded-xl transition-all duration-200",
                  inputValue.trim()
                    ? "bg-gradient-to-br from-blue-500 to-indigo-600 text-white shadow-lg shadow-blue-500/30 hover:from-blue-400 hover:to-indigo-500 hover:shadow-blue-500/50 active:scale-95"
                    : "bg-white/5 text-slate-600"
                )}
              >
                <ArrowUpIcon className="size-4" />
              </button>
            </div>
          </div>
          <p className="mt-1.5 text-center text-[10px] text-slate-600">
            按 Enter 发送，Shift + Enter 换行
          </p>
        </div>
      </div>
    </div>
  );
};

export const ChatDrawer: React.FC = () => {
  const [isOpen, setIsOpen] = React.useState(false);
  const [drawerWidth, setDrawerWidth] = React.useState<DrawerWidth>("narrow");
  const [isHoveringFab, setIsHoveringFab] = React.useState(false);

  const toggleWidth = (e: React.MouseEvent) => {
    e.stopPropagation();
    setDrawerWidth((prev) => (prev === "narrow" ? "wide" : "narrow"));
  };

  return (
    <>
      {/* FAB */}
      <motion.button
        onClick={() => setIsOpen(true)}
        onMouseEnter={() => setIsHoveringFab(true)}
        onMouseLeave={() => setIsHoveringFab(false)}
        className={cn(
          "fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full shadow-2xl shadow-blue-500/20 transition-all focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2 focus:ring-offset-[#0d1117] active:scale-95",
          "bg-gradient-to-br from-blue-500 to-indigo-600 hover:from-blue-400 hover:to-indigo-500 hover:shadow-blue-500/40 hover:scale-105 hover:shadow-2xl"
        )}
        aria-label="打开知识库问答"
        whileTap={{ scale: 0.93 }}
      >
        <motion.div
          animate={{ rotate: isHoveringFab ? [0, 15, -15, 10, -10, 5, -5, 0] : 0 }}
          transition={{ duration: 0.5, ease: "easeInOut" }}
        >
          <MessageCircle className="size-6 text-white drop-shadow-lg" />
        </motion.div>
        {/* Glow ring */}
        <span className="absolute inset-0 rounded-full animate-fabGlow" />
      </motion.button>

      {/* Backdrop */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={() => setIsOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Drawer */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            className={cn(
              "fixed right-0 top-0 z-50 flex h-full flex-col overflow-hidden shadow-2xl shadow-black/50",
              "bg-[#0d1117]/95 border-l border-white/[0.06]",
              "backdrop-blur-xl",
              DRAWER_WIDTHS[drawerWidth]
            )}
            style={{ width: `min(${WIDTH_PX[drawerWidth]}px, 100vw)` }}
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 300 }}
          >
            {/* Header */}
            <div className="flex h-14 shrink-0 items-center justify-between border-b border-white/[0.06] px-4">
              <div className="flex items-center gap-3">
                <div className="flex size-8 items-center justify-center rounded-xl border border-violet-500/20 bg-gradient-to-br from-violet-500/10 to-indigo-500/10 shadow-lg shadow-violet-500/10">
                  <Sparkles className="size-4 text-violet-400" />
                </div>
                <div>
                  <h2 className="text-sm font-bold text-white">知识库问答</h2>
                  <p className="text-[10px] text-slate-500">
                    基于分析历史的 AI 助手
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-1">
                {/* Resize toggle */}
                <button
                  onClick={toggleWidth}
                  className="flex size-8 items-center justify-center rounded-lg text-slate-400 transition-all duration-200 hover:bg-white/10 hover:text-white"
                  title={drawerWidth === "narrow" ? "展开面板" : "收起面板"}
                >
                  {drawerWidth === "narrow" ? (
                    <Maximize2 className="size-4" />
                  ) : (
                    <Minimize2 className="size-4" />
                  )}
                </button>
                {/* Close */}
                <button
                  onClick={() => setIsOpen(false)}
                  className="flex size-8 items-center justify-center rounded-lg text-slate-400 transition-all duration-200 hover:bg-white/10 hover:text-white"
                  aria-label="关闭"
                >
                  <X className="size-4" />
                </button>
              </div>
            </div>

            {/* Body */}
            <div className="flex flex-1 overflow-hidden">
              <RAGChatThread drawerWidth={drawerWidth} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};
