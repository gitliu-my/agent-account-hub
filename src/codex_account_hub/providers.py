from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .core import (
    APP_DISPLAY_NAME,
    AuthHub,
    AuthHubError,
    PROJECT_ROOT,
    auth_identity_key,
    atomic_write_bytes,
    atomic_write_json,
    build_auth_summary,
    default_data_root,
    default_state,
    ensure_parent,
    is_placeholder_account_label,
    load_json_file,
    sha256_file,
    suggested_account_label,
    timestamp_to_iso,
    utc_now_iso,
)


CLAUDE_CODE_PROVIDER_ID = "claude-code"
CLAUDE_CODE_PROVIDER_LABEL = "Claude Code"
CODEX_USAGE_API_URL = "https://chatgpt.com/backend-api/wham/usage"
CODEX_USAGE_MIN_REFRESH_SECONDS = 5 * 60
CODEX_USAGE_STALE_SECONDS = 60 * 60
CODEX_USAGE_ERROR_BACKOFF_SECONDS = 90 * 60
CODEX_USAGE_UNAUTHORIZED_BACKOFF_SECONDS = 6 * 60 * 60
CODEX_USAGE_RATE_LIMIT_BACKOFF_SECONDS = 3 * 60 * 60
DEFAULT_CLAUDE_CODE_KEYCHAIN_SERVICE = "Claude Code-credentials"
DEFAULT_CLAUDE_PROFILE_PATH = Path.home() / ".claude.json"
DEFAULT_CLAUDE_CONFIG_DIR = Path.home() / ".claude"
DEFAULT_CLAUDE_USAGE_SESSION_KEYCHAIN_SERVICE = "Agent Account Hub-claude.ai-session"
CLAUDE_AI_API_BASE_URL = "https://claude.ai/api"
CLAUDE_USAGE_STALE_SECONDS = 15 * 60
CLAUDE_STATUSLINE_SCRIPT_NAME = "agent-account-hub-statusline.pl"
CLAUDE_STATUSLINE_WRAPPER_NAME = "agent-account-hub-statusline.sh"


def current_claude_config_dir() -> Path:
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return DEFAULT_CLAUDE_CONFIG_DIR


def provider_label(provider: str) -> str:
    normalized = normalize_provider_name(provider)
    return "Codex" if normalized == "codex" else CLAUDE_CODE_PROVIDER_LABEL


def normalize_provider_name(value: str | None) -> str:
    normalized = (value or "codex").strip().lower().replace("_", "-")
    if normalized in {"codex", "openai", "codex-cli"}:
        return "codex"
    if normalized in {"claude", "claude-code", "claudecode"}:
        return CLAUDE_CODE_PROVIDER_ID
    raise AuthHubError(f"unsupported provider: {value}")


def timestamp_ms_to_iso(value: Any) -> str | None:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return utc_from_timestamp_ms(numeric)


def utc_from_timestamp_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_datetime(value: Any) -> str | None:
    parsed = parse_iso_datetime(value)
    return parsed.isoformat() if parsed else None


def sha256_json_payload(payload: dict[str, Any]) -> str:
    import hashlib

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_subprocess(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise AuthHubError(f"failed to run {' '.join(args)}: {exc}") from exc


def default_claude_code_data_root() -> Path:
    return default_data_root() / "providers" / CLAUDE_CODE_PROVIDER_ID


def empty_claude_summary(path: str, *, exists: bool = False) -> dict[str, Any]:
    return {
        "path": path,
        "exists": exists,
        "status": "missing" if not exists else "invalid",
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
        "org_id": None,
        "org_name": None,
        "logged_in": None,
        "api_provider": None,
        "scopes": [],
        "rate_limit_tier": None,
        "keychain_account_name": None,
        "oauth_account": None,
    }


def claude_summary_from_payload(
    payload: dict[str, Any],
    *,
    path: str,
    status_payload: dict[str, Any] | None = None,
    keychain_account_name: str | None = None,
    oauth_account: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = empty_claude_summary(path, exists=True)
    summary["status"] = "ready"
    summary["hash"] = sha256_json_payload(payload)

    oauth_payload = payload.get("claudeAiOauth") if isinstance(payload.get("claudeAiOauth"), dict) else {}
    access_token = oauth_payload.get("accessToken")
    refresh_token = oauth_payload.get("refreshToken")
    access_expires_at = timestamp_ms_to_iso(oauth_payload.get("expiresAt"))

    summary["auth_mode"] = (
        status_payload.get("authMethod")
        if isinstance(status_payload, dict)
        else None
    ) or ("claude.ai" if oauth_payload else None)
    summary["email"] = (
        status_payload.get("email") if isinstance(status_payload, dict) else None
    ) or (oauth_account.get("emailAddress") if isinstance(oauth_account, dict) else None)
    summary["name"] = oauth_account.get("displayName") if isinstance(oauth_account, dict) else None
    summary["account_id"] = (
        status_payload.get("orgId") if isinstance(status_payload, dict) else None
    ) or (oauth_account.get("organizationUuid") if isinstance(oauth_account, dict) else None)
    summary["org_id"] = summary["account_id"]
    summary["org_name"] = (
        status_payload.get("orgName") if isinstance(status_payload, dict) else None
    ) or (oauth_account.get("organizationName") if isinstance(oauth_account, dict) else None)
    summary["logged_in"] = status_payload.get("loggedIn") if isinstance(status_payload, dict) else None
    summary["api_provider"] = status_payload.get("apiProvider") if isinstance(status_payload, dict) else None
    summary["plan_type"] = oauth_payload.get("subscriptionType") or (
        status_payload.get("subscriptionType") if isinstance(status_payload, dict) else None
    )
    summary["rate_limit_tier"] = oauth_payload.get("rateLimitTier")
    summary["access_expires_at"] = access_expires_at
    summary["expires_at"] = access_expires_at
    summary["has_access_token"] = bool(access_token)
    summary["has_refresh_token"] = bool(refresh_token)
    summary["scopes"] = list(oauth_payload.get("scopes") or [])
    summary["keychain_account_name"] = keychain_account_name
    summary["oauth_account"] = oauth_account if isinstance(oauth_account, dict) else None
    return summary


def claude_oauth_account_from_profile(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    oauth_account = payload.get("oauthAccount")
    return oauth_account if isinstance(oauth_account, dict) else None


def claude_oauth_account_matches(summary: dict[str, Any], oauth_account: dict[str, Any] | None) -> bool:
    if not isinstance(oauth_account, dict):
        return False
    summary_email = str(summary.get("email") or "").strip().lower()
    summary_org_id = str(summary.get("org_id") or summary.get("account_id") or "").strip()
    oauth_email = str(oauth_account.get("emailAddress") or "").strip().lower()
    oauth_org_id = str(oauth_account.get("organizationUuid") or "").strip()

    if summary_email and oauth_email != summary_email:
        return False
    if summary_org_id and oauth_org_id != summary_org_id:
        return False
    return bool(summary_email or summary_org_id)


def claude_identity_key(summary: dict[str, Any]) -> str | None:
    if summary.get("status") != "ready":
        return None
    email = summary.get("email")
    if isinstance(email, str) and email.strip():
        return f"email:{email.strip().lower()}"
    org_id = summary.get("org_id") or summary.get("account_id")
    if isinstance(org_id, str) and org_id.strip():
        return f"org_id:{org_id.strip()}"
    file_hash = summary.get("hash")
    if isinstance(file_hash, str) and file_hash:
        return f"hash:{file_hash}"
    return None


def empty_claude_usage_auth(path: str) -> dict[str, Any]:
    return {
        "path": path,
        "configured": False,
        "has_session_key": False,
        "status": "not_configured",
        "organization_id": None,
        "organization_name": None,
        "updated_at": None,
        "error": None,
        "keychain_service": DEFAULT_CLAUDE_USAGE_SESSION_KEYCHAIN_SERVICE,
        "keychain_account_name": None,
    }


def empty_claude_usage_cache(path: str, *, status: str = "not_configured") -> dict[str, Any]:
    return {
        "path": path,
        "status": status,
        "error": None,
        "last_attempt_at": None,
        "last_success_at": None,
        "five_hour_percent": None,
        "five_hour_reset_at": None,
        "seven_day_percent": None,
        "seven_day_reset_at": None,
        "seven_day_opus_percent": None,
        "seven_day_sonnet_percent": None,
        "stale": status == "stale",
        "organization_id": None,
        "organization_name": None,
    }


def empty_claude_usage_display_preferences(path: str) -> dict[str, Any]:
    return {
        "path": path,
        "selected_account_ids": [],
    }


def empty_claude_statusline_preferences(path: str) -> dict[str, Any]:
    return {
        "path": path,
        "show_directory": True,
        "show_model": True,
        "show_account": True,
        "show_context": True,
        "show_usage": True,
        "show_progress_bar": True,
        "show_pace_marker": True,
        "show_reset_time": True,
        "show_seven_day_usage": False,
        "show_seven_day_progress_bar": True,
        "show_seven_day_pace_marker": True,
        "show_seven_day_reset_time": True,
        "show_seven_day_label": True,
        "show_context_label": True,
        "show_usage_label": True,
        "show_reset_label": True,
        "use_24_hour_time": False,
        "bar_width": 10,
        "separator": " │ ",
        "updated_at": None,
    }


def normalize_claude_statusline_preferences(path: str, stored: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = empty_claude_statusline_preferences(path)
    stored = stored if isinstance(stored, dict) else {}
    bool_fields = (
        "show_directory",
        "show_model",
        "show_account",
        "show_context",
        "show_usage",
        "show_progress_bar",
        "show_pace_marker",
        "show_reset_time",
        "show_seven_day_usage",
        "show_seven_day_progress_bar",
        "show_seven_day_pace_marker",
        "show_seven_day_reset_time",
        "show_seven_day_label",
        "show_context_label",
        "show_usage_label",
        "show_reset_label",
        "use_24_hour_time",
    )
    for field in bool_fields:
        if field in stored:
            payload[field] = bool(stored.get(field))

    try:
        bar_width = int(stored.get("bar_width"))
    except (TypeError, ValueError):
        bar_width = payload["bar_width"]
    payload["bar_width"] = max(6, min(16, bar_width))

    separator = str(stored.get("separator") or "")
    if separator and separator.strip():
        payload["separator"] = separator

    payload["updated_at"] = iso_datetime(stored.get("updated_at"))
    return payload


def compute_pace_marker_ratio(reset_at: Any, *, window_seconds: int = 5 * 60 * 60) -> float | None:
    reset_dt = parse_iso_datetime(reset_at)
    if reset_dt is None:
        return None
    now = datetime.now(timezone.utc)
    start_dt = reset_dt - timedelta(seconds=window_seconds)
    elapsed = (now - start_dt).total_seconds()
    ratio = elapsed / window_seconds
    return max(0.0, min(1.0, ratio))


def build_statusline_bar(
    percent: float | None,
    *,
    width: int,
    marker_ratio: float | None = None,
    fill_char: str = "▓",
    empty_char: str = "░",
    marker_char: str = "┃",
) -> str:
    width = max(1, width)
    if percent is None:
        chars = [empty_char] * width
    else:
        filled = max(0, min(width, int(round((percent / 100.0) * width))))
        chars = [fill_char if index < filled else empty_char for index in range(width)]
    if marker_ratio is not None:
        marker_index = min(width - 1, max(0, int(marker_ratio * width)))
        chars[marker_index] = marker_char
    return "".join(chars)


def format_statusline_reset(
    reset_at: Any,
    *,
    use_24_hour_time: bool,
    include_date: bool = False,
) -> str | None:
    parsed = parse_iso_datetime(reset_at)
    if parsed is None:
        return None
    local_dt = parsed.astimezone()
    time_pattern = "%H:%M" if use_24_hour_time else "%I:%M %p"
    if include_date:
        time_text = local_dt.strftime(time_pattern)
        return f"{local_dt.month}/{local_dt.day} {local_dt.strftime('%a')} {time_text}"
    if use_24_hour_time:
        return local_dt.strftime("%H:%M")
    return local_dt.strftime("%I:%M %p")


def build_claude_statusline_preview(
    preferences: dict[str, Any],
    *,
    account_label: str | None,
    usage: dict[str, Any] | None,
) -> str:
    def usage_segment(
        *,
        percent_value: Any,
        reset_value: Any,
        label_text: str,
        show_label: bool,
        show_progress_bar: bool,
        show_pace_marker: bool,
        show_reset_time: bool,
        window_seconds: int,
        include_date_in_reset: bool = False,
    ) -> str:
        usage_percent = parse_cached_usage_percent(percent_value)
        if usage_percent is None:
            usage_percent = 0.0
        segment = f"{int(usage_percent)}%" if usage_percent.is_integer() else f"{usage_percent:.1f}%"
        if show_label:
            segment = f"{label_text}: {segment}"
        if show_progress_bar:
            marker_ratio = (
                compute_pace_marker_ratio(reset_value, window_seconds=window_seconds)
                if show_pace_marker
                else None
            )
            segment = (
                f"{segment} "
                f"{build_statusline_bar(usage_percent, width=int(preferences.get('bar_width') or 10), marker_ratio=marker_ratio)}"
            )
        if show_reset_time:
            reset_text = format_statusline_reset(
                reset_value,
                use_24_hour_time=bool(preferences.get("use_24_hour_time")),
                include_date=include_date_in_reset,
            ) or (
                "4/2 Wed 15:00"
                if include_date_in_reset and preferences.get("use_24_hour_time")
                else "4/2 Wed 03:00 PM"
                if include_date_in_reset
                else "15:00"
                if preferences.get("use_24_hour_time")
                else "03:00 PM"
            )
            reset_label = "Reset: " if preferences.get("show_reset_label") else ""
            segment = f"{segment} → {reset_label}{reset_text}"
        return segment

    parts: list[str] = []
    separator = str(preferences.get("separator") or " │ ")
    if preferences.get("show_directory"):
        parts.append("agent-account-hub")
    if preferences.get("show_model"):
        parts.append("Opus 4.6")
    if preferences.get("show_account"):
        parts.append(account_label or "当前账号")
    if preferences.get("show_context"):
        context_text = "0%"
        if preferences.get("show_context_label"):
            context_text = f"Ctx: {context_text}"
        parts.append(context_text)
    if preferences.get("show_usage"):
        parts.append(
            usage_segment(
                percent_value=(usage or {}).get("five_hour_percent"),
                reset_value=(usage or {}).get("five_hour_reset_at"),
                label_text="Usage",
                show_label=bool(preferences.get("show_usage_label")),
                show_progress_bar=bool(preferences.get("show_progress_bar")),
                show_pace_marker=bool(preferences.get("show_pace_marker")),
                show_reset_time=bool(preferences.get("show_reset_time")),
                window_seconds=5 * 60 * 60,
                include_date_in_reset=False,
            )
        )
    if preferences.get("show_seven_day_usage"):
        parts.append(
            usage_segment(
                percent_value=(usage or {}).get("seven_day_percent"),
                reset_value=(usage or {}).get("seven_day_reset_at"),
                label_text="7d",
                show_label=bool(preferences.get("show_seven_day_label")),
                show_progress_bar=bool(preferences.get("show_seven_day_progress_bar")),
                show_pace_marker=bool(preferences.get("show_seven_day_pace_marker")),
                show_reset_time=bool(preferences.get("show_seven_day_reset_time")),
                window_seconds=7 * 24 * 60 * 60,
                include_date_in_reset=True,
            )
        )
    return separator.join(part for part in parts if part)


def build_claude_statusline_wrapper_script(script_path: Path) -> str:
    return f"""#!/bin/bash
exec /usr/bin/env perl "{script_path}" "$@"
"""


def build_claude_statusline_perl_script(config_path: Path, runtime_path: Path) -> str:
    config_literal = json.dumps(str(config_path))
    runtime_literal = json.dumps(str(runtime_path))
    return f"""#!/usr/bin/env perl
use strict;
use warnings;
use utf8;
use JSON::PP qw(decode_json);
use POSIX qw(strftime);
use File::Basename qw(basename);

my $config_path = {config_literal};
my $runtime_path = {runtime_literal};
binmode(STDIN, ':raw');
binmode(STDOUT, ':encoding(UTF-8)');

sub load_json_file {{
  my ($path) = @_;
  return {{}} unless defined $path && -f $path;
  open my $fh, '<:raw', $path or return {{}};
  local $/;
  my $raw = <$fh>;
  close $fh;
  return {{}} unless defined $raw && $raw =~ /\\S/;
  my $decoded = eval {{ decode_json($raw) }};
  return {{}} unless ref($decoded) eq 'HASH';
  return $decoded;
}}

sub nested_hash {{
  my ($value, $key) = @_;
  return {{}} unless ref($value) eq 'HASH';
  my $child = $value->{{$key}};
  return ref($child) eq 'HASH' ? $child : {{}};
}}

sub parse_percent {{
  my ($value) = @_;
  return undef unless defined $value;
  return undef if ref($value);
  return undef unless $value =~ /^-?\\d+(?:\\.\\d+)?$/;
  my $number = $value + 0;
  $number = 0 if $number < 0;
  $number = 100 if $number > 100;
  return sprintf('%.1f', $number) + 0;
}}

sub format_percent {{
  my ($value) = @_;
  return '~' unless defined $value;
  return sprintf('%.0f%%', $value) if int($value) == $value;
  return sprintf('%.1f%%', $value);
}}

sub parse_context_percent {{
  my ($stdin) = @_;
  my $context = nested_hash($stdin, 'context_window');
  my $native = $context->{{used_percentage}};
  my $native_percent = parse_percent($native);
  return $native_percent if defined $native_percent;
  my $size = $context->{{context_window_size}} || 0;
  return 0 if !$size;
  my $usage = nested_hash($context, 'current_usage');
  my $total = ($usage->{{input_tokens}} || 0)
    + ($usage->{{cache_creation_input_tokens}} || 0)
    + ($usage->{{cache_read_input_tokens}} || 0);
  my $percent = ($total / $size) * 100;
  return parse_percent($percent);
}}

sub build_bar {{
  my ($percent, $width, $marker_ratio) = @_;
  $width = 10 unless defined $width && $width =~ /^\\d+$/;
  $width = 6 if $width < 6;
  $width = 16 if $width > 16;
  my @chars = ('░') x $width;
  if (defined $percent) {{
    my $filled = int((($percent / 100) * $width) + 0.5);
    $filled = 0 if $filled < 0;
    $filled = $width if $filled > $width;
    for (my $i = 0; $i < $filled; $i++) {{
      $chars[$i] = '▓';
    }}
  }}
  if (defined $marker_ratio) {{
    my $index = int($marker_ratio * $width);
    $index = 0 if $index < 0;
    $index = $width - 1 if $index >= $width;
    $chars[$index] = '┃';
  }}
  return join('', @chars);
}}

sub pace_ratio {{
  my ($reset_epoch, $window_seconds) = @_;
  return undef unless defined $reset_epoch && $reset_epoch =~ /^\\d+$/;
  $window_seconds = 18000 unless defined $window_seconds && $window_seconds =~ /^\\d+$/ && $window_seconds > 0;
  my $start_epoch = $reset_epoch - $window_seconds;
  my $ratio = (time() - $start_epoch) / $window_seconds;
  $ratio = 0 if $ratio < 0;
  $ratio = 1 if $ratio > 1;
  return $ratio;
}}

sub format_reset_time {{
  my ($epoch, $use_24_hour, $include_date) = @_;
  return undef unless defined $epoch && $epoch =~ /^\\d+$/;
  if ($include_date) {{
    my @local = localtime($epoch);
    my $month = $local[4] + 1;
    my $day = $local[3];
    my $weekday = strftime('%a', @local);
    my $time = $use_24_hour
      ? strftime('%H:%M', @local)
      : strftime('%I:%M %p', @local);
    return "$month/$day $weekday $time";
  }}
  return $use_24_hour ? strftime('%H:%M', localtime($epoch)) : strftime('%I:%M %p', localtime($epoch));
}}

sub color_for_percent {{
  my ($percent) = @_;
  return \"\\e[38;5;244m\" unless defined $percent;
  return \"\\e[38;5;196m\" if $percent >= 80;
  return \"\\e[38;5;214m\" if $percent >= 60;
  return \"\\e[38;5;42m\";
}}

sub maybe_color {{
  my ($text, $ansi) = @_;
  return $text unless defined $text && length($text);
  return $text unless defined $ansi && length($ansi);
  return $ansi . $text . \"\\e[0m\";
}}

my $defaults = {{
  show_directory => JSON::PP::true,
  show_model => JSON::PP::true,
  show_account => JSON::PP::true,
  show_context => JSON::PP::true,
  show_usage => JSON::PP::true,
  show_progress_bar => JSON::PP::true,
  show_pace_marker => JSON::PP::true,
  show_reset_time => JSON::PP::true,
  show_seven_day_usage => JSON::PP::false,
  show_seven_day_progress_bar => JSON::PP::true,
  show_seven_day_pace_marker => JSON::PP::true,
  show_seven_day_reset_time => JSON::PP::true,
  show_seven_day_label => JSON::PP::true,
  show_context_label => JSON::PP::true,
  show_usage_label => JSON::PP::true,
  show_reset_label => JSON::PP::true,
  use_24_hour_time => JSON::PP::false,
  bar_width => 10,
  separator => ' │ ',
}};
my $config = load_json_file($config_path);
for my $key (keys %$defaults) {{
  $config->{{$key}} = $defaults->{{$key}} unless exists $config->{{$key}};
}}

my $runtime = load_json_file($runtime_path);

my $raw = do {{
  local $/;
  <STDIN>;
}};
my $stdin = {{}};
if (defined $raw && $raw =~ /\\S/) {{
  my $decoded = eval {{ decode_json($raw) }};
  $stdin = $decoded if ref($decoded) eq 'HASH';
}}

my $workspace = nested_hash($stdin, 'workspace');
my $cwd = $workspace->{{current_dir}} || $stdin->{{cwd}} || '';
my $dir = $cwd ? basename($cwd) : undef;
my $model = nested_hash($stdin, 'model')->{{display_name}} || nested_hash($stdin, 'model')->{{id}} || 'Claude';
my $context_percent = parse_context_percent($stdin);

my $rate_limits = nested_hash($stdin, 'rate_limits');
my $five_hour = nested_hash($rate_limits, 'five_hour');
my $seven_day = nested_hash($rate_limits, 'seven_day');
my $runtime_usage = nested_hash($runtime, 'usage');
my $usage_percent = parse_percent($five_hour->{{used_percentage}});
$usage_percent = parse_percent($runtime_usage->{{five_hour_percent}}) unless defined $usage_percent;
my $reset_epoch = $five_hour->{{resets_at}};
$reset_epoch = $runtime_usage->{{five_hour_reset_epoch}} unless defined $reset_epoch;
my $seven_day_percent = parse_percent($seven_day->{{used_percentage}});
$seven_day_percent = parse_percent($runtime_usage->{{seven_day_percent}}) unless defined $seven_day_percent;
my $seven_day_reset_epoch = $seven_day->{{resets_at}};
$seven_day_reset_epoch = $runtime_usage->{{seven_day_reset_epoch}} unless defined $seven_day_reset_epoch;

my @parts = ();
my $separator = $config->{{separator}} || ' │ ';

if ($config->{{show_directory}} && defined $dir && length($dir)) {{
  push @parts, maybe_color($dir, \"\\e[38;5;244m\");
}}
if ($config->{{show_model}} && defined $model && length($model)) {{
  push @parts, maybe_color($model, \"\\e[38;5;45m\");
}}
my $account_label = $runtime->{{current_account_label}} || $runtime->{{current_email}} || undef;
if ($config->{{show_account}} && defined $account_label && length($account_label)) {{
  push @parts, maybe_color($account_label, \"\\e[38;5;215m\");
}}
if ($config->{{show_context}}) {{
  my $ctx_text = format_percent($context_percent);
  $ctx_text = 'Ctx: ' . $ctx_text if $config->{{show_context_label}};
  push @parts, maybe_color($ctx_text, color_for_percent($context_percent));
}}
if ($config->{{show_usage}}) {{
  my $usage_text = format_percent($usage_percent);
  $usage_text = 'Usage: ' . $usage_text if $config->{{show_usage_label}};
  if ($config->{{show_progress_bar}}) {{
    my $marker_ratio = $config->{{show_pace_marker}} ? pace_ratio($reset_epoch, 18000) : undef;
    $usage_text .= ' ' . build_bar($usage_percent, $config->{{bar_width}}, $marker_ratio);
  }}
  if ($config->{{show_reset_time}}) {{
    my $reset_text = format_reset_time($reset_epoch, $config->{{use_24_hour_time}}, 0);
    if (defined $reset_text) {{
      my $label = $config->{{show_reset_label}} ? 'Reset: ' : '';
      $usage_text .= ' → ' . $label . $reset_text;
    }}
  }}
  push @parts, maybe_color($usage_text, color_for_percent($usage_percent));
}}
if ($config->{{show_seven_day_usage}}) {{
  my $seven_day_text = format_percent($seven_day_percent);
  $seven_day_text = '7d: ' . $seven_day_text if $config->{{show_seven_day_label}};
  if ($config->{{show_seven_day_progress_bar}}) {{
    my $marker_ratio = $config->{{show_seven_day_pace_marker}} ? pace_ratio($seven_day_reset_epoch, 604800) : undef;
    $seven_day_text .= ' ' . build_bar($seven_day_percent, $config->{{bar_width}}, $marker_ratio);
  }}
  if ($config->{{show_seven_day_reset_time}}) {{
    my $reset_text = format_reset_time($seven_day_reset_epoch, $config->{{use_24_hour_time}}, 1);
    if (defined $reset_text) {{
      my $label = $config->{{show_reset_label}} ? 'Reset: ' : '';
      $seven_day_text .= ' → ' . $label . $reset_text;
    }}
  }}
  push @parts, maybe_color($seven_day_text, color_for_percent($seven_day_percent));
}}

print join($separator, grep {{ defined($_) && length($_) }} @parts), \"\\n\";
"""


def parse_claude_usage_percent(value: Any) -> float | None:
    numeric: float
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if isinstance(value, float) and 0.0 <= numeric <= 1.0:
            numeric *= 100.0
    elif isinstance(value, str):
        cleaned = value.strip().replace("%", "")
        if not cleaned:
            return None
        try:
            numeric = float(cleaned)
        except ValueError:
            return None
        if 0.0 <= numeric <= 1.0 and "." in cleaned:
            numeric *= 100.0
    else:
        return None
    return max(0.0, min(100.0, round(numeric, 1)))


def parse_cached_usage_percent(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, round(numeric, 1)))


def normalize_usage_display_preferences(path: str, raw_ids: list[Any] | None) -> dict[str, Any]:
    payload = {
        "path": path,
        "selected_account_ids": [],
    }
    seen: set[str] = set()
    for value in raw_ids or []:
        account_id = str(value or "").strip()
        if not account_id or account_id in seen:
            continue
        seen.add(account_id)
        payload["selected_account_ids"].append(account_id)
    return payload


def empty_codex_usage_auth(path: str) -> dict[str, Any]:
    return {
        "path": path,
        "configured": False,
        "status": "auth_missing",
        "mode": "saved_access_token",
        "has_access_token": False,
        "updated_at": None,
        "error": None,
    }


def empty_codex_usage_cache(path: str, *, status: str = "not_configured") -> dict[str, Any]:
    return {
        "path": path,
        "status": status,
        "error": None,
        "last_attempt_at": None,
        "last_success_at": None,
        "next_refresh_at": None,
        "five_hour_percent": None,
        "five_hour_reset_at": None,
        "seven_day_percent": None,
        "seven_day_reset_at": None,
        "code_review_seven_day_percent": None,
        "code_review_seven_day_reset_at": None,
        "allowed": None,
        "limit_reached": None,
        "plan_type": None,
        "email": None,
        "credits_balance": None,
        "credits_unlimited": None,
        "stale": status == "stale",
    }


class CodexUsageFetchError(AuthHubError):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class CodexUsageClient:
    def fetch_usage(self, access_token: str) -> dict[str, Any]:
        raise NotImplementedError


class ChatGPTWhamUsageClient(CodexUsageClient):
    def __init__(self, url: str = CODEX_USAGE_API_URL, timeout_seconds: float = 20.0) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds

    def fetch_usage(self, access_token: str) -> dict[str, Any]:
        request = Request(
            self.url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "User-Agent": "Agent Account Hub",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise CodexUsageFetchError("unauthorized", "Codex access token 已失效，需要重新登录并更新保存账号") from exc
            if exc.code == 429:
                raise CodexUsageFetchError("rate_limited", "Codex 用量接口暂时限制请求频率，稍后再试") from exc
            raise CodexUsageFetchError("error", f"Codex usage 请求失败：HTTP {exc.code}") from exc
        except URLError as exc:
            raise CodexUsageFetchError("error", f"无法连接 ChatGPT 用量接口：{exc.reason}") from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CodexUsageFetchError("invalid_response", "Codex usage 返回了无法解析的数据") from exc
        if not isinstance(payload, dict):
            raise CodexUsageFetchError("invalid_response", "Codex usage 返回的数据格式不正确")

        rate_limit = payload.get("rate_limit") if isinstance(payload.get("rate_limit"), dict) else {}
        primary_window = rate_limit.get("primary_window") if isinstance(rate_limit.get("primary_window"), dict) else {}
        secondary_window = (
            rate_limit.get("secondary_window") if isinstance(rate_limit.get("secondary_window"), dict) else {}
        )
        review_limit = (
            payload.get("code_review_rate_limit")
            if isinstance(payload.get("code_review_rate_limit"), dict)
            else {}
        )
        review_primary = (
            review_limit.get("primary_window") if isinstance(review_limit.get("primary_window"), dict) else {}
        )

        normalized = {
            "five_hour_percent": parse_claude_usage_percent(primary_window.get("used_percent")),
            "five_hour_reset_at": timestamp_to_iso(primary_window.get("reset_at")),
            "seven_day_percent": parse_claude_usage_percent(secondary_window.get("used_percent")),
            "seven_day_reset_at": timestamp_to_iso(secondary_window.get("reset_at")),
            "code_review_seven_day_percent": parse_claude_usage_percent(review_primary.get("used_percent")),
            "code_review_seven_day_reset_at": timestamp_to_iso(review_primary.get("reset_at")),
            "allowed": rate_limit.get("allowed"),
            "limit_reached": rate_limit.get("limit_reached"),
            "plan_type": str(payload.get("plan_type") or "").strip() or None,
            "email": str(payload.get("email") or "").strip() or None,
            "credits_balance": str((payload.get("credits") or {}).get("balance") or "").strip() or None,
            "credits_unlimited": bool((payload.get("credits") or {}).get("unlimited")),
        }
        if not any(
            normalized.get(key) is not None
            for key in ("five_hour_percent", "seven_day_percent", "code_review_seven_day_percent")
        ):
            raise CodexUsageFetchError("invalid_response", "Codex usage 响应里没有可识别的用量字段")
        return normalized


class CodexUsageHub(AuthHub):
    def __init__(
        self,
        paths: Any | None = None,
        usage_client: CodexUsageClient | None = None,
    ) -> None:
        super().__init__(paths=paths)
        self.usage_client = usage_client or ChatGPTWhamUsageClient()

    def usage_cache_path(self, account_id: str) -> Path:
        return self.paths.accounts_root / account_id / "usage_cache.json"

    def usage_display_preferences_path(self) -> Path:
        return self.paths.data_root / "usage_display.json"

    def load_usage_display_preferences(self) -> dict[str, Any]:
        path = self.usage_display_preferences_path()
        if not path.is_file():
            return normalize_usage_display_preferences(str(path), [])
        try:
            stored = load_json_file(path)
        except (OSError, json.JSONDecodeError, AuthHubError):
            return normalize_usage_display_preferences(str(path), [])
        return normalize_usage_display_preferences(str(path), stored.get("selected_account_ids"))

    def save_usage_display_preferences(self, payload: dict[str, Any]) -> None:
        normalized = normalize_usage_display_preferences(
            str(self.usage_display_preferences_path()),
            payload.get("selected_account_ids"),
        )
        atomic_write_json(self.usage_display_preferences_path(), normalized)

    def saved_usage_auth(self, account_id: str) -> dict[str, Any]:
        auth_path = self.account_auth_path(account_id)
        payload = empty_codex_usage_auth(str(auth_path))
        summary = build_auth_summary(auth_path)
        payload["has_access_token"] = bool(summary.get("has_access_token"))
        payload["configured"] = bool(summary.get("has_access_token"))
        payload["status"] = "ready" if payload["configured"] else "auth_missing"
        payload["updated_at"] = summary.get("last_refresh")
        if not payload["configured"]:
            payload["error"] = "当前保存快照缺少可用于查询用量的 access token"
        return payload

    def saved_usage_cache(self, account_id: str) -> dict[str, Any]:
        cache_path = self.usage_cache_path(account_id)
        payload = empty_codex_usage_cache(str(cache_path))
        auth = self.saved_usage_auth(account_id)
        if not cache_path.is_file():
            if auth.get("status") == "auth_missing":
                payload["status"] = "auth_missing"
                payload["error"] = auth.get("error")
            return payload

        try:
            stored = load_json_file(cache_path)
        except (OSError, json.JSONDecodeError, AuthHubError) as exc:
            payload["status"] = "error"
            payload["error"] = str(exc)
            return payload

        payload["status"] = str(stored.get("status") or payload["status"])
        payload["error"] = str(stored.get("error") or "").strip() or None
        payload["last_attempt_at"] = iso_datetime(stored.get("last_attempt_at"))
        payload["last_success_at"] = iso_datetime(stored.get("last_success_at"))
        payload["next_refresh_at"] = iso_datetime(stored.get("next_refresh_at"))
        payload["five_hour_percent"] = parse_cached_usage_percent(stored.get("five_hour_percent"))
        payload["five_hour_reset_at"] = iso_datetime(stored.get("five_hour_reset_at"))
        payload["seven_day_percent"] = parse_cached_usage_percent(stored.get("seven_day_percent"))
        payload["seven_day_reset_at"] = iso_datetime(stored.get("seven_day_reset_at"))
        payload["code_review_seven_day_percent"] = parse_cached_usage_percent(
            stored.get("code_review_seven_day_percent")
        )
        payload["code_review_seven_day_reset_at"] = iso_datetime(stored.get("code_review_seven_day_reset_at"))
        payload["allowed"] = stored.get("allowed")
        payload["limit_reached"] = stored.get("limit_reached")
        payload["plan_type"] = str(stored.get("plan_type") or "").strip() or None
        payload["email"] = str(stored.get("email") or "").strip() or None
        payload["credits_balance"] = str(stored.get("credits_balance") or "").strip() or None
        payload["credits_unlimited"] = bool(stored.get("credits_unlimited"))

        last_success = parse_iso_datetime(payload.get("last_success_at"))
        payload["stale"] = False
        if payload["status"] in {"ok", "stale"} and last_success is not None:
            age_seconds = (datetime.now(timezone.utc) - last_success).total_seconds()
            if age_seconds >= CODEX_USAGE_STALE_SECONDS:
                payload["status"] = "stale"
                payload["stale"] = True
        elif payload["status"] == "stale":
            payload["stale"] = True

        if auth.get("status") == "auth_missing":
            payload["status"] = "auth_missing"
            payload["error"] = auth.get("error")
        return payload

    def _write_usage_cache(self, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        atomic_write_json(self.usage_cache_path(account_id), payload)
        return self.saved_usage_cache(account_id)

    def _clear_usage_cache_file(self, account_id: str) -> None:
        cache_path = self.usage_cache_path(account_id)
        if cache_path.exists():
            cache_path.unlink()

    def usage_menu_bar_eligible(
        self,
        account_id: str,
        *,
        usage_auth: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
    ) -> bool:
        auth = usage_auth or self.saved_usage_auth(account_id)
        cache = usage or self.saved_usage_cache(account_id)
        if not auth.get("configured"):
            return False
        if str(cache.get("status") or "") not in {"ok", "stale"}:
            return False
        return any(cache.get(key) is not None for key in ("five_hour_percent", "seven_day_percent"))

    def usage_menu_bar_selected_account_ids(self) -> list[str]:
        preferences = self.load_usage_display_preferences()
        normalized_ids: list[str] = []
        changed = False
        for account_id in preferences["selected_account_ids"]:
            try:
                self.get_account(account_id)
            except AuthHubError:
                changed = True
                continue
            usage_auth = self.saved_usage_auth(account_id)
            usage = self.saved_usage_cache(account_id)
            if not self.usage_menu_bar_eligible(account_id, usage_auth=usage_auth, usage=usage):
                changed = True
                continue
            normalized_ids.append(account_id)
        if changed or normalized_ids != preferences["selected_account_ids"]:
            self.save_usage_display_preferences({"selected_account_ids": normalized_ids})
        return normalized_ids

    def usage_menu_bar_accounts(self) -> list[dict[str, Any]]:
        return [self.account_overview(account_id) for account_id in self.usage_menu_bar_selected_account_ids()]

    def _set_usage_menu_bar_selection(self, selected_ids: list[str]) -> None:
        self.save_usage_display_preferences({"selected_account_ids": selected_ids})

    def remove_usage_menu_bar_account(self, account_id: str) -> None:
        preferences = self.load_usage_display_preferences()
        selected_ids = [value for value in preferences["selected_account_ids"] if value != account_id]
        if selected_ids != preferences["selected_account_ids"]:
            self._set_usage_menu_bar_selection(selected_ids)

    def set_usage_menu_bar_visible(self, account_id: str, visible: bool) -> dict[str, Any]:
        self.get_account(account_id)
        preferences = self.load_usage_display_preferences()
        selected_ids = list(preferences["selected_account_ids"])
        if visible:
            account = self.account_overview(account_id)
            if not account.get("usage_menu_bar_eligible"):
                raise AuthHubError("只有已成功获取到 Codex 用量的账号才能显示到菜单栏")
            if account_id not in selected_ids:
                selected_ids.append(account_id)
        else:
            selected_ids = [value for value in selected_ids if value != account_id]
        self._set_usage_menu_bar_selection(selected_ids)
        return self.account_overview(account_id)

    def _future_iso(self, seconds: int) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat()

    def refresh_usage(self, account_id: str) -> dict[str, Any]:
        self.get_account(account_id)
        now = utc_now_iso()
        auth = self.saved_usage_auth(account_id)
        previous_cache = self.saved_usage_cache(account_id)

        if not auth.get("configured"):
            self._write_usage_cache(
                account_id,
                {
                    **empty_codex_usage_cache(str(self.usage_cache_path(account_id))),
                    "status": "auth_missing",
                    "error": auth.get("error"),
                    "last_attempt_at": now,
                    "last_success_at": previous_cache.get("last_success_at"),
                    "next_refresh_at": self._future_iso(CODEX_USAGE_UNAUTHORIZED_BACKOFF_SECONDS),
                    "five_hour_percent": previous_cache.get("five_hour_percent"),
                    "five_hour_reset_at": previous_cache.get("five_hour_reset_at"),
                    "seven_day_percent": previous_cache.get("seven_day_percent"),
                    "seven_day_reset_at": previous_cache.get("seven_day_reset_at"),
                    "code_review_seven_day_percent": previous_cache.get("code_review_seven_day_percent"),
                    "code_review_seven_day_reset_at": previous_cache.get("code_review_seven_day_reset_at"),
                    "allowed": previous_cache.get("allowed"),
                    "limit_reached": previous_cache.get("limit_reached"),
                    "plan_type": previous_cache.get("plan_type"),
                    "email": previous_cache.get("email"),
                    "credits_balance": previous_cache.get("credits_balance"),
                    "credits_unlimited": previous_cache.get("credits_unlimited"),
                    "stale": bool(previous_cache.get("last_success_at")),
                },
            )
            return self.account_overview(account_id)

        next_refresh = parse_iso_datetime(previous_cache.get("next_refresh_at"))
        if next_refresh is not None and next_refresh > datetime.now(timezone.utc):
            return self.account_overview(account_id)

        auth_payload = load_json_file(self.account_auth_path(account_id))
        access_token = str(((auth_payload.get("tokens") or {}).get("access_token")) or "").strip()
        if not access_token:
            self._write_usage_cache(
                account_id,
                {
                    **empty_codex_usage_cache(str(self.usage_cache_path(account_id))),
                    "status": "auth_missing",
                    "error": "当前保存快照缺少 access token",
                    "last_attempt_at": now,
                    "last_success_at": previous_cache.get("last_success_at"),
                    "next_refresh_at": self._future_iso(CODEX_USAGE_UNAUTHORIZED_BACKOFF_SECONDS),
                    "five_hour_percent": previous_cache.get("five_hour_percent"),
                    "five_hour_reset_at": previous_cache.get("five_hour_reset_at"),
                    "seven_day_percent": previous_cache.get("seven_day_percent"),
                    "seven_day_reset_at": previous_cache.get("seven_day_reset_at"),
                    "code_review_seven_day_percent": previous_cache.get("code_review_seven_day_percent"),
                    "code_review_seven_day_reset_at": previous_cache.get("code_review_seven_day_reset_at"),
                    "allowed": previous_cache.get("allowed"),
                    "limit_reached": previous_cache.get("limit_reached"),
                    "plan_type": previous_cache.get("plan_type"),
                    "email": previous_cache.get("email"),
                    "credits_balance": previous_cache.get("credits_balance"),
                    "credits_unlimited": previous_cache.get("credits_unlimited"),
                    "stale": bool(previous_cache.get("last_success_at")),
                },
            )
            return self.account_overview(account_id)

        try:
            usage = self.usage_client.fetch_usage(access_token)
        except CodexUsageFetchError as exc:
            has_prior_data = any(
                previous_cache.get(key) is not None
                for key in ("five_hour_percent", "seven_day_percent", "code_review_seven_day_percent")
            )
            backoff_seconds = {
                "unauthorized": CODEX_USAGE_UNAUTHORIZED_BACKOFF_SECONDS,
                "rate_limited": CODEX_USAGE_RATE_LIMIT_BACKOFF_SECONDS,
            }.get(exc.kind, CODEX_USAGE_ERROR_BACKOFF_SECONDS)
            status = exc.kind
            if status not in {"unauthorized", "rate_limited", "invalid_response"} and has_prior_data:
                status = "stale"
            if status == "invalid_response":
                status = "error"
            self._write_usage_cache(
                account_id,
                {
                    **previous_cache,
                    "path": str(self.usage_cache_path(account_id)),
                    "status": status,
                    "error": str(exc),
                    "last_attempt_at": now,
                    "next_refresh_at": self._future_iso(backoff_seconds),
                    "stale": status == "stale",
                },
            )
            if status in {"unauthorized", "rate_limited", "error"}:
                self.remove_usage_menu_bar_account(account_id)
            return self.account_overview(account_id)

        self._write_usage_cache(
            account_id,
            {
                **empty_codex_usage_cache(str(self.usage_cache_path(account_id)), status="ok"),
                **usage,
                "status": "ok",
                "error": None,
                "last_attempt_at": now,
                "last_success_at": now,
                "next_refresh_at": self._future_iso(CODEX_USAGE_MIN_REFRESH_SECONDS),
                "stale": False,
            },
        )
        return self.account_overview(account_id)

    def refresh_all_usage(self) -> dict[str, Any]:
        for account in self.load_state()["accounts"]:
            account_id = str(account["id"])
            auth = self.saved_usage_auth(account_id)
            if auth.get("configured"):
                self.refresh_usage(account_id)
        return self.overview()

    def current_overview(self, sync_result: dict[str, Any] | None = None) -> dict[str, Any]:
        current = super().current_overview(sync_result=sync_result)
        matched_account_id = current.get("matched_account_id")
        current["usage_auth"] = self.saved_usage_auth(matched_account_id) if matched_account_id else empty_codex_usage_auth("")
        current["usage"] = self.saved_usage_cache(matched_account_id) if matched_account_id else empty_codex_usage_cache("")
        return current

    def account_overview(self, account_id: str) -> dict[str, Any]:
        account = dict(self.get_account(account_id))
        snapshot = build_auth_summary(self.account_auth_path(account_id))
        usage_auth = self.saved_usage_auth(account_id)
        usage = self.saved_usage_cache(account_id)
        usage_menu_bar_selected_ids = set(self.usage_menu_bar_selected_account_ids())
        current_account_id = self.current_account_id()
        account["snapshot"] = snapshot
        account["usage_auth"] = usage_auth
        account["usage"] = usage
        account["usage_menu_bar_eligible"] = self.usage_menu_bar_eligible(
            account_id,
            usage_auth=usage_auth,
            usage=usage,
        )
        account["usage_menu_bar_visible"] = account_id in usage_menu_bar_selected_ids
        account["active"] = account_id == current_account_id
        return account

    def overview(self) -> dict[str, Any]:
        sync_result = self.sync_current_account_snapshot()
        accounts = [self.account_overview(str(account["id"])) for account in self.load_state()["accounts"]]
        return {
            "active_auth_path": str(self.paths.active_auth_path),
            "current": self.current_overview(sync_result=sync_result),
            "accounts": accounts,
            "slots": list(accounts),
            "usage_menu_bar_accounts": self.usage_menu_bar_accounts(),
            "project_root": str(PROJECT_ROOT),
            "data_root": str(self.paths.data_root),
        }

    def delete_account(self, account_id: str) -> dict[str, Any]:
        account = dict(self.get_account(account_id))
        self._clear_usage_cache_file(account_id)
        self.remove_usage_menu_bar_account(account_id)
        result = super().delete_account(account_id)
        parent = self.account_auth_path(account_id).parent
        if parent.exists():
            shutil.rmtree(parent, ignore_errors=True)
        return {"id": account_id, "label": account.get("label") or account_id, "deleted": True, **result}

    def _clear_duplicate_accounts(self, target_account_id: str) -> list[str]:
        target_summary = build_auth_summary(self.account_auth_path(target_account_id))
        target_identity = auth_identity_key(target_summary)
        if not target_identity:
            return []

        target_cache_path = self.usage_cache_path(target_account_id)
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

            other_cache_path = self.usage_cache_path(account_id)
            if not target_cache_path.is_file() and other_cache_path.is_file():
                ensure_parent(target_cache_path)
                shutil.copy2(other_cache_path, target_cache_path)

            if other_path.exists():
                other_path.unlink()
            if other_cache_path.exists():
                other_cache_path.unlink()
            parent = other_path.parent
            if parent.exists():
                shutil.rmtree(parent, ignore_errors=True)
            self.remove_usage_menu_bar_account(account_id)
            cleared_account_ids.append(account_id)

        if cleared_account_ids:
            state["accounts"] = remaining_accounts
            self.save_state(state)

        return cleared_account_ids


class ClaudeUsageFetchError(AuthHubError):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class ClaudeUsageSessionStore:
    service_name = DEFAULT_CLAUDE_USAGE_SESSION_KEYCHAIN_SERVICE

    def account_name(self, account_id: str) -> str:
        return f"{CLAUDE_CODE_PROVIDER_ID}:{account_id}"

    def read(self, account_id: str) -> str:
        raise NotImplementedError

    def read_optional(self, account_id: str) -> str | None:
        raise NotImplementedError

    def write(self, account_id: str, session_key: str) -> None:
        raise NotImplementedError

    def delete(self, account_id: str) -> None:
        raise NotImplementedError


class KeychainClaudeUsageSessionStore(ClaudeUsageSessionStore):
    def __init__(self, service_name: str = DEFAULT_CLAUDE_USAGE_SESSION_KEYCHAIN_SERVICE) -> None:
        self.service_name = service_name

    def read_optional(self, account_id: str) -> str | None:
        account_name = self.account_name(account_id)
        result = run_subprocess(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-w",
                "-s",
                self.service_name,
                "-a",
                account_name,
            ]
        )
        if result.returncode != 0:
            return None
        secret = (result.stdout or "").strip()
        return secret or None

    def read(self, account_id: str) -> str:
        session_key = self.read_optional(account_id)
        if session_key:
            return session_key
        raise AuthHubError("未找到这个账号对应的 claude.ai sessionKey")

    def write(self, account_id: str, session_key: str) -> None:
        account_name = self.account_name(account_id)
        result = run_subprocess(
            [
                "/usr/bin/security",
                "add-generic-password",
                "-U",
                "-s",
                self.service_name,
                "-a",
                account_name,
                "-w",
                session_key,
            ]
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise AuthHubError(message or "写入 claude.ai sessionKey 到 Keychain 失败")

    def delete(self, account_id: str) -> None:
        account_name = self.account_name(account_id)
        result = run_subprocess(
            [
                "/usr/bin/security",
                "delete-generic-password",
                "-s",
                self.service_name,
                "-a",
                account_name,
            ]
        )
        if result.returncode not in {0, 44}:
            message = (result.stderr or result.stdout or "").strip()
            raise AuthHubError(message or "删除 claude.ai sessionKey 失败")


class ClaudeUsageClient:
    def fetch_usage(self, session_key: str, organization_id: str) -> dict[str, Any]:
        raise NotImplementedError


class ClaudeAiWebUsageClient(ClaudeUsageClient):
    def __init__(self, base_url: str = CLAUDE_AI_API_BASE_URL, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def fetch_usage(self, session_key: str, organization_id: str) -> dict[str, Any]:
        url = f"{self.base_url}/organizations/{quote(organization_id, safe='')}/usage"
        request = Request(
            url,
            headers={
                "Cookie": f"sessionKey={session_key}",
                "Accept": "application/json",
                "User-Agent": "Agent Account Hub",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise ClaudeUsageFetchError("unauthorized", "claude.ai session 已失效，或当前 organization 无权限访问") from exc
            if exc.code == 404:
                raise ClaudeUsageFetchError("error", "organizationId 无效，或当前 session 无法访问这个组织") from exc
            raise ClaudeUsageFetchError("error", f"claude.ai usage 请求失败：HTTP {exc.code}") from exc
        except URLError as exc:
            raise ClaudeUsageFetchError("error", f"无法连接 claude.ai：{exc.reason}") from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ClaudeUsageFetchError("invalid_response", "claude.ai usage 返回了无法解析的数据") from exc
        if not isinstance(payload, dict):
            raise ClaudeUsageFetchError("invalid_response", "claude.ai usage 返回的数据格式不正确")

        five_hour = payload.get("five_hour") if isinstance(payload.get("five_hour"), dict) else {}
        seven_day = payload.get("seven_day") if isinstance(payload.get("seven_day"), dict) else {}
        seven_day_opus = payload.get("seven_day_opus") if isinstance(payload.get("seven_day_opus"), dict) else {}
        seven_day_sonnet = (
            payload.get("seven_day_sonnet") if isinstance(payload.get("seven_day_sonnet"), dict) else {}
        )

        normalized = {
            "five_hour_percent": parse_claude_usage_percent(five_hour.get("utilization")),
            "five_hour_reset_at": iso_datetime(five_hour.get("resets_at")),
            "seven_day_percent": parse_claude_usage_percent(seven_day.get("utilization")),
            "seven_day_reset_at": iso_datetime(seven_day.get("resets_at")),
            "seven_day_opus_percent": parse_claude_usage_percent(seven_day_opus.get("utilization")),
            "seven_day_sonnet_percent": parse_claude_usage_percent(seven_day_sonnet.get("utilization")),
        }
        if not any(value is not None for key, value in normalized.items() if key.endswith("_percent")):
            raise ClaudeUsageFetchError("invalid_response", "claude.ai usage 响应里没有可识别的用量字段")
        return normalized


class ClaudeCodeBackend:
    def read_secret_payload(self) -> tuple[dict[str, Any], str | None]:
        raise NotImplementedError

    def write_secret_payload(self, payload: dict[str, Any], account_name: str | None = None) -> None:
        raise NotImplementedError

    def status(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def active_auth_path(self) -> str:
        raise NotImplementedError


class SubprocessClaudeCodeBackend(ClaudeCodeBackend):
    EXTRA_CLAUDE_PATH_ENTRIES = ("/opt/homebrew/bin", "/usr/local/bin")

    def __init__(
        self,
        service_name: str = DEFAULT_CLAUDE_CODE_KEYCHAIN_SERVICE,
        default_account_name: str | None = None,
        claude_command: str = "claude",
    ) -> None:
        self.service_name = service_name
        self.default_account_name = default_account_name or os.environ.get("USER")
        self.claude_command = claude_command

    @property
    def active_auth_path(self) -> str:
        return f"keychain://generic-password/{self.service_name}"

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=False,
                env=self._command_env(),
            )
        except OSError as exc:
            raise AuthHubError(f"failed to run {' '.join(args)}: {exc}") from exc

    def _command_env(self) -> dict[str, str]:
        env = os.environ.copy()
        path_entries = [entry for entry in env.get("PATH", "").split(os.pathsep) if entry]
        seen_entries = set(path_entries)
        for candidate in self.EXTRA_CLAUDE_PATH_ENTRIES:
            if candidate not in seen_entries:
                path_entries.append(candidate)
                seen_entries.add(candidate)
        env["PATH"] = os.pathsep.join(path_entries)
        return env

    def resolve_claude_command(self) -> str:
        raw_command = self.claude_command.strip()
        if not raw_command:
            raise AuthHubError("claude command must not be empty")

        expanded_path = Path(raw_command).expanduser()
        if expanded_path.is_file():
            return str(expanded_path)

        resolved = shutil.which(raw_command, path=self._command_env().get("PATH"))
        if resolved:
            return resolved

        searched = ", ".join(self.EXTRA_CLAUDE_PATH_ENTRIES)
        raise AuthHubError(
            f"claude executable not found; checked PATH and common install paths: {searched}"
        )

    def read_secret_payload(self) -> tuple[dict[str, Any], str | None]:
        account_name = self.read_account_name()
        args = ["security", "find-generic-password", "-w", "-s", self.service_name]
        if account_name:
            args.extend(["-a", account_name])
        result = self._run(args)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise AuthHubError(message or f"Claude Code credentials not found in Keychain: {self.service_name}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AuthHubError("Claude Code Keychain secret is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise AuthHubError("Claude Code Keychain secret must be a JSON object")
        return payload, account_name

    def read_account_name(self) -> str | None:
        result = self._run(["security", "find-generic-password", "-s", self.service_name])
        if result.returncode != 0:
            return self.default_account_name
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        match = re.search(r'"acct"<blob>="([^"]*)"', output)
        if match:
            return match.group(1)
        return self.default_account_name

    def write_secret_payload(self, payload: dict[str, Any], account_name: str | None = None) -> None:
        resolved_account_name = account_name or self.read_account_name() or self.default_account_name or "claude-code"
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        result = self._run(
            [
                "security",
                "add-generic-password",
                "-U",
                "-s",
                self.service_name,
                "-a",
                resolved_account_name,
                "-w",
                raw,
            ]
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise AuthHubError(message or f"failed to update Keychain item: {self.service_name}")

    def status(self) -> dict[str, Any]:
        result = self._run([self.resolve_claude_command(), "auth", "status"])
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise AuthHubError(message or "claude auth status failed")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AuthHubError("claude auth status did not return valid JSON") from exc
        if not isinstance(payload, dict):
            raise AuthHubError("claude auth status did not return a JSON object")
        return payload


@dataclass(frozen=True)
class ClaudeCodeHubPaths:
    data_root: Path
    state_path: Path
    accounts_root: Path
    profile_path: Path = DEFAULT_CLAUDE_PROFILE_PATH
    claude_config_dir: Path = DEFAULT_CLAUDE_CONFIG_DIR

    @classmethod
    def defaults(cls) -> "ClaudeCodeHubPaths":
        data_root = default_claude_code_data_root()
        return cls(
            data_root=data_root,
            state_path=data_root / "state.json",
            accounts_root=data_root / "accounts",
            profile_path=DEFAULT_CLAUDE_PROFILE_PATH,
            claude_config_dir=current_claude_config_dir(),
        )


class ClaudeCodeHub:
    def __init__(
        self,
        paths: ClaudeCodeHubPaths | None = None,
        backend: ClaudeCodeBackend | None = None,
        usage_client: ClaudeUsageClient | None = None,
        session_store: ClaudeUsageSessionStore | None = None,
    ) -> None:
        self.paths = paths or ClaudeCodeHubPaths.defaults()
        self.backend = backend or SubprocessClaudeCodeBackend()
        self.usage_client = usage_client or ClaudeAiWebUsageClient()
        self.session_store = session_store or KeychainClaudeUsageSessionStore()
        self.paths.data_root.mkdir(parents=True, exist_ok=True)
        self.paths.accounts_root.mkdir(parents=True, exist_ok=True)

    def account_secret_path(self, account_id: str) -> Path:
        return self.paths.accounts_root / account_id / "credentials.json"

    def account_summary_path(self, account_id: str) -> Path:
        return self.paths.accounts_root / account_id / "summary.json"

    def usage_auth_path(self, account_id: str) -> Path:
        return self.paths.accounts_root / account_id / "usage_auth.json"

    def usage_cache_path(self, account_id: str) -> Path:
        return self.paths.accounts_root / account_id / "usage_cache.json"

    def usage_display_preferences_path(self) -> Path:
        return self.paths.data_root / "usage_display.json"

    def claude_settings_path(self) -> Path:
        return self.paths.claude_config_dir / "settings.json"

    def statusline_preferences_path(self) -> Path:
        return self.paths.data_root / "statusline.json"

    def statusline_runtime_path(self) -> Path:
        return self.paths.data_root / "statusline-runtime.json"

    def installed_statusline_script_path(self) -> Path:
        return self.paths.claude_config_dir / CLAUDE_STATUSLINE_SCRIPT_NAME

    def installed_statusline_wrapper_path(self) -> Path:
        return self.paths.claude_config_dir / CLAUDE_STATUSLINE_WRAPPER_NAME

    def load_statusline_preferences(self) -> dict[str, Any]:
        path = self.statusline_preferences_path()
        if not path.is_file():
            return empty_claude_statusline_preferences(str(path))
        try:
            stored = load_json_file(path)
        except (OSError, json.JSONDecodeError, AuthHubError):
            return empty_claude_statusline_preferences(str(path))
        return normalize_claude_statusline_preferences(str(path), stored)

    def save_statusline_preferences(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_claude_statusline_preferences(str(self.statusline_preferences_path()), payload)
        normalized["updated_at"] = utc_now_iso()
        atomic_write_json(self.statusline_preferences_path(), normalized)
        return self.load_statusline_preferences()

    def load_claude_settings(self) -> dict[str, Any]:
        path = self.claude_settings_path()
        if not path.is_file():
            return {}
        return load_json_file(path)

    def save_claude_settings(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self.claude_settings_path(), payload)

    def statusline_command(self) -> str:
        return f"bash {self.installed_statusline_wrapper_path()}"

    def statusline_command_matches(self, statusline_payload: Any) -> bool:
        if not isinstance(statusline_payload, dict):
            return False
        if str(statusline_payload.get("type") or "").strip() != "command":
            return False
        command = str(statusline_payload.get("command") or "")
        return CLAUDE_STATUSLINE_WRAPPER_NAME in command

    def install_statusline_files(self) -> None:
        self.paths.claude_config_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(
            self.installed_statusline_script_path(),
            build_claude_statusline_perl_script(
                self.statusline_preferences_path(),
                self.statusline_runtime_path(),
            ).encode("utf-8"),
            mode=0o755,
        )
        atomic_write_bytes(
            self.installed_statusline_wrapper_path(),
            build_claude_statusline_wrapper_script(self.installed_statusline_script_path()).encode("utf-8"),
            mode=0o755,
        )

    def statusline_runtime_payload(self, current: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = current or self.current_overview()
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        five_hour_reset = parse_iso_datetime(usage.get("five_hour_reset_at"))
        seven_day_reset = parse_iso_datetime(usage.get("seven_day_reset_at"))
        return {
            "updated_at": utc_now_iso(),
            "current_account_id": payload.get("matched_account_id"),
            "current_account_label": payload.get("matched_account_label")
            or payload.get("name")
            or payload.get("email"),
            "current_email": payload.get("email"),
            "usage": {
                "five_hour_percent": parse_cached_usage_percent(usage.get("five_hour_percent")),
                "five_hour_reset_at": iso_datetime(usage.get("five_hour_reset_at")),
                "five_hour_reset_epoch": int(five_hour_reset.timestamp()) if five_hour_reset else None,
                "seven_day_percent": parse_cached_usage_percent(usage.get("seven_day_percent")),
                "seven_day_reset_at": iso_datetime(usage.get("seven_day_reset_at")),
                "seven_day_reset_epoch": int(seven_day_reset.timestamp()) if seven_day_reset else None,
            },
        }

    def write_statusline_runtime_cache(self, current: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = self.statusline_runtime_payload(current=current)
        atomic_write_json(self.statusline_runtime_path(), payload)
        return payload

    def statusline_preview(self, current: dict[str, Any] | None = None) -> str:
        payload = current
        if payload is None:
            summary = self.current_summary()
            matched_account_id = self.current_account_id(current_summary=summary)
            payload = {
                **summary,
                "matched_account_id": matched_account_id,
                "matched_account_label": self.account_label(matched_account_id),
                "usage": self.saved_usage_cache(matched_account_id) if matched_account_id else empty_claude_usage_cache(""),
            }
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return build_claude_statusline_preview(
            self.load_statusline_preferences(),
            account_label=str(payload.get("matched_account_label") or payload.get("name") or payload.get("email") or "").strip() or None,
            usage=usage,
        )

    def statusline_overview(self, current: dict[str, Any] | None = None) -> dict[str, Any]:
        preferences = self.load_statusline_preferences()
        settings_path = self.claude_settings_path()
        script_path = self.installed_statusline_script_path()
        wrapper_path = self.installed_statusline_wrapper_path()
        settings_error = None
        settings = {}
        try:
            settings = self.load_claude_settings()
        except (OSError, json.JSONDecodeError, AuthHubError) as exc:
            settings_error = str(exc)
        statusline_payload = settings.get("statusLine") if isinstance(settings, dict) else None
        enabled_in_settings = self.statusline_command_matches(statusline_payload)
        configured_command = (
            str(statusline_payload.get("command") or "").strip()
            if isinstance(statusline_payload, dict)
            else None
        )
        current_account_id = self.current_account_id()
        current_payload = current or {
            **self.current_summary(),
            "matched_account_id": current_account_id,
            "matched_account_label": self.account_label(current_account_id),
            "usage": self.saved_usage_cache(current_account_id) if current_account_id else empty_claude_usage_cache(""),
        }
        return {
            "active": enabled_in_settings,
            "installed": script_path.is_file() and wrapper_path.is_file(),
            "settings_error": settings_error,
            "settings_path": str(settings_path),
            "script_path": str(script_path),
            "wrapper_path": str(wrapper_path),
            "command": self.statusline_command(),
            "configured_command": configured_command,
            "preferences": preferences,
            "saved_at": preferences.get("updated_at"),
            "preview": self.statusline_preview(current=current_payload),
            "source": "Claude Code stdin + Agent Account Hub 本地缓存兜底",
            "current_account_label": current_payload.get("matched_account_label")
            or current_payload.get("name")
            or current_payload.get("email"),
        }

    def set_statusline_preferences(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.current_overview()
        merged = {**self.load_statusline_preferences(), **(payload if isinstance(payload, dict) else {})}
        self.save_statusline_preferences(merged)
        self.write_statusline_runtime_cache(current=current)
        return self.statusline_overview(current=current)

    def apply_statusline(self) -> dict[str, Any]:
        current = self.current_overview()
        self.install_statusline_files()
        settings = self.load_claude_settings()
        settings["statusLine"] = {
            "type": "command",
            "command": self.statusline_command(),
            "padding": 0,
        }
        self.save_claude_settings(settings)
        self.write_statusline_runtime_cache(current=current)
        return self.statusline_overview(current=current)

    def disable_statusline(self) -> dict[str, Any]:
        settings = self.load_claude_settings()
        existing = settings.get("statusLine")
        if self.statusline_command_matches(existing):
            settings.pop("statusLine", None)
            self.save_claude_settings(settings)
        current = self.current_overview()
        self.write_statusline_runtime_cache(current=current)
        return self.statusline_overview(current=current)

    def load_state(self) -> dict[str, Any]:
        if not self.paths.state_path.is_file():
            state = default_state()
            self.save_state(state)
            return state

        state = load_json_file(self.paths.state_path)
        accounts_payload = state.get("accounts")
        if not isinstance(accounts_payload, list):
            raise AuthHubError(f"{self.paths.state_path} is missing a valid accounts array")

        normalized_accounts = self._normalize_accounts(accounts_payload)
        normalized_state = {"version": 2, "accounts": normalized_accounts}
        if state.get("version") != 2 or state.get("accounts") != normalized_accounts:
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

            secret_path = self.account_secret_path(account_id)
            if not secret_path.is_file():
                continue

            snapshot = self.saved_account_summary(account_id)
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

    def update_account(self, account_id: str, **updates: Any) -> dict[str, Any]:
        state = self.load_state()
        for account in state["accounts"]:
            if account.get("id") == account_id:
                account.update(updates)
                self.save_state(state)
                return account
        raise AuthHubError(f"account {account_id} not found")

    def rename_account(self, account_id: str, label: str) -> dict[str, Any]:
        if not label.strip():
            raise AuthHubError("label must not be empty")
        return self.update_account(account_id, label=label.strip())

    def rename_slot(self, slot_id: str, label: str) -> dict[str, Any]:
        return self.rename_account(slot_id, label)

    def _current_secret_payload(self) -> tuple[dict[str, Any], str | None]:
        return self.backend.read_secret_payload()

    def load_profile_payload(self, path: Path | None = None) -> dict[str, Any] | None:
        profile_path = path or self.paths.profile_path
        if not profile_path.is_file():
            return None
        try:
            return load_json_file(profile_path)
        except (OSError, json.JSONDecodeError, AuthHubError):
            return None

    def profile_backup_paths(self) -> list[Path]:
        candidates: list[Path] = []
        sibling_backup = self.paths.profile_path.with_name(f"{self.paths.profile_path.name}.backup")
        if sibling_backup.is_file():
            candidates.append(sibling_backup)

        backups_root = self.paths.profile_path.parent / ".claude" / "backups"
        if backups_root.is_dir():
            candidates.extend(sorted(backups_root.glob(f"{self.paths.profile_path.name}.backup*"), reverse=True))

        unique_paths: list[Path] = []
        seen: set[Path] = set()
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            unique_paths.append(path)
        return unique_paths

    def resolve_oauth_account(self, summary: dict[str, Any]) -> dict[str, Any] | None:
        direct_oauth_account = summary.get("oauth_account")
        if claude_oauth_account_matches(summary, direct_oauth_account):
            return direct_oauth_account

        for path in [self.paths.profile_path, *self.profile_backup_paths()]:
            oauth_account = claude_oauth_account_from_profile(self.load_profile_payload(path))
            if claude_oauth_account_matches(summary, oauth_account):
                return oauth_account
        return None

    def write_profile_oauth_account(self, oauth_account: dict[str, Any] | None) -> None:
        if not isinstance(oauth_account, dict):
            return
        profile_payload = self.load_profile_payload() or {}
        profile_payload["oauthAccount"] = oauth_account
        atomic_write_json(self.paths.profile_path, profile_payload)

    def saved_usage_auth(self, account_id: str) -> dict[str, Any]:
        auth_path = self.usage_auth_path(account_id)
        payload = empty_claude_usage_auth(str(auth_path))
        if not auth_path.is_file():
            return payload

        try:
            stored = load_json_file(auth_path)
        except (OSError, json.JSONDecodeError, AuthHubError) as exc:
            payload["status"] = "error"
            payload["error"] = str(exc)
            return payload

        payload["organization_id"] = str(stored.get("organization_id") or "").strip() or None
        payload["organization_name"] = str(stored.get("organization_name") or "").strip() or None
        payload["updated_at"] = iso_datetime(stored.get("updated_at"))
        payload["keychain_service"] = (
            str(stored.get("keychain_service") or "").strip()
            or self.session_store.service_name
        )
        payload["keychain_account_name"] = (
            str(stored.get("keychain_account_name") or "").strip()
            or self.session_store.account_name(account_id)
        )

        session_key = self.session_store.read_optional(account_id)
        payload["has_session_key"] = bool(session_key)
        payload["configured"] = bool(payload["organization_id"] and session_key)
        payload["status"] = "ready" if payload["configured"] else "auth_missing"
        return payload

    def saved_usage_cache(self, account_id: str) -> dict[str, Any]:
        cache_path = self.usage_cache_path(account_id)
        payload = empty_claude_usage_cache(str(cache_path))
        auth = self.saved_usage_auth(account_id)
        payload["organization_id"] = auth.get("organization_id")
        payload["organization_name"] = auth.get("organization_name")
        if not cache_path.is_file():
            if auth.get("status") == "auth_missing":
                payload["status"] = "auth_missing"
                payload["error"] = "缺少 claude.ai sessionKey"
            return payload

        try:
            stored = load_json_file(cache_path)
        except (OSError, json.JSONDecodeError, AuthHubError) as exc:
            payload["status"] = "error"
            payload["error"] = str(exc)
            return payload

        payload["status"] = str(stored.get("status") or payload["status"])
        payload["error"] = str(stored.get("error") or "").strip() or None
        payload["last_attempt_at"] = iso_datetime(stored.get("last_attempt_at"))
        payload["last_success_at"] = iso_datetime(stored.get("last_success_at"))
        payload["five_hour_percent"] = parse_cached_usage_percent(stored.get("five_hour_percent"))
        payload["five_hour_reset_at"] = iso_datetime(stored.get("five_hour_reset_at"))
        payload["seven_day_percent"] = parse_cached_usage_percent(stored.get("seven_day_percent"))
        payload["seven_day_reset_at"] = iso_datetime(stored.get("seven_day_reset_at"))
        payload["seven_day_opus_percent"] = parse_cached_usage_percent(stored.get("seven_day_opus_percent"))
        payload["seven_day_sonnet_percent"] = parse_cached_usage_percent(stored.get("seven_day_sonnet_percent"))
        payload["organization_id"] = (
            str(stored.get("organization_id") or "").strip() or payload["organization_id"]
        )
        payload["organization_name"] = (
            str(stored.get("organization_name") or "").strip() or payload["organization_name"]
        )

        last_success = parse_iso_datetime(payload.get("last_success_at"))
        payload["stale"] = False
        if payload["status"] in {"ok", "stale"} and last_success is not None:
            age_seconds = (datetime.now(timezone.utc) - last_success).total_seconds()
            if age_seconds >= CLAUDE_USAGE_STALE_SECONDS:
                payload["status"] = "stale"
                payload["stale"] = True
        elif payload["status"] == "stale":
            payload["stale"] = True

        if auth.get("status") == "auth_missing":
            payload["status"] = "auth_missing"
            payload["error"] = auth.get("error") or "缺少 claude.ai sessionKey"

        return payload

    def load_usage_display_preferences(self) -> dict[str, Any]:
        path = self.usage_display_preferences_path()
        payload = empty_claude_usage_display_preferences(str(path))
        if not path.is_file():
            return payload
        try:
            stored = load_json_file(path)
        except (OSError, json.JSONDecodeError, AuthHubError):
            return payload
        raw_ids = stored.get("selected_account_ids")
        if isinstance(raw_ids, list):
            seen: set[str] = set()
            normalized_ids: list[str] = []
            for value in raw_ids:
                account_id = str(value or "").strip()
                if not account_id or account_id in seen:
                    continue
                seen.add(account_id)
                normalized_ids.append(account_id)
            payload["selected_account_ids"] = normalized_ids
        return payload

    def save_usage_display_preferences(self, payload: dict[str, Any]) -> None:
        normalized = empty_claude_usage_display_preferences(str(self.usage_display_preferences_path()))
        seen: set[str] = set()
        selected_ids: list[str] = []
        for value in payload.get("selected_account_ids") or []:
            account_id = str(value or "").strip()
            if not account_id or account_id in seen:
                continue
            seen.add(account_id)
            selected_ids.append(account_id)
        normalized["selected_account_ids"] = selected_ids
        atomic_write_json(self.usage_display_preferences_path(), normalized)

    def usage_menu_bar_eligible(
        self,
        account_id: str,
        *,
        usage_auth: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
    ) -> bool:
        auth = usage_auth or self.saved_usage_auth(account_id)
        cache = usage or self.saved_usage_cache(account_id)
        if not auth.get("configured"):
            return False
        status = str(cache.get("status") or "")
        if status not in {"ok", "stale"}:
            return False
        return any(
            cache.get(key) is not None
            for key in ("five_hour_percent", "seven_day_percent")
        )

    def usage_menu_bar_selected_account_ids(self) -> list[str]:
        preferences = self.load_usage_display_preferences()
        normalized_ids: list[str] = []
        changed = False
        for account_id in preferences["selected_account_ids"]:
            try:
                self.get_account(account_id)
            except AuthHubError:
                changed = True
                continue
            usage_auth = self.saved_usage_auth(account_id)
            usage = self.saved_usage_cache(account_id)
            if not self.usage_menu_bar_eligible(
                account_id,
                usage_auth=usage_auth,
                usage=usage,
            ):
                changed = True
                continue
            normalized_ids.append(account_id)
        if changed or normalized_ids != preferences["selected_account_ids"]:
            self.save_usage_display_preferences({"selected_account_ids": normalized_ids})
        return normalized_ids

    def usage_menu_bar_accounts(self) -> list[dict[str, Any]]:
        return [self.account_overview(account_id) for account_id in self.usage_menu_bar_selected_account_ids()]

    def _set_usage_menu_bar_selection(self, selected_ids: list[str]) -> None:
        self.save_usage_display_preferences({"selected_account_ids": selected_ids})

    def remove_usage_menu_bar_account(self, account_id: str) -> None:
        preferences = self.load_usage_display_preferences()
        selected_ids = [value for value in preferences["selected_account_ids"] if value != account_id]
        if selected_ids != preferences["selected_account_ids"]:
            self._set_usage_menu_bar_selection(selected_ids)

    def set_usage_menu_bar_visible(self, account_id: str, visible: bool) -> dict[str, Any]:
        self.get_account(account_id)
        preferences = self.load_usage_display_preferences()
        selected_ids = list(preferences["selected_account_ids"])
        if visible:
            account = self.account_overview(account_id)
            if not account.get("usage_menu_bar_eligible"):
                raise AuthHubError("只有已配置 claude.ai 认证并且已成功获取到用量的账号才能显示到菜单栏")
            if account_id not in selected_ids:
                selected_ids.append(account_id)
        else:
            selected_ids = [value for value in selected_ids if value != account_id]
        self._set_usage_menu_bar_selection(selected_ids)
        return self.account_overview(account_id)

    def _write_usage_auth(
        self,
        account_id: str,
        *,
        organization_id: str,
        organization_name: str | None = None,
    ) -> dict[str, Any]:
        auth_path = self.usage_auth_path(account_id)
        payload = {
            "organization_id": organization_id,
            "organization_name": organization_name,
            "updated_at": utc_now_iso(),
            "keychain_service": self.session_store.service_name,
            "keychain_account_name": self.session_store.account_name(account_id),
        }
        atomic_write_json(auth_path, payload)
        return self.saved_usage_auth(account_id)

    def _write_usage_cache(self, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        cache_path = self.usage_cache_path(account_id)
        atomic_write_json(cache_path, payload)
        return self.saved_usage_cache(account_id)

    def _clear_usage_cache_file(self, account_id: str) -> None:
        cache_path = self.usage_cache_path(account_id)
        if cache_path.exists():
            cache_path.unlink()

    def set_usage_auth(
        self,
        account_id: str,
        session_key: str,
        organization_id: str,
        organization_name: str | None = None,
    ) -> dict[str, Any]:
        self.get_account(account_id)
        normalized_session_key = session_key.strip()
        normalized_org_id = organization_id.strip()
        normalized_org_name = organization_name.strip() if isinstance(organization_name, str) else None
        if not normalized_session_key:
            normalized_session_key = self.session_store.read_optional(account_id) or ""
        if not normalized_session_key:
            raise AuthHubError("sessionKey 不能为空")
        if not normalized_org_id:
            raise AuthHubError("organizationId 不能为空")

        self.session_store.write(account_id, normalized_session_key)
        self._write_usage_auth(
            account_id,
            organization_id=normalized_org_id,
            organization_name=normalized_org_name or None,
        )
        self.refresh_usage(account_id)
        return self.account_overview(account_id)

    def clear_usage_auth(self, account_id: str) -> dict[str, Any]:
        self.get_account(account_id)
        self.session_store.delete(account_id)
        auth_path = self.usage_auth_path(account_id)
        if auth_path.exists():
            auth_path.unlink()
        self._clear_usage_cache_file(account_id)
        self.remove_usage_menu_bar_account(account_id)
        return self.account_overview(account_id)

    def refresh_usage(self, account_id: str) -> dict[str, Any]:
        self.get_account(account_id)
        now = utc_now_iso()
        auth = self.saved_usage_auth(account_id)
        previous_cache = self.saved_usage_cache(account_id)

        if not auth.get("organization_id"):
            self._write_usage_cache(
                account_id,
                {
                    **empty_claude_usage_cache(str(self.usage_cache_path(account_id))),
                    "status": "not_configured",
                    "error": None,
                    "last_attempt_at": now,
                    "organization_id": None,
                    "organization_name": None,
                },
            )
            return self.account_overview(account_id)

        session_key = self.session_store.read_optional(account_id)
        if not session_key:
            self._write_usage_cache(
                account_id,
                {
                    **empty_claude_usage_cache(str(self.usage_cache_path(account_id))),
                    "status": "auth_missing",
                    "error": "缺少 claude.ai sessionKey",
                    "last_attempt_at": now,
                    "last_success_at": previous_cache.get("last_success_at"),
                    "five_hour_percent": previous_cache.get("five_hour_percent"),
                    "five_hour_reset_at": previous_cache.get("five_hour_reset_at"),
                    "seven_day_percent": previous_cache.get("seven_day_percent"),
                    "seven_day_reset_at": previous_cache.get("seven_day_reset_at"),
                    "seven_day_opus_percent": previous_cache.get("seven_day_opus_percent"),
                    "seven_day_sonnet_percent": previous_cache.get("seven_day_sonnet_percent"),
                    "organization_id": auth.get("organization_id"),
                    "organization_name": auth.get("organization_name"),
                    "stale": bool(previous_cache.get("last_success_at")),
                },
            )
            return self.account_overview(account_id)

        try:
            usage = self.usage_client.fetch_usage(session_key, str(auth["organization_id"]))
        except ClaudeUsageFetchError as exc:
            has_prior_data = any(
                previous_cache.get(key) is not None
                for key in (
                    "five_hour_percent",
                    "seven_day_percent",
                    "seven_day_opus_percent",
                    "seven_day_sonnet_percent",
                )
            )
            status = exc.kind
            if status not in {"unauthorized", "invalid_response"} and has_prior_data:
                status = "stale"
            if status == "invalid_response":
                status = "error"
            self._write_usage_cache(
                account_id,
                {
                    **previous_cache,
                    "path": str(self.usage_cache_path(account_id)),
                    "status": status,
                    "error": str(exc),
                    "last_attempt_at": now,
                    "organization_id": auth.get("organization_id"),
                    "organization_name": auth.get("organization_name"),
                    "stale": status == "stale",
                },
            )
            return self.account_overview(account_id)

        self._write_usage_cache(
            account_id,
            {
                **empty_claude_usage_cache(str(self.usage_cache_path(account_id)), status="ok"),
                **usage,
                "status": "ok",
                "error": None,
                "last_attempt_at": now,
                "last_success_at": now,
                "organization_id": auth.get("organization_id"),
                "organization_name": auth.get("organization_name"),
                "stale": False,
            },
        )
        return self.account_overview(account_id)

    def refresh_all_usage(self) -> dict[str, Any]:
        for account in self.load_state()["accounts"]:
            account_id = str(account["id"])
            auth = self.saved_usage_auth(account_id)
            if auth.get("status") in {"ready", "auth_missing"} or auth.get("organization_id"):
                self.refresh_usage(account_id)
        return self.overview()

    def current_summary(self) -> dict[str, Any]:
        path = self.backend.active_auth_path
        try:
            payload, keychain_account_name = self._current_secret_payload()
        except AuthHubError as exc:
            summary = empty_claude_summary(path, exists=False)
            summary["error"] = str(exc)
            return summary

        try:
            status_payload = self.backend.status()
        except AuthHubError as exc:
            status_payload = None
            status_error = str(exc)
        else:
            status_error = None

        oauth_account = claude_oauth_account_from_profile(self.load_profile_payload())
        summary = claude_summary_from_payload(
            payload,
            path=path,
            status_payload=status_payload,
            keychain_account_name=keychain_account_name,
            oauth_account=oauth_account,
        )
        if status_error:
            summary["error"] = status_error
        return summary

    def saved_account_summary(self, account_id: str) -> dict[str, Any]:
        secret_path = self.account_secret_path(account_id)
        if not secret_path.is_file():
            return empty_claude_summary(str(secret_path), exists=False)

        try:
            payload = load_json_file(secret_path)
        except (OSError, json.JSONDecodeError, AuthHubError) as exc:
            summary = empty_claude_summary(str(secret_path), exists=True)
            summary["status"] = "invalid"
            summary["error"] = str(exc)
            summary["hash"] = sha256_file(secret_path)
            return summary

        summary = claude_summary_from_payload(payload, path=str(secret_path))
        summary["hash"] = sha256_file(secret_path)

        summary_path = self.account_summary_path(account_id)
        if summary_path.is_file():
            try:
                stored_summary = load_json_file(summary_path)
            except (OSError, json.JSONDecodeError, AuthHubError):
                stored_summary = {}
            for key, value in stored_summary.items():
                if key in {"path", "exists", "status", "hash", "error"}:
                    continue
                if value not in (None, "", []):
                    summary[key] = value
        return summary

    def current_account_id(self, current_summary: dict[str, Any] | None = None) -> str | None:
        current_summary = current_summary or self.current_summary()
        current_hash = current_summary.get("hash")
        if current_hash:
            for account in self.load_state()["accounts"]:
                account_id = str(account["id"])
                if sha256_file(self.account_secret_path(account_id)) == current_hash:
                    return account_id

        current_identity = claude_identity_key(current_summary)
        if not current_identity:
            return None
        return self.find_account_id_by_identity(current_identity)

    def current_overview(self, sync_result: dict[str, Any] | None = None) -> dict[str, Any]:
        if sync_result is None:
            sync_result = self.sync_current_account_snapshot()
        current = self.current_summary()
        matched_account_id = self.current_account_id(current_summary=current)
        current["matched_account_id"] = matched_account_id
        current["matched_slot_id"] = matched_account_id
        current["matched_account_label"] = self.account_label(matched_account_id)
        current["snapshot_sync_status"] = sync_result.get("status")
        current["snapshot_sync_updated"] = bool(sync_result.get("updated"))
        current["snapshot_sync_account_id"] = sync_result.get("account_id") or matched_account_id
        current["usage_auth"] = self.saved_usage_auth(matched_account_id) if matched_account_id else empty_claude_usage_auth("")
        current["usage"] = self.saved_usage_cache(matched_account_id) if matched_account_id else empty_claude_usage_cache("")
        self.write_statusline_runtime_cache(current=current)
        return current

    def overview(self) -> dict[str, Any]:
        sync_result = self.sync_current_account_snapshot()
        current = self.current_overview(sync_result=sync_result)
        accounts = []
        for account in self.load_state()["accounts"]:
            account_id = str(account["id"])
            accounts.append(self.account_overview(account_id))
        return {
            "active_auth_path": self.backend.active_auth_path,
            "current": current,
            "accounts": accounts,
            "slots": list(accounts),
            "usage_menu_bar_accounts": self.usage_menu_bar_accounts(),
            "statusline": self.statusline_overview(current=current),
            "project_root": str(PROJECT_ROOT),
            "data_root": str(self.paths.data_root),
        }

    def find_account_id_by_identity(self, identity_key: str) -> str | None:
        for account in self.load_state()["accounts"]:
            account_id = str(account["id"])
            summary = self.saved_account_summary(account_id)
            if claude_identity_key(summary) == identity_key:
                return account_id
        return None

    def account_label(self, account_id: str | None) -> str | None:
        if not account_id:
            return None
        try:
            account = self.get_account(account_id)
        except AuthHubError:
            return None
        snapshot = self.saved_account_summary(account_id)
        existing_label = str(account.get("label") or "").strip()
        if snapshot.get("exists") and is_placeholder_account_label(existing_label, account_id):
            return suggested_account_label(snapshot)
        return existing_label or (suggested_account_label(snapshot) if snapshot.get("exists") else account_id)

    def account_overview(self, account_id: str) -> dict[str, Any]:
        account = dict(self.get_account(account_id))
        snapshot = self.saved_account_summary(account_id)
        usage_auth = self.saved_usage_auth(account_id)
        usage = self.saved_usage_cache(account_id)
        usage_menu_bar_selected_ids = set(self.usage_menu_bar_selected_account_ids())
        current_account_id = self.current_account_id()
        account["snapshot"] = snapshot
        account["usage_auth"] = usage_auth
        account["usage"] = usage
        account["usage_menu_bar_eligible"] = self.usage_menu_bar_eligible(
            account_id,
            usage_auth=usage_auth,
            usage=usage,
        )
        account["usage_menu_bar_visible"] = account_id in usage_menu_bar_selected_ids
        account["active"] = account_id == current_account_id
        return account

    def _write_snapshot(
        self,
        payload: dict[str, Any],
        summary: dict[str, Any],
        account_id: str,
        *,
        allow_create: bool,
    ) -> dict[str, Any]:
        state = self.load_state()
        account: dict[str, Any] | None = None
        for item in state["accounts"]:
            if item.get("id") == account_id:
                account = item
                break

        now = utc_now_iso()
        account_label = suggested_account_label(summary, len(state["accounts"]) + 1)
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

        secret_path = self.account_secret_path(account_id)
        summary_path = self.account_summary_path(account_id)
        atomic_write_json(secret_path, payload)
        atomic_write_json(summary_path, summary)

        account_payload = self.account_overview(account_id)
        account_payload["cleared_account_ids"] = self._clear_duplicate_accounts(account_id)
        account_payload["cleared_slot_ids"] = list(account_payload["cleared_account_ids"])
        return account_payload

    def create_account_from_current(self) -> dict[str, Any]:
        current_summary = self.current_summary()
        if not current_summary.get("exists"):
            raise AuthHubError("Claude Code credentials not found in Keychain")

        payload, _ = self._current_secret_payload()
        current_identity = claude_identity_key(current_summary)
        if current_identity:
            existing_id = self.find_account_id_by_identity(current_identity)
            if existing_id:
                snapshot = self._write_snapshot(payload, current_summary, existing_id, allow_create=False)
                snapshot["created_new_account"] = False
                return snapshot

        account_id = self.next_account_id()
        snapshot = self._write_snapshot(payload, current_summary, account_id, allow_create=True)
        snapshot["created_new_account"] = True
        return snapshot

    def save_current_to_account(self, account_id: str) -> dict[str, Any]:
        current_summary = self.current_summary()
        if not current_summary.get("exists"):
            raise AuthHubError("Claude Code credentials not found in Keychain")
        payload, _ = self._current_secret_payload()
        return self._write_snapshot(payload, current_summary, account_id, allow_create=False)

    def import_file(self, account_id: str, credentials_path: Path) -> dict[str, Any]:
        if not credentials_path.is_file():
            raise AuthHubError(f"credentials snapshot not found: {credentials_path}")
        payload = load_json_file(credentials_path)
        summary = claude_summary_from_payload(payload, path=str(credentials_path))
        return self._write_snapshot(payload, summary, account_id, allow_create=True)

    def switch(self, account_id: str) -> dict[str, Any]:
        secret_path = self.account_secret_path(account_id)
        if not secret_path.is_file():
            raise AuthHubError(f"account {account_id} has no saved credentials snapshot")
        payload = load_json_file(secret_path)
        account_summary = self.saved_account_summary(account_id)
        self.backend.write_secret_payload(payload, account_summary.get("keychain_account_name"))
        self.write_profile_oauth_account(self.resolve_oauth_account(account_summary))
        account = self.get_account(account_id)
        self.update_account(
            account_id,
            created_at=account.get("created_at") or utc_now_iso(),
            updated_at=account.get("updated_at") or utc_now_iso(),
        )
        return self.current_overview()

    def delete_account(self, account_id: str) -> dict[str, Any]:
        account = dict(self.get_account(account_id))
        secret_path = self.account_secret_path(account_id)
        summary_path = self.account_summary_path(account_id)
        usage_auth_path = self.usage_auth_path(account_id)
        usage_cache_path = self.usage_cache_path(account_id)
        if secret_path.exists():
            secret_path.unlink()
        if summary_path.exists():
            summary_path.unlink()
        if usage_auth_path.exists():
            usage_auth_path.unlink()
        if usage_cache_path.exists():
            usage_cache_path.unlink()
        self.session_store.delete(account_id)
        self.remove_usage_menu_bar_account(account_id)
        parent = secret_path.parent
        if parent.exists():
            shutil.rmtree(parent, ignore_errors=True)
        state = self.load_state()
        state["accounts"] = [item for item in state["accounts"] if item.get("id") != account_id]
        self.save_state(state)
        return {"id": account_id, "label": account.get("label") or account_id, "deleted": True}

    def sync_current_account_snapshot(self) -> dict[str, Any]:
        result = {"account_id": None, "status": "not_saved", "updated": False}
        current_summary = self.current_summary()
        if not current_summary.get("exists"):
            result["status"] = "missing"
            return result
        if current_summary.get("status") != "ready":
            result["status"] = "invalid"
            return result

        current_identity = claude_identity_key(current_summary)
        if not current_identity:
            result["status"] = "unidentifiable"
            return result

        account_id = self.find_account_id_by_identity(current_identity)
        if not account_id:
            return result

        result["account_id"] = account_id
        snapshot_hash = sha256_file(self.account_secret_path(account_id))
        current_hash = current_summary.get("hash")
        if snapshot_hash and current_hash and snapshot_hash == current_hash:
            result["status"] = "up_to_date"
            return result

        payload, _ = self._current_secret_payload()
        self._write_snapshot(payload, current_summary, account_id, allow_create=False)
        result["status"] = "updated"
        result["updated"] = True
        return result

    def _clear_duplicate_accounts(self, target_account_id: str) -> list[str]:
        target_summary = self.saved_account_summary(target_account_id)
        target_identity = claude_identity_key(target_summary)
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

            other_summary = self.saved_account_summary(account_id)
            if claude_identity_key(other_summary) != target_identity:
                remaining_accounts.append(account)
                continue

            target_auth = self.saved_usage_auth(target_account_id)
            other_auth = self.saved_usage_auth(account_id)
            if not target_auth.get("configured") and other_auth.get("configured"):
                session_key = self.session_store.read_optional(account_id)
                organization_id = str(other_auth.get("organization_id") or "").strip()
                if session_key and organization_id:
                    self.session_store.write(target_account_id, session_key)
                    self._write_usage_auth(
                        target_account_id,
                        organization_id=organization_id,
                        organization_name=other_auth.get("organization_name"),
                    )
                    other_cache_path = self.usage_cache_path(account_id)
                    if other_cache_path.is_file():
                        shutil.copy2(other_cache_path, self.usage_cache_path(target_account_id))

            parent = self.account_secret_path(account_id).parent
            if parent.exists():
                shutil.rmtree(parent, ignore_errors=True)
            self.session_store.delete(account_id)
            self.remove_usage_menu_bar_account(account_id)
            cleared_account_ids.append(account_id)

        if cleared_account_ids:
            state["accounts"] = remaining_accounts
            self.save_state(state)

        return cleared_account_ids


class UnifiedAuthHub:
    def __init__(
        self,
        codex_hub: AuthHub | None = None,
        claude_code_hub: ClaudeCodeHub | None = None,
    ) -> None:
        self._hubs: dict[str, Any] = {
            "codex": codex_hub or CodexUsageHub(),
            CLAUDE_CODE_PROVIDER_ID: claude_code_hub or ClaudeCodeHub(),
        }

    def provider_hub(self, provider: str) -> Any:
        normalized = normalize_provider_name(provider)
        return self._hubs[normalized]

    def provider_ids(self) -> list[str]:
        return list(self._hubs.keys())

    def provider_overview(self, provider: str) -> dict[str, Any]:
        normalized = normalize_provider_name(provider)
        overview = self.provider_hub(normalized).overview()
        overview["provider_id"] = normalized
        overview["provider_label"] = provider_label(normalized)
        overview["capabilities"] = {
            "usage_tracking": normalized in {"codex", CLAUDE_CODE_PROVIDER_ID},
            "usage_auth_mode": "embedded" if normalized == "codex" else "manual",
            "usage_auto_refresh_seconds": CODEX_USAGE_MIN_REFRESH_SECONDS
            if normalized == "codex"
            else 5 * 60,
            "statusline_integration": normalized == CLAUDE_CODE_PROVIDER_ID,
        }
        return overview

    def create_account_from_current(self, provider: str) -> dict[str, Any]:
        return self.provider_hub(provider).create_account_from_current()

    def save_current_to_account(self, provider: str, account_id: str) -> dict[str, Any]:
        return self.provider_hub(provider).save_current_to_account(account_id)

    def switch(self, provider: str, account_id: str) -> dict[str, Any]:
        return self.provider_hub(provider).switch(account_id)

    def delete_account(self, provider: str, account_id: str) -> dict[str, Any]:
        return self.provider_hub(provider).delete_account(account_id)

    def rename_account(self, provider: str, account_id: str, label: str) -> dict[str, Any]:
        hub = self.provider_hub(provider)
        rename = getattr(hub, "rename_slot", None) or getattr(hub, "rename_account", None)
        if rename is None:
            raise AuthHubError(f"provider {provider} does not support renaming accounts")
        return rename(account_id, label)

    def set_usage_auth(
        self,
        provider: str,
        account_id: str,
        session_key: str,
        organization_id: str,
        organization_name: str | None = None,
    ) -> dict[str, Any]:
        hub = self.provider_hub(provider)
        configure = getattr(hub, "set_usage_auth", None)
        if configure is None:
            raise AuthHubError(f"provider {provider} does not support usage tracking")
        return configure(account_id, session_key, organization_id, organization_name)

    def clear_usage_auth(self, provider: str, account_id: str) -> dict[str, Any]:
        hub = self.provider_hub(provider)
        clear = getattr(hub, "clear_usage_auth", None)
        if clear is None:
            raise AuthHubError(f"provider {provider} does not support usage tracking")
        return clear(account_id)

    def refresh_usage(self, provider: str, account_id: str) -> dict[str, Any]:
        hub = self.provider_hub(provider)
        refresh = getattr(hub, "refresh_usage", None)
        if refresh is None:
            raise AuthHubError(f"provider {provider} does not support usage tracking")
        return refresh(account_id)

    def refresh_all_usage(self, provider: str) -> dict[str, Any]:
        hub = self.provider_hub(provider)
        refresh = getattr(hub, "refresh_all_usage", None)
        if refresh is None:
            raise AuthHubError(f"provider {provider} does not support usage tracking")
        return refresh()

    def set_usage_menu_bar_visible(self, provider: str, account_id: str, visible: bool) -> dict[str, Any]:
        hub = self.provider_hub(provider)
        update = getattr(hub, "set_usage_menu_bar_visible", None)
        if update is None:
            raise AuthHubError(f"provider {provider} does not support menu bar usage selection")
        return update(account_id, visible)

    def set_statusline_preferences(self, provider: str, payload: dict[str, Any]) -> dict[str, Any]:
        hub = self.provider_hub(provider)
        update = getattr(hub, "set_statusline_preferences", None)
        if update is None:
            raise AuthHubError(f"provider {provider} does not support statusline integration")
        return update(payload)

    def apply_statusline(self, provider: str) -> dict[str, Any]:
        hub = self.provider_hub(provider)
        apply_statusline = getattr(hub, "apply_statusline", None)
        if apply_statusline is None:
            raise AuthHubError(f"provider {provider} does not support statusline integration")
        return apply_statusline()

    def disable_statusline(self, provider: str) -> dict[str, Any]:
        hub = self.provider_hub(provider)
        disable = getattr(hub, "disable_statusline", None)
        if disable is None:
            raise AuthHubError(f"provider {provider} does not support statusline integration")
        return disable()
