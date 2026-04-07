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

// ArchitectureAgent 输出
export interface ArchitectureResult {
  complexity: "Low" | "Medium" | "High";
  components: number;
  techStack: string[];
  maintainability: string;
  architectureStyle?: string;
  keyPatterns?: string[];
  hotSpots?: string[];
  summary?: string;
  llmPowered?: boolean;
}

// QualityAgent 输出
export interface QualityResult {
  healthScore: number;
  testCoverage: number;
  complexity: "Low" | "Medium" | "High";
  maintainability?: string;
  duplication?: {
    score: number;
    duplication_level: "Low" | "Medium" | "High";
  };
  pythonMetrics?: {
    totalFunctions: number;
    overComplexityCount: number;
    avgComplexity: number;
  };
  // LLM 五维评分
  maintScore?: number;
  compScore?: number;
  dupScore?: number;
  testScore?: number;
  coupScore?: number;
  llmPowered?: boolean;
}

// DependencyAgent 输出
export interface DependencyResult {
  total: number;
  scanned: number;
  high: number;
  medium: number;
  low: number;
  riskLevel: "low" | "medium" | "high" | "unknown";
  deps?: Array<{
    name: string;
    version?: string;
    risk?: string;
    riskLevel?: string;
  }>;
}

export interface Suggestion {
  id: number;
  type: "performance" | "refactor" | "security" | "general";
  title: string;
  description: string;
  priority: "high" | "medium" | "low";
  category?: string;
  source?: string;
}

export interface OptimizationResult {
  suggestions: Suggestion[];
  total: number;
  high_priority?: number;
  medium_priority?: number;
  low_priority?: number;
}

export interface AnalysisResult {
  repoLoader?: Record<string, unknown>;
  codeParser?: Record<string, unknown>;
  techStack?: Record<string, unknown>;
  quality: QualityResult;
  dependency: DependencyResult;
  architecture: ArchitectureResult;
  suggestion: OptimizationResult;
  suggestions?: Suggestion[];
}

// --- 历史记录类型 ---

export interface HistoryItem {
  id: string;
  repo_url: string;
  repo_name: string;
  branch: string;
  health_score: number | null;
  quality_score: string | null;
  risk_level: string | null;
  risk_level_color: string | null;
  risk_level_bg: string | null;
  border_color: string | null;
  result_data: AnalysisResult | null;
  created_at: string;
}

export interface HistoryStats {
  total_scans: number;
  avg_health_score: number;
  high_risk_count: number;
  medium_risk_count: number;
}

export interface HistoryListResponse {
  items: HistoryItem[];
  total: number;
  page: number;
  page_size: number;
  stats: HistoryStats;
}

export interface SaveAnalysisPayload {
  repo_url: string;
  branch: string;
  result_data: AnalysisResult;
}

// --- 用户资料类型 ---

export interface UserProfile {
  id: string;
  auth_user_id: string;
  github_id: string | null;
  login: string;
  email: string | null;
  avatar_url: string | null;
  name: string | null;
  bio: string | null;
  company: string | null;
  location: string | null;
  blog: string | null;
  public_repos: number;
  followers: number;
  following: number;
  created_at: string;
  updated_at: string;
}
