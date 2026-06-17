#!/usr/bin/env python3
"""合并 backend/storage 与仓库根 storage，避免 Docker bind mount 路径不一致导致登录态丢失。"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BASE_DIR.parent
LEGACY_DIR = BASE_DIR / "storage"
TARGET_DIR = Path(os.environ.get("STORAGE_ROOT", str(ROOT_DIR / "storage"))).resolve()


def _copy_tree(src: Path, dst: Path) -> int:
    copied = 0
    if not src.exists():
        return copied
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        target = dst / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    return copied


def main() -> int:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    if LEGACY_DIR.resolve() != TARGET_DIR and LEGACY_DIR.exists():
        copied += _copy_tree(LEGACY_DIR, TARGET_DIR)
    repo_storage = ROOT_DIR / "storage"
    if repo_storage.resolve() != TARGET_DIR and repo_storage.exists():
        copied += _copy_tree(repo_storage, TARGET_DIR)
    print(f"[storage-migrate] target={TARGET_DIR} copied_files={copied}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
