from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from codex_account_hub.ui_helpers import current_summary_items, slot_table_row, usage_summary_label


class UiHelpersTests(unittest.TestCase):
    def test_current_summary_items_include_matched_account_label(self) -> None:
        items = dict(
            current_summary_items(
                "claude-code",
                {
                    "email": "alice@example.com",
                    "name": "Alice",
                    "plan_type": "max-5x",
                    "auth_mode": "claude.ai",
                    "snapshot_sync_status": "updated",
                    "matched_account_label": "工作账号",
                },
                account_count=3,
            )
        )
        self.assertEqual(items["当前身份"], "Alice")
        self.assertEqual(items["已关联快照"], "工作账号")
        self.assertEqual(items["已保存账号"], "3")

    def test_slot_table_row_prefers_custom_label(self) -> None:
        row = slot_table_row(
            {
                "id": "account-2",
                "label": "Claude 主号",
                "active": True,
                "snapshot": {
                    "exists": True,
                    "email": "test@example.com",
                    "name": "Six",
                    "plan_type": "pro",
                },
            }
        )
        self.assertEqual(row["status"], "当前认证")
        self.assertEqual(row["label"], "Claude 主号")
        self.assertEqual(row["email"], "test@example.com")
        self.assertEqual(row["plan"], "pro")

    def test_usage_summary_label_prefers_percentages(self) -> None:
        label = usage_summary_label(
            {
                "usage": {
                    "status": "ok",
                    "five_hour_percent": 23.4,
                    "seven_day_percent": 61.0,
                },
                "usage_auth": {
                    "configured": True,
                    "organization_id": "org-1",
                    "has_session_key": True,
                },
            }
        )
        self.assertEqual(label, "5h 已用 23.4% / 7d 已用 61%")

    def test_slot_table_row_includes_usage_summary(self) -> None:
        row = slot_table_row(
            {
                "id": "account-1",
                "label": "Claude 主号",
                "active": False,
                "snapshot": {
                    "exists": True,
                    "email": "test@example.com",
                    "name": "Six",
                    "plan_type": "max",
                },
                "usage": {
                    "status": "unauthorized",
                },
                "usage_auth": {
                    "organization_id": "org-1",
                    "has_session_key": True,
                },
            }
        )
        self.assertEqual(row["usage"], "认证失效")


if __name__ == "__main__":
    unittest.main()
