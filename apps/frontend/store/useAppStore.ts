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

  // 事件版本号（递增用于强制刷新所有订阅者）
  eventsVersion: number;

  // 当前分析的仓库
  repoUrl: string;
  setRepoUrl: (url: string) => void;

  // SSE 事件累积（按 agent 分组，存最新事件）
  agentEvents: Record<string, AgentEventData>;
  finishedAgents: string[];
  // 追加单个 SSE 事件
  pushAgentEvent: (event: AgentEventData) => void;

  // 实时进度日志（供 LiveProgress 组件展示）
  progressMessages: Array<{ id: string; agent: string; message: string; time: Date; type: string }>;
  addProgressMessage: (agent: string, message: string, type?: string) => void;
  clearProgressMessages: () => void;

  // 最终聚合结果（suggestion 完成后由 analysis_graph 推送）
  finalResult: Record<string, unknown> | null;
  setFinalResult: (result: Record<string, unknown>) => void;

  // 分析结果（兼容旧写法，弃用）
  analysisResult: unknown | null;
  setAnalysisResult: (result: unknown) => void;

  // 错误信息
  error: string | null;
  setError: (error: string | null) => void;

  // 当前活跃的 Agent（用于扫描动画高亮）
  activeAgent: string | null;
  setActiveAgent: (agent: string | null) => void;

  // 清除所有状态
  reset: () => void;

  // 聊天抽屉
  isChatDrawerOpen: boolean;
  toggleChatDrawer: () => void;
  setChatDrawerOpen: (open: boolean) => void;
}

const initialState = {
  isAnalyzing: false,
  eventsVersion: 0,
  activeAgent: null,
  repoUrl: "https://github.com/facebook/react.git",
  agentEvents: {},
  finishedAgents: [],
  finalResult: null,
  analysisResult: null,
  error: null,
  progressMessages: [],
  isChatDrawerOpen: false,
};

export const useAppStore = create<AppState>((set) => ({
  ...initialState,

  setIsAnalyzing: (value) => set({ isAnalyzing: value }),

  setRepoUrl: (url) => set({ repoUrl: url }),

  setActiveAgent: (agent) => set({ activeAgent: agent }),

  pushAgentEvent: (event) =>
    set((state) => {
      const finishedAgents = event.type === "result"
        ? [...new Set([...state.finishedAgents, event.agent])]
        : state.finishedAgents;

      // 如果是 final_result 事件（包含所有数据），存到 finalResult
      const finalResult = event.agent === "final_result" && event.type === "result" && event.data
        ? (event.data as Record<string, unknown>)
        : state.finalResult;

      // 记录进度日志（仅 status / progress / result 类型）
      const newMessages = event.message
        ? [
            ...state.progressMessages,
            {
              id: `${Date.now()}-${Math.random()}`,
              agent: event.agent,
              message: event.message,
              time: new Date(),
              type: event.type,
            },
          ]
        : state.progressMessages;

      return {
        eventsVersion: state.eventsVersion + 1,
        agentEvents: { ...state.agentEvents, [event.agent]: event },
        finishedAgents,
        finalResult,
        analysisResult: event.type === "result" ? event.data : state.analysisResult,
        progressMessages: newMessages.slice(-50),
      };
    }),

  addProgressMessage: (agent, message, type = "progress") =>
    set((state) => ({
      progressMessages: [
        ...state.progressMessages,
        { id: `${Date.now()}-${Math.random()}`, agent, message, time: new Date(), type },
      ].slice(-50),
      eventsVersion: state.eventsVersion + 1,
    })),

  clearProgressMessages: () =>
    set((state) => ({
      progressMessages: [],
      eventsVersion: state.eventsVersion + 1,
    })),

  setFinalResult: (result) => set({ finalResult: result }),

  setAnalysisResult: (result) => set({ analysisResult: result }),

  setError: (error) => set({ error, isAnalyzing: false }),

  reset: () => set({ ...initialState, progressMessages: [] }),

  toggleChatDrawer: () => set((state) => ({ isChatDrawerOpen: !state.isChatDrawerOpen })),
  setChatDrawerOpen: (open) => set({ isChatDrawerOpen: open }),
}));
