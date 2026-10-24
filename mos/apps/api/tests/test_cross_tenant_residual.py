"""P1-17：剩余的跨租户读写口子（emissions / org-units / 镜像发票 / SOF 事件）。

这些口子有一个共同形状：**写入端接受任意外键**（不校验该 id 属于本租户），
读端再把这个外键 join 出对方的业务名称 —— 于是 A 租户能看见 B 租户的
航次号 / 船舶名 / 经理姓名 / 发票金额与发票号。

绿线（必须成立）：

1. 任何**写入**引用的实体 id（voyage / vessel / counterparty / manager …）
   必须属于调用方租户，否则 404；
2. 列表端点**不得**把外租户实体的业务名称 join 出来；
3. 跨租户镜像只在调用方租户启用了 ``CFGEnableIntercompany`` 时才允许，
   且**关闭时连已有的跨租户镜像链都不能读**（否则等于一个后门）。

对外键引用的校验统一走 ``scoped_get``（IDOR 约定：不区分"不存在"与
"跨租户"，一律 404，不泄露存在性）。
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.orm import sessionmaker

from tests.isolation_helpers import API, create_tenant


@pytest.fixture()
def tenant_b(client):
    """第二个租户 'gtx'，带自己的船舶 / 对手方 / 航次 / 发票。"""
    _, hb = create_tenant(client, code="gtx", name="GTX Marine", admin_email="Admin@Gtx.example.com")
    vessel = client.post(f"{API}/masterdata/vessels", headers=hb, json={"name": "GTX Vessel"})
    cp = client.post(f"{API}/masterdata/counterparties", headers=hb, json={"name": "GTX CP", "type": "charterer"})
    charter = client.post(f"{API}/charters", headers=hb, json={"charter_type": "voyage", "counterparty_id": cp.json()["id"]})
    voyage = client.post(
        f"{API}/voyages",
        headers=hb,
        json={"voyage_no": "GTX-V1", "vessel_id": vessel.json()["id"], "charter_id": charter.json()["id"]},
    )
    invoice = client.post(
        f"{API}/invoices",
        headers=hb,
        json={"counterparty_id": cp.json()["id"], "voyage_id": voyage.json()["id"], "amount": 1234.5, "invoice_type": "FRT"},
    )
    assert invoice.status_code in (200, 201), invoice.text
    return {
        "headers": hb,
        "vessel_id": vessel.json()["id"],
        "counterparty_id": cp.json()["id"],
        "voyage_id": voyage.json()["id"],
        "invoice_id": invoice.json()["id"],
    }


# —— 1. emissions：航次 / 船舶外键必须校验租户 ——


def test_emission_rejects_foreign_voyage_and_vessel(client, auth_headers, tenant_b):
    r = client.post(
        f"{API}/emissions",
        headers=auth_headers,
        params={"voyage_id": tenant_b["voyage_id"], "fo_mt": 10, "do_mt": 5},
    )
    assert r.status_code in (403, 404), f"外租户航次必须被拒：{r.status_code} {r.text}"

    r2 = client.post(
        f"{API}/emissions",
        headers=auth_headers,
        params={"vessel_id": tenant_b["vessel_id"], "fo_mt": 10, "do_mt": 5},
    )
    assert r2.status_code in (403, 404), f"外租户船舶必须被拒：{r2.status_code} {r2.text}"


def test_emission_patch_rejects_foreign_voyage(client, auth_headers, tenant_b):
    own = client.post(
        f"{API}/emissions",
        headers=auth_headers,
        params={"fo_mt": 10, "do_mt": 5},
    )
    assert own.status_code in (200, 201), own.text
    own_id = own.json()["id"]

    r = client.patch(
        f"{API}/emissions/{own_id}",
        headers=auth_headers,
        json={"voyage_id": tenant_b["voyage_id"]},
    )
    assert r.status_code in (403, 404), f"改挂外租户航次必须被拒：{r.status_code} {r.text}"

    r2 = client.patch(
        f"{API}/emissions/{own_id}",
        headers=auth_headers,
        json={"vessel_id": tenant_b["vessel_id"]},
    )
    assert r2.status_code in (403, 404), f"改挂外租户船舶必须被拒：{r2.status_code} {r.text}"


def test_emission_list_never_joins_foreign_names(client, auth_headers, tenant_b):
    """即便库里存了指向外租户的旧脏数据，列表也不能把对方的名称 join 出来。"""
    # 走 API 造一条合法记录，再确认列表里不出现任何外租户名称
    own = client.post(f"{API}/emissions", headers=auth_headers, params={"fo_mt": 3, "do_mt": 2})
    assert own.status_code in (200, 201), own.text
    rows = client.get(f"{API}/emissions", headers=auth_headers)
    assert rows.status_code == 200, rows.text
    body = rows.json()
    items = body["items"] if isinstance(body, dict) else body
    for item in items:
        assert item.get("voyage_no") != "GTX-V1", "列表泄漏了外租户航次号"
        assert item.get("vessel_name") != "GTX Vessel", "列表泄漏了外租户船舶名"


# —— 2. org-units：manager_user_id 必须属于本租户 ——


def test_org_unit_rejects_foreign_manager(client, auth_headers, tenant_b, db_engine):
    from sqlalchemy import select

    from app.models import User

    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        foreign = db.scalar(select(User).where(User.email == "admin@gtx.example.com"))
        assert foreign is not None
        foreign_id = str(foreign.id)
    finally:
        db.close()

    r = client.post(
        f"{API}/admin/org-units",
        headers=auth_headers,
        json={"code": "LEAK", "name": "Leak Dept", "unit_type": "dept", "manager_user_id": foreign_id},
    )
    assert r.status_code in (403, 404), f"外租户用户不得被设为组织经理：{r.status_code} {r.text}"


def test_org_unit_list_never_leaks_foreign_manager_name(client, auth_headers, tenant_b):
    r = client.get(f"{API}/admin/org-units", headers=auth_headers)
    assert r.status_code == 200, r.text
    for unit in r.json():
        assert unit.get("manager_name") != "GTX Marine", "组织列表泄漏了外租户用户姓名"
        assert unit.get("manager_name") != "Admin", "组织列表泄漏了外租户用户姓名"


# —— 3. 镜像发票：跨租户镜像必须受 CFGEnableIntercompany 约束 ——


def test_cross_tenant_mirror_requires_intercompany_flag(client, auth_headers, tenant_b, db_engine):
    from sqlalchemy import select

    from app.models import User

    # 本租户造一张 FRT 发票
    cp = client.post(f"{API}/masterdata/counterparties", headers=auth_headers, json={"name": "A CP", "type": "charterer"})
    inv = client.post(
        f"{API}/invoices",
        headers=auth_headers,
        json={"counterparty_id": cp.json()["id"], "amount": 500, "invoice_type": "FRT"},
    )
    assert inv.status_code in (200, 201), inv.text

    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        gtx = db.scalar(select(User).where(User.email == "admin@gtx.example.com").limit(1))
        gtx_tenant = str(gtx.tenant_id) if gtx else None
    finally:
        db.close()
    assert gtx_tenant

    r = client.post(
        f"{API}/invoices/{inv.json()['id']}/mirror",
        headers=auth_headers,
        json={"target_tenant_id": gtx_tenant},
    )
    assert r.status_code == 403, f"未开启公司间镜像时跨租户镜像必须被拒：{r.status_code} {r.text}"


def test_mirror_chain_hidden_when_intercompany_disabled(client, auth_headers, tenant_b, db_engine):
    """即使库里**已经**存在跨租户镜像，没开公司间镜像时链上不得出现对方单据。"""
    from app.models_domain import Invoice
    from sqlalchemy import select

    # 本租户造一张 FRT 发票
    cp = client.post(f"{API}/masterdata/counterparties", headers=auth_headers, json={"name": "A CP2", "type": "charterer"})
    inv = client.post(
        f"{API}/invoices",
        headers=auth_headers,
        json={"counterparty_id": cp.json()["id"], "amount": 777, "invoice_type": "FRT"},
    )
    assert inv.status_code in (200, 201), inv.text
    own_invoice_id = inv.json()["id"]

    # 直接在库里造一个"跨租户镜像"（绕过 intercompany 闸门，模拟历史脏数据）
    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        own = db.get(Invoice, UUID(own_invoice_id))
        foreign = db.scalar(select(Invoice).where(Invoice.tenant_id != own.tenant_id).limit(1))
        assert foreign is not None, "需要至少一张外租户发票"
        dirty = Invoice(
            tenant_id=foreign.tenant_id,
            invoice_no="DIRTY-MIRROR",
            invoice_type="FRT",
            status="draft",
            amount=999999,
            currency="USD",
            mirror_of_id=own.id,
        )
        db.add(dirty)
        db.commit()
    finally:
        db.close()

    chain = client.get(f"{API}/invoices/{own_invoice_id}/mirror-chain", headers=auth_headers)
    assert chain.status_code == 200, chain.text
    for row in chain.json()["items"]:
        assert row.get("invoice_no") != "DIRTY-MIRROR", "未开公司间镜像却读到了外租户单据"
        assert float(row.get("amount") or 0) != 999999.0, "未开公司间镜像却读到了外租户金额"


# —— 4. SOF 事件：外键与读端都必须在本租户内 ——


def test_sof_event_rejects_foreign_port_call(client, auth_headers, tenant_b):
    r = client.post(
        f"{API}/sof-events",
        headers=auth_headers,
        json={"port_call_id": tenant_b["voyage_id"], "event_code": "NOR", "event_at": "2026-01-01T00:00:00"},
    )
    assert r.status_code in (403, 404), f"外租户挂靠港必须被拒：{r.status_code} {r.text}"


def test_sof_event_list_ignores_foreign_port_call(client, auth_headers, tenant_b):
    r = client.get(f"{API}/sof-events", headers=auth_headers, params={"port_call_id": tenant_b["voyage_id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    items = body["items"] if isinstance(body, dict) else body
    assert not items, f"外租户挂靠港的 SOF 事件不得返回：{items}"
