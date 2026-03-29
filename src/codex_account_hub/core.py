from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ACTIVE_AUTH_PATH = Path.home() / ".codex" / "auth.json"
APP_DISPLAY_NAME = "Agent Account Hub"
MACOS_APP_SUPPORT_ROOT = Path.home() / "Library" / "Application Support" / APP_DISPLAY_NAME
LEGACY_MACOS_APP_SUPPORT_ROOT = Path.home() / "Library" / "Application Support" / "Codex Account Hub"
DATA_ROOT_ENV_VAR = "CODEX_ACCOUNT_HUB_DATA_ROOT"
LEGACY_DATA_ROOT_ENV_VAR = "CODEX_ACCOUNT_HUB_LEGACY_DATA_ROOT"


class AuthHubError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthHubPaths:
    data_root: Path
    state_path: Path
    accounts_root: Path
    active_auth_path: Path = DEFAULT_ACTIVE_AUTH_PATH

    @classmethod
    def defaults(cls) -> "AuthHubPaths":
        data_root = default_data_root()
        return cls(
            data_root=data_root,
            state_path=data_root / "state.json",
            accounts_root=data_root / "accounts",
            active_auth_path=DEFAULT_ACTIVE_AUTH_PATH,
        )


def running_in_bundled_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def default_data_root() -> Path:
    override = os.environ.get(DATA_ROOT_ENV_VAR)
    if override:
        return Path(override).expanduser()
    if running_in_bundled_app() and sys.platform == "darwin":
        return MACOS_APP_SUPPORT_ROOT
    return PROJECT_ROOT / "data"


def has_saved_data(data_root: Path) -> bool:
    accounts_root = data_root / "accounts"
    if accounts_root.is_dir() and any(accounts_root.glob("*/auth.json")):
        return True

    claude_accounts_root = data_root / "providers" / "claude-code" / "accounts"
    if claude_accounts_root.is_dir() and any(claude_accounts_root.glob("*/credentials.json")):
        return True

    return False


def legacy_data_root_candidates(target_data_root: Path) -> list[Path]:
    candidates: list[Path] = []

    override = os.environ.get(LEGACY_DATA_ROOT_ENV_VAR)
    if override:
        candidates.append(Path(override).expanduser())

    legacy_project_data = PROJECT_ROOT / "data"
    if legacy_project_data != target_data_root:
        candidates.append(legacy_project_data)

    if LEGACY_MACOS_APP_SUPPORT_ROOT != target_data_root:
        candidates.append(LEGACY_MACOS_APP_SUPPORT_ROOT)

    if running_in_bundled_app():
        executable_path = Path(sys.executable).resolve()
        parents = list(executable_path.parents)
        if len(parents) >= 5 and parents[2].suffix == ".app":
            bundled_legacy_data = parents[4] / "data"
            if bundled_legacy_data != target_data_root:
                candidates.append(bundled_legacy_data)

    unique_candidates: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_candidates.append(resolved)
    return unique_candidates


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp_to_iso(value: Any) -> str | None:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(numeric, tz=timezone.utc).isoformat()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def atomic_write_bytes(path: Path, content: bytes, mode: int = 0o600) -> None:
    ensure_parent(path)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_bytes(content)
    try:
        os.chmod(temp_path, mode)
    except PermissionError:
        pass
    os.replace(temp_path, path)


def atomic_write_json(path: Path, payload: dict[str, Any], mode: int = 0o600) -> None:
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    atomic_write_bytes(path, content, mode=mode)


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode_jwt_payload(token: str | None) -> dict[str, Any]:
    if not token:
        return {}
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("utf-8"))
        value = json.loads(decoded.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def load_json_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AuthHubError(f"{path} does not contain a JSON object")
    return value


def build_auth_summary(path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "status": "missing",
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
    }

    if not path.is_file():
        return summary

    summary["hash"] = sha256_file(path)
    try:
        payload = load_json_file(path)
    except (OSError, json.JSONDecodeError, AuthHubError) as exc:
        summary["status"] = "invalid"
        summary["error"] = str(exc)
        return summary

    tokens = payload.get("tokens", {})
    id_token = tokens.get("id_token")
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")

    id_claims = decode_jwt_payload(id_token)
    access_claims = decode_jwt_payload(access_token)
    auth_claims = (
        id_claims.get("https://api.openai.com/auth")
        or access_claims.get("https://api.openai.com/auth")
        or {}
    )

    summary["status"] = "ready"
    summary["auth_mode"] = payload.get("auth_mode")
    summary["account_id"] = (
        tokens.get("account_id")
        or auth_claims.get("chatgpt_account_id")
    )
    summary["name"] = id_claims.get("name")
    summary["email"] = id_claims.get("email")
    summary["plan_type"] = auth_claims.get("chatgpt_plan_type")
    summary["last_refresh"] = payload.get("last_refresh")
    summary["id_expires_at"] = timestamp_to_iso(id_claims.get("exp"))
    summary["access_expires_at"] = timestamp_to_iso(access_claims.get("exp"))
    summary["has_id_token"] = bool(id_token)
    summary["has_access_token"] = bool(access_token)
    summary["has_refresh_token"] = bool(refresh_token)
    # Use access_token expiry as the primary health signal. It tracks the
    # token that actually gates API calls more closely than id_token expiry.
    summary["expires_at"] = summary["access_expires_at"] or summary["id_expires_at"]
    return summary


def auth_identity_key(summary: dict[str, Any]) -> str | None:
    if summary.get("status") != "ready":
        return None
    account_id = summary.get("account_id")
    if account_id:
        return f"account_id:{account_id}"
    email = summary.get("email")
    if email:
        return f"email:{str(email).strip().lower()}"
    file_hash = summary.get("hash")
    if file_hash:
        return f"hash:{file_hash}"
    return None


def suggested_account_label(summary: dict[str, Any], fallback_index: int | None = None) -> str:
    for key in ("email", "name", "account_id"):
        value = summary.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if fallback_index is not None:
        return f"账号 {fallback_index}"
    return "未命名账号"


def is_placeholder_account_label(label: str, account_id: str) -> bool:
    stripped = label.strip()
    if not stripped or stripped == account_id or stripped.startswith("account-"):
        return True
    if stripped.startswith("账号 "):
        suffix = stripped.removeprefix("账号 ").strip()
        return suffix.isdigit()
    return False


def default_state() -> dict[str, Any]:
    return {"version": 2, "accounts": []}


class AuthHub:
    def __init__(self, paths: AuthHubPaths | None = None) -> None:
        self.paths = paths or AuthHubPaths.defaults()
        self._bootstrap_data_root()
        self.paths.data_root.mkdir(parents=True, exist_ok=True)
        self.paths.accounts_root.mkdir(parents=True, exist_ok=True)

    def _bootstrap_data_root(self) -> None:
        if has_saved_data(self.paths.data_root):
            return

        self.paths.data_root.mkdir(parents=True, exist_ok=True)
        for legacy_root in legacy_data_root_candidates(self.paths.data_root):
            if not has_saved_data(legacy_root):
                continue
            shutil.copytree(legacy_root, self.paths.data_root, dirs_exist_ok=True)
            return

    def load_state(self) -> dict[str, Any]:
        if not self.paths.state_path.is_file():
            state = default_state()
            self.save_state(state)
            return state

        state = load_json_file(self.paths.state_path)
        migrated = False

        accounts_payload = state.get("accounts")
        if not isinstance(accounts_payload, list):
            legacy_slots = state.get("slots")
            if not isinstance(legacy_slots, list):
                raise AuthHubError(f"{self.paths.state_path} is missing a valid accounts array")
            accounts_payload = legacy_slots
            migrated = True

        normalized_accounts = self._normalize_accounts(accounts_payload)
        normalized_state = {"version": 2, "accounts": normalized_accounts}

        if migrated or state.get("version") != 2 or state.get("accounts") != normalized_accounts:
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

            auth_path = self.account_auth_path(account_id)
            if not auth_path.is_file():
                continue

            snapshot = build_auth_summary(auth_path)
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

    def account_auth_path(self, account_id: str) -> Path:
        return self.paths.accounts_root / account_id / "auth.json"

    def slot_auth_path(self, slot_id: str) -> Path:
        return self.account_auth_path(slot_id)

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

    def get_slot(self, slot_id: str) -> dict[str, Any]:
        return self.get_account(slot_id)

    def update_account(self, account_id: str, **updates: Any) -> dict[str, Any]:
        state = self.load_state()
        for account in state["accounts"]:
            if account.get("id") == account_id:
                account.update(updates)
                self.save_state(state)
                return account
        raise AuthHubError(f"account {account_id} not found")

    def update_slot(self, slot_id: str, **updates: Any) -> dict[str, Any]:
        return self.update_account(slot_id, **updates)

    def rename_account(self, account_id: str, label: str) -> dict[str, Any]:
        if not label.strip():
            raise AuthHubError("label must not be empty")
        return self.update_account(account_id, label=label.strip())

    def rename_slot(self, slot_id: str, label: str) -> dict[str, Any]:
        return self.rename_account(slot_id, label)

    def create_account_from_current(self) -> dict[str, Any]:
        source = self.paths.active_auth_path
        if not source.is_file():
            raise AuthHubError(f"active auth file not found: {source}")

        current_summary = build_auth_summary(source)
        current_identity = auth_identity_key(current_summary)
        if current_identity:
            existing_id = self.find_account_id_by_identity(current_identity)
            if existing_id:
                payload = self.save_current_to_account(existing_id)
                payload["created_new_account"] = False
                return payload

        account_id = self.next_account_id()
        payload = self._write_auth_snapshot(
            source,
            account_id,
            allow_create=True,
        )
        payload["created_new_account"] = True
        return payload

    def capture_current(self, slot_id: str) -> dict[str, Any]:
        source = self.paths.active_auth_path
        if not source.is_file():
            raise AuthHubError(f"active auth file not found: {source}")
        return self._write_auth_snapshot(source, slot_id, allow_create=True)

    def save_current_to_account(self, account_id: str) -> dict[str, Any]:
        source = self.paths.active_auth_path
        if not source.is_file():
            raise AuthHubError(f"active auth file not found: {source}")
        return self._write_auth_snapshot(source, account_id, allow_create=False)

    def import_file(self, slot_id: str, auth_path: Path) -> dict[str, Any]:
        if not auth_path.is_file():
            raise AuthHubError(f"auth snapshot not found: {auth_path}")
        return self._write_auth_snapshot(auth_path, slot_id, allow_create=True)

    def _write_auth_snapshot(
        self,
        source: Path,
        account_id: str,
        allow_create: bool,
    ) -> dict[str, Any]:
        source_summary = build_auth_summary(source)
        state = self.load_state()
        account: dict[str, Any] | None = None
        for item in state["accounts"]:
            if item.get("id") == account_id:
                account = item
                break

        now = utc_now_iso()
        account_label = suggested_account_label(source_summary, len(state["accounts"]) + 1)
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

        destination = self.account_auth_path(account_id)
        ensure_parent(destination)
        shutil.copyfile(source, destination)
        try:
            os.chmod(destination, 0o600)
        except PermissionError:
            pass

        account_payload = self.account_overview(account_id)
        account_payload["cleared_account_ids"] = self._clear_duplicate_accounts(account_id)
        account_payload["cleared_slot_ids"] = list(account_payload["cleared_account_ids"])
        return account_payload

    def switch(self, slot_id: str) -> dict[str, Any]:
        source = self.account_auth_path(slot_id)
        if not source.is_file():
            raise AuthHubError(f"account {slot_id} has no saved auth snapshot")
        destination = self.paths.active_auth_path
        ensure_parent(destination)
        shutil.copyfile(source, destination)
        try:
            os.chmod(destination, 0o600)
        except PermissionError:
            pass

        account = self.get_account(slot_id)
        self.update_account(
            slot_id,
            created_at=account.get("created_at") or utc_now_iso(),
            updated_at=account.get("updated_at") or utc_now_iso(),
        )
        return self.current_overview()

    def delete_account(self, account_id: str) -> dict[str, Any]:
        account = dict(self.get_account(account_id))
        auth_path = self.account_auth_path(account_id)
        if auth_path.exists():
            auth_path.unlink()
        state = self.load_state()
        state["accounts"] = [item for item in state["accounts"] if item.get("id") != account_id]
        self.save_state(state)
        return {
            "id": account_id,
            "label": account.get("label") or account_id,
            "deleted": True,
        }

    def clear_slot(self, slot_id: str) -> dict[str, Any]:
        return self.delete_account(slot_id)

    def sync_current_account_snapshot(self) -> dict[str, Any]:
        source = self.paths.active_auth_path
        result = {
            "account_id": None,
            "status": "not_saved",
            "updated": False,
        }

        if not source.is_file():
            result["status"] = "missing"
            return result

        current_summary = build_auth_summary(source)
        if current_summary.get("status") != "ready":
            result["status"] = "invalid"
            return result

        current_identity = auth_identity_key(current_summary)
        if not current_identity:
            result["status"] = "unidentifiable"
            return result

        account_id = self.find_account_id_by_identity(current_identity)
        if not account_id:
            return result

        result["account_id"] = account_id
        snapshot_hash = sha256_file(self.account_auth_path(account_id))
        current_hash = current_summary.get("hash")
        if snapshot_hash and current_hash and snapshot_hash == current_hash:
            result["status"] = "up_to_date"
            return result

        self._write_auth_snapshot(source, account_id, allow_create=False)
        result["status"] = "updated"
        result["updated"] = True
        return result

    def current_account_id(self) -> str | None:
        current_hash = sha256_file(self.paths.active_auth_path)
        if current_hash:
            for account in self.load_state()["accounts"]:
                account_hash = sha256_file(self.account_auth_path(account["id"]))
                if account_hash and account_hash == current_hash:
                    return str(account["id"])

        current_summary = build_auth_summary(self.paths.active_auth_path)
        current_identity = auth_identity_key(current_summary)
        if not current_identity:
            return None
        return self.find_account_id_by_identity(current_identity)

    def current_slot_id(self) -> str | None:
        return self.current_account_id()

    def current_overview(self, sync_result: dict[str, Any] | None = None) -> dict[str, Any]:
        if sync_result is None:
            sync_result = self.sync_current_account_snapshot()
        current = build_auth_summary(self.paths.active_auth_path)
        matched_account_id = self.current_account_id()
        current["matched_account_id"] = matched_account_id
        current["matched_slot_id"] = matched_account_id
        current["matched_account_label"] = self.account_label(matched_account_id)
        current["snapshot_sync_status"] = sync_result.get("status")
        current["snapshot_sync_updated"] = bool(sync_result.get("updated"))
        current["snapshot_sync_account_id"] = sync_result.get("account_id") or matched_account_id
        return current

    def account_label(self, account_id: str | None) -> str | None:
        if not account_id:
            return None
        try:
            account = self.get_account(account_id)
        except AuthHubError:
            return None
        snapshot = build_auth_summary(self.account_auth_path(account_id))
        existing_label = str(account.get("label") or "").strip()
        if snapshot.get("exists") and is_placeholder_account_label(existing_label, account_id):
            return suggested_account_label(snapshot)
        return existing_label or (suggested_account_label(snapshot) if snapshot.get("exists") else account_id)

    def account_overview(self, account_id: str) -> dict[str, Any]:
        account = dict(self.get_account(account_id))
        snapshot = build_auth_summary(self.account_auth_path(account_id))
        account["snapshot"] = snapshot
        account["active"] = bool(
            snapshot.get("hash") and snapshot.get("hash") == sha256_file(self.paths.active_auth_path)
        )
        return account

    def slot_overview(self, slot_id: str) -> dict[str, Any]:
        return self.account_overview(slot_id)

    def overview(self) -> dict[str, Any]:
        sync_result = self.sync_current_account_snapshot()
        current_hash = sha256_file(self.paths.active_auth_path)
        accounts = []
        for account in self.load_state()["accounts"]:
            account_id = str(account["id"])
            snapshot = build_auth_summary(self.account_auth_path(account_id))
            accounts.append(
                {
                    **account,
                    "snapshot": snapshot,
                    "active": bool(current_hash and snapshot.get("hash") == current_hash),
                }
            )
        return {
            "active_auth_path": str(self.paths.active_auth_path),
            "current": self.current_overview(sync_result=sync_result),
            "accounts": accounts,
            "slots": list(accounts),
            "project_root": str(PROJECT_ROOT),
            "data_root": str(self.paths.data_root),
        }

    def find_account_id_by_identity(self, identity_key: str) -> str | None:
        for account in self.load_state()["accounts"]:
            account_id = str(account["id"])
            summary = build_auth_summary(self.account_auth_path(account_id))
            if auth_identity_key(summary) == identity_key:
                return account_id
        return None

    def _clear_duplicate_accounts(self, target_account_id: str) -> list[str]:
        target_summary = build_auth_summary(self.account_auth_path(target_account_id))
        target_identity = auth_identity_key(target_summary)
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

            other_path = self.account_auth_path(account_id)
            other_summary = build_auth_summary(other_path)
            if auth_identity_key(other_summary) != target_identity:
                remaining_accounts.append(account)
                continue

            if other_path.exists():
                other_path.unlink()
            cleared_account_ids.append(account_id)

        if cleared_account_ids:
            state["accounts"] = remaining_accounts
            self.save_state(state)

        return cleared_account_ids

    def _clear_duplicate_slots(self, target_slot_id: str) -> list[str]:
        return self._clear_duplicate_accounts(target_slot_id)
