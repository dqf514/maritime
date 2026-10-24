"""行级数据权限（data_scope）的落地覆盖与别名归一化。

审计项："data_scope 只落地 2 处" —— 权限矩阵里把某个角色收窄成
"只看自己建的"之后，只有发票和航次两个列表真的会变窄；估价、看板、
CSV 导出、账龄全都不管 —— 管理员明明配了，用户看到的还是全租户的数据。

这里锁住：
- 每个落地面（发票列表 / 估价列表 / CSV 导出 / 账龄 / 工作台队列 /
  看板）都真的按 scope 收窄；
- 模块别名（"ship" / "estimate"）与主模块等价 —— 两边各写一份模块名
  必然漂移，一漂移收窄就**静默失效**。
"""

from __future__ import annotations

import csv
import io
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.models_saas import RoleDataScope
from app.services.data_scope import canonical_module, effective_scope

API = "/api/v1"


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _login(client, email: str, password: str = "Demo1234!") -> dict[str, str]:
    r = client.post(
        f"{API}/auth/login",
        json={"email": email, "password": password, "tenant_code": "demo"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_user(client, admin_h, role_code: str, tag: str) -> dict[str, str]:
    email = f"{tag}-{uuid4().hex[:8]}@example.com"
    r = client.post(
        f"{API}/admin/users",
        headers=admin_h,
        json={
            "email": email,
            "full_name": f"Scope {tag}",
            "password": "Demo1234!",
            "role_codes": [role_code],
        },
    )
    assert r.status_code == 200, r.text
    return _login(client, email)


def _invoice(client, h, amount: float) -> tuple[str, str]:
    r = client.post(
        f"{API}/invoices",
        headers=h,
        json={"amount": amount, "currency": "USD", "invoice_type": "FRT"},
    )
    assert r.status_code == 200, r.text
    return r.json()["invoice_no"], r.json()["id"]


def _issue(client, h, invoice_id: str) -> None:
    """把草稿发票签发 —— 账龄 / 默认导出只认已签发口径。

    状态机：draft → pending_approval → issued（不能跳步）。
    """
    for target in ("pending_approval", "issued"):
        r = client.post(f"{API}/invoices/{invoice_id}/transition?target={target}", headers=h)
        assert r.status_code == 200, r.text


def _items(payload):
    if isinstance(payload, dict):
        return payload.get("items", [])
    return payload


def _csv_cells(body: str) -> set[str]:
    rows = list(csv.reader(io.StringIO(body.lstrip("﻿"))))
    return {cell for row in rows for cell in row}


# ────────────────────────── 收窄真的生效 ──────────────────────────


def test_finance_scope_narrows_invoice_list_and_export(client, auth_headers):
    """finance 角色收窄成 "own" → 发票列表、账龄、CSV 导出都只看自己的。"""
    admin_no, admin_id = _invoice(client, auth_headers, 100.0)

    fh = _make_user(client, auth_headers, "finance", "fin")
    own_no, own_id = _invoice(client, fh, 200.0)

    _issue(client, auth_headers, admin_id)
    _issue(client, auth_headers, own_id)

    # 默认（未收窄）：能看到 admin 的发票
    r = client.get(f"{API}/invoices", headers=fh)
    assert r.status_code == 200, r.text
    assert admin_no in [i["invoice_no"] for i in _items(r.json())]

    r = client.put(
        f"{API}/admin/data-scopes",
        headers=auth_headers,
        json={"role_code": "finance", "module": "finance", "scope": "own"},
    )
    assert r.status_code == 200, r.text

    # 列表：只剩自己建的
    r = client.get(f"{API}/invoices", headers=fh)
    assert r.status_code == 200, r.text
    nos = [i["invoice_no"] for i in _items(r.json())]
    assert own_no in nos
    assert admin_no not in nos

    # 账龄：同口径
    r = client.get(f"{API}/finance/aging", headers=fh)
    assert r.status_code == 200, r.text
    aging_nos = {row["invoice_no"] for row in r.json()}
    assert own_no in aging_nos
    assert admin_no not in aging_nos

    # CSV 导出：界面上收窄了，导出的文件里也得收窄
    r = client.get(f"{API}/export/invoices.csv", headers=fh)
    assert r.status_code == 200, r.text
    flat = _csv_cells(r.text)
    assert own_no in flat, "自己的发票必须在导出里"
    assert admin_no not in flat, "别人的发票不该出现在收窄后的导出里"


def test_chartering_scope_narrows_estimate_list(client, auth_headers):
    """chartering 角色收窄成 "own" → 估价列表只看自己建的。"""
    r = client.post(
        f"{API}/estimates", headers=auth_headers, json={"title": "Admin Estimate"}
    )
    assert r.status_code == 200, r.text
    admin_est = r.json()["id"]

    ch = _make_user(client, auth_headers, "chartering", "cht")
    r = client.post(f"{API}/estimates", headers=ch, json={"title": "Own Estimate"})
    assert r.status_code == 200, r.text
    own_est = r.json()["id"]

    r = client.get(f"{API}/estimates", headers=ch)
    assert r.status_code == 200, r.text
    assert admin_est in [e["id"] for e in r.json()]

    r = client.put(
        f"{API}/admin/data-scopes",
        headers=auth_headers,
        json={"role_code": "chartering", "module": "chartering", "scope": "own"},
    )
    assert r.status_code == 200, r.text

    r = client.get(f"{API}/estimates", headers=ch)
    assert r.status_code == 200, r.text
    ids = [e["id"] for e in r.json()]
    assert own_est in ids
    assert admin_est not in ids


def test_scope_narrows_home_queue_and_dashboard(client, auth_headers):
    """工作台待审批队列与财务看板也要按 scope 收窄。"""
    admin_no, admin_id = _invoice(client, auth_headers, 300.0)
    fh = _make_user(client, auth_headers, "finance", "finq")
    own_no, own_id = _invoice(client, fh, 400.0)

    r = client.put(
        f"{API}/admin/data-scopes",
        headers=auth_headers,
        json={"role_code": "finance", "module": "finance", "scope": "own"},
    )
    assert r.status_code == 200, r.text

    r = client.get(f"{API}/home/summary", headers=fh)
    assert r.status_code == 200, r.text
    body = r.text
    assert admin_no not in body, "工作台队列里不该出现别人的单号"

    r = client.get(f"{API}/dashboards/finance/snapshot", headers=fh)
    assert r.status_code == 200, r.text
    assert admin_no not in r.text, "看板里不该出现别人的单号"


# ────────────────────────── 别名归一化 ──────────────────────────

def test_module_aliases_are_canonical():
    assert canonical_module("ship") == "ship_mgmt"
    assert canonical_module("SHIP") == "ship_mgmt"
    assert canonical_module("estimate") == "chartering"
    assert canonical_module("finance") == "finance"


def test_effective_scope_honours_alias_rows(db_session):
    """老数据里存的是别名（"ship"）→ 按主模块（"ship_mgmt"）查也必须命中。"""
    admin = db_session.scalar(select(User).where(User.email == "admin@demo.marios"))
    tid = admin.tenant_id
    db_session.add(
        RoleDataScope(tenant_id=tid, role_code="technical", module="ship", scope="own")
    )
    db_session.commit()
    assert effective_scope(db_session, tid, ["technical"], "ship_mgmt") == "own"
    assert effective_scope(db_session, tid, ["technical"], "ship") == "own"


def test_data_scope_admin_rejects_unknown_module(client, auth_headers):
    r = client.put(
        f"{API}/admin/data-scopes",
        headers=auth_headers,
        json={"role_code": "finance", "module": "not_a_module", "scope": "own"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "INVALID_MODULE"


@pytest.mark.parametrize("module", ["ship", "ship_mgmt", "estimate", "chartering"])
def test_data_scope_admin_accepts_alias_modules(client, auth_headers, module):
    """别名也必须能写进去（写进去时统一归一化成主模块）。"""
    r = client.put(
        f"{API}/admin/data-scopes",
        headers=auth_headers,
        json={"role_code": "finance", "module": module, "scope": "all"},
    )
    assert r.status_code == 200, r.text
    r = client.get(f"{API}/admin/data-scopes", headers=auth_headers)
    assert r.status_code == 200, r.text
    modules = [i["module"] for i in r.json()["items"]]
    assert canonical_module(module) in modules


# ────────────────────── fail-closed（失败即关闭）──────────────────────


def test_data_scope_fails_closed_for_tenant_model_without_owner_column(db_session):
    """租户数据但模型没有归属列 → "own" 必须返回**空集**。

    以前这里是"静默放行"：管理员把角色收窄成"只看自己建的"，列表却还是
    全租户的数据 —— 开关成了摆设，比直接报错更危险。现在失败即关闭。
    """
    from app.models_domain import EmissionRecord
    from app.services.data_scope import apply_data_scope

    admin = db_session.scalar(select(User).where(User.email == "admin@demo.marios"))
    tid = admin.tenant_id
    # 自备一行：演示种子不一定有排放记录，但语义要独立于种子内容。
    db_session.add(
        EmissionRecord(tenant_id=tid, fo_mt=10.0, do_mt=1.0, co2_mt=40.0, period="2026")
    )
    db_session.commit()
    total = db_session.scalar(
        select(func.count()).select_from(EmissionRecord).where(EmissionRecord.tenant_id == tid)
    )
    assert total and total > 0, "演示数据里应该有排放记录才能验证收窄"

    rows = db_session.scalars(
        apply_data_scope(
            select(EmissionRecord).where(EmissionRecord.tenant_id == tid),
            EmissionRecord,
            admin.id,
            "own",
        )
    ).all()
    assert rows == [], "没有归属列的租户模型不能按 'own' 放行全租户数据"


def test_data_scope_keeps_global_reference_data_untouched(db_session):
    """全局参考数据（ports 等无 tenant_id）不受行级范围影响。"""
    from app.models_wave1 import Port
    from app.services.data_scope import apply_data_scope

    rows = db_session.scalars(apply_data_scope(select(Port), Port, uuid4(), "own")).all()
    assert rows, "全局参考数据不该被行级范围清空"


def test_data_scope_uses_owner_column_when_present(db_session):
    """有归属列的模型 → 按 ``created_by`` 过滤。"""
    from app.models_domain import Claim
    from app.services.data_scope import apply_data_scope

    admin = db_session.scalar(select(User).where(User.email == "admin@demo.marios"))
    tid = admin.tenant_id
    total = db_session.scalar(
        select(func.count()).select_from(Claim).where(Claim.tenant_id == tid)
    )
    if not total:
        pytest.skip("演示数据里没有索赔记录")
    rows = db_session.scalars(
        apply_data_scope(
            select(Claim).where(Claim.tenant_id == tid), Claim, admin.id, "own"
        )
    ).all()
    # 演示索赔没有 created_by（历史数据）→ 收窄后为空，但**不能**是全量。
    assert len(rows) < total or all(r.created_by == admin.id for r in rows)


def test_masterdata_scope_narrows_counterparty_list(client, auth_headers):
    """主数据（往来单位）也真的能按 "own" 收窄 —— 归属列补齐后不再是摆设。"""
    r = client.post(
        f"{API}/masterdata/counterparties",
        headers=auth_headers,
        json={"name": "Admin Counterparty"},
    )
    assert r.status_code == 200, r.text
    admin_cp = r.json()["id"]

    th = _make_user(client, auth_headers, "technical", "tech")
    r = client.post(
        f"{API}/masterdata/counterparties",
        headers=th,
        json={"name": "Own Counterparty"},
    )
    assert r.status_code == 200, r.text
    own_cp = r.json()["id"]

    r = client.put(
        f"{API}/admin/data-scopes",
        headers=auth_headers,
        json={"role_code": "technical", "module": "masterdata", "scope": "own"},
    )
    assert r.status_code == 200, r.text

    r = client.get(f"{API}/masterdata/counterparties", headers=th)
    assert r.status_code == 200, r.text
    ids = [c["id"] for c in r.json()]
    assert own_cp in ids
    assert admin_cp not in ids, "收窄后不该看到别人建的往来单位"
