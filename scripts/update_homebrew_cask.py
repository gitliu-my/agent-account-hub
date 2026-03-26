from __future__ import annotations

import argparse
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update a Homebrew cask file with a new version and sha256."
    )
    parser.add_argument("--cask-file", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--sha256", required=True)
    return parser.parse_args()


def replace_once(pattern: str, replacement: str, content: str) -> str:
    updated, count = re.subn(pattern, replacement, content, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"pattern not found: {pattern}")
    return updated


def main() -> None:
    args = parse_args()
    content = args.cask_file.read_text(encoding="utf-8")
    content = replace_once(r'^  version ".*"$', f'  version "{args.version}"', content)
    content = replace_once(r'^  sha256 ".*"$', f'  sha256 "{args.sha256}"', content)
    args.cask_file.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
