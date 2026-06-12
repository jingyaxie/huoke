from __future__ import annotations

import json
from pathlib import Path

from app.schemas.skill import BUILTIN_HANDLERS


def test_global_skills_has_core_builtin_handlers():
    path = Path(__file__).resolve().parents[1] / "storage" / "skills" / "global.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    handlers = {item.get("builtin_handler") for item in payload.get("skills", [])}
    for required in (
        "follow_user",
        "send_dm",
        "pipeline_keyword_comments",
        "crawl_keyword_comments",
    ):
        assert required in handlers


def test_builtin_handlers_registry_matches_code():
    assert "pipeline_keyword_comments" in BUILTIN_HANDLERS
    assert "follow_user" in BUILTIN_HANDLERS
