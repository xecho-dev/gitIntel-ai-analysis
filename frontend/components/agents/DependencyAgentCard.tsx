import React from "react";
import { ShieldAlert, AlertTriangle, AlertOctagon, CheckCircle2, Package, RefreshCw } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { useAppStore } from "@/store/useAppStore";

interface DependencyData {
  total?: number;
  scanned?: number;
  high?: number;
  medium?: number;
  low?: number;
  risk_level?: string;
  summary?: string[];
  deps?: Array<{
    name?: string;
    version?: string;
    type?: string;
    manager?: string;
    risk_level?: string;
    risk_reason?: string;
  }>;
  outdated_deps?: string[];
}

const RISK_META = {
  "高危": { color: "text-rose-400", bg: "bg-rose-500/20", border: "border-rose-500/30", icon: AlertOctagon },
  "中等": { color: "text-yellow-400", bg: "bg-yellow-500/20", border: "border-yellow-500/30", icon: AlertTriangle },
  "低危": { color: "text-emerald-400", bg: "bg-emerald-500/20", border: "border-emerald-500/30", icon: CheckCircle2 },
  "极低": { color: "text-slate-400", bg: "bg-slate-500/20", border: "border-slate-500/30", icon: CheckCircle2 },
  "未检测": { color: "text-slate-500", bg: "bg-slate-700/50", border: "border-slate-600/30", icon: ShieldAlert },
};

const MANAGER_COLORS: Record<string, string> = {
  npm: "bg-blue-500/20 text-blue-400",
  pip: "bg-green-500/20 text-green-400",
  go: "bg-cyan-500/20 text-cyan-400",
  cargo: "bg-orange-500/20 text-orange-400",
  bundler: "bg-red-500/20 text-red-400",
  composer: "bg-purple-500/20 text-purple-400",
  maven: "bg-red-600/20 text-red-300",
  gradle: "bg-green-700/20 text-green-300",
  poetry: "bg-indigo-500/20 text-indigo-400",
  pipenv: "bg-emerald-500/20 text-emerald-400",
  unknown: "bg-slate-600/20 text-slate-400",
};

function RiskBadge({ level }: { level: string }) {
  const meta = RISK_META[level as keyof typeof RISK_META] ?? RISK_META["未检测"];
  const Icon = meta.icon;
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full font-medium ${meta.bg} ${meta.color} border ${meta.border}`}>
      <Icon size={10} />
      {level}
    </span>
  );
}

export const DependencyAgentCard = () => {
  const isAnalyzing = useAppStore((s) => s.isAnalyzing);
  const finishedAgents = useAppStore((s) => s.finishedAgents);
  const depEvent = useAppStore((s) => s.agentEvents["dependency"]);
  const depDone = finishedAgents.includes("dependency");

  const raw = depEvent?.data as DependencyData | undefined;
  const total = raw?.total ?? 0;
  const high = raw?.high ?? 0;
  const medium = raw?.medium ?? 0;
  const low = raw?.low ?? 0;
  const riskLevel = raw?.risk_level ?? "未检测";
  const summary = raw?.summary ?? [];
  const deps = raw?.deps ?? [];
  const outdated = raw?.outdated_deps ?? [];

  const meta = RISK_META[riskLevel as keyof typeof RISK_META] ?? RISK_META["未检测"];
  const Icon = meta.icon;

  const showResult = depDone || isAnalyzing;

  return (
    <GlassCard className="p-5">
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-3">
          <div className={`w-8 h-8 rounded flex items-center justify-center ${meta.bg}`}>
            <Icon size={18} className={meta.color} />
          </div>
          <div>
            <h3 className="text-sm font-bold">依赖风险 Agent</h3>
            <p className="text-[10px] text-slate-500 tracking-widest uppercase">
              Vulnerability Scan
            </p>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className={`text-[10px] px-2 py-0.5 rounded font-bold ${
            isAnalyzing
              ? `${meta.bg} ${meta.color} animate-pulse`
              : depDone
              ? `${meta.bg} ${meta.color}`
              : "bg-slate-700 text-slate-500"
          }`}>
            {isAnalyzing ? "SCANNING" : depDone ? "DONE" : "IDLE"}
          </span>
          {total > 0 && (
            <span className="text-[9px] text-slate-600">
              <Package size={9} className="inline mr-0.5" />
              {total} 个依赖
            </span>
          )}
        </div>
      </div>

      {showResult ? (
        <div className="space-y-3">
          {/* 进度条 */}
          <div className="h-2 w-full bg-[#1a1a1a] rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-700 ${
                high > 0 ? "bg-rose-500" : medium > 0 ? "bg-yellow-500" : total === 0 ? "bg-slate-600" : "bg-emerald-500"
              }`}
              style={{ width: total > 0 ? "100%" : "100%" }}
            />
          </div>

          {total === 0 ? (
            /* 无依赖文件 */
            <div className="text-center py-3">
              <RefreshCw size={20} className="mx-auto text-slate-600 mb-1" />
              <p className="text-[10px] text-slate-500">未检测到依赖配置文件</p>
              <p className="text-[9px] text-slate-600 mt-0.5">requirements.txt / package.json 等</p>
            </div>
          ) : (
            <>
              {/* H/M/L 计数条 */}
              <div className={`grid grid-cols-3 gap-1.5 rounded-lg p-2 border ${meta.border}`}>
                <div className="text-center">
                  <p className="text-[8px] text-slate-500 uppercase tracking-wider">高危</p>
                  <p className={`text-lg font-bold font-mono ${high > 0 ? "text-rose-400" : "text-slate-600"}`}>
                    {high || "—"}
                  </p>
                </div>
                <div className="text-center border-x border-slate-700/50">
                  <p className="text-[8px] text-slate-500 uppercase tracking-wider">中危</p>
                  <p className={`text-lg font-bold font-mono ${medium > 0 ? "text-yellow-400" : "text-slate-600"}`}>
                    {medium || "—"}
                  </p>
                </div>
                <div className="text-center">
                  <p className="text-[8px] text-slate-500 uppercase tracking-wider">低危</p>
                  <p className="text-lg font-bold font-mono text-slate-400">
                    {low || "—"}
                  </p>
                </div>
              </div>

              {/* 风险等级 */}
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-slate-500">风险等级</span>
                <RiskBadge level={riskLevel} />
              </div>

              {/* 风险依赖列表 */}
              {deps.length > 0 && (
                <div className="space-y-1">
                  <p className="text-[9px] text-slate-600 uppercase tracking-wider">风险依赖</p>
                  <div className="space-y-0.5">
                    {deps.slice(0, 5).map((d, i) => {
                      const isHigh = d.risk_level === "high";
                      return (
                        <div key={i} className={`flex items-start justify-between gap-2 px-2 py-1 rounded text-[10px] ${isHigh ? "bg-rose-500/10" : "bg-yellow-500/10"}`}>
                          <div className="flex items-center gap-1.5 flex-1 min-w-0">
                            <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 mt-0.5 ${isHigh ? "bg-rose-400" : "bg-yellow-400"}`} />
                            <span className={`font-medium truncate ${isHigh ? "text-rose-300" : "text-yellow-300"}`}>
                              {d.name}
                            </span>
                            {d.manager && (
                              <span className={`text-[8px] px-1 rounded flex-shrink-0 ${MANAGER_COLORS[d.manager] ?? MANAGER_COLORS.unknown}`}>
                                {d.manager}
                              </span>
                            )}
                          </div>
                          {d.version && (
                            <span className="text-slate-600 flex-shrink-0">@{d.version}</span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* 过时依赖警告 */}
              {outdated.length > 0 && (
                <div className="space-y-1">
                  <p className="text-[9px] text-slate-600 uppercase tracking-wider">过时依赖</p>
                  {outdated.map((item, i) => {
                    const [name, reason] = item.split(": ");
                    return (
                      <div key={i} className="flex items-start gap-1.5 px-2 py-1 bg-orange-500/5 rounded border border-orange-500/20">
                        <span className="w-1.5 h-1.5 rounded-full bg-orange-400 flex-shrink-0 mt-1" />
                        <div className="flex-1 min-w-0">
                          <span className="text-[10px] text-orange-300 font-medium">{name}</span>
                          {reason && <p className="text-[9px] text-orange-400/70 truncate">{reason}</p>}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* 风险摘要 */}
              {summary.length > 0 && (
                <div className="space-y-0.5">
                  {summary.slice(0, 3).map((line, i) => (
                    <p key={i} className="text-[9px] text-slate-500 leading-relaxed">
                      {line}
                    </p>
                  ))}
                </div>
              )}

              {/* 无风险时的提示 */}
              {high === 0 && medium === 0 && total > 0 && (
                <div className="flex items-center gap-1.5 text-emerald-400/70 text-[10px]">
                  <CheckCircle2 size={12} />
                  <span>未发现高危漏洞，依赖管理状态良好</span>
                </div>
              )}
            </>
          )}
        </div>
      ) : (
        <div className="h-32 flex flex-col items-center justify-center text-slate-500 text-xs gap-2">
          <ShieldAlert size={24} className="opacity-50" />
          <span>{isAnalyzing ? "正在扫描依赖包..." : "等待分析开始..."}</span>
        </div>
      )}
    </GlassCard>
  );
};
