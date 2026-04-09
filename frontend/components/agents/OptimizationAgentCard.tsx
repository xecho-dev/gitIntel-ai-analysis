import React, { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Zap, Rocket } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { PRCreateModal, CodeFix } from "@/components/ui/PRCreateModal";
import { useAppStore } from "@/store/useAppStore";

interface SuggestionData {
  suggestions?: Array<{
    id?: number;
    type?: string;
    title?: string;
    description?: string;
    priority?: string;
    done?: boolean;
    code_fix?: {
      file: string;
      type: string;
      original: string;
      updated: string;
      reason: string;
    };
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
  const [showPRModal, setShowPRModal] = useState(false);
  const [currentSuggestion, setCurrentSuggestion] = useState<CodeFix | null>(null);
  const isAnalyzing = useAppStore((s) => s.isAnalyzing);
  const activeAgent = useAppStore((s) => s.activeAgent);
  const finishedAgents = useAppStore((s) => s.finishedAgents);
  const suggestionEvent = useAppStore((s) => s.agentEvents["optimization"]);
  const repoUrl = useAppStore((s) => s.repoUrl);

  const suggestionDone = finishedAgents.includes("optimization");
  const isScanning = isAnalyzing || activeAgent === "optimization";

  const raw = suggestionEvent?.data as SuggestionData | undefined;
  const suggestions = raw?.suggestions ?? [];

  const statusLabel = isScanning
    ? "GENERATING"
    : suggestionDone
    ? "DONE"
    : "IDLE";

  return (
    <>
    <GlassCard className="p-5 relative" glow={isScanning}>
      {isScanning && <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-purple-400/80 to-transparent animate-pulse" />}
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
            isScanning
              ? "bg-purple-500/30 text-purple-400 animate-pulse"
              : suggestionDone
              ? "bg-emerald-500/20 text-emerald-400"
              : "bg-slate-700 text-slate-500"
          }`}
        >
          {statusLabel}
        </span>
      </div>

      <AnimatePresence mode="wait">
        {suggestions.length > 0 ? (
          <motion.div
            key="suggestions"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, scale: 0.96 }}
            transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            className="space-y-3 overflow-y-auto max-h-80 pr-1 scrollbar-thin"
          >
            {suggestions.map((item, i) => {
              const pStyle = PRIORITY_STYLES[item.priority ?? "medium"] ?? PRIORITY_STYLES.medium;
              return (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 12, scale: 0.96 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  transition={{ duration: 0.35, delay: i * 0.07, ease: [0.22, 1, 0.36, 1] }}
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
                  <button
                    onClick={() => {
                      const fix = item.code_fix;
                      console.log('💪🐻👉 ~ OptimizationAgentCard ~ fix:', fix)
                      setCurrentSuggestion({
                        file: fix?.file || "",
                        type: (fix?.type as "replace" | "insert" | "delete") || "replace",
                        original: fix?.original || "",
                        updated: fix?.updated || "",
                        description:`${item.type}: ${item.description}`,
                        reason: fix?.reason || "",
                      });
                      setShowPRModal(true);
                    }}
                    className="px-3 py-1.5 bg-blue-500/10 border border-blue-500/30 rounded-lg flex items-center gap-2 text-[10px] font-bold text-blue-400 hover:bg-blue-500/20 transition-all"
                  >
                    <Rocket size={12} />
                    <span>一键提交 PR</span>
                  </button>
                </div>
              </motion.div>
            );
          })}
        </motion.div>
        ) : (
          <motion.div
            key="idle"
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.96 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
            className="flex flex-col items-center justify-center h-32 text-slate-500 text-xs gap-2"
          >
            <motion.div
              animate={isScanning ? { opacity: [0.5, 1, 0.5] } : { opacity: 0.5 }}
              transition={isScanning ? { repeat: Infinity, duration: 0.8, ease: "easeInOut" } : {}}
            >
              <Zap size={24} className="opacity-50" />
            </motion.div>
            <span>{isScanning ? "正在生成优化建议..." : "等待分析开始..."}</span>
          </motion.div>
        )}
        </AnimatePresence>

    </GlassCard>

      <PRCreateModal
        isOpen={showPRModal}
        onClose={() => setShowPRModal(false)}
        suggestion={currentSuggestion}
        repoUrl={repoUrl}
        branch="main"
      />
    </>
  );
};
