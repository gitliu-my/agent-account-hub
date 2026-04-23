from __future__ import annotations

import json
import sys
import threading
import unittest
from http import HTTPStatus
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from codex_account_hub.web import make_server


class WebRouteTests(unittest.TestCase):
    def test_update_check_route_returns_checker_payload(self) -> None:
        server = make_server(object(), host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address[:2]

        try:
            with patch(
                "codex_account_hub.web.check_for_updates",
                return_value={
                    "status": "up_to_date",
                    "current_version": "0.1.11",
                    "current_tag": "v0.1.11",
                    "update_available": False,
                },
            ):
                conn = HTTPConnection(host, port, timeout=5)
                try:
                    conn.request(
                        "POST",
                        "/api/app/update-check",
                        body="{}",
                        headers={
                            "Content-Type": "application/json",
                            "Content-Length": "2",
                            "Origin": f"http://{host}:{port}",
                        },
                    )
                    response = conn.getresponse()
                    payload = json.loads(response.read().decode("utf-8"))
                finally:
                    conn.close()

            self.assertEqual(response.status, HTTPStatus.OK)
            self.assertEqual(payload["status"], "up_to_date")
            self.assertEqual(payload["current_tag"], "v0.1.11")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_invalid_provider_post_routes_return_bad_request(self) -> None:
        server = make_server(object(), host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address[:2]

        try:
            for path in (
                "/api/providers/not-real/accounts/account-1/usage-auth",
                "/api/providers/not-real/accounts/account-1/usage-auth/clear",
                "/api/providers/not-real/accounts/account-1/usage/refresh",
                "/api/providers/not-real/usage/refresh-all",
                "/api/providers/not-real/accounts/account-1/usage-menu-bar",
                "/api/providers/not-real/accounts/account-1/rename",
                "/api/providers/not-real/accounts/account-1/capture",
                "/api/providers/not-real/accounts/account-1/switch",
                "/api/providers/not-real/accounts/account-1/delete",
            ):
                with self.subTest(path=path):
                    conn = HTTPConnection(host, port, timeout=5)
                    try:
                        conn.request(
                            "POST",
                            path,
                            body="{}",
                            headers={
                                "Content-Type": "application/json",
                                "Content-Length": "2",
                                "Origin": f"http://{host}:{port}",
                            },
                        )
                        response = conn.getresponse()
                        payload = json.loads(response.read().decode("utf-8"))
                    finally:
                        conn.close()

                    self.assertEqual(response.status, HTTPStatus.BAD_REQUEST)
                    self.assertEqual(payload["error"], "unsupported provider: not-real")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
