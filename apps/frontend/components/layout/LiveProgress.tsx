"use client";

import React, { useEffect, useRef } from "react";
import { useAppStore } from "@/store/useAppStore";

const AGENT_LABELS: Record<string, string> = {
  pipeline: "Pipeline",
  react_loader: "仓库加载",
  explorer: "并行探索",
  tech_stack: "技术栈",
  quality: "代码质量",
  dependency: "依赖风险",
  architecture: "架构评估",
  optimization: "优化建议",
  final_result: "汇总",
};

const AGENT_COLORS: Record<string, string> = {
  pipeline: "text-slate-400",
  react_loader: "text-blue-400",
  explorer: "text-violet-400",
  tech_stack: "text-cyan-400",
  quality: "text-yellow-400",
  dependency: "text-orange-400",
  architecture: "text-emerald-400",
  optimization: "text-rose-400",
  final_result: "text-indigo-400",
};

function formatTime(date: Date): string {
  return date.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function formatMessage(msg: string): string {
  // 去掉重复的时间戳前缀（如 10:46:56 [INFO] gitintel:）
  return msg
    .replace(/^\d{2}:\d{2}:\d{2}\s+\[.?\w.?\]\s+gitintel:\s*/, "")
    .trim();
}

export const LiveProgress = () => {
  const isAnalyzing = useAppStore((s) => s.isAnalyzing);
  const messages = useAppStore((s) => s.progressMessages);
  const eventsVersion = useAppStore((s) => s.eventsVersion);
  const scrollRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (!scrollRef.current) return;
    if (isAtBottomRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [eventsVersion, messages.length]);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    isAtBottomRef.current = scrollHeight - scrollTop - clientHeight < 40;
  };

  const done = !isAnalyzing && messages.length > 0;
  const allMessages = done ? messages : messages.slice(-30);

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-white/5 flex-shrink-0">
        <div className="flex items-center gap-2">
          <div
            className={`w-1.5 h-1.5 rounded-full ${
              isAnalyzing ? "bg-blue-400 animate-pulse" : done ? "bg-emerald-400" : "bg-slate-600"
            }`}
          />
          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">
            {isAnalyzing ? "实时分析" : done ? "分析完成" : "等待开始"}
          </span>
        </div>
        {messages.length > 0 && (
          <span className="text-[9px] text-slate-600">{messages.length} 条记录</span>
        )}
      </div>

      {/* Log area */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-3 py-2 space-y-0.5 min-h-0"
        style={{ scrollbarWidth: "thin", scrollbarColor: "#2a3040 transparent" }}
      >
        {allMessages.length === 0 ? (
          <p className="text-[10px] text-slate-600 text-center mt-4">等待分析开始...</p>
        ) : (
          allMessages.map((msg) => {
            const label = AGENT_LABELS[msg.agent] ?? msg.agent;
            const colorClass = AGENT_COLORS[msg.agent] ?? "text-slate-400";
            const isResult = msg.type === "result" || msg.message.includes("完成");
            const isStatus = msg.type === "status";
            const lineColor = isResult
              ? "text-emerald-400/80"
              : isStatus
              ? "text-blue-300/80"
              : colorClass;
            const prefix = isResult ? "✓" : isStatus ? "▸" : "·";

            return (
              <div key={msg.id} className="flex items-start gap-1.5 group">
                <span className="text-[9px] text-slate-600 flex-shrink-0 mt-[3px] select-none w-5">
                  {formatTime(msg.time)}
                </span>
                <span
                  className={`text-[10px] font-medium flex-shrink-0 mt-0.5 w-14 text-right ${colorClass}`}
                >
                  {label}
                </span>
                <span className={`text-[10px] mt-0.5 flex-shrink-0 ${lineColor}`}>
                  {prefix}
                </span>
                <span className={`text-[10px] mt-0.5 ${lineColor} break-all`}>
                  {formatMessage(msg.message)}
                </span>
              </div>
            );
          })
        )}

        {/* Live cursor */}
        {isAnalyzing && (
          <div className="flex items-start gap-1.5">
            <span className="text-[9px] text-slate-600 flex-shrink-0 mt-0.5 select-none w-5">
              {formatTime(new Date())}
            </span>
            <span className="text-[10px] text-right text-blue-400 font-medium flex-shrink-0 mt-0.5 w-14">
              ···
            </span>
            <span className="text-[10px] text-blue-400 mt-0.5 animate-pulse">
              ▌ 分析中...
            </span>
          </div>
        )}
      </div>
    </div>
  );
};
