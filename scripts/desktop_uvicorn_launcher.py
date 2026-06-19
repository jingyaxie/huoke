#!/usr/bin/env python3
"""Desktop backend entry: unified preflight + uvicorn in one Python process."""
from __future__ import annotations

import argparse
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from desktop_stdio import configure_pipe_stdio, log_line


def _register_windows_dll_dirs() -> None:
    try:
        import portable_dll_bootstrap

        portable_dll_bootstrap.bootstrap_portable_python_dlls(heal_layout=True)
        return
    except Exception:
        pass
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
    for candidate in candidates:
        if not os.path.isdir(candidate):
            continue
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(candidate)
            except OSError:
                pass
    if os.environ.get("HUOKE_DLL_BOOTSTRAP_DONE") != "1":
        path_prefix = [p for p in candidates if os.path.isdir(p)]
        if path_prefix:
            existing = os.environ.get("PATH", "")
            os.environ["PATH"] = ";".join(path_prefix + ([existing] if existing else []))
        os.environ["HUOKE_DLL_BOOTSTRAP_DONE"] = "1"


def run_lifespan_smoke(app: object) -> None:
    import asyncio

    async def _run() -> None:
        async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
            pass

    asyncio.run(_run())


def run_preflight(*, include_lifespan: bool = False) -> object:
    configure_pipe_stdio()
    _register_windows_dll_dirs()
    log_line(f"preflight: python {sys.version.split()[0]}")

    import greenlet  # noqa: F401
    from greenlet._greenlet import _C_API  # noqa: F401

    log_line("greenlet ok")
    import cryptography  # noqa: F401

    log_line("cryptography ok")
    import pydantic_core  # noqa: F401

    log_line("pydantic_core ok")
    from playwright.async_api import async_playwright  # noqa: F401

    log_line("playwright ok")
    from app.db.bootstrap import ensure_database_schema
    from app.main import app

    log_line("app.main ok")
    ensure_database_schema()
    log_line("database schema ready")
    if include_lifespan:
        run_lifespan_smoke(app)
        log_line("lifespan ok")
    log_line("preflight unified ok")
    return app


def main() -> int:
    configure_pipe_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    try:
        app = run_preflight(include_lifespan=args.check_only)
    except Exception as exc:
        log_line(f"preflight failed: {type(exc).__name__}: {exc}", err=True)
        import traceback

        try:
            traceback.print_exc()
        except OSError:
            pass
        return 1

    if args.check_only:
        return 0

    import uvicorn

    log_line(f"starting uvicorn on port {args.port}")
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
    except SystemExit as exc:
        code = exc.code
        if code in (0, None):
            return 0
        return int(code) if isinstance(code, int) else 1
    except Exception as exc:
        log_line(f"uvicorn failed: {type(exc).__name__}: {exc}", err=True)
        import traceback

        try:
            traceback.print_exc()
        except OSError:
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
