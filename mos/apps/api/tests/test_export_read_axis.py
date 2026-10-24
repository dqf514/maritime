"""导出的**读**闸门（许可 + 读角色双轴）—— "能导不能看"倒挂的回归护栏。

审计项 S3：CSV / XML 导出以前只挂**许可**闸门（``require_module``），
许可轴只回答"这个租户买没买这个模块"，**完全不查角色**。于是：

- 买了模块的租户里，**菜单里看不到该模块的角色**照样能把整张表导出去；
- 角色不匹配的用户能拿到**全租户**的发票 / 索赔 / 航次 CSV。

现在导出走 ``require_module_read(code)`` = 许可 + **读角色**（读角色集合 =
``roles_for_module(code) | {"viewer"}``）：

- 没有任何该模块读权限的角色 → 403 ``ROLE_REQUIRED``；
- ``viewer``（只读角色）→ 允许（只读用户本来就该能导出核对）；
- 许可轴仍然生效（没买模块照样 403 ``MODULE_NOT_LICENSED``）。
"""

from __future__ import annotations

from uuid import uuid4

import pytest

API = "/api/v1"


@pytest.fixture()
def _admin(client, auth_headers):
    return auth_headers


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
            "full_name": f"ReadAxis {tag}",
            "password": "Demo1234!",
            "role_codes": [role_code],
        },
    )
    assert r.status_code == 200, r.text
    return _login(client, email)


def test_export_denied_for_role_without_module_read_access(client, auth_headers):
    """``operations`` 角色对 ``chartering`` 模块既没有写也没有读授权 → 403。"""
    h = _make_user(client, auth_headers, "operations", "ops")
    r = client.get(f"{API}/export/charters.csv", headers=h)
    assert r.status_code == 403, f"没有读授权却导出了整张表：{r.status_code} {r.text}"
    assert r.json()["detail"]["code"] == "ROLE_REQUIRED"


def test_export_denied_for_role_without_module_read_access_on_finance(client, auth_headers):
    """``operations`` 角色对 ``finance`` 模块无授权 → 发票 CSV 导出必须 403。"""
    h = _make_user(client, auth_headers, "operations", "opsfin")
    for entity in ("invoices", "payments"):
        r = client.get(f"{API}/export/{entity}.csv", headers=h)
        assert r.status_code == 403, f"{entity} 导出越权：{r.status_code} {r.text}"


def test_export_allowed_for_viewer(client, auth_headers):
    """``viewer`` 是只读角色 —— 读闸门必须放行（否则只读用户没法导出核对）。"""
    h = _make_user(client, auth_headers, "viewer", "vw")
    r = client.get(f"{API}/export/voyages.csv", headers=h)
    assert r.status_code == 200, r.text
    assert "Voyage" in r.text or r.text.strip(), "导出内容为空"


def test_export_allowed_for_module_role(client, auth_headers):
    """有该模块角色的用户照常导出（别把闸门收得太紧）。"""
    h = _make_user(client, auth_headers, "finance", "fin")
    r = client.get(f"{API}/export/invoices.csv", headers=h)
    assert r.status_code == 200, r.text


def test_export_allowed_for_tenant_admin(client, auth_headers):
    r = client.get(f"{API}/export/voyages.csv", headers=auth_headers)
    assert r.status_code == 200, r.text


def test_invoice_xml_export_denied_for_foreign_role(client, auth_headers):
    """发票 XML 导出（单据级）同样要过读闸门。"""
    r = client.post(
        f"{API}/invoices",
        headers=auth_headers,
        json={"amount": 100.0, "currency": "USD", "invoice_type": "FRT"},
    )
    assert r.status_code == 200, r.text
    invoice_id = r.json()["id"]

    h = _make_user(client, auth_headers, "operations", "opsxml")
    r = client.get(f"{API}/invoices/{invoice_id}/export-xml", headers=h)
    assert r.status_code == 403, f"单据 XML 导出越权：{r.status_code} {r.text}"


def test_invoice_xml_export_allowed_for_finance_role(client, auth_headers):
    r = client.post(
        f"{API}/invoices",
        headers=auth_headers,
        json={"amount": 100.0, "currency": "USD", "invoice_type": "FRT"},
    )
    assert r.status_code == 200, r.text
    invoice_id = r.json()["id"]

    h = _make_user(client, auth_headers, "finance", "finxml")
    r = client.get(f"{API}/invoices/{invoice_id}/export-xml", headers=h)
    assert r.status_code == 200, r.text
