from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from codex_account_hub.tray import slot_preview_label, snapshot_sync_label, tray_title


class TrayHelpersTests(unittest.TestCase):
    def test_slot_preview_label_for_saved_slot(self) -> None:
        slot = {
            "id": "account-2",
            "label": "工作账号",
            "active": True,
            "snapshot": {
                "exists": True,
                "name": "Alice",
                "email": "alice@example.com",
                "account_id": "acct-2",
            },
        }
        self.assertEqual(slot_preview_label(slot), "工作账号 · 当前")

    def test_slot_preview_label_for_empty_slot(self) -> None:
        slot = {
            "id": "account-3",
            "label": "账号 3",
            "active": False,
            "snapshot": {
                "exists": False,
            },
        }
        self.assertEqual(slot_preview_label(slot), "账号 3")

    def test_tray_title_uses_matched_slot_number(self) -> None:
        overview = {"current": {"matched_slot_id": "account-4"}}
        self.assertEqual(tray_title(overview), "Hub")

    def test_snapshot_sync_label_for_updated_current(self) -> None:
        current = {"snapshot_sync_status": "updated"}
        self.assertEqual(snapshot_sync_label(current), "已自动同步")


if __name__ == "__main__":
    unittest.main()
