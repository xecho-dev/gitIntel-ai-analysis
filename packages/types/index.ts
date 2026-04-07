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

export type AgentName =
  | "fetch_tree_classify"
  | "load_p0"
  | "load_p1"
  | "load_p2"
  | "load_p2_decide"
  | "load_more_p2"
  | "code_parser_p0"
  | "code_parser_p1"
  | "code_parser_final"
  | "tech_stack"
  | "quality"
  | "dependency"
  | "architecture"
  | "merge_analysis"
  | "optimization"
  | "suggestion";

export type EventType = "status" | "progress" | "result" | "error";

export interface AgentEvent {
  type: EventType;
  agent: AgentName;
  message?: string;
  percent?: number;
  data?: unknown;
}

// --- 分析结果类型 ---

// ArchitectureAgent 输出（真正的 LLM 驱动）
export interface ArchitectureResult {
  complexity: "Low" | "Medium" | "High";
  components: number;
  techStack: string[];
  maintainability: string;
  architectureStyle: string;
  keyPatterns: string[];
  hotSpots: string[];
  summary: string;
  llmPowered?: boolean;
}

// QualityAgent 输出（tree-sitter AST 分析 + LLM 五维评分）
export interface QualityResult {
  healthScore: number;
  testCoverage: number;
  complexity: "Low" | "Medium" | "High";
  maintainability: string;
  duplication: {
    score: number;
    duplication_level: "Low" | "Medium" | "High";
  };
  pythonMetrics?: {
    totalFunctions: number;
    overComplexityCount: number;
    avgComplexity: number;
    longFunctions: Array<{ function: string; lines: number }>;
  };
  typescriptMetrics?: {
    totalFunctions: number;
    overComplexityCount: number;
    avgComplexity: number;
  };
  // LLM 五维评分（0-100，越高越好）
  maintScore?: number;
  compScore?: number;
  dupScore?: number;
  testScore?: number;
  coupScore?: number;
  llmPowered?: boolean;
}

// DependencyAgent 输出（规则引擎风险评估）
export interface DependencyResult {
  total: number;
  scanned: number;
  high: number;
  medium: number;
  low: number;
  riskLevel: "low" | "medium" | "high" | "unknown";
  deps: Array<{
    name: string;
    version?: string;
    risk?: string;
    riskLevel?: string;
  }>;
}

// SuggestionAgent / OptimizationAgent 输出（LLM + 规则引擎）
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
  high_priority: number;
  medium_priority: number;
  low_priority: number;
}

export interface AnalysisResult {
  repoLoader?: {
    owner: string;
    repo: string;
    branch: string;
    sha: string;
    total_tree_files: number;
    p0_count: number;
    p1_count: number;
    p2_count: number;
  };
  codeParser?: {
    total_files: number;
    parsed_files: number;
    total_functions: number;
    total_classes: number;
    language_stats: Record<string, {
      files: number;
      functions: number;
      classes: number;
      imports: number;
      total_lines: number;
    }>;
    largest_files: Array<{
      path: string;
      lines: number;
      functions: number;
      language: string;
    }>;
    chunked_files: Record<string, unknown[]>;
    total_chunks: number;
  };
  techStack?: {
    languages: string[];
    frameworks: string[];
    infrastructure: string[];
    dev_tools: string[];
    package_manager: string;
    dependency_count: number;
    dev_dependency_count: number;
    config_files_found: string[];
  };
  quality: QualityResult;
  dependency: DependencyResult;
  architecture: ArchitectureResult;
  suggestion: OptimizationResult;
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
