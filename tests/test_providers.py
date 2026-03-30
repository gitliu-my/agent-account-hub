from __future__ import annotations

import base64
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from codex_account_hub.core import AuthHubPaths
from codex_account_hub.providers import (
    ClaudeCodeBackend,
    ClaudeCodeHub,
    ClaudeCodeHubPaths,
    ClaudeUsageClient,
    ClaudeUsageFetchError,
    ClaudeUsageSessionStore,
    CodexUsageClient,
    CodexUsageFetchError,
    CodexUsageHub,
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


def encode_segment(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def fake_jwt(payload: dict) -> str:
    return ".".join([encode_segment({"alg": "none"}), encode_segment(payload), "signature"])


def build_codex_auth(
    email: str,
    name: str,
    account_id: str,
    plan_type: str,
    *,
    access_token: str,
) -> dict:
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
    jwt_access_token = fake_jwt(
        {
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
            "access_token": access_token or jwt_access_token,
            "refresh_token": "refresh-token",
            "account_id": account_id,
        },
        "last_refresh": "2026-03-30T10:00:00Z",
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


class FakeClaudeUsageSessionStore(ClaudeUsageSessionStore):
    def __init__(self) -> None:
        self.secrets: dict[str, str] = {}

    def read_optional(self, account_id: str) -> str | None:
        return self.secrets.get(account_id)

    def read(self, account_id: str) -> str:
        secret = self.read_optional(account_id)
        if secret is None:
            raise RuntimeError(f"missing secret for {account_id}")
        return secret

    def write(self, account_id: str, session_key: str) -> None:
        self.secrets[account_id] = session_key

    def delete(self, account_id: str) -> None:
        self.secrets.pop(account_id, None)


class FakeClaudeUsageClient(ClaudeUsageClient):
    def __init__(self) -> None:
        self.responses: dict[tuple[str, str], dict] = {}
        self.errors: dict[tuple[str, str], Exception] = {}
        self.calls: list[tuple[str, str]] = []

    def fetch_usage(self, session_key: str, organization_id: str) -> dict:
        key = (session_key, organization_id)
        self.calls.append(key)
        if key in self.errors:
            raise self.errors[key]
        return copy.deepcopy(self.responses[key])


class FakeCodexUsageClient(CodexUsageClient):
    def __init__(self) -> None:
        self.responses: dict[str, dict] = {}
        self.errors: dict[str, Exception] = {}
        self.calls: list[str] = []

    def fetch_usage(self, access_token: str) -> dict:
        self.calls.append(access_token)
        if access_token in self.errors:
            raise self.errors[access_token]
        return copy.deepcopy(self.responses[access_token])


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
        self.session_store = FakeClaudeUsageSessionStore()
        self.usage_client = FakeClaudeUsageClient()
        self.hub = ClaudeCodeHub(
            self.paths,
            self.backend,
            usage_client=self.usage_client,
            session_store=self.session_store,
        )

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

    def test_set_usage_auth_refreshes_and_persists_usage_cache(self) -> None:
        self.hub.create_account_from_current()
        self.usage_client.responses[("session-one", "org-usage-one")] = {
            "five_hour_percent": 23.4,
            "five_hour_reset_at": "2026-03-30T12:00:00Z",
            "seven_day_percent": 61.0,
            "seven_day_reset_at": "2026-04-02T12:00:00Z",
            "seven_day_opus_percent": 12.0,
            "seven_day_sonnet_percent": 48.0,
        }

        account = self.hub.set_usage_auth("account-1", "session-one", "org-usage-one", "Main Org")

        self.assertEqual(self.session_store.secrets["account-1"], "session-one")
        self.assertTrue(account["usage_auth"]["configured"])
        self.assertEqual(account["usage_auth"]["organization_id"], "org-usage-one")
        self.assertEqual(account["usage_auth"]["organization_name"], "Main Org")
        self.assertEqual(account["usage"]["status"], "ok")
        self.assertEqual(account["usage"]["five_hour_percent"], 23.4)
        self.assertEqual(account["usage"]["seven_day_percent"], 61.0)
        self.assertEqual(self.hub.current_overview()["usage"]["status"], "ok")

    def test_refresh_usage_marks_unauthorized_when_session_expires(self) -> None:
        self.hub.create_account_from_current()
        self.usage_client.responses[("session-one", "org-usage-one")] = {
            "five_hour_percent": 12.0,
            "five_hour_reset_at": "2026-03-30T12:00:00Z",
            "seven_day_percent": 31.0,
            "seven_day_reset_at": "2026-04-02T12:00:00Z",
            "seven_day_opus_percent": 9.0,
            "seven_day_sonnet_percent": 22.0,
        }
        self.hub.set_usage_auth("account-1", "session-one", "org-usage-one", "Main Org")

        self.usage_client.errors[("session-one", "org-usage-one")] = ClaudeUsageFetchError(
            "unauthorized",
            "claude.ai session 已失效",
        )

        account = self.hub.refresh_usage("account-1")

        self.assertEqual(account["usage"]["status"], "unauthorized")
        self.assertIn("已失效", account["usage"]["error"])
        self.assertEqual(account["usage"]["five_hour_percent"], 12.0)
        self.assertIsNotNone(account["usage"]["last_success_at"])

    def test_clear_usage_auth_removes_saved_usage_state(self) -> None:
        self.hub.create_account_from_current()
        self.usage_client.responses[("session-one", "org-usage-one")] = {
            "five_hour_percent": 15.0,
            "five_hour_reset_at": "2026-03-30T12:00:00Z",
            "seven_day_percent": 35.0,
            "seven_day_reset_at": "2026-04-02T12:00:00Z",
            "seven_day_opus_percent": 11.0,
            "seven_day_sonnet_percent": 20.0,
        }
        self.hub.set_usage_auth("account-1", "session-one", "org-usage-one", "Main Org")

        account = self.hub.clear_usage_auth("account-1")

        self.assertNotIn("account-1", self.session_store.secrets)
        self.assertFalse(account["usage_auth"]["configured"])
        self.assertEqual(account["usage"]["status"], "not_configured")

    def test_set_usage_auth_allows_reusing_existing_session_key(self) -> None:
        self.hub.create_account_from_current()
        self.usage_client.responses[("session-one", "org-usage-one")] = {
            "five_hour_percent": 15.0,
            "five_hour_reset_at": "2026-03-30T12:00:00Z",
            "seven_day_percent": 35.0,
            "seven_day_reset_at": "2026-04-02T12:00:00Z",
            "seven_day_opus_percent": 11.0,
            "seven_day_sonnet_percent": 20.0,
        }
        self.usage_client.responses[("session-one", "org-usage-two")] = {
            "five_hour_percent": 18.0,
            "five_hour_reset_at": "2026-03-30T13:00:00Z",
            "seven_day_percent": 40.0,
            "seven_day_reset_at": "2026-04-03T12:00:00Z",
            "seven_day_opus_percent": 14.0,
            "seven_day_sonnet_percent": 26.0,
        }
        self.hub.set_usage_auth("account-1", "session-one", "org-usage-one", "Main Org")

        account = self.hub.set_usage_auth("account-1", "", "org-usage-two", "Second Org")

        self.assertEqual(self.session_store.secrets["account-1"], "session-one")
        self.assertEqual(account["usage_auth"]["organization_id"], "org-usage-two")
        self.assertEqual(account["usage"]["five_hour_percent"], 18.0)

    def test_saved_usage_cache_preserves_cached_percent_values(self) -> None:
        self.hub.create_account_from_current()
        self.session_store.write("account-1", "session-one")
        auth_path = self.paths.accounts_root / "account-1" / "usage_auth.json"
        auth_path.parent.mkdir(parents=True, exist_ok=True)
        auth_path.write_text(
            json.dumps(
                {
                    "organization_id": "org-usage-one",
                    "organization_name": "Main Org",
                    "updated_at": "2026-03-30T12:00:00Z",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        cache_path = self.paths.accounts_root / "account-1" / "usage_cache.json"
        cache_path.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "five_hour_percent": 2.0,
                    "seven_day_percent": 1.0,
                    "seven_day_opus_percent": 4.0,
                    "seven_day_sonnet_percent": 7.0,
                    "last_success_at": "2026-03-30T12:00:00Z",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        usage = self.hub.saved_usage_cache("account-1")

        self.assertEqual(usage["five_hour_percent"], 2.0)
        self.assertEqual(usage["seven_day_percent"], 1.0)
        self.assertEqual(usage["seven_day_opus_percent"], 4.0)
        self.assertEqual(usage["seven_day_sonnet_percent"], 7.0)

    def test_usage_menu_bar_accounts_follow_selected_eligible_accounts(self) -> None:
        self.hub.create_account_from_current()
        self.backend.payload = build_claude_payload("access-two", "refresh-two", subscription_type="max")
        self.write_profile("two@example.com", "org-two", display_name="Two User")
        self.hub.create_account_from_current()

        self.usage_client.responses[("session-one", "org-usage-one")] = {
            "five_hour_percent": 18.0,
            "five_hour_reset_at": "2026-03-30T12:00:00Z",
            "seven_day_percent": 35.0,
            "seven_day_reset_at": "2026-04-02T12:00:00Z",
            "seven_day_opus_percent": 11.0,
            "seven_day_sonnet_percent": 20.0,
        }
        self.usage_client.responses[("session-two", "org-usage-two")] = {
            "five_hour_percent": 52.0,
            "five_hour_reset_at": "2026-03-30T13:00:00Z",
            "seven_day_percent": 68.0,
            "seven_day_reset_at": "2026-04-03T12:00:00Z",
            "seven_day_opus_percent": 21.0,
            "seven_day_sonnet_percent": 34.0,
        }
        self.hub.set_usage_auth("account-1", "session-one", "org-usage-one", "Main Org")
        self.hub.set_usage_auth("account-2", "session-two", "org-usage-two", "Second Org")
        self.hub.set_usage_menu_bar_visible("account-1", True)
        self.hub.set_usage_menu_bar_visible("account-2", True)

        overview = self.hub.overview()

        self.assertEqual(
            [slot["id"] for slot in overview["usage_menu_bar_accounts"]],
            ["account-1", "account-2"],
        )
        self.assertEqual(
            {slot["id"]: slot["active"] for slot in overview["usage_menu_bar_accounts"]},
            {"account-1": False, "account-2": True},
        )
        visibility = {slot["id"]: slot["usage_menu_bar_visible"] for slot in overview["accounts"]}
        self.assertEqual(visibility, {"account-1": True, "account-2": True})

    def test_clear_usage_auth_removes_account_from_menu_bar_selection(self) -> None:
        self.hub.create_account_from_current()
        self.usage_client.responses[("session-one", "org-usage-one")] = {
            "five_hour_percent": 15.0,
            "five_hour_reset_at": "2026-03-30T12:00:00Z",
            "seven_day_percent": 35.0,
            "seven_day_reset_at": "2026-04-02T12:00:00Z",
            "seven_day_opus_percent": 11.0,
            "seven_day_sonnet_percent": 20.0,
        }
        self.hub.set_usage_auth("account-1", "session-one", "org-usage-one", "Main Org")
        self.hub.set_usage_menu_bar_visible("account-1", True)

        account = self.hub.clear_usage_auth("account-1")
        overview = self.hub.overview()

        self.assertFalse(account["usage_menu_bar_visible"])
        self.assertEqual(overview["usage_menu_bar_accounts"], [])
        self.assertFalse(overview["accounts"][0]["usage_menu_bar_visible"])

    def test_unauthorized_usage_is_not_menu_bar_eligible(self) -> None:
        self.hub.create_account_from_current()
        self.usage_client.responses[("session-one", "org-usage-one")] = {
            "five_hour_percent": 12.0,
            "five_hour_reset_at": "2026-03-30T12:00:00Z",
            "seven_day_percent": 31.0,
            "seven_day_reset_at": "2026-04-02T12:00:00Z",
            "seven_day_opus_percent": 9.0,
            "seven_day_sonnet_percent": 22.0,
        }
        self.hub.set_usage_auth("account-1", "session-one", "org-usage-one", "Main Org")
        self.hub.set_usage_menu_bar_visible("account-1", True)
        self.usage_client.errors[("session-one", "org-usage-one")] = ClaudeUsageFetchError(
            "unauthorized",
            "claude.ai session 已失效",
        )

        account = self.hub.refresh_usage("account-1")
        overview = self.hub.overview()

        self.assertFalse(account["usage_menu_bar_eligible"])
        self.assertFalse(account["usage_menu_bar_visible"])
        self.assertEqual(overview["usage_menu_bar_accounts"], [])


class CodexUsageHubTests(unittest.TestCase):
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
        self.usage_client = FakeCodexUsageClient()
        self.hub = CodexUsageHub(paths=self.paths, usage_client=self.usage_client)

    def tearDown(self) -> None:
        self.legacy_candidates_patcher.stop()
        self.tempdir.cleanup()

    def write_active_auth(
        self,
        email: str,
        name: str,
        account_id: str,
        plan_type: str,
        *,
        access_token: str,
    ) -> None:
        self.paths.active_auth_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.active_auth_path.write_text(
            json.dumps(
                build_codex_auth(
                    email,
                    name,
                    account_id,
                    plan_type,
                    access_token=access_token,
                ),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_refresh_usage_uses_saved_access_token_and_persists_cache(self) -> None:
        self.write_active_auth(
            "one@example.com",
            "One",
            "acct-one",
            "plus",
            access_token="access-one",
        )
        self.hub.create_account_from_current()
        self.usage_client.responses["access-one"] = {
            "five_hour_percent": 28.0,
            "five_hour_reset_at": "2026-03-30T12:00:00Z",
            "seven_day_percent": 49.0,
            "seven_day_reset_at": "2026-04-02T12:00:00Z",
            "code_review_seven_day_percent": 0.0,
            "code_review_seven_day_reset_at": "2026-04-05T12:00:00Z",
            "plan_type": "plus",
            "email": "one@example.com",
            "allowed": True,
            "limit_reached": False,
            "credits_balance": "0",
            "credits_unlimited": False,
        }

        account = self.hub.refresh_usage("account-1")

        self.assertEqual(self.usage_client.calls, ["access-one"])
        self.assertTrue(account["usage_auth"]["configured"])
        self.assertEqual(account["usage"]["status"], "ok")
        self.assertEqual(account["usage"]["five_hour_percent"], 28.0)
        self.assertEqual(account["usage"]["seven_day_percent"], 49.0)
        self.assertEqual(account["usage"]["plan_type"], "plus")

    def test_refresh_usage_skips_duplicate_calls_before_next_refresh_window(self) -> None:
        self.write_active_auth(
            "one@example.com",
            "One",
            "acct-one",
            "plus",
            access_token="access-one",
        )
        self.hub.create_account_from_current()
        self.usage_client.responses["access-one"] = {
            "five_hour_percent": 28.0,
            "five_hour_reset_at": "2026-03-30T12:00:00Z",
            "seven_day_percent": 49.0,
            "seven_day_reset_at": "2026-04-02T12:00:00Z",
            "code_review_seven_day_percent": 0.0,
            "code_review_seven_day_reset_at": "2026-04-05T12:00:00Z",
            "plan_type": "plus",
            "email": "one@example.com",
            "allowed": True,
            "limit_reached": False,
            "credits_balance": "0",
            "credits_unlimited": False,
        }

        self.hub.refresh_usage("account-1")
        account = self.hub.refresh_usage("account-1")

        self.assertEqual(self.usage_client.calls, ["access-one"])
        self.assertEqual(account["usage"]["status"], "ok")

    def test_refresh_usage_rate_limit_enters_backoff_without_repeating(self) -> None:
        self.write_active_auth(
            "one@example.com",
            "One",
            "acct-one",
            "plus",
            access_token="access-one",
        )
        self.hub.create_account_from_current()
        self.usage_client.errors["access-one"] = CodexUsageFetchError(
            "rate_limited",
            "Codex 用量接口暂时限制请求频率，稍后再试",
        )

        first = self.hub.refresh_usage("account-1")
        second = self.hub.refresh_usage("account-1")

        self.assertEqual(self.usage_client.calls, ["access-one"])
        self.assertEqual(first["usage"]["status"], "rate_limited")
        self.assertEqual(second["usage"]["status"], "rate_limited")
        self.assertIsNotNone(second["usage"]["next_refresh_at"])

    def test_saved_usage_cache_preserves_cached_percent_values(self) -> None:
        self.write_active_auth(
            "one@example.com",
            "One",
            "acct-one",
            "plus",
            access_token="access-one",
        )
        self.hub.create_account_from_current()
        cache_path = self.paths.accounts_root / "account-1" / "usage_cache.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "five_hour_percent": 2.0,
                    "seven_day_percent": 1.0,
                    "code_review_seven_day_percent": 3.0,
                    "last_success_at": "2026-03-30T12:00:00Z",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        usage = self.hub.saved_usage_cache("account-1")

        self.assertEqual(usage["five_hour_percent"], 2.0)
        self.assertEqual(usage["seven_day_percent"], 1.0)
        self.assertEqual(usage["code_review_seven_day_percent"], 3.0)

    def test_usage_menu_bar_accounts_follow_selected_eligible_accounts(self) -> None:
        self.write_active_auth(
            "one@example.com",
            "One",
            "acct-one",
            "plus",
            access_token="access-one",
        )
        self.hub.create_account_from_current()

        self.write_active_auth(
            "two@example.com",
            "Two",
            "acct-two",
            "plus",
            access_token="access-two",
        )
        self.hub.create_account_from_current()

        self.usage_client.responses["access-one"] = {
            "five_hour_percent": 18.0,
            "five_hour_reset_at": "2026-03-30T12:00:00Z",
            "seven_day_percent": 35.0,
            "seven_day_reset_at": "2026-04-02T12:00:00Z",
            "code_review_seven_day_percent": 0.0,
            "code_review_seven_day_reset_at": "2026-04-05T12:00:00Z",
            "plan_type": "plus",
            "email": "one@example.com",
            "allowed": True,
            "limit_reached": False,
            "credits_balance": "0",
            "credits_unlimited": False,
        }
        self.usage_client.responses["access-two"] = {
            "five_hour_percent": 52.0,
            "five_hour_reset_at": "2026-03-30T13:00:00Z",
            "seven_day_percent": 68.0,
            "seven_day_reset_at": "2026-04-03T12:00:00Z",
            "code_review_seven_day_percent": 10.0,
            "code_review_seven_day_reset_at": "2026-04-05T12:00:00Z",
            "plan_type": "plus",
            "email": "two@example.com",
            "allowed": True,
            "limit_reached": False,
            "credits_balance": "0",
            "credits_unlimited": False,
        }

        self.hub.refresh_usage("account-1")
        self.hub.refresh_usage("account-2")
        self.hub.set_usage_menu_bar_visible("account-1", True)
        self.hub.set_usage_menu_bar_visible("account-2", True)

        overview = self.hub.overview()

        self.assertEqual(
            [slot["id"] for slot in overview["usage_menu_bar_accounts"]],
            ["account-1", "account-2"],
        )
        self.assertEqual(
            {slot["id"]: slot["active"] for slot in overview["usage_menu_bar_accounts"]},
            {"account-1": False, "account-2": True},
        )


class SubprocessClaudeCodeBackendTests(unittest.TestCase):
    def test_resolve_claude_command_checks_common_homebrew_path(self) -> None:
        backend = SubprocessClaudeCodeBackend()
        with patch("codex_account_hub.providers.shutil.which", return_value="/opt/homebrew/bin/claude"):
            self.assertEqual(backend.resolve_claude_command(), "/opt/homebrew/bin/claude")


if __name__ == "__main__":
    unittest.main()
