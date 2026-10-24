"""Prometheus 文本指标（3.7 可观测性）。

仅聚合进程级计数，不含租户数据。

**鉴权（P2 · 「/metrics 无鉴权」）**：指标里含 QPS、错误率、慢查询条数，属于
运维信息，匿名公网可读等于把系统运行状况白送。规则：

- ``METRICS_TOKEN`` 已配置 → 必须带 ``Authorization: Bearer <token>`` 或
  ``X-Metrics-Token: <token>``（常量时间比较）；
- ``METRICS_TOKEN`` 未配置且 ``ENV=production`` → **端点直接不存在**（404），
  宁可监控拿不到数据，也不把指标裸奔在公网上；
- 未配置且非生产 → 放行（本地开发/Prometheus 内网抓取），但每次访问记一条
  告警，提醒部署时补上 token。
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Response

from app.config import get_settings
from app.services.observability import render_prometheus

log = logging.getLogger("marios.metrics")

router = APIRouter(tags=["Observability"])


def _assert_metrics_allowed(authorization: str | None, metrics_token: str | None) -> None:
    settings = get_settings()
    token = (settings.metrics_token or "").strip()
    if not token:
        if settings.env == "production":
            # 生产环境没配 token → 端点不存在（不泄露"存在但没保护"这一信息）
            raise HTTPException(status_code=404, detail="Not found")
        log.warning(
            "/metrics 未配置 METRICS_TOKEN —— 当前环境放行匿名抓取，生产部署前必须补上"
        )
        return
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    elif metrics_token:
        supplied = metrics_token.strip()
    if not supplied or not hmac.compare_digest(supplied, token):
        raise HTTPException(status_code=401, detail="Invalid metrics token")


@router.get("/metrics")
def metrics(
    response: Response,
    authorization: str | None = Header(default=None),
    x_metrics_token: str | None = Header(default=None, alias="X-Metrics-Token"),
):
    _assert_metrics_allowed(authorization, x_metrics_token)
    return Response(content=render_prometheus(), media_type="text/plain; version=0.0.4")
