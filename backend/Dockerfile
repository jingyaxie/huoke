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
    wget \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
RUN playwright install chromium

FROM backend-base AS backend-app

COPY . /app
RUN chmod +x /app/scripts/docker-entrypoint.sh /app/scripts/install-cjk-fonts.sh

EXPOSE 8000
EXPOSE 6080

CMD ["/app/scripts/docker-entrypoint.sh"]
