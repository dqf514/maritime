"""Prometheus 文本指标（3.7 可观测性）。

仅聚合进程级计数，不含租户数据；供内网抓取。鉴权由网关层控制。
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.services.observability import render_prometheus

router = APIRouter(tags=["Observability"])


@router.get("/metrics")
def metrics() -> Response:
    return Response(content=render_prometheus(), media_type="text/plain; version=0.0.4")
