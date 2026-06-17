from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.desktop_static import mount_desktop_frontend


def test_desktop_spa_serves_index_for_auto_tasks(tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><html><body>ok</body></html>", encoding="utf-8")

    app = FastAPI()
    mount_desktop_frontend(app, dist)
    client = TestClient(app)

    root = client.get("/")
    assert root.status_code == 200
    assert "text/html" in root.headers.get("content-type", "")
    assert "ok" in root.text

    spa = client.get("/auto-tasks")
    assert spa.status_code == 200
    assert "text/html" in spa.headers.get("content-type", "")
    assert "ok" in spa.text
