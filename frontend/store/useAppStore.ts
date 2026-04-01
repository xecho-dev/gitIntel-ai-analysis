import { create } from "zustand";

export interface AgentEventData {
  type: "status" | "progress" | "result" | "error";
  agent: string;
  message?: string;
  percent?: number;
  data?: Record<string, unknown>;
}

interface AppState {
  // 分析状态
  isAnalyzing: boolean;
  setIsAnalyzing: (value: boolean) => void;

  // 当前分析的仓库
  repoUrl: string;
  setRepoUrl: (url: string) => void;

  // SSE 事件累积（按 agent 分组，存最新事件）
  agentEvents: Record<string, AgentEventData>;
  finishedAgents: string[];
  // 追加单个 SSE 事件
  pushAgentEvent: (event: AgentEventData) => void;

  // 最终聚合结果（suggestion 完成后由 analysis_graph 推送）
  finalResult: Record<string, unknown> | null;
  setFinalResult: (result: Record<string, unknown>) => void;

  // 分析结果（兼容旧写法，弃用）
  analysisResult: unknown | null;
  setAnalysisResult: (result: unknown) => void;

  // 错误信息
  error: string | null;
  setError: (error: string | null) => void;

  // 清除所有状态
  reset: () => void;
}

const initialState = {
  isAnalyzing: false,
  repoUrl: "https://github.com/xecho-dev/test.git",
  agentEvents: {},
  finishedAgents: [],
  finalResult: null,
  analysisResult: null,
  error: null,
};

export const useAppStore = create<AppState>((set) => ({
  ...initialState,

  setIsAnalyzing: (value) => set({ isAnalyzing: value }),

  setRepoUrl: (url) => set({ repoUrl: url }),

  pushAgentEvent: (event) =>
    set((state) => {
      const finishedAgents = event.type === "result"
        ? [...new Set([...state.finishedAgents, event.agent])]
        : state.finishedAgents;

      // 如果是 final_result 事件（包含所有数据），存到 finalResult
      const finalResult = event.agent === "final_result" && event.type === "result" && event.data
        ? (event.data as Record<string, unknown>)
        : state.finalResult;

      return {
        agentEvents: { ...state.agentEvents, [event.agent]: event },
        finishedAgents,
        finalResult,
        // 同时兼容旧 analysisResult
        analysisResult: event.type === "result" ? event.data : state.analysisResult,
      };
    }),

  setFinalResult: (result) => set({ finalResult: result }),

  setAnalysisResult: (result) => set({ analysisResult: result }),

  setError: (error) => set({ error, isAnalyzing: false }),

  reset: () => set(initialState),
}));
