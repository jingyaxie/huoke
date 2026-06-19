#!/usr/bin/env python3
"""Desktop backend entry: unified preflight + uvicorn in one Python process."""
from __future__ import annotations

import argparse
import os
import sys


def _register_windows_dll_dirs() -> None:
    if os.name != "nt":
        return
    exe = os.path.abspath(sys.executable)
    base = os.path.dirname(exe)
    runtime_root = os.path.dirname(base)
    candidates = [
        base,
        os.path.join(base, "DLLs"),
        os.path.join(runtime_root, "msvc"),
    ]
    site_packages = os.path.join(base, "Lib", "site-packages")
    if os.path.isdir(site_packages):
        for name in os.listdir(site_packages):
            pkg_dir = os.path.join(site_packages, name)
            if os.path.isdir(pkg_dir):
                candidates.append(pkg_dir)

    path_prefix: list[str] = []
    for candidate in candidates:
        if not os.path.isdir(candidate):
            continue
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(candidate)
            except OSError:
                pass
        path_prefix.append(candidate)
    if path_prefix:
        os.environ["PATH"] = ";".join(path_prefix + [os.environ.get("PATH", "")])


def run_preflight() -> object:
    _register_windows_dll_dirs()
    print("preflight: python", sys.version.split()[0], flush=True)

    import greenlet  # noqa: F401
    from greenlet._greenlet import _C_API  # noqa: F401

    print("greenlet ok", flush=True)
    import cryptography  # noqa: F401

    print("cryptography ok", flush=True)
    import pydantic_core  # noqa: F401

    print("pydantic_core ok", flush=True)
    from playwright.async_api import async_playwright  # noqa: F401

    print("playwright ok", flush=True)
    from app.db.bootstrap import ensure_database_schema
    from app.main import app

    print("app.main ok", flush=True)
    ensure_database_schema()
    print("database schema ready", flush=True)
    print("preflight unified ok", flush=True)
    return app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    try:
        app = run_preflight()
    except Exception as exc:
        print(f"preflight failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1

    if args.check_only:
        return 0

    import uvicorn

    print(f"starting uvicorn on port {args.port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
