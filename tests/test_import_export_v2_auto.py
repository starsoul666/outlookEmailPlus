import re
import unittest
import uuid
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class ImportExportV2AutoTests(unittest.TestCase):
    """
    对齐：PRD-00006 / FD-00006 / TDD-00006
    目标：验证“账号导入导出无缝迁移”的核心功能（混合导入 + 导出 v2）。
    """

    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()

    def _login(self, client, password: str = "testpass123"):
        resp = client.post("/login", json={"password": password})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("success"), True)

    def _default_group_id(self) -> int:
        conn = self.module.create_sqlite_connection()
        try:
            row = conn.execute("SELECT id FROM groups WHERE name = '默认分组' LIMIT 1").fetchone()
            return int(row["id"]) if row else 1
        finally:
            conn.close()

    def _temp_email_group_id(self) -> int:
        conn = self.module.create_sqlite_connection()
        try:
            row = conn.execute("SELECT id FROM groups WHERE name = '临时邮箱' LIMIT 1").fetchone()
            self.assertIsNotNone(row)
            return int(row["id"])
        finally:
            conn.close()

    def _get_or_create_group(self, name: str) -> int:
        conn = self.module.create_sqlite_connection()
        try:
            row = conn.execute("SELECT id FROM groups WHERE name = ? LIMIT 1", (name,)).fetchone()
            if row:
                return int(row["id"])
            cur = conn.execute(
                "INSERT INTO groups (name, description, color, proxy_url, is_system) VALUES (?, ?, ?, ?, 0)",
                (name, "", "#111111", ""),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def _get_group_id_by_name(self, name: str) -> int:
        conn = self.module.create_sqlite_connection()
        try:
            row = conn.execute("SELECT id FROM groups WHERE name = ? LIMIT 1", (name,)).fetchone()
            self.assertIsNotNone(row)
            return int(row["id"])
        finally:
            conn.close()

    def _get_account_row(self, email_addr: str):
        conn = self.module.create_sqlite_connection()
        try:
            return conn.execute("SELECT * FROM accounts WHERE email = ? LIMIT 1", (email_addr,)).fetchone()
        finally:
            conn.close()

    def _decrypt_if_needed(self, value: str) -> str:
        if not value:
            return value
        try:
            return self.module.decrypt_data(value)
        except Exception:
            return value

    def _issue_export_token(self, client) -> str:
        verify = client.post("/api/export/verify", json={"password": "testpass123"})
        self.assertEqual(verify.status_code, 200)
        data = verify.get_json()
        self.assertEqual(data.get("success"), True)
        token = data.get("verify_token")
        self.assertTrue(token)
        return token

    def _parse_export_filename(self, content_disposition: str) -> str:
        if not content_disposition:
            return ""
        m = re.search(r"filename\*=(?:UTF-8''|utf-8'')([^;\n]+)", content_disposition)
        if not m:
            return ""
        try:
            from urllib.parse import unquote

            return unquote(m.group(1))
        except Exception:
            return m.group(1)

    def _parse_header_total(self, text: str) -> int:
        # 支持中文全角/半角冒号
        m = re.search(r"账号总数[:：]\s*(\d+)", text)
        self.assertIsNotNone(m, "导出头部缺少“账号总数”字段")
        return int(m.group(1))

    def test_auto_import_mixed_file_imports_accounts_and_temp_emails_and_auto_groups(
        self,
    ):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        outlook_email = f"auto_out_{unique}@outlook.com"
        gmail_email = f"auto_gmail_{unique}@gmail.com"
        qq_email = f"auto_qq_{unique}@qq.com"
        custom_email = f"auto_custom_{unique}@company.com"
        temp_mail_email = f"auto_tmp_{unique}@temp.example"

        outlook_password = f"p_{unique}"
        client_id = f"cid_{unique}"
        refresh_token = f"rt_{unique}----tail"

        gmail_imap_pwd = f"gp_{unique}"
        qq_imap_pwd = f"qqp_{unique}"
        custom_imap_pwd = f"cp_{unique}"
        custom_host = f"imap{unique}.company.com"
        custom_port = 993

        # 兼容导出 v2：包含注释头部与分段注释行
        account_string = "\n".join(
            [
                "# ============================================",
                "# Outlook Email Plus — 账号导出",
                "# 导出时间：2026-03-04 15:30:00",
                "# 格式版本：v2",
                "# ============================================",
                "",
                "# === Outlook 账号 ===",
                f"{outlook_email}----{outlook_password}----{client_id}----{refresh_token}",
                "",
                "# === IMAP 账号（Gmail）===",
                f"{gmail_email}----{gmail_imap_pwd}----gmail",
                "",
                "# === IMAP 账号（QQ邮箱）===",
                f"{qq_email}----{qq_imap_pwd}",
                "",
                "# === IMAP 账号（自定义）===",
                f"{custom_email}----{custom_imap_pwd}----custom----{custom_host}----{custom_port}",
                "",
                "# === 临时邮箱（自建）===",
                temp_mail_email,
            ]
        )

        # 严格导入：探测必须返回非空 list 才允许落库
        with patch(
            "outlook_web.services.gptmail.get_temp_emails_from_api",
            return_value=[{"id": "probe"}],
        ):
            resp = client.post(
                "/api/accounts",
                json={
                    "provider": "auto",
                    "group_id": None,
                    "duplicate_strategy": "skip",
                    "account_string": account_string,
                },
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("success"), True)

        summary = data.get("summary") or {}
        self.assertEqual(summary.get("mode"), "auto")
        self.assertEqual(summary.get("imported"), 5)
        self.assertEqual(summary.get("skipped"), 0)
        self.assertEqual(summary.get("failed"), 0)

        by_provider = summary.get("by_provider") or {}
        self.assertIn("outlook", by_provider)
        self.assertIn("gmail", by_provider)
        self.assertIn("qq", by_provider)
        self.assertIn("custom", by_provider)
        self.assertIn("temp_mail", by_provider)

        # accounts 表应包含 Outlook/IMAP（4 个），不应包含临时邮箱 provider
        out_row = self._get_account_row(outlook_email)
        self.assertIsNotNone(out_row)
        self.assertEqual((out_row["account_type"] or "").lower(), "outlook")
        self.assertEqual((out_row["provider"] or "").lower(), "outlook")
        self.assertEqual(out_row["client_id"], client_id)
        self.assertEqual(self._decrypt_if_needed(out_row["password"]), outlook_password)
        self.assertEqual(self._decrypt_if_needed(out_row["refresh_token"]), refresh_token)

        gmail_row = self._get_account_row(gmail_email)
        self.assertIsNotNone(gmail_row)
        self.assertEqual((gmail_row["account_type"] or "").lower(), "imap")
        self.assertEqual((gmail_row["provider"] or "").lower(), "gmail")
        self.assertEqual((gmail_row["imap_host"] or "").lower(), "imap.gmail.com")
        self.assertEqual(int(gmail_row["imap_port"] or 0), 993)
        self.assertEqual(self._decrypt_if_needed(gmail_row["imap_password"]), gmail_imap_pwd)

        qq_row = self._get_account_row(qq_email)
        self.assertIsNotNone(qq_row)
        self.assertEqual((qq_row["account_type"] or "").lower(), "imap")
        self.assertEqual((qq_row["provider"] or "").lower(), "qq")
        self.assertEqual((qq_row["imap_host"] or "").lower(), "imap.qq.com")  # 2 段格式域名推断
        self.assertEqual(int(qq_row["imap_port"] or 0), 993)
        self.assertEqual(self._decrypt_if_needed(qq_row["imap_password"]), qq_imap_pwd)

        custom_row = self._get_account_row(custom_email)
        self.assertIsNotNone(custom_row)
        self.assertEqual((custom_row["account_type"] or "").lower(), "imap")
        self.assertEqual((custom_row["provider"] or "").lower(), "custom")
        self.assertEqual((custom_row["imap_host"] or "").lower(), custom_host.lower())
        self.assertEqual(int(custom_row["imap_port"] or 0), custom_port)
        self.assertEqual(self._decrypt_if_needed(custom_row["imap_password"]), custom_imap_pwd)

        temp_as_account = self._get_account_row(temp_mail_email)
        self.assertIsNone(temp_as_account)

        conn = self.module.create_sqlite_connection()
        try:
            tmp_row = conn.execute("SELECT * FROM temp_emails WHERE email = ? LIMIT 1", (temp_mail_email,)).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(tmp_row)
        self.assertEqual(tmp_row["source"], "custom_domain_temp_mail")

        # 自动分组：应存在并分配到对应分组（命名对齐 TDD-00006）
        outlook_gid = self._get_group_id_by_name("Outlook")
        gmail_gid = self._get_group_id_by_name("Gmail")
        qq_gid = self._get_group_id_by_name("QQ邮箱")
        custom_gid = self._get_group_id_by_name("自定义IMAP")

        self.assertEqual(int(out_row["group_id"]), outlook_gid)
        self.assertEqual(int(gmail_row["group_id"]), gmail_gid)
        self.assertEqual(int(qq_row["group_id"]), qq_gid)
        self.assertEqual(int(custom_row["group_id"]), custom_gid)

    def test_auto_import_temp_mail_persists_actual_remote_created_email(self):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        requested_email = f"import_req_{unique}@temp.example"
        actual_email = f"import_real_{unique}@temp.example"

        with (
            patch(
                "outlook_web.services.gptmail.get_temp_emails_from_api",
                return_value=None,
            ),
            patch(
                "outlook_web.services.gptmail.generate_temp_email",
                return_value=(actual_email, None),
            ),
        ):
            resp = client.post(
                "/api/accounts",
                json={
                    "provider": "auto",
                    "group_id": None,
                    "duplicate_strategy": "skip",
                    "account_string": requested_email,
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual((data.get("summary") or {}).get("imported"), 1)

        conn = self.module.create_sqlite_connection()
        try:
            actual_row = conn.execute("SELECT * FROM temp_emails WHERE email = ? LIMIT 1", (actual_email,)).fetchone()
            requested_row = conn.execute(
                "SELECT * FROM temp_emails WHERE email = ? LIMIT 1",
                (requested_email,),
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(actual_row)
        self.assertIsNone(requested_row)

    def test_auto_import_unknown_domain_with_fallback_imports_as_custom(self):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        email_addr = f"auto_unknown_{unique}@corp-example.com"
        imap_pwd = f"pw_{unique}"

        fallback_host = f"imap{unique}.corp-example.com"
        fallback_port = 993

        resp = client.post(
            "/api/accounts",
            json={
                "provider": "auto",
                "group_id": None,
                "duplicate_strategy": "skip",
                "imap_host": fallback_host,
                "imap_port": fallback_port,
                "account_string": f"{email_addr}----{imap_pwd}",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("success"), True)

        row = self._get_account_row(email_addr)
        self.assertIsNotNone(row)
        self.assertEqual((row["account_type"] or "").lower(), "imap")
        self.assertEqual((row["provider"] or "").lower(), "custom")
        self.assertEqual((row["imap_host"] or "").lower(), fallback_host.lower())
        self.assertEqual(int(row["imap_port"] or 0), fallback_port)
        self.assertEqual(self._decrypt_if_needed(row["imap_password"]), imap_pwd)

    def test_auto_import_unknown_domain_without_fallback_fails_line_but_continues(self):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        bad_email = f"auto_unknown_{unique}@corp-unknown.com"
        good_email = f"auto_g_{unique}@gmail.com"

        account_string = "\n".join([f"{bad_email}----pw_{unique}", f"{good_email}----gp_{unique}----gmail"])

        resp = client.post(
            "/api/accounts",
            json={
                "provider": "auto",
                "group_id": None,
                "duplicate_strategy": "skip",
                "account_string": account_string,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        # 允许部分失败：只要有成功导入或跳过，则整体 success=True（对齐 TDD-00006）
        self.assertEqual(data.get("success"), True)

        summary = data.get("summary") or {}
        self.assertEqual(summary.get("mode"), "auto")
        self.assertEqual(summary.get("imported"), 1)
        self.assertEqual(summary.get("failed"), 1)

        errors = data.get("errors") or []
        self.assertTrue(errors)
        self.assertEqual(errors[0].get("line"), 1)

        self.assertIsNone(self._get_account_row(bad_email))
        self.assertIsNotNone(self._get_account_row(good_email))

    def test_auto_import_duplicate_skip_does_not_overwrite_credentials(self):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        email_addr = f"dup_skip_{unique}@outlook.com"
        old_rt = f"old_rt_{unique}"
        new_rt = f"new_rt_{unique}"

        conn = self.module.create_sqlite_connection()
        try:
            conn.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, account_type, provider, group_id, remark, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email_addr,
                    self.module.encrypt_data("old_pw_" + unique),
                    "cid_" + unique,
                    self.module.encrypt_data(old_rt),
                    "outlook",
                    "outlook",
                    self._default_group_id(),
                    "keep_remark",
                    "active",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        resp = client.post(
            "/api/accounts",
            json={
                "provider": "auto",
                "group_id": None,
                "duplicate_strategy": "skip",
                "account_string": f"{email_addr}----new_pw_{unique}----cid_{unique}----{new_rt}",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("success"), True)

        summary = data.get("summary") or {}
        self.assertEqual(summary.get("mode"), "auto")
        self.assertEqual(summary.get("imported"), 0)
        self.assertEqual(summary.get("skipped"), 1)
        self.assertEqual(summary.get("failed"), 0)

        row = self._get_account_row(email_addr)
        self.assertIsNotNone(row)
        self.assertEqual(self._decrypt_if_needed(row["refresh_token"]), old_rt)
        self.assertEqual((row["remark"] or ""), "keep_remark")

    def test_auto_import_duplicate_overwrite_updates_credentials_keeps_remark(self):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        email_addr = f"dup_over_{unique}@outlook.com"
        old_rt = f"old_rt_{unique}"
        new_rt = f"new_rt_{unique}----tail"

        conn = self.module.create_sqlite_connection()
        try:
            conn.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, account_type, provider, group_id, remark, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email_addr,
                    self.module.encrypt_data("old_pw_" + unique),
                    "cid_" + unique,
                    self.module.encrypt_data(old_rt),
                    "outlook",
                    "outlook",
                    self._default_group_id(),
                    "keep_remark",
                    "active",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        resp = client.post(
            "/api/accounts",
            json={
                "provider": "auto",
                "group_id": None,
                "duplicate_strategy": "overwrite",
                "account_string": f"{email_addr}----new_pw_{unique}----cid_{unique}----{new_rt}",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("success"), True)

        summary = data.get("summary") or {}
        self.assertEqual(summary.get("mode"), "auto")
        self.assertEqual(summary.get("imported"), 1)
        self.assertEqual(summary.get("skipped"), 0)
        self.assertEqual(summary.get("failed"), 0)

        row = self._get_account_row(email_addr)
        self.assertIsNotNone(row)
        self.assertEqual(self._decrypt_if_needed(row["refresh_token"]), new_rt)
        self.assertEqual((row["remark"] or ""), "keep_remark")

        # overwrite 时应按新分组策略更新 group_id（Outlook -> "Outlook" 分组）
        outlook_gid = self._get_group_id_by_name("Outlook")
        self.assertEqual(int(row["group_id"]), outlook_gid)

    def test_export_selected_v2_includes_temp_mail_only_when_temp_group_selected(self):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        group_name = f"导出测试_{unique}"
        group_id = self._get_or_create_group(group_name)
        temp_group_id = self._temp_email_group_id()

        outlook_email = f"exp_out_{unique}@outlook.com"
        imap_email = f"exp_g_{unique}@gmail.com"
        tmp1 = f"tmp_{unique}_1@temp.example"
        tmp2 = f"tmp_{unique}_2@temp.example"

        conn = self.module.create_sqlite_connection()
        try:
            conn.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, account_type, provider, group_id, remark, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outlook_email,
                    self.module.encrypt_data("pw_" + unique),
                    "cid_" + unique,
                    self.module.encrypt_data("rt_" + unique),
                    "outlook",
                    "outlook",
                    group_id,
                    "",
                    "active",
                ),
            )
            conn.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, account_type, provider, imap_host, imap_port, imap_password, group_id, remark, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    imap_email,
                    "",
                    "",
                    "",
                    "imap",
                    "gmail",
                    "imap.gmail.com",
                    993,
                    self.module.encrypt_data("imap_pw_" + unique),
                    group_id,
                    "",
                    "active",
                ),
            )
            conn.execute("INSERT OR IGNORE INTO temp_emails (email) VALUES (?)", (tmp1,))
            conn.execute("INSERT OR IGNORE INTO temp_emails (email) VALUES (?)", (tmp2,))
            conn.commit()

            temp_total = conn.execute("SELECT COUNT(*) as c FROM temp_emails").fetchone()["c"]
            acc_total = conn.execute("SELECT COUNT(*) as c FROM accounts WHERE group_id = ?", (group_id,)).fetchone()["c"]
        finally:
            conn.close()

        token1 = self._issue_export_token(client)

        # 1) 不包含“临时邮箱”分组：不应输出临时邮箱分段
        export1 = client.post(
            "/api/accounts/export-selected",
            headers={"X-Export-Token": token1, "Content-Type": "application/json"},
            json={"group_ids": [group_id]},
        )
        self.assertEqual(export1.status_code, 200)
        body1 = export1.get_data(as_text=True)
        self.assertIn("格式版本：v2", body1)
        self.assertNotIn("# === 临时邮箱（自建）===", body1)
        self.assertNotIn(tmp1, body1)
        self.assertNotIn(tmp2, body1)
        self.assertTrue(body1.endswith("\n"))

        # export verify token 为一次性（one-time）使用：第二次导出需重新获取
        token2 = self._issue_export_token(client)

        # 2) 包含“临时邮箱”分组：输出临时邮箱分段（包含邮箱地址）
        export2 = client.post(
            "/api/accounts/export-selected",
            headers={"X-Export-Token": token2, "Content-Type": "application/json"},
            json={"group_ids": [group_id, temp_group_id]},
        )
        self.assertEqual(export2.status_code, 200)
        body2 = export2.get_data(as_text=True)
        self.assertIn("格式版本：v2", body2)
        self.assertIn("# === 临时邮箱（自建）===", body2)
        self.assertIn(tmp1, body2)
        self.assertIn(tmp2, body2)
        self.assertIn(outlook_email, body2)
        self.assertIn(imap_email, body2)
        self.assertTrue(body2.endswith("\n"))

        # 临时邮箱行必须是“仅邮箱地址”（不包含分隔符）
        lines = body2.splitlines()
        self.assertIn(tmp1, lines)
        self.assertIn(tmp2, lines)
        self.assertTrue(all("----" not in l for l in [tmp1, tmp2]))

        # 头部统计：账号总数应等于（选中分组 accounts 数量 + temp_emails 总数）
        total = self._parse_header_total(body2)
        self.assertEqual(total, int(acc_total) + int(temp_total))

        # 文件名：需要包含时间戳（对齐 PRD-00006）
        filename = self._parse_export_filename(export2.headers.get("Content-Disposition", ""))
        self.assertTrue(filename.startswith("accounts_export_selected_"))
        self.assertRegex(filename, r"^accounts_export_selected_\d{8}_\d{6}\.txt$")

    def test_export_selected_v2_by_account_ids_only_exports_checked_accounts(self):
        client = self.app.test_client()
        self._login(client)

        unique = uuid.uuid4().hex
        group_id_a = self._get_or_create_group(f"勾选导出A_{unique}")
        group_id_b = self._get_or_create_group(f"勾选导出B_{unique}")

        selected_outlook = f"checked_out_{unique}@outlook.com"
        selected_imap = f"checked_g_{unique}@gmail.com"
        unselected_email = f"unchecked_{unique}@outlook.com"
        tmp_email = f"tmp_checked_{unique}@temp.example"

        conn = self.module.create_sqlite_connection()
        try:
            cur1 = conn.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, account_type, provider, group_id, remark, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    selected_outlook,
                    self.module.encrypt_data("pw_" + unique),
                    "cid_" + unique,
                    self.module.encrypt_data("rt_" + unique),
                    "outlook",
                    "outlook",
                    group_id_a,
                    "",
                    "active",
                ),
            )
            selected_outlook_id = int(cur1.lastrowid)

            cur2 = conn.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, account_type, provider, imap_host, imap_port, imap_password, group_id, remark, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    selected_imap,
                    "",
                    "",
                    "",
                    "imap",
                    "gmail",
                    "imap.gmail.com",
                    993,
                    self.module.encrypt_data("imap_pw_" + unique),
                    group_id_b,
                    "",
                    "active",
                ),
            )
            selected_imap_id = int(cur2.lastrowid)

            conn.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, account_type, provider, group_id, remark, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    unselected_email,
                    self.module.encrypt_data("pw_unchecked_" + unique),
                    "cid_unchecked_" + unique,
                    self.module.encrypt_data("rt_unchecked_" + unique),
                    "outlook",
                    "outlook",
                    group_id_a,
                    "",
                    "active",
                ),
            )
            conn.execute("INSERT OR IGNORE INTO temp_emails (email) VALUES (?)", (tmp_email,))
            conn.commit()
        finally:
            conn.close()

        token = self._issue_export_token(client)
        export_resp = client.post(
            "/api/accounts/export-selected",
            headers={"X-Export-Token": token, "Content-Type": "application/json"},
            json={"account_ids": [selected_outlook_id, selected_imap_id]},
        )
        self.assertEqual(export_resp.status_code, 200)

        body = export_resp.get_data(as_text=True)
        self.assertIn("格式版本：v2", body)
        self.assertIn(selected_outlook, body)
        self.assertIn(selected_imap, body)
        self.assertNotIn(unselected_email, body)
        self.assertNotIn(tmp_email, body)
        self.assertNotIn("# === 临时邮箱（自建）===", body)
        self.assertEqual(self._parse_header_total(body), 2)
        self.assertTrue(body.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
