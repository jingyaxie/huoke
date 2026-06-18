#!/usr/bin/env python3
"""CI / build smoke test: bundled Playwright Chromium can launch."""
from __future__ import annotations

import os
import sys


def main() -> int:
    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if browsers_path and not os.path.isdir(browsers_path):
        print(f"PLAYWRIGHT_BROWSERS_PATH is not a directory: {browsers_path}", file=sys.stderr)
        return 1

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        browser.close()

    print("playwright chromium launch ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
