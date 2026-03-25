"use client";

import React, { useState } from "react";
import {
  LayoutDashboard,
  History,
  UserCircle,
  Bell,
  Settings,
  ChevronRight,
  Search,
  Filter,
  RefreshCw,
  ShieldAlert,
  Zap,
  CheckCircle2,
  Code2,
  BarChart3,
  Rocket,
  Key,
  CreditCard,
  FileText,
  Trash2,
  Copy,
  ArrowUpRight,
  TrendingUp,
  Github,
  Check,
} from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import {
  BarChart,
  Bar,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { cn } from "@/lib/utils";

// --- Types ---
type Tab = "workspace" | "history" | "account";

// --- Mock Data ---
const QUALITY_PULSE_DATA = [
  { name: "M1", value: 60 },
  { name: "M2", value: 40 },
  { name: "M3", value: 75 },
  { name: "M4", value: 90 },
  { name: "M5", value: 55 },
  { name: "M6", value: 30 },
  { name: "M7", value: 80 },
  { name: "M8", value: 65 },
];

const HISTORY_DATA = [
  {
    id: 1,
    repo: "kubernetes/kubernetes",
    branch: "main",
    date: "2023年10月24日",
    time: "2 小时前完成",
    health: "优 (94%)",
    quality: "A+",
    risk: "极低",
    riskColor: "text-emerald-400",
    riskBg: "bg-emerald-400",
    border: "border-blue-400",
    type: "default",
  },
  {
    id: 2,
    repo: "intel/legacy-app-engine",
    branch: "premium",
    date: "2023年10月20日",
    time: "4 天前完成",
    health: "危 (42%)",
    quality: "C-",
    risk: "高危",
    riskColor: "text-rose-400",
    riskBg: "bg-rose-400",
    border: "border-rose-400",
    type: "premium",
  },
  {
    id: 3,
    repo: "facebook/react",
    version: "v18.2.0",
    date: "2023年09月15日",
    time: "1 个月前完成",
    health: "良 (78%)",
    quality: "B+",
    risk: "中等",
    riskColor: "text-purple-400",
    riskBg: "bg-purple-400",
    border: "border-purple-400",
    type: "version",
  },
];

// --- Components ---

interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
  glow?: boolean;
}

const GlassCard = ({ children, className, glow = false }: GlassCardProps) => (
  <div
    className={cn(
      "bg-[#1c2026]/40 backdrop-blur-xl border border-white/5 rounded-xl overflow-hidden",
      glow && "shadow-[0_0_20px_rgba(172,199,255,0.05)]",
      className
    )}
  >
    {children}
  </div>
);

const Badge = ({
  children,
  variant = "primary",
}: {
  children: React.ReactNode;
  variant?: "primary" | "secondary" | "tertiary" | "error" | "outline";
}) => {
  const variants = {
    primary: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    secondary: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    tertiary: "bg-purple-500/10 text-purple-400 border-purple-500/20",
    error: "bg-rose-500/10 text-rose-400 border-rose-500/20",
    outline: "border-white/10 text-slate-400",
  };
  return (
    <span
      className={cn(
        "px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider border rounded-sm",
        variants[variant]
      )}
    >
      {children}
    </span>
  );
};

// --- View: Workspace ---
function WorkspaceView() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="space-y-10"
    >
      <section className="text-center">
        <h1 className="text-4xl font-black mb-2 tracking-tight">
          智能分析工作台
        </h1>
        <p className="text-slate-400 font-light">
          输入仓库地址，启动深度架构与风险评估
        </p>

        <div className="relative max-w-3xl mx-auto mt-8 flex gap-3 p-1.5 bg-[#1c2026] rounded-xl border border-white/5 shadow-2xl">
          <div className="flex-1 flex items-center px-4 gap-3">
            <Search className="text-slate-500" size={18} />
            <input
              type="text"
              placeholder="https://github.com/facebook/react"
              className="bg-transparent border-none text-[#dfe2eb] w-full focus:ring-0 placeholder:text-slate-600 text-sm"
              defaultValue="https://github.com/facebook/react"
            />
          </div>
          <button className="bg-blue-400 text-blue-950 px-8 py-2.5 font-black text-sm rounded-lg hover:brightness-110 transition-all flex items-center gap-2">
            <span>立即分析</span>
            <Zap size={16} fill="currentColor" />
          </button>
        </div>
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        {/* Left Column: Agents */}
        <div className="xl:col-span-9 grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Architecture Agent */}
          <GlassCard className="p-5 relative border-l-2 border-blue-400" glow>
            <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-blue-400/50 to-transparent animate-pulse" />
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
              <span className="px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-400 text-[10px] font-bold animate-pulse">
                LIVE
              </span>
            </div>
            <div className="bg-[#0a0e14] rounded p-4 font-mono text-[11px] h-48 overflow-y-auto border border-white/5 space-y-1">
              <p className="text-blue-400">[14:20:01] 正在扫描项目目录...</p>
              <p className="text-slate-400">
                [14:20:03] 检测到 React + Vite 技术栈...
              </p>
              <p className="text-slate-400">
                [14:20:05] 正在解析 42 个核心组件...
              </p>
              <p className="text-emerald-400">
                [14:20:07] 正在绘制组件依赖树...
              </p>
              <p className="text-blue-400 animate-pulse">
                _ 正在识别全局状态流 (Zustand)
              </p>
            </div>
          </GlassCard>

          {/* Code Quality Agent */}
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
                <span className="text-2xl font-black text-emerald-400">84</span>
                <span className="text-[10px] text-slate-500 ml-1">HEALTH</span>
              </div>
            </div>
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={QUALITY_PULSE_DATA}>
                  <Bar dataKey="value" radius={[2, 2, 0, 0]}>
                    {QUALITY_PULSE_DATA.map((entry, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={index === 3 ? "#00e297" : "#00e29733"}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-4 flex justify-between text-[10px] text-slate-500">
              <span>复杂度分析: 正常</span>
              <span>单元测试覆盖率: 62%</span>
            </div>
          </GlassCard>

          {/* Dependency Risk Agent */}
          <GlassCard className="p-5">
            <div className="flex justify-between items-start mb-4">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded bg-rose-500/10 flex items-center justify-center text-rose-400">
                  <ShieldAlert size={18} />
                </div>
                <div>
                  <h3 className="text-sm font-bold">依赖风险 Agent</h3>
                  <p className="text-[10px] text-rose-400/60 tracking-widest uppercase">
                    Vulnerability Scan
                  </p>
                </div>
              </div>
              <span className="text-xs font-mono text-slate-500">142/200</span>
            </div>
            <div className="h-32 flex flex-col justify-center gap-4">
              <div className="h-3 w-full bg-[#31353c] rounded-full overflow-hidden p-0.5">
                <div className="h-full bg-rose-400 rounded-full" style={{ width: "71%" }} />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div className="bg-[#31353c] rounded p-2 border border-rose-400/20">
                  <p className="text-[9px] text-slate-500 uppercase">High</p>
                  <p className="text-lg font-bold text-rose-400">2</p>
                </div>
                <div className="bg-[#31353c] rounded p-2">
                  <p className="text-[9px] text-slate-500 uppercase">Medium</p>
                  <p className="text-lg font-bold">12</p>
                </div>
                <div className="bg-[#31353c] rounded p-2">
                  <p className="text-[9px] text-slate-500 uppercase">Low</p>
                  <p className="text-lg font-bold">45</p>
                </div>
              </div>
            </div>
            <div className="mt-2 text-[11px] text-slate-400 italic">
              正在扫描: lodash@4.17.21 (发现 CVE-2020-8203)
            </div>
          </GlassCard>

          {/* Optimization Suggestion Agent */}
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
              <span className="text-[10px] bg-purple-500/10 text-purple-400 px-2 py-0.5 rounded">
                AI GENERATING
              </span>
            </div>
            <div className="space-y-3">
              <div className="p-3 bg-[#31353c] rounded border-l-2 border-purple-400 flex flex-col justify-between">
                <h4 className="text-xs font-bold mb-1">性能提升建议 #1</h4>
                <p className="text-[11px] text-slate-400">
                  将 `Context.Provider` 拆分为更细粒度的组件以减少重绘。
                </p>
                <div className="mt-3 flex justify-end">
                  <button className="px-3 py-1.5 bg-blue-500/10 border border-blue-500/30 rounded-lg flex items-center gap-2 text-[10px] font-bold text-blue-400 hover:bg-blue-500/20 transition-all">
                    <Rocket size={12} />
                    <span>一键提交 PR</span>
                  </button>
                </div>
              </div>
              <div className="p-3 bg-[#31353c] rounded border-l-2 border-purple-400 opacity-60 flex flex-col justify-between">
                <h4 className="text-xs font-bold mb-1">重构建议 #2</h4>
                <p className="text-[11px] text-slate-400">
                  检测到 3 处冗余的 `useEffect` 逻辑，建议合并为自定义 Hook...
                </p>
                <div className="mt-3 flex justify-end">
                  <button className="px-3 py-1.5 bg-blue-500/10 border border-blue-500/30 rounded-lg flex items-center gap-2 text-[10px] font-bold text-blue-400">
                    <Rocket size={12} />
                    <span>一键提交 PR</span>
                  </button>
                </div>
              </div>
            </div>
          </GlassCard>
        </div>

        {/* Right Column: Sidebar */}
        <div className="xl:col-span-3 space-y-6">
          <GlassCard className="p-6 relative overflow-hidden">
            <div className="absolute top-0 right-0 w-32 h-32 bg-blue-500/10 blur-[60px] -mr-16 -mt-16" />
            <div className="flex justify-between items-center mb-6">
              <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider">
                方案对比
              </h3>
              <span className="px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 text-[10px] font-bold">
                当前: 免费版
              </span>
            </div>
            <div className="space-y-4 mb-6">
              <div className="p-3 rounded-lg border border-white/5 bg-white/5 opacity-80">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-sm font-bold">免费版</span>
                  <span className="text-[10px] text-slate-500">$0/月</span>
                </div>
                <ul className="space-y-1.5">
                  <li className="flex items-center gap-2 text-[10px] text-slate-400">
                    <CheckCircle2 size={12} className="text-emerald-400" />
                    3次/日 基础分析
                  </li>
                </ul>
              </div>
              <div className="p-3 rounded-lg border border-blue-400/30 bg-blue-500/5 ring-1 ring-blue-400/20">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-sm font-bold text-blue-400">
                    开发者 Pro
                  </span>
                  <span className="text-[10px] text-blue-400">$19/月</span>
                </div>
                <ul className="space-y-1.5">
                  <li className="flex items-center gap-2 text-[10px] text-slate-300">
                    <CheckCircle2 size={12} className="text-blue-400" />
                    无限次深度分析
                  </li>
                  <li className="flex items-center gap-2 text-[10px] text-slate-300">
                    <CheckCircle2 size={12} className="text-blue-400" />
                    AI 架构优化建议
                  </li>
                </ul>
              </div>
            </div>
            <button className="w-full py-3 bg-blue-500 text-blue-950 font-black rounded-lg shadow-lg shadow-blue-500/20 hover:brightness-110 active:scale-95 transition-all flex items-center justify-center gap-2 mb-4">
              <Zap size={16} fill="currentColor" />
              立即升级 Pro
            </button>
            <button className="w-full text-[10px] text-slate-500 hover:text-blue-400 transition-colors flex items-center justify-center gap-1 group">
              查看完整功能对比
              <ChevronRight
                size={12}
                className="group-hover:translate-x-0.5 transition-transform"
              />
            </button>
          </GlassCard>

          <GlassCard className="p-6">
            <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-4">
              分析结果预览
            </h3>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400">架构复杂度</span>
                <span className="text-xs font-mono px-1.5 py-0.5 bg-[#31353c] rounded">
                  Medium
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400">维护性评分</span>
                <span className="text-xs font-mono text-emerald-400 font-bold">
                  A-
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400">代码体积</span>
                <span className="text-xs font-mono">1.2 MB</span>
              </div>
            </div>
            <div className="mt-6 p-4 rounded-lg bg-[#0a0e14] border border-white/5">
              <div className="flex items-center gap-3 mb-3">
                <div className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                <span className="text-[10px] text-slate-500 uppercase">
                  实时洞察
                </span>
              </div>
              <p className="text-xs leading-relaxed text-[#dfe2eb]">
                当前项目存在较大的组件重叠风险，建议在第 4 阶段进行模块解耦。
              </p>
            </div>
          </GlassCard>
        </div>
      </div>
    </motion.div>
  );
}

// --- View: History ---
function HistoryView() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="space-y-8"
    >
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div>
          <h1 className="text-4xl font-black tracking-tighter mb-2">
            分析历史记录
          </h1>
          <p className="text-slate-400">
            深度审计资产库：追溯代码演进与安全态势
          </p>
        </div>
        <div className="flex gap-4">
          <div className="relative group">
            <input
              type="text"
              placeholder="搜索存储库..."
              className="bg-[#1c2026] border-none text-[#dfe2eb] px-4 py-2 pl-10 rounded-sm focus:ring-1 focus:ring-blue-500 w-64 transition-all text-sm"
            />
            <Search
              className="absolute left-3 top-2.5 text-slate-500"
              size={16}
            />
          </div>
          <button className="bg-[#1c2026] p-2 px-4 rounded-sm hover:bg-[#31353c] transition-colors flex items-center gap-2 text-sm">
            <Filter size={16} />
            <span>筛选</span>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <GlassCard className="p-6 flex flex-col justify-between">
          <span className="text-slate-500 text-[10px] uppercase tracking-widest mb-4">
            扫描总计
          </span>
          <div className="text-4xl font-bold text-blue-400">128</div>
          <div className="mt-4 flex items-center gap-1 text-emerald-400 text-xs">
            <TrendingUp size={12} />
            <span>本月 +12%</span>
          </div>
        </GlassCard>
        <GlassCard className="p-6 flex flex-col justify-between">
          <span className="text-slate-500 text-[10px] uppercase tracking-widest mb-4">
            平均健康得分
          </span>
          <div className="text-4xl font-bold text-emerald-400">84.2</div>
          <div className="mt-4 h-1 bg-[#1c2026] rounded-full overflow-hidden">
            <div className="h-full bg-emerald-400 w-[84%]" />
          </div>
        </GlassCard>
        <GlassCard
          className="p-6 col-span-2 relative overflow-hidden"
        >
          <div className="relative z-10">
            <span className="text-slate-500 text-[10px] uppercase tracking-widest mb-4">
              安全概览
            </span>
            <div className="flex items-end gap-6 mt-2">
              <div>
                <div className="text-3xl font-bold text-rose-400">02</div>
                <div className="text-[10px] text-slate-500 uppercase mt-1">
                  高风险
                </div>
              </div>
              <div className="h-10 w-[1px] bg-white/10" />
              <div>
                <div className="text-3xl font-bold text-purple-400">14</div>
                <div className="text-[10px] text-slate-500 uppercase mt-1">
                  中风险
                </div>
              </div>
            </div>
          </div>
          <ShieldAlert
            className="absolute right-0 bottom-0 opacity-10"
            style={{ fontSize: 120 }}
          />
        </GlassCard>
      </div>

      <div className="space-y-4">
        {HISTORY_DATA.map((item) => (
          <GlassCard
            key={item.id}
            className={cn("group border-l-2", item.border)}
          >
            <div className="flex flex-col md:flex-row items-center p-6 gap-6">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3 mb-1">
                  <Code2
                    className={cn(
                      "text-xl",
                      item.type === "premium" ? "text-rose-400" : "text-blue-400"
                    )}
                    size={20}
                  />
                  <h3 className="text-lg font-bold tracking-tight truncate">
                    {item.repo}
                  </h3>
                  {item.branch && (
                    <Badge
                      variant={item.type === "premium" ? "tertiary" : "primary"}
                    >
                      {item.branch === "main" ? "主分支" : "专业版分析"}
                    </Badge>
                  )}
                  {item.version && (
                    <Badge variant="outline">{item.version}</Badge>
                  )}
                </div>
                <div className="flex items-center gap-4 text-xs text-slate-500">
                  <span className="flex items-center gap-1">
                    <History size={14} /> {item.date}
                  </span>
                  <span className="flex items-center gap-1">
                    <RefreshCw size={14} /> {item.time}
                  </span>
                </div>
              </div>

              <div className="flex flex-wrap md:flex-nowrap gap-8 items-center">
                <div className="text-center">
                  <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">
                    架构健康度
                  </div>
                  <div
                    className={cn(
                      "text-xl font-bold",
                      item.health.includes("优")
                        ? "text-emerald-400"
                        : item.health.includes("危")
                        ? "text-rose-400"
                        : "text-slate-200"
                    )}
                  >
                    {item.health}
                  </div>
                </div>
                <div className="text-center">
                  <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">
                    代码质量
                  </div>
                  <div className="text-xl font-bold">{item.quality}</div>
                </div>
                <div className="text-center min-w-[100px]">
                  <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">
                    安全风险
                  </div>
                  <div className="flex items-center justify-center gap-1">
                    <span className={cn("w-2 h-2 rounded-full", item.riskBg)} />
                    <span className={cn("text-sm font-bold", item.riskColor)}>
                      {item.risk}
                    </span>
                  </div>
                </div>
              </div>

              <div className="flex gap-2">
                <button className="px-4 py-2 bg-[#31353c] hover:bg-blue-500/20 hover:text-blue-400 transition-all text-xs font-bold uppercase tracking-widest rounded-sm border border-white/5">
                  查看详情
                </button>
                <button className="p-2 bg-[#31353c] hover:bg-blue-500 transition-all text-[#dfe2eb] hover:text-blue-950 rounded-sm border border-white/5">
                  <RefreshCw size={14} />
                </button>
              </div>
            </div>
          </GlassCard>
        ))}
      </div>

      <div className="mt-12 flex items-center justify-between border-t border-white/5 pt-8">
        <span className="text-xs text-slate-500 uppercase tracking-widest">
          显示 128 条结果中的 1-10 条
        </span>
        <div className="flex gap-1">
          <button className="w-8 h-8 flex items-center justify-center rounded-sm bg-[#31353c] text-slate-500 hover:text-blue-400 transition-all">
            <ChevronRight className="rotate-180" size={16} />
          </button>
          <button className="w-8 h-8 flex items-center justify-center rounded-sm bg-blue-500 text-blue-950 font-bold text-xs">
            1
          </button>
          <button className="w-8 h-8 flex items-center justify-center rounded-sm bg-[#31353c] text-slate-300 hover:bg-[#414754] transition-all font-bold text-xs">
            2
          </button>
          <button className="w-8 h-8 flex items-center justify-center rounded-sm bg-[#31353c] text-slate-300 hover:bg-[#414754] transition-all font-bold text-xs">
            3
          </button>
          <button className="w-8 h-8 flex items-center justify-center rounded-sm bg-[#31353c] text-slate-500 hover:text-blue-400 transition-all">
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
    </motion.div>
  );
}

// --- View: Account ---
function AccountView() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="space-y-12"
    >
      <div>
        <h1 className="text-4xl font-black tracking-tight mb-2">
          账户与订阅
        </h1>
        <p className="text-slate-400">
          管理您的个人资料、订阅计划和系统配置
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* User Profile */}
        <GlassCard className="lg:col-span-4 p-8 flex flex-col items-center text-center">
          <div className="relative mb-6">
            <div className="w-24 h-24 rounded-full p-1 bg-gradient-to-tr from-blue-400 to-purple-400">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="https://lh3.googleusercontent.com/aida-public/AB6AXuCA8VBxQEer3YNEz3ruxzs8t0WvwyhUU_sE2cZorPOm8nQRjxbC9uSgGBFyqoJrnoA0d_Py5Dp6c-iXkfaCC7ao_tmk10bX1YRrVaRYeM5KvtQ0szzwYP_imSoy0-8n4xyB6Sa5eTvIVmzTM3jHAhpZAsVrZBl737uQYrRybfUbAjH7VG5TsBElF_1NmUBkUlY5KZ5qGeOQkkCeuFM7Qso2R86fXssEq5ChI-vdmVbS4W78lL0deh3M6EBG1-tQDrsw3iRa5_tsEZ-5"
                alt="Profile"
                className="w-full h-full rounded-full bg-[#10141a] border-4 border-[#10141a] object-cover"
              />
            </div>
            <div className="absolute bottom-0 right-0 w-6 h-6 bg-emerald-400 rounded-full border-4 border-[#10141a] flex items-center justify-center">
              <Check
                size={12}
                className="text-[#002112]"
                strokeWidth={3}
              />
            </div>
          </div>
          <h2 className="text-2xl font-bold mb-1">李伟勋 (WeiXun Li)</h2>
          <div className="flex items-center gap-2 text-blue-400 text-sm font-mono mb-4">
            <Github size={14} />
            github.com/weixun-dev
          </div>
          <div className="w-full pt-6 border-t border-white/5 text-left space-y-4">
            <div className="flex justify-between text-sm">
              <span className="text-slate-500">加入日期</span>
              <span className="font-medium">2023年10月12日</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-500">账户角色</span>
              <span className="font-medium">技术专家 (Architect)</span>
            </div>
          </div>
          <button className="mt-8 w-full py-2.5 border border-white/10 text-sm hover:bg-white/5 transition-colors rounded-sm font-medium">
            编辑个人资料
          </button>
        </GlassCard>

        {/* Subscription Details */}
        <div className="lg:col-span-8 space-y-6">
          <GlassCard className="p-8 relative overflow-hidden group" glow>
            <div className="absolute top-0 right-0 p-6 opacity-10">
              <Zap size={96} />
            </div>
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-8 relative z-10">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <Badge variant="tertiary">Premium Pro</Badge>
                  <span className="text-emerald-400 text-xs">年度订阅</span>
                </div>
                <h3 className="text-3xl font-bold">专业版订阅</h3>
              </div>
              <div className="text-right">
                <p className="text-slate-500 text-sm mb-1">距离下次结算</p>
                <p className="text-xl font-bold font-mono">
                  14 天{" "}
                  <span className="text-slate-600 font-normal text-sm">
                    / 2024.11.20
                  </span>
                </p>
              </div>
            </div>

            <div className="space-y-6 relative z-10">
              <div>
                <div className="flex justify-between text-sm mb-2 font-mono">
                  <span>AI 扫描额度 (本月)</span>
                  <span>78 / 200</span>
                </div>
                <div className="h-2 w-full bg-[#31353c] rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-blue-400 to-purple-400"
                    style={{ width: "39%" }}
                  />
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="bg-[#0a0e14] p-4 rounded-sm border border-white/5">
                  <p className="text-xs text-slate-500 mb-1">存储空间</p>
                  <p className="text-lg font-bold font-mono">
                    4.2 GB{" "}
                    <span className="text-xs font-normal text-slate-600">
                      / 10GB
                    </span>
                  </p>
                </div>
                <div className="bg-[#0a0e14] p-4 rounded-sm border border-white/5">
                  <p className="text-xs text-slate-500 mb-1">导出报告</p>
                  <p className="text-lg font-bold font-mono">
                    12{" "}
                    <span className="text-xs font-normal text-slate-600">
                      / 不限
                    </span>
                  </p>
                </div>
                <div className="bg-[#0a0e14] p-4 rounded-sm border border-white/5">
                  <p className="text-xs text-slate-500 mb-1">API 调用</p>
                  <p className="text-lg font-bold font-mono">
                    1,402{" "}
                    <span className="text-xs font-normal text-slate-600">
                      / 5k
                    </span>
                  </p>
                </div>
              </div>
            </div>
          </GlassCard>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <GlassCard className="p-6 flex items-start gap-4 hover:bg-white/5 transition-colors cursor-pointer group">
              <div className="p-3 rounded-sm bg-blue-500/10 text-blue-400">
                <CreditCard size={24} />
              </div>
              <div className="flex-1">
                <h4 className="font-bold mb-1">管理支付方式</h4>
                <p className="text-xs text-slate-500">
                  修改您的信用卡或 PayPal 信息
                </p>
              </div>
              <ChevronRight
                className="text-slate-600 group-hover:text-blue-400 transition-colors"
                size={20}
              />
            </GlassCard>
            <GlassCard className="p-6 flex items-start gap-4 hover:bg-white/5 transition-colors cursor-pointer group">
              <div className="p-3 rounded-sm bg-emerald-500/10 text-emerald-400">
                <FileText size={24} />
              </div>
              <div className="flex-1">
                <h4 className="font-bold mb-1">账单历史</h4>
                <p className="text-xs text-slate-500">查看并下载过往发票</p>
              </div>
              <ChevronRight
                className="text-slate-600 group-hover:text-emerald-400 transition-colors"
                size={20}
              />
            </GlassCard>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <GlassCard className="p-8 flex flex-col border-l-2 border-blue-400">
          <div className="flex items-center gap-2 mb-6 text-blue-400">
            <Settings size={18} />
            <h3 className="font-bold uppercase tracking-wider text-sm">
              基本设置
            </h3>
          </div>
          <div className="space-y-6 flex-1">
            <div>
              <label className="block text-[10px] text-slate-500 uppercase tracking-widest mb-1">
                电子邮箱
              </label>
              <div className="flex items-center justify-between gap-4">
                <p className="text-sm font-medium">wei***.li@intel.com</p>
                <button className="text-[10px] text-blue-400 hover:underline uppercase font-bold">
                  更改
                </button>
              </div>
            </div>
            <div>
              <label className="block text-[10px] text-slate-500 uppercase tracking-widest mb-1">
                通知偏好
              </label>
              <div className="flex items-center justify-between py-2">
                <span className="text-sm">漏洞扫描提醒</span>
                <div className="w-8 h-4 bg-blue-500 rounded-full relative cursor-pointer">
                  <div className="absolute right-0.5 top-0.5 w-3 h-3 bg-blue-950 rounded-full" />
                </div>
              </div>
            </div>
          </div>
          <button className="mt-8 text-xs text-rose-400 font-medium flex items-center gap-2 hover:opacity-80 transition-opacity">
            <Trash2 size={14} />
            注销账户
          </button>
        </GlassCard>

        <GlassCard className="p-8 flex flex-col border-l-2 border-emerald-400">
          <div className="flex items-center gap-2 mb-6 text-emerald-400">
            <Key size={18} />
            <h3 className="font-bold uppercase tracking-wider text-sm">
              API 令牌
            </h3>
          </div>
          <div className="space-y-4 flex-1">
            <div className="p-3 bg-[#0a0e14] border border-white/5 rounded-sm">
              <div className="flex justify-between items-center mb-2">
                <span className="text-[10px] font-mono text-slate-500">
                  PROD_KEY_01
                </span>
                <span className="text-[10px] text-emerald-400 font-bold">
                  已激活
                </span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <code className="text-xs text-slate-300 font-mono">
                  gi_sk_****************4k2l
                </code>
                <Copy
                  size={14}
                  className="text-slate-500 cursor-pointer hover:text-white transition-colors"
                />
              </div>
            </div>
            <p className="text-[10px] text-slate-500 leading-relaxed">
              API 令牌允许第三方服务访问您的分析数据。请妥善保管，切勿泄露。
            </p>
          </div>
          <button className="mt-8 py-2 border border-emerald-400/20 text-emerald-400 text-xs hover:bg-emerald-500/10 transition-colors uppercase font-bold tracking-widest rounded-sm">
            创建新令牌
          </button>
        </GlassCard>

        <GlassCard className="p-8 flex flex-col border-l-2 border-purple-400">
          <div className="flex items-center gap-2 mb-6 text-purple-400">
            <ArrowUpRight size={18} />
            <h3 className="font-bold uppercase tracking-wider text-sm">
              方案管理
            </h3>
          </div>
          <div className="flex-1 space-y-4">
            <div className="flex items-center gap-4 group cursor-pointer p-2 -mx-2 hover:bg-white/5 transition-colors rounded-sm">
              <div className="w-10 h-10 bg-[#31353c] rounded-sm flex items-center justify-center">
                <Zap
                  size={20}
                  className="text-slate-500 group-hover:text-blue-400 transition-colors"
                />
              </div>
              <div>
                <p className="text-sm font-bold">升级到企业版</p>
                <p className="text-[10px] text-slate-500">
                  无限团队席位与私有化部署
                </p>
              </div>
            </div>
            <div className="flex items-center gap-4 group cursor-pointer p-2 -mx-2 hover:bg-white/5 transition-colors rounded-sm">
              <div className="w-10 h-10 bg-[#31353c] rounded-sm flex items-center justify-center">
                <RefreshCw
                  size={20}
                  className="text-slate-500 group-hover:text-purple-400 transition-colors"
                />
              </div>
              <div>
                <p className="text-sm font-bold">降级到基础版</p>
                <p className="text-[10px] text-slate-500">
                  仅保留基础扫描与历史记录
                </p>
              </div>
            </div>
          </div>
          <div className="mt-8 pt-4 border-t border-white/5">
            <p className="text-[10px] text-slate-600 italic">
              订阅受《GitIntel 服务条款》约束
            </p>
          </div>
        </GlassCard>
      </div>
    </motion.div>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>("workspace");

  return (
    <div className="min-h-screen bg-[#10141a] text-[#dfe2eb] font-sans selection:bg-blue-500/30">
      {/* Background Accents */}
      <div className="fixed top-0 right-0 w-[500px] h-[500px] bg-blue-500/5 rounded-full blur-[120px] -z-10 pointer-events-none" />
      <div className="fixed bottom-0 left-0 w-[300px] h-[300px] bg-purple-500/5 rounded-full blur-[100px] -z-10 pointer-events-none" />

      {/* Navigation Header */}
      <header className="fixed top-0 w-full z-50 bg-[#10141a]/80 backdrop-blur-xl border-b border-white/5 flex justify-between items-center px-6 h-16">
        <div className="flex items-center gap-8">
          <div className="flex items-center gap-2">
            <span className="text-xl font-bold tracking-tighter text-blue-400 font-headline">
              GitIntel
            </span>
          </div>
          <nav className="hidden md:flex gap-1">
            {[
              { id: "workspace", label: "工作台", icon: LayoutDashboard },
              { id: "history", label: "历史记录", icon: History },
              { id: "account", label: "账户中心", icon: UserCircle },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as Tab)}
                className={cn(
                  "px-4 py-2 text-sm tracking-tight transition-all duration-200 rounded flex items-center gap-2",
                  activeTab === tab.id
                    ? "text-blue-400 font-bold bg-blue-500/10"
                    : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
                )}
              >
                <tab.icon size={16} />
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-4">
          <button className="hidden md:block px-4 py-1.5 bg-blue-500/10 text-blue-400 border border-blue-500/20 rounded-sm hover:bg-blue-500/20 transition-all font-medium text-xs uppercase tracking-widest">
            升级专业版
          </button>
          <div className="flex items-center gap-2">
            <button className="p-2 text-slate-400 hover:bg-white/5 rounded-full transition-colors">
              <Bell size={20} />
            </button>
            <button className="p-2 text-slate-400 hover:bg-white/5 rounded-full transition-colors">
              <Settings size={20} />
            </button>
            <div className="w-8 h-8 rounded bg-blue-600 flex items-center justify-center overflow-hidden border border-white/10 ml-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="https://lh3.googleusercontent.com/aida-public/AB6AXuDkPsi_KTxSXNH9ttW5l6V7hIV-OQ3BDUygCu3ymWaH3BM-g9HKp1L-QsN9HdOcQLssuyWdLPDLGZXTeBDrd12OmGNn31RfbEk222AfDci-T9UmIAsj6AKzQ5Du0gU3T7Xjx34J2426XlzRq9tLWgr_S7yyYRSb7jpw9BNa2O6R52iBtUQmU96WfwgIAhrAHTF3YPRQVFF3SZqiXCYw9wEtJtUye7Gf1sVl0K40UOWk3RD7FONeqNz7EAtC-lcuYiE00jPwBDLHwmVP"
                alt="Avatar"
                className="w-full h-full object-cover"
              />
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="pt-24 pb-12 px-6 lg:px-12 max-w-[1400px] mx-auto min-h-screen">
        <AnimatePresence mode="wait">
          {activeTab === "workspace" && <WorkspaceView key="workspace" />}
          {activeTab === "history" && <HistoryView key="history" />}
          {activeTab === "account" && <AccountView key="account" />}
        </AnimatePresence>
      </main>
    </div>
  );
}
