from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import AuthHub, AuthHubError
from .web import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-account-hub",
        description="Minimal auth.json snapshot switcher for Codex",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Run the local switching dashboard")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8766)

    tray_parser = subparsers.add_parser("tray", help="Run the macOS menu bar app")
    tray_parser.add_argument("--dashboard-host", default="127.0.0.1")
    tray_parser.add_argument("--dashboard-port", type=int, default=0)
    tray_parser.add_argument("--refresh-seconds", type=float, default=5.0)

    current_parser = subparsers.add_parser("current", help="Show current ~/.codex/auth.json summary")
    current_parser.add_argument("--json", action="store_true")

    list_parser = subparsers.add_parser("list", help="List saved accounts")
    list_parser.add_argument("--json", action="store_true")

    capture_new_parser = subparsers.add_parser(
        "capture-new", help="Save current auth.json as a new saved account"
    )

    capture_parser = subparsers.add_parser("capture", help="Overwrite a saved account with current auth.json")
    capture_parser.add_argument("slot")

    switch_parser = subparsers.add_parser("switch", help="Switch ~/.codex/auth.json to a saved account")
    switch_parser.add_argument("slot")

    import_parser = subparsers.add_parser("import-file", help="Import an auth.json file into a saved account")
    import_parser.add_argument("slot")
    import_parser.add_argument("path", type=Path)

    rename_parser = subparsers.add_parser("rename", help="Rename a saved account label")
    rename_parser.add_argument("slot")
    rename_parser.add_argument("label")

    clear_parser = subparsers.add_parser("clear", help="Delete a saved account")
    clear_parser.add_argument("slot")

    return parser


def print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def print_current(payload: dict) -> None:
    identity = payload.get("name") or payload.get("email") or payload.get("account_id") or "未登录"
    print(f"当前身份: {identity}")
    print(f"已保存账号: {payload.get('matched_account_label') or payload.get('matched_account_id') or '未保存'}")
    print(f"Plan: {payload.get('plan_type') or '—'}")
    print(f"认证方式: {payload.get('auth_mode') or '—'}")
    print(f"最后刷新: {payload.get('last_refresh') or '—'}")
    print(f"过期时间: {payload.get('expires_at') or '—'}")
    print(f"认证文件: {payload.get('path')}")


def print_slots(payload: dict) -> None:
    accounts = payload.get("accounts") or payload["slots"]
    current_slot = payload["current"].get("matched_account_id") or payload["current"].get("matched_slot_id")
    for slot in accounts:
        snapshot = slot["snapshot"]
        identity = snapshot.get("name") or snapshot.get("email") or snapshot.get("account_id") or "未保存"
        marker = "*" if slot["id"] == current_slot else " "
        print(f"{marker} {slot['id']}  {slot['label']}  {identity}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    hub = AuthHub()

    try:
        if args.command == "serve":
            serve(hub, host=args.host, port=args.port)
            return

        if args.command == "tray":
            from .tray import run_tray

            run_tray(
                hub,
                dashboard_host=args.dashboard_host,
                dashboard_port=args.dashboard_port,
                refresh_seconds=args.refresh_seconds,
            )
            return

        if args.command == "current":
            payload = hub.current_overview()
            if args.json:
                print_json(payload)
            else:
                print_current(payload)
            return

        if args.command == "list":
            payload = hub.overview()
            if args.json:
                print_json(payload)
            else:
                print_slots(payload)
            return

        if args.command == "capture-new":
            payload = hub.create_account_from_current()
            print_json(payload)
            return

        if args.command == "capture":
            payload = hub.save_current_to_account(args.slot)
            print_json(payload)
            return

        if args.command == "switch":
            payload = hub.switch(args.slot)
            print_json(payload)
            return

        if args.command == "import-file":
            payload = hub.import_file(args.slot, args.path)
            print_json(payload)
            return

        if args.command == "rename":
            payload = hub.rename_slot(args.slot, args.label)
            print_json(payload)
            return

        if args.command == "clear":
            payload = hub.delete_account(args.slot)
            print_json(payload)
            return
    except AuthHubError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
