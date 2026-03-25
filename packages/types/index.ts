// ============================================================
// GitIntel 共享类型定义
// 前端（BFF）和后端（Agent）共用同一份类型定义
// ============================================================

// --- 请求类型 ---

export interface AnalyzeRequest {
  repoUrl: string;
  branch?: string;
}

// --- SSE 事件类型 ---

export type AgentName = "architecture" | "quality" | "dependency" | "optimization";

export type EventType = "status" | "progress" | "result" | "error";

export interface AgentEvent {
  type: EventType;
  agent: AgentName;
  message?: string;
  percent?: number;
  data?: unknown;
}

// --- 分析结果类型 ---

export interface ArchitectureResult {
  complexity: "Low" | "Medium" | "High";
  components: number;
  techStack: string[];
  maintainability: string;
}

export interface QualityResult {
  healthScore: number;
  testCoverage: number;
  complexity: "Low" | "Normal" | "High";
}

export interface DependencyResult {
  total: number;
  scanned: number;
  high: number;
  medium: number;
  low: number;
}

export interface Suggestion {
  id: number;
  type: "performance" | "refactor" | "security";
  title: string;
  description: string;
  priority: "high" | "medium" | "low";
}

export interface OptimizationResult {
  suggestions: Suggestion[];
}

export interface AnalysisResult {
  architecture: ArchitectureResult;
  quality: QualityResult;
  dependency: DependencyResult;
  optimization: OptimizationResult;
}

// --- 历史记录类型 ---

export interface HistoryItem {
  id: number;
  repo: string;
  branch?: string;
  version?: string;
  date: string;
  time: string;
  health: string;
  quality: string;
  risk: string;
  riskColor: string;
  riskBg: string;
  border: string;
  type: "default" | "premium" | "version";
}
