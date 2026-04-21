"use client";

import React from "react";
import { Check, X, Star } from "lucide-react";

export const LandingPricing = () => (
  <section id="pricing" className="py-32 relative overflow-hidden">
    <div className="max-w-7xl mx-auto px-6 relative z-10">
      <div className="text-center mb-20">
        <h2 className="text-4xl font-bold text-white mb-4">按需选择，无限扩展</h2>
        <p className="text-slate-500">无论是个人开源作者还是大型企业，都有合适的方案</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 max-w-4xl mx-auto">
        {/* Open Source */}
        <div className="glass-card p-10 rounded-2xl border-white/5 flex flex-col">
          <div className="mb-8">
            <h3 className="text-xl font-bold text-white mb-2">开源基础版</h3>
            <p className="text-sm text-slate-500">适用于开源维护者</p>
            <div className="mt-6 flex items-baseline gap-1">
              <span className="text-5xl font-bold text-white tracking-tighter">¥0</span>
              <span className="text-sm text-slate-500">/ 永久</span>
            </div>
          </div>
          <ul className="flex-1 space-y-5 mb-10 text-sm">
            {[
              "公共仓库无限次分析",
              "基础架构拓扑图",
              { text: "AI 自动 PR 提交", disabled: true },
              { text: "企业级安全审计报告", disabled: true }
            ].map((feat, i) => {
              const isDisabled = typeof feat === "object" && feat.disabled;
              const label = typeof feat === "string" ? feat : feat.text;
              return (
                <li key={i} className={`flex items-center gap-3 ${isDisabled ? "text-slate-600" : "text-slate-300"}`}>
                  {isDisabled ? (
                    <X className="w-4 h-4 shrink-0" />
                  ) : (
                    <Check className="w-4 h-4 text-blue-400 shrink-0" />
                  )}
                  <span className={isDisabled ? "line-through" : ""}>{label}</span>
                </li>
              );
            })}
          </ul>
          <button className="w-full py-4 rounded-xl border border-white/10 text-white font-bold text-sm tracking-widest uppercase hover:bg-white/5 transition-all">
            立即开始
          </button>
        </div>

        {/* Pro */}
        <div className="glass-card p-10 rounded-2xl border-blue-500 bg-blue-500/5 flex flex-col relative overflow-hidden">
          <div className="absolute top-0 right-0 bg-blue-400 text-black px-4 py-1 text-[8px] font-bold uppercase tracking-widest">
            Recommended
          </div>
          <div className="mb-8">
            <h3 className="text-xl font-bold text-blue-400 mb-2">专业开发者</h3>
            <p className="text-sm text-slate-400">深度集成 AI 代理工作流</p>
            <div className="mt-6 flex items-baseline gap-1">
              <span className="text-5xl font-bold text-white tracking-tighter">¥99</span>
              <span className="text-sm text-slate-500">/ 月</span>
            </div>
          </div>
          <ul className="flex-1 space-y-5 mb-10 text-sm text-slate-300">
            {[
              "私有仓库优先访问权",
              "增强型 AI 自动 PR (不限次数)",
              "全栈架构重构建议",
              "实时漏洞扫描与一键修复",
              { text: "专享会员专属紫金 UI 主题", star: true }
            ].map((feat, i) => {
              const hasStar = typeof feat === "object" && feat.star;
              const label = typeof feat === "string" ? feat : feat.text;
              return (
                <li key={i} className="flex items-center gap-3">
                  {hasStar ? (
                    <Star className="w-4 h-4 text-indigo-400 fill-indigo-400 shrink-0" />
                  ) : (
                    <Check className="w-4 h-4 text-blue-400 shrink-0" />
                  )}
                  {label}
                </li>
              );
            })}
          </ul>
          <button className="w-full py-4 rounded-xl bg-blue-400 text-black font-bold text-sm tracking-widest uppercase hover:opacity-90 shadow-2xl shadow-blue-400/20 transition-all">
            升级至 PRO 账户
          </button>
        </div>
      </div>
    </div>
  </section>
);
