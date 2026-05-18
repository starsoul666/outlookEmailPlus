from __future__ import annotations

import json
import secrets
import unittest

from tests._import_app import import_web_app_module


class Issue60CompatibilityRegressionTests(unittest.TestCase):
    """Issue #60 兼容性回归：
    1) GET /api/accounts 旧语义不被污染
    2) /api/external/pool/* 关键链路可用
    3) overview pool 接口可用
    """

    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app
        cls.client = cls.app.test_client()

    def setUp(self):
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.repositories import settings as settings_repo

            db = get_db()
            db.execute("DELETE FROM account_claim_logs")
            db.execute("DELETE FROM account_project_usage")
            db.execute("DELETE FROM accounts")
            db.execute("DELETE FROM external_api_keys")
            db.execute("DELETE FROM external_api_rate_limits")
            db.execute("DELETE FROM verification_extract_logs")
            db.commit()

            settings_repo.set_setting("external_api_key", "abc123")
            settings_repo.set_setting("pool_external_enabled", "true")
            settings_repo.set_setting("external_api_public_mode", "false")
            settings_repo.set_setting("external_api_ip_whitelist", "[]")
            settings_repo.set_setting("external_api_rate_limit_per_minute", "60")
            settings_repo.set_setting("external_api_disable_pool_claim_random", "false")
            settings_repo.set_setting("external_api_disable_pool_claim_release", "false")
            settings_repo.set_setting("external_api_disable_pool_claim_complete", "false")
            settings_repo.set_setting("external_api_disable_pool_stats", "false")

    def _login(self) -> None:
        resp = self.client.post("/login", json={"password": "testpass123"})
        self.assertEqual(resp.status_code, 200)

    @staticmethod
    def _auth_headers() -> dict[str, str]:
        return {"X-API-Key": "abc123"}

    def _get_authed(self, url: str):
        """对 /api/overview/* 显式带 Cookie 头，避免测试客户端为了 overview 路径清空内部 cookie。"""
        return self.client.get(url, headers={"Cookie": "loggedin"})

    def _make_account(self, *, group_id: int | None = None, pool_status: str | None = None) -> int:
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            email = f"issue60_reg_{secrets.token_hex(4)}@example.com"
            db.execute(
                """
                INSERT INTO accounts (email, client_id, refresh_token, status, group_id, pool_status, provider, account_type)
                VALUES (?, 'test_client', 'test_token', 'active', ?, ?, 'outlook', 'outlook')
                """,
                (email, group_id, pool_status),
            )
            db.commit()
            row = db.execute("SELECT id FROM accounts WHERE email = ?", (email,)).fetchone()
            return int(row["id"])

    def _make_group(self, name_suffix: str = "") -> int:
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            name = f"Issue60Compat-{name_suffix or secrets.token_hex(3)}"
            db.execute(
                "INSERT INTO groups (name, description, color, proxy_url, is_system) VALUES (?, '', '#123456', '', 0)",
                (name,),
            )
            db.commit()
            row = db.execute("SELECT id FROM groups WHERE name = ?", (name,)).fetchone()
            return int(row["id"])

    def test_get_accounts_still_returns_legacy_shape(self):
        """GET /api/accounts 仍返回 accounts + pagination，且不会混入 pool-admin 语义字段"""
        self._login()
        gid = self._make_group("legacy-shape")
        self._make_account(group_id=gid, pool_status="available")

        resp = self.client.get(f"/api/accounts?group_id={gid}&page=1&page_size=20")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)

        self.assertTrue(data.get("success"))
        self.assertIn("accounts", data)
        self.assertIn("pagination", data)
        self.assertNotIn("items", data, "旧接口不应变成 pool-admin 风格")

        if data.get("accounts"):
            first = data["accounts"][0]
            self.assertIn("email", first)
            self.assertNotIn("claimed_by", first, "旧接口不应泄露 pool-admin claim 字段")

    def test_external_pool_contract_still_works(self):
        """/api/external/pool/* 核心链路仍可用"""
        self._make_account(pool_status="available")

        stats_resp = self.client.get("/api/external/pool/stats", headers=self._auth_headers())
        self.assertEqual(stats_resp.status_code, 200)
        stats = json.loads(stats_resp.data)
        self.assertTrue(stats.get("success"))

        claim_resp = self.client.post(
            "/api/external/pool/claim-random",
            headers=self._auth_headers(),
            json={"caller_id": "issue60_compat", "task_id": "compat_flow"},
        )
        self.assertEqual(claim_resp.status_code, 200)
        claim = json.loads(claim_resp.data)
        self.assertTrue(claim.get("success"))
        self.assertIn("claim_token", claim.get("data", {}))

        release_resp = self.client.post(
            "/api/external/pool/claim-release",
            headers=self._auth_headers(),
            json={
                "account_id": claim["data"]["account_id"],
                "claim_token": claim["data"]["claim_token"],
                "caller_id": "issue60_compat",
                "task_id": "compat_flow",
                "reason": "compat regression check",
            },
        )
        self.assertEqual(release_resp.status_code, 200)
        release = json.loads(release_resp.data)
        self.assertTrue(release.get("success"))

    def test_overview_pool_endpoint_still_available(self):
        """/api/overview/pool 不受 pool-admin 改造副作用影响"""
        self._login()
        resp = self._get_authed("/api/overview/pool")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn("kpi", data)
        self.assertIn("recent_operations", data)


if __name__ == "__main__":
    unittest.main()
