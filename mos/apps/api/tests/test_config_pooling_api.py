"""Task A–F 接口测试：Config Flags 预置 / Pooling 纵深 / Lightering&Barging /
XML API / 主数据扩展。

运行：
    LICENSE_DEV_UNLOCK=all python -m pytest tests/test_config_pooling_api.py -q
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

API = "/api/v1"


# ── A. Config flags ─────────────────────────────────────────────────────


def test_config_flags_presets_seeded(client, auth_headers):
    """70+ 预置键 + platform 域种子行。"""
    h = auth_headers
    presets = client.get(f"{API}/config/presets", headers=h)
    assert presets.status_code == 200, presets.text
    cats = presets.json()
    keys = [item["key"] for items in cats.values() for item in items]
    assert len(keys) >= 70, f"expected 70+ preset keys, got {len(keys)}"

    # 任务清单中的代表性键（每个板块至少一个）
    for k in (
        "CFGEnableScheduling",
        "CFGEnableBarging",
        "CFGEnableLightering",
        "CFGEnableCOA",
        "CFGEnableTrading",
        "CFGEnableWorldScale",
        "CFGEnableIntercompany",
        "CFGEnableIFRS15",
        "CFGEnableMRV",
        "CFGEnableUkEts",
        "CFGEnableReportDesigner",
        "CFGEnablePowerBI",
        "CFGEnableSSO",
        "CFGEnforceUniqueVesselImo",
        "CFG_INVOICE_MIRROR",
    ):
        assert k in keys, f"missing preset key {k}"

    # 种子行已落库（platform 域）；再次种子应幂等
    seed = client.post(f"{API}/config/flags/seed-presets", headers=h)
    assert seed.status_code == 201, seed.text
    assert seed.json()["added"] == 0

    flags = client.get(f"{API}/config/flags", headers=h).json()
    platform_keys = {f["flag_key"] for f in flags if f["scope_key"] == "platform"}
    assert set(keys) <= platform_keys, "presets not seeded into platform scope"


def test_config_flag_crud_and_scope_fallback(client, auth_headers, db_engine):
    """CRUD + scope 回退：platform < tenant < user。"""
    h = auth_headers

    # platform 默认 False
    r0 = client.get(f"{API}/config/flags/CFGEnableTrading", headers=h)
    assert r0.status_code == 200
    assert r0.json()["value"] is False

    # 租户域覆盖 → true
    r1 = client.post(
        f"{API}/config/flags",
        headers=h,
        json={"key": "CFGEnableTrading", "value": "true", "value_type": "bool", "category": "chartering"},
    )
    assert r1.status_code == 201, r1.text
    flag = r1.json()
    assert flag["scope_key"] != "platform"
    assert flag["value_type"] == "bool"
    assert client.get(f"{API}/config/flags/CFGEnableTrading", headers=h).json()["value"] is True

    # 用户域覆盖（最高优先级）→ false
    from app.models import User
    from app.models_config import ConfigFlag
    from app.services.config_service import ConfigService

    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        user = db.scalar(select(User).where(User.email == "admin@demo.marios"))
        assert user is not None
        ConfigService.set(
            db,
            key="CFGEnableTrading",
            value=False,
            tenant_id=user.tenant_id,
            user_id=user.id,
            category="chartering",
        )
        user_flag_id = db.scalar(
            select(ConfigFlag.id).where(ConfigFlag.scope_key == str(user.id), ConfigFlag.flag_key == "CFGEnableTrading")
        )

    assert client.get(f"{API}/config/flags/CFGEnableTrading", headers=h).json()["value"] is False

    # 删除用户域行 → 回退到租户域 true
    with TestingSession() as db:
        row = db.get(ConfigFlag, user_flag_id)
        db.delete(row)
        db.commit()
    assert client.get(f"{API}/config/flags/CFGEnableTrading", headers=h).json()["value"] is True

    # 删除租户域行 → 回退到 platform false
    d = client.delete(f"{API}/config/flags/{flag['id']}", headers=h)
    assert d.status_code == 200, d.text
    assert client.get(f"{API}/config/flags/CFGEnableTrading", headers=h).json()["value"] is False

    # 未知键 → default None
    missing = client.get(f"{API}/config/flags/NoSuchFlagKey", headers=h)
    assert missing.status_code == 200
    assert missing.json()["value"] is None


# ── B. Pooling depth ────────────────────────────────────────────────────


def _pool_with_vessels(client, h, total_pool_result=100000.0):
    v1 = client.post(f"{API}/masterdata/vessels", headers=h, json={"name": f"MV Pool A {uuid4().hex[:4]}"}).json()
    v2 = client.post(f"{API}/masterdata/vessels", headers=h, json={"name": f"MV Pool B {uuid4().hex[:4]}"}).json()
    pool = client.post(f"{API}/pools?name=Test Pool {uuid4().hex[:4]}", headers=h).json()
    pid = pool["id"]
    assert client.post(f"{API}/pools/{pid}/vessels?vessel_id={v1['id']}&points=1", headers=h).status_code == 200
    assert client.post(f"{API}/pools/{pid}/vessels?vessel_id={v2['id']}&points=3", headers=h).status_code == 200
    period = client.post(
        f"{API}/pools/{pid}/periods?label=2026-09&total_pool_result={total_pool_result}", headers=h
    ).json()
    return pid, period["id"], v1, v2


def test_pooling_fees_and_distribution(client, auth_headers):
    h = auth_headers
    pid, per_id, v1, v2 = _pool_with_vessels(client, h, total_pool_result=100000.0)

    # 管理费 10% + 杂费固定 50
    fee = client.post(
        f"{API}/pools/{pid}/management-fee",
        headers=h,
        json={"fee_basis": "pct", "amount": 10, "currency": "USD", "note": "mgmt"},
    )
    assert fee.status_code == 200, fee.text
    fbody = fee.json()
    assert fbody["fee_type"] == "management"
    assert fbody["fee_basis"] == "pct" and fbody["amount"] == 10.0

    admin = client.post(f"{API}/pools/{pid}/admin-fee", headers=h, json={"fee_basis": "fixed", "amount": 50})
    assert admin.status_code == 200, admin.text
    assert admin.json()["fee_type"] == "admin" and admin.json()["fee_basis"] == "fixed"

    # 非法 basis / 超范围 pct
    bad = client.post(f"{API}/pools/{pid}/management-fee", headers=h, json={"fee_basis": "weird", "amount": 1})
    assert bad.status_code == 400
    bad_pct = client.post(f"{API}/pools/{pid}/management-fee", headers=h, json={"fee_basis": "pct", "amount": 150})
    assert bad_pct.status_code == 400

    # 费用分摊：100000 → fee 10050（10% + 50），points 1:3
    calc = client.post(f"{API}/pools/{pid}/periods/{per_id}/calculate-fees", headers=h)
    assert calc.status_code == 200, calc.text
    body = calc.json()
    assert body["status"] == "calculating"
    assert body["management_fee"] == 10000.0
    assert body["admin_fee"] == 50.0
    assert body["fee_total"] == 10050.0
    assert len(body["distributions"]) == 2

    by_v = {d["vessel_id"]: d for d in body["distributions"]}
    d1 = by_v[v1["id"]]
    assert d1["gross_share"] == 25000.0
    assert d1["fee_deduction"] == 2512.5
    assert d1["net_share"] == 22487.5
    assert d1["paid_status"] == "pending"
    d2 = by_v[v2["id"]]
    assert d2["gross_share"] == 75000.0
    assert d2["fee_deduction"] == 7537.5
    assert d2["net_share"] == 67462.5

    # 现金分摊 → 已付 + period settled
    cash = client.post(f"{API}/pools/{pid}/periods/{per_id}/cash-distribution", headers=h)
    assert cash.status_code == 200, cash.text
    assert cash.json()["paid_count"] == 2
    assert cash.json()["paid_total"] == 89950.0
    assert cash.json()["status"] == "settled"

    # 汇总
    s = client.get(f"{API}/pools/{pid}/periods/{per_id}/summary", headers=h)
    assert s.status_code == 200, s.text
    sb = s.json()
    assert sb["fee_total"] == 10050.0
    assert sb["gross_total"] == 100000.0
    assert sb["net_total"] == 89950.0
    assert sb["paid_count"] == 2 and sb["pending_count"] == 0

    # settled 后重算 → 409
    again = client.post(f"{API}/pools/{pid}/periods/{per_id}/calculate-fees", headers=h)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "INVALID_STATE"


def test_pooling_fee_replacement_and_intercompany(client, auth_headers):
    h = auth_headers
    pid, per_id, _v1, _v2 = _pool_with_vessels(client, h, total_pool_result=100000.0)

    first = client.post(f"{API}/pools/{pid}/management-fee", headers=h, json={"fee_basis": "pct", "amount": 10}).json()
    second = client.post(f"{API}/pools/{pid}/management-fee", headers=h, json={"fee_basis": "pct", "amount": 5}).json()
    assert first["id"] != second["id"]
    s0 = client.get(f"{API}/pools/{pid}/periods/{per_id}/summary", headers=h).json()
    active_mgmt = [f for f in s0["fees"] if f["fee_type"] == "management" and f["active"]]
    assert len(active_mgmt) == 1
    assert active_mgmt[0]["amount"] == 5.0

    c1 = client.post(
        f"{API}/masterdata/companies", headers=h, json={"name": "MOS Co A", "code": f"MCA-{uuid4().hex[:6]}"}
    ).json()
    c2 = client.post(
        f"{API}/masterdata/companies", headers=h, json={"name": "MOS Co B", "code": f"MCB-{uuid4().hex[:6]}"}
    ).json()

    # net = 100000 - 5% = 95000
    ic = client.post(
        f"{API}/pools/{pid}/periods/{per_id}/intercompany-distribution",
        headers=h,
        json={"allocations": [{"company_id": c1["id"], "share_pct": 60}, {"company_id": c2["id"], "share_pct": 40}]},
    )
    assert ic.status_code == 200, ic.text
    ib = ic.json()
    assert ib["net_total"] == 95000.0
    amounts = {a["company_id"]: a["amount"] for a in ib["allocations"]}
    assert amounts[c1["id"]] == 57000.0
    assert amounts[c2["id"]] == 38000.0

    # share_pct 合计必须 100
    bad = client.post(
        f"{API}/pools/{pid}/periods/{per_id}/intercompany-distribution",
        headers=h,
        json={"allocations": [{"company_id": c1["id"], "share_pct": 30}, {"company_id": c2["id"], "share_pct": 30}]},
    )
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "INVALID_SHARE_PCT"

    # 汇总里回显 intercompany
    s = client.get(f"{API}/pools/{pid}/periods/{per_id}/summary", headers=h).json()
    assert s["intercompany"] and len(s["intercompany"]) == 2

    # 未知 pool / period → 404
    assert client.get(f"{API}/pools/{uuid4()}/periods/{per_id}/summary", headers=h).status_code == 404
    assert client.get(f"{API}/pools/{pid}/periods/{uuid4()}/summary", headers=h).status_code == 404


# ── C. Lightering & Barging ─────────────────────────────────────────────


def test_lightering_and_barge_crud(client, auth_headers):
    h = auth_headers
    vessel = client.post(f"{API}/masterdata/vessels", headers=h, json={"name": f"MV Lighter {uuid4().hex[:4]}"}).json()

    lg = client.post(
        f"{API}/lightering-ops",
        headers=h,
        json={
            "lightering_type": "fso",
            "vessel_id": vessel["id"],
            "location": "Singapore",
            "qty_lightered": 30000,
            "status": "planned",
            "notes": "STS lightering",
        },
    )
    assert lg.status_code == 201, lg.text
    row = lg.json()
    assert row["op_no"].startswith("LGT-")
    assert row["lightering_type"] == "fso"
    assert row["qty_lightered"] == 30000

    assert client.get(f"{API}/lightering-ops/{row['id']}", headers=h).json()["location"] == "Singapore"
    listed = client.get(f"{API}/lightering-ops", headers=h).json()
    assert any(x["id"] == row["id"] for x in listed)
    assert any(x["id"] == row["id"] for x in client.get(f"{API}/lightering-ops?status=planned", headers=h).json())

    p = client.patch(
        f"{API}/lightering-ops/{row['id']}",
        headers=h,
        json={"lightering_type": "stS", "vessel_id": vessel["id"], "status": "completed", "qty_lightered": 28000},
    )
    assert p.status_code == 200, p.text
    assert p.json()["status"] == "completed" and p.json()["lightering_type"] == "stS"

    assert client.delete(f"{API}/lightering-ops/{row['id']}", headers=h).json()["ok"] is True
    assert client.get(f"{API}/lightering-ops/{row['id']}", headers=h).status_code == 404

    bg = client.post(
        f"{API}/barge-ops",
        headers=h,
        json={
            "barge_name": f"Barge Alpha {uuid4().hex[:4]}",
            "barge_type": "tank",
            "operation_type": "bunkering",
            "vessel_id": vessel["id"],
            "qty": 500,
            "status": "in_progress",
        },
    )
    assert bg.status_code == 201, bg.text
    brow = bg.json()
    assert brow["op_no"].startswith("BRG-")
    assert brow["operation_type"] == "bunkering"

    assert client.get(f"{API}/barge-ops/{brow['id']}", headers=h).json()["qty"] == 500
    assert any(
        x["id"] == brow["id"] for x in client.get(f"{API}/barge-ops?operation_type=bunkering", headers=h).json()
    )

    p2 = client.patch(
        f"{API}/barge-ops/{brow['id']}",
        headers=h,
        json={"barge_name": brow["barge_name"], "operation_type": "transport", "status": "completed"},
    )
    assert p2.status_code == 200 and p2.json()["operation_type"] == "transport"

    assert client.delete(f"{API}/barge-ops/{brow['id']}", headers=h).json()["ok"] is True
    assert client.get(f"{API}/barge-ops/{brow['id']}", headers=h).status_code == 404


# ── D. XML API ──────────────────────────────────────────────────────────


def test_invoice_export_xml(client, auth_headers):
    h = auth_headers
    cp = client.post(
        f"{API}/masterdata/counterparties", headers=h, json={"name": f"CP XML {uuid4().hex[:6]}", "type": "charterer"}
    ).json()
    inv = client.post(
        f"{API}/invoices", headers=h, json={"counterparty_id": cp["id"], "amount": 1234.5, "currency": "USD"}
    ).json()

    r = client.get(f"{API}/invoices/{inv['id']}/export-xml", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/xml")
    root = ET.fromstring(r.text)
    assert root.tag == "Invoice"
    assert root.get("id") == inv["id"]
    assert root.get("currency") == "USD"
    assert float(root.find("Amount").text) == 1234.5
    cp_el = root.find("Counterparty")
    assert cp_el is not None and cp_el.get("id") == cp["id"]
    assert root.find("Payments") is not None

    assert client.get(f"{API}/invoices/{uuid4()}/export-xml", headers=h).status_code == 404


def test_forms_submit_xml_validate_and_import(client, auth_headers):
    h = auth_headers
    vessel = client.post(f"{API}/masterdata/vessels", headers=h, json={"name": f"MV Form {uuid4().hex[:4]}"}).json()
    terminal = client.post(f"{API}/marilink/terminals", headers=h, json={"vessel_id": vessel["id"]}).json()
    form = client.post(
        f"{API}/marilink/forms",
        headers=h,
        json={
            "form_type": "noon_report",
            "form_name": f"Noon Report XML {uuid4().hex[:4]}",
            "form_schema": {},
            "fields_json": [
                {"name": "mt_per_day", "required": True},
                {"name": "ifo_rob", "required": False},
            ],
        },
    ).json()
    assert form["form_type"] == "noon_report"

    good_xml = (
        f'<Form formType="noon_report" submittedBy="Captain" terminalKey="{terminal["terminal_key"]}">'
        "<Field name=\"mt_per_day\">12.5</Field>"
        "<Field name=\"ifo_rob\">120</Field>"
        "</Form>"
    )
    r = client.post(f"{API}/forms/submit", headers=h, json={"xml": good_xml})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] is True
    assert body["model"] == "ship_report"
    assert body["form_type"] == "noon_report"
    assert body["report_ref"].startswith("NR-")
    assert body["fields"]["mt_per_day"] == "12.5"

    # 已导入报告可查询
    reports = client.get(f"{API}/marilink/reports", headers=h).json()
    assert any(rep.get("id") == body["report_id"] or rep.get("report_ref") == body["report_ref"] for rep in reports)

    # 校验失败路径
    bad_parse = client.post(f"{API}/forms/submit", headers=h, json={"xml": "<Form"})
    assert bad_parse.status_code == 400
    assert bad_parse.json()["detail"]["code"] == "FORM_XML_PARSE"

    bad_root = client.post(f"{API}/forms/submit", headers=h, json={"xml": "<Nope/>"})
    assert bad_root.status_code == 422
    assert bad_root.json()["detail"]["code"] == "FORM_XML_ROOT"

    no_type = client.post(f"{API}/forms/submit", headers=h, json={"xml": "<Form><Field name=\"a\">1</Field></Form>"})
    assert no_type.status_code == 422
    assert no_type.json()["detail"]["code"] == "FORM_TYPE_MISSING"

    unknown_type = client.post(
        f"{API}/forms/submit",
        headers=h,
        json={"xml": f'<Form formType="no_such_type" terminalKey="{terminal["terminal_key"]}"/>'},
    )
    assert unknown_type.status_code == 422
    assert unknown_type.json()["detail"]["code"] == "FORM_TYPE_UNKNOWN"

    missing_field = client.post(
        f"{API}/forms/submit",
        headers=h,
        json={"xml": f'<Form formType="noon_report" terminalKey="{terminal["terminal_key"]}"><Field name="ifo_rob">1</Field></Form>'},
    )
    assert missing_field.status_code == 422
    assert missing_field.json()["detail"]["code"] == "FORM_FIELD_MISSING"

    no_terminal = client.post(
        f"{API}/forms/submit",
        headers=h,
        json={"xml": '<Form formType="noon_report"><Field name="mt_per_day">1</Field></Form>'},
    )
    assert no_terminal.status_code == 422
    assert no_terminal.json()["detail"]["code"] == "FORM_TERMINAL_REQUIRED"


def test_payment_batch_export_xml_still_wired(client, auth_headers):
    """D3 已有实现/测试覆盖（test_finance_depth）；此处只确认路由挂载存在。"""
    h = auth_headers
    r = client.get(f"{API}/payments/batches/{uuid4()}/export-xml", headers=h)
    assert r.status_code in (404, 400, 422)


# ── E. Master data additions ────────────────────────────────────────────


def test_reference_ext_crud(client, auth_headers):
    h = auth_headers

    # Holiday calendar
    cal_in = {
        "name": "China 2026",
        "country_code": "CN",
        "year": 2026,
        "holidays": [{"date": "2026-01-01", "name": "New Year", "type": "public"}],
    }
    cal = client.post(f"{API}/masterdata/holiday-calendars", headers=h, json=cal_in)
    assert cal.status_code == 201, cal.text
    cal_row = cal.json()
    assert cal_row["year"] == 2026
    assert cal_row["holidays"][0]["date"] == "2026-01-01"
    assert client.get(f"{API}/masterdata/holiday-calendars/{cal_row['id']}", headers=h).status_code == 200
    assert any(
        x["id"] == cal_row["id"]
        for x in client.get(f"{API}/masterdata/holiday-calendars?year=2026&country_code=CN", headers=h).json()
    )
    up = client.patch(
        f"{API}/masterdata/holiday-calendars/{cal_row['id']}",
        headers=h,
        json={**cal_in, "name": "China 2026 (rev)"},
    )
    assert up.status_code == 200 and up.json()["name"] == "China 2026 (rev)"
    assert client.delete(f"{API}/masterdata/holiday-calendars/{cal_row['id']}", headers=h).json()["ok"] is True
    assert client.get(f"{API}/masterdata/holiday-calendars/{cal_row['id']}", headers=h).status_code == 404

    # Working day pattern
    pat_in = {"name": f"SHINC {uuid4().hex[:4]}", "monday": True, "saturday": True, "sunday": False, "is_default": True}
    pat = client.post(f"{API}/masterdata/working-day-patterns", headers=h, json=pat_in)
    assert pat.status_code == 201, pat.text
    pat_row = pat.json()
    assert pat_row["saturday"] is True and pat_row["sunday"] is False
    assert client.get(f"{API}/masterdata/working-day-patterns/{pat_row['id']}", headers=h).json()["monday"] is True
    assert any(x["id"] == pat_row["id"] for x in client.get(f"{API}/masterdata/working-day-patterns", headers=h).json())
    up2 = client.patch(
        f"{API}/masterdata/working-day-patterns/{pat_row['id']}",
        headers=h,
        json={**pat_in, "name": pat_row["name"], "sunday": True},
    )
    assert up2.status_code == 200 and up2.json()["sunday"] is True
    assert client.delete(f"{API}/masterdata/working-day-patterns/{pat_row['id']}", headers=h).json()["ok"] is True

    # Term list
    term_in = {
        "category": "laytime_terms",
        "code": f"WWD {uuid4().hex[:4]}",
        "label_en": "Weather Working Day",
        "label_zh": "天气工作日",
        "sort_order": 10,
        "is_active": True,
    }
    term = client.post(f"{API}/masterdata/term-lists", headers=h, json=term_in)
    assert term.status_code == 201, term.text
    term_row = term.json()
    assert term_row["category"] == "laytime_terms"
    assert client.get(f"{API}/masterdata/term-lists/{term_row['id']}", headers=h).json()["label_zh"] == "天气工作日"
    assert any(
        x["id"] == term_row["id"]
        for x in client.get(f"{API}/masterdata/term-lists?category=laytime_terms&active_only=true", headers=h).json()
    )
    up3 = client.patch(
        f"{API}/masterdata/term-lists/{term_row['id']}", headers=h, json={**term_in, "is_active": False}
    )
    assert up3.status_code == 200 and up3.json()["is_active"] is False
    assert client.delete(f"{API}/masterdata/term-lists/{term_row['id']}", headers=h).json()["ok"] is True

    # Standard paragraph
    para_in = {
        "category": "cp_clause",
        "code": f"CP-{uuid4().hex[:4]}",
        "title": "Deviation Clause",
        "content": "The Vessel shall not deviate...",
        "is_system": False,
    }
    para = client.post(f"{API}/masterdata/standard-paragraphs", headers=h, json=para_in)
    assert para.status_code == 201, para.text
    para_row = para.json()
    assert para_row["content"].startswith("The Vessel")
    assert client.get(f"{API}/masterdata/standard-paragraphs/{para_row['id']}", headers=h).status_code == 200
    assert any(
        x["id"] == para_row["id"]
        for x in client.get(f"{API}/masterdata/standard-paragraphs?category=cp_clause", headers=h).json()
    )
    up4 = client.patch(
        f"{API}/masterdata/standard-paragraphs/{para_row['id']}",
        headers=h,
        json={**para_in, "title": "Deviation Clause (rev)"},
    )
    assert up4.status_code == 200 and up4.json()["title"] == "Deviation Clause (rev)"
    assert client.delete(f"{API}/masterdata/standard-paragraphs/{para_row['id']}", headers=h).json()["ok"] is True
    assert client.get(f"{API}/masterdata/standard-paragraphs/{para_row['id']}", headers=h).status_code == 404
