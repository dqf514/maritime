"""邮件闭环：解析 → 业务草稿 / 生成回复 / OneDrive 归档 / Teams 工作流通知。

验证「邮件整合对工作真正有帮助」的四个落点：
- recap / NOR / SOF 邮件 → 一键落单（Estimate 草稿 / 航次 nor_at / LaytimeCalc 草稿），
  不再只是 JSON 预览给人看
- 按模板生成业务回函发送（平台通道），同线程回写 outbound 消息 + OutboundMailLog 审计
- laytime 定稿 / 发票签发 → 凭证 CSV 自动推 OneDrive（OfficeResourceLink 关联实体）
- 复核队列新增 / 定稿 / 签发 → Teams 频道工作流提醒（带 MariOS 深链，软失败）
"""

from __future__ import annotations

import base64
from datetime import datetime
from uuid import UUID

import pytest
from sqlalchemy.orm import sessionmaker

from app.models_domain import Estimate, LaytimeCalc, PortCall, Voyage
from app.models_identity import OutboundMailLog
from app.models_office import OfficeResourceLink
from app.models_wave1 import EmailMessage
from app.services.graph_client import GraphClient


def _stub_graph(monkeypatch):
    monkeypatch.setattr(
        "app.services.office_hub.get_graph_client",
        lambda db, tenant_id: GraphClient("stub-token", mode="stub"),
    )


@pytest.fixture()
def open_db(db_engine):
    """每次调用开新会话 —— 避免跨连接快照看不到 API 侧已提交的写入。"""
    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False)


def _seed_vessel_voyage(client, h, name="Ocean Star", voyage_no="DW-001"):
    v = client.post("/api/v1/masterdata/vessels", headers=h, json={"name": name, "imo": "9123456"}).json()
    assert "id" in v, v
    vo = client.post("/api/v1/voyages", headers=h, json={"voyage_no": voyage_no, "vessel_id": v["id"]}).json()
    assert "id" in vo, vo
    return v, vo


def _rich_inbox(mails):
    def _list_mail(self, *, top: int = 25, folder: str = "inbox"):
        return mails[:top]

    return _list_mail


# ── 1. recap 邮件 → 估算草稿 ───────────────────────────────────────────


def test_apply_fixture_recap_creates_estimate_draft(client, auth_headers, open_db):
    API = "/api/v1"
    _seed_vessel_voyage(client, auth_headers)
    r = client.post(
        f"{API}/email/accounts",
        headers=auth_headers,
        json={"provider": "demo", "email": "ops@demo.marios", "config": {}},
    )
    acc = r.json()
    client.post(f"{API}/email/accounts/{acc['id']}/sync", headers=auth_headers)

    review = client.get(f"{API}/email/review", headers=auth_headers).json()
    recap = [m for m in review if "RECAP" in (m["subject"] or "")]
    assert recap, review
    mid = recap[0]["id"]

    res = client.post(f"{API}/email/review/{mid}/apply", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["email_type"] in ("fixture_recap", "recap")
    created = body["created"]
    assert len(created) == 1 and created[0]["entity"] == "estimate"

    with open_db() as s:
        est = s.get(Estimate, UUID(created[0]["id"]))
        assert est is not None
        assert est.status == "draft"
        assert est.inputs["load_port"] == "SGSIN"
        assert est.inputs["discharge_port"] == "NLRTM"
        assert float(est.inputs["freight_rate"]) == 18.5
        assert est.vessel_id is not None  # 船名模糊匹配到 Ocean Star
        assert est.inputs["source_email"]["email_message_db_id"] == mid

        # 源邮件以 OfficeResourceLink=mail 挂回实体（实体页可回溯原始邮件）
        links = (
            s.query(OfficeResourceLink)
            .filter(
                OfficeResourceLink.entity_type == "estimate",
                OfficeResourceLink.entity_id == est.id,
                OfficeResourceLink.resource_kind == "mail",
            )
            .all()
        )
        assert len(links) == 1

        # 落单后消息出复核队列
        msg = s.get(EmailMessage, UUID(mid))
        assert msg.parse_status == "parsed"

    # 幂等：重复 apply 不再生成第二份草稿
    again = client.post(f"{API}/email/review/{mid}/apply", headers=auth_headers)
    assert again.status_code == 200
    assert again.json()["created"] == []
    assert "already_applied" in again.json()["hints"]


# ── 2. NOR 邮件 → 航次盖 nor_at ────────────────────────────────────────


def test_apply_nor_stamps_voyage(client, auth_headers, open_db, monkeypatch):
    API = "/api/v1"
    _stub_graph(monkeypatch)
    _seed_vessel_voyage(client, auth_headers)

    now = datetime.now().astimezone().isoformat()
    monkeypatch.setattr(
        GraphClient,
        "list_mail",
        _rich_inbox(
            [
                {
                    "id": "nor-rich-1",
                    "subject": "Notice of Readiness — Ocean Star / Rotterdam",
                    "from": {"emailAddress": {"address": "master@oceanstar.demo"}},
                    "receivedDateTime": now,
                    "body": (
                        "Notice of Readiness\n"
                        "Vessel: MV Ocean Star\n"
                        "Port: Rotterdam\n"
                        "Date: 22/10/2026 08:00\n"
                        "Position: 51°55'N 004°28'E\n"
                        "Draft: 12.4 m\n"
                    ),
                }
            ]
        ),
    )

    r = client.post(
        f"{API}/email/accounts",
        headers=auth_headers,
        json={"provider": "microsoft", "config": {}},
    )
    client.post(f"{API}/email/accounts/{r.json()['id']}/sync", headers=auth_headers)

    review = client.get(f"{API}/email/review", headers=auth_headers).json()
    nor = [m for m in review if "Readiness" in (m["subject"] or "") or "NOR" in (m["subject"] or "")]
    assert nor, review

    res = client.post(f"{API}/email/review/{nor[0]['id']}/apply", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["email_type"] == "nor"
    assert len(body["created"]) == 1
    assert body["created"][0]["action"] == "nor_stamped"
    assert body["created"][0]["nor_at"].startswith("2026-10-22T08:00")

    with open_db() as s:
        voyage = s.query(Voyage).filter(Voyage.voyage_no == "DW-001").one()
        assert (voyage.meta or {}).get("nor_at", "").startswith("2026-10-22T08:00")
        pc = s.query(PortCall).filter(PortCall.voyage_id == voyage.id).first()
        if pc is not None:  # 有 port call 则直接盖在上面
            assert pc.nor_at is not None


# ── 3. laytime statement → LaytimeCalc 草稿 ────────────────────────────


def test_apply_laytime_statement_creates_calc(client, auth_headers, open_db, monkeypatch):
    API = "/api/v1"
    _stub_graph(monkeypatch)
    _seed_vessel_voyage(client, auth_headers)

    now = datetime.now().astimezone().isoformat()
    monkeypatch.setattr(
        GraphClient,
        "list_mail",
        _rich_inbox(
            [
                {
                    "id": "sof-rich-1",
                    "subject": "Laytime Statement — Ocean Star / DW-001",
                    "from": {"emailAddress": {"address": "agent@rotterdam.demo"}},
                    "receivedDateTime": now,
                    "body": (
                        "Statement of Facts\n"
                        "Vessel: MV Ocean Star\n"
                        "01/10 06:00 NOR tendered\n"
                        "01/10 09:30 Commenced loading\n"
                        "01/10 18:00 Completed loading\n"
                        "Total allowed: 3 days\n"
                    ),
                }
            ]
        ),
    )

    r = client.post(
        f"{API}/email/accounts",
        headers=auth_headers,
        json={"provider": "microsoft", "config": {}},
    )
    client.post(f"{API}/email/accounts/{r.json()['id']}/sync", headers=auth_headers)

    review = client.get(f"{API}/email/review", headers=auth_headers).json()
    sof = [m for m in review if "Laytime" in (m["subject"] or "")]
    assert sof, review

    res = client.post(f"{API}/email/review/{sof[0]['id']}/apply", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["email_type"] == "laytime_statement"
    created = body["created"]
    assert len(created) == 1 and created[0]["entity"] == "laytime"
    assert created[0]["events"] == 3

    with open_db() as s:
        calc = s.get(LaytimeCalc, UUID(created[0]["id"]))
        assert calc is not None
        assert calc.voyage_id is not None  # 船名匹配到航次
        assert len(calc.inputs["sof_events"]) == 3
        assert float(calc.inputs["allowed_days"]) == 3.0


# ── 4. 生成回复 ─────────────────────────────────────────────────────────


def test_reply_render_and_send(client, auth_headers, open_db):
    API = "/api/v1"
    r = client.post(
        f"{API}/email/accounts",
        headers=auth_headers,
        json={"provider": "demo", "email": "ops@demo.marios", "config": {}},
    )
    client.post(f"{API}/email/accounts/{r.json()['id']}/sync", headers=auth_headers)
    review = client.get(f"{API}/email/review", headers=auth_headers).json()
    recap = [m for m in review if "RECAP" in (m["subject"] or "")]
    assert recap, review
    mid = recap[0]["id"]

    # 详情：含正文（回复预览的数据源）
    detail = client.get(f"{API}/email/messages/{mid}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["body_text"]

    # 发送：ack_recap 模板 → 确认成交条款回函
    res = client.post(
        f"{API}/email/messages/{mid}/reply",
        headers=auth_headers,
        json={"template": "ack_recap", "extra": {}},
    )
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["to"] == "broker@example.com"
    assert out["subject"].startswith("Re:")
    assert out["status"] in ("sent", "fallback_console")

    with open_db() as s:
        # 同线程回写 outbound 消息
        msg = s.get(EmailMessage, UUID(out["outbound_message_id"]))
        assert msg is not None and msg.direction == "outbound"
        src = s.get(EmailMessage, UUID(mid))
        assert msg.thread_id == src.thread_id
        assert "We confirm the fixture recap" in (msg.body_text or "")
        assert "> " in (msg.body_text or "")  # 引用原文

        # OutboundMailLog 审计
        log_row = s.get(OutboundMailLog, UUID(out["mail_log_id"]))
        assert log_row is not None and log_row.purpose == "email.reply"

    # 未知模板 422
    bad = client.post(
        f"{API}/email/messages/{mid}/reply",
        headers=auth_headers,
        json={"template": "nope"},
    )
    assert bad.status_code == 422


# ── 5. OneDrive 归档 + Teams 工作流通知 ─────────────────────────────────


def test_office_archive_and_workflow_notify(client, auth_headers, oauth_stub, open_db, monkeypatch):
    API = "/api/v1"
    _stub_graph(monkeypatch)

    est = client.post(
        f"{API}/estimates",
        headers=auth_headers,
        json={"title": "archive me", "mode": "voyage", "inputs": {}},
    ).json()

    # 未连接 → archive 503（且不会把租户悄悄 stub 连上）
    pre = client.post(
        f"{API}/office/archive",
        headers=auth_headers,
        json={
            "entity_type": "estimate",
            "entity_id": est["id"],
            "filename": "x.csv",
            "content_b64": base64.b64encode(b"a,b\n1,2\n").decode(),
        },
    )
    assert pre.status_code == 503
    assert pre.json()["detail"]["code"] == "OFFICE_NOT_CONNECTED"

    # 连接 stub M365 → archive 成功并记 OfficeResourceLink
    conn = client.get(f"{API}/office/connect", headers=auth_headers)
    assert conn.status_code == 200, conn.text

    csv_b64 = base64.b64encode("field,value\namount,100\n".encode("utf-8-sig")).decode()
    res = client.post(
        f"{API}/office/archive",
        headers=auth_headers,
        json={
            "entity_type": "estimate",
            "entity_id": est["id"],
            "filename": "estimate_snapshot.csv",
            "content_b64": csv_b64,
            "content_type": "text/csv",
        },
    )
    assert res.status_code == 200, res.text
    doc = res.json()
    assert doc["item_id"] and doc["web_url"]

    with open_db() as s:
        link = (
            s.query(OfficeResourceLink)
            .filter(
                OfficeResourceLink.entity_type == "estimate",
                OfficeResourceLink.resource_kind == "drive_item",
            )
            .one()
        )
        assert link.web_url == doc["web_url"]
        tenant_id = link.tenant_id

    # Teams 工作流事件（stub 发送，connected 时可用；软失败返回值而非异常）
    from app.services import office_hub

    with open_db() as s:
        out = office_hub.notify_workflow_event(
            s,
            tenant_id,
            title="Test event",
            lines=["line one"],
            href="/email/review",
        )
    assert out is not None


# ── 6. 业务钩子：laytime 定稿 / 发票签发 → 归档 + 通知（软失败）───────


def test_laytime_finalize_and_invoice_issue_escalate(client, auth_headers, oauth_stub, open_db, monkeypatch):
    API = "/api/v1"
    _stub_graph(monkeypatch)
    client.get(f"{API}/office/connect", headers=auth_headers)

    # laytime：create → calculate → finalize → 归档 drive_item
    lt = client.post(
        f"{API}/laytimes",
        headers=auth_headers,
        json={"inputs": {"sof_events": [{"time": "01/10 06:00", "event": "NOR"}], "allowed_days": 3}},
    )
    assert lt.status_code == 200, lt.text
    lt_id = lt.json()["id"]
    assert client.post(f"{API}/laytimes/{lt_id}/calculate", headers=auth_headers).status_code == 200
    fin = client.post(f"{API}/laytimes/{lt_id}/finalize", headers=auth_headers)
    assert fin.status_code == 200, fin.text

    with open_db() as s:
        lay_links = (
            s.query(OfficeResourceLink)
            .filter(
                OfficeResourceLink.entity_type == "laytime",
                OfficeResourceLink.entity_id == UUID(lt_id),
                OfficeResourceLink.resource_kind == "drive_item",
            )
            .all()
        )
        assert len(lay_links) == 1
        assert lay_links[0].display_name and lay_links[0].display_name.endswith(".csv")

    # invoice：create → pending_approval → issued → 归档 drive_item
    inv = client.post(
        f"{API}/invoices",
        headers=auth_headers,
        json={"invoice_type": "freight", "amount": 100000, "currency": "USD"},
    )
    assert inv.status_code == 200, inv.text
    inv_id = inv.json()["id"]
    pa = client.post(f"{API}/invoices/{inv_id}/transition", headers=auth_headers, params={"target": "pending_approval"})
    assert pa.status_code == 200, pa.text
    iss = client.post(f"{API}/invoices/{inv_id}/transition", headers=auth_headers, params={"target": "issued"})
    assert iss.status_code == 200, iss.text

    with open_db() as s:
        inv_links = (
            s.query(OfficeResourceLink)
            .filter(
                OfficeResourceLink.entity_type == "invoice",
                OfficeResourceLink.entity_id == UUID(inv_id),
                OfficeResourceLink.resource_kind == "drive_item",
            )
            .all()
        )
        assert len(inv_links) == 1

    # 断开后 finalize 另一条 laytime：软失败，不 500、不产生 drive_item
    client.post(f"{API}/office/disconnect", headers=auth_headers)
    lt2 = client.post(f"{API}/laytimes", headers=auth_headers, json={"inputs": {"allowed_days": 2}})
    lt2_id = lt2.json()["id"]
    client.post(f"{API}/laytimes/{lt2_id}/calculate", headers=auth_headers)
    fin2 = client.post(f"{API}/laytimes/{lt2_id}/finalize", headers=auth_headers)
    assert fin2.status_code == 200
    with open_db() as s:
        none2 = (
            s.query(OfficeResourceLink)
            .filter(
                OfficeResourceLink.entity_type == "laytime",
                OfficeResourceLink.entity_id == UUID(lt2_id),
            )
            .all()
        )
        assert none2 == []
