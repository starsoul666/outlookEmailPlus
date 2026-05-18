from __future__ import annotations

from typing import Any

from flask import jsonify, request

from outlook_web.services import pool_admin as pool_admin_svc
from outlook_web.security.auth import login_required


@login_required
def api_list_accounts() -> Any:
    """GET /api/pool-admin/accounts"""
    in_pool = request.args.get("in_pool", "all")
    pool_status = request.args.get("pool_status") or None
    provider = request.args.get("provider") or None
    group_id_raw = request.args.get("group_id")
    search = request.args.get("search") or None
    page_raw = request.args.get("page", "1")
    page_size_raw = request.args.get("page_size", "50")

    group_id = None
    if group_id_raw is not None:
        try:
            group_id = int(group_id_raw)
        except ValueError:
            group_id = None

    try:
        page = max(1, int(page_raw))
    except ValueError:
        page = 1

    try:
        page_size = max(1, min(200, int(page_size_raw)))
    except ValueError:
        page_size = 50

    result = pool_admin_svc.list_accounts(
        in_pool=in_pool,
        pool_status=pool_status,
        provider=provider,
        group_id=group_id,
        search=search,
        page=page,
        page_size=page_size,
    )
    return jsonify(result)


@login_required
def api_account_action(account_id: int) -> Any:
    """POST /api/pool-admin/accounts/<id>/action"""
    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "").strip().lower()

    if not action:
        return jsonify({"success": False, "message": "缺少 action 参数", "error_code": "ACTION_REQUIRED", "data": {}}), 400

    # 动作名标准化：允许下划线/中划线混用
    action = action.replace("-", "_")

    # 从 session 读取操作者（如有）
    operator = None
    try:
        from flask import session

        operator = session.get("operator") or session.get("user") or None
    except Exception:
        pass

    result = pool_admin_svc.apply_action(account_id, action, operator=operator)
    if result.get("success"):
        return jsonify(result)
    # 失败时根据错误码返回合适的状态码
    error_code = result.get("error_code", "")
    status_code = 400
    if error_code == "ACCOUNT_NOT_FOUND":
        status_code = 404
    elif error_code == "CLAIMED_PROTECTED":
        status_code = 409
    elif error_code == "INVALID_STATE_TRANSITION":
        status_code = 409
    elif error_code == "NOT_CLAIMED":
        status_code = 409
    return jsonify(result), status_code
