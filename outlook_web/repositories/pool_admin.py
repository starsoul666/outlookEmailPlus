from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional


def list_accounts(
    conn: sqlite3.Connection,
    *,
    in_pool: str = "all",
    pool_status: Optional[str] = None,
    provider: Optional[str] = None,
    group_id: Optional[int] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """号池管理专用查询：返回账号列表与分页信息。

    参数:
        in_pool: "true" | "false" | "all"
        pool_status: 精确匹配池状态（如 claimed / available / cooldown / used / frozen / retired）
        provider: 精确匹配 provider
        group_id: 精确匹配 group_id
        search: 模糊匹配 email / remark / email_domain
        page: 页码（从 1 开始）
        page_size: 每页条数
    """
    where_clauses: List[str] = []
    params: List[Any] = []

    normalized_in_pool = str(in_pool or "all").strip().lower()
    if normalized_in_pool == "true":
        where_clauses.append("a.pool_status IS NOT NULL")
    elif normalized_in_pool == "false":
        where_clauses.append("a.pool_status IS NULL")

    if pool_status:
        where_clauses.append("a.pool_status = ?")
        params.append(pool_status)

    if provider:
        where_clauses.append("a.provider = ?")
        params.append(provider)

    if group_id is not None:
        where_clauses.append("a.group_id = ?")
        params.append(group_id)

    normalized_search = str(search or "").strip().lower()
    if normalized_search:
        like_value = f"%{normalized_search}%"
        where_clauses.append(
            """
            (
                LOWER(COALESCE(a.email, '')) LIKE ?
                OR LOWER(COALESCE(a.remark, '')) LIKE ?
                OR LOWER(COALESCE(a.email_domain, '')) LIKE ?
            )
            """
        )
        params.extend([like_value, like_value, like_value])

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    # 总数
    total_row = conn.execute(
        f"""
        SELECT COUNT(*) AS total_count
        FROM accounts a
        {where_sql}
        """,
        params,
    ).fetchone()
    total_count = int(total_row["total_count"] or 0) if total_row else 0

    normalized_page = max(1, int(page or 1))
    normalized_page_size = max(1, int(page_size or 50))
    total_pages = (total_count + normalized_page_size - 1) // normalized_page_size if total_count > 0 else 1
    effective_page = min(normalized_page, total_pages)
    offset = (effective_page - 1) * normalized_page_size

    rows = conn.execute(
        f"""
        SELECT
            a.id,
            a.email,
            a.provider,
            a.account_type,
            a.status,
            a.pool_status,
            a.claimed_by,
            a.claimed_at,
            a.lease_expires_at,
            a.last_result,
            a.last_result_detail,
            a.group_id,
            a.remark,
            a.email_domain,
            a.created_at,
            a.updated_at,
            g.name AS group_name,
            g.color AS group_color
        FROM accounts a
        LEFT JOIN groups g ON a.group_id = g.id
        {where_sql}
        ORDER BY a.updated_at DESC, a.id DESC
        LIMIT ? OFFSET ?
        """,
        [*params, normalized_page_size, offset],
    ).fetchall()

    items: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        # 确保前端拿到的是 None 而不是空字符串（保持语义一致）
        for key in ("pool_status", "claimed_by", "claimed_at", "lease_expires_at", "last_result", "last_result_detail"):
            if item.get(key) == "":
                item[key] = None
        items.append(item)

    return {
        "items": items,
        "total": total_count,
        "page": effective_page,
        "page_size": normalized_page_size,
        "total_pages": total_pages,
    }


def get_account_pool_status(conn: sqlite3.Connection, account_id: int) -> Optional[str]:
    """返回账号当前 pool_status（None 表示池外）。"""
    row = conn.execute(
        "SELECT pool_status FROM accounts WHERE id = ?",
        (account_id,),
    ).fetchone()
    if row is None:
        return None
    return row["pool_status"]


def update_pool_status(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    new_pool_status: Optional[str],
) -> None:
    """更新账号 pool_status，同时更新 updated_at。

    当 new_pool_status 为 None（移出号池）时，顺带清理 claim 相关字段。
    """
    from datetime import datetime, timezone

    now_str = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    if new_pool_status is None:
        conn.execute(
            """
            UPDATE accounts SET
                pool_status = NULL,
                claimed_by = NULL,
                claimed_at = NULL,
                lease_expires_at = NULL,
                claim_token = NULL,
                claimed_project_key = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (now_str, account_id),
        )
    else:
        conn.execute(
            """
            UPDATE accounts SET
                pool_status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (new_pool_status, now_str, account_id),
        )
    conn.commit()


def force_release(conn: sqlite3.Connection, *, account_id: int) -> None:
    """强制释放 claimed 账号：将状态置为 available，并清空 claim 上下文。

    调用方（Service 层）应确保当前状态为 claimed。
    """
    from datetime import datetime, timezone

    now_str = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    conn.execute(
        """
        UPDATE accounts SET
            pool_status = 'available',
            claimed_by = NULL,
            claimed_at = NULL,
            lease_expires_at = NULL,
            claim_token = NULL,
            claimed_project_key = NULL,
            updated_at = ?
        WHERE id = ?
        """,
        (now_str, account_id),
    )
    conn.commit()
