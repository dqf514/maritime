# Build context must be the `mos/` directory (fixtures live at mos/fixtures and
# checks/registry.py resolves them via parents[3]):
#   docker build -f apps/api/Dockerfile -t marios-api mos/
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

WORKDIR /srv/mos/apps/api

COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

# P0-8: 镜像内必须带 Alembic 与迁移目录 —— 否则生产库永远拿不到新列
# （create_all 只建缺失的表，从不 ALTER 已有表）。
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini ./alembic.ini

# Repo layout preserved so checks/registry.py finds mos/fixtures
COPY apps/api/app ./app
COPY apps/api/checks ./checks
COPY fixtures /srv/mos/fixtures

# P1-10: Chromium 必须真的装进镜像。app/services/doc_engine.py 的
# pdf_available() 只检查 Python 包在不在，浏览器二进制缺失时它照样返回
# "可用"，实际渲染必失败。PLAYWRIGHT_BROWSERS_PATH 固定到全局目录，
# 否则浏览器只会装到 root 的 ~/.cache 里，appuser 读不到。
# 浏览器下载源默认走 npmmirror（国内可达）；换官方源：
#   docker build --build-arg PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.playwright.dev ...
ARG PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_DOWNLOAD_HOST=${PLAYWRIGHT_DOWNLOAD_HOST}
RUN python -m playwright install --with-deps chromium \
    && mkdir -p /srv/mos/apps/api/app/data /srv/mos/apps/api/uploads \
    && chown -R appuser:appuser /srv/mos

ENV PYTHONPATH=/srv/mos/apps/api \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    ALEMBIC_CONFIG=/srv/mos/apps/api/alembic.ini

USER appuser
EXPOSE 8000

# P1-3: 探针用 /readyz（探依赖），/healthz 只探进程存活。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/readyz || exit 1

# P0-12: 反向代理后必须信任 X-Forwarded-For，否则 request.client.host 恒为
# 反代容器 IP —— 全站共用一个限流桶（登录 5 次/分钟全局）。
#   TRUSTED_PROXY_IPS="*"            —— compose 内网反代（默认）
#   TRUSTED_PROXY_IPS="172.16.0.0/12" —— 收紧到反代网段
# shell 形式以便展开环境变量；exec 让 uvicorn 成为 1 号进程（能收到 SIGTERM
# 优雅停机）；--timeout-graceful-shutdown 给长请求（报表/导出）收尾时间。
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${TRUSTED_PROXY_IPS:-*}\" --timeout-graceful-shutdown 30"]
