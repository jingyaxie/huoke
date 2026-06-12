# 业务层：基于已构建的依赖镜像，仅 COPY 代码（秒级构建，便于单独上传）
ARG BASE_IMAGE=douyin-backend-base:py312
FROM ${BASE_IMAGE}

WORKDIR /app

COPY . /app
RUN chmod +x /app/scripts/docker-entrypoint.sh /app/scripts/install-cjk-fonts.sh \
    && mkdir -p /root/.fluxbox \
    && cp /app/scripts/fluxbox/init /root/.fluxbox/init

EXPOSE 8000
EXPOSE 6080

CMD ["/app/scripts/docker-entrypoint.sh"]
