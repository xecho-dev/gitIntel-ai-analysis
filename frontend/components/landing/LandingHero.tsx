"use client";

import React from "react";
import Link from "next/link";
import { motion } from "motion/react";
import { Rocket, Github } from "lucide-react";

export const LandingHero = () => (
  <section className="relative pt-32 pb-20 overflow-hidden">
    <div className="mesh-grid absolute inset-0 -z-10 opacity-30" />
    <div className="glow-bg absolute top-0 left-1/2 -translate-x-1/2 w-full max-w-4xl h-[500px] pointer-events-none" />

    <div className="max-w-7xl mx-auto px-6 text-center">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-[11px] font-bold tracking-[0.2em] text-blue-400 mb-8"
      >
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-400" />
        </span>
        V2.0 BETA 现在开启
      </motion.div>

      <motion.h1
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="text-5xl md:text-8xl font-bold tracking-tight text-white mb-8 leading-[0.9]"
      >
        深度代码洞察<br />
        <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 via-indigo-400 to-emerald-400">重塑开发体验</span>
      </motion.h1>

      <motion.p
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="max-w-2xl mx-auto text-lg md:text-xl text-slate-400 mb-12 leading-relaxed"
      >
        GitHub 仓库智能分析 Agent，从架构拓扑分析到自动化重构，AI 驱动的一键式 Pull Request 提交，让理解代码不再是负担。
      </motion.p>

      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.3 }}
        className="flex flex-col sm:flex-row items-center justify-center gap-4"
      >
        <Link href="/workspace" className="group relative px-8 py-4 rounded-xl bg-blue-400 text-black font-bold flex items-center gap-2 hover:scale-105 transition-all overflow-hidden">
          <div className="absolute inset-0 bg-white/20 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-500" />
          立即开启分析
          <Rocket className="w-5 h-5" />
        </Link>
        <button onClick={() => window.open("https://github.com/xecho-dev/gitIntel-ai-analysis.git", "_blank")} className="px-8 py-4 rounded-xl bg-white/5 border border-white/10 text-white font-bold flex items-center gap-2 hover:bg-white/10 transition-all">
          GITHUB
          <Github className="w-5 h-5 fill-white" />
        </button>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 40 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.5, duration: 1 }}
        className="mt-20 relative"
      >
        <div className="glass-card p-2 rounded-2xl">
          <img
            src="https://picsum.photos/seed/code-viz/1200/600"
            alt="Dashboard Preview"
            className="w-full h-auto rounded-xl opacity-80"
            referrerPolicy="no-referrer"
          />
        </div>
      </motion.div>
    </div>
  </section>
);
