import React from "react";
import { motion, AnimatePresence } from "motion/react";
import { Code2, GitBranch, AlertTriangle } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { useAppStore } from "@/store/useAppStore";

interface ArchitectureData {
  complexity?: string;
  components?: number;
  techStack?: string[];
  maintainability?: string;
  architectureStyle?: string;
  keyPatterns?: string[];
  hotSpots?: string[];
  summary?: string;
  llmPowered?: boolean;
}

const COMPLEXITY_COLORS: Record<string, string> = {
  Low: "text-emerald-400",
  Medium: "text-yellow-400",
  High: "text-rose-400",
};

export const ArchitectureAgentCard = () => {
  const finishedAgents = useAppStore((s) => s.finishedAgents);
  const activeAgent = useAppStore((s) => s.activeAgent);
  const isAnalyzing = useAppStore((s) => s.isAnalyzing);

  const archEvent = useAppStore((s) => s.agentEvents["architecture"]);
  const techStackEvent = useAppStore((s) => s.agentEvents["tech_stack"]);

  const archDone = finishedAgents.includes("architecture");
  const archData = archEvent?.data as ArchitectureData | undefined;
  const techData = techStackEvent?.data as {
    languages?: string[];
    frameworks?: string[] | { name: string; confidence?: number; evidence?: string[] }[];
  } | undefined;

  const frameworkNames: string[] = (techData?.frameworks ?? []).map((f) =>
    typeof f === "string" ? f : (f as { name: string }).name
  );

  const isScanning = isAnalyzing || activeAgent === "architecture";

  const statusLabel = isScanning
    ? "ANALYZING"
    : archDone
    ? "DONE"
    : "IDLE";

  return (
    <GlassCard className="p-5 relative border-l-2" glow={isScanning}>
      {isScanning && <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-blue-400/80 to-transparent animate-pulse" />}

      {/* ── Header ── */}
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-blue-500/10 flex items-center justify-center text-blue-400">
            <Code2 size={18} />
          </div>
          <div>
            <h3 className="text-sm font-bold">架构分析 Agent</h3>
            <p className="text-[10px] text-blue-400/60 tracking-widest uppercase">
              System Mapping
            </p>
          </div>
        </div>
        <span
          className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
            isScanning
              ? "bg-blue-500/30 text-blue-400 animate-pulse"
              : "bg-emerald-500/20 text-emerald-400"
          }`}
        >
          {statusLabel}
        </span>
      </div>

      {/* ── 真实分析结果 ── */}
      <AnimatePresence mode="wait">
        {archData ? (
          <motion.div
            key="result"
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.96 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
            className="space-y-3"
          >
          {/* 核心指标 */}
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-[#1c2330] rounded p-2 border border-white/5">
              <p className="text-[9px] text-slate-600 uppercase mb-1">复杂度</p>
              <p className={`text-sm font-bold ${COMPLEXITY_COLORS[archData.complexity ?? ''] ?? "text-slate-300"}`}>
                {archData.complexity ?? "—"}
              </p>
            </div>
            <div className="bg-[#1c2330] rounded p-2 border border-white/5">
              <p className="text-[9px] text-slate-600 uppercase mb-1">组件数</p>
              <p className="text-sm font-bold text-blue-400">
                {archData.components ?? "—"}
              </p>
            </div>
            <div className="bg-[#1c2330] rounded p-2 border border-white/5">
              <p className="text-[9px] text-slate-600 uppercase mb-1">可维护性</p>
              <p className="text-sm font-bold text-slate-200">
                {archData.maintainability ?? "—"}
              </p>
            </div>
            <div className="bg-[#1c2330] rounded p-2 border border-white/5">
              <p className="text-[9px] text-slate-600 uppercase mb-1 flex items-center gap-1">
                {archData.llmPowered && <span className="text-[7px] px-1 py-0.5 bg-purple-500/20 text-purple-400 rounded">LLM</span>}
                架构风格
              </p>
              <p className="text-[11px] font-bold text-slate-200 leading-tight">
                {archData.architectureStyle ?? "—"}
              </p>
            </div>
          </div>

          {/* 技术栈标签 */}
          {(archData.techStack ?? techData?.languages ?? frameworkNames.length > 0) && (
            <div>
              <p className="text-[9px] text-slate-600 uppercase mb-1">技术栈</p>
              <div className="flex flex-wrap gap-1">
                {[
                  ...(archData.techStack ?? []),
                  ...(techData?.languages ?? []),
                  ...frameworkNames,
                ]
                  .map((item) => typeof item === "string" ? item : (item as { name?: string }).name ?? JSON.stringify(item))
                  .filter((v, i, a) => v && a.indexOf(v) === i)
                  .slice(0, 8)
                  .map((tag) => (
                    <span
                      key={tag}
                      className="px-1.5 py-0.5 bg-blue-500/10 border border-blue-500/20 rounded text-[10px] text-blue-400"
                    >
                      {tag}
                    </span>
                  ))}
              </div>
            </div>
          )}

          {/* 设计模式 */}
          {archData.keyPatterns && archData.keyPatterns.length > 0 && (
            <div>
              <p className="text-[9px] text-slate-600 uppercase mb-1 flex items-center gap-1">
                <GitBranch size={10} /> 设计模式
              </p>
              <div className="flex flex-wrap gap-1">
                {archData.keyPatterns.slice(0, 4).map((p) => (
                  <span
                    key={p}
                    className="px-1.5 py-0.5 bg-emerald-500/10 border border-emerald-500/20 rounded text-[10px] text-emerald-400"
                  >
                    {p}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* 热点/风险 */}
          {archData.hotSpots && archData.hotSpots.length > 0 && (
            <div>
              <p className="text-[9px] text-slate-600 uppercase mb-1 flex items-center gap-1">
                <AlertTriangle size={10} /> 风险热点
              </p>
              <div className="space-y-0.5">
                {archData.hotSpots.slice(0, 3).map((h, i) => (
                  <p key={i} className="text-[10px] text-rose-400/80 flex items-center gap-1">
                    <span className="text-rose-500">•</span>{h}
                  </p>
                ))}
              </div>
            </div>
          )}

          {/* 摘要 */}
          {archData.summary && (
            <p className="text-[10px] text-slate-400 italic leading-relaxed border-t border-white/5 pt-2">
              {archData.summary}
            </p>
          )}
        </motion.div>
      ) : (
        <motion.div
          key="loading"
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.96 }}
          transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          className="flex flex-col items-center justify-center h-48 gap-2 text-slate-500 text-xs"
        >
          <motion.div
            animate={isScanning ? { translateY: [0, -4, 0] } : { translateY: 0 }}
            transition={isScanning ? { repeat: Infinity, duration: 1.2, ease: "easeInOut" } : {}}
          >
            <Code2 size={24} className="opacity-40" />
          </motion.div>
          <span>{isScanning ? "正在分析项目架构..." : "等待分析开始..."}</span>
        </motion.div>
      )}
      </AnimatePresence>
    </GlassCard>
  );
};
