"""邮件 → 实体草稿扩展 + 忽略记忆 + 通用附件/邮件存档。

Request XIV 的三个落点：
- PDA 从 invoice 拆出独立类型；bunker_offer / port_disbursement / invoice / claim
  四类新解析器 + apply 落单分支（BunkerOrder / PortDisbursement / Invoice / Claim），
  recap 同时挂估算 + 租约两份草稿
- 「忽略并记住」：误判邮件可一键忽略，同源同类型后续不再进复核队列
  （ConfigService 租户 JSON 规则，classify_with_memory 分类时降级）
- 通用实体附件（上传/版本/当前版/删除/租户隔离/模块闸门）+ 邮件一键存档为附件
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import pytest
from sqlalchemy.orm import sessionmaker

from app.models_domain import BunkerOrder, Charter, Claim, Estimate, Invoice, PortDisbursement, Voyage
from app.models_office import OfficeResourceLink
from app.models_wave1 import Attachment, EmailMessage
from app.services.graph_client import GraphClient


def _stub_graph(monkeypatch):
    monkeypatch.setattr(
        "app.services.office_hub.get_graph_client",
        lambda db, tenant_id: GraphClient("stub-token", mode="stub"),
    )


@pytest.fixture()
def open_db(db_engine):
    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False)


def _seed_vessel_voyage(client, h, name="Ocean Star", voyage_no="DW-001"):
    v = client.post("/api/v1/masterdata/vessels", headers=h, json={"name": name, "imo": "9123456"}).json()
    assert "id" in v, v
    vo = client.post("/api/v1/voyages", headers=h, json={"voyage_no": voyage_no, "vessel_id": v["id"]}).json()
    assert "id" in vo, vo
    return v, vo


def _rich_inbox(mails):
    def _list_mail(self, *, top: int = 25, folder: str = "inbox", since=None, **kwargs):
        return mails[:top] if folder == "inbox" else []

    return _list_mail


def _sync_rich(client, h, monkeypatch, mails):
    _stub_graph(monkeypatch)
    monkeypatch.setattr(GraphClient, "list_mail", _rich_inbox(mails))
    # 同一测试里可能多次同步 —— 账户复用，避免 ACCOUNT_EXISTS 409
    existing = client.get("/api/v1/email/accounts", headers=h).json()
    acc_id = existing[0]["id"] if existing else None
    if acc_id is None:
        r = client.post("/api/v1/email/accounts", headers=h, json={"provider": "microsoft", "config": {}})
        assert r.status_code == 200, r.text
        acc_id = r.json()["id"]
    sync = client.post(f"/api/v1/email/accounts/{acc_id}/sync", headers=h)
    assert sync.status_code == 200, sync.text
    return sync.json()


# ── 1. 分类器拆分 + 新解析器（纯函数） ─────────────────────────────────


def test_classifier_splits_pda_from_invoice():
    from app.services.email_intelligence import classify_email

    pda = classify_email("PDA account — Ocean Star", "Please find the port disbursement account attached.")
    assert pda["type"] == "port_disbursement"
    inv = classify_email("Invoice INV-001", "Please find our invoice attached for USD 12,000.")
    assert inv["type"] == "invoice"
    # 无关键词不误伤
    assert classify_email("Weather routing", "ETA updated.")["type"] == "general"


def test_new_rule_parsers_extract_fields():
    from app.services.email_intelligence import (
        parse_bunker_offer,
        parse_claim,
        parse_invoice,
        parse_port_disbursement,
    )

    b = parse_bunker_offer(
        "Bunker offer\nPort: Singapore\nVLSFO\nUnit price: 585.50\nQuantity: 1000 mt\nSupplier: Global Fuels\nCurrency: USD\n"
    )
    assert b["port"] == "Singapore"
    assert b["grade"] == "VLSFO"
    assert float(b["unit_price"]) == 585.5
    assert float(b["qty_ordered"]) == 1000
    assert b["supplier"] == "Global Fuels"

    p = parse_port_disbursement(
        "Port disbursement account\nPort: Rotterdam\nPDA amount: 45,000.00\nAgent: ABC Shipping Agents\nCurrency: USD\n"
    )
    assert p["port"] == "Rotterdam"
    assert float(p["pda_amount"]) == 45000.0
    assert p["agent"] == "ABC Shipping Agents"

    i = parse_invoice("Invoice No: INV-2026-001\nTotal amount: USD 12,500.75\nDue date: 15/11/2026\n")
    assert i["invoice_no_ref"] == "INV-2026-001"
    assert float(i["amount"]) == 12500.75
    assert i["due_date"] == "15/11/2026"

    c = parse_claim("We hereby claim demurrage USD 25,000. Time bar: 15/12/2026")
    assert c["claim_type"] == "demurrage"
    assert float(c["amount"]) == 25000.0
    assert c["time_bar"] == "15/12/2026"


# ── 2. sync 管线：新类型进复核队列 ─────────────────────────────────────


def test_sync_new_types_enter_review(client, auth_headers, monkeypatch):
    API = "/api/v1"
    _seed_vessel_voyage(client, auth_headers)
    now = datetime.now().astimezone().isoformat()
    _sync_rich(
        client,
        auth_headers,
        monkeypatch,
        [
            {
                "id": "bnk-1",
                "subject": "Bunker offer — Ocean Star",
                "from": {"emailAddress": {"address": "bunker@fuels.demo"}},
                "receivedDateTime": now,
                "body": "Bunker offer\nPort: Singapore\nVLSFO\nUnit price: 585\nQuantity: 1000 mt\n",
            },
            {
                "id": "pda-1",
                "subject": "PDA account — Ocean Star",
                "from": {"emailAddress": {"address": "agent@rotterdam.demo"}},
                "receivedDateTime": now,
                "body": "Port disbursement account\nPort: Rotterdam\nPDA amount: 45,000\n",
            },
            {
                "id": "inv-1",
                "subject": "Invoice for laytime",
                "from": {"emailAddress": {"address": "billing@charterer.demo"}},
                "receivedDateTime": now,
                "body": "Invoice No: INV-X-1\nTotal amount: USD 12,500\n",
            },
            {
                "id": "clm-1",
                "subject": "Demurrage claim",
                "from": {"emailAddress": {"address": "claims@charterer.demo"}},
                "receivedDateTime": now,
                "body": "We claim demurrage USD 25,000. Time bar: 15/12/2026",
            },
        ],
    )
    review = client.get(f"{API}/email/review", headers=auth_headers).json()
    types = {(m["parse_result"] or {}).get("email_type") for m in review}
    assert {"bunker_offer", "port_disbursement", "invoice", "claim"} <= types, types


# ── 3. apply：四类新分支落草稿 ─────────────────────────────────────────


def test_apply_bunker_offer_creates_order(client, auth_headers, open_db, monkeypatch):
    API = "/api/v1"
    _seed_vessel_voyage(client, auth_headers)
    now = datetime.now().astimezone().isoformat()
    _sync_rich(
        client,
        auth_headers,
        monkeypatch,
        [
            {
                "id": "bnk-2",
                "subject": "Bunker offer — Ocean Star",
                "from": {"emailAddress": {"address": "bunker@fuels.demo"}},
                "receivedDateTime": now,
                "body": "Bunker offer\nPort: Singapore\nVLSFO\nUnit price: 585.50\nQuantity: 1000 mt\nSupplier: Global Fuels\n",
            }
        ],
    )
    review = client.get(f"{API}/email/review", headers=auth_headers).json()
    msg = [m for m in review if (m["parse_result"] or {}).get("email_type") == "bunker_offer"][0]
    res = client.post(f"{API}/email/review/{msg['id']}/apply", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["email_type"] == "bunker_offer"
    created = body["created"]
    assert len(created) == 1 and created[0]["entity"] == "bunker_order"
    with open_db() as s:
        order = s.get(BunkerOrder, UUID(created[0]["id"]))
        assert order is not None
        assert order.status == "planned"
        assert order.grade == "VLSFO"
        assert float(order.unit_price) == 585.5
        assert float(order.qty_ordered) == 1000
        assert order.vessel_id is not None
        assert order.voyage_id is not None
        # 源邮件挂回实体
        links = (
            s.query(OfficeResourceLink)
            .filter(
                OfficeResourceLink.entity_type == "bunker_order",
                OfficeResourceLink.entity_id == order.id,
                OfficeResourceLink.resource_kind == "mail",
            )
            .all()
        )
        assert len(links) == 1


def test_apply_pda_creates_disbursement(client, auth_headers, open_db, monkeypatch):
    API = "/api/v1"
    _seed_vessel_voyage(client, auth_headers)
    now = datetime.now().astimezone().isoformat()
    _sync_rich(
        client,
        auth_headers,
        monkeypatch,
        [
            {
                "id": "pda-2",
                "subject": "PDA account — Ocean Star",
                "from": {"emailAddress": {"address": "agent@rotterdam.demo"}},
                "receivedDateTime": now,
                "body": "Port disbursement account\nPort: Rotterdam\nPDA amount: 45,000.00\nCurrency: USD\n",
            }
        ],
    )
    review = client.get(f"{API}/email/review", headers=auth_headers).json()
    msg = [m for m in review if (m["parse_result"] or {}).get("email_type") == "port_disbursement"][0]
    res = client.post(f"{API}/email/review/{msg['id']}/apply", headers=auth_headers)
    assert res.status_code == 200, res.text
    created = res.json()["created"]
    assert len(created) == 1 and created[0]["entity"] == "port_disbursement"
    with open_db() as s:
        pda = s.get(PortDisbursement, UUID(created[0]["id"]))
        assert pda is not None
        assert pda.status == "draft"
        assert float(pda.pda_amount) == 45000.0
        assert pda.voyage_id is not None


def test_apply_invoice_creates_draft(client, auth_headers, open_db, monkeypatch):
    API = "/api/v1"
    _seed_vessel_voyage(client, auth_headers)
    now = datetime.now().astimezone().isoformat()
    _sync_rich(
        client,
        auth_headers,
        monkeypatch,
        [
            {
                "id": "inv-2",
                "subject": "Invoice for laytime",
                "from": {"emailAddress": {"address": "billing@charterer.demo"}},
                "receivedDateTime": now,
                "body": "Invoice No: INV-X-9\nTotal amount: USD 12,500.75\nDue date: 15/11/2026\n",
            }
        ],
    )
    review = client.get(f"{API}/email/review", headers=auth_headers).json()
    msg = [m for m in review if (m["parse_result"] or {}).get("email_type") == "invoice"][0]
    res = client.post(f"{API}/email/review/{msg['id']}/apply", headers=auth_headers)
    assert res.status_code == 200, res.text
    created = res.json()["created"]
    assert len(created) == 1 and created[0]["entity"] == "invoice"
    with open_db() as s:
        inv = s.get(Invoice, UUID(created[0]["id"]))
        assert inv is not None
        assert inv.status == "draft"
        assert float(inv.amount) == 12500.75
        assert inv.invoice_no.startswith("INV-")
        assert inv.meta["source_email"]["email_message_db_id"] == msg["id"]


def test_apply_invoice_without_amount_hints(client, auth_headers, monkeypatch):
    API = "/api/v1"
    now = datetime.now().astimezone().isoformat()
    _sync_rich(
        client,
        auth_headers,
        monkeypatch,
        [
            {
                "id": "inv-3",
                "subject": "Invoice notice",
                "from": {"emailAddress": {"address": "billing@charterer.demo"}},
                "receivedDateTime": now,
                "body": "Please find our invoice. No amount given yet.",
            }
        ],
    )
    review = client.get(f"{API}/email/review", headers=auth_headers).json()
    msg = [m for m in review if (m["parse_result"] or {}).get("email_type") == "invoice"][0]
    res = client.post(f"{API}/email/review/{msg['id']}/apply", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["created"] == []
    assert "invoice_amount_missing" in body["hints"]


def test_apply_claim_creates_record(client, auth_headers, open_db, monkeypatch):
    API = "/api/v1"
    _seed_vessel_voyage(client, auth_headers)
    now = datetime.now().astimezone().isoformat()
    _sync_rich(
        client,
        auth_headers,
        monkeypatch,
        [
            {
                "id": "clm-2",
                "subject": "Demurrage claim — Ocean Star",
                "from": {"emailAddress": {"address": "claims@charterer.demo"}},
                "receivedDateTime": now,
                "body": "We hereby claim demurrage USD 25,000.00. Time bar: 15/12/2026",
            }
        ],
    )
    review = client.get(f"{API}/email/review", headers=auth_headers).json()
    msg = [m for m in review if (m["parse_result"] or {}).get("email_type") == "claim"][0]
    res = client.post(f"{API}/email/review/{msg['id']}/apply", headers=auth_headers)
    assert res.status_code == 200, res.text
    created = res.json()["created"]
    assert len(created) == 1 and created[0]["entity"] == "claim"
    with open_db() as s:
        claim = s.get(Claim, UUID(created[0]["id"]))
        assert claim is not None
        assert claim.status == "open"
        assert claim.claim_type == "demurrage"
        assert float(claim.amount) == 25000.0
        assert claim.claim_no.startswith("CL-")
        assert claim.voyage_id is not None


def test_apply_recap_also_creates_charter(client, auth_headers, open_db):
    """recap 落单从「只有估算」变成「估算 + 租约草稿」。"""
    API = "/api/v1"
    _seed_vessel_voyage(client, auth_headers)
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
    res = client.post(f"{API}/email/review/{mid}/apply", headers=auth_headers)
    assert res.status_code == 200, res.text
    created = res.json()["created"]
    entities = {c["entity"] for c in created}
    assert entities == {"estimate", "charter"}, created
    with open_db() as s:
        charter = s.get(Charter, UUID([c for c in created if c["entity"] == "charter"][0]["id"]))
        assert charter is not None
        assert charter.status == "draft"
        assert charter.charter_no.startswith("CP-")
        assert charter.estimate_id is not None
        assert charter.freight_rate is not None
        links = (
            s.query(OfficeResourceLink)
            .filter(
                OfficeResourceLink.entity_type == "charter",
                OfficeResourceLink.entity_id == charter.id,
                OfficeResourceLink.resource_kind == "mail",
            )
            .all()
        )
        assert len(links) == 1


# ── 4. 忽略并记住 ──────────────────────────────────────────────────────


def test_ignore_and_remember_suppresses_future(client, auth_headers, open_db, monkeypatch):
    API = "/api/v1"
    now = datetime.now().astimezone().isoformat()
    mails = [
        {
            "id": "bnk-ign-1",
            "subject": "Bunker offer — Ocean Star",
            "from": {"emailAddress": {"address": "promo@bulkmail.demo"}},
            "receivedDateTime": now,
            "body": "Bunker offer\nPort: Singapore\nVLSFO\nUnit price: 585\nQuantity: 1000 mt\n",
        }
    ]
    _sync_rich(client, auth_headers, monkeypatch, mails)
    review = client.get(f"{API}/email/review", headers=auth_headers).json()
    msg = [m for m in review if (m["parse_result"] or {}).get("email_type") == "bunker_offer"][0]

    # 忽略并记住 → 出队 + 规则落库
    res = client.post(f"{API}/email/review/{msg['id']}/ignore", headers=auth_headers, json={"remember": True})
    assert res.status_code == 200, res.text
    assert res.json()["remembered"]["from_pattern"] == "promo@bulkmail.demo"
    rules = client.get(f"{API}/email/ignore-rules", headers=auth_headers).json()["rules"]
    assert any(r["email_type"] == "bunker_offer" and r["from_pattern"] == "promo@bulkmail.demo" for r in rules)

    review_after = client.get(f"{API}/email/review", headers=auth_headers).json()
    assert msg["id"] not in {m["id"] for m in review_after}

    # 同源新邮件：分类降级为 general，不再进复核队列
    _sync_rich(
        client,
        auth_headers,
        monkeypatch,
        [
            {
                "id": "bnk-ign-2",
                "subject": "Bunker offer again",
                "from": {"emailAddress": {"address": "promo@bulkmail.demo"}},
                "receivedDateTime": now,
                "body": "Bunker offer\nPort: Singapore\nVLSFO\nUnit price: 590\nQuantity: 500 mt\n",
            }
        ],
    )
    review2 = client.get(f"{API}/email/review", headers=auth_headers).json()
    gids2 = {(m.get("parse_result") or {}).get("graph_id") for m in review2}
    assert "bnk-ign-2" not in gids2
    with open_db() as s:
        suppressed = s.query(EmailMessage).filter(EmailMessage.message_id == "bnk-ign-2").one()
        assert suppressed.parse_status == "parsed"
        assert (suppressed.parse_result or {}).get("email_type") == "general"
        assert (suppressed.parse_result or {}).get("suppressed_by_rule")

    # 撤销规则 → 恢复识别
    dele = client.request(
        "DELETE",
        f"{API}/email/ignore-rules",
        headers=auth_headers,
        json={"email_type": "bunker_offer", "from_pattern": "promo@bulkmail.demo"},
    )
    assert dele.status_code == 200, dele.text
    _sync_rich(
        client,
        auth_headers,
        monkeypatch,
        [
            {
                "id": "bnk-ign-3",
                "subject": "Bunker offer third",
                "from": {"emailAddress": {"address": "promo@bulkmail.demo"}},
                "receivedDateTime": now,
                "body": "Bunker offer\nPort: Singapore\nVLSFO\nUnit price: 600\nQuantity: 500 mt\n",
            }
        ],
    )
    review3 = client.get(f"{API}/email/review", headers=auth_headers).json()
    gids3 = {(m.get("parse_result") or {}).get("graph_id") for m in review3}
    assert "bnk-ign-3" in gids3


# ── 5. 通用实体附件 ────────────────────────────────────────────────────


def test_entity_attachments_crud(client, auth_headers, open_db):
    API = "/api/v1"
    est = client.post(
        f"{API}/estimates", headers=auth_headers, json={"title": "attach me", "mode": "voyage", "inputs": {}}
    ).json()

    # 上传（multipart）
    up = client.post(
        f"{API}/entities/estimate/{est['id']}/files",
        headers=auth_headers,
        files={"file": ("termsheet.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"note": "fixture termsheet"},
    )
    assert up.status_code == 200, up.text
    att = up.json()
    assert att["entity_type"] == "estimate"
    assert att["version_no"] == 1
    assert att["is_current"] is True

    # 第二版 → 旧版置非当前
    up2 = client.post(
        f"{API}/entities/estimate/{est['id']}/files",
        headers=auth_headers,
        files={"file": ("termsheet.pdf", b"%PDF-1.4 revised", "application/pdf")},
    )
    assert up2.status_code == 200
    assert up2.json()["version_no"] == 2
    lst = client.get(f"{API}/entities/estimate/{est['id']}/files", headers=auth_headers).json()
    assert len(lst) == 2
    assert [r["is_current"] for r in lst] == [True, False]

    # 下载（鉴权通道）
    dl = client.get(f"{API}/files/{att['id']}/download", headers=auth_headers)
    assert dl.status_code == 200
    assert dl.content.startswith(b"%PDF-1.4 fake")

    # 设为当前版本
    sc = client.post(f"{API}/files/{att['id']}/current", headers=auth_headers)
    assert sc.status_code == 200
    lst2 = client.get(f"{API}/entities/estimate/{est['id']}/files", headers=auth_headers).json()
    assert [r["is_current"] for r in lst2] == [False, True]

    # 删除
    dele = client.delete(f"{API}/files/{up2.json()['id']}", headers=auth_headers)
    assert dele.status_code == 200
    lst3 = client.get(f"{API}/entities/estimate/{est['id']}/files", headers=auth_headers).json()
    assert len(lst3) == 1

    # 未知实体类型 422；不存在的实体 404
    bad = client.post(
        f"{API}/entities/nonsense/{est['id']}/files",
        headers=auth_headers,
        files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert bad.status_code == 422
    missing = client.get(f"{API}/entities/estimate/00000000-0000-0000-0000-000000000000/files", headers=auth_headers)
    assert missing.status_code == 404

    # 非法内容：扩展名 pdf 但内容不是 PDF → INVALID_CONTENT
    bad_content = client.post(
        f"{API}/entities/estimate/{est['id']}/files",
        headers=auth_headers,
        files={"file": ("fake.pdf", b"plain text pretending", "application/pdf")},
    )
    assert bad_content.status_code == 400
    assert bad_content.json()["detail"]["code"] == "INVALID_CONTENT"


def test_entity_attachment_requires_login(client):
    API = "/api/v1"
    r = client.get(f"{API}/entities/estimate/00000000-0000-0000-0000-000000000000/files")
    assert r.status_code in (401, 403)


# ── 6. 邮件存档为项目附件 ──────────────────────────────────────────────


def test_archive_email_to_voyage(client, auth_headers, open_db, monkeypatch):
    API = "/api/v1"
    _seed_vessel_voyage(client, auth_headers)
    now = datetime.now().astimezone().isoformat()
    _sync_rich(
        client,
        auth_headers,
        monkeypatch,
        [
            {
                "id": "arch-1",
                "subject": "Weather routing update",
                "from": {"emailAddress": {"address": "ops@partner.demo"}},
                "receivedDateTime": now,
                "body": "Please route via Malacca Strait. ETA Singapore 22/10.",
            }
        ],
    )
    msgs = client.get(f"{API}/email/messages", headers=auth_headers).json()
    msg = [m for m in msgs if (m["parse_result"] or {}).get("graph_id") == "arch-1" or "Weather" in (m["subject"] or "")][0]
    with open_db() as s:
        voyage = s.query(Voyage).filter(Voyage.voyage_no == "DW-001").one()
        voyage_id = str(voyage.id)

    res = client.post(
        f"{API}/email/messages/{msg['id']}/archive",
        headers=auth_headers,
        json={"entity_type": "voyage", "entity_id": voyage_id},
    )
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["entity_type"] == "voyage"
    assert out["version_no"] == 1

    with open_db() as s:
        att = s.get(Attachment, UUID(out["attachment_id"]))
        assert att is not None
        assert att.entity_type == "voyage"
        assert att.file_name.endswith(".eml.txt")
        content = open(att.file_path, "r", encoding="utf-8").read()
        assert "Malacca Strait" in content
        assert "Subject: Weather routing update" in content
        link = (
            s.query(OfficeResourceLink)
            .filter(
                OfficeResourceLink.entity_type == "voyage",
                OfficeResourceLink.resource_kind == "mail",
                OfficeResourceLink.display_name == "Weather routing update",
            )
            .one()
        )
        assert link is not None
        msg_row = s.get(EmailMessage, UUID(msg["id"]))
        assert (msg_row.parse_result or {}).get("archived_to")

    # 再存档一封 → 版本 +1
    res2 = client.post(
        f"{API}/email/messages/{msg['id']}/archive",
        headers=auth_headers,
        json={"entity_type": "voyage", "entity_id": voyage_id},
    )
    assert res2.status_code == 200
    assert res2.json()["version_no"] == 2

    # 未知实体类型 422；不属于本租户的实体 404
    bad = client.post(
        f"{API}/email/messages/{msg['id']}/archive",
        headers=auth_headers,
        json={"entity_type": "spaceship", "entity_id": voyage_id},
    )
    assert bad.status_code == 422
    missing = client.post(
        f"{API}/email/messages/{msg['id']}/archive",
        headers=auth_headers,
        json={"entity_type": "voyage", "entity_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert missing.status_code == 404
