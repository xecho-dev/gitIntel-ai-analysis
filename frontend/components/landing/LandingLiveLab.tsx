"use client";

import React, { useState, useEffect } from "react";
import { motion } from "motion/react";
import { Terminal, Activity, Check } from "lucide-react";

const INITIAL_LOGS = [
  "[INFO] Starting analyzer...",
  "> indexing ./src/core",
  "> building AST tree"
];

const NEW_MESSAGES = [
  "[SSE] Event: module_map",
  "> data: {\"nodes\": 154, \"links\": 892}",
  "[AI] Insight: circular dependency detected",
  "> suggesting fix...",
  "Analyzing patterns...",
  "Generating topology..."
];

export const LandingLiveLab = () => {
  const [logs, setLogs] = useState(INITIAL_LOGS);

  useEffect(() => {
    const timer = setInterval(() => {
      setLogs(prev =>
        [...prev, NEW_MESSAGES[Math.floor(Math.random() * NEW_MESSAGES.length)]].slice(-6)
      );
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  return (
    <section id="labs" className="py-24 bg-[#10141a]/60">
      <div className="max-w-7xl mx-auto px-6">
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-12 items-center">
          <div className="lg:col-span-2">
            <h2 className="text-4xl font-bold text-white mb-6">实时分析实验室</h2>
            <p className="text-lg text-slate-400 mb-8 leading-relaxed">
              见证 GitIntel 如何在毫秒级内解构复杂的代码仓库。通过 SSE (Server-Sent Events) 流式处理，系统会向您展示每一步思考过程。
            </p>
            <ul className="space-y-4">
              {[
                "语义聚类分析中...",
                "依赖深度扫描 (42 层)",
                "正在计算重构方案..."
              ].map((text, i) => (
                <li key={i} className="flex items-center gap-3 group">
                  <div className={`w-5 h-5 rounded-full flex items-center justify-center border ${i === 2 ? "border-blue-400" : "border-emerald-400"} transition-all`}>
                    {i === 2 ? (
                      <Activity className="w-3 h-3 text-blue-400 animate-pulse" />
                    ) : (
                      <Check className="w-3 h-3 text-emerald-400" />
                    )}
                  </div>
                  <span className={`text-xs font-bold tracking-widest uppercase ${i === 2 ? "text-blue-400" : "text-slate-400"}`}>
                    {text}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="lg:col-span-3 glass-card rounded-2xl overflow-hidden aspect-video flex flex-col border-blue-500/20">
            <div className="bg-white/5 px-4 py-3 border-b border-white/5 flex items-center justify-between">
              <div className="flex gap-2">
                <div className="w-2.5 h-2.5 rounded-full bg-red-400/50" />
                <div className="w-2.5 h-2.5 rounded-full bg-yellow-400/50" />
                <div className="w-2.5 h-2.5 rounded-full bg-green-400/50" />
              </div>
              <span className="text-[10px] font-mono text-slate-500 tracking-widest uppercase">
                AGENT_SESSION_ID: 0x8F2C
              </span>
            </div>
            <div className="flex-1 grid grid-cols-2">
              <div className="p-6 font-mono text-[10px] text-slate-400 border-r border-white/5 overflow-hidden">
                <div className="space-y-1.5">
                  {logs.map((log, i) => (
                    <motion.p
                      key={`${i}-${log}`}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      className={log.startsWith("[") ? "text-emerald-400" : ""}
                    >
                      {log}
                    </motion.p>
                  ))}
                  <motion.span
                    animate={{ opacity: [1, 0] }}
                    transition={{ repeat: Infinity, duration: 0.8 }}
                    className="inline-block"
                  >
                    _
                  </motion.span>
                </div>
              </div>
              <div className="relative flex items-center justify-center overflow-hidden">
                <div className="absolute inset-0 bg-blue-500/5 opacity-40 mesh-grid" />
                <div className="z-10 flex flex-col items-center">
                  <motion.div
                    animate={{ rotate: 360 }}
                    transition={{ repeat: Infinity, duration: 10, ease: "linear" }}
                    className="w-16 h-16 border-2 border-blue-400/20 rounded-full border-t-blue-400 flex items-center justify-center"
                  >
                    <Terminal className="w-6 h-6 text-blue-400" />
                  </motion.div>
                  <p className="mt-4 text-[10px] tracking-[0.4em] font-bold text-blue-400 uppercase">
                    生成拓扑模型中
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
