from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from codex_account_hub.core import AuthHub, AuthHubPaths, LEGACY_DATA_ROOT_ENV_VAR


def encode_segment(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def fake_jwt(payload: dict) -> str:
    return ".".join([encode_segment({"alg": "none"}), encode_segment(payload), "signature"])


def build_auth(email: str, name: str, account_id: str, plan_type: str) -> dict:
    id_token = fake_jwt(
        {
            "email": email,
            "name": name,
            "exp": 1_900_000_000,
            "https://api.openai.com/auth": {
                "chatgpt_account_id": account_id,
                "chatgpt_plan_type": plan_type,
            },
        }
    )
    return {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": id_token,
            "access_token": id_token,
            "refresh_token": "refresh",
            "account_id": account_id,
        },
        "last_refresh": "2026-03-25T10:00:00Z",
    }


class AuthHubTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.paths = AuthHubPaths(
            data_root=root / "data",
            state_path=root / "data" / "state.json",
            accounts_root=root / "data" / "accounts",
            active_auth_path=root / "shared" / "auth.json",
        )
        self.legacy_candidates_patcher = patch(
            "codex_account_hub.core.legacy_data_root_candidates",
            return_value=[],
        )
        self.legacy_candidates_patcher.start()
        self.hub = AuthHub(self.paths)

    def tearDown(self) -> None:
        self.legacy_candidates_patcher.stop()
        self.tempdir.cleanup()

    def write_active_auth(self, email: str, name: str, account_id: str, plan_type: str) -> None:
        self.paths.active_auth_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.active_auth_path.write_text(
            json.dumps(build_auth(email, name, account_id, plan_type), ensure_ascii=False),
            encoding="utf-8",
        )

    def test_capture_and_detect_active_slot(self) -> None:
        self.write_active_auth("one@example.com", "One", "acct-one", "plus")
        self.hub.capture_current("account-1")

        overview = self.hub.overview()
        self.assertEqual(overview["current"]["matched_slot_id"], "account-1")
        self.assertEqual(overview["slots"][0]["snapshot"]["email"], "one@example.com")

    def test_create_account_from_current_adds_dynamic_saved_account(self) -> None:
        self.write_active_auth("new@example.com", "New", "acct-new", "pro")

        payload = self.hub.create_account_from_current()

        self.assertTrue(payload["created_new_account"])
        overview = self.hub.overview()
        self.assertEqual(len(overview["accounts"]), 1)
        self.assertEqual(overview["accounts"][0]["snapshot"]["email"], "new@example.com")

    def test_switch_replaces_active_auth(self) -> None:
        self.write_active_auth("one@example.com", "One", "acct-one", "plus")
        self.hub.capture_current("account-1")

        self.write_active_auth("two@example.com", "Two", "acct-two", "pro")
        self.hub.capture_current("account-2")

        self.hub.switch("account-1")
        current = self.hub.current_overview()
        self.assertEqual(current["email"], "one@example.com")
        self.assertEqual(current["matched_slot_id"], "account-1")

    def test_capture_moves_existing_binding_to_new_slot(self) -> None:
        self.write_active_auth("same@example.com", "Same", "acct-same", "plus")
        self.hub.capture_current("account-2")

        moved = self.hub.capture_current("account-3")
        self.assertEqual(moved["cleared_slot_ids"], ["account-2"])
        self.assertFalse(self.hub.slot_auth_path("account-2").exists())
        self.assertTrue(self.hub.slot_auth_path("account-3").exists())

    def test_import_file_populates_slot(self) -> None:
        source = Path(self.tempdir.name) / "external-auth.json"
        source.write_text(
            json.dumps(build_auth("ext@example.com", "Ext", "acct-ext", "plus"), ensure_ascii=False),
            encoding="utf-8",
        )

        slot = self.hub.import_file("account-3", source)
        self.assertEqual(slot["snapshot"]["account_id"], "acct-ext")

    def test_clear_slot_removes_snapshot(self) -> None:
        self.write_active_auth("one@example.com", "One", "acct-one", "plus")
        self.hub.capture_current("account-1")

        self.hub.clear_slot("account-1")
        self.assertFalse(self.hub.slot_auth_path("account-1").exists())

    def test_bootstrap_migrates_saved_slots_from_legacy_data_root(self) -> None:
        legacy_root = Path(self.tempdir.name) / "legacy-data"
        (legacy_root / "accounts" / "account-4").mkdir(parents=True, exist_ok=True)
        (legacy_root / "accounts" / "account-4" / "auth.json").write_text(
            json.dumps(build_auth("legacy@example.com", "Legacy", "acct-legacy", "plus")),
            encoding="utf-8",
        )
        (legacy_root / "state.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "slots": [
                        {
                            "id": "account-4",
                            "label": "旧账号 4",
                            "created_at": "2026-03-25T00:00:00+00:00",
                            "updated_at": "2026-03-25T00:00:00+00:00",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        migrated_paths = AuthHubPaths(
            data_root=Path(self.tempdir.name) / "migrated-data",
            state_path=Path(self.tempdir.name) / "migrated-data" / "state.json",
            accounts_root=Path(self.tempdir.name) / "migrated-data" / "accounts",
            active_auth_path=self.paths.active_auth_path,
        )

        self.legacy_candidates_patcher.stop()
        with patch.dict("os.environ", {LEGACY_DATA_ROOT_ENV_VAR: str(legacy_root)}):
            migrated_hub = AuthHub(migrated_paths)
        self.legacy_candidates_patcher.start()

        slot = migrated_hub.slot_overview("account-4")
        self.assertTrue(migrated_hub.slot_auth_path("account-4").exists())
        self.assertEqual(slot["label"], "旧账号 4")
        self.assertEqual(slot["snapshot"]["email"], "legacy@example.com")


if __name__ == "__main__":
    unittest.main()
