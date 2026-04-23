from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from codex_account_hub.update_checker import check_for_updates, compare_versions


class FakeProxyGuard:
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready

    def current_status(self) -> SimpleNamespace:
        return SimpleNamespace(ready=self.ready, detail="代理未就绪")


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class UpdateCheckerTests(unittest.TestCase):
    def test_compare_versions_ignores_v_prefix_and_pads_parts(self) -> None:
        self.assertEqual(compare_versions("v0.1.12", "0.1.11"), 1)
        self.assertEqual(compare_versions("0.1.11", "v0.1.11"), 0)
        self.assertEqual(compare_versions("0.1.9", "0.1.10"), -1)

    def test_check_for_updates_reports_new_release(self) -> None:
        def fake_opener(request: object, timeout: float = 12.0) -> FakeResponse:
            return FakeResponse(
                {
                    "tag_name": "v0.1.12",
                    "html_url": "https://github.com/gitliu-my/agent-account-hub/releases/tag/v0.1.12",
                    "published_at": "2026-04-22T10:00:00Z",
                    "name": "v0.1.12",
                }
            )

        payload = check_for_updates(
            current_version="0.1.11",
            proxy_guard=FakeProxyGuard(),
            opener=fake_opener,
        )

        self.assertEqual(payload["status"], "update_available")
        self.assertTrue(payload["update_available"])
        self.assertEqual(payload["latest_version"], "0.1.12")
        self.assertIn("brew upgrade", payload["brew_command"])

    def test_check_for_updates_reports_current_version_up_to_date(self) -> None:
        def fake_opener(request: object, timeout: float = 12.0) -> FakeResponse:
            return FakeResponse({"tag_name": "v0.1.11"})

        payload = check_for_updates(
            current_version="0.1.11",
            proxy_guard=FakeProxyGuard(),
            opener=fake_opener,
        )

        self.assertEqual(payload["status"], "up_to_date")
        self.assertFalse(payload["update_available"])

    def test_check_for_updates_skips_network_when_proxy_unavailable(self) -> None:
        def fake_opener(request: object, timeout: float = 12.0) -> FakeResponse:
            raise AssertionError("update check should not call GitHub without proxy")

        payload = check_for_updates(
            current_version="0.1.11",
            proxy_guard=FakeProxyGuard(ready=False),
            opener=fake_opener,
        )

        self.assertEqual(payload["status"], "proxy_unavailable")
        self.assertIn("代理", payload["error"])


if __name__ == "__main__":
    unittest.main()
