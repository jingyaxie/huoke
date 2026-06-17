#!/usr/bin/env python3
"""分步实测：搜索 → 抓评论 → 回复 → 关注 → 私信（抖音）。

用法:
  python scripts/test_shower_room_steps.py --step 1   # 仅搜索
  python scripts/test_shower_room_steps.py --step 2   # 抓评论（需 step1 状态）
  python scripts/test_shower_room_steps.py --step 3   # 回复「同意」
  python scripts/test_shower_room_steps.py --step 4   # 关注
  python scripts/test_shower_room_steps.py --step 5   # 私信
  python scripts/test_shower_room_steps.py --all      # 连续跑 1-5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.platforms.douyin.comments import DouyinCommentCrawler
from app.platforms.douyin.dm import DouyinDmTool
from app.platforms.douyin.follow import DouyinFollowTool
from app.platforms.douyin.js_constants import _extract_aweme_id
from app.platforms.douyin.session import DouyinSessionStore
from app.services.comment_reply_service import CommentReplyService
from app.services.playwright_pool import PlaywrightPool
from app.services.supervisor_outreach import persist_crawl_skill_result

KEYWORD = "上海淋浴房"
REPLY_TEXT = "同意"
DM_TEXT = "你好，想了解一下淋浴房"
TENANT_ID = "default"
ACCOUNT_ID = "default"
STATE_PATH = Path("storage/dev/test_shower_room_state.json")


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _pick_comment_user(payload: dict) -> dict | None:
    for row in payload.get("comments") or []:
        if not isinstance(row, dict):
            continue
        sec_uid = str(row.get("sec_uid") or "").strip()
        user_id = str(row.get("user_id") or "").strip()
        comment_id = str(row.get("comment_id") or "").strip()
        if sec_uid and user_id and comment_id:
            return {
                "comment_id": comment_id,
                "user_id": user_id,
                "sec_uid": sec_uid,
                "username": str(row.get("username") or row.get("nickname") or "").strip(),
                "comment_text": str(row.get("comment") or row.get("text") or "").strip(),
            }
    return None


async def step_search(state: dict, *, timeout_s: int) -> dict:
    settings = get_settings()
    crawler = DouyinCommentCrawler(settings, TENANT_ID, DouyinSessionStore(settings), account_id=ACCOUNT_ID)
    report: dict = {"step": 1, "name": "search", "keyword": KEYWORD, "ok": False}
    t0 = time.time()
    pool = PlaywrightPool.get()
    try:
        async with pool.tenant_context(
            "douyin", TENANT_ID, crawler.store, settings, headless=False, account_id=ACCOUNT_ID
        ) as (_, page):
            captured: list[str] = []

            def on_response(resp) -> None:
                if "/aweme/v1/web/" in resp.url:
                    captured.append(resp.url)

            page.on("response", on_response)
            urls, diagnostic, template = await asyncio.wait_for(
                crawler._search.keyword_search(
                    page,
                    keyword=KEYWORD,
                    limit=3,
                    captured_api_urls=captured,
                    headless=False,
                    manual_search=False,
                ),
                timeout=timeout_s,
            )
            page.remove_listener("response", on_response)
            report.update(
                {
                    "elapsed_s": round(time.time() - t0, 2),
                    "diagnostic": diagnostic,
                    "video_urls": urls,
                    "template_preview": (template or "")[:160],
                    "captured_apis": len(captured),
                    "page_url": page.url,
                    "ok": bool(urls),
                }
            )
            if urls:
                state["keyword"] = KEYWORD
                state["video_url"] = urls[0]
                state["aweme_id"] = _extract_aweme_id(urls[0])
                state["search_template"] = template
                _save_state(state)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["trace"] = traceback.format_exc()[-1500:]
    return report


async def step_crawl_comments(state: dict, *, timeout_s: int) -> dict:
    video_url = str(state.get("video_url") or "").strip()
    template = str(state.get("search_template") or "").strip()
    aweme_id = str(state.get("aweme_id") or "").strip()
    if not video_url or not aweme_id:
        return {"step": 2, "name": "crawl_comments", "ok": False, "error": "缺少 step1 状态，请先跑 --step 1"}

    settings = get_settings()
    crawler = DouyinCommentCrawler(settings, TENANT_ID, DouyinSessionStore(settings), account_id=ACCOUNT_ID)
    report: dict = {"step": 2, "name": "crawl_comments", "video_url": video_url, "ok": False}
    t0 = time.time()
    db = SessionLocal()
    pool = PlaywrightPool.get()
    try:
        async with pool.tenant_context(
            "douyin", TENANT_ID, crawler.store, settings, headless=False, account_id=ACCOUNT_ID
        ) as (_, page):
            payload = await asyncio.wait_for(
                crawler._comments._fetch_comments_from_api(
                    page,
                    aweme_id,
                    video_url,
                    template,
                    max_comments=30,
                ),
                timeout=timeout_s,
            )
            payload["platform"] = "douyin"
            payload["keyword_context"] = {"keyword": KEYWORD}
            persisted = persist_crawl_skill_result(
                db,
                settings,
                tenant_id=TENANT_ID,
                platform="douyin",
                skill_result={
                    "results": [payload],
                    "total_comments_captured": payload.get("total_comments_captured", 0),
                },
                source_keyword=KEYWORD,
            )
            db.commit()
            target = _pick_comment_user(payload)
            report.update(
                {
                    "elapsed_s": round(time.time() - t0, 2),
                    "capture_method": payload.get("capture_method"),
                    "total_comments_captured": payload.get("total_comments_captured"),
                    "persisted_rows": persisted,
                    "ok": bool(target),
                }
            )
            if target:
                state.update(
                    {
                        "comment_id": target["comment_id"],
                        "user_id": target["user_id"],
                        "sec_uid": target["sec_uid"],
                        "username": target["username"],
                        "target_comment_text": target["comment_text"],
                    }
                )
                _save_state(state)
                report["target_user"] = target
            else:
                report["error"] = "未找到含 sec_uid/user_id 的评论，无法继续触达测试"
    except Exception as exc:
        db.rollback()
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["trace"] = traceback.format_exc()[-1500:]
    finally:
        db.close()
    return report


async def step_reply(state: dict, *, timeout_s: int) -> dict:
    comment_id = str(state.get("comment_id") or "").strip()
    if not comment_id:
        return {"step": 3, "name": "reply_comment", "ok": False, "error": "缺少 comment_id，请先跑 --step 2"}

    settings = get_settings()
    db = SessionLocal()
    report: dict = {
        "step": 3,
        "name": "reply_comment",
        "comment_id": comment_id,
        "reply_text": REPLY_TEXT,
        "ok": False,
    }
    t0 = time.time()
    try:
        service = CommentReplyService(
            settings,
            tenant_id=TENANT_ID,
            platform="douyin",
            session=db,
            account_id=ACCOUNT_ID,
        )
        result = await asyncio.wait_for(
            service.reply_comment(
                comment_id=comment_id,
                reply_text=REPLY_TEXT,
                show_browser=False,
            ),
            timeout=timeout_s,
        )
        report.update(
            {
                "elapsed_s": round(time.time() - t0, 2),
                "status": result.get("status"),
                "capture_method": result.get("capture_method"),
                "content_url": result.get("content_url"),
                "error": result.get("error"),
                "ok": result.get("status") == "completed",
            }
        )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["trace"] = traceback.format_exc()[-1500:]
    finally:
        db.close()
    return report


async def step_follow(state: dict, *, timeout_s: int) -> dict:
    sec_uid = str(state.get("sec_uid") or "").strip()
    user_id = str(state.get("user_id") or "").strip()
    username = str(state.get("username") or "").strip()
    if not sec_uid or not user_id:
        return {"step": 4, "name": "follow_user", "ok": False, "error": "缺少用户 ID，请先跑 --step 2"}

    settings = get_settings()
    tool = DouyinFollowTool(settings, TENANT_ID, account_id=ACCOUNT_ID)
    report: dict = {"step": 4, "name": "follow_user", "sec_uid": sec_uid, "user_id": user_id, "ok": False}
    t0 = time.time()
    try:
        result = await asyncio.wait_for(
            tool.follow_user(sec_uid=sec_uid, user_id=user_id, username=username, show_browser=False),
            timeout=timeout_s,
        )
        follow = result.get("follow") or {}
        report.update(
            {
                "elapsed_s": round(time.time() - t0, 2),
                "username": result.get("username"),
                "follow_status_before": result.get("follow_status_before"),
                "follow_status_after": result.get("follow_status_after"),
                "follow": follow,
                "ok": bool(follow.get("ok")),
                "error": follow.get("error") or follow.get("reason"),
            }
        )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["trace"] = traceback.format_exc()[-1500:]
    return report


async def step_dm(state: dict, *, timeout_s: int) -> dict:
    sec_uid = str(state.get("sec_uid") or "").strip()
    username = str(state.get("username") or "").strip()
    if not sec_uid:
        return {"step": 5, "name": "send_dm", "ok": False, "error": "缺少 sec_uid，请先跑 --step 2"}

    settings = get_settings()
    tool = DouyinDmTool(settings, TENANT_ID, account_id=ACCOUNT_ID)
    message = f"{DM_TEXT}（测试 {datetime.now().strftime('%H:%M:%S')}）"
    report: dict = {"step": 5, "name": "send_dm", "sec_uid": sec_uid, "message": message, "ok": False}
    t0 = time.time()
    try:
        result = await asyncio.wait_for(
            tool.send_message(sec_uid=sec_uid, message=message, username=username, show_browser=False),
            timeout=timeout_s,
        )
        dm = result.get("message") or {}
        report.update(
            {
                "elapsed_s": round(time.time() - t0, 2),
                "username": result.get("username"),
                "dm": dm,
                "ok": bool(dm.get("ok")),
                "error": dm.get("error") or dm.get("hint"),
            }
        )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["trace"] = traceback.format_exc()[-1500:]
    return report


STEPS = {
    1: ("搜索", step_search),
    2: ("抓评论", step_crawl_comments),
    3: ("回复评论", step_reply),
    4: ("关注", step_follow),
    5: ("私信", step_dm),
}


async def main() -> int:
    parser = argparse.ArgumentParser(description="上海淋浴房分步实测")
    parser.add_argument("--step", type=int, choices=[1, 2, 3, 4, 5], help="只跑指定步骤")
    parser.add_argument("--all", action="store_true", help="连续跑 1-5")
    parser.add_argument("--timeout", type=int, default=180, help="单步超时秒数")
    args = parser.parse_args()

    if not args.step and not args.all:
        parser.error("请指定 --step N 或 --all")

    state = _load_state()
    steps_to_run = list(range(1, 6)) if args.all else [args.step]
    exit_code = 0
    summary: list[dict] = []

    for n in steps_to_run:
        label, fn = STEPS[n]
        print(f"\n{'='*60}\nSTEP {n}: {label} | keyword={KEYWORD}\n{'='*60}", flush=True)
        report = await fn(state, timeout_s=args.timeout)
        summary.append(report)
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        if not report.get("ok"):
            exit_code = 1
            if args.all:
                print(f"\n步骤 {n} 失败，停止后续步骤。", flush=True)
                break
        state = _load_state()

    print(f"\n状态文件: {STATE_PATH.resolve()}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
