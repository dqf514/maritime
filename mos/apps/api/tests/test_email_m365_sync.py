"""邮件复核 × Microsoft 365：Graph 收件箱落库到复核管线 + 关键词关联检索。

- provider=microsoft 的邮箱账户：地址可省略（从 Graph /me 解析），同步走真实/stub Graph
- 同步落库 EmailMessage：业务邮件（NOR/recap/SOF）进 review 队列，普通邮件直接 parsed
- 按 Graph message id 去重（重复同步 synced=0）
- Graph 不可用 → 502 GRAPH_SYNC_FAILED（不 500）
- GET /email/related：逗号分隔关键词 OR 匹配主题/正文（业务页面附属邮件面板的数据源）
"""

from __future__ import annotations

from app.services.graph_client import GraphClient, GraphError


def _stub_graph(monkeypatch):
    monkeypatch.setattr(
        "app.services.office_hub.get_graph_client",
        lambda db, tenant_id: GraphClient("stub-token", mode="stub"),
    )


def test_m365_account_created_and_synced_into_review(client, auth_headers, monkeypatch):
    _stub_graph(monkeypatch)
    API = "/api/v1"

    # 无 email → 服务端从 Graph /me 解析邮箱地址
    r = client.post(
        f"{API}/email/accounts",
        headers=auth_headers,
        json={"provider": "microsoft", "display_name": "M365 Inbox", "config": {}},
    )
    assert r.status_code == 200, r.text
    acc = r.json()
    assert acc["email"] == "demo@contoso.onmicrosoft.com"

    # 同步 stub 收件箱：2 封样例邮件，NOR 进 review 队列
    s = client.post(f"{API}/email/accounts/{acc['id']}/sync", headers=auth_headers)
    assert s.status_code == 200, s.text
    body = s.json()
    assert body["synced"] == 2
    assert body["review_queue"] == 1
    assert body["provider"] == "microsoft"

    rv = client.get(f"{API}/email/review", headers=auth_headers)
    assert rv.status_code == 200
    nor = [m for m in rv.json() if "NOR" in (m["subject"] or "")]
    assert nor and nor[0]["parse_status"] == "review"

    # 重复同步按 Graph message id 去重
    s2 = client.post(f"{API}/email/accounts/{acc['id']}/sync", headers=auth_headers)
    assert s2.status_code == 200
    assert s2.json()["synced"] == 0

    # 全部邮件可检索（FIRM OFFER 作为 general 存为 parsed）
    msgs = client.get(f"{API}/email/messages", headers=auth_headers).json()
    assert len(msgs) == 2


def test_m365_sync_graph_failure_returns_502(client, auth_headers, monkeypatch):
    API = "/api/v1"

    def _boom(db, tenant_id):
        raise GraphError("office_not_connected", status=409)

    monkeypatch.setattr("app.services.office_hub.get_graph_client", _boom)
    r = client.post(
        f"{API}/email/accounts",
        headers=auth_headers,
        json={"provider": "microsoft", "email": "broken@office.example.com", "config": {}},
    )
    # 创建时解析 /me 失败 → 400（显式给了 email 则创建成功，同步时才失败）
    assert r.status_code == 200, r.text
    acc = r.json()
    s = client.post(f"{API}/email/accounts/{acc['id']}/sync", headers=auth_headers)
    assert s.status_code == 502
    assert s.json()["detail"]["code"] == "GRAPH_SYNC_FAILED"


def test_demo_sync_still_works(client, auth_headers):
    API = "/api/v1"
    r = client.post(
        f"{API}/email/accounts",
        headers=auth_headers,
        json={"provider": "demo", "email": "ops@demo.marios", "config": {}},
    )
    assert r.status_code == 200, r.text
    s = client.post(f"{API}/email/accounts/{r.json()['id']}/sync", headers=auth_headers)
    assert s.status_code == 200, s.text
    assert s.json()["synced"] == 1


def test_email_related_keyword_search(client, auth_headers, monkeypatch):
    _stub_graph(monkeypatch)
    API = "/api/v1"
    r = client.post(
        f"{API}/email/accounts",
        headers=auth_headers,
        json={"provider": "microsoft", "config": {}},
    )
    assert r.status_code == 200, r.text
    client.post(f"{API}/email/accounts/{r.json()['id']}/sync", headers=auth_headers)

    hit = client.get(f"{API}/email/related?q=DEMO WAVE", headers=auth_headers)
    assert hit.status_code == 200, hit.text
    rows = hit.json()
    assert any("FIRM OFFER" in (m["subject"] or "") for m in rows)

    # 多关键词 OR：任一命中即返回
    multi = client.get(f"{API}/email/related?q=DEMO WAVE,Rotterdam", headers=auth_headers)
    assert multi.status_code == 200
    assert len(multi.json()) >= len(rows)

    miss = client.get(f"{API}/email/related?q=no-such-keyword-xyz", headers=auth_headers)
    assert miss.status_code == 200 and miss.json() == []
