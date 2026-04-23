"""GitIntel 数据库操作层（直接调用 Supabase Python SDK）。"""
from datetime import datetime
from typing import Optional
from supabase_client import Client
from schemas.chat import (
    ChatSession,
    ChatMessage,
    CreateSessionRequest,
    RAGSource,
)
from schemas.history import (
    HistoryItem,
    HistoryStats,
    HistoryListResponse,
    SaveAnalysisResponse,
    UserProfile,
    AdminOverviewResponse,
    AdminUserItem,
    AdminUserListResponse,
    AdminHistoryItem,
    AdminHistoryListResponse,
)


def _derive_history_metrics(result_data: dict) -> dict:
    """从 Agent 结果 JSON 中提取健康度、风险等级等元数据。"""
    quality_res = result_data.get("quality", {})
    dep_res = result_data.get("dependency", {})
    arch_res = result_data.get("architecture", {})

    health = quality_res.get("healthScore", 0) or 0
    risk_high = dep_res.get("high", 0) or 0
    risk_med = dep_res.get("medium", 0) or 0

    if health >= 85:
        health_label = f"优 ({health}%)"
    elif health >= 60:
        health_label = f"良 ({health}%)"
    else:
        health_label = f"危 ({health}%)"

    if health >= 85:
        quality_score = "A+"
    elif health >= 75:
        quality_score = "A"
    elif health >= 65:
        quality_score = "B+"
    elif health >= 55:
        quality_score = "B"
    elif health >= 45:
        quality_score = "C"
    else:
        quality_score = "C-"

    if risk_high > 0:
        risk_level = "高危"
        risk_color = "text-rose-400"
        risk_bg = "bg-rose-400"
        border = "border-rose-400"
    elif risk_med > 0:
        risk_level = "中等"
        risk_color = "text-purple-400"
        risk_bg = "bg-purple-400"
        border = "border-purple-400"
    else:
        risk_level = "极低"
        risk_color = "text-emerald-400"
        risk_bg = "bg-emerald-400"
        border = "border-blue-400"

    return {
        "health_score": health,
        "health_label": health_label,
        "quality_score": quality_score,
        "risk_level": risk_level,
        "risk_level_color": risk_color,
        "risk_level_bg": risk_bg,
        "border_color": border,
        "complexity": arch_res.get("complexity", "Medium"),
    }


def _extract_repo_sha(result_data: dict) -> Optional[str]:
    """从 result_data 中提取 repo_sha。

    result_data 可能有两个来源，结构不同：
    1. SSE 流保存时：result_data = {"final_result": {...}}，需先解包
    2. /api/history/save 手动保存时：result_data 直接包含 "repo_loader"
    """
    import logging
    logger2 = logging.getLogger("gitintel")

    data = result_data

    # 如果 result_data["final_result"] 存在（来自 SSE 流保存路径），先解包
    if "final_result" in data:
        logger2.info(f"[_extract_repo_sha] 解包 final_result，原始 keys={list(data.keys())}")
        data = data["final_result"]
        logger2.info(f"[_extract_repo_sha] 解包后 keys={list(data.keys())}")
    else:
        logger2.info(f"[_extract_repo_sha] 无 final_result，原始 keys={list(data.keys())}")

    repo_loader = data.get("repo_loader", {})
    if isinstance(repo_loader, dict):
        sha = repo_loader.get("repo_sha")
        return sha
    logger2.warning(f"[_extract_repo_sha] 未找到 repo_loader，data keys={list(data.keys())}")
    return None


def save_analysis(
    sb: Client,
    auth_user_id: str,
    repo_url: str,
    branch: str,
    result_data: dict,
    langsmith_trace_id: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> SaveAnalysisResponse:
    """保存一次分析结果，返回新记录的 id。"""
    # 先找 user uuid（users.id 是 UUID，而 analysis_history.user_id 需要 UUID）
    user_row = (
        sb.table("users")
        .select("id")
        .eq("auth_user_id", auth_user_id)
        .maybe_single()
        .execute()
    )
    if user_row is None:
        raise ValueError(f"User not found for auth_user_id: {auth_user_id}")
    row = user_row.data
    if not row or not row.get("id"):
        raise ValueError(f"User not found for auth_user_id: {auth_user_id}")
    user_uuid = row["id"]

    metrics = _derive_history_metrics(result_data)
    repo_sha = _extract_repo_sha(result_data)

    # 从 repo_url 提取 repo_name（"owner/repo"）
    repo_name = repo_url.rstrip("/").split("/")[-1]

    sb.table("analysis_history").insert(
        {
            "user_id": user_uuid,
            "repo_url": repo_url,
            "repo_name": repo_name,
            "branch": branch,
            "repo_sha": repo_sha,
            "result_data": result_data,
            "health_score": metrics["health_score"],
            "quality_score": metrics["quality_score"],
            "risk_level": metrics["risk_level"],
            "risk_level_color": metrics["risk_level_color"],
            "risk_level_bg": metrics["risk_level_bg"],
            "border_color": metrics["border_color"],
            "langsmith_trace_id": langsmith_trace_id,
            "thread_id": thread_id,
        }
    ).execute()

    fetched = (
        sb.table("analysis_history")
        .select("id, created_at")
        .eq("user_id", user_uuid)
        .order("created_at", desc=True)
        .limit(1)
        .maybe_single()
        .execute()
    )
    r = fetched.data if hasattr(fetched, "data") else fetched
    if not r:
        raise RuntimeError("Save analysis failed: record not found after insert")
    return SaveAnalysisResponse(id=r["id"], created_at=r["created_at"])


def get_history(
    sb: Client,
    auth_user_id: str,
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
) -> HistoryListResponse:
    """分页查询用户的分析历史。"""
    offset = (page - 1) * page_size

    # 先找 user uuid（users.id 是 UUID，而 analysis_history.user_id 需要 UUID）
    user_row = (
        sb.table("users")
        .select("id")
        .eq("auth_user_id", auth_user_id)
        .maybe_single()
        .execute()
    )
    if user_row is None:
        return HistoryListResponse(
            items=[],
            total=0,
            page=page,
            page_size=page_size,
            stats=HistoryStats(total_scans=0, avg_health_score=0, high_risk_count=0, medium_risk_count=0),
        )
    row = user_row.data
    if not row or not row.get("id"):
        return HistoryListResponse(
            items=[],
            total=0,
            page=page,
            page_size=page_size,
            stats=HistoryStats(total_scans=0, avg_health_score=0, high_risk_count=0, medium_risk_count=0),
        )
    user_uuid = row["id"]

    # 查询历史
    query = (
        sb.table("analysis_history")
        .select("*")
        .eq("user_id", user_uuid)
        .order("created_at", desc=True)
        .range(offset, offset + page_size - 1)
    )
    if search:
        query = query.ilike("repo_name", f"%{search}%")

    data = query.execute()

    # 查询总数
    count_query = (
        sb.table("analysis_history")
        .select("id", count="exact")
        .eq("user_id", user_uuid)
    )
    if search:
        count_query = count_query.ilike("repo_name", f"%{search}%")
    count_data = count_query.execute()
    total = count_data.count or 0

    # 查询统计数据
    stats_data = (
        sb.table("analysis_history")
        .select("health_score, risk_level")
        .eq("user_id", user_uuid)
        .execute()
    )
    rows = stats_data.data or []
    scores = [r["health_score"] for r in rows if r.get("health_score") is not None]
    avg_hs = round(sum(scores) / len(scores), 1) if scores else 0
    high_count = sum(1 for r in rows if r.get("risk_level") == "高危")
    med_count = sum(1 for r in rows if r.get("risk_level") == "中等")

    items = [
        HistoryItem(
            id=r["id"],
            repo_url=r["repo_url"],
            repo_name=r["repo_name"],
            branch=r.get("branch", "main"),
            repo_sha=r.get("repo_sha"),
            health_score=r.get("health_score"),
            quality_score=r.get("quality_score"),
            risk_level=r.get("risk_level"),
            risk_level_color=r.get("risk_level_color"),
            risk_level_bg=r.get("risk_level_bg"),
            border_color=r.get("border_color"),
            result_data=r.get("result_data"),
            created_at=r["created_at"],
        )
        for r in data.data
    ]

    return HistoryListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        stats=HistoryStats(
            total_scans=len(rows),
            avg_health_score=avg_hs,
            high_risk_count=high_count,
            medium_risk_count=med_count,
        ),
    )


def delete_analysis(sb: Client, auth_user_id: str, history_id: str) -> bool:
    """删除指定历史记录。"""
    user_row = (
        sb.table("users")
        .select("id")
        .eq("auth_user_id", auth_user_id)
        .maybe_single()
        .execute()
    )
    if user_row is None:
        return False
    row = user_row.data
    if not row or not row.get("id"):
        return False
    user_uuid = row["id"]

    sb.table("analysis_history").delete().eq("id", history_id).eq("user_id", user_uuid).execute()
    return True


def get_sha_cached_analysis(sb: Client, auth_user_id: str, repo_url: str, branch: str, repo_sha: str) -> Optional[dict]:
    """
    查询最近一次分析结果，条件：repo_url + branch + repo_sha 完全相同。

    用于智能缓存：若 SHA 未变，直接复用已有结果，无需重新分析。
    返回 result_data（完整分析结果），若不存在则返回 None。
    """
    user_row = (
        sb.table("users")
        .select("id")
        .eq("auth_user_id", auth_user_id)
        .maybe_single()
        .execute()
    )
    if user_row is None or not user_row.data or not user_row.data.get("id"):
        return None
    user_uuid = user_row.data["id"]

    record = (
        sb.table("analysis_history")
        .select("result_data, repo_sha, created_at")
        .eq("user_id", user_uuid)
        .eq("repo_url", repo_url)
        .eq("branch", branch)
        .eq("repo_sha", repo_sha)
        .order("created_at", desc=True)
        .limit(1)
        .maybe_single()
        .execute()
    )
    if record is None or not record.data:
        return None
    return record.data.get("result_data")


def upsert_user(sb: Client, auth_user_id: str, payload: dict) -> UserProfile:
    """
    Upsert GitHub 用户信息。

    去重策略（防止同一 GitHub 账户因 auth_user_id 变化而重复创建）：
    1. 先按 auth_user_id 查找（稳定路径）
    2. 如果找不到，再按 login 查找：
       - 找到 → 更新旧记录的 auth_user_id（保留原 users.id，历史记录不受影响）
       - 未找到 → 正常创建新记录
    """
    payload_clean = {k: v for k, v in payload.items() if v is not None and v != ""}
    payload_clean["auth_user_id"] = auth_user_id
    payload_clean["updated_at"] = datetime.utcnow().isoformat()

    # 尝试 1：按 auth_user_id 查找（正常路径）
    existing = (
        sb.table("users")
        .select("*")
        .eq("auth_user_id", auth_user_id)
        .maybe_single()
        .execute()
    )

    if existing is not None and existing.data:
        # 路径 A：auth_user_id 已存在，直接更新
        sb.table("users").upsert(payload_clean, on_conflict="auth_user_id").execute()
    else:
        # 路径 B：auth_user_id 变化，检查是否有相同 login 的旧记录
        login_val = payload_clean.get("login")
        if login_val:
            same_login = (
                sb.table("users")
                .select("id, auth_user_id")
                .eq("login", login_val)
                .maybe_single()
                .execute()
            )
            if same_login is not None and same_login.data:
                # 同一 GitHub 账户（login 相同），复用旧记录的 id
                # 先把旧记录的 auth_user_id 更新为新的（突破 auth_user_id UNIQUE 约束）
                old_id = same_login.data["id"]
                sb.table("users").update({"auth_user_id": auth_user_id}).eq("id", old_id).execute()
                # 再正常 upsert（此时 auth_user_id 唯一，不会再产生重复）
                sb.table("users").upsert(payload_clean, on_conflict="auth_user_id").execute()
            else:
                # 路径 C：真正的全新用户，直接 upsert
                sb.table("users").upsert(payload_clean, on_conflict="auth_user_id").execute()
        else:
            # 无 login 字段，fallback 直接 upsert
            sb.table("users").upsert(payload_clean, on_conflict="auth_user_id").execute()

    fetched = (
        sb.table("users")
        .select("*")
        .eq("auth_user_id", auth_user_id)
        .maybe_single()
        .execute()
    )
    r = fetched.data if hasattr(fetched, "data") else fetched
    if not r:
        raise RuntimeError("Upsert user failed: user not found after upsert")
    return UserProfile(
        id=r["id"],
        auth_user_id=r["auth_user_id"],
        github_id=r.get("github_id"),
        login=r["login"],
        email=r.get("email"),
        avatar_url=r.get("avatar_url"),
        name=r.get("name"),
        bio=r.get("bio"),
        company=r.get("company"),
        location=r.get("location"),
        blog=r.get("blog"),
        public_repos=r.get("public_repos", 0),
        followers=r.get("followers", 0),
        following=r.get("following", 0),
        created_at=r["created_at"],
        updated_at=r.get("updated_at", r["created_at"]),
    )


def get_user_profile(sb: Client, auth_user_id: str) -> Optional[UserProfile]:
    """获取用户资料。"""
    data = (
        sb.table("users")
        .select("*")
        .eq("auth_user_id", auth_user_id)
        .maybe_single()
        .execute()
    )
    if data is None:
        return None
    r = data.data
    if not r or not isinstance(r, dict):
        return None
    return UserProfile(
        id=r["id"],
        auth_user_id=r["auth_user_id"],
        github_id=r.get("github_id"),
        login=r["login"],
        email=r.get("email"),
        avatar_url=r.get("avatar_url"),
        name=r.get("name"),
        bio=r.get("bio"),
        company=r.get("company"),
        location=r.get("location"),
        blog=r.get("blog"),
        public_repos=r.get("public_repos", 0),
        followers=r.get("followers", 0),
        following=r.get("following", 0),
        created_at=r["created_at"],
        updated_at=r.get("updated_at", r["created_at"]),
    )


def get_user_uuid(sb: Client, auth_user_id: str) -> Optional[str]:
    """根据 auth_user_id 查找用户的 uuid。"""
    resp = (
        sb.table("users")
        .select("id")
        .eq("auth_user_id", auth_user_id)
        .maybe_single()
        .execute()
    )
    if resp is None:
        return None
    row = resp.data
    if not row or not isinstance(row, dict):
        return None
    return row.get("id")


# ─── 管理端（Admin）数据库操作 ─────────────────────────────────────────────────

def db_get_overview_stats(sb: Client) -> AdminOverviewResponse:
    """获取全站概览统计数据。"""
    # 总用户数
    user_count_data = sb.table("users").select("id", count="exact").execute()
    total_users = user_count_data.count or 0

    # 总分析次数 + 统计信息
    all_history = sb.table("analysis_history").select(
        "health_score, risk_level, created_at"
    ).execute()
    all_rows = all_history.data or []
    total_analysis = len(all_rows)

    # 今日分析次数
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    today_data = (
        sb.table("analysis_history")
        .select("id", count="exact")
        .gte("created_at", f"{today}T00:00:00Z")
        .execute()
    )
    today_analysis = today_data.count or 0

    # 平均健康分
    scores = [r["health_score"] for r in all_rows if r.get("health_score") is not None]
    avg_hs = round(sum(scores) / len(scores), 1) if scores else 0.0

    high_risk_count = sum(1 for r in all_rows if r.get("risk_level") == "高危")
    medium_risk_count = sum(1 for r in all_rows if r.get("risk_level") == "中等")

    return AdminOverviewResponse(
        total_users=total_users,
        total_analysis=total_analysis,
        today_analysis=today_analysis,
        avg_health_score=avg_hs,
        high_risk_count=high_risk_count,
        medium_risk_count=medium_risk_count,
    )


def db_get_all_users(
    sb: Client,
    page: int = 1,
    page_size: int = 10,
    search: str | None = None,
) -> AdminUserListResponse:
    """管理端：获取全部用户列表（分页，支持按 login/email 搜索）。"""
    offset = (page - 1) * page_size

    query = sb.table("users").select("*").order("created_at", desc=True).range(offset, offset + page_size - 1)
    if search:
        query = query.or_(f"login.ilike.%{search}%,email.ilike.%{search}%")

    data = query.execute()

    count_query = sb.table("users").select("id", count="exact")
    if search:
        count_query = count_query.or_(f"login.ilike.%{search}%,email.ilike.%{search}%")
    count_data = count_query.execute()
    total = count_data.count or 0

    items = [
        AdminUserItem(
            id=r["id"],
            auth_user_id=r["auth_user_id"],
            github_id=r.get("github_id"),
            login=r["login"],
            email=r.get("email"),
            avatar_url=r.get("avatar_url"),
            name=r.get("name"),
            bio=r.get("bio"),
            company=r.get("company"),
            location=r.get("location"),
            blog=r.get("blog"),
            public_repos=r.get("public_repos", 0),
            followers=r.get("followers", 0),
            following=r.get("following", 0),
            created_at=r["created_at"],
            updated_at=r.get("updated_at", r["created_at"]),
        )
        for r in data.data
    ]
    return AdminUserListResponse(items=items, total=total, page=page, pageSize=page_size)


def db_update_user(sb: Client, user_id: str, data: dict) -> bool:
    """管理端：更新指定用户信息（支持禁用/启用等）。"""
    update_fields = {k: v for k, v in data.items() if k not in ("id", "auth_user_id", "created_at")}
    update_fields["updated_at"] = datetime.utcnow().isoformat()
    result = sb.table("users").update(update_fields).eq("id", user_id).execute()
    return (result.data is not None and len(result.data) > 0) or (hasattr(result, "count") and result.count > 0)


def db_get_all_history(
    sb: Client,
    page: int = 1,
    page_size: int = 10,
    search: str | None = None,
) -> AdminHistoryListResponse:
    """管理端：获取全站分析历史（分页）。"""
    offset = (page - 1) * page_size

    query = (
        sb.table("analysis_history")
        .select("*")
        .order("created_at", desc=True)
        .range(offset, offset + page_size - 1)
    )
    if search:
        query = query.ilike("repo_name", f"%{search}%")

    data = query.execute()

    count_query = sb.table("analysis_history").select("id", count="exact")
    if search:
        count_query = count_query.ilike("repo_name", f"%{search}%")
    count_data = count_query.execute()
    total = count_data.count or 0

    # 统计信息（不计筛选）
    stats_all = sb.table("analysis_history").select("health_score, risk_level").execute()
    all_rows = stats_all.data or []
    scores = [r["health_score"] for r in all_rows if r.get("health_score") is not None]
    avg_hs = round(sum(scores) / len(scores), 1) if scores else 0.0
    high_count = sum(1 for r in all_rows if r.get("risk_level") == "高危")
    med_count = sum(1 for r in all_rows if r.get("risk_level") == "中等")

    items = [
        AdminHistoryItem(
            id=r["id"],
            user_id=r["user_id"],
            repo_url=r["repo_url"],
            repo_name=r["repo_name"],
            branch=r.get("branch", "main"),
            repo_sha=r.get("repo_sha"),
            health_score=r.get("health_score"),
            quality_score=r.get("quality_score"),
            risk_level=r.get("risk_level"),
            risk_level_color=r.get("risk_level_color"),
            risk_level_bg=r.get("risk_level_bg"),
            border_color=r.get("border_color"),
            result_data=r.get("result_data"),
            langsmith_trace_id=r.get("langsmith_trace_id"),
            thread_id=r.get("thread_id"),
            created_at=r["created_at"],
        )
        for r in data.data
    ]
    return AdminHistoryListResponse(
        items=items,
        total=total,
        page=page,
        pageSize=page_size,
        stats=HistoryStats(
            total_scans=len(all_rows),
            avg_health_score=avg_hs,
            high_risk_count=high_count,
            medium_risk_count=med_count,
        ),
    )


def db_delete_history_by_admin(sb: Client, record_id: str) -> bool:
    """管理端：删除指定分析记录（不校验用户权限）。"""
    result = sb.table("analysis_history").delete().eq("id", record_id).execute()
    return (result.data is not None and len(result.data) > 0) or (hasattr(result, "count") and result.count > 0)


def db_get_history_by_id(sb: Client, record_id: str) -> Optional[AdminHistoryItem]:
    """根据 record_id 获取单条分析历史记录。"""
    data = (
        sb.table("analysis_history")
        .select("*")
        .eq("id", record_id)
        .maybe_single()
        .execute()
    )
    if data is None:
        return None
    r = data.data
    if not r or not isinstance(r, dict):
        return None
    return AdminHistoryItem(
        id=r["id"],
        user_id=r["user_id"],
        repo_url=r["repo_url"],
        repo_name=r["repo_name"],
        branch=r.get("branch", "main"),
        repo_sha=r.get("repo_sha"),
        health_score=r.get("health_score"),
        quality_score=r.get("quality_score"),
        risk_level=r.get("risk_level"),
        risk_level_color=r.get("risk_level_color"),
        risk_level_bg=r.get("risk_level_bg"),
        border_color=r.get("border_color"),
        result_data=r.get("result_data"),
        langsmith_trace_id=r.get("langsmith_trace_id"),
        thread_id=r.get("thread_id"),
        created_at=r["created_at"],
    )


def db_get_user_by_id(sb: Client, user_id: str) -> Optional[AdminUserItem]:
    """根据 user_id（UUID）获取用户信息。"""
    data = (
        sb.table("users")
        .select("*")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    if data is None:
        return None
    r = data.data
    if not r or not isinstance(r, dict):
        return None
    return AdminUserItem(
        id=r["id"],
        auth_user_id=r["auth_user_id"],
        github_id=r.get("github_id"),
        login=r["login"],
        email=r.get("email"),
        avatar_url=r.get("avatar_url"),
        name=r.get("name"),
        bio=r.get("bio"),
        company=r.get("company"),
        location=r.get("location"),
        blog=r.get("blog"),
        public_repos=r.get("public_repos", 0),
        followers=r.get("followers", 0),
        following=r.get("following", 0),
        created_at=r["created_at"],
        updated_at=r.get("updated_at", r["created_at"]),
    )


def db_get_user_analysis_history(
    sb: Client,
    user_id: str,
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
) -> AdminHistoryListResponse:
    """获取指定用户的分析历史（分页）。"""
    offset = (page - 1) * page_size

    query = (
        sb.table("analysis_history")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range(offset, offset + page_size - 1)
    )
    if search:
        query = query.ilike("repo_name", f"%{search}%")

    data = query.execute()

    count_query = sb.table("analysis_history").select("id", count="exact").eq("user_id", user_id)
    if search:
        count_query = count_query.ilike("repo_name", f"%{search}%")
    count_data = count_query.execute()
    total = count_data.count or 0

    stats_all = sb.table("analysis_history").select("health_score, risk_level").eq("user_id", user_id).execute()
    all_rows = stats_all.data or []
    scores = [r["health_score"] for r in all_rows if r.get("health_score") is not None]
    avg_hs = round(sum(scores) / len(scores), 1) if scores else 0.0
    high_count = sum(1 for r in all_rows if r.get("risk_level") == "高危")
    med_count = sum(1 for r in all_rows if r.get("risk_level") == "中等")

    items = [
        AdminHistoryItem(
            id=r["id"],
            user_id=r["user_id"],
            repo_url=r["repo_url"],
            repo_name=r["repo_name"],
            branch=r.get("branch", "main"),
            repo_sha=r.get("repo_sha"),
            health_score=r.get("health_score"),
            quality_score=r.get("quality_score"),
            risk_level=r.get("risk_level"),
            risk_level_color=r.get("risk_level_color"),
            risk_level_bg=r.get("risk_level_bg"),
            border_color=r.get("border_color"),
            result_data=r.get("result_data"),
            langsmith_trace_id=r.get("langsmith_trace_id"),
            thread_id=r.get("thread_id"),
            created_at=r["created_at"],
        )
        for r in data.data
    ]
    return AdminHistoryListResponse(
        items=items,
        total=total,
        page=page,
        pageSize=page_size,
        stats=HistoryStats(
            total_scans=len(all_rows),
            avg_health_score=avg_hs,
            high_risk_count=high_count,
            medium_risk_count=med_count,
        ),
    )


def db_get_filtered_history(
    sb: Client,
    page: int = 1,
    page_size: int = 10,
    user_id: Optional[str] = None,
    risk_level: Optional[str] = None,
    quality_score_min: Optional[float] = None,
    quality_score_max: Optional[float] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    repo_name: Optional[str] = None,
    branch: Optional[str] = None,
    search: Optional[str] = None,
) -> AdminHistoryListResponse:
    """管理端：高级筛选分析历史（支持多条件组合）。"""
    offset = (page - 1) * page_size

    query = sb.table("analysis_history").select("*").order("created_at", desc=True)

    if user_id:
        query = query.eq("user_id", user_id)
    if risk_level:
        query = query.eq("risk_level", risk_level)
    if date_from:
        query = query.gte("created_at", f"{date_from}T00:00:00Z")
    if date_to:
        query = query.lte("created_at", f"{date_to}T23:59:59Z")
    if repo_name:
        query = query.ilike("repo_name", f"%{repo_name}%")
    if branch:
        query = query.eq("branch", branch)

    # 质量分筛选（通过 ilike 或范围过滤，health_score 存储的是数值）
    # 先执行主查询，再在内存中过滤 health_score 范围（Supabase postgrest 不支持 range on numeric via python sdk 直接）
    # 使用 gte/lte 配合 health_score 字段
    if quality_score_min is not None:
        query = query.gte("health_score", quality_score_min)
    if quality_score_max is not None:
        query = query.lte("health_score", quality_score_max)

    data = query.execute()

    # 内存中过滤 search（repo_name 模糊搜索已在服务端处理）
    filtered = data.data or []
    if search:
        import re
        pattern = re.compile(search, re.IGNORECASE)
        filtered = [r for r in filtered if pattern.search(r.get("repo_name", "")) or pattern.search(r.get("repo_url", ""))]

    total = len(filtered)
    page_items = filtered[offset:offset + page_size]

    # 统计（全局，不受筛选影响以提供参照）
    stats_all = sb.table("analysis_history").select("health_score, risk_level").execute()
    all_rows = stats_all.data or []
    scores = [r["health_score"] for r in all_rows if r.get("health_score") is not None]
    avg_hs = round(sum(scores) / len(scores), 1) if scores else 0.0
    high_count = sum(1 for r in all_rows if r.get("risk_level") == "高危")
    med_count = sum(1 for r in all_rows if r.get("risk_level") == "中等")

    items = [
        AdminHistoryItem(
            id=r["id"],
            user_id=r["user_id"],
            repo_url=r["repo_url"],
            repo_name=r["repo_name"],
            branch=r.get("branch", "main"),
            repo_sha=r.get("repo_sha"),
            health_score=r.get("health_score"),
            quality_score=r.get("quality_score"),
            risk_level=r.get("risk_level"),
            risk_level_color=r.get("risk_level_color"),
            risk_level_bg=r.get("risk_level_bg"),
            border_color=r.get("border_color"),
            result_data=r.get("result_data"),
            langsmith_trace_id=r.get("langsmith_trace_id"),
            thread_id=r.get("thread_id"),
            created_at=r["created_at"],
        )
        for r in page_items
    ]
    return AdminHistoryListResponse(
        items=items,
        total=total,
        page=page,
        pageSize=page_size,
        stats=HistoryStats(
            total_scans=len(all_rows),
            avg_health_score=avg_hs,
            high_risk_count=high_count,
            medium_risk_count=med_count,
        ),
    )


# ─── Chat ────────────────────────────────────────────────────────────────────

def create_chat_session(sb: Client, user_uuid: str, title: str | None = None) -> ChatSession:
    """创建新的 Chat Session。"""
    title = title or "新对话"
    data = (
        sb.table("chat_sessions")
        .insert({"user_id": user_uuid, "title": title})
        .execute()
    ).data[0]
    return ChatSession(
        id=data["id"],
        user_id=data["user_id"],
        title=data["title"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


def get_chat_sessions(sb: Client, user_uuid: str) -> list[ChatSession]:
    """获取用户所有 Chat Sessions（按更新时间倒序）。"""
    rows = (
        sb.table("chat_sessions")
        .select("*")
        .eq("user_id", user_uuid)
        .order("updated_at", desc=True)
        .execute()
    ).data
    return [
        ChatSession(
            id=r["id"],
            user_id=r["user_id"],
            title=r["title"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


def get_chat_messages(sb: Client, session_id: str) -> list[ChatMessage]:
    """获取某个 Session 的所有消息。"""
    rows = (
        sb.table("chat_messages")
        .select("*")
        .eq("session_id", session_id)
        .order("created_at", asc=True)
        .execute()
    ).data

    messages = []
    for r in rows:
        rag_context = None
        if r.get("rag_context"):
            raw_ctx = r["rag_context"]
            if isinstance(raw_ctx, list):
                rag_context = [RAGSource(**src) if isinstance(src, dict) else src for src in raw_ctx]
            elif isinstance(raw_ctx, str):
                import json as _json
                parsed = _json.loads(raw_ctx)
                rag_context = [RAGSource(**src) for src in parsed]

        messages.append(
            ChatMessage(
                id=r["id"],
                session_id=r["session_id"],
                role=r["role"],
                content=r["content"],
                rag_context=rag_context,
                analysis_id=r.get("analysis_id"),
                created_at=r["created_at"],
            )
        )
    return messages


def save_chat_message(
    sb: Client,
    session_id: str,
    role: str,
    content: str,
    rag_context: list[dict] | None = None,
    analysis_id: str | None = None,
) -> ChatMessage:
    """保存一条消息到数据库。"""
    import json as _json
    insert_data: dict = {
        "session_id": session_id,
        "role": role,
        "content": content,
    }
    if rag_context:
        insert_data["rag_context"] = _json.dumps(rag_context)
    if analysis_id:
        insert_data["analysis_id"] = analysis_id

    data = (
        sb.table("chat_messages")
        .insert(insert_data)
        .execute()
    ).data[0]

    rag_ctx_out = None
    if data.get("rag_context"):
        parsed = _json.loads(data["rag_context"]) if isinstance(data["rag_context"], str) else data["rag_context"]
        rag_ctx_out = [RAGSource(**src) for src in parsed]

    return ChatMessage(
        id=data["id"],
        session_id=data["session_id"],
        role=data["role"],
        content=data["content"],
        rag_context=rag_ctx_out,
        analysis_id=data.get("analysis_id"),
        created_at=data["created_at"],
    )


def delete_chat_session(sb: Client, session_id: str, user_uuid: str) -> bool:
    """删除一个 Chat Session（级联删除消息）。"""
    result = (
        sb.table("chat_sessions")
        .delete()
        .eq("id", session_id)
        .eq("user_id", user_uuid)
        .execute()
    )
    return len(result.data) > 0


def get_session_owner(sb: Client, session_id: str) -> str | None:
    """查询某个 session 的 owner user_uuid，用于权限校验。"""
    rows = (
        sb.table("chat_sessions")
        .select("user_id")
        .eq("id", session_id)
        .execute()
    ).data
    return rows[0]["user_id"] if rows else None
