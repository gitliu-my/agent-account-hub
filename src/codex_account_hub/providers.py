from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core import (
    AuthHub,
    AuthHubError,
    PROJECT_ROOT,
    atomic_write_json,
    default_data_root,
    default_state,
    is_placeholder_account_label,
    load_json_file,
    sha256_file,
    suggested_account_label,
    utc_now_iso,
)


CLAUDE_CODE_PROVIDER_ID = "claude-code"
CLAUDE_CODE_PROVIDER_LABEL = "Claude Code"
DEFAULT_CLAUDE_CODE_KEYCHAIN_SERVICE = "Claude Code-credentials"
DEFAULT_CLAUDE_PROFILE_PATH = Path.home() / ".claude.json"


def provider_label(provider: str) -> str:
    normalized = normalize_provider_name(provider)
    return "Codex" if normalized == "codex" else CLAUDE_CODE_PROVIDER_LABEL


def normalize_provider_name(value: str | None) -> str:
    normalized = (value or "codex").strip().lower().replace("_", "-")
    if normalized in {"codex", "openai", "codex-cli"}:
        return "codex"
    if normalized in {"claude", "claude-code", "claudecode"}:
        return CLAUDE_CODE_PROVIDER_ID
    raise AuthHubError(f"unsupported provider: {value}")


def timestamp_ms_to_iso(value: Any) -> str | None:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return utc_from_timestamp_ms(numeric)


def utc_from_timestamp_ms(value: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def sha256_json_payload(payload: dict[str, Any]) -> str:
    import hashlib

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def default_claude_code_data_root() -> Path:
    return default_data_root() / "providers" / CLAUDE_CODE_PROVIDER_ID


def empty_claude_summary(path: str, *, exists: bool = False) -> dict[str, Any]:
    return {
        "path": path,
        "exists": exists,
        "status": "missing" if not exists else "invalid",
        "hash": None,
        "auth_mode": None,
        "account_id": None,
        "name": None,
        "email": None,
        "plan_type": None,
        "last_refresh": None,
        "expires_at": None,
        "id_expires_at": None,
        "access_expires_at": None,
        "has_id_token": False,
        "has_access_token": False,
        "has_refresh_token": False,
        "error": None,
        "org_id": None,
        "org_name": None,
        "logged_in": None,
        "api_provider": None,
        "scopes": [],
        "rate_limit_tier": None,
        "keychain_account_name": None,
        "oauth_account": None,
    }


def claude_summary_from_payload(
    payload: dict[str, Any],
    *,
    path: str,
    status_payload: dict[str, Any] | None = None,
    keychain_account_name: str | None = None,
    oauth_account: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = empty_claude_summary(path, exists=True)
    summary["status"] = "ready"
    summary["hash"] = sha256_json_payload(payload)

    oauth_payload = payload.get("claudeAiOauth") if isinstance(payload.get("claudeAiOauth"), dict) else {}
    access_token = oauth_payload.get("accessToken")
    refresh_token = oauth_payload.get("refreshToken")
    access_expires_at = timestamp_ms_to_iso(oauth_payload.get("expiresAt"))

    summary["auth_mode"] = (
        status_payload.get("authMethod")
        if isinstance(status_payload, dict)
        else None
    ) or ("claude.ai" if oauth_payload else None)
    summary["email"] = (
        status_payload.get("email") if isinstance(status_payload, dict) else None
    ) or (oauth_account.get("emailAddress") if isinstance(oauth_account, dict) else None)
    summary["name"] = oauth_account.get("displayName") if isinstance(oauth_account, dict) else None
    summary["account_id"] = (
        status_payload.get("orgId") if isinstance(status_payload, dict) else None
    ) or (oauth_account.get("organizationUuid") if isinstance(oauth_account, dict) else None)
    summary["org_id"] = summary["account_id"]
    summary["org_name"] = (
        status_payload.get("orgName") if isinstance(status_payload, dict) else None
    ) or (oauth_account.get("organizationName") if isinstance(oauth_account, dict) else None)
    summary["logged_in"] = status_payload.get("loggedIn") if isinstance(status_payload, dict) else None
    summary["api_provider"] = status_payload.get("apiProvider") if isinstance(status_payload, dict) else None
    summary["plan_type"] = oauth_payload.get("subscriptionType") or (
        status_payload.get("subscriptionType") if isinstance(status_payload, dict) else None
    )
    summary["rate_limit_tier"] = oauth_payload.get("rateLimitTier")
    summary["access_expires_at"] = access_expires_at
    summary["expires_at"] = access_expires_at
    summary["has_access_token"] = bool(access_token)
    summary["has_refresh_token"] = bool(refresh_token)
    summary["scopes"] = list(oauth_payload.get("scopes") or [])
    summary["keychain_account_name"] = keychain_account_name
    summary["oauth_account"] = oauth_account if isinstance(oauth_account, dict) else None
    return summary


def claude_oauth_account_from_profile(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    oauth_account = payload.get("oauthAccount")
    return oauth_account if isinstance(oauth_account, dict) else None


def claude_oauth_account_matches(summary: dict[str, Any], oauth_account: dict[str, Any] | None) -> bool:
    if not isinstance(oauth_account, dict):
        return False
    summary_email = str(summary.get("email") or "").strip().lower()
    summary_org_id = str(summary.get("org_id") or summary.get("account_id") or "").strip()
    oauth_email = str(oauth_account.get("emailAddress") or "").strip().lower()
    oauth_org_id = str(oauth_account.get("organizationUuid") or "").strip()

    if summary_email and oauth_email != summary_email:
        return False
    if summary_org_id and oauth_org_id != summary_org_id:
        return False
    return bool(summary_email or summary_org_id)


def claude_identity_key(summary: dict[str, Any]) -> str | None:
    if summary.get("status") != "ready":
        return None
    email = summary.get("email")
    if isinstance(email, str) and email.strip():
        return f"email:{email.strip().lower()}"
    org_id = summary.get("org_id") or summary.get("account_id")
    if isinstance(org_id, str) and org_id.strip():
        return f"org_id:{org_id.strip()}"
    file_hash = summary.get("hash")
    if isinstance(file_hash, str) and file_hash:
        return f"hash:{file_hash}"
    return None


class ClaudeCodeBackend:
    def read_secret_payload(self) -> tuple[dict[str, Any], str | None]:
        raise NotImplementedError

    def write_secret_payload(self, payload: dict[str, Any], account_name: str | None = None) -> None:
        raise NotImplementedError

    def status(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def active_auth_path(self) -> str:
        raise NotImplementedError


class SubprocessClaudeCodeBackend(ClaudeCodeBackend):
    EXTRA_CLAUDE_PATH_ENTRIES = ("/opt/homebrew/bin", "/usr/local/bin")

    def __init__(
        self,
        service_name: str = DEFAULT_CLAUDE_CODE_KEYCHAIN_SERVICE,
        default_account_name: str | None = None,
        claude_command: str = "claude",
    ) -> None:
        self.service_name = service_name
        self.default_account_name = default_account_name or os.environ.get("USER")
        self.claude_command = claude_command

    @property
    def active_auth_path(self) -> str:
        return f"keychain://generic-password/{self.service_name}"

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=False,
                env=self._command_env(),
            )
        except OSError as exc:
            raise AuthHubError(f"failed to run {' '.join(args)}: {exc}") from exc

    def _command_env(self) -> dict[str, str]:
        env = os.environ.copy()
        path_entries = [entry for entry in env.get("PATH", "").split(os.pathsep) if entry]
        seen_entries = set(path_entries)
        for candidate in self.EXTRA_CLAUDE_PATH_ENTRIES:
            if candidate not in seen_entries:
                path_entries.append(candidate)
                seen_entries.add(candidate)
        env["PATH"] = os.pathsep.join(path_entries)
        return env

    def resolve_claude_command(self) -> str:
        raw_command = self.claude_command.strip()
        if not raw_command:
            raise AuthHubError("claude command must not be empty")

        expanded_path = Path(raw_command).expanduser()
        if expanded_path.is_file():
            return str(expanded_path)

        resolved = shutil.which(raw_command, path=self._command_env().get("PATH"))
        if resolved:
            return resolved

        searched = ", ".join(self.EXTRA_CLAUDE_PATH_ENTRIES)
        raise AuthHubError(
            f"claude executable not found; checked PATH and common install paths: {searched}"
        )

    def read_secret_payload(self) -> tuple[dict[str, Any], str | None]:
        account_name = self.read_account_name()
        args = ["security", "find-generic-password", "-w", "-s", self.service_name]
        if account_name:
            args.extend(["-a", account_name])
        result = self._run(args)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise AuthHubError(message or f"Claude Code credentials not found in Keychain: {self.service_name}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AuthHubError("Claude Code Keychain secret is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise AuthHubError("Claude Code Keychain secret must be a JSON object")
        return payload, account_name

    def read_account_name(self) -> str | None:
        result = self._run(["security", "find-generic-password", "-s", self.service_name])
        if result.returncode != 0:
            return self.default_account_name
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        match = re.search(r'"acct"<blob>="([^"]*)"', output)
        if match:
            return match.group(1)
        return self.default_account_name

    def write_secret_payload(self, payload: dict[str, Any], account_name: str | None = None) -> None:
        resolved_account_name = account_name or self.read_account_name() or self.default_account_name or "claude-code"
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        result = self._run(
            [
                "security",
                "add-generic-password",
                "-U",
                "-s",
                self.service_name,
                "-a",
                resolved_account_name,
                "-w",
                raw,
            ]
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise AuthHubError(message or f"failed to update Keychain item: {self.service_name}")

    def status(self) -> dict[str, Any]:
        result = self._run([self.resolve_claude_command(), "auth", "status"])
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise AuthHubError(message or "claude auth status failed")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AuthHubError("claude auth status did not return valid JSON") from exc
        if not isinstance(payload, dict):
            raise AuthHubError("claude auth status did not return a JSON object")
        return payload


@dataclass(frozen=True)
class ClaudeCodeHubPaths:
    data_root: Path
    state_path: Path
    accounts_root: Path
    profile_path: Path = DEFAULT_CLAUDE_PROFILE_PATH

    @classmethod
    def defaults(cls) -> "ClaudeCodeHubPaths":
        data_root = default_claude_code_data_root()
        return cls(
            data_root=data_root,
            state_path=data_root / "state.json",
            accounts_root=data_root / "accounts",
            profile_path=DEFAULT_CLAUDE_PROFILE_PATH,
        )


class ClaudeCodeHub:
    def __init__(
        self,
        paths: ClaudeCodeHubPaths | None = None,
        backend: ClaudeCodeBackend | None = None,
    ) -> None:
        self.paths = paths or ClaudeCodeHubPaths.defaults()
        self.backend = backend or SubprocessClaudeCodeBackend()
        self.paths.data_root.mkdir(parents=True, exist_ok=True)
        self.paths.accounts_root.mkdir(parents=True, exist_ok=True)

    def account_secret_path(self, account_id: str) -> Path:
        return self.paths.accounts_root / account_id / "credentials.json"

    def account_summary_path(self, account_id: str) -> Path:
        return self.paths.accounts_root / account_id / "summary.json"

    def load_state(self) -> dict[str, Any]:
        if not self.paths.state_path.is_file():
            state = default_state()
            self.save_state(state)
            return state

        state = load_json_file(self.paths.state_path)
        accounts_payload = state.get("accounts")
        if not isinstance(accounts_payload, list):
            raise AuthHubError(f"{self.paths.state_path} is missing a valid accounts array")

        normalized_accounts = self._normalize_accounts(accounts_payload)
        normalized_state = {"version": 2, "accounts": normalized_accounts}
        if state.get("version") != 2 or state.get("accounts") != normalized_accounts:
            self.save_state(normalized_state)
        return normalized_state

    def save_state(self, state: dict[str, Any]) -> None:
        atomic_write_json(self.paths.state_path, state)

    def _normalize_accounts(self, accounts_payload: list[Any]) -> list[dict[str, Any]]:
        normalized_accounts: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for item in accounts_payload:
            if not isinstance(item, dict):
                continue

            account_id = str(item.get("id") or "").strip()
            if not account_id or account_id in seen_ids:
                continue

            secret_path = self.account_secret_path(account_id)
            if not secret_path.is_file():
                continue

            snapshot = self.saved_account_summary(account_id)
            existing_label = str(item.get("label") or "").strip()
            normalized_accounts.append(
                {
                    "id": account_id,
                    "label": suggested_account_label(snapshot, len(normalized_accounts) + 1)
                    if is_placeholder_account_label(existing_label, account_id)
                    else existing_label,
                    "created_at": item.get("created_at"),
                    "updated_at": item.get("updated_at"),
                }
            )
            seen_ids.add(account_id)

        return normalized_accounts

    def next_account_id(self) -> str:
        existing_ids = {str(account.get("id")) for account in self.load_state()["accounts"]}
        next_index = 1
        while True:
            candidate = f"account-{next_index}"
            if candidate not in existing_ids:
                return candidate
            next_index += 1

    def get_account(self, account_id: str) -> dict[str, Any]:
        for account in self.load_state()["accounts"]:
            if account.get("id") == account_id:
                return account
        raise AuthHubError(f"account {account_id} not found")

    def update_account(self, account_id: str, **updates: Any) -> dict[str, Any]:
        state = self.load_state()
        for account in state["accounts"]:
            if account.get("id") == account_id:
                account.update(updates)
                self.save_state(state)
                return account
        raise AuthHubError(f"account {account_id} not found")

    def rename_account(self, account_id: str, label: str) -> dict[str, Any]:
        if not label.strip():
            raise AuthHubError("label must not be empty")
        return self.update_account(account_id, label=label.strip())

    def rename_slot(self, slot_id: str, label: str) -> dict[str, Any]:
        return self.rename_account(slot_id, label)

    def _current_secret_payload(self) -> tuple[dict[str, Any], str | None]:
        return self.backend.read_secret_payload()

    def load_profile_payload(self, path: Path | None = None) -> dict[str, Any] | None:
        profile_path = path or self.paths.profile_path
        if not profile_path.is_file():
            return None
        try:
            return load_json_file(profile_path)
        except (OSError, json.JSONDecodeError, AuthHubError):
            return None

    def profile_backup_paths(self) -> list[Path]:
        candidates: list[Path] = []
        sibling_backup = self.paths.profile_path.with_name(f"{self.paths.profile_path.name}.backup")
        if sibling_backup.is_file():
            candidates.append(sibling_backup)

        backups_root = self.paths.profile_path.parent / ".claude" / "backups"
        if backups_root.is_dir():
            candidates.extend(sorted(backups_root.glob(f"{self.paths.profile_path.name}.backup*"), reverse=True))

        unique_paths: list[Path] = []
        seen: set[Path] = set()
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            unique_paths.append(path)
        return unique_paths

    def resolve_oauth_account(self, summary: dict[str, Any]) -> dict[str, Any] | None:
        direct_oauth_account = summary.get("oauth_account")
        if claude_oauth_account_matches(summary, direct_oauth_account):
            return direct_oauth_account

        for path in [self.paths.profile_path, *self.profile_backup_paths()]:
            oauth_account = claude_oauth_account_from_profile(self.load_profile_payload(path))
            if claude_oauth_account_matches(summary, oauth_account):
                return oauth_account
        return None

    def write_profile_oauth_account(self, oauth_account: dict[str, Any] | None) -> None:
        if not isinstance(oauth_account, dict):
            return
        profile_payload = self.load_profile_payload() or {}
        profile_payload["oauthAccount"] = oauth_account
        atomic_write_json(self.paths.profile_path, profile_payload)

    def current_summary(self) -> dict[str, Any]:
        path = self.backend.active_auth_path
        try:
            payload, keychain_account_name = self._current_secret_payload()
        except AuthHubError as exc:
            summary = empty_claude_summary(path, exists=False)
            summary["error"] = str(exc)
            return summary

        try:
            status_payload = self.backend.status()
        except AuthHubError as exc:
            status_payload = None
            status_error = str(exc)
        else:
            status_error = None

        oauth_account = claude_oauth_account_from_profile(self.load_profile_payload())
        summary = claude_summary_from_payload(
            payload,
            path=path,
            status_payload=status_payload,
            keychain_account_name=keychain_account_name,
            oauth_account=oauth_account,
        )
        if status_error:
            summary["error"] = status_error
        return summary

    def saved_account_summary(self, account_id: str) -> dict[str, Any]:
        secret_path = self.account_secret_path(account_id)
        if not secret_path.is_file():
            return empty_claude_summary(str(secret_path), exists=False)

        try:
            payload = load_json_file(secret_path)
        except (OSError, json.JSONDecodeError, AuthHubError) as exc:
            summary = empty_claude_summary(str(secret_path), exists=True)
            summary["status"] = "invalid"
            summary["error"] = str(exc)
            summary["hash"] = sha256_file(secret_path)
            return summary

        summary = claude_summary_from_payload(payload, path=str(secret_path))
        summary["hash"] = sha256_file(secret_path)

        summary_path = self.account_summary_path(account_id)
        if summary_path.is_file():
            try:
                stored_summary = load_json_file(summary_path)
            except (OSError, json.JSONDecodeError, AuthHubError):
                stored_summary = {}
            for key, value in stored_summary.items():
                if key in {"path", "exists", "status", "hash", "error"}:
                    continue
                if value not in (None, "", []):
                    summary[key] = value
        return summary

    def current_account_id(self, current_summary: dict[str, Any] | None = None) -> str | None:
        current_summary = current_summary or self.current_summary()
        current_hash = current_summary.get("hash")
        if current_hash:
            for account in self.load_state()["accounts"]:
                account_id = str(account["id"])
                if sha256_file(self.account_secret_path(account_id)) == current_hash:
                    return account_id

        current_identity = claude_identity_key(current_summary)
        if not current_identity:
            return None
        return self.find_account_id_by_identity(current_identity)

    def current_overview(self, sync_result: dict[str, Any] | None = None) -> dict[str, Any]:
        if sync_result is None:
            sync_result = self.sync_current_account_snapshot()
        current = self.current_summary()
        matched_account_id = self.current_account_id(current_summary=current)
        current["matched_account_id"] = matched_account_id
        current["matched_slot_id"] = matched_account_id
        current["matched_account_label"] = self.account_label(matched_account_id)
        current["snapshot_sync_status"] = sync_result.get("status")
        current["snapshot_sync_updated"] = bool(sync_result.get("updated"))
        current["snapshot_sync_account_id"] = sync_result.get("account_id") or matched_account_id
        return current

    def overview(self) -> dict[str, Any]:
        sync_result = self.sync_current_account_snapshot()
        current = self.current_summary()
        matched_account_id = self.current_account_id(current_summary=current)
        accounts = []
        for account in self.load_state()["accounts"]:
            account_id = str(account["id"])
            snapshot = self.saved_account_summary(account_id)
            accounts.append(
                {
                    **account,
                    "snapshot": snapshot,
                    "active": account_id == matched_account_id,
                }
            )
        return {
            "active_auth_path": self.backend.active_auth_path,
            "current": self.current_overview(sync_result=sync_result),
            "accounts": accounts,
            "slots": list(accounts),
            "project_root": str(PROJECT_ROOT),
            "data_root": str(self.paths.data_root),
        }

    def find_account_id_by_identity(self, identity_key: str) -> str | None:
        for account in self.load_state()["accounts"]:
            account_id = str(account["id"])
            summary = self.saved_account_summary(account_id)
            if claude_identity_key(summary) == identity_key:
                return account_id
        return None

    def account_label(self, account_id: str | None) -> str | None:
        if not account_id:
            return None
        try:
            account = self.get_account(account_id)
        except AuthHubError:
            return None
        snapshot = self.saved_account_summary(account_id)
        existing_label = str(account.get("label") or "").strip()
        if snapshot.get("exists") and is_placeholder_account_label(existing_label, account_id):
            return suggested_account_label(snapshot)
        return existing_label or (suggested_account_label(snapshot) if snapshot.get("exists") else account_id)

    def account_overview(self, account_id: str) -> dict[str, Any]:
        account = dict(self.get_account(account_id))
        snapshot = self.saved_account_summary(account_id)
        current_account_id = self.current_account_id()
        account["snapshot"] = snapshot
        account["active"] = account_id == current_account_id
        return account

    def _write_snapshot(
        self,
        payload: dict[str, Any],
        summary: dict[str, Any],
        account_id: str,
        *,
        allow_create: bool,
    ) -> dict[str, Any]:
        state = self.load_state()
        account: dict[str, Any] | None = None
        for item in state["accounts"]:
            if item.get("id") == account_id:
                account = item
                break

        now = utc_now_iso()
        account_label = suggested_account_label(summary, len(state["accounts"]) + 1)
        if account is None:
            if not allow_create:
                raise AuthHubError(f"account {account_id} not found")
            account = {
                "id": account_id,
                "label": account_label,
                "created_at": now,
                "updated_at": now,
            }
            state["accounts"].append(account)
        else:
            existing_label = str(account.get("label") or "").strip()
            account["label"] = (
                account_label if is_placeholder_account_label(existing_label, account_id) else existing_label
            )
            account["created_at"] = account.get("created_at") or now
            account["updated_at"] = now

        self.save_state(state)

        secret_path = self.account_secret_path(account_id)
        summary_path = self.account_summary_path(account_id)
        atomic_write_json(secret_path, payload)
        atomic_write_json(summary_path, summary)

        account_payload = self.account_overview(account_id)
        account_payload["cleared_account_ids"] = self._clear_duplicate_accounts(account_id)
        account_payload["cleared_slot_ids"] = list(account_payload["cleared_account_ids"])
        return account_payload

    def create_account_from_current(self) -> dict[str, Any]:
        current_summary = self.current_summary()
        if not current_summary.get("exists"):
            raise AuthHubError("Claude Code credentials not found in Keychain")

        payload, _ = self._current_secret_payload()
        current_identity = claude_identity_key(current_summary)
        if current_identity:
            existing_id = self.find_account_id_by_identity(current_identity)
            if existing_id:
                snapshot = self._write_snapshot(payload, current_summary, existing_id, allow_create=False)
                snapshot["created_new_account"] = False
                return snapshot

        account_id = self.next_account_id()
        snapshot = self._write_snapshot(payload, current_summary, account_id, allow_create=True)
        snapshot["created_new_account"] = True
        return snapshot

    def save_current_to_account(self, account_id: str) -> dict[str, Any]:
        current_summary = self.current_summary()
        if not current_summary.get("exists"):
            raise AuthHubError("Claude Code credentials not found in Keychain")
        payload, _ = self._current_secret_payload()
        return self._write_snapshot(payload, current_summary, account_id, allow_create=False)

    def import_file(self, account_id: str, credentials_path: Path) -> dict[str, Any]:
        if not credentials_path.is_file():
            raise AuthHubError(f"credentials snapshot not found: {credentials_path}")
        payload = load_json_file(credentials_path)
        summary = claude_summary_from_payload(payload, path=str(credentials_path))
        return self._write_snapshot(payload, summary, account_id, allow_create=True)

    def switch(self, account_id: str) -> dict[str, Any]:
        secret_path = self.account_secret_path(account_id)
        if not secret_path.is_file():
            raise AuthHubError(f"account {account_id} has no saved credentials snapshot")
        payload = load_json_file(secret_path)
        account_summary = self.saved_account_summary(account_id)
        self.backend.write_secret_payload(payload, account_summary.get("keychain_account_name"))
        self.write_profile_oauth_account(self.resolve_oauth_account(account_summary))
        account = self.get_account(account_id)
        self.update_account(
            account_id,
            created_at=account.get("created_at") or utc_now_iso(),
            updated_at=account.get("updated_at") or utc_now_iso(),
        )
        return self.current_overview()

    def delete_account(self, account_id: str) -> dict[str, Any]:
        account = dict(self.get_account(account_id))
        secret_path = self.account_secret_path(account_id)
        summary_path = self.account_summary_path(account_id)
        if secret_path.exists():
            secret_path.unlink()
        if summary_path.exists():
            summary_path.unlink()
        parent = secret_path.parent
        if parent.exists():
            shutil.rmtree(parent, ignore_errors=True)
        state = self.load_state()
        state["accounts"] = [item for item in state["accounts"] if item.get("id") != account_id]
        self.save_state(state)
        return {"id": account_id, "label": account.get("label") or account_id, "deleted": True}

    def sync_current_account_snapshot(self) -> dict[str, Any]:
        result = {"account_id": None, "status": "not_saved", "updated": False}
        current_summary = self.current_summary()
        if not current_summary.get("exists"):
            result["status"] = "missing"
            return result
        if current_summary.get("status") != "ready":
            result["status"] = "invalid"
            return result

        current_identity = claude_identity_key(current_summary)
        if not current_identity:
            result["status"] = "unidentifiable"
            return result

        account_id = self.find_account_id_by_identity(current_identity)
        if not account_id:
            return result

        result["account_id"] = account_id
        snapshot_hash = sha256_file(self.account_secret_path(account_id))
        current_hash = current_summary.get("hash")
        if snapshot_hash and current_hash and snapshot_hash == current_hash:
            result["status"] = "up_to_date"
            return result

        payload, _ = self._current_secret_payload()
        self._write_snapshot(payload, current_summary, account_id, allow_create=False)
        result["status"] = "updated"
        result["updated"] = True
        return result

    def _clear_duplicate_accounts(self, target_account_id: str) -> list[str]:
        target_summary = self.saved_account_summary(target_account_id)
        target_identity = claude_identity_key(target_summary)
        if not target_identity:
            return []

        state = self.load_state()
        remaining_accounts: list[dict[str, Any]] = []
        cleared_account_ids: list[str] = []
        for account in state["accounts"]:
            account_id = str(account["id"])
            if account_id == target_account_id:
                remaining_accounts.append(account)
                continue

            other_summary = self.saved_account_summary(account_id)
            if claude_identity_key(other_summary) != target_identity:
                remaining_accounts.append(account)
                continue

            parent = self.account_secret_path(account_id).parent
            if parent.exists():
                shutil.rmtree(parent, ignore_errors=True)
            cleared_account_ids.append(account_id)

        if cleared_account_ids:
            state["accounts"] = remaining_accounts
            self.save_state(state)

        return cleared_account_ids


class UnifiedAuthHub:
    def __init__(
        self,
        codex_hub: AuthHub | None = None,
        claude_code_hub: ClaudeCodeHub | None = None,
    ) -> None:
        self._hubs: dict[str, Any] = {
            "codex": codex_hub or AuthHub(),
            CLAUDE_CODE_PROVIDER_ID: claude_code_hub or ClaudeCodeHub(),
        }

    def provider_hub(self, provider: str) -> Any:
        normalized = normalize_provider_name(provider)
        return self._hubs[normalized]

    def provider_ids(self) -> list[str]:
        return list(self._hubs.keys())

    def provider_overview(self, provider: str) -> dict[str, Any]:
        normalized = normalize_provider_name(provider)
        overview = self.provider_hub(normalized).overview()
        overview["provider_id"] = normalized
        overview["provider_label"] = provider_label(normalized)
        return overview

    def create_account_from_current(self, provider: str) -> dict[str, Any]:
        return self.provider_hub(provider).create_account_from_current()

    def save_current_to_account(self, provider: str, account_id: str) -> dict[str, Any]:
        return self.provider_hub(provider).save_current_to_account(account_id)

    def switch(self, provider: str, account_id: str) -> dict[str, Any]:
        return self.provider_hub(provider).switch(account_id)

    def delete_account(self, provider: str, account_id: str) -> dict[str, Any]:
        return self.provider_hub(provider).delete_account(account_id)

    def rename_account(self, provider: str, account_id: str, label: str) -> dict[str, Any]:
        hub = self.provider_hub(provider)
        rename = getattr(hub, "rename_slot", None) or getattr(hub, "rename_account", None)
        if rename is None:
            raise AuthHubError(f"provider {provider} does not support renaming accounts")
        return rename(account_id, label)
