import React from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  BarChart,
  Bar,
  ResponsiveContainer,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
} from "recharts";
import { BarChart3 } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { useAppStore } from "@/store/useAppStore";

interface QualityData {
  health_score?: number;
  test_coverage?: number;
  complexity?: string;
  maintainability?: string;
  duplication?: {
    score?: number;
    duplication_level?: string;
    duplicated_blocks?: number;
  };
  python_metrics?: {
    total_functions?: number;
    over_complexity_count?: number;
    avg_complexity?: number;
    long_functions?: Array<{ function?: string; lines?: number }>;
  };
  typescript_metrics?: {
    total_functions?: number;
    over_complexity_count?: number;
    avg_complexity?: number;
  };
  total_files?: number;
  // LLM 五维评分
  maint_score?: number;
  comp_score?: number;
  dup_score?: number;
  test_score?: number;
  coup_score?: number;
  llmPowered?: boolean;
}

export const QualityAgentCard = () => {
  const finishedAgents = useAppStore((s) => s.finishedAgents);
  const activeAgent = useAppStore((s) => s.activeAgent);
  const isAnalyzing = useAppStore((s) => s.isAnalyzing);
  const qualityEvent = useAppStore((s) => s.agentEvents["quality"]);
  const qualityDone = finishedAgents.includes("quality");
  const isScanning = isAnalyzing || activeAgent === "quality";

  const raw = qualityEvent?.data as QualityData | undefined;
  const complexity = raw?.complexity ?? "—";
  const maintainability = raw?.maintainability ?? "—";
  const pyMetrics = raw?.python_metrics;
  const tsMetrics = raw?.typescript_metrics;

  // LLM 五维评分（无降级，LLM 未返回时各指标为空）
  const maintScore = raw?.maint_score;
  const compScore = raw?.comp_score;
  const dupScore = raw?.dup_score;
  const testScore = raw?.test_score;
  const coupScore = raw?.coup_score;
  const llmPowered = raw?.llmPowered ?? false;
  const hasLlmScores = llmPowered && (maintScore !== undefined || compScore !== undefined || dupScore !== undefined);

  const barData = hasLlmScores
    ? [
        { name: "MAINT", value: maintScore ?? 0, label: "可维护性" },
        { name: "COMP", value: compScore ?? 0, label: "复杂度" },
        { name: "DUP", value: dupScore ?? 0, label: "独特率" },
        { name: "TEST", value: testScore ?? 0, label: "测试覆盖" },
        { name: "COUP", value: coupScore ?? 0, label: "耦合度" },
      ]
    : [];

  const peakIndex = barData.reduce(
    (maxIdx, v, i, arr) => (v.value > arr[maxIdx].value ? i : maxIdx),
    0
  );

  const statusLabel = isScanning
    ? "ANALYZING"
    : qualityDone
    ? "DONE"
    : "IDLE";

  return (
    <GlassCard className="p-5 relative" glow={isScanning}>
      {isScanning && <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-emerald-400/80 to-transparent animate-pulse" />}
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-emerald-500/10 flex items-center justify-center text-emerald-400">
            <BarChart3 size={18} />
          </div>
          <div>
            <h3 className="text-sm font-bold">代码质量 Agent</h3>
            <p className="text-[10px] text-emerald-400/60 tracking-widest uppercase">
              Quality Pulse
            </p>
          </div>
        </div>
        <span
          className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
            isScanning
              ? "bg-emerald-500/30 text-emerald-400 animate-pulse"
              : qualityDone
              ? "bg-emerald-500/20 text-emerald-400"
              : "bg-slate-700 text-slate-500"
          }`}
        >
          {statusLabel}
        </span>
      </div>
      <div className="h-48">
        <AnimatePresence mode="wait">
          {hasLlmScores ? (
            <motion.div
              key="chart"
              initial={{ opacity: 0, scale: 0.96 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.96 }}
              transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
              className="h-full"
            >
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={barData}>
                  <XAxis dataKey="name" tick={{ fontSize: 9, fill: "#64748b" }} />
                  <YAxis hide domain={[0, 100]} />
                  <Tooltip
                    contentStyle={{
                      background: "#1c2026",
                      border: "1px solid rgba(255,255,255,0.05)",
                      borderRadius: 6,
                      fontSize: 11,
                    }}
                    cursor={{ fill: "rgba(0,226,151,0.05)" }}
                    content={({ active, payload }) => {
                      if (active && payload && payload.length > 0) {
                        const item = barData.find(d => d.value === payload[0].value);
                        return (
                          <div className="bg-[#1c2026] border border-white/5 rounded px-2 py-1.5 text-[11px]">
                            <p className="text-slate-300 font-medium">{item?.name ?? '--'}（{item?.label ?? '--'}）</p>
                            <p className="text-emerald-400">{payload[0].value}分</p>
                          </div>
                        );
                      }
                      return null;
                    }}
                  />
                  <Bar dataKey="value" radius={[2, 2, 0, 0]}>
                    {barData.map((_, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={index === peakIndex ? "#00e297" : "#00e29733"}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>

              <div className="mt-4 grid grid-cols-3 gap-2 text-[10px] text-slate-500">
                <div className="bg-[#31353c] rounded p-2 text-center">
                  <p className="uppercase text-slate-600 mb-1">复杂度</p>
                  <p className={
                    complexity === "Low" ? "text-emerald-400" :
                    complexity === "High" ? "text-rose-400" : "text-yellow-400"
                  }>{complexity}</p>
                </div>
                <div className="bg-[#31353c] rounded p-2 text-center">
                  <p className="uppercase text-slate-600 mb-1">可维护性</p>
                  <p className="text-slate-300">{maintainability}</p>
                </div>
                <div className="bg-[#31353c] rounded p-2 text-center">
                  <p className="uppercase text-slate-600 mb-1">测试覆盖</p>
                  <p className="text-emerald-400">{raw?.test_coverage ? `${raw.test_coverage}%` : "—"}</p>
                </div>
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="loading"
              initial={{ opacity: 0, scale: 0.96 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.96 }}
              transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
              className="flex flex-col items-center justify-center h-full text-slate-500 text-xs gap-2"
            >
            <motion.div
              animate={isScanning ? { scale: [1, 1.2, 1] } : { scale: 1 }}
              transition={isScanning ? { repeat: Infinity, duration: 1.2, ease: "easeInOut" } : {}}
            >
              <BarChart3 size={24} className="opacity-50" />
            </motion.div>
              <span>{isScanning ? "正在生成质量评分..." : "等待分析开始..."}</span>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {(pyMetrics?.over_complexity_count ?? 0) > 0 && (
        <p className="mt-2 text-[10px] text-rose-400">
          ⚠ {pyMetrics?.over_complexity_count} 个高圈复杂度 Python 函数
        </p>
      )}
      {(tsMetrics?.over_complexity_count ?? 0) > 0 && (
        <p className="mt-1 text-[10px] text-rose-400">
          ⚠ {tsMetrics?.over_complexity_count} 个高圈复杂度 TS 函数
        </p>
      )}
    </GlassCard>
  );
};
