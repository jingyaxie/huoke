from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles


def mount_desktop_frontend(app: FastAPI, dist_dir: Path) -> None:
    """Desktop 模式：由 FastAPI 托管前端静态资源，与 /api 同源。"""
    dist = dist_dir.resolve()
    if not dist.is_dir():
        return

    assets_dir = dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="desktop-assets")

    index_file = dist / "index.html"

    @app.get("/", include_in_schema=False)
    async def desktop_index() -> FileResponse:
        if not index_file.is_file():
            raise HTTPException(status_code=404, detail="frontend index missing")
        return FileResponse(index_file)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def desktop_spa(full_path: str) -> FileResponse:
        if full_path.startswith("api") or full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = dist / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        if not index_file.is_file():
            raise HTTPException(status_code=404, detail="frontend index missing")
        return FileResponse(index_file)
