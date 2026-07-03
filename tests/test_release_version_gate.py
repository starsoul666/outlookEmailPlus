"""Release version alignment gate (scripts/check_release_version.py)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from scripts import check_release_version as gate


class ReleaseVersionGateTests(unittest.TestCase):
    def test_skip_on_main_ref(self):
        self.assertEqual(gate.run_checks("refs/heads/main"), [])

    def test_ok_when_version_and_changelog_match(self):
        ref = "refs/tags/v2.7.0"
        with patch.object(gate, "check_app_version", return_value=[]):
            with patch.object(gate, "check_changelog", return_value=[]):
                self.assertEqual(gate.run_checks(ref), [])

    def test_errors_when_version_mismatch(self):
        ref = "refs/tags/v2.7.0"
        with patch.object(gate, "check_app_version", return_value=["version mismatch"]):
            with patch.object(gate, "check_changelog", return_value=[]):
                errors = gate.run_checks(ref)
        self.assertEqual(len(errors), 1)
        self.assertIn("version", errors[0])

    def test_main_exits_zero(self):
        with patch.dict(os.environ, {"GITHUB_REF": "refs/heads/main"}, clear=False):
            self.assertEqual(gate.main(), 0)

    def test_tag_mismatch_exits_nonzero(self):
        with patch.dict(os.environ, {"GITHUB_REF": "refs/tags/v9.9.9"}, clear=False):
            code = gate.main()
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
