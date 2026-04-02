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
