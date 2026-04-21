"use client";

import React from "react";
import { useSession } from "next-auth/react";
import { AnalyzeInput } from "@/components/layout/AnalyzeInput";
import { ArchitectureAgentCard } from "@/components/agents/ArchitectureAgentCard";
import { QualityAgentCard } from "@/components/agents/QualityAgentCard";
import { DependencyAgentCard } from "@/components/agents/DependencyAgentCard";
import { OptimizationAgentCard } from "@/components/agents/OptimizationAgentCard";
import { AnalysisPreview } from "@/components/layout/AnalysisPreview";

export default function WorkspacePage() {
  const { data: session } = useSession();
  const userId = session?.user?.id ?? session?.user?.sub ?? "";

  return (
    <div className="space-y-10">
      <section className="text-center">
        <h1 className="text-4xl font-black mb-2 tracking-tight">
          智能分析工作台
        </h1>
        <p className="text-slate-400 font-light">
          输入仓库地址，启动深度架构与风险评估
        </p>
        <AnalyzeInput userId={userId} />
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        <div className="xl:col-span-9 grid grid-cols-1 md:grid-cols-2 gap-6">
          <ArchitectureAgentCard />
          <QualityAgentCard />
          <DependencyAgentCard />
          <OptimizationAgentCard />
        </div>

        <div className="xl:col-span-3">
          <AnalysisPreview />
        </div>
      </div>
    </div>
  );
}
