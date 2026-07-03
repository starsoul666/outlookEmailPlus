from __future__ import annotations

import time
from typing import Any

from flask import jsonify

from outlook_web.repositories import overview as overview_repo
from outlook_web.security.auth import login_required

# ==================== 概览 summary 进程级 TTL 缓存 ====================
# summary 是 dashboard 首屏加载的聚合查询（6 条 SQL），
# 在单 sync worker 下频繁刷新会加重排队。30 秒 TTL 兼顾数据实时性与请求降频。
_OVERVIEW_SUMMARY_CACHE: dict | None = None
_OVERVIEW_SUMMARY_CACHE_AT: float = 0.0
_OVERVIEW_SUMMARY_CACHE_TTL: int = 30  # 秒


@login_required
def api_get_overview_summary() -> Any:
    global _OVERVIEW_SUMMARY_CACHE, _OVERVIEW_SUMMARY_CACHE_AT
    now = time.time()
    if _OVERVIEW_SUMMARY_CACHE is not None and (now - _OVERVIEW_SUMMARY_CACHE_AT) < _OVERVIEW_SUMMARY_CACHE_TTL:
        return jsonify(_OVERVIEW_SUMMARY_CACHE)
    result = overview_repo.get_overview_summary()
    _OVERVIEW_SUMMARY_CACHE = result
    _OVERVIEW_SUMMARY_CACHE_AT = now
    return jsonify(result)


@login_required
def api_get_overview_verification() -> Any:
    return jsonify(overview_repo.get_verification_stats())


@login_required
def api_get_overview_external_api() -> Any:
    return jsonify(overview_repo.get_external_api_stats())


@login_required
def api_get_overview_pool() -> Any:
    return jsonify(overview_repo.get_pool_stats())


@login_required
def api_get_overview_activity() -> Any:
    return jsonify(overview_repo.get_activity_stats())
