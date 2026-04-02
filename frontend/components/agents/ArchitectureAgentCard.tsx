import React, { useRef, useEffect } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Code2, Layers, GitBranch, AlertTriangle } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { useAppStore } from "@/store/useAppStore";

interface ArchitectureData {
  complexity?: string;
  components?: number;
  techStack?: string[];
  maintainability?: string;
  architectureStyle?: string;
  keyPatterns?: string[];
  hotSpots?: string[];
  summary?: string;
  llmPowered?: boolean;
}

const COMPLEXITY_COLORS: Record<string, string> = {
  Low: "text-emerald-400",
  Medium: "text-yellow-400",
  High: "text-rose-400",
};

export const ArchitectureAgentCard = () => {
  const eventsVersion = useAppStore((s) => s.eventsVersion);
  const finishedAgents = useAppStore((s) => s.finishedAgents);
  const activeAgent = useAppStore((s) => s.activeAgent);
  const isAnalyzing = useAppStore((s) => s.isAnalyzing);

  // 订阅单个事件（reactively read from agentEvents via eventsVersion trigger）
  const fetchTreeEvent = useAppStore((s) => s.agentEvents["fetch_tree_classify"]);
  const loadP0Event = useAppStore((s) => s.agentEvents["load_p0"]);
  const loadP1Event = useAppStore((s) => s.agentEvents["load_p1"]);
  const loadP2Event = useAppStore((s) => s.agentEvents["load_p2"]);
  const codeParserP0Event = useAppStore((s) => s.agentEvents["code_parser_p0"]);
  const codeParserP1Event = useAppStore((s) => s.agentEvents["code_parser_p1"]);
  const codeParserFinalEvent = useAppStore((s) => s.agentEvents["code_parser_final"]);
  const archEvent = useAppStore((s) => s.agentEvents["architecture"]);
  const techStackEvent = useAppStore((s) => s.agentEvents["tech_stack"]);

  const archDone = finishedAgents.includes("architecture");
  const archData = archEvent?.data as ArchitectureData | undefined;
  const techData = techStackEvent?.data as { languages?: string[]; frameworks?: string[] } | undefined;

  const ARCH_AGENTS = new Set([
    "fetch_tree_classify", "load_p0", "load_p1", "load_p2",
    "code_parser_p0", "code_parser_p1", "code_parser_final",
    "architecture", "tech_stack",
  ]);
  const isScanning = isAnalyzing && activeAgent !== null && ARCH_AGENTS.has(activeAgent);

  // ── 累加进度日志 ──────────────────────────────────────────────
  const linesRef = useRef<{ text: string; color: string }[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isAnalyzing) {
      linesRef.current = [];
      return;
    }

    const subAgents = [
      { event: fetchTreeEvent, key: "fetch_tree_classify", done: finishedAgents.includes("fetch_tree_classify"), doneText: "✓ 文件树获取完成" },
      { event: loadP0Event, key: "load_p0", done: finishedAgents.includes("load_p0"), doneText: "✓ 核心文件加载完成" },
      { event: loadP1Event, key: "load_p1", done: finishedAgents.includes("load_p1"), doneText: "✓ 次要文件加载完成" },
      { event: loadP2Event, key: "load_p2", done: finishedAgents.includes("load_p2"), doneText: "✓ 文档文件加载完成" },
      { event: codeParserP0Event, key: "code_parser_p0", done: finishedAgents.includes("code_parser_p0"), doneText: "✓ 核心代码结构解析完成" },
      { event: codeParserP1Event, key: "code_parser_p1", done: finishedAgents.includes("code_parser_p1"), doneText: "✓ 次要代码结构解析完成" },
      { event: codeParserFinalEvent, key: "code_parser_final", done: finishedAgents.includes("code_parser_final"), doneText: "✓ 架构综合分析完成" },
      { event: techStackEvent, key: "tech_stack", done: finishedAgents.includes("tech_stack"), doneText: "✓ 技术栈识别完成" },
      { event: archEvent, key: "architecture", done: finishedAgents.includes("architecture"), doneText: "✓ 架构评估完成" },
    ];

    for (const sub of subAgents) {
      if (!linesRef.current.find((l) => l.text === sub.doneText)) {
        if (sub.event?.message && !sub.done) {
          linesRef.current = linesRef.current.filter((l) => l.text !== sub.doneText);
          linesRef.current.push({ text: sub.event.message, color: "text-blue-400" });
        } else if (sub.done) {
          linesRef.current = linesRef.current.filter(
            (l) => l.text !== sub.event?.message && l.text !== sub.doneText
          );
          linesRef.current.push({ text: sub.doneText, color: "text-emerald-400" });
        }
      }
    }

    linesRef.current = linesRef.current.slice(-20);

    // 新行追加后自动滚到底部
    requestAnimationFrame(() => {
      if (scrollRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
    });
  }, [isAnalyzing, eventsVersion]);

  const statusLabel = isScanning
    ? activeAgent === "architecture" ? "ANALYZING" : "SCANNING"
    : archDone
    ? "DONE"
    : "IDLE";

  return (
    <GlassCard className="p-5 relative border-l-2" glow={isScanning}>
      {isScanning && <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-blue-400/80 to-transparent animate-pulse" />}

      {/* ── Header ── */}
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
        <span
          className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
            isScanning
              ? "bg-blue-500/30 text-blue-400 animate-pulse"
              : "bg-emerald-500/20 text-emerald-400"
          }`}
        >
          {statusLabel}
        </span>
      </div>

      {/* ── 真实分析结果 ── */}
      <AnimatePresence mode="wait">
        {archData ? (
          <motion.div
            key="result"
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.96 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
            className="space-y-3"
          >
          {/* 核心指标 */}
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-[#1c2330] rounded p-2 border border-white/5">
              <p className="text-[9px] text-slate-600 uppercase mb-1">复杂度</p>
              <p className={`text-sm font-bold ${COMPLEXITY_COLORS[archData.complexity ?? ''] ?? "text-slate-300"}`}>
                {archData.complexity ?? "—"}
              </p>
            </div>
            <div className="bg-[#1c2330] rounded p-2 border border-white/5">
              <p className="text-[9px] text-slate-600 uppercase mb-1">组件数</p>
              <p className="text-sm font-bold text-blue-400">
                {archData.components ?? "—"}
              </p>
            </div>
            <div className="bg-[#1c2330] rounded p-2 border border-white/5">
              <p className="text-[9px] text-slate-600 uppercase mb-1">可维护性</p>
              <p className="text-sm font-bold text-slate-200">
                {archData.maintainability ?? "—"}
              </p>
            </div>
            <div className="bg-[#1c2330] rounded p-2 border border-white/5">
              <p className="text-[9px] text-slate-600 uppercase mb-1 flex items-center gap-1">
                {archData.llmPowered && <span className="text-[7px] px-1 py-0.5 bg-purple-500/20 text-purple-400 rounded">LLM</span>}
                架构风格
              </p>
              <p className="text-[11px] font-bold text-slate-200 leading-tight">
                {archData.architectureStyle ?? "—"}
              </p>
            </div>
          </div>

          {/* 技术栈标签 */}
          {(archData.techStack ?? techData?.languages ?? techData?.frameworks) && (
            <div>
              <p className="text-[9px] text-slate-600 uppercase mb-1">技术栈</p>
              <div className="flex flex-wrap gap-1">
                {[
                  ...(archData.techStack ?? []),
                  ...(techData?.languages ?? []),
                  ...(techData?.frameworks ?? []),
                ]
                  .filter((v, i, a) => a.indexOf(v) === i)
                  .slice(0, 8)
                  .map((tag) => (
                    <span
                      key={tag}
                      className="px-1.5 py-0.5 bg-blue-500/10 border border-blue-500/20 rounded text-[10px] text-blue-400"
                    >
                      {tag}
                    </span>
                  ))}
              </div>
            </div>
          )}

          {/* 设计模式 */}
          {archData.keyPatterns && archData.keyPatterns.length > 0 && (
            <div>
              <p className="text-[9px] text-slate-600 uppercase mb-1 flex items-center gap-1">
                <GitBranch size={10} /> 设计模式
              </p>
              <div className="flex flex-wrap gap-1">
                {archData.keyPatterns.slice(0, 4).map((p) => (
                  <span
                    key={p}
                    className="px-1.5 py-0.5 bg-emerald-500/10 border border-emerald-500/20 rounded text-[10px] text-emerald-400"
                  >
                    {p}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* 热点/风险 */}
          {archData.hotSpots && archData.hotSpots.length > 0 && (
            <div>
              <p className="text-[9px] text-slate-600 uppercase mb-1 flex items-center gap-1">
                <AlertTriangle size={10} /> 风险热点
              </p>
              <div className="space-y-0.5">
                {archData.hotSpots.slice(0, 3).map((h, i) => (
                  <p key={i} className="text-[10px] text-rose-400/80 flex items-center gap-1">
                    <span className="text-rose-500">•</span>{h}
                  </p>
                ))}
              </div>
            </div>
          )}

          {/* 摘要 */}
          {archData.summary && (
            <p className="text-[10px] text-slate-400 italic leading-relaxed border-t border-white/5 pt-2">
              {archData.summary}
            </p>
          )}
        </motion.div>
      ) : (
        /* ── 加载中 / 无数据状态 ── */
        <motion.div
          key="idle"
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.96 }}
          transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          ref={scrollRef}
          className="bg-[#0a0e14] rounded p-4 font-mono text-[11px] h-48 overflow-y-auto border border-white/5 space-y-1 scrollbar-hide"
          style={{ paddingBottom: "2.5rem" }}
        >
          {linesRef.current.map((line, i) => (
            <p key={i} className={line.color}>
              {line.text}
            </p>
          ))}
          {isScanning && (
            <p className="text-blue-400 animate-pulse">
              ▌ {activeAgent}...
            </p>
          )}
          {!isAnalyzing && linesRef.current.length === 0 && (
            <p className="text-slate-600">等待分析开始...</p>
          )}
        </motion.div>
      )}
      </AnimatePresence>
    </GlassCard>
  );
};
