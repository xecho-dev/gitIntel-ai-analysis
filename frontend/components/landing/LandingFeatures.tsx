"use client";

import React from "react";
import { Activity, Zap, Shield, Code2, LucideIcon } from "lucide-react";

const FeatureCard = ({ icon: Icon, title, description, color }: {
  icon: LucideIcon;
  title: string;
  description: string;
  color: string;
}) => (
  <div className="glass-card group p-8 rounded-2xl hover:border-blue-500/50 transition-all cursor-default relative overflow-hidden">
    <div className={`absolute top-0 right-0 p-4 opacity-5 group-hover:opacity-20 transition-opacity ${color}`}>
      <Icon className="w-16 h-16" />
    </div>
    <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-6 bg-white/5 border border-white/10 group-hover:border-blue-500/50 transition-all`}>
      <Icon className={`w-6 h-6 ${color}`} />
    </div>
    <h3 className="text-xl font-bold text-white mb-4 tracking-tight">{title}</h3>
    <p className="text-sm leading-relaxed text-slate-400">{description}</p>
  </div>
);

export const LandingFeatures = () => (
  <section id="features" className="py-24 relative">
    <div className="max-w-7xl mx-auto px-6">
      <div className="flex flex-col md:flex-row items-end gap-4 mb-16">
        <div className="h-0.5 w-12 bg-blue-400 mb-3 md:mb-5" />
        <div>
          <h2 className="text-3xl font-bold text-white mb-2 tracking-tight">核心智能能力</h2>
          <p className="text-slate-500">集成最前沿的 LLM 模型，专为代码语义理解而生</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <FeatureCard
          icon={Activity}
          title="架构分析"
          description="基于静态分析与语义建模，实时生成模块依赖拓扑图，洞察代码全局逻辑。"
          color="text-blue-400"
        />
        <FeatureCard
          icon={Zap}
          title="代码质量"
          description="深度代码坏味道识别，提供重构路径建议，并自动生成符合规范的可读性报告。"
          color="text-emerald-400"
        />
        <FeatureCard
          icon={Shield}
          title="依赖风险"
          description="全库扫描三方依赖及 CVE 漏洞，实时预警可能的供应链安全风险与版本冲突。"
          color="text-red-400"
        />
        <FeatureCard
          icon={Code2}
          title="智能 PR"
          description="AI 驱动的一键优化提交。自动编写变更日志并提交 Pull Request，提效 50%。"
          color="text-indigo-400"
        />
      </div>
    </div>
  </section>
);
