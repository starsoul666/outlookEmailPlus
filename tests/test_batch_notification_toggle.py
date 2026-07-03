"""tests/test_batch_notification_toggle.py — Issue #64 TDD 批量通知开关测试

目标：先写 RED 测试，再实现 `POST /api/accounts/batch-notification-toggle`。

测试分组：
  BatchNotificationToggleApiTests — N-01~N-16 批量通知开关 API 契约
"""

from __future__ import annotations

import json
import unittest

from tests._import_app import clear_login_attempts, import_web_app_module

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _get_app():
    return import_web_app_module().app


def _login(client):
    resp = client.post("/login", json={"password": "testpass123"})
    assert resp.status_code == 200, f"Login failed: {resp.data}"


def _insert_test_account(db, email, provider="imap", enabled=0, pool_status=None):
    """在 accounts 表中插入测试账号，返回 rowid。"""
    db.execute(
        """INSERT INTO accounts
           (email, client_id, provider, account_type, refresh_token, imap_host, imap_port,
            imap_password, group_id, telegram_push_enabled, status, pool_status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            email,
            "test_client_id",
            provider,
            "outlook" if provider == "outlook" else "imap",
            "enc:dummy_refresh",
            "imap.test.com",
            993,
            "enc:dummy_pass",
            None,
            enabled,
            "active",
            pool_status,
        ),
    )
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _insert_test_accounts(db, count=3, prefix="batch_test", enabled=0):
    """批量插入测试账号，返回 ID 列表。"""
    ids = []
    for i in range(count):
        aid = _insert_test_account(db, f"{prefix}{i}@test.com", enabled=enabled)
        ids.append(aid)
    return ids


# ===========================================================================
# N-01 ~ N-16：批量通知开关 API 测试
# ===========================================================================


class BatchNotificationToggleApiTests(unittest.TestCase):
    """Issue #64 — 批量通知开关 API 端点测试"""

    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.db import get_db

            db = get_db()
            db.execute("DELETE FROM account_claim_logs")
            db.execute("DELETE FROM account_project_usage")
            db.execute("DELETE FROM notification_cursor_states")
            db.execute("DELETE FROM accounts")
            db.commit()

    # ── 成功场景 ──────────────────────────────────────────────

    def test_n01_batch_enable_all_exist(self):
        """N-01：批量开启通知 — 全部账号存在"""
        client = self.app.test_client()
        _login(client)

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            ids = _insert_test_accounts(db, count=3, enabled=0)

        resp = client.post(
            "/api/accounts/batch-notification-toggle",
            json={"account_ids": ids, "enabled": True},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("updated_count"), 3)
        self.assertEqual(data.get("failed_count"), 0)
        self.assertIn("message", data)

        # 验证 DB 状态
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            for aid in ids:
                row = db.execute("SELECT telegram_push_enabled FROM accounts WHERE id = ?", (aid,)).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["telegram_push_enabled"], 1)

    def test_n02_batch_disable_all_exist(self):
        """N-02：批量关闭通知 — 全部账号存在"""
        client = self.app.test_client()
        _login(client)

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            ids = _insert_test_accounts(db, count=3, enabled=1)

        resp = client.post(
            "/api/accounts/batch-notification-toggle",
            json={"account_ids": ids, "enabled": False},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("updated_count"), 3)
        self.assertEqual(data.get("failed_count"), 0)

        # 验证 DB 状态
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            for aid in ids:
                row = db.execute("SELECT telegram_push_enabled FROM accounts WHERE id = ?", (aid,)).fetchone()
                self.assertEqual(row["telegram_push_enabled"], 0)

    # ── 幂等场景 ──────────────────────────────────────────────

    def test_n03_idempotent_enable(self):
        """N-03：幂等开启 — 已开启的账号再开启不报错"""
        client = self.app.test_client()
        _login(client)

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            ids = _insert_test_accounts(db, count=2, enabled=1)

        # 第一次开启（已开启）
        resp = client.post(
            "/api/accounts/batch-notification-toggle",
            json={"account_ids": ids, "enabled": True},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))

        # 第二次开启（幂等）
        resp2 = client.post(
            "/api/accounts/batch-notification-toggle",
            json={"account_ids": ids, "enabled": True},
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp2.get_json().get("success"))

    def test_n04_idempotent_disable(self):
        """N-04：幂等关闭 — 已关闭的账号再关闭不报错"""
        client = self.app.test_client()
        _login(client)

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            ids = _insert_test_accounts(db, count=2, enabled=0)

        resp = client.post(
            "/api/accounts/batch-notification-toggle",
            json={"account_ids": ids, "enabled": False},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))

        resp2 = client.post(
            "/api/accounts/batch-notification-toggle",
            json={"account_ids": ids, "enabled": False},
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp2.get_json().get("success"))

    # ── 部分失败场景 ──────────────────────────────────────────

    def test_n05_partial_missing_ids(self):
        """N-05：部分 ID 不存在 — 存在的正常处理，不存在的计入 missing"""
        client = self.app.test_client()
        _login(client)

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            ids = _insert_test_accounts(db, count=2, enabled=0)

        partial_ids = ids + [999999, 999998]  # 后两个不存在

        resp = client.post(
            "/api/accounts/batch-notification-toggle",
            json={"account_ids": partial_ids, "enabled": True},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("updated_count"), 2)
        self.assertEqual(data.get("failed_count"), 2)
        self.assertIn("missing_ids", data)
        self.assertEqual(sorted(data["missing_ids"]), [999998, 999999])

    def test_n06_mixed_state_batch_toggle(self):
        """N-06：混合状态批量 — 部分已开启部分已关闭，统一按 enabled 设置"""
        client = self.app.test_client()
        _login(client)

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            id_enabled = _insert_test_account(db, "enabled1@test.com", enabled=1)
            id_disabled = _insert_test_account(db, "disabled1@test.com", enabled=0)

        # 批量开启
        resp = client.post(
            "/api/accounts/batch-notification-toggle",
            json={"account_ids": [id_enabled, id_disabled], "enabled": True},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))

        # 两个都应该变成 enabled=1
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            for aid in [id_enabled, id_disabled]:
                row = db.execute("SELECT telegram_push_enabled FROM accounts WHERE id = ?", (aid,)).fetchone()
                self.assertEqual(row["telegram_push_enabled"], 1)

    # ── 边界与错误场景 ────────────────────────────────────────

    def test_n07_empty_ids_list(self):
        """N-07：空 ID 列表 — 返回参数错误"""
        client = self.app.test_client()
        _login(client)

        resp = client.post(
            "/api/accounts/batch-notification-toggle",
            json={"account_ids": [], "enabled": True},
        )
        data = resp.get_json()
        self.assertFalse(data.get("success"))
        self.assertIn("error", data)
        self.assertIn("ACCOUNT_IDS_REQUIRED", data.get("error", {}).get("code", ""))

    def test_n08_missing_account_ids_field(self):
        """N-08：缺少 account_ids 字段 — 返回参数错误"""
        client = self.app.test_client()
        _login(client)

        resp = client.post(
            "/api/accounts/batch-notification-toggle",
            json={"enabled": True},
        )
        data = resp.get_json()
        self.assertFalse(data.get("success"))
        self.assertIn("error", data)

    def test_n09_invalid_type_ids(self):
        """N-09：ID 类型错误（字符串） — 返回参数错误"""
        client = self.app.test_client()
        _login(client)

        resp = client.post(
            "/api/accounts/batch-notification-toggle",
            json={"account_ids": ["abc", "def"], "enabled": True},
        )
        data = resp.get_json()
        self.assertFalse(data.get("success"))
        self.assertIn("error", data)
        self.assertIn("INVALID_PARAM", data.get("error", {}).get("code", ""))

    def test_n10_missing_enabled_defaults_false(self):
        """N-10：缺少 enabled 字段 — 默认 false（关闭通知）"""
        client = self.app.test_client()
        _login(client)

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            ids = _insert_test_accounts(db, count=2, enabled=1)

        resp = client.post(
            "/api/accounts/batch-notification-toggle",
            json={"account_ids": ids},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        # 默认 enabled=false，所以应该关闭通知
        self.assertFalse(data.get("enabled"))

        # 验证 DB 中已关闭
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            for aid in ids:
                row = db.execute("SELECT telegram_push_enabled FROM accounts WHERE id = ?", (aid,)).fetchone()
                self.assertEqual(row["telegram_push_enabled"], 0)

    # ── 鉴权场景 ──────────────────────────────────────────────

    def test_n11_unauthenticated(self):
        """N-11：未登录 — 返回 401 或 302 重定向"""
        client = self.app.test_client()
        resp = client.post(
            "/api/accounts/batch-notification-toggle",
            json={"account_ids": [1], "enabled": True},
        )
        # 未登录时可能返回 302（重定向到登录页）或 401
        self.assertIn(resp.status_code, (302, 401))

    # ── 池状态无关场景 ────────────────────────────────────────

    def test_n12_claimed_account_toggle(self):
        """N-12：claimed 状态账号 — 通知开关不受池状态影响"""
        client = self.app.test_client()
        _login(client)

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            aid = _insert_test_account(db, "claimed_note@test.com", enabled=0, pool_status="claimed")

        resp = client.post(
            "/api/accounts/batch-notification-toggle",
            json={"account_ids": [aid], "enabled": True},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            row = db.execute(
                "SELECT telegram_push_enabled, pool_status FROM accounts WHERE id = ?",
                (aid,),
            ).fetchone()
            self.assertEqual(row["telegram_push_enabled"], 1)
            self.assertEqual(row["pool_status"], "claimed")  # 池状态不变

    def test_n13_frozen_account_toggle(self):
        """N-13：frozen 状态账号 — 通知开关不受池状态影响"""
        client = self.app.test_client()
        _login(client)

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            aid = _insert_test_account(db, "frozen_note@test.com", enabled=0, pool_status="frozen")

        resp = client.post(
            "/api/accounts/batch-notification-toggle",
            json={"account_ids": [aid], "enabled": True},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))

    # ── DB 状态验证场景 ──────────────────────────────────────

    def test_n14_telegram_push_enabled_field_updated(self):
        """N-14：telegram_push_enabled 字段正确写入 DB"""
        client = self.app.test_client()
        _login(client)

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            ids = _insert_test_accounts(db, count=3, enabled=0)

        client.post(
            "/api/accounts/batch-notification-toggle",
            json={"account_ids": ids, "enabled": True},
        )

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            for aid in ids:
                row = db.execute(
                    "SELECT telegram_push_enabled, telegram_last_checked_at FROM accounts WHERE id = ?",
                    (aid,),
                ).fetchone()
                self.assertEqual(row["telegram_push_enabled"], 1)
                self.assertIsNotNone(row["telegram_last_checked_at"])  # 开启时更新

    def test_n15_cursor_initialized_on_enable(self):
        """N-15：开启通知时 notification_cursor_states 写入 channel 游标"""
        client = self.app.test_client()
        _login(client)

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            aid = _insert_test_account(db, "cursor_test@test.com", enabled=0)

        client.post(
            "/api/accounts/batch-notification-toggle",
            json={"account_ids": [aid], "enabled": True},
        )

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            rows = db.execute(
                "SELECT channel, source_type, source_key FROM notification_cursor_states WHERE source_key LIKE ?",
                ("%cursor_test%",),
            ).fetchall()
            channels = {row["channel"] for row in rows}
            # 应包含 email 和 telegram 两个 channel 的游标
            self.assertIn("email", channels)
            self.assertIn("telegram", channels)

    def test_n16_last_checked_updated_on_enable(self):
        """N-16：开启通知时 telegram_last_checked_at 更新为当前时间"""
        client = self.app.test_client()
        _login(client)

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            aid = _insert_test_account(db, "lastcheck@test.com", enabled=0)
            # 确认初始为空
            before = db.execute("SELECT telegram_last_checked_at FROM accounts WHERE id = ?", (aid,)).fetchone()
            self.assertIsNone(before["telegram_last_checked_at"])

        client.post(
            "/api/accounts/batch-notification-toggle",
            json={"account_ids": [aid], "enabled": True},
        )

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            after = db.execute("SELECT telegram_last_checked_at FROM accounts WHERE id = ?", (aid,)).fetchone()
            self.assertIsNotNone(after["telegram_last_checked_at"])


# ===========================================================================
# 批量获取邮件 API 测试（增强项 — RED 占位）
# ===========================================================================


class BatchEmailFetchApiTests(unittest.TestCase):
    """Issue #64 — 批量邮件获取 API 测试（增强项，先 RED）"""

    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.db import get_db

            db = get_db()
            db.execute("DELETE FROM account_claim_logs")
            db.execute("DELETE FROM account_project_usage")
            db.execute("DELETE FROM accounts")
            db.commit()

    def test_e01_batch_fetch_endpoint_defined(self):
        """E-01：确认批量获取邮件端点已注册（当前应 404 RED）"""
        client = self.app.test_client()
        _login(client)

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            ids = _insert_test_accounts(db, count=2)

        resp = client.post(
            "/api/emails/batch",
            json={"account_ids": ids},
        )
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("results", data)
        self.assertEqual(len(data["results"]), 2)

    def test_e02_partial_failure(self):
        """E-02：部分账号失败不中断整批"""
        client = self.app.test_client()
        _login(client)

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            ids = _insert_test_accounts(db, count=1)

        resp = client.post(
            "/api/emails/batch",
            json={"account_ids": ids + [999999]},  # 含不存在 ID
        )
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        # 汇总应反映部分失败
        summary = data.get("summary", {})
        self.assertEqual(summary.get("total_accounts"), 2)
        self.assertGreaterEqual(summary.get("success_accounts"), 0)
        self.assertGreaterEqual(summary.get("failed_accounts"), 0)

    def test_e03_empty_ids_list(self):
        """E-03：空 ID 列表返回参数错误"""
        client = self.app.test_client()
        _login(client)

        resp = client.post(
            "/api/emails/batch",
            json={"account_ids": []},
        )
        data = resp.get_json()
        self.assertFalse(data.get("success"))

    def test_e04_unauthenticated(self):
        """E-04：未登录返回 401"""
        client = self.app.test_client()
        resp = client.post(
            "/api/emails/batch",
            json={"account_ids": [1]},
        )
        self.assertIn(resp.status_code, (302, 401))
