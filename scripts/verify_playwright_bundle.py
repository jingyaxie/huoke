#!/usr/bin/env python3
"""CI / build smoke test: bundled Playwright Chromium is present and launchable."""
from __future__ import annotations

import glob
import os
import sys


def _has_full_chromium(browsers_path: str) -> bool:
    patterns = [
        os.path.join(browsers_path, "chromium-*", "chrome-win64", "chrome.exe"),
        os.path.join(browsers_path, "chromium-*", "chrome-mac", "Chromium.app"),
        os.path.join(browsers_path, "chromium-*", "chrome-linux", "chrome"),
    ]
    return any(glob.glob(pattern) for pattern in patterns)


def _has_headless_shell(browsers_path: str) -> bool:
    patterns = [
        os.path.join(browsers_path, "chromium_headless_shell-*", "chrome-headless-shell-win64", "chrome-headless-shell.exe"),
        os.path.join(browsers_path, "chromium_headless_shell-*", "chrome-headless-shell-mac-*", "headless_shell"),
        os.path.join(browsers_path, "chromium_headless_shell-*", "chrome-headless-shell-linux64", "headless_shell"),
    ]
    return any(glob.glob(pattern) for pattern in patterns)


def main() -> int:
    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if not browsers_path:
        print("PLAYWRIGHT_BROWSERS_PATH is not set", file=sys.stderr)
        return 1
    if not os.path.isdir(browsers_path):
        print(f"PLAYWRIGHT_BROWSERS_PATH is not a directory: {browsers_path}", file=sys.stderr)
        return 1

    if not _has_full_chromium(browsers_path):
        print(f"Full Chromium browser missing under {browsers_path} (needed for headed desktop)", file=sys.stderr)
        return 1
    print("full chromium bundle ok")

    if not _has_headless_shell(browsers_path):
        print(f"Chromium headless shell missing under {browsers_path}", file=sys.stderr)
        return 1
    print("chromium headless shell bundle ok")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        browser.close()

    print("playwright chromium launch ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
