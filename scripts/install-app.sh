#!/usr/bin/env bash

set -euo pipefail

REPO_OWNER="gitliu-my"
REPO_NAME="codex-account-hub"
ASSET_NAME="Codex Account Hub.zip"
TARGET_DIR=""
VERSION=""

usage() {
  cat <<'EOF'
Install the latest Codex Account Hub macOS app bundle from GitHub Releases.

Usage:
  install-app.sh [--user] [--version v0.1.0]

Options:
  --user            Install to ~/Applications instead of /Applications.
  --version <tag>   Install a specific Git tag release instead of the latest release.
  -h, --help        Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user)
      TARGET_DIR="$HOME/Applications"
      shift
      ;;
    --version)
      VERSION="${2:-}"
      if [[ -z "$VERSION" ]]; then
        echo "error: --version requires a tag like v0.1.0" >&2
        exit 1
      fi
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: this installer only supports macOS." >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "error: curl is required." >&2
  exit 1
fi

if ! command -v ditto >/dev/null 2>&1; then
  echo "error: ditto is required." >&2
  exit 1
fi

if [[ -z "$TARGET_DIR" ]]; then
  TARGET_DIR="/Applications"
  if [[ ! -d "$TARGET_DIR" || ! -w "$TARGET_DIR" ]]; then
    TARGET_DIR="$HOME/Applications"
  fi
fi

mkdir -p "$TARGET_DIR"

resolve_asset_url() {
  if [[ -n "$VERSION" ]]; then
    python3 - "$REPO_OWNER" "$REPO_NAME" "$VERSION" "$ASSET_NAME" <<'PY'
import json
import sys
from urllib.parse import quote

owner, repo, version, asset_name = sys.argv[1:]
print(f"https://github.com/{owner}/{repo}/releases/download/{version}/{quote(asset_name)}")
PY
    return
  fi

  local api_url="https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/releases/latest"
  python3 - "$api_url" "$ASSET_NAME" <<'PY'
import json
import sys
import urllib.request

api_url, asset_name = sys.argv[1:]
with urllib.request.urlopen(api_url) as response:
    payload = json.load(response)

for asset in payload.get("assets", []):
    if asset.get("name") == asset_name:
        print(asset["browser_download_url"])
        break
else:
    raise SystemExit(f"release asset not found: {asset_name}")
PY
}

ASSET_URL="$(resolve_asset_url)"
TMP_DIR="$(mktemp -d)"
ZIP_PATH="${TMP_DIR}/${ASSET_NAME}"
APP_STAGING_DIR="${TMP_DIR}/staging"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "Downloading ${ASSET_NAME}..."
curl -fL --progress-bar "$ASSET_URL" -o "$ZIP_PATH"

echo "Extracting app bundle..."
mkdir -p "$APP_STAGING_DIR"
ditto -x -k "$ZIP_PATH" "$APP_STAGING_DIR"

APP_SOURCE_PATH="${APP_STAGING_DIR}/Codex Account Hub.app"
APP_TARGET_PATH="${TARGET_DIR}/Codex Account Hub.app"

if [[ ! -d "$APP_SOURCE_PATH" ]]; then
  echo "error: extracted archive did not contain Codex Account Hub.app" >&2
  exit 1
fi

echo "Installing to ${APP_TARGET_PATH}..."
ditto "$APP_SOURCE_PATH" "$APP_TARGET_PATH"

echo
echo "Installed:"
echo "  ${APP_TARGET_PATH}"
echo
echo "Launch it with:"
echo "  open \"${APP_TARGET_PATH}\""
