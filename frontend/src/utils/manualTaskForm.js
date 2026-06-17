const PROFILE_URL_PATTERNS = {
  douyin: [/douyin\.com\/user\//i, /iesdouyin\.com\/share\/user\//i, /v\.douyin\.com\/[\w-]+/i],
  xiaohongshu: [/xiaohongshu\.com\/user\/profile\//i, /xhslink\.com\//i],
  kuaishou: [/kuaishou\.com\/profile\//i, /v\.kuaishou\.com\//i],
};

const VIDEO_URL_PATTERNS = {
  douyin: [/douyin\.com\/video\//i, /iesdouyin\.com\/share\/video\//i],
  xiaohongshu: [/xiaohongshu\.com\/explore\//i, /xiaohongshu\.com\/discovery\/item\//i, /xhslink\.com\//i],
  kuaishou: [/kuaishou\.com\/short-video\//i, /v\.kuaishou\.com\/short\//i],
};

export function deriveManualTaskName(inputUrl, intent) {
  const mode = intent === "account_home" ? "home_manual" : "video_manual";
  const trimmed = String(inputUrl || "").trim();
  if (!trimmed) {
    return mode === "home_manual" ? "博主主页获客" : "单视频获客";
  }
  try {
    const url = new URL(trimmed);
    const slug = decodeURIComponent(url.pathname.split("/").filter(Boolean).pop() || "").slice(0, 24);
    if (slug) {
      return mode === "home_manual" ? `博主-${slug}` : `视频-${slug}`;
    }
  } catch {
    /* ignore */
  }
  return mode === "home_manual" ? "博主主页获客" : "单视频获客";
}

export function validateManualTaskUrl(inputUrl, intent, platform) {
  const mode = intent === "account_home" ? "home_manual" : "video_manual";
  const trimmed = String(inputUrl || "").trim();
  if (!trimmed) {
    return mode === "home_manual" ? "请粘贴博主主页链接" : "请粘贴视频详情页链接";
  }
  try {
    // eslint-disable-next-line no-new
    new URL(trimmed);
  } catch {
    return "链接格式不正确，请粘贴完整的 http/https 地址";
  }
  const patterns = mode === "home_manual"
    ? PROFILE_URL_PATTERNS[platform] || []
    : VIDEO_URL_PATTERNS[platform] || [];
  if (!patterns.some((re) => re.test(trimmed))) {
    return mode === "home_manual"
      ? "请粘贴博主账号主页链接（非单条视频链接）"
      : "请粘贴单条视频详情页链接";
  }
  return null;
}
