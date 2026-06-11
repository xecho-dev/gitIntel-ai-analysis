"""
GitIntel 数据库操作层（asyncpg）
替代原先依赖 Supabase Python SDK 的实现，使用原生 PostgreSQL 驱动。
"""
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

import asyncpg

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

logger = logging.getLogger("gitintel")


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
    data = result_data

    if "final_result" in data:
        logger.info(f"[_extract_repo_sha] 解包 final_result，原始 keys={list(data.keys())}")
        data = data["final_result"]
        logger.info(f"[_extract_repo_sha] 解包后 keys={list(data.keys())}")
    else:
        logger.info(f"[_extract_repo_sha] 无 final_result，原始 keys={list(data.keys())}")

    repo_loader = data.get("repo_loader", {})
    if isinstance(repo_loader, dict):
        sha = repo_loader.get("repo_sha")
        return sha
    logger.warning(f"[_extract_repo_sha] 未找到 repo_loader，data keys={list(data.keys())}")
    return None


async def save_analysis(
    pool: asyncpg.Pool,
    auth_user_id: str,
    repo_url: str,
    branch: str,
    result_data: dict,
    langsmith_trace_id: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> SaveAnalysisResponse:
    """保存一次分析结果，返回新记录的 id。"""
    async with pool.acquire() as conn:
        user_row = await conn.fetchrow(
            "SELECT id FROM users WHERE auth_user_id = $1", auth_user_id
        )
        if user_row is None:
            raise ValueError(f"User not found for auth_user_id: {auth_user_id}")
        user_uuid = user_row["id"]

        metrics = _derive_history_metrics(result_data)
        repo_sha = _extract_repo_sha(result_data)
        repo_name = repo_url.rstrip("/").split("/")[-1]

        row = await conn.fetchrow(
            """
            INSERT INTO analysis_history
                (user_id, repo_url, repo_name, branch, repo_sha, result_data,
                 health_score, quality_score, risk_level, risk_level_color,
                 risk_level_bg, border_color, langsmith_trace_id, thread_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            RETURNING id, created_at
            """,
            user_uuid,
            repo_url,
            repo_name,
            branch,
            repo_sha,
            result_data,
            metrics["health_score"],
            metrics["quality_score"],
            metrics["risk_level"],
            metrics["risk_level_color"],
            metrics["risk_level_bg"],
            metrics["border_color"],
            langsmith_trace_id,
            thread_id,
        )
        return SaveAnalysisResponse(id=str(row["id"]), created_at=row["created_at"].isoformat())


async def get_history(
    pool: asyncpg.Pool,
    auth_user_id: str,
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
) -> HistoryListResponse:
    """分页查询用户的分析历史。"""
    offset = (page - 1) * page_size

    async with pool.acquire() as conn:
        user_row = await conn.fetchrow(
            "SELECT id FROM users WHERE auth_user_id = $1", auth_user_id
        )
        if user_row is None:
            return HistoryListResponse(
                items=[],
                total=0,
                page=page,
                page_size=page_size,
                stats=HistoryStats(
                    total_scans=0,
                    avg_health_score=0,
                    high_risk_count=0,
                    medium_risk_count=0,
                ),
            )
        user_uuid = user_row["id"]

        if search:
            rows = await conn.fetch(
                """
                SELECT * FROM analysis_history
                WHERE user_id = $1 AND repo_name ILIKE $2
                ORDER BY created_at DESC
                LIMIT $3 OFFSET $4
                """,
                user_uuid,
                f"%{search}%",
                page_size,
                offset,
            )
            count_row = await conn.fetchrow(
                """
                SELECT COUNT(*) as cnt FROM analysis_history
                WHERE user_id = $1 AND repo_name ILIKE $2
                """,
                user_uuid,
                f"%{search}%",
            )
            total = count_row["cnt"]
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM analysis_history
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                user_uuid,
                page_size,
                offset,
            )
            count_row = await conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM analysis_history WHERE user_id = $1",
                user_uuid,
            )
            total = count_row["cnt"]

        stats_rows = await conn.fetch(
            "SELECT health_score, risk_level FROM analysis_history WHERE user_id = $1",
            user_uuid,
        )

    scores = [r["health_score"] for r in stats_rows if r.get("health_score") is not None]
    avg_hs = round(sum(scores) / len(scores), 1) if scores else 0
    high_count = sum(1 for r in stats_rows if r.get("risk_level") == "高危")
    med_count = sum(1 for r in stats_rows if r.get("risk_level") == "中等")

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
            created_at=r["created_at"].isoformat(),
        )
        for r in rows
    ]

    return HistoryListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        stats=HistoryStats(
            total_scans=len(stats_rows),
            avg_health_score=avg_hs,
            high_risk_count=high_count,
            medium_risk_count=med_count,
        ),
    )


async def delete_analysis(
    pool: asyncpg.Pool,
    auth_user_id: str,
    history_id: str,
) -> bool:
    """删除指定历史记录。"""
    async with pool.acquire() as conn:
        user_row = await conn.fetchrow(
            "SELECT id FROM users WHERE auth_user_id = $1", auth_user_id
        )
        if user_row is None:
            return False
        user_uuid = user_row["id"]

        result = await conn.execute(
            """
            DELETE FROM analysis_history
            WHERE id = $1 AND user_id = $2
            """,
            uuid.UUID(history_id),
            user_uuid,
        )
        return result != "DELETE 0"


async def get_sha_cached_analysis(
    pool: asyncpg.Pool,
    auth_user_id: str,
    repo_url: str,
    branch: str,
    repo_sha: str,
) -> Optional[dict]:
    """
    查询最近一次分析结果，条件：repo_url + branch + repo_sha 完全相同。
    用于智能缓存：若 SHA 未变，直接复用已有结果。
    """
    async with pool.acquire() as conn:
        user_row = await conn.fetchrow(
            "SELECT id FROM users WHERE auth_user_id = $1", auth_user_id
        )
        if user_row is None:
            return None
        user_uuid = user_row["id"]

        row = await conn.fetchrow(
            """
            SELECT result_data, repo_sha, created_at FROM analysis_history
            WHERE user_id = $1 AND repo_url = $2 AND branch = $3 AND repo_sha = $4
            ORDER BY created_at DESC
            LIMIT 1
            """,
            user_uuid,
            repo_url,
            branch,
            repo_sha,
        )
        if row is None:
            return None
        return row["result_data"]


async def upsert_user(pool: asyncpg.Pool, auth_user_id: str, payload: dict) -> UserProfile:
    """
    Upsert GitHub 用户信息。

    去重策略：
    1. 先按 auth_user_id 查找（稳定路径）
    2. 如果找不到，再按 login 查找：
       - 找到 → 更新旧记录的 auth_user_id（复用 users.id，历史记录不受影响）
       - 未找到 → 正常创建新记录
    """
    async with pool.acquire() as conn:
        payload_clean = {k: v for k, v in payload.items() if v is not None and v != ""}
        payload_clean["auth_user_id"] = auth_user_id
        payload_clean["updated_at"] = datetime.now(timezone.utc)

        existing = await conn.fetchrow(
            "SELECT * FROM users WHERE auth_user_id = $1", auth_user_id
        )

        if existing is not None:
            await conn.execute(
                """
                UPDATE users SET
                    github_id = COALESCE($2, github_id),
                    login = $3,
                    email = COALESCE($4, email),
                    avatar_url = $5,
                    name = $6,
                    bio = $7,
                    company = $8,
                    location = $9,
                    blog = $10,
                    public_repos = COALESCE($11, public_repos),
                    followers = COALESCE($12, followers),
                    following = COALESCE($13, following),
                    updated_at = $14
                WHERE auth_user_id = $1
                """,
                auth_user_id,
                payload_clean.get("github_id"),
                payload_clean.get("login", ""),
                payload_clean.get("email"),
                payload_clean.get("avatar_url"),
                payload_clean.get("name"),
                payload_clean.get("bio"),
                payload_clean.get("company"),
                payload_clean.get("location"),
                payload_clean.get("blog"),
                payload_clean.get("public_repos"),
                payload_clean.get("followers"),
                payload_clean.get("following"),
                payload_clean["updated_at"],
            )
        else:
            login_val = payload_clean.get("login")
            if login_val:
                same_login = await conn.fetchrow(
                    "SELECT id, auth_user_id FROM users WHERE login = $1", login_val
                )
                if same_login is not None:
                    await conn.execute(
                        "UPDATE users SET auth_user_id = $1 WHERE id = $2",
                        auth_user_id,
                        same_login["id"],
                    )
                    await conn.execute(
                        """
                        UPDATE users SET
                            github_id = COALESCE($2, github_id),
                            email = COALESCE($3, email),
                            avatar_url = $4,
                            name = $5,
                            bio = $6,
                            company = $7,
                            location = $8,
                            blog = $9,
                            public_repos = COALESCE($10, public_repos),
                            followers = COALESCE($11, followers),
                            following = COALESCE($12, following),
                            updated_at = $13
                        WHERE auth_user_id = $1
                        """,
                        auth_user_id,
                        payload_clean.get("github_id"),
                        payload_clean.get("email"),
                        payload_clean.get("avatar_url"),
                        payload_clean.get("name"),
                        payload_clean.get("bio"),
                        payload_clean.get("company"),
                        payload_clean.get("location"),
                        payload_clean.get("blog"),
                        payload_clean.get("public_repos"),
                        payload_clean.get("followers"),
                        payload_clean.get("following"),
                        payload_clean["updated_at"],
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO users
                            (auth_user_id, github_id, login, email, avatar_url,
                             name, bio, company, location, blog,
                             public_repos, followers, following, updated_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                        """,
                        auth_user_id,
                        payload_clean.get("github_id"),
                        payload_clean.get("login", ""),
                        payload_clean.get("email"),
                        payload_clean.get("avatar_url"),
                        payload_clean.get("name"),
                        payload_clean.get("bio"),
                        payload_clean.get("company"),
                        payload_clean.get("location"),
                        payload_clean.get("blog"),
                        payload_clean.get("public_repos"),
                        payload_clean.get("followers"),
                        payload_clean.get("following"),
                        payload_clean["updated_at"],
                    )
            else:
                await conn.execute(
                    """
                    INSERT INTO users (auth_user_id, login, updated_at)
                    VALUES ($1, $2, $3)
                    """,
                    auth_user_id,
                    auth_user_id.split("-")[0] if "-" in auth_user_id else auth_user_id,
                    payload_clean["updated_at"],
                )

        r = await conn.fetchrow(
            "SELECT * FROM users WHERE auth_user_id = $1", auth_user_id
        )
        if r is None:
            raise RuntimeError("Upsert user failed: user not found after upsert")

        return UserProfile(
            id=str(r["id"]),
            auth_user_id=str(r["auth_user_id"]),
            github_id=r.get("github_id"),
            login=r["login"],
            email=r.get("email"),
            avatar_url=r.get("avatar_url"),
            name=r.get("name"),
            bio=r.get("bio"),
            company=r.get("company"),
            location=r.get("location"),
            blog=r.get("blog"),
            public_repos=r["public_repos"] or 0,
            followers=r["followers"] or 0,
            following=r["following"] or 0,
            created_at=r["created_at"].isoformat(),
            updated_at=r.get("updated_at", r["created_at"]).isoformat()
            if r.get("updated_at")
            else r["created_at"].isoformat(),
        )


async def get_user_profile(pool: asyncpg.Pool, auth_user_id: str) -> Optional[UserProfile]:
    """获取用户资料。"""
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT * FROM users WHERE auth_user_id = $1", auth_user_id
        )
        if r is None:
            return None
        return UserProfile(
            id=str(r["id"]),
            auth_user_id=str(r["auth_user_id"]),
            github_id=r.get("github_id"),
            login=r["login"],
            email=r.get("email"),
            avatar_url=r.get("avatar_url"),
            name=r.get("name"),
            bio=r.get("bio"),
            company=r.get("company"),
            location=r.get("location"),
            blog=r.get("blog"),
            public_repos=r["public_repos"] or 0,
            followers=r["followers"] or 0,
            following=r["following"] or 0,
            created_at=r["created_at"].isoformat(),
            updated_at=r.get("updated_at", r["created_at"]).isoformat()
            if r.get("updated_at")
            else r["created_at"].isoformat(),
        )


async def get_user_uuid(pool: asyncpg.Pool, auth_user_id: str) -> Optional[str]:
    """根据 auth_user_id 查找用户的 uuid。"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE auth_user_id = $1", auth_user_id
        )
        if row is None:
            return None
        return str(row["id"])


# ─── 管理端（Admin）数据库操作 ─────────────────────────────────────────────────


async def db_get_overview_stats(pool: asyncpg.Pool) -> AdminOverviewResponse:
    """获取全站概览统计数据。"""
    async with pool.acquire() as conn:
        user_count_row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM users"
        )
        total_users = user_count_row["cnt"]

        all_history = await conn.fetch(
            "SELECT health_score, risk_level, created_at FROM analysis_history"
        )
        total_analysis = len(all_history)

        today = datetime.now(timezone.utc).date().isoformat()
        today_row = await conn.fetchrow(
            """
            SELECT COUNT(*) as cnt FROM analysis_history
            WHERE created_at >= $1
            """,
            f"{today}T00:00:00Z",
        )
        today_analysis = today_row["cnt"]

        scores = [r["health_score"] for r in all_history if r.get("health_score") is not None]
        avg_hs = round(sum(scores) / len(scores), 1) if scores else 0.0
        high_risk_count = sum(1 for r in all_history if r.get("risk_level") == "高危")
        medium_risk_count = sum(1 for r in all_history if r.get("risk_level") == "中等")

        return AdminOverviewResponse(
            total_users=total_users,
            total_analysis=total_analysis,
            today_analysis=today_analysis,
            avg_health_score=avg_hs,
            high_risk_count=high_risk_count,
            medium_risk_count=medium_risk_count,
        )


async def db_get_all_users(
    pool: asyncpg.Pool,
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
) -> AdminUserListResponse:
    """管理端：获取全部用户列表（分页，支持按 login/email 搜索）。"""
    offset = (page - 1) * page_size

    async with pool.acquire() as conn:
        if search:
            rows = await conn.fetch(
                """
                SELECT * FROM users
                WHERE login ILIKE $1 OR email ILIKE $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                f"%{search}%",
                page_size,
                offset,
            )
            count_row = await conn.fetchrow(
                """
                SELECT COUNT(*) as cnt FROM users
                WHERE login ILIKE $1 OR email ILIKE $1
                """,
                f"%{search}%",
            )
            total = count_row["cnt"]
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM users
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
                """,
                page_size,
                offset,
            )
            count_row = await conn.fetchrow("SELECT COUNT(*) as cnt FROM users")
            total = count_row["cnt"]

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
            created_at=r["created_at"].isoformat(),
            updated_at=r.get("updated_at", r["created_at"]).isoformat()
            if r.get("updated_at")
            else r["created_at"].isoformat(),
        )
        for r in rows
    ]
    return AdminUserListResponse(items=items, total=total, page=page, pageSize=page_size)


async def db_update_user(pool: asyncpg.Pool, user_id: str, data: dict) -> bool:
    """管理端：更新指定用户信息（支持禁用/启用等）。"""
    async with pool.acquire() as conn:
        update_fields = {
            k: v
            for k, v in data.items()
            if k not in ("id", "auth_user_id", "created_at")
        }
        update_fields["updated_at"] = datetime.utcnow().isoformat()

        if not update_fields:
            return False

        set_clauses = [f"{k} = ${i+2}" for i, k in enumerate(update_fields.keys())]
        set_sql = ", ".join(set_clauses)
        values = list(update_fields.values())
        values.append(uuid.UUID(user_id))

        result = await conn.execute(
            f"UPDATE users SET {set_sql} WHERE id = ${len(values)}",
            *values,
        )
        return result != "UPDATE 0"


async def db_get_all_history(
    pool: asyncpg.Pool,
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
) -> AdminHistoryListResponse:
    """管理端：获取全站分析历史（分页）。"""
    offset = (page - 1) * page_size

    async with pool.acquire() as conn:
        if search:
            rows = await conn.fetch(
                """
                SELECT * FROM analysis_history
                WHERE repo_name ILIKE $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                f"%{search}%",
                page_size,
                offset,
            )
            count_row = await conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM analysis_history WHERE repo_name ILIKE $1",
                f"%{search}%",
            )
            total = count_row["cnt"]
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM analysis_history
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
                """,
                page_size,
                offset,
            )
            count_row = await conn.fetchrow("SELECT COUNT(*) as cnt FROM analysis_history")
            total = count_row["cnt"]

        stats_all = await conn.fetch(
            "SELECT health_score, risk_level FROM analysis_history"
        )
        all_rows = stats_all
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
            created_at=r["created_at"].isoformat(),
        )
        for r in rows
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


async def db_delete_history_by_admin(pool: asyncpg.Pool, record_id: str) -> bool:
    """管理端：删除指定分析记录（不校验用户权限）。"""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM analysis_history WHERE id = $1",
            uuid.UUID(record_id),
        )
        return result != "DELETE 0"


async def db_get_history_by_id(pool: asyncpg.Pool, record_id: str) -> Optional[AdminHistoryItem]:
    """根据 record_id 获取单条分析历史记录。"""
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT * FROM analysis_history WHERE id = $1",
            uuid.UUID(record_id),
        )
        if r is None:
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
            created_at=r["created_at"].isoformat(),
        )


async def db_get_user_by_id(pool: asyncpg.Pool, user_id: str) -> Optional[AdminUserItem]:
    """根据 user_id（UUID）获取用户信息。"""
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT * FROM users WHERE id = $1",
            uuid.UUID(user_id),
        )
        if r is None:
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
            created_at=r["created_at"].isoformat(),
            updated_at=r.get("updated_at", r["created_at"]).isoformat()
            if r.get("updated_at")
            else r["created_at"].isoformat(),
        )


async def db_get_user_analysis_history(
    pool: asyncpg.Pool,
    user_id: str,
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
) -> AdminHistoryListResponse:
    """获取指定用户的分析历史（分页）。"""
    offset = (page - 1) * page_size
    user_uuid = uuid.UUID(user_id)

    async with pool.acquire() as conn:
        if search:
            rows = await conn.fetch(
                """
                SELECT * FROM analysis_history
                WHERE user_id = $1 AND repo_name ILIKE $2
                ORDER BY created_at DESC
                LIMIT $3 OFFSET $4
                """,
                user_uuid,
                f"%{search}%",
                page_size,
                offset,
            )
            count_row = await conn.fetchrow(
                """
                SELECT COUNT(*) as cnt FROM analysis_history
                WHERE user_id = $1 AND repo_name ILIKE $2
                """,
                user_uuid,
                f"%{search}%",
            )
            total = count_row["cnt"]
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM analysis_history
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                user_uuid,
                page_size,
                offset,
            )
            count_row = await conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM analysis_history WHERE user_id = $1",
                user_uuid,
            )
            total = count_row["cnt"]

        stats_all = await conn.fetch(
            "SELECT health_score, risk_level FROM analysis_history WHERE user_id = $1",
            user_uuid,
        )
        all_rows = stats_all
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
            created_at=r["created_at"].isoformat(),
        )
        for r in rows
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


async def db_get_filtered_history(
    pool: asyncpg.Pool,
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

    conditions = []
    params: list = []
    param_idx = 1

    def add_cond(sql_snippet: str, *vals: any):
        nonlocal param_idx
        conditions.append(sql_snippet)
        for v in vals:
            params.append(v)
            param_idx += 1

    if user_id:
        add_cond(f"user_id = ${param_idx}", uuid.UUID(user_id))
    if risk_level:
        add_cond(f"risk_level = ${param_idx}", risk_level)
    if quality_score_min is not None:
        add_cond(f"health_score >= ${param_idx}", quality_score_min)
    if quality_score_max is not None:
        add_cond(f"health_score <= ${param_idx}", quality_score_max)
    if date_from:
        add_cond(f"created_at >= ${param_idx}", f"{date_from}T00:00:00Z")
    if date_to:
        add_cond(f"created_at <= ${param_idx}", f"{date_to}T23:59:59Z")
    if repo_name:
        add_cond(f"repo_name ILIKE ${param_idx}", f"%{repo_name}%")
    if branch:
        add_cond(f"branch = ${param_idx}", branch)

    where_sql = " AND ".join(conditions) if conditions else "1=1"

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT * FROM analysis_history
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """,
            *params,
            page_size,
            offset,
        )

        count_row = await conn.fetchrow(
            f"SELECT COUNT(*) as cnt FROM analysis_history WHERE {where_sql}",
            *params,
        )
        total = count_row["cnt"]

        stats_all = await conn.fetch(
            "SELECT health_score, risk_level FROM analysis_history"
        )
        all_rows = stats_all
        scores = [r["health_score"] for r in all_rows if r.get("health_score") is not None]
        avg_hs = round(sum(scores) / len(scores), 1) if scores else 0.0
        high_count = sum(1 for r in all_rows if r.get("risk_level") == "高危")
        med_count = sum(1 for r in all_rows if r.get("risk_level") == "中等")

    filtered = list(rows)
    if search:
        import re
        pattern = re.compile(search, re.IGNORECASE)
        filtered = [
            r
            for r in filtered
            if pattern.search(r.get("repo_name", "") or "")
            or pattern.search(r.get("repo_url", "") or "")
        ]

    total = len(filtered)
    page_items = filtered[offset : offset + page_size]

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
            created_at=r["created_at"].isoformat(),
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


# ─── Chat ─────────────────────────────────────────────────────────────────────


async def create_chat_session(
    pool: asyncpg.Pool,
    user_uuid: str,
    title: Optional[str] = None,
) -> ChatSession:
    """创建新的 Chat Session。"""
    title = title or "新对话"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO chat_sessions (user_id, title)
            VALUES ($1, $2)
            RETURNING id, user_id, title, created_at, updated_at
            """,
            uuid.UUID(user_uuid),
            title,
        )
        return ChatSession(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            created_at=row["created_at"].isoformat(),
            updated_at=row["updated_at"].isoformat(),
        )


async def get_chat_sessions(pool: asyncpg.Pool, user_uuid: str) -> list[ChatSession]:
    """获取用户所有 Chat Sessions（按更新时间倒序）。"""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM chat_sessions
            WHERE user_id = $1
            ORDER BY updated_at DESC
            """,
            uuid.UUID(user_uuid),
        )
        return [
            ChatSession(
                id=r["id"],
                user_id=r["user_id"],
                title=r["title"],
                created_at=r["created_at"].isoformat(),
                updated_at=r["updated_at"].isoformat(),
            )
            for r in rows
        ]


def _normalize_rag_source(src: dict) -> dict:
    """Normalize old DB records that may be missing score/priority/content/repo_url."""
    defaults = {
        "score": src.get("relevance", src.get("score", 0.0)),
        "priority": src.get("priority", "medium"),
        "content": src.get("content") or src.get("preview", ""),
        "repo_url": src.get("repo_url", ""),
    }
    return {**defaults, **src}


async def get_chat_messages(pool: asyncpg.Pool, session_id: str) -> list[ChatMessage]:
    """获取某个 Session 的所有消息。"""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM chat_messages
            WHERE session_id = $1
            ORDER BY created_at ASC
            """,
            uuid.UUID(session_id),
        )

        messages = []
        for r in rows:
            rag_context = None
            raw_ctx = r.get("rag_context")
            if raw_ctx is not None:
                if isinstance(raw_ctx, list):
                    rag_context = [
                        RAGSource(**_normalize_rag_source(src))
                        if isinstance(src, dict)
                        else src
                        for src in raw_ctx
                    ]
                elif isinstance(raw_ctx, str):
                    parsed = json.loads(raw_ctx)
                    rag_context = [
                        RAGSource(**_normalize_rag_source(src)) for src in parsed
                    ]

            messages.append(
                ChatMessage(
                    id=r["id"],
                    session_id=r["session_id"],
                    role=r["role"],
                    content=r["content"],
                    rag_context=rag_context,
                    analysis_id=r.get("analysis_id"),
                    created_at=r["created_at"].isoformat(),
                )
            )
        return messages


async def save_chat_message(
    pool: asyncpg.Pool,
    session_id: str,
    role: str,
    content: str,
    rag_context: Optional[list[dict]] = None,
    analysis_id: Optional[str] = None,
) -> ChatMessage:
    """保存一条消息到数据库。"""
    rag_context_json = json.dumps(rag_context) if rag_context else None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO chat_messages (session_id, role, content, rag_context, analysis_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            uuid.UUID(session_id),
            role,
            content,
            rag_context_json,
            uuid.UUID(analysis_id) if analysis_id else None,
        )

        rag_ctx_out = None
        raw_ctx = row.get("rag_context")
        if raw_ctx:
            parsed = json.loads(raw_ctx) if isinstance(raw_ctx, str) else raw_ctx
            rag_ctx_out = [RAGSource(**_normalize_rag_source(src)) for src in parsed]

        return ChatMessage(
            id=row["id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            rag_context=rag_ctx_out,
            analysis_id=row.get("analysis_id"),
            created_at=row["created_at"].isoformat(),
        )


async def delete_chat_session(
    pool: asyncpg.Pool,
    session_id: str,
    user_uuid: str,
) -> bool:
    """删除一个 Chat Session（级联删除消息）。"""
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM chat_sessions
            WHERE id = $1 AND user_id = $2
            """,
            uuid.UUID(session_id),
            uuid.UUID(user_uuid),
        )
        return result != "DELETE 0"


async def get_session_owner(pool: asyncpg.Pool, session_id: str) -> Optional[str]:
    """查询某个 session 的 owner user_uuid，用于权限校验。"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM chat_sessions WHERE id = $1",
            uuid.UUID(session_id),
        )
        return str(row["user_id"]) if row else None
