from __future__ import annotations

import os
import sys

from app.core.antibot import launch_args


def test_visible_linux_launch_args_include_subpixel_fix(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":99")
    args = launch_args(headless=False)
    assert "--disable-font-subpixel-positioning" in args
    assert "--disable-gpu" in args
    assert "--disable-gpu-compositing" in args
    assert "VizDisplayCompositor" in " ".join(args)


def test_headless_launch_args_skip_vnc_render(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":99")
    args = launch_args(headless=True)
    assert "--disable-font-subpixel-positioning" not in args


def test_visible_without_display_skips_vnc_render(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    args = launch_args(headless=False)
    assert "--disable-font-subpixel-positioning" not in args
