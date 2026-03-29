from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from codex_account_hub.providers import (
    ClaudeCodeBackend,
    ClaudeCodeHub,
    ClaudeCodeHubPaths,
    SubprocessClaudeCodeBackend,
)


def build_claude_payload(
    access_token: str,
    refresh_token: str,
    *,
    expires_at: int = 1_774_797_891_547,
    subscription_type: str = "pro",
) -> dict:
    return {
        "claudeAiOauth": {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": expires_at,
            "subscriptionType": subscription_type,
            "rateLimitTier": "default_claude_ai",
            "scopes": ["user:profile", "user:sessions:claude_code"],
        }
    }


def build_claude_profile(
    email: str,
    org_id: str,
    *,
    display_name: str = "Claude User",
    organization_name: str | None = None,
) -> dict:
    return {
        "oauthAccount": {
            "accountUuid": f"user-{org_id}",
            "emailAddress": email,
            "organizationUuid": org_id,
            "hasExtraUsageEnabled": False,
            "billingType": "subscription",
            "accountCreatedAt": "2026-03-27T05:57:54.531910Z",
            "subscriptionCreatedAt": "2026-03-29T06:40:08.663063Z",
            "displayName": display_name,
            "organizationRole": "admin",
            "workspaceRole": None,
            "organizationName": organization_name or f"{email}'s Organization",
        }
    }


class FakeClaudeCodeBackend(ClaudeCodeBackend):
    def __init__(self, payload: dict, profiles: dict[str, dict]) -> None:
        self.payload = copy.deepcopy(payload)
        self.profiles = copy.deepcopy(profiles)
        self.account_name = "test-user"

    @property
    def active_auth_path(self) -> str:
        return "keychain://generic-password/Claude Code-credentials"

    def read_secret_payload(self) -> tuple[dict, str | None]:
        return copy.deepcopy(self.payload), self.account_name

    def write_secret_payload(self, payload: dict, account_name: str | None = None) -> None:
        self.payload = copy.deepcopy(payload)
        if account_name:
            self.account_name = account_name

    def status(self) -> dict:
        access_token = self.payload["claudeAiOauth"]["accessToken"]
        return copy.deepcopy(self.profiles[access_token])


class ClaudeCodeHubTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.paths = ClaudeCodeHubPaths(
            data_root=root / "data",
            state_path=root / "data" / "state.json",
            accounts_root=root / "data" / "accounts",
            profile_path=root / "profile.json",
        )
        self.backend = FakeClaudeCodeBackend(
            build_claude_payload("access-one", "refresh-one"),
            {
                "access-one": {
                    "loggedIn": True,
                    "authMethod": "claude.ai",
                    "apiProvider": "firstParty",
                    "email": "one@example.com",
                    "orgId": "org-one",
                    "orgName": "One Org",
                    "subscriptionType": "pro",
                },
                "access-one-refreshed": {
                    "loggedIn": True,
                    "authMethod": "claude.ai",
                    "apiProvider": "firstParty",
                    "email": "one@example.com",
                    "orgId": "org-one",
                    "orgName": "One Org",
                    "subscriptionType": "pro",
                },
                "access-two": {
                    "loggedIn": True,
                    "authMethod": "claude.ai",
                    "apiProvider": "firstParty",
                    "email": "two@example.com",
                    "orgId": "org-two",
                    "orgName": "Two Org",
                    "subscriptionType": "max",
                },
            },
        )
        self.write_profile("one@example.com", "org-one", display_name="One User")
        self.hub = ClaudeCodeHub(self.paths, self.backend)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def write_profile(self, email: str, org_id: str, *, display_name: str = "Claude User") -> None:
        self.paths.profile_path.write_text(
            json.dumps(build_claude_profile(email, org_id, display_name=display_name), ensure_ascii=False),
            encoding="utf-8",
        )

    def test_create_account_from_current_adds_dynamic_saved_account(self) -> None:
        payload = self.hub.create_account_from_current()

        self.assertTrue(payload["created_new_account"])
        overview = self.hub.overview()
        self.assertEqual(overview["current"]["matched_account_id"], "account-1")
        self.assertEqual(overview["accounts"][0]["snapshot"]["email"], "one@example.com")

    def test_current_overview_auto_syncs_matching_saved_account(self) -> None:
        self.hub.create_account_from_current()
        before_hash = self.hub.account_overview("account-1")["snapshot"]["hash"]

        self.backend.payload = build_claude_payload(
            "access-one-refreshed",
            "refresh-one-refreshed",
            expires_at=1_874_797_891_547,
        )
        self.write_profile("one@example.com", "org-one", display_name="One User")

        current = self.hub.current_overview()
        account = self.hub.account_overview("account-1")

        self.assertEqual(current["matched_account_id"], "account-1")
        self.assertEqual(current["snapshot_sync_status"], "updated")
        self.assertTrue(current["snapshot_sync_updated"])
        self.assertNotEqual(before_hash, account["snapshot"]["hash"])
        self.assertEqual(account["snapshot"]["email"], "one@example.com")

    def test_switch_replaces_active_credentials(self) -> None:
        self.hub.create_account_from_current()

        self.backend.payload = build_claude_payload("access-two", "refresh-two", subscription_type="max")
        self.write_profile("two@example.com", "org-two", display_name="Two User")
        self.hub.create_account_from_current()

        self.hub.switch("account-1")
        current = self.hub.current_overview()

        self.assertEqual(current["email"], "one@example.com")
        self.assertEqual(current["matched_account_id"], "account-1")
        self.assertEqual(current["plan_type"], "pro")
        self.assertEqual(current["name"], "One User")

    def test_custom_label_survives_snapshot_updates(self) -> None:
        self.hub.create_account_from_current()
        self.hub.rename_slot("account-1", "Claude 主号")

        self.backend.payload = build_claude_payload(
            "access-one-refreshed",
            "refresh-one-refreshed",
            expires_at=1_874_797_891_547,
        )
        self.write_profile("one@example.com", "org-one", display_name="One User")
        self.hub.save_current_to_account("account-1")

        account = self.hub.account_overview("account-1")
        self.assertEqual(account["label"], "Claude 主号")
        self.assertEqual(account["snapshot"]["email"], "one@example.com")
        self.assertEqual(self.hub.current_overview()["matched_account_label"], "Claude 主号")

    def test_switch_updates_profile_oauth_account(self) -> None:
        self.hub.create_account_from_current()

        self.backend.payload = build_claude_payload("access-two", "refresh-two", subscription_type="max")
        self.write_profile("two@example.com", "org-two", display_name="Two User")
        self.hub.create_account_from_current()

        self.hub.switch("account-1")

        profile = json.loads(self.paths.profile_path.read_text(encoding="utf-8"))
        self.assertEqual(profile["oauthAccount"]["emailAddress"], "one@example.com")
        self.assertEqual(profile["oauthAccount"]["organizationUuid"], "org-one")

    def test_switch_uses_profile_backup_when_saved_summary_lacks_oauth_account(self) -> None:
        self.hub.create_account_from_current()

        summary_path = self.paths.accounts_root / "account-1" / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary.pop("oauth_account", None)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")

        backup_path = self.paths.profile_path.with_name(f"{self.paths.profile_path.name}.backup")
        backup_path.write_text(
            json.dumps(build_claude_profile("one@example.com", "org-one", display_name="One User"), ensure_ascii=False),
            encoding="utf-8",
        )

        self.backend.payload = build_claude_payload("access-two", "refresh-two", subscription_type="max")
        self.write_profile("two@example.com", "org-two", display_name="Two User")
        self.hub.create_account_from_current()

        self.hub.switch("account-1")

        profile = json.loads(self.paths.profile_path.read_text(encoding="utf-8"))
        self.assertEqual(profile["oauthAccount"]["emailAddress"], "one@example.com")


class SubprocessClaudeCodeBackendTests(unittest.TestCase):
    def test_resolve_claude_command_checks_common_homebrew_path(self) -> None:
        backend = SubprocessClaudeCodeBackend()
        with patch("codex_account_hub.providers.shutil.which", return_value="/opt/homebrew/bin/claude"):
            self.assertEqual(backend.resolve_claude_command(), "/opt/homebrew/bin/claude")


if __name__ == "__main__":
    unittest.main()
