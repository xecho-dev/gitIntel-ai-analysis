// 管理员端专用类型（Users / Analysis History 相关）
// 与 @gitintel/types 的主要区别：
// - AdminUserItem 包含 users 表全部字段（用于管理后台展示）
// - AdminAnalysisItem 包含 user_id（关联到具体用户）

// ─── 用户管理 ────────────────────────────────────────────────────────────────

export interface AdminUserItem {
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

export interface AdminUserListResponse {
  items: AdminUserItem[];
  total: number;
  page: number;
  pageSize: number;
}

// ─── 分析记录 ────────────────────────────────────────────────────────────────

export interface AdminAnalysisItem {
  id: string;
  user_id: string;
  repo_url: string;
  repo_name: string;
  branch: string;
  health_score: number | null;
  quality_score: string | null;
  risk_level: string | null;
  risk_level_color: string | null;
  risk_level_bg: string | null;
  border_color: string | null;
  result_data: Record<string, unknown> | null;
  langsmith_trace_id?: string | null;
  thread_id?: string | null;
  created_at: string;
}

export interface AdminHistoryListResponse {
  items: AdminAnalysisItem[];
  total: number;
  page: number;
  pageSize: number;
  stats: {
    total_scans: number;
    avg_health_score: number;
    high_risk_count: number;
    medium_risk_count: number;
  };
}

// ─── 概览统计 ────────────────────────────────────────────────────────────────

export interface AdminOverviewStats {
  total_users: number;
  total_analysis: number;
  today_analysis: number;
  avg_health_score: number;
  high_risk_count: number;
  medium_risk_count: number;
}

// ─── 主题颜色常量 ────────────────────────────────────────────────────────────

export const THEME_COLORS = {
  primary: '#acc7ff',
  primaryContainer: '#498fff',
  secondary: '#f4fff5',
  secondaryFixedDim: '#00e297',
  tertiary: '#d5bbff',
  tertiaryContainer: '#a875fc',
  error: '#ffb4ab',
  background: '#10141a',
  surface: '#10141a',
  surfaceContainer: '#1c2026',
  surfaceContainerLow: '#181c22',
  surfaceContainerLowest: '#0a0e14',
  surfaceContainerHigh: '#262a31',
  surfaceContainerHighest: '#31353c',
  onBackground: '#dfe2eb',
  onSurface: '#dfe2eb',
  onSurfaceVariant: '#c1c6d6',
  outline: '#8b909f',
  outlineVariant: '#414754',
};

// ─── 分析详情 ────────────────────────────────────────────────────────────────

export interface HistoryStats {
  total_scans: number;
  avg_health_score: number;
  high_risk_count: number;
  medium_risk_count: number;
}

export interface AdminHistoryDetailResponse {
  history: AdminAnalysisItem;
  user: AdminUserItem;
  langsmith?: LangSmithTraceInfo | null;
}

export interface AdminUserHistoryResponse {
  user: AdminUserItem;
  history: AdminHistoryListResponse;
}

export interface LangSmithTraceInfo {
  project_name: string;
  run_url?: string | null;
  trace_id?: string | null;
  total_tokens: number;
  total_cost_usd: number;
  total_runs: number;
  agents: string[];
  total_prompt_tokens?: number;
  total_completion_tokens?: number;
  total_duration_ms?: number;
}

export interface HistoryFilterParams {
  page?: number;
  pageSize?: number;
  search?: string;
  user_id?: string;
  risk_level?: string;
  quality_score_min?: number;
  quality_score_max?: number;
  date_from?: string;
  date_to?: string;
  repo_name?: string;
  branch?: string;
}