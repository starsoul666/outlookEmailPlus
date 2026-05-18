from __future__ import annotations

"""
TDD C 层：号池管理 Controller / API 集成测试

覆盖 docs/TDD/2026-05-18-Issue60-号池管理UI与状态维护TDD.md §7
当前运行会失败（红）—— pool_admin route/controller 模块尚未创建。
实现 outlook_web/routes/pool_admin.py + outlook_web/controllers/pool_admin.py 后，所有用例应通过（绿）。

测试目标：
1. [MVP] 查询接口鉴权（未登录 401）
2. [MVP] 查询接口结构（items + 分页）
3. [MVP] 移入号池成功
4. [MVP] 移出号池成功
5. [MVP] claimed 拒绝普通动作
6. [增强] force_release 接口
"""

import json
import secrets
import unittest

from tests._import_app import clear_login_attempts, import_web_app_module


class PoolAdminApiBase(unittest.TestCase):
    """API 测试基类：登录 + 辅助方法"""

    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app
        cls.client = cls.app.test_client()

    def _login(self):
        """登录并返回 session cookie 标记"""
        clear_login_attempts()
        resp = self.client.post("/login", json={"password": "testpass123"})
        if resp.status_code != 200:
            raise RuntimeError(f"测试用户登录失败 ({resp.status_code}): {resp.data[:200]}")
        return "loggedin"

    def _authed_get(self, url, *, authed=True):
        headers = {}
        if authed:
            self._login()
        return self.client.get(url, headers=headers)

    def _authed_post(self, url, data=None, *, authed=True):
        headers = {"Content-Type": "application/json"}
        if authed:
            self._login()
        return self.client.post(url, data=json.dumps(data) if data else None, headers=headers)

    def _assert_json(self, resp) -> dict:
        self.assertIn("application/json", resp.content_type, f"非 JSON 响应: {resp.data[:200]}")
        return json.loads(resp.data)

    def _make_account_via_db(self, *, pool_status=None, provider="outlook"):
        """通过直接 DB 操作创建测试账号"""
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            email = f"api_admin_{secrets.token_hex(4)}@example.com"
            db.execute(
                """
                INSERT INTO accounts (email, client_id, refresh_token, status, pool_status, provider)
                VALUES (?, 'test_client', 'test_token', 'active', ?, ?)
                """,
                (email, pool_status, provider),
            )
            db.commit()
            row = db.execute("SELECT id FROM accounts WHERE email = ?", (email,)).fetchone()
            return row["id"]

    def _make_group_via_db(self, *, name_prefix="PoolAdminGroup"):
        """创建测试分组并返回 group_id"""
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            name = f"{name_prefix}_{secrets.token_hex(3)}"
            db.execute(
                "INSERT INTO groups (name, description, color, proxy_url, is_system) VALUES (?, '', '#123456', '', 0)",
                (name,),
            )
            db.commit()
            row = db.execute("SELECT id FROM groups WHERE name = ?", (name,)).fetchone()
            return row["id"]

    def _make_claimed_via_db(self, *, caller_id="bot1", task_id="task1"):
        """通过直接 DB 操作创建 claimed 账号"""
        import secrets as _secrets
        from datetime import datetime, timedelta, timezone

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            account_id = self._make_account_via_db(pool_status="available")
            now_str = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
            expires_str = (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=600)).isoformat() + "Z"
            token = "clm_" + _secrets.token_urlsafe(9)
            db.execute(
                """
                UPDATE accounts SET
                    pool_status = 'claimed',
                    claimed_by = ?,
                    claimed_at = ?,
                    lease_expires_at = ?,
                    claim_token = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (f"{caller_id}:{task_id}", now_str, expires_str, token, now_str, account_id),
            )
            db.commit()
            return account_id

    def setUp(self):
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            db.execute("DELETE FROM account_claim_logs")
            db.execute("DELETE FROM accounts")
            db.commit()


# ===== MVP: §7.1 查询接口 =====


class PoolAdminQueryApiTests(PoolAdminApiBase):
    """API 层查询接口测试"""

    def test_pool_admin_accounts_requires_login(self):
        """I-03: GET /api/pool-admin/accounts 未登录返回 401"""
        resp = self._authed_get("/api/pool-admin/accounts", authed=False)
        self.assertEqual(resp.status_code, 401, "未登录应返回 401")

    def test_pool_admin_accounts_returns_pagination_and_items(self):
        """查询接口返回合法分页结构"""
        self._make_account_via_db(pool_status="available")

        resp = self._authed_get("/api/pool-admin/accounts?in_pool=true")
        self.assertEqual(resp.status_code, 200, f"已登录应返回 200: {resp.data[:200]}")
        data = self._assert_json(resp)
        self.assertIn("items", data, "响应应包含 items 字段")
        self.assertIsInstance(data["items"], list)
        # 应包含分页相关字段（page / page_size / total 或类似）
        has_pagination = any(k in data for k in ("total", "page", "page_size", "total_pages", "has_more"))
        self.assertTrue(has_pagination, f"响应应包含分页字段: {list(data.keys())}")

    def test_pool_admin_accounts_supports_in_pool_filter(self):
        """查询接口支持 in_pool 筛选"""
        id_in = self._make_account_via_db(pool_status="available")
        id_out = self._make_account_via_db(pool_status=None)

        # 池内
        resp = self._authed_get("/api/pool-admin/accounts?in_pool=true")
        data = self._assert_json(resp)
        returned_ids = [item["id"] for item in data["items"]]
        self.assertIn(id_in, returned_ids)
        self.assertNotIn(id_out, returned_ids)

        # 池外
        resp = self._authed_get("/api/pool-admin/accounts?in_pool=false")
        data = self._assert_json(resp)
        returned_ids = [item["id"] for item in data["items"]]
        self.assertIn(id_out, returned_ids)
        self.assertNotIn(id_in, returned_ids)

    def test_pool_admin_accounts_supports_group_filter(self):
        """查询接口支持 group_id 筛选"""
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            group_a = self._make_group_via_db(name_prefix="PoolAdminA")
            group_b = self._make_group_via_db(name_prefix="PoolAdminB")

            email_a = f"api_group_a_{secrets.token_hex(4)}@example.com"
            email_b = f"api_group_b_{secrets.token_hex(4)}@example.com"
            db.execute(
                "INSERT INTO accounts (email, client_id, refresh_token, status, pool_status, provider, group_id) VALUES (?, 'test_client', 'test_token', 'active', 'available', 'outlook', ?)",
                (email_a, group_a),
            )
            db.execute(
                "INSERT INTO accounts (email, client_id, refresh_token, status, pool_status, provider, group_id) VALUES (?, 'test_client', 'test_token', 'active', 'available', 'outlook', ?)",
                (email_b, group_b),
            )
            db.commit()

            row_a = db.execute("SELECT id FROM accounts WHERE email = ?", (email_a,)).fetchone()
            row_b = db.execute("SELECT id FROM accounts WHERE email = ?", (email_b,)).fetchone()
            id_a, id_b = row_a["id"], row_b["id"]

        resp = self._authed_get(f"/api/pool-admin/accounts?in_pool=true&group_id={group_a}")
        self.assertEqual(resp.status_code, 200)
        data = self._assert_json(resp)
        returned_ids = [item["id"] for item in data["items"]]
        self.assertIn(id_a, returned_ids)
        self.assertNotIn(id_b, returned_ids)


# ===== MVP: §7.2 动作接口 =====


class PoolAdminActionApiTests(PoolAdminApiBase):
    """API 层动作接口测试"""

    def test_pool_admin_action_move_into_pool_success(self):
        """移入号池成功"""
        account_id = self._make_account_via_db(pool_status=None)

        resp = self._authed_post(f"/api/pool-admin/accounts/{account_id}/action", data={"action": "move_into_pool"})
        self.assertEqual(resp.status_code, 200, f"移入号池应返回 200: {resp.data[:200]}")
        data = self._assert_json(resp)
        self.assertTrue(data.get("success"), f"移入号池应成功: {data}")

    def test_pool_admin_action_move_out_of_pool_success(self):
        """移出号池成功"""
        account_id = self._make_account_via_db(pool_status="available")

        resp = self._authed_post(f"/api/pool-admin/accounts/{account_id}/action", data={"action": "move_out_of_pool"})
        self.assertEqual(resp.status_code, 200, f"移出号池应返回 200: {resp.data[:200]}")
        data = self._assert_json(resp)
        self.assertTrue(data.get("success"), f"移出号池应成功: {data}")

    def test_pool_admin_action_claimed_generic_action_rejected(self):
        """claimed 状态拒绝普通动作"""
        account_id = self._make_claimed_via_db()

        for action in ["move_out_of_pool", "freeze", "retire"]:
            resp = self._authed_post(f"/api/pool-admin/accounts/{account_id}/action", data={"action": action})
            data = self._assert_json(resp)
            self.assertFalse(data.get("success"), f"claimed 应拒绝 {action}: {data}")

    def test_pool_admin_action_invalid_action_rejected(self):
        """无效动作名称应被拒绝"""
        account_id = self._make_account_via_db(pool_status="available")

        resp = self._authed_post(f"/api/pool-admin/accounts/{account_id}/action", data={"action": "invalid_action"})
        data = self._assert_json(resp)
        self.assertFalse(data.get("success"), "无效动作应被拒绝")

    def test_pool_admin_action_returns_unified_structure(self):
        """I-04: 动作接口返回统一 success/message/data 结构"""
        account_id = self._make_account_via_db(pool_status=None)

        resp = self._authed_post(f"/api/pool-admin/accounts/{account_id}/action", data={"action": "move_into_pool"})
        data = self._assert_json(resp)
        self.assertIn("success", data, "响应应包含 success 字段")
        # message 或 error 至少有一个
        has_feedback = "message" in data or "error" in data or "error_code" in data
        self.assertTrue(has_feedback, f"响应应有 message/error/error_code: {list(data.keys())}")


# ===== 增强项: §7.3 强制释放接口 =====


class PoolAdminForceReleaseApiTests(PoolAdminApiBase):
    """API 层强制释放测试（增强项）"""

    def test_pool_admin_action_force_release_success_for_claimed(self):
        """claimed 账号可通过 force_release 释放"""
        account_id = self._make_claimed_via_db()

        resp = self._authed_post(f"/api/pool-admin/accounts/{account_id}/action", data={"action": "force_release"})
        data = self._assert_json(resp)
        self.assertTrue(data.get("success"), f"force_release 应成功: {data}")

    def test_pool_admin_action_force_release_rejects_non_claimed(self):
        """非 claimed 账号不能 force_release"""
        account_id = self._make_account_via_db(pool_status="available")

        resp = self._authed_post(f"/api/pool-admin/accounts/{account_id}/action", data={"action": "force_release"})
        data = self._assert_json(resp)
        self.assertFalse(data.get("success"), "非 claimed 账号应拒绝 force_release")


if __name__ == "__main__":
    unittest.main()
