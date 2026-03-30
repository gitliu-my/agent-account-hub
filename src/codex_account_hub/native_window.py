from __future__ import annotations

import webbrowser
from typing import Any, Callable

from .core import AuthHubError
from .providers import UnifiedAuthHub, provider_label
from .ui_helpers import APP_NAME, current_summary_items, slot_table_row

try:
    import AppKit
    import Foundation
    import objc
except ImportError:
    AppKit = None
    Foundation = None
    objc = None


if objc is not None:
    python_method = objc.python_method
else:
    def python_method(func):  # type: ignore[misc]
        return func


if AppKit is not None and Foundation is not None and objc is not None:
    class _HubWindowController(Foundation.NSObject):
        def init(self):
            self = objc.super(_HubWindowController, self).init()
            if self is None:
                return None

            self.hub = None
            self.open_dashboard = None
            self.provider_ids: list[str] = []
            self.provider_titles: dict[str, str] = {}
            self.current_provider = "codex"
            self._overview: dict[str, Any] = {}
            self._rows: list[dict[str, str | bool]] = []
            self._accounts: list[dict[str, Any]] = []
            self._selected_account_id: str | None = None
            self.window = None
            self.provider_popup = None
            self.summary_fields: dict[str, Any] = {}
            self.table_view = None
            self.status_label = None
            self.switch_button = None
            self.capture_button = None
            self.rename_button = None
            self.delete_button = None
            return self

        @python_method
        def configure(self, hub: UnifiedAuthHub, open_dashboard: Callable[[], str]) -> None:
            self.hub = hub
            self.open_dashboard = open_dashboard
            self.provider_ids = list(hub.provider_ids())
            self.provider_titles = {provider_label(provider): provider for provider in self.provider_ids}
            if self.provider_ids:
                self.current_provider = self.provider_ids[0]
            self._build_window()
            self.reload_data()

        @python_method
        def show(self) -> None:
            self.reload_data()
            self.window.center()
            self.window.makeKeyAndOrderFront_(None)
            AppKit.NSApp.activateIgnoringOtherApps_(True)

        @python_method
        def reload_data(self, status_message: str | None = None) -> None:
            if self.hub is None:
                return

            try:
                overview = self.hub.provider_overview(self.current_provider)
            except (AuthHubError, OSError) as exc:
                self._set_status(str(exc), error=True)
                return

            self._overview = overview
            self._accounts = list(overview.get("accounts") or overview.get("slots") or [])
            self._rows = [slot_table_row(slot) for slot in self._accounts]
            self._reload_summary_fields()
            self.table_view.reloadData()
            self._restore_selection()
            self._update_action_buttons()
            if status_message:
                self._set_status(status_message)

        @python_method
        def _build_window(self) -> None:
            if self.window is not None:
                return

            style_mask = (
                AppKit.NSWindowStyleMaskTitled
                | AppKit.NSWindowStyleMaskClosable
                | AppKit.NSWindowStyleMaskMiniaturizable
                | AppKit.NSWindowStyleMaskResizable
            )
            rect = Foundation.NSMakeRect(0, 0, 1080, 720)
            self.window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                rect,
                style_mask,
                AppKit.NSBackingStoreBuffered,
                False,
            )
            self.window.setTitle_(APP_NAME)
            self.window.setReleasedWhenClosed_(False)
            self.window.setMinSize_(Foundation.NSMakeSize(960, 640))

            content = self.window.contentView()

            title_label = self._make_label(
                Foundation.NSMakeRect(24, 670, 360, 28),
                APP_NAME,
                font=AppKit.NSFont.boldSystemFontOfSize_(26),
            )
            content.addSubview_(title_label)

            subtitle_label = self._make_label(
                Foundation.NSMakeRect(24, 646, 540, 18),
                "原生 app 控制台，直接在应用里切换和管理账号。",
                color=AppKit.NSColor.secondaryLabelColor(),
            )
            content.addSubview_(subtitle_label)

            self.provider_popup = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
                Foundation.NSMakeRect(24, 606, 180, 30),
                False,
            )
            for provider in self.provider_ids:
                self.provider_popup.addItemWithTitle_(provider_label(provider))
            self.provider_popup.setTarget_(self)
            self.provider_popup.setAction_("providerChanged:")
            content.addSubview_(self.provider_popup)

            refresh_button = self._make_button(
                "刷新状态",
                Foundation.NSMakeRect(220, 604, 100, 32),
                "refreshClicked:",
            )
            content.addSubview_(refresh_button)

            save_button = self._make_button(
                "保存当前为新账号",
                Foundation.NSMakeRect(332, 604, 148, 32),
                "saveCurrentAsNew:",
            )
            content.addSubview_(save_button)

            web_button = self._make_button(
                "打开网页控制台",
                Foundation.NSMakeRect(492, 604, 132, 32),
                "openWebConsole:",
            )
            content.addSubview_(web_button)

            current_box = AppKit.NSBox.alloc().initWithFrame_(Foundation.NSMakeRect(24, 432, 1032, 150))
            current_box.setTitle_("当前登录")
            current_box.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewMinYMargin)
            content.addSubview_(current_box)
            self._build_summary_grid(current_box.contentView())

            table_label = self._make_label(
                Foundation.NSMakeRect(24, 404, 240, 18),
                "已保存账号",
                font=AppKit.NSFont.boldSystemFontOfSize_(15),
            )
            table_label.setAutoresizingMask_(AppKit.NSViewMaxXMargin | AppKit.NSViewMinYMargin)
            content.addSubview_(table_label)

            table_hint = self._make_label(
                Foundation.NSMakeRect(24, 384, 480, 16),
                "选中一个账号后，可以直接切换、覆盖、重命名或删除；Claude 账号还会显示用量摘要。",
                color=AppKit.NSColor.secondaryLabelColor(),
            )
            table_hint.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewMinYMargin)
            content.addSubview_(table_hint)

            self._build_accounts_table(content)
            self._build_action_row(content)

            self.status_label = self._make_label(
                Foundation.NSMakeRect(24, 20, 1032, 20),
                "就绪",
                color=AppKit.NSColor.secondaryLabelColor(),
            )
            self.status_label.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewMaxYMargin)
            content.addSubview_(self.status_label)

        @python_method
        def _build_summary_grid(self, view: Any) -> None:
            pairs = [
                ("Provider", (18, 90)),
                ("当前身份", (18, 46)),
                ("当前邮箱", (280, 90)),
                ("已关联快照", (280, 46)),
                ("Plan", (542, 90)),
                ("认证方式", (542, 46)),
                ("快照同步", (804, 90)),
                ("已保存账号", (804, 46)),
            ]
            for title, (x, y) in pairs:
                label = self._make_label(
                    Foundation.NSMakeRect(x, y + 18, 120, 16),
                    title,
                    color=AppKit.NSColor.secondaryLabelColor(),
                )
                value = self._make_label(
                    Foundation.NSMakeRect(x, y, 214, 22),
                    "—",
                    font=AppKit.NSFont.systemFontOfSize_(14),
                )
                value.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
                value.setAutoresizingMask_(AppKit.NSViewMaxXMargin | AppKit.NSViewMinYMargin)
                view.addSubview_(label)
                view.addSubview_(value)
                self.summary_fields[title] = value

        @python_method
        def _build_accounts_table(self, content: Any) -> None:
            scroll = AppKit.NSScrollView.alloc().initWithFrame_(Foundation.NSMakeRect(24, 116, 1032, 250))
            scroll.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
            scroll.setHasVerticalScroller_(True)
            scroll.setAutohidesScrollers_(True)
            table = AppKit.NSTableView.alloc().initWithFrame_(scroll.bounds())
            table.setDelegate_(self)
            table.setDataSource_(self)
            table.setUsesAlternatingRowBackgroundColors_(True)
            table.setAllowsEmptySelection_(True)
            table.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)

            for identifier, title, width in [
                ("status", "状态", 96),
                ("label", "名称", 220),
                ("email", "邮箱", 250),
                ("identity", "身份", 280),
                ("plan", "Plan", 120),
                ("usage", "用量", 140),
            ]:
                column = AppKit.NSTableColumn.alloc().initWithIdentifier_(identifier)
                column.headerCell().setStringValue_(title)
                column.setWidth_(width)
                table.addTableColumn_(column)

            scroll.setDocumentView_(table)
            content.addSubview_(scroll)
            self.table_view = table

        @python_method
        def _build_action_row(self, content: Any) -> None:
            self.switch_button = self._make_button(
                "切换到选中账号",
                Foundation.NSMakeRect(24, 64, 146, 34),
                "switchSelectedAccount:",
            )
            self.capture_button = self._make_button(
                "用当前登录覆盖",
                Foundation.NSMakeRect(182, 64, 146, 34),
                "captureSelectedAccount:",
            )
            self.rename_button = self._make_button(
                "重命名",
                Foundation.NSMakeRect(340, 64, 100, 34),
                "renameSelectedAccount:",
            )
            self.delete_button = self._make_button(
                "删除",
                Foundation.NSMakeRect(452, 64, 100, 34),
                "deleteSelectedAccount:",
            )

            for button in [
                self.switch_button,
                self.capture_button,
                self.rename_button,
                self.delete_button,
            ]:
                button.setAutoresizingMask_(AppKit.NSViewMaxXMargin | AppKit.NSViewMaxYMargin)
                content.addSubview_(button)

        @python_method
        def _make_label(
            self,
            frame: Any,
            text: str,
            *,
            font: Any | None = None,
            color: Any | None = None,
        ) -> Any:
            field = AppKit.NSTextField.alloc().initWithFrame_(frame)
            field.setBezeled_(False)
            field.setDrawsBackground_(False)
            field.setEditable_(False)
            field.setSelectable_(False)
            field.setStringValue_(text)
            if font is not None:
                field.setFont_(font)
            if color is not None:
                field.setTextColor_(color)
            return field

        @python_method
        def _make_button(self, title: str, frame: Any, action: str) -> Any:
            button = AppKit.NSButton.alloc().initWithFrame_(frame)
            button.setTitle_(title)
            button.setBezelStyle_(AppKit.NSBezelStyleRounded)
            button.setTarget_(self)
            button.setAction_(action)
            return button

        @python_method
        def _reload_summary_fields(self) -> None:
            current = self._overview.get("current", {})
            items = current_summary_items(
                self.current_provider,
                current,
                account_count=len(self._accounts),
            )
            for title, value in items:
                field = self.summary_fields.get(title)
                if field is not None:
                    field.setStringValue_(value)
            self.provider_popup.selectItemWithTitle_(provider_label(self.current_provider))

        @python_method
        def _restore_selection(self) -> None:
            if not self._rows:
                self.table_view.deselectAll_(None)
                self._selected_account_id = None
                return

            selected_index = 0
            if self._selected_account_id:
                for index, row in enumerate(self._rows):
                    if row["id"] == self._selected_account_id:
                        selected_index = index
                        break
            index_set = Foundation.NSIndexSet.indexSetWithIndex_(selected_index)
            self.table_view.selectRowIndexes_byExtendingSelection_(index_set, False)
            self._selected_account_id = str(self._rows[selected_index]["id"])

        @python_method
        def _selected_slot(self) -> dict[str, Any]:
            row = int(self.table_view.selectedRow())
            if row < 0 or row >= len(self._accounts):
                raise AuthHubError("请先在下方选中一个已保存账号。")
            self._selected_account_id = str(self._accounts[row]["id"])
            return self._accounts[row]

        @python_method
        def _set_status(self, message: str, *, error: bool = False) -> None:
            self.status_label.setStringValue_(message)
            color = AppKit.NSColor.systemRedColor() if error else AppKit.NSColor.secondaryLabelColor()
            self.status_label.setTextColor_(color)

        @python_method
        def _show_error(self, title: str, message: str) -> None:
            alert = AppKit.NSAlert.alloc().init()
            alert.setAlertStyle_(AppKit.NSAlertStyleWarning)
            alert.setMessageText_(title)
            alert.setInformativeText_(message)
            alert.runModal()

        @python_method
        def _show_rename_prompt(self, current_label: str) -> str | None:
            alert = AppKit.NSAlert.alloc().init()
            alert.setMessageText_("重命名账号")
            alert.setInformativeText_("给这个账号起一个更容易识别的名字。")
            text_field = AppKit.NSTextField.alloc().initWithFrame_(Foundation.NSMakeRect(0, 0, 280, 24))
            text_field.setStringValue_(current_label)
            alert.setAccessoryView_(text_field)
            alert.addButtonWithTitle_("保存")
            alert.addButtonWithTitle_("取消")
            result = alert.runModal()
            if result != AppKit.NSAlertFirstButtonReturn:
                return None
            next_label = str(text_field.stringValue() or "").strip()
            return next_label or None

        @python_method
        def _confirm_delete(self, slot_label: str) -> bool:
            alert = AppKit.NSAlert.alloc().init()
            alert.setMessageText_(f"删除 {slot_label}")
            alert.setInformativeText_("这会删除已保存快照，但不会删除当前正在使用的凭据。")
            alert.addButtonWithTitle_("删除")
            alert.addButtonWithTitle_("取消")
            return alert.runModal() == AppKit.NSAlertFirstButtonReturn

        @python_method
        def _update_action_buttons(self) -> None:
            has_rows = bool(self._rows)
            selected_exists = False
            if has_rows:
                row = int(self.table_view.selectedRow())
                if 0 <= row < len(self._rows):
                    selected_exists = bool(self._rows[row]["exists"])

            self.switch_button.setEnabled_(has_rows and selected_exists)
            self.capture_button.setEnabled_(has_rows)
            self.rename_button.setEnabled_(has_rows)
            self.delete_button.setEnabled_(has_rows and selected_exists)

        def numberOfRowsInTableView_(self, _table_view: Any) -> int:
            return len(self._rows)

        def tableView_objectValueForTableColumn_row_(
            self,
            _table_view: Any,
            table_column: Any,
            row: int,
        ) -> str:
            identifier = str(table_column.identifier())
            return str(self._rows[row].get(identifier) or "")

        def tableViewSelectionDidChange_(self, _notification: Any) -> None:
            row = int(self.table_view.selectedRow())
            if 0 <= row < len(self._rows):
                self._selected_account_id = str(self._rows[row]["id"])
            self._update_action_buttons()

        def providerChanged_(self, sender: Any) -> None:
            title = str(sender.titleOfSelectedItem() or "")
            provider = self.provider_titles.get(title)
            if provider:
                self.current_provider = provider
                self._selected_account_id = None
                self.reload_data()

        def refreshClicked_(self, _sender: Any) -> None:
            self.reload_data("已刷新原生控制台")

        def saveCurrentAsNew_(self, _sender: Any) -> None:
            try:
                payload = self.hub.create_account_from_current(self.current_provider)
            except AuthHubError as exc:
                self._show_error("保存失败", str(exc))
                return

            snapshot = payload.get("snapshot", {})
            identity = str(snapshot.get("email") or snapshot.get("name") or snapshot.get("account_id") or "当前登录")
            if payload.get("created_new_account"):
                status_message = f"已保存为新账号：{identity}"
            else:
                status_message = f"已更新已有账号：{identity}"
            self.reload_data(status_message)

        def openWebConsole_(self, _sender: Any) -> None:
            try:
                url = self.open_dashboard()
            except OSError as exc:
                self._show_error("无法启动网页控制台", str(exc))
                return

            webbrowser.open(url)
            self._set_status(f"已打开网页控制台：{url}")

        def switchSelectedAccount_(self, _sender: Any) -> None:
            try:
                slot = self._selected_slot()
                self.hub.switch(self.current_provider, str(slot["id"]))
            except AuthHubError as exc:
                self._show_error("切换失败", str(exc))
                return

            self.reload_data(f"已切换到 {slot_table_row(slot)['label']}")

        def captureSelectedAccount_(self, _sender: Any) -> None:
            try:
                slot = self._selected_slot()
                payload = self.hub.save_current_to_account(self.current_provider, str(slot["id"]))
            except AuthHubError as exc:
                self._show_error("保存失败", str(exc))
                return

            moved = payload.get("cleared_account_ids") or payload.get("cleared_slot_ids") or []
            message = f"已用当前登录覆盖 {slot_table_row(slot)['label']}"
            if moved:
                message += f"；并移除重复账号 {', '.join(moved)}"
            self.reload_data(message)

        def renameSelectedAccount_(self, _sender: Any) -> None:
            try:
                slot = self._selected_slot()
            except AuthHubError as exc:
                self._show_error("无法重命名", str(exc))
                return

            current_label = str(slot_table_row(slot)["label"])
            next_label = self._show_rename_prompt(current_label)
            if not next_label or next_label == current_label:
                return

            try:
                self.hub.rename_account(self.current_provider, str(slot["id"]), next_label)
            except AuthHubError as exc:
                self._show_error("重命名失败", str(exc))
                return

            self.reload_data(f"已重命名为 {next_label}")

        def deleteSelectedAccount_(self, _sender: Any) -> None:
            try:
                slot = self._selected_slot()
            except AuthHubError as exc:
                self._show_error("无法删除", str(exc))
                return

            slot_label = str(slot_table_row(slot)["label"])
            if not self._confirm_delete(slot_label):
                return

            try:
                self.hub.delete_account(self.current_provider, str(slot["id"]))
            except AuthHubError as exc:
                self._show_error("删除失败", str(exc))
                return

            self._selected_account_id = None
            self.reload_data(f"已删除 {slot_label}")
else:
    _HubWindowController = None


class NativeHubWindow:
    def __init__(
        self,
        hub: UnifiedAuthHub,
        *,
        open_dashboard: Callable[[], str],
    ) -> None:
        if _HubWindowController is None:
            raise AuthHubError(
                "native app window requires AppKit/PyObjC; run `python3 -m pip install -e .` inside the project venv first"
            )

        controller = _HubWindowController.alloc().init()
        controller.configure(hub, open_dashboard)
        self._controller = controller

    def show(self) -> None:
        self._controller.show()

    def reload_data(self) -> None:
        self._controller.reload_data()
