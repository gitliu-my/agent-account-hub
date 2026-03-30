from __future__ import annotations

from typing import Any

from .providers import provider_label


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


def format_usage_percent(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    rounded = round(numeric, 1)
    if abs(rounded - round(rounded)) < 0.01:
        return f"{int(round(rounded))}%"
    return f"{rounded:.1f}%"


def usage_status_label(usage: dict[str, Any], usage_auth: dict[str, Any] | None = None) -> str:
    usage_auth = usage_auth or {}
    configured = bool(
        usage_auth.get("configured")
        or usage_auth.get("organization_id")
        or usage_auth.get("has_session_key")
        or usage_auth.get("has_access_token")
    )
    if not configured:
        return "未配置"
    status = str(usage.get("status") or "")
    if status == "ok":
        return "已同步"
    if status == "stale":
        return "缓存过期"
    if status == "unauthorized":
        return "认证失效"
    if status == "rate_limited":
        return "请求受限"
    if status == "auth_missing":
        return "缺少凭据"
    if status == "error":
        return "刷新失败"
    return "待刷新"


def usage_summary_label(slot: dict[str, Any]) -> str:
    if "usage" not in slot and "usage_auth" not in slot:
        return "—"
    usage = slot.get("usage") or {}
    usage_auth = slot.get("usage_auth") or {}
    five_hour = format_usage_percent(usage.get("five_hour_percent"))
    seven_day = format_usage_percent(usage.get("seven_day_percent"))
    if five_hour or seven_day:
        parts = []
        if five_hour:
            parts.append(f"5h 已用 {five_hour}")
        if seven_day:
            parts.append(f"7d 已用 {seven_day}")
        return " / ".join(parts)
    return usage_status_label(usage, usage_auth)


def tray_title(overview: dict[str, Any]) -> str:
    return "Hub"


def current_summary_items(
    provider: str,
    current: dict[str, Any],
    *,
    account_count: int,
) -> list[tuple[str, str]]:
    matched_account = (
        current.get("matched_account_label")
        or current.get("matched_account_id")
        or current.get("matched_slot_id")
        or "未关联快照"
    )
    return [
        ("Provider", provider_label(provider)),
        ("当前身份", summary_identity(current)),
        ("当前邮箱", str(current.get("email") or "—")),
        ("已关联快照", str(matched_account)),
        ("Plan", str(current.get("plan_type") or "—")),
        ("认证方式", str(current.get("auth_mode") or "—")),
        ("快照同步", snapshot_sync_label(current)),
        ("已保存账号", str(account_count)),
    ]


def slot_table_row(slot: dict[str, Any]) -> dict[str, str | bool]:
    snapshot = slot.get("snapshot", {})
    return {
        "id": str(slot.get("id") or ""),
        "status": slot_status_label(slot),
        "label": slot_display_label(slot),
        "email": str(snapshot.get("email") or "—"),
        "identity": slot_preview_identity(snapshot),
        "plan": str(snapshot.get("plan_type") or "—"),
        "usage": usage_summary_label(slot),
        "exists": bool(snapshot.get("exists")),
        "active": bool(slot.get("active")),
    }
