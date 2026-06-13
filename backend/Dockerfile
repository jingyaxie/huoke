FROM python:3.12-slim AS backend-base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    x11vnc \
    novnc \
    websockify \
    fluxbox \
    feh \
    x11-utils \
    libglib2.0-0t64 \
    libcairo2 \
    libpango-1.0-0 \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0t64 \
    libatk-bridge2.0-0t64 \
    libcups2t64 \
    libdrm2 \
    libxkbcommon0 \
    libatspi2.0-0t64 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libx11-6 \
    libasound2t64 \
    libxext6 \
    libxshmfence1 \
    ca-certificates \
    fonts-liberation \
    fontconfig \
    fonts-wqy-microhei \
    fonts-wqy-zenhei \
    fonts-noto-cjk \
    wget \
    curl \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
# BuildKit 缓存 pip 下载；镜像内仍不保留 pip cache（减小体积）
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /app/requirements.txt
# Playwright 浏览器写入镜像层；不用 cache mount（buildx 并发会触发 __dirlock 失败）
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install chromium \
    && (playwright install chrome || true)

FROM backend-base AS backend-app

COPY . /app
RUN chmod +x /app/scripts/docker-entrypoint.sh /app/scripts/install-cjk-fonts.sh \
    && mkdir -p /root/.fluxbox \
    && cp /app/scripts/fluxbox/init /root/.fluxbox/init

EXPOSE 8000
EXPOSE 6080

CMD ["/app/scripts/docker-entrypoint.sh"]
