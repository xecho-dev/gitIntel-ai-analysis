import { create } from "zustand";

interface AppState {
  // 分析状态
  isAnalyzing: boolean;
  setIsAnalyzing: (value: boolean) => void;

  // 当前分析的仓库
  repoUrl: string;
  setRepoUrl: (url: string) => void;

  // 分析结果
  analysisResult: any | null;
  setAnalysisResult: (result: any) => void;

  // 错误信息
  error: string | null;
  setError: (error: string | null) => void;

  // 清除所有状态
  reset: () => void;
}

const initialState = {
  isAnalyzing: false,
  repoUrl: "",
  analysisResult: null,
  error: null,
};

export const useAppStore = create<AppState>((set) => ({
  ...initialState,

  setIsAnalyzing: (value) => set({ isAnalyzing: value }),

  setRepoUrl: (url) => set({ repoUrl: url }),

  setAnalysisResult: (result) => set({ analysisResult: result, error: null }),

  setError: (error) => set({ error, isAnalyzing: false }),

  reset: () => set(initialState),
}));
