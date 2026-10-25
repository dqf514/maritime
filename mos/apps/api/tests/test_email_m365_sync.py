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


# ── 邮件复核增强：多文件夹 / 时间窗 / HTML 清洗 / 参数校验 ─────────────────


def test_sync_multi_folder_and_response_shape(client, auth_headers, monkeypatch):
    """folders=inbox,sentitems：inbox 2 封 + sentitems 1 封；响应带新键。"""
    _stub_graph(monkeypatch)
    API = "/api/v1"
    r = client.post(
        f"{API}/email/accounts",
        headers=auth_headers,
        json={"provider": "microsoft", "config": {}},
    )
    assert r.status_code == 200, r.text
    acc = r.json()
    s = client.post(
        f"{API}/email/accounts/{acc['id']}/sync?days=7&count=200&folders=inbox,sentitems",
        headers=auth_headers,
    )
    assert s.status_code == 200, s.text
    body = s.json()
    # stub sentitems 为空 → synced 2（inbox）；folders 统计含 inbox
    assert body["synced"] == 2
    assert body["window_days"] == 7
    assert body["count_cap"] == 200
    assert body["capped"] is False
    assert body["folders"].get("inbox") == 2

    # folder/direction 落库：inbox 行 direction=inbound, folder=inbox
    msgs = client.get(f"{API}/email/messages", headers=auth_headers).json()
    assert all(m["folder"] == "inbox" for m in msgs)
    assert all(m["direction"] == "inbound" for m in msgs)


def test_sync_param_validation_422(client, auth_headers, monkeypatch):
    _stub_graph(monkeypatch)
    API = "/api/v1"
    r = client.post(
        f"{API}/email/accounts",
        headers=auth_headers,
        json={"provider": "microsoft", "config": {}},
    )
    acc = r.json()
    # days 超上限
    assert (
        client.post(f"{API}/email/accounts/{acc['id']}/sync?days=31", headers=auth_headers).status_code
        == 422
    )
    assert (
        client.post(f"{API}/email/accounts/{acc['id']}/sync?days=0", headers=auth_headers).status_code
        == 422
    )
    # count 超上限
    assert (
        client.post(
            f"{API}/email/accounts/{acc['id']}/sync?count=1001", headers=auth_headers
        ).status_code
        == 422
    )
    # 非法文件夹名（含路径注入字符）
    assert (
        client.post(
            f"{API}/email/accounts/{acc['id']}/sync?folders=inbox%2F..%2Fetc",
            headers=auth_headers,
        ).status_code
        == 422
    )


def test_html_body_stored_as_plain_text(client, auth_headers, monkeypatch):
    """HTML body 同步后 body_text / parse_result 不含标签。"""
    from datetime import datetime, timezone

    from app.services.graph_client import GraphClient

    html_body = (
        "<html><head><style>.Mso{font-size:11pt}</style></head><body>"
        "<div class=MsoNormal><span style='color:red'>NOR tendered at "
        "<b>08:00</b> LT</span></div></body></html>"
    )
    mails = [
        {
            "id": "html-nor-1",
            "subject": "NOR tendered — Rotterdam",
            "from": {"emailAddress": {"address": "master@vessel.demo"}},
            "toRecipients": [{"emailAddress": {"address": "ops@demo.marios"}}],
            "receivedDateTime": datetime.now(timezone.utc).isoformat(),
            "sentDateTime": datetime.now(timezone.utc).isoformat(),
            "body": {"contentType": "HTML", "content": html_body},
            "conversationId": "conv-html-1",
        }
    ]

    class _Client(GraphClient):
        def list_mail(self, *, top=25, folder="inbox", since=None):
            return mails[:top] if folder == "inbox" else []

    monkeypatch.setattr(
        "app.services.office_hub.get_graph_client",
        lambda db, tenant_id: _Client("stub-token", mode="stub"),
    )
    API = "/api/v1"
    r = client.post(
        f"{API}/email/accounts",
        headers=auth_headers,
        json={"provider": "microsoft", "config": {}},
    )
    acc = r.json()
    s = client.post(f"{API}/email/accounts/{acc['id']}/sync", headers=auth_headers)
    assert s.status_code == 200, s.text

    msgs = client.get(f"{API}/email/messages", headers=auth_headers).json()
    nor = [m for m in msgs if "NOR" in (m["subject"] or "")]
    assert nor, msgs
    detail = client.get(f"{API}/email/messages/{nor[0]['id']}", headers=auth_headers).json()
    assert "<" not in detail["body_text"]
    assert "mso" not in detail["body_text"].lower()
    assert "08:00" in detail["body_text"]
    # parse_result 也不含标签（NOR 类型 → nor 字段被规则解析器捕获为纯文本）
    assert "<" not in str(detail["parse_result"])


def test_outbound_folder_not_in_review_queue(client, auth_headers, monkeypatch):
    """sentitems 行 direction=outbound、强制 parsed、不在 /email/review。"""
    from datetime import datetime, timezone

    from app.services.graph_client import GraphClient

    now = datetime.now(timezone.utc).isoformat()
    sent_mails = [
        {
            "id": "sent-1",
            "subject": "RE: FIRM OFFER — MV DEMO",
            "from": {"emailAddress": {"address": "ops@demo.marios"}},
            "toRecipients": [{"emailAddress": {"address": "charterer@broker.com"}}],
            "receivedDateTime": now,
            "sentDateTime": now,
            "body": {"contentType": "Text", "content": "We accept the rate."},
            "conversationId": "conv-sent-1",
        }
    ]

    class _Client(GraphClient):
        def list_mail(self, *, top=25, folder="inbox", since=None):
            return sent_mails[:top] if folder == "sentitems" else []

    monkeypatch.setattr(
        "app.services.office_hub.get_graph_client",
        lambda db, tenant_id: _Client("stub-token", mode="stub"),
    )
    API = "/api/v1"
    r = client.post(
        f"{API}/email/accounts",
        headers=auth_headers,
        json={"provider": "microsoft", "config": {}},
    )
    acc = r.json()
    s = client.post(
        f"{API}/email/accounts/{acc['id']}/sync?folders=sentitems", headers=auth_headers
    )
    assert s.status_code == 200, s.text

    msgs = client.get(f"{API}/email/messages", headers=auth_headers).json()
    sent = [m for m in msgs if m["folder"] == "sentitems"]
    assert sent and sent[0]["direction"] == "outbound"
    assert sent[0]["parse_status"] == "parsed"

    # 不进复核队列
    review = client.get(f"{API}/email/review", headers=auth_headers).json()
    assert all(m["folder"] == "inbox" for m in review)


def test_email_folders_endpoint(client, auth_headers, monkeypatch):
    _stub_graph(monkeypatch)
    API = "/api/v1"
    r = client.post(
        f"{API}/email/accounts",
        headers=auth_headers,
        json={"provider": "microsoft", "config": {}},
    )
    assert r.status_code == 200, r.text
    f = client.get(f"{API}/email/folders", headers=auth_headers)
    assert f.status_code == 200, f.text
    keys = {x["key"] for x in f.json()["folders"]}
    assert {"inbox", "sentitems"} <= keys


def test_list_mail_pagination(client, auth_headers, monkeypatch):
    """list_mail(top=150) 跨页拼接（页大小 100 + nextLink 翻页）。"""
    from app.services import graph_client as gc

    mails_page1 = [
        {"id": f"p1-{i}", "subject": f"m{i}", "receivedDateTime": "2026-10-25T00:00:00Z"}
        for i in range(100)
    ]
    mails_page2 = [
        {"id": f"p2-{i}", "subject": f"m{100 + i}", "receivedDateTime": "2026-10-24T00:00:00Z"}
        for i in range(50)
    ]

    class _FakeClient(GraphClient):
        mode = "live"

        def __init__(self):
            self.paths = []

        def _get(self, path):
            self.paths.append(path)
            if len(self.paths) == 1:
                return {
                    "value": mails_page1,
                    "@odata.nextLink": f"{gc.GRAPH_BASE}/me/mailFolders/inbox/messages?$top=100&skiptoken=abc",
                }
            return {"value": mails_page2}

    client_obj = _FakeClient()
    out = gc.GraphClient.list_mail(client_obj, top=150, folder="inbox")
    assert len(out) == 150
    assert out[0]["id"] == "p1-0"
    assert out[-1]["id"] == "p2-49"
    # 第一页带上 $select 与 $orderby（urlencode 会把 $ 编码为 %24）
    assert "%24select=" in client_obj.paths[0]
    assert "%24orderby=receivedDateTime" in client_obj.paths[0]


def test_list_mail_since_filter_param(client, auth_headers):
    """since 给了则第一页 URL 带 $filter receivedDateTime ge。"""
    from app.services import graph_client as gc

    class _FakeClient(GraphClient):
        mode = "live"

        def __init__(self):
            self.paths = []

        def _get(self, path):
            self.paths.append(path)
            return {"value": []}

    client_obj = _FakeClient()
    from datetime import datetime as _dt, timezone as _tz

    since = _dt(2026, 10, 18, tzinfo=_tz.utc)
    gc.GraphClient.list_mail(client_obj, top=10, folder="inbox", since=since)
    assert "%24filter=" in client_obj.paths[0]
    assert "receivedDateTime+ge+2026-10-18" in client_obj.paths[0]


def test_messages_list_filters(client, auth_headers, monkeypatch):
    """GET /email/messages 的 folder/days/limit 过滤。"""
    _stub_graph(monkeypatch)
    API = "/api/v1"
    r = client.post(
        f"{API}/email/accounts",
        headers=auth_headers,
        json={"provider": "microsoft", "config": {}},
    )
    acc = r.json()
    client.post(f"{API}/email/accounts/{acc['id']}/sync", headers=auth_headers)

    # folder 过滤
    inbox_only = client.get(f"{API}/email/messages?folder=inbox", headers=auth_headers).json()
    assert len(inbox_only) == 2
    assert all(m["folder"] == "inbox" for m in inbox_only)

    # folder=nonexistent → 空
    assert client.get(f"{API}/email/messages?folder=nope", headers=auth_headers).json() == []

    # limit 截断
    limited = client.get(f"{API}/email/messages?limit=1", headers=auth_headers).json()
    assert len(limited) == 1

    # parse_status 过滤仍可用
    review = client.get(f"{API}/email/messages?parse_status=review", headers=auth_headers).json()
    assert all(m["parse_status"] == "review" for m in review)
