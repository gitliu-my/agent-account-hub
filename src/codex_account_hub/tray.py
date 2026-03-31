from __future__ import annotations

import sys
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer
from typing import Any

from .core import AuthHubError
from .native_window import NativeHubWindow
from .providers import UnifiedAuthHub, provider_label
from .ui_helpers import (
    APP_NAME,
    slot_display_label,
    slot_preview_identity,
    slot_preview_label,
    snapshot_sync_label,
    summary_identity,
    tray_title,
    usage_status_label,
    usage_summary_label,
)
from .web import make_server

DEFAULT_USAGE_AUTO_REFRESH_SECONDS = 5 * 60
MENU_BAR_GROUP_GAP = 4.0
TRAY_UI_POLL_SECONDS = 1.0
STATUS_ITEM_HIDDEN_TITLE = "\u200b"

try:
    import AppKit
    import Foundation
except ImportError:
    AppKit = None
    Foundation = None


def tray_usage_source(overview: dict[str, Any]) -> dict[str, Any] | None:
    current = overview.get("current") or {}
    current_usage = current.get("usage") or {}
    current_usage_auth = current.get("usage_auth") or {}
    if current_usage_auth.get("configured") or any(
        current_usage.get(key) is not None for key in ("five_hour_percent", "seven_day_percent")
    ):
        return {
            "usage": current_usage,
            "usage_auth": current_usage_auth,
        }

    accounts = overview.get("accounts") or overview.get("slots") or []
    for slot in accounts:
        usage = slot.get("usage") or {}
        usage_auth = slot.get("usage_auth") or {}
        if usage_auth.get("configured") or any(
            usage.get(key) is not None for key in ("five_hour_percent", "seven_day_percent")
        ):
            return {
                "usage": usage,
                "usage_auth": usage_auth,
            }
    return None


def format_menu_usage_value(value: Any) -> str:
    if value in (None, ""):
        return "—"
    try:
        numeric = round(float(value))
    except (TypeError, ValueError):
        return "—"
    return str(int(max(0, min(100, numeric))))


def usage_progress_tone(percent: Any, status: str | None = None) -> str:
    if status in {"unauthorized", "error", "auth_missing"} and percent in (None, ""):
        return "bad"
    try:
        numeric = float(percent)
    except (TypeError, ValueError):
        return "warn" if status == "stale" else "muted"
    if numeric >= 80:
        return "bad"
    if numeric >= 60:
        return "warn"
    return "good"


def tray_usage_slots(overview: dict[str, Any]) -> list[dict[str, Any]]:
    slots = overview.get("usage_menu_bar_accounts") or []
    if not isinstance(slots, list):
        return []
    provider_id = str(overview.get("provider_id") or "").strip() or None
    normalized_slots: list[dict[str, Any]] = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        payload = dict(slot)
        if provider_id and not payload.get("provider_id"):
            payload["provider_id"] = provider_id
        normalized_slots.append(payload)
    return normalized_slots


def tray_usage_slots_from_overviews(overviews: dict[str, dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not isinstance(overviews, dict):
        return []
    slots: list[dict[str, Any]] = []
    for provider in ("codex", "claude-code"):
        overview = overviews.get(provider)
        if not isinstance(overview, dict):
            continue
        slots.extend(tray_usage_slots(overview))
    return slots


def status_item_usage_title(overview: dict[str, Any]) -> str:
    source = tray_usage_source(overview)
    if not source:
        return "Hub"
    usage = source.get("usage") or {}
    five_hour = format_menu_usage_value(usage.get("five_hour_percent"))
    seven_day = format_menu_usage_value(usage.get("seven_day_percent"))
    if five_hour == "—" and seven_day == "—":
        status = str(usage.get("status") or "")
        return "!" if status in {"unauthorized", "error", "auth_missing"} else "··"
    return f"{five_hour}·{seven_day}"


def _nscolor_for_tone(tone: str) -> Any:
    if AppKit is None:
        return None
    if tone == "good":
        return AppKit.NSColor.systemGreenColor()
    if tone == "warn":
        return AppKit.NSColor.systemOrangeColor()
    if tone == "bad":
        return AppKit.NSColor.systemRedColor()
    return AppKit.NSColor.tertiaryLabelColor()


def _slot_frame_stroke_color(provider_id: str | None) -> Any:
    if AppKit is None:
        return None
    if provider_id == "claude-code":
        return AppKit.NSColor.systemOrangeColor().colorWithAlphaComponent_(0.9)
    if provider_id == "codex":
        return AppKit.NSColor.labelColor().colorWithAlphaComponent_(0.52)
    return AppKit.NSColor.separatorColor().colorWithAlphaComponent_(0.35)


def _slot_frame_fill_color(provider_id: str | None) -> Any:
    if AppKit is None:
        return None
    if provider_id == "claude-code":
        return AppKit.NSColor.systemOrangeColor().colorWithAlphaComponent_(0.12)
    if provider_id == "codex":
        return AppKit.NSColor.labelColor().colorWithAlphaComponent_(0.08)
    return AppKit.NSColor.windowBackgroundColor().colorWithAlphaComponent_(0.22)


def _slot_active_indicator_color(provider_id: str | None) -> Any:
    if AppKit is None:
        return None
    if provider_id == "claude-code":
        return AppKit.NSColor.systemOrangeColor().colorWithAlphaComponent_(0.95)
    if provider_id == "codex":
        return AppKit.NSColor.controlAccentColor().colorWithAlphaComponent_(0.92)
    return AppKit.NSColor.controlAccentColor().colorWithAlphaComponent_(0.88)


def build_usage_status_icon_for_slots(slots: list[dict[str, Any]]) -> Any | None:
    if AppKit is None or Foundation is None:
        return None

    if not slots:
        return None

    slot_count = len(slots)
    group_padding_x = 3.2
    bar_width = max(16.5, 27.0 - max(0, slot_count - 1) * 1.45)
    group_width = bar_width + group_padding_x * 2.0
    image_width = 4.0 + slot_count * group_width + max(0, slot_count - 1) * MENU_BAR_GROUP_GAP
    size = Foundation.NSMakeSize(image_width, 18.0)
    image = AppKit.NSImage.alloc().initWithSize_(size)
    image.setTemplate_(False)
    image.lockFocus()

    group_x = 2.0
    for slot in slots:
        provider_id = str(slot.get("provider_id") or "").strip() or None
        usage = slot.get("usage") or {}
        status = str(usage.get("status") or "")
        is_active = bool(slot.get("active"))

        group_rect = Foundation.NSMakeRect(group_x, 1.0, group_width, 16.0)
        group_path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(group_rect, 4.0, 4.0)
        frame_fill = _slot_frame_fill_color(provider_id) or AppKit.NSColor.windowBackgroundColor().colorWithAlphaComponent_(0.22)
        if is_active:
            frame_fill = frame_fill.colorWithAlphaComponent_(min(0.32, frame_fill.alphaComponent() + 0.12))
        frame_fill.setFill()
        group_path.fill()
        frame_stroke = _slot_frame_stroke_color(provider_id) or AppKit.NSColor.separatorColor().colorWithAlphaComponent_(0.28)
        frame_stroke.setStroke()
        group_path.setLineWidth_(1.65 if is_active else 1.1)
        group_path.stroke()

        if is_active:
            inner_rect = Foundation.NSMakeRect(group_x + 0.85, 1.85, group_width - 1.7, 14.3)
            inner_path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(inner_rect, 3.2, 3.2)
            (_slot_active_indicator_color(provider_id) or AppKit.NSColor.controlAccentColor()).setStroke()
            inner_path.setLineWidth_(1.05)
            inner_path.stroke()

        bar_x = group_x + group_padding_x
        top_track = Foundation.NSMakeRect(bar_x, 9.5, bar_width, 3.0)
        bottom_track = Foundation.NSMakeRect(bar_x, 4.5, bar_width, 3.0)
        for rect, percent in (
            (top_track, usage.get("five_hour_percent")),
            (bottom_track, usage.get("seven_day_percent")),
        ):
            track_path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, 2.0, 2.0)
            AppKit.NSColor.tertiaryLabelColor().colorWithAlphaComponent_(0.26).setFill()
            track_path.fill()

            tone = usage_progress_tone(percent, status=status)
            fill_color = _nscolor_for_tone(tone)
            if fill_color is None:
                continue

            try:
                normalized = max(0.0, min(100.0, float(percent)))
            except (TypeError, ValueError):
                normalized = 100.0 if status in {"unauthorized", "error", "auth_missing"} else 12.0

            fill_width = max(2.0, rect.size.width * normalized / 100.0)
            fill_rect = Foundation.NSMakeRect(
                rect.origin.x,
                rect.origin.y,
                fill_width,
                rect.size.height,
            )
            fill_path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(fill_rect, 2.0, 2.0)
            fill_color.setFill()
            fill_path.fill()

        group_x += group_width + MENU_BAR_GROUP_GAP

    image.unlockFocus()
    return image


def build_loading_status_icon() -> Any | None:
    if AppKit is None or Foundation is None:
        return None

    size = Foundation.NSMakeSize(28.0, 18.0)
    image = AppKit.NSImage.alloc().initWithSize_(size)
    image.setTemplate_(False)
    image.lockFocus()

    frame_rect = Foundation.NSMakeRect(3.0, 3.0, 22.0, 12.0)
    frame_path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(frame_rect, 4.0, 4.0)
    AppKit.NSColor.tertiaryLabelColor().colorWithAlphaComponent_(0.14).setFill()
    frame_path.fill()
    AppKit.NSColor.tertiaryLabelColor().colorWithAlphaComponent_(0.28).setStroke()
    frame_path.setLineWidth_(1.0)
    frame_path.stroke()

    for x in (8.0, 12.5, 17.0):
        dot_rect = Foundation.NSMakeRect(x, 7.0, 2.4, 2.4)
        dot_path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(dot_rect, 1.2, 1.2)
        AppKit.NSColor.tertiaryLabelColor().colorWithAlphaComponent_(0.7).setFill()
        dot_path.fill()

    image.unlockFocus()
    return image


def build_usage_status_icon(overview: dict[str, Any]) -> Any | None:
    return build_usage_status_icon_for_slots(tray_usage_slots(overview))


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
    try:
        console_window: NativeHubWindow | None = NativeHubWindow(open_dashboard=dashboard.ensure_started)
    except AuthHubError:
        console_window = None
    interval = max(3.0, float(refresh_seconds))

    def disabled_item(title: str) -> Any:
        item = rumps.MenuItem(title)
        item.set_callback(None)
        return item

    class AuthHubTrayApp(rumps.App):
        def __init__(self) -> None:
            super().__init__(APP_NAME, title=STATUS_ITEM_HIDDEN_TITLE, quit_button=None)
            self._timer = rumps.Timer(self._refresh_from_timer, TRAY_UI_POLL_SECONDS)
            now = time.monotonic()
            self._last_usage_refresh_at = {
                provider: now
                for provider in hub.provider_ids()
            }
            self._last_overview_refresh_at = 0.0
            self._latest_overviews: dict[str, dict[str, Any]] | None = None
            self._pending_overviews: dict[str, dict[str, Any]] | None = None
            self._pending_error: str | None = None
            self._pending_usage_refreshed: list[str] = []
            self._refresh_lock = threading.Lock()
            self._refresh_inflight = False
            self._set_status_item_image(build_loading_status_icon())
            self._set_loading_menu("正在读取状态…")
            self._start_background_refresh(force=True)

        def run(self, **options: Any) -> None:
            self._timer.start()
            try:
                super().run(**options)
            finally:
                self._timer.stop()
                dashboard.shutdown()

        def _refresh_from_timer(self, _sender: Any) -> None:
            self._apply_pending_refresh()
            now = time.monotonic()
            should_refresh_overview = (
                self._latest_overviews is None or now - self._last_overview_refresh_at >= interval
            )
            usage_providers: list[str] = []
            overviews = self._latest_overviews or {}
            for provider in hub.provider_ids():
                provider_overview = overviews.get(provider) or {}
                capabilities = provider_overview.get("capabilities") or {}
                if not capabilities.get("usage_tracking"):
                    continue
                refresh_seconds = float(capabilities.get("usage_auto_refresh_seconds") or DEFAULT_USAGE_AUTO_REFRESH_SECONDS)
                last_refresh_at = self._last_usage_refresh_at.get(provider, 0.0)
                if now - last_refresh_at >= refresh_seconds:
                    usage_providers.append(provider)
            if usage_providers or should_refresh_overview:
                self._start_background_refresh(include_usage_providers=usage_providers)

        def _fetch_overviews(self) -> dict[str, dict[str, Any]]:
            return {
                provider: hub.provider_overview(provider)
                for provider in hub.provider_ids()
            }

        def _set_loading_menu(self, message: str) -> None:
            self._set_status_item_visuals(self._latest_overviews)
            self.menu.clear()
            self.menu.update(
                [
                    disabled_item(APP_NAME),
                    None,
                    disabled_item(message),
                    None,
                    rumps.MenuItem("打开控制台", callback=self._open_dashboard),
                    rumps.MenuItem("刷新状态", callback=self._manual_refresh),
                    rumps.MenuItem("退出", callback=self._quit),
                ]
            )

        def _start_background_refresh(
            self,
            *,
            include_usage_providers: list[str] | None = None,
            force: bool = False,
        ) -> None:
            with self._refresh_lock:
                if self._refresh_inflight and not force:
                    return
                if self._refresh_inflight:
                    return
                self._refresh_inflight = True

            def worker() -> None:
                overviews: dict[str, dict[str, Any]] | None = None
                error_message: str | None = None
                usage_refreshed: list[str] = []
                try:
                    for provider in include_usage_providers or []:
                        try:
                            hub.refresh_all_usage(provider)
                        except AuthHubError:
                            continue
                        usage_refreshed.append(provider)
                    overviews = self._fetch_overviews()
                except (AuthHubError, OSError) as exc:
                    error_message = str(exc)
                finally:
                    with self._refresh_lock:
                        self._pending_overviews = overviews
                        self._pending_error = error_message
                        self._pending_usage_refreshed = usage_refreshed
                        self._refresh_inflight = False

            threading.Thread(
                target=worker,
                name="agent-account-hub-tray-refresh",
                daemon=True,
            ).start()

        def _apply_pending_refresh(self) -> None:
            with self._refresh_lock:
                overviews = self._pending_overviews
                error_message = self._pending_error
                usage_refreshed = self._pending_usage_refreshed
                self._pending_overviews = None
                self._pending_error = None
                self._pending_usage_refreshed = []

            if overviews is not None:
                self._latest_overviews = overviews
                self._last_overview_refresh_at = time.monotonic()
                if usage_refreshed:
                    refreshed_at = time.monotonic()
                    for provider in usage_refreshed:
                        self._last_usage_refresh_at[provider] = refreshed_at
                self._set_status_item_visuals(overviews)
                self.menu.clear()
                self.menu.update(self._build_menu_items(overviews))
                return

            if error_message and self._latest_overviews is None:
                self._set_status_item_visuals(None, error=True)
                self.menu.clear()
                self.menu.update(
                    [
                        disabled_item(APP_NAME),
                        None,
                        disabled_item(f"读取失败: {error_message}"),
                        None,
                        rumps.MenuItem("刷新状态", callback=self._manual_refresh),
                        rumps.MenuItem("打开控制台", callback=self._open_dashboard),
                        rumps.MenuItem("退出", callback=self._quit),
                    ]
                )
                return

            if error_message and self._latest_overviews is not None:
                self._set_status_item_visuals(self._latest_overviews)
                self.menu.clear()
                self.menu.update(self._build_menu_items(self._latest_overviews))
                return

        def _reload_menu(self) -> None:
            try:
                overviews = self._fetch_overviews()
            except (AuthHubError, OSError) as exc:
                self._set_status_item_visuals(None, error=True)
                self.menu.clear()
                self.menu.update(
                    [
                        disabled_item(APP_NAME),
                        None,
                        disabled_item(f"读取失败: {exc}"),
                        None,
                        rumps.MenuItem("刷新状态", callback=self._manual_refresh),
                        rumps.MenuItem("打开控制台", callback=self._open_dashboard),
                        rumps.MenuItem("退出", callback=self._quit),
                    ]
                )
                return

            self._latest_overviews = overviews
            self._last_overview_refresh_at = time.monotonic()
            self._set_status_item_visuals(overviews)
            self.menu.clear()
            self.menu.update(self._build_menu_items(overviews))

        def _set_status_item_visuals(
            self,
            overviews: dict[str, dict[str, Any]] | None,
            *,
            error: bool = False,
        ) -> None:
            if error:
                self._set_status_item_image(None)
                self._set_native_status_title("Hub !")
                return

            if overviews:
                image = build_usage_status_icon_for_slots(tray_usage_slots_from_overviews(overviews))
                self._set_status_item_image(image)
                self._set_native_status_title("" if image is not None else "Hub")
                return

            self._set_status_item_image(build_loading_status_icon())
            self._set_native_status_title("")

        def _set_status_item_image(self, image: Any | None) -> None:
            self._icon = None
            self._icon_nsimage = image
            try:
                self._nsapp.setStatusBarIcon()
            except AttributeError:
                pass

        def _set_native_status_title(self, title: str) -> None:
            normalized = title if title else STATUS_ITEM_HIDDEN_TITLE
            self._title = normalized
            try:
                self._nsapp.nsstatusitem.setTitle_(normalized)
            except AttributeError:
                pass

        def _build_menu_items(self, overviews: dict[str, dict[str, Any]]) -> list[Any]:
            items: list[Any] = [
                disabled_item(APP_NAME),
            ]

            for provider in hub.provider_ids():
                items.extend([None, self._build_provider_menu(provider, overviews[provider])])

            items.extend(
                [
                    None,
                    rumps.MenuItem("打开控制台", callback=self._open_dashboard),
                    rumps.MenuItem("刷新状态", callback=self._manual_refresh),
                    rumps.MenuItem("退出", callback=self._quit),
                ]
            )
            return items

        def _build_provider_menu(self, provider: str, overview: dict[str, Any]) -> Any:
            current = overview["current"]
            accounts = overview.get("accounts") or overview.get("slots") or []
            capabilities = overview.get("capabilities") or {}
            usage_supported = bool(capabilities.get("usage_tracking"))
            usage_manual_auth = capabilities.get("usage_auth_mode") == "manual"
            configured_usage_accounts = sum(
                1 for slot in accounts if (slot.get("usage_auth") or {}).get("configured")
            )
            menu_bar_usage_accounts = tray_usage_slots(overview)
            provider_menu = rumps.MenuItem(provider_label(provider))
            items = [
                disabled_item(f"当前邮箱: {current.get('email') or '—'}"),
                disabled_item(f"当前身份: {summary_identity(current)}"),
                disabled_item(f"Plan: {current.get('plan_type') or '—'}"),
                disabled_item(f"快照同步: {snapshot_sync_label(current)}"),
                disabled_item(f"已保存账号: {len(accounts)}"),
            ]
            if usage_supported:
                summary_label = "已配置用量" if usage_manual_auth else "可查询用量"
                items.append(disabled_item(f"{summary_label}: {configured_usage_accounts}"))
                items.append(disabled_item(f"菜单栏展示: {len(menu_bar_usage_accounts)}"))
            items.extend(
                [
                    None,
                    rumps.MenuItem("保存当前为新账号", callback=self._create_new_account(provider)),
                ]
            )
            if usage_supported:
                items.append(rumps.MenuItem("刷新全部用量", callback=self._refresh_all_usage(provider)))
            items.extend(
                [
                    None,
                    *[
                        self._build_slot_menu(
                            provider,
                            slot,
                            usage_supported=usage_supported,
                            usage_manual_auth=usage_manual_auth,
                        )
                        for slot in accounts
                    ],
                ]
            )
            provider_menu.update(items)
            return provider_menu

        def _build_slot_menu(
            self,
            provider: str,
            slot: dict[str, Any],
            *,
            usage_supported: bool,
            usage_manual_auth: bool,
        ) -> Any:
            slot_id = str(slot["id"])
            snapshot = slot["snapshot"]
            slot_label = slot_display_label(slot)
            slot_identity = slot_preview_identity(snapshot)
            usage = slot.get("usage") or {}
            usage_auth = slot.get("usage_auth") or {}

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

            refresh_usage_item = rumps.MenuItem("刷新这个账号的用量")
            refresh_usage_item.set_callback(
                self._refresh_slot_usage(provider, slot_id, slot_label)
                if usage_supported and usage_auth.get("configured")
                else None
            )

            clear_item = rumps.MenuItem("删除这个账号")
            clear_item.set_callback(
                self._clear_slot(provider, slot_id, slot_label) if snapshot["exists"] else None
            )

            items = [
                disabled_item(f"状态: {'当前账号' if slot.get('active') else '已保存'}"),
                disabled_item(f"名称: {slot_label}"),
                disabled_item(f"邮箱: {snapshot.get('email') or '—'}"),
                disabled_item(f"姓名: {snapshot.get('name') or '—'}"),
                disabled_item(f"身份: {slot_identity}"),
                disabled_item(f"账号 ID: {snapshot.get('account_id') or '—'}"),
                disabled_item(f"Plan: {snapshot.get('plan_type') or '—'}"),
            ]
            if usage_supported:
                items.extend(
                    [
                        disabled_item(f"用量: {usage_summary_label(slot)}"),
                        disabled_item(f"用量状态: {usage_status_label(usage, usage_auth)}"),
                        disabled_item(
                            "来源: "
                            + (
                                usage_auth.get("organization_name")
                                or usage_auth.get("organization_id")
                                or ("已保存 access token" if usage_auth.get("configured") else "缺少 access token")
                            )
                        ),
                        disabled_item(f"菜单栏: {'展示中' if slot.get('usage_menu_bar_visible') else '未展示'}"),
                    ]
                )
            items.extend(
                [
                    None,
                    switch_item,
                    capture_item,
                    rename_item,
                ]
            )
            if usage_supported:
                items.append(refresh_usage_item)
                items.append(
                    rumps.MenuItem(
                        "打开控制台查看更多",
                        callback=self._open_dashboard,
                    )
                )
            items.append(clear_item)
            slot_menu.update(items)
            return slot_menu

        def _manual_refresh(self, _sender: Any) -> None:
            self._set_loading_menu("正在刷新状态…")
            self._start_background_refresh(force=True)

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
                self._start_background_refresh(force=True)

            return callback

        def _open_dashboard(self, _sender: Any) -> None:
            try:
                url = dashboard.ensure_started()
            except OSError as exc:
                rumps.alert("无法启动控制台", str(exc))
                return

            if console_window is not None:
                try:
                    console_window.show()
                except AuthHubError:
                    pass
                else:
                    self._notify(APP_NAME, "已打开控制台", "应用内控制台已置前")
                    return

            webbrowser.open(url)
            self._notify(APP_NAME, "已在浏览器中打开控制台", url)

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
                self._start_background_refresh(force=True)

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
                self._start_background_refresh(force=True)

            return callback

        def _switch_slot(self, provider: str, slot_id: str, slot_label: str):
            def callback(_sender: Any) -> None:
                try:
                    hub.switch(provider, slot_id)
                except AuthHubError as exc:
                    rumps.alert("切换失败", str(exc))
                    return

                self._notify(APP_NAME, "切换成功", f"{provider_label(provider)} 已切换到 {slot_label}")
                self._start_background_refresh(force=True)

            return callback

        def _refresh_slot_usage(self, provider: str, slot_id: str, slot_label: str):
            def callback(_sender: Any) -> None:
                try:
                    hub.refresh_usage(provider, slot_id)
                except AuthHubError as exc:
                    rumps.alert("刷新用量失败", str(exc))
                    return

                self._last_usage_refresh_at[provider] = time.monotonic()
                self._notify(APP_NAME, "用量已刷新", f"{provider_label(provider)} {slot_label} 的用量已更新")
                self._start_background_refresh(force=True)

            return callback

        def _refresh_all_usage(self, provider: str):
            def callback(_sender: Any) -> None:
                try:
                    hub.refresh_all_usage(provider)
                except AuthHubError as exc:
                    rumps.alert("刷新全部用量失败", str(exc))
                    return

                self._last_usage_refresh_at[provider] = time.monotonic()
                self._notify(APP_NAME, "用量已刷新", f"{provider_label(provider)} 已刷新可查询账号的用量")
                self._start_background_refresh(force=True)

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
                self._start_background_refresh(force=True)

            return callback

        def _quit(self, _sender: Any) -> None:
            if console_window is not None:
                console_window.close()
            dashboard.shutdown()
            rumps.quit_application()

        def _notify(self, title: str, subtitle: str, message: str) -> None:
            try:
                rumps.notification(title, subtitle, message, sound=False)
            except RuntimeError:
                pass

    AuthHubTrayApp().run()
