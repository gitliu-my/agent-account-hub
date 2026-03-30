from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from codex_account_hub.tray import (
    slot_preview_label,
    snapshot_sync_label,
    status_item_usage_title,
    tray_title,
    tray_usage_slots,
)


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

    def test_status_item_usage_title_prefers_current_usage_percentages(self) -> None:
        overview = {
            "current": {
                "usage": {
                    "status": "ok",
                    "five_hour_percent": 23.4,
                    "seven_day_percent": 61.0,
                },
                "usage_auth": {
                    "configured": True,
                },
            },
            "accounts": [],
        }
        self.assertEqual(status_item_usage_title(overview), "23·61")

    def test_status_item_usage_title_falls_back_to_error_marker(self) -> None:
        overview = {
            "current": {
                "usage": {
                    "status": "unauthorized",
                },
                "usage_auth": {},
            },
            "accounts": [
                {
                    "usage": {
                        "status": "unauthorized",
                    },
                    "usage_auth": {
                        "configured": True,
                    },
                }
            ],
        }
        self.assertEqual(status_item_usage_title(overview), "!")

    def test_tray_usage_slots_reads_selected_menu_bar_accounts(self) -> None:
        overview = {
            "provider_id": "codex",
            "usage_menu_bar_accounts": [
                {"id": "account-1", "active": True, "usage": {"five_hour_percent": 21.0}},
                {"id": "account-2", "active": False, "usage": {"seven_day_percent": 64.0}},
            ]
        }
        slots = tray_usage_slots(overview)
        self.assertEqual([slot["id"] for slot in slots], ["account-1", "account-2"])
        self.assertEqual([slot["provider_id"] for slot in slots], ["codex", "codex"])
        self.assertEqual([slot["active"] for slot in slots], [True, False])


if __name__ == "__main__":
    unittest.main()
