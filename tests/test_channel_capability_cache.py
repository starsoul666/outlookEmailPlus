"""
D 层：通道能力缓存测试

验证 services/channel_capability_cache.py 的写入/读取/TTL/失效行为。
对应 TDD 矩阵 C-01 ~ C-07。

注意：通道缓存模块尚未实现，本测试先行编写（TDD 红灯阶段）。
实现时需新建 outlook_web/services/channel_capability_cache.py。
"""

import unittest
from unittest.mock import patch


class TestChannelCapabilityCache(unittest.TestCase):
    """通道能力缓存测试"""

    def setUp(self):
        """每个测试前清空缓存"""
        try:
            from outlook_web.services.channel_capability_cache import clear_all

            clear_all()
        except ImportError:
            pass

    def tearDown(self):
        try:
            from outlook_web.services.channel_capability_cache import clear_all

            clear_all()
        except ImportError:
            pass

    # C-01: 写入可用 → 读取返回 available
    def test_set_available_and_get(self):
        from outlook_web.services.channel_capability_cache import get_status, set_status

        set_status("user@test.com", "imap_new", available=True)
        status = get_status("user@test.com", "imap_new")
        self.assertEqual(status, "available")

    # C-02: 写入不可用 → 读取返回 unavailable
    def test_set_unavailable_and_get(self):
        from outlook_web.services.channel_capability_cache import get_status, set_status

        set_status("user@test.com", "graph_inbox", available=False)
        status = get_status("user@test.com", "graph_inbox")
        self.assertEqual(status, "unavailable")

    # C-03: 不可用渠道应被 filter 跳过
    def test_unavailable_channel_filtered_in_plan(self):
        from outlook_web.services.channel_capability_cache import (
            filter_channel_plan,
            set_status,
        )

        set_status("user@test.com", "graph_inbox", available=False)
        set_status("user@test.com", "graph_junk", available=False)

        original_plan = ["graph_inbox", "graph_junk", "imap_new", "imap_old"]
        filtered = filter_channel_plan("user@test.com", original_plan)

        self.assertNotIn("graph_inbox", filtered)
        self.assertNotIn("graph_junk", filtered)
        self.assertIn("imap_new", filtered)
        self.assertIn("imap_old", filtered)

    # C-04: 无缓存 → 返回 None
    def test_no_cache_returns_none(self):
        from outlook_web.services.channel_capability_cache import get_status

        status = get_status("new@test.com", "imap_new")
        self.assertIsNone(status)

    # C-05: TTL 过期 → 返回 None
    @patch("outlook_web.services.channel_capability_cache.time.monotonic")
    def test_cache_expires_after_ttl(self, mock_time):
        from outlook_web.services.channel_capability_cache import get_status, set_status

        mock_time.return_value = 0.0
        set_status("user@test.com", "imap_new", available=True)

        # 1 小时后过期
        mock_time.return_value = 3601.0
        status = get_status("user@test.com", "imap_new")
        self.assertIsNone(status)

    # C-06: 手动清除（如 token 刷新后）
    def test_clear_cache_for_account(self):
        from outlook_web.services.channel_capability_cache import (
            clear_for_account,
            get_status,
            set_status,
        )

        set_status("user@test.com", "imap_new", available=True)
        set_status("user@test.com", "graph_inbox", available=False)
        clear_for_account("user@test.com")

        self.assertIsNone(get_status("user@test.com", "imap_new"))
        self.assertIsNone(get_status("user@test.com", "graph_inbox"))

    # C-07: 不同账号隔离
    def test_different_accounts_isolated(self):
        from outlook_web.services.channel_capability_cache import get_status, set_status

        set_status("alice@test.com", "imap_new", available=True)
        set_status("bob@test.com", "imap_new", available=False)

        self.assertEqual(get_status("alice@test.com", "imap_new"), "available")
        self.assertEqual(get_status("bob@test.com", "imap_new"), "unavailable")

    # 额外：filter_channel_plan 缓存为空时不过滤
    def test_filter_no_cache_returns_all(self):
        from outlook_web.services.channel_capability_cache import filter_channel_plan

        plan = ["graph_inbox", "graph_junk", "imap_new", "imap_old"]
        filtered = filter_channel_plan("uncached@test.com", plan)
        self.assertEqual(filtered, plan)

    # 全部渠道缓存为不可用时，回退完整 plan 并清缓存，避免永久跳过
    def test_filter_all_unavailable_falls_back_to_full_plan(self):
        from outlook_web.services.channel_capability_cache import (
            filter_channel_plan,
            get_status,
            set_status,
        )

        plan = ["graph_inbox", "graph_junk", "imap_new", "imap_old"]
        for ch in plan:
            set_status("user@test.com", ch, available=False)

        filtered = filter_channel_plan("user@test.com", plan)
        self.assertEqual(filtered, plan)
        self.assertIsNone(get_status("user@test.com", "graph_inbox"))


if __name__ == "__main__":
    unittest.main()
