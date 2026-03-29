from __future__ import annotations

import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from typing import Any

from .core import AuthHubError
from .providers import UnifiedAuthHub, provider_label
from .web import make_server

APP_NAME = "Agent Account Hub"


def summary_identity(summary: dict[str, Any]) -> str:
    return (
        summary.get("name")
        or summary.get("email")
        or summary.get("account_id")
        or "未登录"
    )


def slot_preview_identity(summary: dict[str, Any]) -> str:
    return (
        summary.get("email")
        or summary.get("name")
        or summary.get("account_id")
        or "未保存账号"
    )


def slot_display_label(slot: dict[str, Any]) -> str:
    label = str(slot.get("label") or "").strip()
    if label:
        return label
    return slot_preview_identity(slot.get("snapshot", {}))


def slot_status_label(slot: dict[str, Any]) -> str:
    snapshot = slot.get("snapshot", {})
    if not snapshot.get("exists"):
        return "未保存"
    if slot.get("active"):
        return "当前认证"
    return "已保存"


def slot_preview_label(slot: dict[str, Any]) -> str:
    snapshot = slot.get("snapshot", {})
    if not snapshot.get("exists"):
        return slot_display_label(slot)

    identity = slot_display_label(slot)
    if slot.get("active"):
        return f"{identity} · 当前"
    return identity


def snapshot_sync_label(current: dict[str, Any]) -> str:
    status = current.get("snapshot_sync_status")
    if status == "updated":
        return "已自动同步"
    if status == "up_to_date":
        return "已是最新"
    if status == "not_saved":
        return "未关联快照"
    if status == "invalid":
        return "认证异常"
    if status == "missing":
        return "未检测到认证"
    if status == "unidentifiable":
        return "无法识别账号"
    return "—"


def tray_title(overview: dict[str, Any]) -> str:
    return "Hub"


class DashboardServer:
    def __init__(self, hub: UnifiedAuthHub, host: str, port: int) -> None:
        self._hub = hub
        self._host = host
        self._port = port
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def ensure_started(self) -> str:
        with self._lock:
            if self._server is None:
                server = make_server(self._hub, host=self._host, port=self._port)
                thread = threading.Thread(
                    target=server.serve_forever,
                    name="agent-account-hub-dashboard",
                    daemon=True,
                )
                thread.start()
                self._server = server
                self._thread = thread

            host, port = self._server.server_address[:2]
            display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
            return f"http://{display_host}:{port}"

    def shutdown(self) -> None:
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None

        if server is None:
            return

        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=1.0)


def run_tray(
    hub: UnifiedAuthHub,
    dashboard_host: str = "127.0.0.1",
    dashboard_port: int = 0,
    refresh_seconds: float = 5.0,
) -> None:
    if sys.platform != "darwin":
        raise AuthHubError("tray mode only supports macOS")

    try:
        import rumps
    except ImportError as exc:
        raise AuthHubError(
            "tray mode requires the macOS dependency 'rumps'; run `python3 -m pip install -e .` first"
        ) from exc

    dashboard = DashboardServer(hub, host=dashboard_host, port=dashboard_port)
    interval = max(3.0, float(refresh_seconds))

    def disabled_item(title: str) -> Any:
        item = rumps.MenuItem(title)
        item.set_callback(None)
        return item

    class AuthHubTrayApp(rumps.App):
        def __init__(self) -> None:
            super().__init__(APP_NAME, title="Hub", quit_button=None)
            self._timer = rumps.Timer(self._refresh_from_timer, interval)
            self._reload_menu()

        def run(self, **options: Any) -> None:
            self._timer.start()
            try:
                super().run(**options)
            finally:
                self._timer.stop()
                dashboard.shutdown()

        def _refresh_from_timer(self, _sender: Any) -> None:
            self._reload_menu()

        def _reload_menu(self) -> None:
            try:
                overviews = {
                    provider: hub.provider_overview(provider)
                    for provider in hub.provider_ids()
                }
            except (AuthHubError, OSError) as exc:
                self.title = "Hub !"
                self.menu.clear()
                self.menu.update(
                    [
                        disabled_item(APP_NAME),
                        None,
                        disabled_item(f"读取失败: {exc}"),
                        None,
                        rumps.MenuItem("刷新状态", callback=self._manual_refresh),
                        rumps.MenuItem("打开网页控制台", callback=self._open_dashboard),
                        rumps.MenuItem("退出", callback=self._quit),
                    ]
                )
                return

            self.title = "Hub"
            self.menu.clear()
            self.menu.update(self._build_menu_items(overviews))

        def _build_menu_items(self, overviews: dict[str, dict[str, Any]]) -> list[Any]:
            items: list[Any] = [
                disabled_item(APP_NAME),
            ]

            for provider in hub.provider_ids():
                items.extend([None, self._build_provider_menu(provider, overviews[provider])])

            items.extend(
                [
                    None,
                    rumps.MenuItem("打开网页控制台", callback=self._open_dashboard),
                    rumps.MenuItem("刷新状态", callback=self._manual_refresh),
                    rumps.MenuItem("退出", callback=self._quit),
                ]
            )
            return items

        def _build_provider_menu(self, provider: str, overview: dict[str, Any]) -> Any:
            current = overview["current"]
            accounts = overview.get("accounts") or overview.get("slots") or []
            provider_menu = rumps.MenuItem(provider_label(provider))
            provider_menu.update(
                [
                    disabled_item(f"当前邮箱: {current.get('email') or '—'}"),
                    disabled_item(f"当前身份: {summary_identity(current)}"),
                    disabled_item(f"Plan: {current.get('plan_type') or '—'}"),
                    disabled_item(f"快照同步: {snapshot_sync_label(current)}"),
                    disabled_item(f"已保存账号: {len(accounts)}"),
                    None,
                    rumps.MenuItem("保存当前为新账号", callback=self._create_new_account(provider)),
                    None,
                    *[self._build_slot_menu(provider, slot) for slot in accounts],
                ]
            )
            return provider_menu

        def _build_slot_menu(self, provider: str, slot: dict[str, Any]) -> Any:
            slot_id = str(slot["id"])
            snapshot = slot["snapshot"]
            slot_label = slot_display_label(slot)
            slot_identity = slot_preview_identity(snapshot)

            slot_menu = rumps.MenuItem(slot_preview_label(slot))
            slot_menu.state = 1 if slot.get("active") else 0

            switch_item = rumps.MenuItem("切换到这里")
            switch_item.set_callback(
                self._switch_slot(provider, slot_id, slot_label) if snapshot["exists"] else None
            )

            capture_item = rumps.MenuItem(
                "用当前登录覆盖",
                callback=self._capture_slot(provider, slot_id, slot_label),
            )

            rename_item = rumps.MenuItem(
                "重命名这个账号",
                callback=self._rename_slot(provider, slot_id, slot_label),
            )

            clear_item = rumps.MenuItem("删除这个账号")
            clear_item.set_callback(
                self._clear_slot(provider, slot_id, slot_label) if snapshot["exists"] else None
            )

            slot_menu.update(
                [
                    disabled_item(f"状态: {'当前账号' if slot.get('active') else '已保存'}"),
                    disabled_item(f"名称: {slot_label}"),
                    disabled_item(f"邮箱: {snapshot.get('email') or '—'}"),
                    disabled_item(f"姓名: {snapshot.get('name') or '—'}"),
                    disabled_item(f"身份: {slot_identity}"),
                    disabled_item(f"账号 ID: {snapshot.get('account_id') or '—'}"),
                    disabled_item(f"Plan: {snapshot.get('plan_type') or '—'}"),
                    None,
                    switch_item,
                    capture_item,
                    rename_item,
                    clear_item,
                ]
            )
            return slot_menu

        def _manual_refresh(self, _sender: Any) -> None:
            self._reload_menu()

        def _create_new_account(self, provider: str):
            def callback(_sender: Any) -> None:
                try:
                    payload = hub.create_account_from_current(provider)
                except AuthHubError as exc:
                    rumps.alert("保存失败", str(exc))
                    return

                identity = summary_identity(payload.get("snapshot", {}))
                if payload.get("created_new_account"):
                    message = f"{provider_label(provider)} 已保存为新账号：{identity}"
                else:
                    message = f"{provider_label(provider)} 已更新已有账号：{identity}"
                self._notify(APP_NAME, "保存成功", message)
                self._reload_menu()

            return callback

        def _open_dashboard(self, _sender: Any) -> None:
            try:
                url = dashboard.ensure_started()
            except OSError as exc:
                rumps.alert("无法启动网页控制台", str(exc))
                return

            webbrowser.open(url)
            self._notify(APP_NAME, "已打开网页控制台", url)

        def _capture_slot(self, provider: str, slot_id: str, slot_label: str):
            def callback(_sender: Any) -> None:
                try:
                    payload = hub.save_current_to_account(provider, slot_id)
                except AuthHubError as exc:
                    rumps.alert("保存失败", str(exc))
                    return

                moved = payload.get("cleared_account_ids") or payload.get("cleared_slot_ids") or []
                message = f"{provider_label(provider)} 已用当前登录覆盖 {slot_label}"
                if moved:
                    message += f"；并移除重复账号 {', '.join(moved)}"
                self._notify(APP_NAME, "保存成功", message)
                self._reload_menu()

            return callback

        def _rename_slot(self, provider: str, slot_id: str, current_label: str):
            def callback(_sender: Any) -> None:
                window = rumps.Window(
                    message=f"给这个 {provider_label(provider)} 账号起一个更容易识别的名字。",
                    title="重命名账号",
                    default_text=current_label,
                    ok="保存",
                    cancel="取消",
                    dimensions=(360, 80),
                )
                response = window.run()
                if not getattr(response, "clicked", False):
                    return

                next_label = str(getattr(response, "text", "") or "").strip()
                if not next_label:
                    rumps.alert("名称不能为空")
                    return

                if next_label == current_label.strip():
                    return

                try:
                    hub.rename_account(provider, slot_id, next_label)
                except AuthHubError as exc:
                    rumps.alert("重命名失败", str(exc))
                    return

                self._notify(APP_NAME, "重命名成功", f"{provider_label(provider)} 已更新为 {next_label}")
                self._reload_menu()

            return callback

        def _switch_slot(self, provider: str, slot_id: str, slot_label: str):
            def callback(_sender: Any) -> None:
                try:
                    hub.switch(provider, slot_id)
                except AuthHubError as exc:
                    rumps.alert("切换失败", str(exc))
                    return

                self._notify(APP_NAME, "切换成功", f"{provider_label(provider)} 已切换到 {slot_label}")
                self._reload_menu()

            return callback

        def _clear_slot(self, provider: str, slot_id: str, slot_label: str):
            def callback(_sender: Any) -> None:
                confirmed = rumps.alert(
                    f"删除 {slot_label}",
                    f"这会删除这个已保存账号的 {provider_label(provider)} 快照，但不会删除当前正在使用的凭据。",
                    ok="删除",
                    cancel="取消",
                )
                if confirmed != 1:
                    return

                try:
                    hub.delete_account(provider, slot_id)
                except AuthHubError as exc:
                    rumps.alert("删除失败", str(exc))
                    return

                self._notify(APP_NAME, "删除成功", f"{provider_label(provider)} 已删除 {slot_label}")
                self._reload_menu()

            return callback

        def _quit(self, _sender: Any) -> None:
            dashboard.shutdown()
            rumps.quit_application()

        def _notify(self, title: str, subtitle: str, message: str) -> None:
            try:
                rumps.notification(title, subtitle, message, sound=False)
            except RuntimeError:
                pass

    AuthHubTrayApp().run()
