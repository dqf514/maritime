"""3.7 可观测性：/metrics 聚合指标 + 慢查询计数。"""

from __future__ import annotations


def test_metrics_endpoint_counts_requests(client):
    from app.services.observability import METRICS

    before = METRICS["http_requests_total"]
    r = client.get("/api/v1/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert "http_requests_total" in body
    assert "http_5xx_total" in body
    assert "slow_queries_total" in body
    # 指标请求本身也被计入
    assert METRICS["http_requests_total"] >= before + 1


def test_metrics_no_tenant_data_leak(client, auth_headers):
    r = client.get("/api/v1/metrics", headers=auth_headers)
    # 只含聚合计数，不出现任何路径/租户信息
    assert "demo" not in r.text
    assert "/api/v1/invoices" not in r.text


def test_slow_query_log_counts(monkeypatch):
    from app.services import observability as obs

    obs.install_slow_query_log(0.0)  # 阈值 0 → 任何语句都计
    base = obs.METRICS["slow_queries_total"]

    from sqlalchemy import create_engine, text

    eng = create_engine("sqlite+pysqlite:///:memory:")
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
    assert obs.METRICS["slow_queries_total"] >= base + 1
