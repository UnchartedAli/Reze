# syntax=docker/dockerfile:1

# ========================================================
#  Reze Telegram Userbot & Web Control Panel
#  Developer: UnchartedAli  -  Channel: @yamods
# ========================================================
FROM python:3.12-slim

LABEL org.opencontainers.image.title="Reze Telegram Userbot"
LABEL org.opencontainers.image.description="Advanced Telegram userbot & web control panel by UnchartedAli (@yamods)"
LABEL org.opencontainers.image.authors="UnchartedAli"
LABEL org.opencontainers.image.url="https://t.me/yamods"
LABEL org.opencontainers.image.version="2.0.0"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    REZE_WEB_HOST=0.0.0.0 \
    REZE_DATA_DIR=/app/data

WORKDIR /app

# gosu lets the entrypoint fix ownership of a mounted volume, then drop root.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates gosu tzdata ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin reze

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=reze:reze . .
COPY --chown=root:root deploy/docker-entrypoint.sh /usr/local/bin/reze-entrypoint
RUN sed -i 's/\r$//' /usr/local/bin/reze-entrypoint \
    && chmod 0755 /usr/local/bin/reze-entrypoint \
    && mkdir -p /app/data \
    && chown -R reze:reze /app/data

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD ["python", "scripts/healthcheck.py"]

ENTRYPOINT ["/usr/local/bin/reze-entrypoint"]
CMD ["python", "-m", "reze.app"]

