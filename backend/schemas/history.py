from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# --- 请求模型 ---

class SaveAnalysisRequest(BaseModel):
    repo_url: str
    branch: str = "main"
    result_data: dict


# --- 响应模型 ---

class HistoryItem(BaseModel):
    id: str
    repo_url: str
    repo_name: str
    branch: str
    repo_sha: Optional[str] = None
    health_score: Optional[float]
    quality_score: Optional[str]
    risk_level: Optional[str]
    risk_level_color: Optional[str]
    risk_level_bg: Optional[str]
    border_color: Optional[str]
    result_data: Optional[dict]
    created_at: str


class HistoryStats(BaseModel):
    total_scans: int
    avg_health_score: float
    high_risk_count: int
    medium_risk_count: int


class HistoryListResponse(BaseModel):
    items: list[HistoryItem]
    total: int
    page: int
    page_size: int
    stats: HistoryStats


class SaveAnalysisResponse(BaseModel):
    id: str
    created_at: str


class UserProfile(BaseModel):
    id: str
    auth_user_id: str
    github_id: Optional[str]
    login: str
    email: Optional[str]
    avatar_url: Optional[str]
    name: Optional[str]
    bio: Optional[str]
    company: Optional[str]
    location: Optional[str]
    blog: Optional[str]
    public_repos: int
    followers: int
    following: int
    created_at: str
    updated_at: str


class UpsertUserRequest(BaseModel):
    github_id: Optional[str] = None
    login: str
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    name: Optional[str] = None
    bio: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    blog: Optional[str] = None
    public_repos: int = 0
    followers: int = 0
    following: int = 0


# ─── 管理端（Admin）请求/响应模型 ──────────────────────────────────────────────

class AdminOverviewResponse(BaseModel):
    total_users: int
    total_analysis: int
    today_analysis: int
    avg_health_score: float
    high_risk_count: int
    medium_risk_count: int


class AdminUserItem(BaseModel):
    id: str
    auth_user_id: str
    github_id: Optional[str]
    login: str
    email: Optional[str]
    avatar_url: Optional[str]
    name: Optional[str]
    bio: Optional[str]
    company: Optional[str]
    location: Optional[str]
    blog: Optional[str]
    public_repos: int
    followers: int
    following: int
    created_at: str
    updated_at: str


class AdminUserListResponse(BaseModel):
    items: list[AdminUserItem]
    total: int
    page: int
    pageSize: int


class AdminHistoryItem(BaseModel):
    id: str
    user_id: str
    repo_url: str
    repo_name: str
    branch: str
    repo_sha: Optional[str] = None
    health_score: Optional[float]
    quality_score: Optional[str]
    risk_level: Optional[str]
    risk_level_color: Optional[str]
    risk_level_bg: Optional[str]
    border_color: Optional[str]
    result_data: Optional[dict]
    langsmith_trace_id: Optional[str] = None
    thread_id: Optional[str] = None
    created_at: str


class AdminHistoryListResponse(BaseModel):
    items: list[AdminHistoryItem]
    total: int
    page: int
    pageSize: int
    stats: HistoryStats


# ─── Admin 筛选 & 详情 ─────────────────────────────────────────────────────────

class AdminHistoryFilter(BaseModel):
    """分析历史筛选条件"""
    user_id: Optional[str] = None       # 限定用户
    risk_level: Optional[str] = None     # 高危 | 中等 | 极低
    quality_score_min: Optional[float] = None  # 最低质量分（0-100）
    quality_score_max: Optional[float] = None  # 最高质量分
    date_from: Optional[str] = None     # 开始日期 YYYY-MM-DD
    date_to: Optional[str] = None       # 结束日期 YYYY-MM-DD
    repo_name: Optional[str] = None     # 仓库名（模糊搜索）
    branch: Optional[str] = None        # 分支名


class AdminUserHistoryResponse(BaseModel):
    """指定用户的分析历史（包含用户名信息）"""
    user: AdminUserItem
    history: AdminHistoryListResponse


class LangSmithTraceInfo(BaseModel):
    """LangSmith 追踪信息"""
    project_name: str
    run_url: Optional[str] = None
    trace_id: Optional[str] = None
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_runs: int = 0
    agents: list[str] = []
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_duration_ms: int = 0


class AdminHistoryDetailResponse(BaseModel):
    """单条分析记录的完整详情"""
    history: AdminHistoryItem
    user: AdminUserItem
    langsmith: Optional[LangSmithTraceInfo] = None
