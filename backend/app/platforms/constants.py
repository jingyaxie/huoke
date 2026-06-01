DEFAULT_PLATFORM = "douyin"

SUPPORTED_PLATFORMS = frozenset({"douyin", "xiaohongshu", "kuaishou", "huoshan"})

# 账号绑定支持的平台（不含已弃用的 huoshan 火山版）
BINDABLE_PLATFORMS = frozenset({"douyin", "xiaohongshu", "kuaishou"})

PLATFORM_LABELS = {
    "douyin": "抖音",
    "xiaohongshu": "小红书",
    "kuaishou": "快手",
    "huoshan": "抖音火山版",
}
