# Build context must be the `mos/` directory (fixtures live at mos/fixtures and
# checks/registry.py resolves them via parents[3]):
#   docker build -f apps/api/Dockerfile -t marios-api mos/
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

WORKDIR /srv/mos/apps/api

COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

# Repo layout preserved so checks/registry.py finds mos/fixtures
COPY apps/api/app ./app
COPY apps/api/checks ./checks
COPY fixtures /srv/mos/fixtures

ENV PYTHONPATH=/srv/mos/apps/api \
    PYTHONUNBUFFERED=1

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
