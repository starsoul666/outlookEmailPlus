from __future__ import annotations

from flask import Blueprint

from outlook_web.controllers import pool_admin as pool_admin_controller


def create_blueprint() -> Blueprint:
    bp = Blueprint("pool_admin", __name__)
    bp.add_url_rule("/api/pool-admin/accounts", view_func=pool_admin_controller.api_list_accounts, methods=["GET"])
    bp.add_url_rule(
        "/api/pool-admin/accounts/<int:account_id>/action",
        view_func=pool_admin_controller.api_account_action,
        methods=["POST"],
    )
    return bp
