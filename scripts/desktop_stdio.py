"""Safe stdout/stderr helpers when Python runs under Windows pipe redirection."""
from __future__ import annotations

import os
import sys


def configure_pipe_stdio() -> None:
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (OSError, ValueError, AttributeError):
            pass


def log_line(message: str, *, err: bool = False) -> None:
    """Write a log line without raising on broken pipe / flush errors."""
    targets = (sys.stderr, sys.stdout) if err else (sys.stdout, sys.stderr)
    for target in targets:
        if target is None:
            continue
        try:
            print(message, file=target)
            return
        except OSError:
            continue
