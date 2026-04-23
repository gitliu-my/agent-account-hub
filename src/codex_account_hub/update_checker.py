from __future__ import annotations

import json
import re
from http import HTTPStatus
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__
from .providers import ProxyEnvironmentGuard
from .ui_helpers import APP_NAME


GITHUB_REPO = "gitliu-my/agent-account-hub"
LATEST_RELEASE_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"
BREW_UPGRADE_COMMAND = "brew upgrade --cask gitliu-my/tap/agent-account-hub"


def normalize_version(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith(("v", "V")):
        text = text[1:]
    return text


def parse_version_parts(value: Any) -> tuple[int, ...]:
    text = normalize_version(value)
    match = re.match(r"^(\d+(?:\.\d+)*)", text)
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def compare_versions(left: Any, right: Any) -> int:
    left_parts = parse_version_parts(left)
    right_parts = parse_version_parts(right)
    length = max(len(left_parts), len(right_parts))
    left_parts = left_parts + (0,) * (length - len(left_parts))
    right_parts = right_parts + (0,) * (length - len(right_parts))
    if left_parts > right_parts:
        return 1
    if left_parts < right_parts:
        return -1
    return 0


def _base_payload(current_version: str) -> dict[str, Any]:
    return {
        "current_version": normalize_version(current_version),
        "current_tag": f"v{normalize_version(current_version)}",
        "latest_version": None,
        "latest_tag": None,
        "release_url": RELEASES_URL,
        "published_at": None,
        "name": None,
        "update_available": False,
        "status": "unknown",
        "error": None,
        "brew_command": BREW_UPGRADE_COMMAND,
    }


def check_for_updates(
    *,
    current_version: str = __version__,
    proxy_guard: ProxyEnvironmentGuard | None = None,
    opener: Callable[..., Any] = urlopen,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    payload = _base_payload(current_version)
    guard = proxy_guard or ProxyEnvironmentGuard()
    proxy_status = guard.current_status()
    if not proxy_status.ready:
        payload.update(
            {
                "status": "proxy_unavailable",
                "error": f"{proxy_status.detail}；开启代理后再检查更新",
            }
        )
        return payload

    request = Request(
        LATEST_RELEASE_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": APP_NAME,
        },
        method="GET",
    )
    try:
        with opener(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except HTTPError as exc:
        if exc.code == HTTPStatus.NOT_FOUND:
            message = "GitHub release 暂时不可用"
        else:
            message = f"GitHub release 请求失败：HTTP {exc.code}"
        payload.update({"status": "error", "error": message})
        return payload
    except URLError as exc:
        payload.update({"status": "error", "error": f"无法连接 GitHub release：{exc.reason}"})
        return payload
    except OSError as exc:
        payload.update({"status": "error", "error": f"无法检查更新：{exc}"})
        return payload

    try:
        release = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload.update({"status": "error", "error": "GitHub release 返回了无法解析的数据"})
        return payload
    if not isinstance(release, dict):
        payload.update({"status": "error", "error": "GitHub release 返回的数据格式不正确"})
        return payload

    latest_tag = str(release.get("tag_name") or release.get("name") or "").strip()
    if not latest_tag:
        payload.update({"status": "error", "error": "GitHub release 里没有版本号"})
        return payload

    latest_version = normalize_version(latest_tag)
    update_available = compare_versions(latest_version, current_version) > 0
    payload.update(
        {
            "latest_tag": latest_tag,
            "latest_version": latest_version,
            "release_url": release.get("html_url") or RELEASES_URL,
            "published_at": release.get("published_at"),
            "name": release.get("name"),
            "update_available": update_available,
            "status": "update_available" if update_available else "up_to_date",
        }
    )
    return payload
