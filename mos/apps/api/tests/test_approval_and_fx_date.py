"""P1-B7 / P1-B9：工作流签发发票的审批额度 + 汇率取数日规则接线。

覆盖：

* **P1-B7** —— 工作流路径（``POST /workflows/{id}/decide`` → 签发发票）必须和
  正常签发路径（``POST /invoices/{id}/transition?target=issued``）走**同一套**
  审批额度校验：同样的 409 ``APPROVAL_LIMIT`` + 同样的 detail。超额度时发票
  停在 ``pending_approval``、工作流实例保持 ``running``。
* **P1-B9** —— ``pick_rate_date()`` 以前是死代码（规则从不生效）。现在：
  * 语义测试（配置的 basis / 默认 basis / fallback / datetime → date）；
  * 接线测试（看板折算、额度折算都按「单据日期」取价，不再取绝对最新汇率）。

租户/账号：demo 租户 ``admin@demo.marios`` / ``Demo1234!``（角色 tenant_admin）。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models_domain import Claim, Voyage
from app.models_finance_ext import ApprovalLimit
from app.models_saas import WorkflowDefinition
from app.models_wave1 import ExchangeRate


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _demo_tenant_id(db_session) -> UUID:
    from app.models import Tenant

    return UUID(str(db_session.execute(select(Tenant.id).where(Tenant.code == "demo")).scalar()))


def _sync(db_session) -> None:
    """结束 db_session 的事务，避免和 API 请求在同一 SQLite 库上互锁。"""
    db_session.rollback()


def _create_invoice(client, h, amount=50_000, invoice_type="freight", currency="USD"):
    r = client.post(
        "/api/v1/invoices",
        headers=h,
        json={"invoice_type": invoice_type, "amount": amount, "currency": currency},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _to_pending(client, h, invoice_id):
    r = client.post(f"/api/v1/invoices/{invoice_id}/transition?target=pending_approval", headers=h)
    assert r.status_code == 200, r.text
    return r


def _make_limit(client, h, *, role_code="tenant_admin", entity_type="invoice", currency="USD", lo=0, hi=1_000):
    r = client.post(
        "/api/v1/approvals/limits",
        headers=h,
        json={
            "role_code": role_code,
            "entity_type": entity_type,
            "currency": currency,
            "amount_from": lo,
            "amount_to": hi,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def _enable_invoice_workflow(db_session, *, allow_self_approve=True) -> WorkflowDefinition:
    """确保 demo 租户有启用的 invoice 审批工作流（种子已建，缺则补）。"""
    tid = _demo_tenant_id(db_session)
    row = db_session.scalar(
        select(WorkflowDefinition).where(
            WorkflowDefinition.tenant_id == tid,
            WorkflowDefinition.code == "invoice_approval",
        )
    )
    if row is None:
        row = WorkflowDefinition(
            tenant_id=tid,
            code="invoice_approval",
            name="Invoice issue approval",
            entity_type="invoice",
            steps={"steps": [{"name": "Finance lead", "role_code": "finance"}]},
            enabled=True,
        )
        db_session.add(row)
    steps = dict(row.steps or {})
    steps["steps"] = steps.get("steps") or [{"name": "Finance lead", "role_code": "finance"}]
    steps["allow_self_approve"] = allow_self_approve
    row.steps = steps
    row.enabled = True
    db_session.commit()
    return row


def _workflow_instance(client, h, entity_id):
    """待办箱里找这张单据的工作流实例。"""
    r = client.get("/api/v1/workflows/inbox", headers=h)
    assert r.status_code == 200, r.text
    for item in r.json():
        if item["entity_type"] == "invoice" and item["entity_id"] == str(entity_id):
            return item
    return None


# ── P1-B7：工作流路径的审批额度 ─────────────────────────────────────────────


def test_workflow_issue_enforces_approval_limit_like_normal_path(client, auth_headers, db_session):
    """工作流签发发票也要过审批额度 —— 与正常签发路径同一个 409 / 同一个 code。"""
    h = auth_headers
    _enable_invoice_workflow(db_session)
    _sync(db_session)
    _make_limit(client, h, lo=0, hi=1_000)

    # 正常路径：draft → pending_approval → issued（超额度 → 409）
    normal = _create_invoice(client, h, amount=50_000)
    _to_pending(client, h, normal["id"])
    normal_res = client.post(f"/api/v1/invoices/{normal['id']}/transition?target=issued", headers=h)
    assert normal_res.status_code == 409, normal_res.text
    normal_detail = normal_res.json()["detail"]
    assert normal_detail["code"] == "APPROVAL_LIMIT"

    # 工作流路径：draft → pending_approval（起工作流）→ 待办箱批准
    wf = _create_invoice(client, h, amount=50_000)
    _to_pending(client, h, wf["id"])
    inst = _workflow_instance(client, h, wf["id"])
    assert inst is not None, "invoice workflow instance was not started"

    wf_res = client.post(f"/api/v1/workflows/{inst['id']}/decide", headers=h, json={"decision": "approve"})
    assert wf_res.status_code == 409, wf_res.text
    detail = wf_res.json()["detail"]

    # 与正常路径**完全一致**的状态码与错误码
    assert detail["code"] == normal_detail["code"] == "APPROVAL_LIMIT"
    assert detail["entity_type"] == normal_detail["entity_type"] == "invoice"
    assert detail["amount"] == normal_detail["amount"] == 50_000
    assert detail["currency"] == normal_detail["currency"] == "USD"
    assert detail["limits"] == normal_detail["limits"]

    # 状态没被推进：发票仍待审批、工作流仍在跑
    inv = client.get(f"/api/v1/invoices/{wf['id']}", headers=h).json()
    assert inv["status"] == "pending_approval"
    assert _workflow_instance(client, h, wf["id"]) is not None


def test_workflow_issue_within_limit_still_works(client, auth_headers, db_session):
    """额度内的发票走工作流照样能签发（修的是绕过，不是把工作流堵死）。"""
    h = auth_headers
    _enable_invoice_workflow(db_session)
    _sync(db_session)
    _make_limit(client, h, lo=0, hi=100_000)

    inv = _create_invoice(client, h, amount=1_000)
    _to_pending(client, h, inv["id"])
    inst = _workflow_instance(client, h, inv["id"])
    assert inst is not None

    res = client.post(f"/api/v1/workflows/{inst['id']}/decide", headers=h, json={"decision": "approve"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "approved"

    row = client.get(f"/api/v1/invoices/{inv['id']}", headers=h).json()
    assert row["status"] == "issued"


def test_workflow_issue_without_limit_rows_is_permitted(client, auth_headers, db_session):
    """没有额度配置时沿用宽松默认（与正常路径一致）。"""
    h = auth_headers
    _enable_invoice_workflow(db_session)
    _sync(db_session)
    assert client.get("/api/v1/approvals/limits", headers=h).json()["items"] == []

    inv = _create_invoice(client, h, amount=999_999)
    _to_pending(client, h, inv["id"])
    inst = _workflow_instance(client, h, inv["id"])
    res = client.post(f"/api/v1/workflows/{inst['id']}/decide", headers=h, json={"decision": "approve"})
    assert res.status_code == 200, res.text
    row = client.get(f"/api/v1/invoices/{inv['id']}", headers=h).json()
    assert row["status"] == "issued"


# ── P1-B9：pick_rate_date() 的语义 ──────────────────────────────────────────


def test_pick_rate_date_semantics():
    from app.services.fx_date_rules import DEFAULT_RATE_DATE_BASIS, pick_rate_date

    assert DEFAULT_RATE_DATE_BASIS == "invoice"

    # 配置的 basis → 上下文里的对应日期
    assert pick_rate_date("arrival", {"arrival_date": "2026-03-05"}) == date(2026, 3, 5)
    assert pick_rate_date("posted", {"gmt_date": date(2026, 3, 6)}) == date(2026, 3, 6)
    assert pick_rate_date("departure", {"sailing_date": "2026-03-07"}) == date(2026, 3, 7)

    # basis 对不上 → 不静默取别的键；没有 fallback 时返回 None
    assert pick_rate_date("departure", {"arrival": "2026-03-05"}) is None
    # ...有 fallback（单据日期）就用它，不再退回「绝对最新汇率」
    assert pick_rate_date("departure", {"arrival": "2026-03-05"}, fallback=date(2026, 1, 1)) == date(2026, 1, 1)

    # datetime 取日期部分（旧实现直接把 datetime 返回出去，比较时会串类型）
    assert pick_rate_date("invoice", {"invoice_date": datetime(2026, 3, 5, 18, 30)}) == date(2026, 3, 5)

    # 未知 / 空 basis → 默认 basis（invoice），行为确定
    assert pick_rate_date("moon_phase", {"invoice": date(2026, 4, 1)}) == date(2026, 4, 1)
    assert pick_rate_date("", {"invoice": date(2026, 4, 1)}) == date(2026, 4, 1)

    # 认不出来的日期值 → 走 fallback，不抛 500
    assert pick_rate_date("invoice", {"invoice": "not-a-date"}, fallback=date(2026, 5, 1)) == date(2026, 5, 1)
    assert pick_rate_date("invoice", None) is None


def test_resolve_rate_date_uses_configured_rule(client, auth_headers, db_session):
    """规则行 → basis；没有规则行 → 默认 basis（invoice）。"""
    from app.services.fx_date_rules import resolve_rate_date

    tid = _demo_tenant_id(db_session)
    context = {
        "invoice": date(2026, 2, 1),
        "invoice_date": date(2026, 2, 1),
        "departure": date(2026, 3, 1),
        "departure_date": date(2026, 3, 1),
    }

    # 没有规则行 → 默认 basis = invoice → 单据日期
    assert resolve_rate_date(db_session, tid, "FRT", context) == date(2026, 2, 1)

    put = client.put(
        "/api/v1/approvals/fx-date-rules",
        headers=auth_headers,
        json={"invoice_type": "FRT", "rate_date_basis": "departure", "active": True},
    )
    assert put.status_code == 200, put.text
    _sync(db_session)

    assert resolve_rate_date(db_session, tid, "FRT", context) == date(2026, 3, 1)
    # 别名（freight ≡ FRT）指向同一条规则
    assert resolve_rate_date(db_session, tid, "freight", context) == date(2026, 3, 1)


# ── P1-B9：接线（看板 / 额度折算都按规则取价） ──────────────────────────────


#: EUR→USD 汇率阶梯 —— 三个日期给出三个不同的汇率，用来区分
#: 「单据日期取价」/「配置 basis 取价」/「绝对最新汇率」三种口径。
_RATE_LADDER = (
    (date(2026, 1, 1), "0.50"),
    (date(2026, 6, 1), "0.80"),
    (date(2026, 8, 1), "1.20"),
)


def _add_rates(db_session, tid, pairs):
    for rdate, rate in pairs:
        db_session.add(
            ExchangeRate(
                tenant_id=tid,
                base_currency="EUR",
                quote_currency="USD",
                rate=Decimal(rate),
                rate_date=rdate,
                source="test",
            )
        )
    db_session.commit()


def _open_claims_usd_total(db_session, tid) -> Decimal:
    rows = db_session.scalars(select(Claim).where(Claim.tenant_id == tid)).all()
    return sum(
        (Decimal(str(c.amount or 0)) for c in rows if c.status in ("open", "negotiating") and (c.currency or "USD") == "USD"),
        Decimal("0"),
    )


def _exposure_kpi(snapshot: dict) -> str:
    for kpi in snapshot["kpis"]:
        if kpi["label"] == "Demurrage exposure":
            return kpi["value"]
    raise AssertionError("Demurrage exposure KPI not found")


def test_dashboard_claim_fx_uses_document_rate_date(client, auth_headers, db_session):
    """看板折算按「单据日期」取价（默认 basis=invoice），不再取绝对最新汇率。"""
    h = auth_headers
    tid = _demo_tenant_id(db_session)
    _add_rates(db_session, tid, _RATE_LADDER)
    db_session.add(
        Claim(
            tenant_id=tid,
            claim_no="CLM-TEST-FX-DEFAULT",
            claim_type="demurrage",
            status="open",
            amount=Decimal("1000.00"),
            currency="EUR",
            created_at=datetime(2026, 2, 1),
        )
    )
    db_session.commit()
    _sync(db_session)

    base = _open_claims_usd_total(db_session, tid)
    snapshot = client.get("/api/v1/dashboards/demurrage/snapshot", headers=h).json()
    # 单据日期 2026-02-01 → 当时汇率 0.50 → 1000 EUR = 500 USD
    assert _exposure_kpi(snapshot) == f"{base + Decimal('500'):,.0f}"
    # 「绝对最新汇率」（1.20）不该出现
    assert _exposure_kpi(snapshot) != f"{base + Decimal('1200'):,.0f}"


def test_dashboard_claim_fx_follows_configured_basis(client, auth_headers, db_session):
    """配了 basis=departure → 取价日 = 关联航次的开航日。"""
    h = auth_headers
    tid = _demo_tenant_id(db_session)
    _add_rates(db_session, tid, _RATE_LADDER)

    voyage = Voyage(
        tenant_id=tid,
        voyage_no="V-FX-RULE-TEST",
        status="completed",
        started_at=datetime(2026, 7, 1),
        completed_at=datetime(2026, 7, 20),
    )
    db_session.add(voyage)
    db_session.flush()
    db_session.add(
        Claim(
            tenant_id=tid,
            claim_no="CLM-TEST-FX-RULE",
            claim_type="demurrage",
            status="open",
            voyage_id=voyage.id,
            amount=Decimal("1000.00"),
            currency="EUR",
            created_at=datetime(2026, 2, 1),
        )
    )
    db_session.commit()
    _sync(db_session)

    put = client.put(
        "/api/v1/approvals/fx-date-rules",
        headers=h,
        json={"invoice_type": "DEM", "rate_date_basis": "departure", "active": True},
    )
    assert put.status_code == 200, put.text
    _sync(db_session)

    base = _open_claims_usd_total(db_session, tid)
    snapshot = client.get("/api/v1/dashboards/demurrage/snapshot", headers=h).json()
    # 开航日 2026-07-01 → 当时汇率 0.80
    assert _exposure_kpi(snapshot) == f"{base + Decimal('800'):,.0f}"
    # 默认 basis(invoice → 2026-02-01 → 0.50) 与「绝对最新汇率」(1.20) 都不该出现
    assert _exposure_kpi(snapshot) != f"{base + Decimal('500'):,.0f}"
    assert _exposure_kpi(snapshot) != f"{base + Decimal('1200'):,.0f}"


def test_dashboard_calls_pick_rate_date_with_document_date(client, auth_headers, db_session, monkeypatch):
    """接线证据：看板折算确实走了 pick_rate_date，且上下文带单据日期。"""
    import app.services.fx_date_rules as fx

    tid = _demo_tenant_id(db_session)
    _add_rates(db_session, tid, [(date(2026, 1, 1), "0.50"), (date(2026, 6, 1), "0.80")])
    db_session.add(
        Claim(
            tenant_id=tid,
            claim_no="CLM-TEST-FX-SPY",
            claim_type="demurrage",
            status="open",
            amount=Decimal("1000.00"),
            currency="EUR",
            created_at=datetime(2026, 2, 1),
        )
    )
    db_session.commit()
    _sync(db_session)

    calls: list[tuple] = []
    original = fx.pick_rate_date

    def spy(basis, context, **kwargs):
        calls.append((basis, dict(context or {}), kwargs))
        return original(basis, context, **kwargs)

    monkeypatch.setattr(fx, "pick_rate_date", spy)

    res = client.get("/api/v1/dashboards/demurrage/snapshot", headers=auth_headers)
    assert res.status_code == 200, res.text
    assert calls, "pick_rate_date() was never called by the dashboard FX path"
    basis, context, kwargs = calls[0]
    assert basis in ("invoice", "posted", "departure", "arrival")
    assert context["invoice"] == date(2026, 2, 1)
    assert kwargs.get("fallback") == date(2026, 2, 1)


def test_approval_limit_fx_conversion_uses_document_rate_date(db_session):
    """额度跨币种折算用「单据日期」的汇率（P1-B9 接线：approval_limits）。"""
    tid = _demo_tenant_id(db_session)
    _add_rates(db_session, tid, [(date(2026, 1, 1), "0.50"), (date(2026, 6, 1), "2.00")])
    db_session.add(
        ApprovalLimit(
            tenant_id=tid,
            role_code="tenant_admin",
            entity_type="invoice",
            currency="USD",
            amount_from=Decimal("0"),
            amount_to=Decimal("1000"),
            active=True,
        )
    )
    db_session.commit()

    from app.services.approval_limits import assert_within_limit

    # 单据日期 2026-02-01 → 汇率 0.50 → 600 EUR = 300 USD → 在额度内
    assert_within_limit(
        db_session,
        tid,
        ["tenant_admin"],
        "invoice",
        Decimal("600"),
        "EUR",
        context_date=date(2026, 2, 1),
        invoice_type="FRT",
    )

    # 不给取价日 → 退回「绝对最新汇率」(2.00) → 1200 USD → 超额度
    with pytest.raises(HTTPException) as exc:
        assert_within_limit(
            db_session,
            tid,
            ["tenant_admin"],
            "invoice",
            Decimal("600"),
            "EUR",
            invoice_type="FRT",
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "APPROVAL_LIMIT"
