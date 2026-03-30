from __future__ import annotations

import webbrowser
from typing import Any, Callable

from .core import AuthHubError
from .ui_helpers import APP_NAME

try:
    import AppKit
    import Foundation
    import WebKit
    import objc
except ImportError:
    AppKit = None
    Foundation = None
    WebKit = None
    objc = None


if objc is not None:
    python_method = objc.python_method
else:
    def python_method(func):  # type: ignore[misc]
        return func


if AppKit is not None and Foundation is not None and WebKit is not None and objc is not None:
    class _DashboardWindowController(Foundation.NSObject):
        def init(self):
            self = objc.super(_DashboardWindowController, self).init()
            if self is None:
                return None

            self.open_dashboard = None
            self.window = None
            self.web_view = None
            self.status_label = None
            self.url_label = None
            self._current_url = None
            self._foreground_mode = False
            self._main_menu = None
            self._window_menu = None
            return self

        @python_method
        def configure(self, open_dashboard: Callable[[], str]) -> None:
            self.open_dashboard = open_dashboard
            self._build_window()

        @python_method
        def show(self) -> None:
            self._set_foreground_mode(True)
            self._ensure_dashboard_loaded()
            self.window.makeKeyAndOrderFront_(None)
            AppKit.NSApp.activateIgnoringOtherApps_(True)

        @python_method
        def close(self) -> None:
            if self.window is not None:
                self.window.orderOut_(None)
            self._set_foreground_mode(False)

        @python_method
        def reload(self) -> None:
            self._ensure_dashboard_loaded(force_reload=True)

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
            rect = Foundation.NSMakeRect(0, 0, 1240, 860)
            window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                rect,
                style_mask,
                AppKit.NSBackingStoreBuffered,
                False,
            )
            window.setTitle_(APP_NAME)
            window.setReleasedWhenClosed_(False)
            window.setMinSize_(Foundation.NSMakeSize(980, 700))
            window.setFrameAutosaveName_("AgentAccountHubEmbeddedConsole")
            window.setDelegate_(self)

            content = window.contentView()
            bounds = content.bounds()
            header_height = 86.0

            background = AppKit.NSVisualEffectView.alloc().initWithFrame_(bounds)
            background.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
            background.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
            background.setState_(AppKit.NSVisualEffectStateActive)
            material = getattr(AppKit, "NSVisualEffectMaterialSidebar", None)
            if material is not None:
                background.setMaterial_(material)
            content.addSubview_(background)

            header = AppKit.NSVisualEffectView.alloc().initWithFrame_(
                Foundation.NSMakeRect(0, bounds.size.height - header_height, bounds.size.width, header_height)
            )
            header.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewMinYMargin)
            header.setBlendingMode_(AppKit.NSVisualEffectBlendingModeWithinWindow)
            header.setState_(AppKit.NSVisualEffectStateActive)
            header_material = getattr(AppKit, "NSVisualEffectMaterialHeaderView", None)
            if header_material is None:
                header_material = getattr(AppKit, "NSVisualEffectMaterialWindowBackground", None)
            if header_material is not None:
                header.setMaterial_(header_material)
            background.addSubview_(header)

            title_label = self._make_label(
                Foundation.NSMakeRect(24, 44, 320, 28),
                APP_NAME,
                font=AppKit.NSFont.boldSystemFontOfSize_(26),
            )
            header.addSubview_(title_label)

            subtitle_label = self._make_label(
                Foundation.NSMakeRect(24, 22, 460, 18),
                "应用内控制台，直接在 app 里维护账号、查看用量和菜单栏展示。",
                color=AppKit.NSColor.secondaryLabelColor(),
            )
            header.addSubview_(subtitle_label)

            self.url_label = self._make_label(
                Foundation.NSMakeRect(24, 4, 700, 16),
                "本地控制台尚未启动",
                font=AppKit.NSFont.systemFontOfSize_(11),
                color=AppKit.NSColor.tertiaryLabelColor(),
            )
            self.url_label.setLineBreakMode_(AppKit.NSLineBreakByTruncatingMiddle)
            header.addSubview_(self.url_label)

            open_browser_button = self._make_button(
                "浏览器打开",
                Foundation.NSMakeRect(bounds.size.width - 250, 28, 110, 34),
                "openInBrowserClicked:",
            )
            open_browser_button.setAutoresizingMask_(AppKit.NSViewMinXMargin)
            header.addSubview_(open_browser_button)

            refresh_button = self._make_button(
                "刷新",
                Foundation.NSMakeRect(bounds.size.width - 126, 28, 92, 34),
                "refreshClicked:",
            )
            refresh_button.setAutoresizingMask_(AppKit.NSViewMinXMargin)
            header.addSubview_(refresh_button)

            self.status_label = self._make_label(
                Foundation.NSMakeRect(bounds.size.width - 310, 8, 276, 16),
                "准备就绪",
                font=AppKit.NSFont.systemFontOfSize_(11),
                color=AppKit.NSColor.secondaryLabelColor(),
            )
            self.status_label.setAlignment_(AppKit.NSTextAlignmentRight)
            self.status_label.setAutoresizingMask_(AppKit.NSViewMinXMargin)
            header.addSubview_(self.status_label)

            web_frame = Foundation.NSMakeRect(18, 18, bounds.size.width - 36, bounds.size.height - header_height - 26)
            web_view = WebKit.WKWebView.alloc().initWithFrame_configuration_(
                web_frame,
                WebKit.WKWebViewConfiguration.alloc().init(),
            )
            web_view.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
            background.addSubview_(web_view)

            self.window = window
            self.web_view = web_view

        @python_method
        def _set_foreground_mode(self, enabled: bool) -> None:
            if self._foreground_mode == enabled:
                return
            policy = (
                AppKit.NSApplicationActivationPolicyRegular
                if enabled
                else AppKit.NSApplicationActivationPolicyAccessory
            )
            if enabled:
                self._ensure_main_menu()
            AppKit.NSApp.setActivationPolicy_(policy)
            self._foreground_mode = enabled

        @python_method
        def _ensure_main_menu(self) -> None:
            if self._main_menu is not None:
                AppKit.NSApp.setMainMenu_(self._main_menu)
                if self._window_menu is not None:
                    AppKit.NSApp.setWindowsMenu_(self._window_menu)
                return

            main_menu = AppKit.NSMenu.alloc().initWithTitle_("")

            app_menu_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", None, "")
            app_menu = AppKit.NSMenu.alloc().initWithTitle_(APP_NAME)
            app_menu.addItemWithTitle_action_keyEquivalent_(f"关于 {APP_NAME}", "orderFrontStandardAboutPanel:", "")
            app_menu.addItem_(AppKit.NSMenuItem.separatorItem())
            app_menu.addItemWithTitle_action_keyEquivalent_(f"隐藏 {APP_NAME}", "hide:", "h")
            hide_others = app_menu.addItemWithTitle_action_keyEquivalent_("隐藏其他", "hideOtherApplications:", "h")
            hide_others.setKeyEquivalentModifierMask_(
                AppKit.NSEventModifierFlagCommand | AppKit.NSEventModifierFlagOption
            )
            app_menu.addItemWithTitle_action_keyEquivalent_("显示全部", "unhideAllApplications:", "")
            app_menu.addItem_(AppKit.NSMenuItem.separatorItem())
            app_menu.addItemWithTitle_action_keyEquivalent_(f"退出 {APP_NAME}", "terminate:", "q")
            app_menu_item.setSubmenu_(app_menu)
            main_menu.addItem_(app_menu_item)

            file_menu_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", None, "")
            file_menu = AppKit.NSMenu.alloc().initWithTitle_("文件")
            reload_item = file_menu.addItemWithTitle_action_keyEquivalent_("刷新控制台", "refreshClicked:", "r")
            reload_item.setTarget_(self)
            browser_item = file_menu.addItemWithTitle_action_keyEquivalent_("在浏览器中打开", "openInBrowserClicked:", "o")
            browser_item.setTarget_(self)
            file_menu_item.setSubmenu_(file_menu)
            main_menu.addItem_(file_menu_item)

            window_menu_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", None, "")
            window_menu = AppKit.NSMenu.alloc().initWithTitle_("窗口")
            window_menu.addItemWithTitle_action_keyEquivalent_("最小化", "performMiniaturize:", "m")
            window_menu.addItemWithTitle_action_keyEquivalent_("缩放", "performZoom:", "")
            window_menu.addItemWithTitle_action_keyEquivalent_("关闭窗口", "performClose:", "w")
            window_menu_item.setSubmenu_(window_menu)
            main_menu.addItem_(window_menu_item)

            self._main_menu = main_menu
            self._window_menu = window_menu
            AppKit.NSApp.setMainMenu_(main_menu)
            AppKit.NSApp.setWindowsMenu_(window_menu)

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
            field.setBordered_(False)
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
        def _set_status(self, message: str, *, error: bool = False) -> None:
            if self.status_label is None:
                return
            self.status_label.setStringValue_(message)
            color = AppKit.NSColor.systemRedColor() if error else AppKit.NSColor.secondaryLabelColor()
            self.status_label.setTextColor_(color)

        @python_method
        def _dashboard_url(self) -> str:
            if self.open_dashboard is None:
                raise AuthHubError("控制台窗口尚未配置。")
            url = str(self.open_dashboard() or "").strip()
            if not url:
                raise AuthHubError("无法解析本地控制台地址。")
            return url

        @python_method
        def _ensure_dashboard_loaded(self, *, force_reload: bool = False) -> str:
            url = self._dashboard_url()
            self._load_url(url, force_reload=force_reload)
            self._set_status("应用内控制台已连接")
            return url

        @python_method
        def _load_url(self, url: str, *, force_reload: bool = False) -> None:
            if self.web_view is None:
                raise AuthHubError("控制台窗口尚未初始化。")

            if self.url_label is not None:
                self.url_label.setStringValue_(url)

            if not force_reload and self._current_url == url:
                return

            ns_url = Foundation.NSURL.URLWithString_(url)
            if ns_url is None:
                raise AuthHubError(f"控制台地址无效：{url}")

            request = Foundation.NSURLRequest.requestWithURL_(ns_url)
            self.web_view.loadRequest_(request)
            self._current_url = url

        def refreshClicked_(self, _sender: Any) -> None:
            try:
                self._ensure_dashboard_loaded(force_reload=True)
            except AuthHubError as exc:
                self._set_status(str(exc), error=True)

        def openInBrowserClicked_(self, _sender: Any) -> None:
            try:
                url = self._dashboard_url()
            except AuthHubError as exc:
                self._set_status(str(exc), error=True)
                return

            webbrowser.open(url)
            self._set_status("已在浏览器中打开本地控制台")

        def windowWillClose_(self, _notification: Any) -> None:
            self._set_foreground_mode(False)
else:
    _DashboardWindowController = None


class NativeHubWindow:
    def __init__(self, *, open_dashboard: Callable[[], str]) -> None:
        if _DashboardWindowController is None:
            raise AuthHubError(
                "embedded control center requires AppKit, PyObjC and pyobjc-framework-WebKit in the project venv"
            )

        controller = _DashboardWindowController.alloc().init()
        controller.configure(open_dashboard)
        self._controller = controller

    def show(self) -> None:
        self._controller.show()

    def reload_data(self) -> None:
        self._controller.reload()

    def close(self) -> None:
        self._controller.close()
