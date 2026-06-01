from __future__ import annotations

import re

PLATFORM = "huoshan"

# 火山版与抖音 Web 共用 sessionid 等 Cookie；独立 Web 热榜不存在，热榜走 entry_url 兜底。
REQUIRED_LOGIN_COOKIES = {"sessionid", "sessionid_ss", "sid_tt", "sid_guard", "uid_tt", "uid_tt_ss"}

ITEM_ID_PATTERN = re.compile(
    r"(?:item_id=|aweme_id=|/video/)(\d{8,22})"
)
SHARE_SHORT_PATTERN = re.compile(r"share\.huoshan\.com/hotsoon/s/([A-Za-z0-9_-]+)")

COMMENT_PATH = "/aweme/v1/web/comment/list"
SEARCH_API_HINT = "/aweme/v1/web/"
USER_POST_PATH = "/aweme/v1/web/aweme/post/"
USER_PROFILE_URL = "https://www.douyin.com/user/{sec_uid}"

HOT_MODE_SEED_THEN_FALLBACK = "seed_then_fallback"
HOT_MODE_SEED_ONLY = "seed_only"
HOT_MODE_DOUYIN_ONLY = "douyin_only"

# api.huoshan.com reflow 在部分网络环境 502，播放/评论统一走抖音 Web 页。
WEB_VIDEO_URL = "https://www.douyin.com/video/{item_id}"
REFLOW_URL = "https://api.huoshan.com/hotsoon/item/video/_reflow/?item_id={item_id}"
