"use client";

import React from "react";
import { ChevronDown } from "lucide-react";
import { LiveProgress } from "@/components/layout/LiveProgress";
import { useAppStore } from "@/store/useAppStore";

interface ProgressPanelProps {
  defaultOpen?: boolean;
  height?: string;
}

export const ProgressPanel = ({ height = "h-56" }: ProgressPanelProps) => {
  const isAnalyzing = useAppStore((s) => s.isAnalyzing);

  return (
    <div className="border border-white/5 rounded-xl overflow-hidden bg-[#0d1117]/80 backdrop-blur-sm">
      <button
        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-2">
          <div
            className={`w-1.5 h-1.5 rounded-full ${
              isAnalyzing ? "bg-blue-400 animate-pulse" : "bg-emerald-400"
            }`}
          />
          <span className="text-xs font-bold text-slate-300 uppercase tracking-widest">
            实时进度
          </span>
        </div>
          <ChevronDown size={14} className="text-slate-500" />

      </button>

        <div className={`${height} border-t border-white/5`}>
          <LiveProgress />
        </div>
    </div>
  );
};
