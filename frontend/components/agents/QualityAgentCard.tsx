import React from "react";
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
}

export const QualityAgentCard = () => {
  const qualityEvent = useAppStore((s) => s.agentEvents["quality"]);
  const isAnalyzing = useAppStore((s) => s.isAnalyzing);
  const finishedAgents = useAppStore((s) => s.finishedAgents);
  const qualityDone = finishedAgents.includes("quality");

  const raw = qualityEvent?.data as QualityData | undefined;
  const healthScore = raw?.health_score ?? 0;
  const testCoverage = raw?.test_coverage ?? 0;
  const complexity = raw?.complexity ?? "—";
  const maintainability = raw?.maintainability ?? "—";
  const duplication = raw?.duplication;
  const pyMetrics = raw?.python_metrics;
  const tsMetrics = raw?.typescript_metrics;

  const barData = [
    {
      name: "HEALTH",
      value: Math.round(healthScore),
      label: "健康度",
    },
    {
      name: "COVER",
      value: Math.round(testCoverage),
      label: "测试覆盖",
    },
    {
      name: "DUP",
      value: duplication ? Math.round(100 - (duplication.score ?? 0)) : 0,
      label: "独特率",
    },
    {
      name: "PY-CX",
      value: pyMetrics
        ? Math.min(Math.round((pyMetrics.avg_complexity ?? 0) * 10), 100)
        : 0,
      label: "Py 复杂度",
    },
    {
      name: "TS-CX",
      value: tsMetrics
        ? Math.min(Math.round((tsMetrics.avg_complexity ?? 0) * 10), 100)
        : 0,
      label: "Ts 复杂度",
    },
  ];

  const peakIndex = barData.reduce(
    (maxIdx, v, i, arr) => (v.value > arr[maxIdx].value ? i : maxIdx),
    0
  );

  const CELL_COLORS = [
    "#00e297", "#00e297", "#00e297", "#00e297", "#00e297",
  ];

  return (
    <GlassCard className="p-5">
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
        <div className="text-right">
          <span className="text-2xl font-black text-emerald-400">
            {healthScore > 0 ? healthScore : "—"}
          </span>
          <span className="text-[10px] text-slate-500 ml-1">/100</span>
        </div>
      </div>
      <div className="h-48">
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
              formatter={(value: number, name: string) => [
                value,
                barData.find(d => d.name === name)?.label ?? name,
              ]}
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
      </div>
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
          <p className="text-emerald-400">{testCoverage > 0 ? `${testCoverage}%` : "—"}</p>
        </div>
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
