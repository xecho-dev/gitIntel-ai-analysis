import React from "react";
import { Zap, Rocket } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { useAppStore } from "@/store/useAppStore";

interface SuggestionData {
  suggestions?: Array<{
    id?: number;
    type?: string;
    title?: string;
    description?: string;
    priority?: string;
    done?: boolean;
  }>;
  high_priority?: number;
  medium_priority?: number;
  low_priority?: number;
}

const PRIORITY_STYLES: Record<string, { bg: string; text: string }> = {
  high: { bg: "bg-rose-500/20", text: "text-rose-400" },
  medium: { bg: "bg-yellow-500/20", text: "text-yellow-400" },
  low: { bg: "bg-blue-500/20", text: "text-blue-400" },
};

export const OptimizationAgentCard = () => {
  const isAnalyzing = useAppStore((s) => s.isAnalyzing);
  const finishedAgents = useAppStore((s) => s.finishedAgents);
  const suggestionEvent = useAppStore((s) => s.agentEvents["optimization"]);
  const suggestionDone = finishedAgents.includes("optimization");

  const raw = suggestionEvent?.data as SuggestionData | undefined;
  const suggestions = raw?.suggestions ?? [];
  const displaySuggestions = suggestions.slice(0, 3);

  const statusLabel = isAnalyzing
    ? "AI GENERATING"
    : suggestionDone
    ? "DONE"
    : "IDLE";

  return (
    <GlassCard className="p-5">
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-purple-500/10 flex items-center justify-center text-purple-400">
            <Zap size={18} />
          </div>
          <div>
            <h3 className="text-sm font-bold">优化建议 Agent</h3>
            <p className="text-[10px] text-purple-400/60 tracking-widest uppercase">
              PR Auto-Summary
            </p>
          </div>
        </div>
        <span
          className={`text-[10px] px-2 py-0.5 rounded font-bold ${
            isAnalyzing
              ? "bg-purple-500/20 text-purple-400 animate-pulse"
              : suggestionDone
              ? "bg-emerald-500/20 text-emerald-400"
              : "bg-slate-700 text-slate-500"
          }`}
        >
          {statusLabel}
        </span>
      </div>

      {displaySuggestions.length > 0 ? (
        <div className="space-y-3">
          {displaySuggestions.map((item, i) => {
            const pStyle = PRIORITY_STYLES[item.priority ?? "medium"] ?? PRIORITY_STYLES.medium;
            return (
              <div
                key={i}
                className="p-3 bg-[#31353c] rounded border-l-2 border-purple-400 flex flex-col justify-between"
                style={{ opacity: item.done ? 1 : 0.8 }}
              >
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[10px] font-bold text-purple-400 uppercase">
                      {item.type ?? "优化"}
                    </span>
                    <span
                      className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${pStyle.bg} ${pStyle.text}`}
                    >
                      {item.priority ?? "medium"}
                    </span>
                  </div>
                  <h4 className="text-xs font-bold mb-1">{item.title ?? "优化建议"}</h4>
                  <p className="text-[11px] text-slate-400">{item.description ?? ""}</p>
                </div>
                <div className="mt-3 flex justify-end">
                  <button className="px-3 py-1.5 bg-blue-500/10 border border-blue-500/30 rounded-lg flex items-center gap-2 text-[10px] font-bold text-blue-400 hover:bg-blue-500/20 transition-all">
                    <Rocket size={12} />
                    <span>一键提交 PR</span>
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center h-32 text-slate-500 text-xs gap-2">
          <Zap size={24} className="opacity-50" />
          <span>{isAnalyzing ? "正在生成优化建议..." : "暂无优化建议"}</span>
        </div>
      )}
    </GlassCard>
  );
};
