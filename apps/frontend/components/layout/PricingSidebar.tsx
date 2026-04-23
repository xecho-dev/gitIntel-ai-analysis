import React from "react";
import {
  Zap,
  CheckCircle2,
  ChevronRight,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";

export const PricingSidebar = () => {
  return (
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
  );
};
