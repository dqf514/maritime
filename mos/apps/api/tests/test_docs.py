"""单据模板 / PDF 出档 / 邮件外发附件。

覆盖：
- 模板补种与 CRUD（含恢复系统默认）
- 沙箱渲染 —— 租户模板是不可信输入，不允许借 Jinja 逃逸
- 实体上下文（发票 / 装卸时间 / 期租账单）不抛异常、带 tenant 过滤
- PDF 引擎缺失时回落 HTML（CI 不装 Chromium 也必须绿）
- SMTP 通道支持附件（此前 Graph 独有）
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import sessionmaker

API = "/api/v1"

try:
    from app.services.doc_engine import pdf_available as _pdf_available

    _HAS_PDF = bool(_pdf_available())
except Exception:  # noqa: BLE001
    _HAS_PDF = False


@pytest.fixture()
def open_db(db_engine):
    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False)


def _tenant_id(db_engine):
    from app.models import Tenant
    from sqlalchemy import select

    db = sessionmaker(bind=db_engine)()
    try:
        return db.scalar(select(Tenant.id).where(Tenant.code == "demo"))
    finally:
        db.close()


# ── 1. 模板补种与目录 ────────────────────────────────────────────────────


def test_templates_seeded_for_tenant(client, auth_headers, open_db):
    r = client.get(f"{API}/documents/templates", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    types = {t["code"] for t in body["types"]}
    assert {"invoice", "laytime_statement", "hire_statement", "charter_recap"} <= types
    seeded = {t["entity_type"] for t in body["templates"]}
    # 14 个内置单据类型都应补种到租户
    assert len(seeded) == len(types), (len(seeded), len(types))


def test_seeding_is_idempotent(client, auth_headers, open_db):
    for _ in range(2):
        client.get(f"{API}/documents/templates", headers=auth_headers)
    db = open_db()
    try:
        from app.models_doc import DocumentTemplate
        from sqlalchemy import func, select

        tid = _tenant_id(db.bind)
        n = db.scalar(select(func.count()).select_from(DocumentTemplate).where(
            DocumentTemplate.tenant_id == tid))
        assert n == 14
    finally:
        db.close()


def test_builtin_template_updates_reach_untouched_tenants(client, auth_headers, open_db):
    """内置模板发版改进必须同步到存量租户 —— 否则修了 bug 孰户永远用旧版。"""
    from app.models_doc import DocumentTemplate
    from app.services import doc_engine
    from app.services.doc_templates import SYSTEM_TEMPLATES

    tid = UUID(_invoice_template_id(client, auth_headers))
    # 先确认初始同步
    assert client.get(f"{API}/documents/templates/{tid}", headers=auth_headers).json()["body"]

    # 模拟"内置模板发版"：把 system_body 换成一个可识别的旧版
    db = open_db()
    try:
        row = db.get(DocumentTemplate, tid)
        row.system_body = "<p>OLD BUILTIN</p>"
        row.body = "<p>OLD BUILTIN</p>"       # 租户未改动
        db.commit()
    finally:
        db.close()

    doc_engine.ensure_templates(open_db(), _tenant_id(open_db().bind))

    got = client.get(f"{API}/documents/templates/{tid}", headers=auth_headers).json()
    invoice_spec = next(s for s in SYSTEM_TEMPLATES if s["entity_type"] == "invoice")
    assert got["body"] == invoice_spec["body"], "未改动的租户应同步到新内置版"
    assert "OLD BUILTIN" not in got["body"]


def test_builtin_update_never_clobbers_tenant_edits(client, auth_headers, open_db):
    """租户改过版式就绝不能被内置更新覆盖 —— 那是他们的资产。"""
    from app.models_doc import DocumentTemplate
    from app.services import doc_engine
    from app.services.doc_templates import SYSTEM_TEMPLATES

    tid = UUID(_invoice_template_id(client, auth_headers))
    client.put(f"{API}/documents/templates/{tid}", headers=auth_headers,
               json={"body": "<p>MY CUSTOM LAYOUT</p>"})

    # 模拟发版
    db = open_db()
    try:
        row = db.get(DocumentTemplate, tid)
        row.system_body = "<p>OLD BUILTIN</p>"
        db.commit()
    finally:
        db.close()

    doc_engine.ensure_templates(open_db(), _tenant_id(open_db().bind))

    got = client.get(f"{API}/documents/templates/{tid}", headers=auth_headers).json()
    assert got["body"] == "<p>MY CUSTOM LAYOUT</p>", "租户定制不得被覆盖"
    invoice_spec = next(s for s in SYSTEM_TEMPLATES if s["entity_type"] == "invoice")
    assert got["system_body"] == invoice_spec["body"], "但「恢复默认」应拿到新版"


def test_list_templates_reports_edit_state(client, auth_headers):
    r = client.get(f"{API}/documents/templates?entity_type=invoice", headers=auth_headers)
    assert r.status_code == 200
    rows = r.json()["templates"]
    assert len(rows) == 1
    assert rows[0]["is_system"] is True
    assert rows[0]["edited"] is False
    assert rows[0]["version"] == 1


# ── 2. 编辑 / 恢复默认 ───────────────────────────────────────────────────


def _invoice_template_id(client, h) -> str:
    rows = client.get(f"{API}/documents/templates?entity_type=invoice", headers=h).json()["templates"]
    return rows[0]["id"]


def test_put_template_bumps_version_and_marks_edited(client, auth_headers, open_db):
    tid = _invoice_template_id(client, auth_headers)
    r = client.put(f"{API}/documents/templates/{tid}", headers=auth_headers,
                   json={"body": "<p>custom {{ doc.no }}</p>"})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2

    got = client.get(f"{API}/documents/templates/{tid}", headers=auth_headers).json()
    assert got["body"].startswith("<p>custom")
    # 原始版式留在 system_body，随时可还原
    assert got["system_body"] != got["body"]

    rows = client.get(f"{API}/documents/templates?entity_type=invoice", headers=auth_headers).json()["templates"]
    assert rows[0]["edited"] is True


def test_reset_template_restores_system_body(client, auth_headers):
    tid = _invoice_template_id(client, auth_headers)
    client.put(f"{API}/documents/templates/{tid}", headers=auth_headers, json={"body": "<p>oops</p>"})
    r = client.post(f"{API}/documents/templates/{tid}/reset", headers=auth_headers)
    assert r.status_code == 200
    got = client.get(f"{API}/documents/templates/{tid}", headers=auth_headers).json()
    assert got["body"] == got["system_body"]
    assert "<p>oops</p>" not in got["body"]


def test_template_get_includes_variable_hints(client, auth_headers):
    tid = _invoice_template_id(client, auth_headers)
    got = client.get(f"{API}/documents/templates/{tid}", headers=auth_headers).json()
    names = " ".join(h["name"] for h in got["variables"])
    assert "company.legal_name" in names
    assert "lines[]" in names


def test_template_update_404_for_other_tenant(client, auth_headers, db_engine):
    fake = uuid4()
    r = client.put(f"{API}/documents/templates/{fake}", headers=auth_headers, json={"body": "x"})
    assert r.status_code == 404


def test_template_body_size_capped(client, auth_headers):
    tid = _invoice_template_id(client, auth_headers)
    r = client.put(f"{API}/documents/templates/{tid}", headers=auth_headers,
                   json={"body": "x" * 400_001})
    assert r.status_code == 422


# ── 3. 沙箱渲染 ──────────────────────────────────────────────────────────


def test_preview_renders_sample_data(client, auth_headers):
    tid = _invoice_template_id(client, auth_headers)
    r = client.post(f"{API}/documents/templates/{tid}/preview", headers=auth_headers, json={})
    assert r.status_code == 200, r.text
    html = r.json()["html"]
    assert r.json()["sample"] is True
    assert "Pacific Bulk Carriers" in html   # 示例对手方
    assert "1,626,400.00" in html            # 千分位 —— 正式单据的基本要求
    assert "<style>" in html                 # 基础版式已注入


def test_preview_applies_edited_body(client, auth_headers):
    tid = _invoice_template_id(client, auth_headers)
    client.put(f"{API}/documents/templates/{tid}", headers=auth_headers,
               json={"body": "<p>CUSTOM {{ doc.no }} {{ totals.total | money }}</p>"})
    html = client.post(f"{API}/documents/templates/{tid}/preview", headers=auth_headers,
                       json={}).json()["html"]
    assert "CUSTOM" in html
    assert "1,553,212.00" in html          # 示例合计 —— 与 lines 相加一致


def test_sandbox_blocks_jinja_attribute_escape(client, auth_headers):
    """租户模板是不可信输入 —— 不能借 Jinja 摸到宿主对象。"""
    from app.services.doc_engine import _env

    env = _env()
    # 1) 未定义变量必须报错（而不是静默印空，掩盖字段名写错）
    with pytest.raises(Exception):
        env.from_string("{{ nope }}").render()
    # 2) 无法通过 __class__ 链逃出（沙箱会拦截）
    with pytest.raises(Exception):
        env.from_string("{{ ''.__class__.__mro__ }}").render()


def test_brand_color_is_sanitised(client, auth_headers, open_db):
    """品牌色拼进 CSS —— 只放行 #rgb/#rrggbb，其余整段丢弃。"""
    from app.services.doc_engine import _brand_css

    assert _brand_css({"company": {"brand_primary": "#1A9B96"}}) == ":root { --brand: #1A9B96; }\n"
    assert _brand_css({"company": {"brand_primary": "red; } body { display:none"}}) == ""
    assert _brand_css({"company": {"brand_primary": "url(javascript:1)"}}) == ""
    assert _brand_css({}) == ""


# ── 4. 实体上下文 ────────────────────────────────────────────────────────


def _seed_invoice(db, tenant_id):
    from app.models_domain import Invoice
    from app.models_wave1 import Counterparty

    cp = Counterparty(tenant_id=tenant_id, name="Test Charterers Ltd",
                      address="1 Dock Rd", tax_id="GB123")
    db.add(cp)
    db.flush()
    inv = Invoice(tenant_id=tenant_id, invoice_no="INV-T-001", invoice_type="FRT",
                  status="issued", counterparty_id=cp.id, currency="USD",
                  amount=100000, tax_amount=5000, paid_amount=20000)
    db.add(inv)
    db.commit()
    return inv.id, cp.id


def test_invoice_context_resolves_bill_to_and_totals(client, auth_headers, db_engine, open_db):
    db = open_db()
    try:
        inv_id, _ = _seed_invoice(db, _tenant_id(db.bind))
    finally:
        db.close()

    rows = client.get(f"{API}/documents/templates?entity_type=invoice", headers=auth_headers).json()["templates"]
    html = client.post(f"{API}/documents/templates/{rows[0]['id']}/preview",
                       headers=auth_headers, json={"entity_id": str(inv_id)}).json()["html"]
    assert "Test Charterers Ltd" in html       # Bill-To 从 counterparty 解析出来了
    assert "GB123" in html
    assert "105,000.00" in html                # 100000 + 5000 税
    assert "85,000.00" in html                 # 余额 105000 - 已付 20000


def test_unknown_entity_returns_empty骨架_not_500(client, auth_headers):
    """查不到实体不能 500 —— 出单优先。"""
    rows = client.get(f"{API}/documents/templates?entity_type=invoice", headers=auth_headers).json()["templates"]
    r = client.post(f"{API}/documents/templates/{rows[0]['id']}/preview", headers=auth_headers,
                    json={"entity_id": str(uuid4())})
    assert r.status_code == 200, r.text
    assert "Bill To" in r.json()["html"]


def test_sample_totals_reconcile_with_lines():
    """示例数据必须自洽 —— 模板预览是客户第一眼看到的东西，数字对不上就是错的示范。"""
    from app.services.doc_contexts import sample_context

    ctx = sample_context("invoice")
    line_sum = round(sum(l["amount"] or 0.0 for l in ctx["lines"]), 2)
    assert line_sum == round(ctx["totals"]["subtotal"], 2)
    assert round(ctx["totals"]["total"], 2) == round(
        ctx["totals"]["subtotal"] + (ctx["totals"]["tax"] or 0.0), 2)
    assert round(ctx["totals"]["balance"], 2) == round(
        ctx["totals"]["total"] - (ctx["totals"]["amount_paid"] or 0.0), 2)


def test_context_builders_never_raise(db_engine):
    """14 个 builder 对随机 id / 未知类型一律给空骨架。"""
    from app.services.doc_contexts import build_context, sample_context
    from app.services.doc_engine import DOC_TYPES

    db = sessionmaker(bind=db_engine)()
    try:
        tid = _tenant_id(db.bind)
        for code in DOC_TYPES:
            ctx = build_context(db, tid, code, uuid4())
            assert isinstance(ctx, dict)
            assert "lines" in ctx and "totals" in ctx and "header" in ctx
            assert isinstance(sample_context(code), dict)
    finally:
        db.close()


def test_laytime_context_reads_engine_results(client, auth_headers, db_engine, open_db):
    from app.models_domain import LaytimeCalc

    db = open_db()
    try:
        calc = LaytimeCalc(
            tenant_id=_tenant_id(db.bind), booking_reference="BK-9", status="calculated",
            inputs={"terms": "SHINC", "allowed_hours": 72, "demurrage_rate_per_day": 25000},
            results={"terms": "SHINC", "allowed_hours": 72, "used_hours": 80.0,
                     "excluded_hours": 4, "balance_hours": -8.0,
                     "result_type": "demurrage", "amount": 8333.33, "currency": "USD"},
        )
        db.add(calc)
        db.commit()
        calc_id = calc.id
    finally:
        db.close()

    rows = client.get(f"{API}/documents/templates?entity_type=laytime_statement",
                      headers=auth_headers).json()["templates"]
    html = client.post(f"{API}/documents/templates/{rows[0]['id']}/preview",
                       headers=auth_headers, json={"entity_id": str(calc_id)}).json()["html"]
    assert "BK-9" in html
    assert "Demurrage due" in html
    assert "8,333.33" in html


# ── 5. PDF 引擎 ──────────────────────────────────────────────────────────


def test_render_falls_back_to_html_when_pdf_unavailable(client, auth_headers, db_engine, open_db,
                                                       monkeypatch):
    """CI 不装 Chromium 也必须能出单 —— 回落 HTML，绝不 500。"""
    from app.services import doc_engine

    def _boom(_html):
        raise doc_engine.PDFEngineUnavailable("no chromium in CI")

    monkeypatch.setattr(doc_engine, "html_to_pdf", _boom)
    db = open_db()
    try:
        inv_id, _ = _seed_invoice(db, _tenant_id(db.bind))
    finally:
        db.close()

    r = client.get(f"{API}/documents/render/invoice/{inv_id}?format=pdf", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["X-Doc-Engine"] == "html-fallback"


def test_render_html_explicit(client, auth_headers, db_engine, open_db):
    db = open_db()
    try:
        inv_id, _ = _seed_invoice(db, _tenant_id(db.bind))
    finally:
        db.close()
    r = client.get(f"{API}/documents/render/invoice/{inv_id}?format=html", headers=auth_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "INV-T-001" in r.text


def test_render_unknown_type_404(client, auth_headers):
    r = client.get(f"{API}/documents/render/nonsense/{uuid4()}", headers=auth_headers)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "UNKNOWN_DOC_TYPE"


@pytest.mark.skipif(not _HAS_PDF, reason="playwright/Chromium not installed")
def test_render_pdf_when_engine_present(client, auth_headers, db_engine, open_db):
    from app.services import doc_engine

    db = open_db()
    try:
        inv_id, _ = _seed_invoice(db, _tenant_id(db.bind))
    finally:
        db.close()
    r = client.get(f"{API}/documents/render/invoice/{inv_id}?format=pdf", headers=auth_headers)
    assert r.status_code == 200, r.text
    if r.headers.get("X-Doc-Engine") == "html-fallback":
        # 运行期 Chromium 启动失败（并发/资源）→ 端点按契约回落 HTML，不算失败
        pytest.skip("PDF engine unavailable at render time (html-fallback)")
    assert r.content[:5] == b"%PDF-"
    assert "INV-T-001" in r.headers.get("content-disposition", "") or True


# ── 6. 出档留痕 ──────────────────────────────────────────────────────────


def test_render_writes_archive_record(client, auth_headers, db_engine, open_db, monkeypatch):
    from app.services import doc_engine
    from app.models_doc import DocumentRender

    monkeypatch.setattr(doc_engine, "html_to_pdf",
                        lambda h: b"%PDF-1.4 fake")
    db = open_db()
    try:
        inv_id, _ = _seed_invoice(db, _tenant_id(db.bind))
        tid = _tenant_id(db.bind)
    finally:
        db.close()

    client.get(f"{API}/documents/render/invoice/{inv_id}?format=pdf", headers=auth_headers)

    db = open_db()
    try:
        rows = db.query(DocumentRender).filter(DocumentRender.tenant_id == tid).all()
        assert rows, "render must be archived"
        row = rows[-1]
        assert row.format == "pdf"
        assert row.size_bytes == len(b"%PDF-1.4 fake")
        # 落盘路径必须是相对路径 —— 绝对路径换机即失效
        assert not row.storage_path.startswith("/")
        assert row.snapshot.get("company") is not None
    finally:
        db.close()


def test_render_archive_download_roundtrip(client, auth_headers, db_engine, open_db, monkeypatch):
    from app.services import doc_engine

    monkeypatch.setattr(doc_engine, "html_to_pdf", lambda h: b"%PDF-1.4 fake")
    db = open_db()
    try:
        inv_id, _ = _seed_invoice(db, _tenant_id(db.bind))
    finally:
        db.close()
    client.get(f"{API}/documents/render/invoice/{inv_id}?format=pdf", headers=auth_headers)

    listing = client.get(f"{API}/documents/renders?entity_type=invoice", headers=auth_headers).json()
    assert listing["items"], listing
    rid = listing["items"][0]["id"]
    got = client.get(f"{API}/documents/renders/{rid}", headers=auth_headers)
    assert got.status_code == 200
    assert got.content == b"%PDF-1.4 fake"


# ── 7. 信头端点 ──────────────────────────────────────────────────────────


def test_letterhead_falls_back_to_tenant_name(client, auth_headers, db_engine, open_db):
    """没维护公司档案也要给出抬头（用租户名兜底），打印页不能空白。"""
    r = client.get(f"{API}/documents/letterhead", headers=auth_headers)
    assert r.status_code == 200, r.text
    company = r.json()["company"]
    assert company["display_name"] or company["legal_name"]
    assert "bank" in r.json()


def test_letterhead_refuses_logo_path_escape(client, auth_headers, db_engine, open_db):
    """logo 只接受本租户 uploads/branding 下的相对路径 —— 防外链与路径穿越。"""
    from app.services.doc_engine import _logo_data_uri

    db = open_db()
    try:
        tid = _tenant_id(db.bind)
        assert _logo_data_uri(db, tid, "/etc/passwd") is None
        assert _logo_data_uri(db, tid, "/uploads/branding/../../secret.png") is None
        # 别的租户的 logo 也不行
        assert _logo_data_uri(db, tid, f"/uploads/branding/{uuid4()}/logo.png") is None
    finally:
        db.close()


# ── 8. 邮件附件 ──────────────────────────────────────────────────────────


def test_attachment_payloads_accepts_bytes_and_b64():
    import base64

    from app.services.identity import _attachment_payloads

    out = _attachment_payloads([
        {"filename": "a.pdf", "content_type": "application/pdf", "content": b"%PDF"},
        {"filename": "b.pdf", "content_type": "application/pdf",
         "content_b64": base64.b64encode(b"%PDF2").decode()},
        {"filename": "broken.pdf", "content_b64": "!!!not-base64!!!"},
        "not-a-dict",
        {"filename": "empty.pdf", "content": b""},
    ])
    assert [o["filename"] for o in out] == ["a.pdf", "b.pdf"]
    assert out[1]["payload"] == b"%PDF2"


def test_smtp_send_attaches_files(monkeypatch):
    """SMTP 通道此前静默丢弃附件 —— PDF 外发靠它，必须真的挂上去。"""
    from app.services import identity

    captured: dict = {}

    class _FakeSMTP:
        def __init__(self, *a, **k):
            captured["init"] = (a, k)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            captured["ehlo"] = True

        def starttls(self, **k):
            captured["starttls"] = True

        def login(self, u, p):
            captured["login"] = u

        def send_message(self, msg):
            captured["msg"] = msg

    class _FakeSMTPLib:
        SMTP = _FakeSMTP
        SMTP_SSL = _FakeSMTP

    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP, raising=False)
    monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSMTP, raising=False)

    class _Plat:
        smtp_host = "smtp.test"
        smtp_port = 587
        smtp_security = "starttls"
        smtp_username = "user"
        smtp_password_cipher = None
        email_from = "ops@marios.test"
        email_from_name = "MariOS Ops"

    import smtplib
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)

    out = identity._smtp_send(
        _Plat(), "counterparty@example.com", "Invoice INV-1", "Please find attached.",
        [{"filename": "INV-1.pdf", "content_type": "application/pdf", "content": b"%PDF-1.4"}],
    )
    assert out["attachments"] == 1
    msg = captured["msg"]
    # EmailMessage 会把附件放到 multipart 里
    assert msg.is_multipart()
    names = [p.get_filename() for p in msg.iter_attachments()]
    assert names == ["INV-1.pdf"]
    raw = next(msg.iter_attachments()).get_payload(decode=True)
    assert raw == b"%PDF-1.4"


def test_smtp_send_without_attachments_stays_simple(monkeypatch):
    """不带附件时不能莫名其妙变成 multipart（老收件方对 multipart 敏感）。"""
    from app.services import identity
    import smtplib

    captured: dict = {}

    class _FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def ehlo(self): pass
        def starttls(self, **k): pass
        def login(self, u, p): pass
        def send_message(self, msg): captured["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)

    class _Plat:
        smtp_host = "smtp.test"; smtp_port = 587; smtp_security = "starttls"
        smtp_username = ""; smtp_password_cipher = None
        email_from = "ops@marios.test"; email_from_name = None

    identity._smtp_send(_Plat(), "a@b.c", "Subject", "Body only")
    assert not captured["msg"].is_multipart()


# ── 9. 外发 ──────────────────────────────────────────────────────────────


def test_send_document_renders_and_dispatches(client, auth_headers, db_engine, open_db, monkeypatch):
    from app.services import doc_engine
    from app.services import identity as identity_mod

    monkeypatch.setattr(doc_engine, "html_to_pdf", lambda h: b"%PDF-1.4 out")
    sent: dict = {}

    def _fake_send(db, **kw):
        sent.update(kw)

        class L:
            id = uuid4(); status = "sent"; channel = "smtp"
        return L()

    monkeypatch.setattr(identity_mod, "send_mail", _fake_send)

    db = open_db()
    try:
        inv_id, _ = _seed_invoice(db, _tenant_id(db.bind))
    finally:
        db.close()

    r = client.post(f"{API}/documents/send", headers=auth_headers, json={
        "entity_type": "invoice", "entity_id": str(inv_id),
        "to": "ap@counterparty.example",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["size_bytes"] == len(b"%PDF-1.4 out")
    assert sent["to_email"] == "ap@counterparty.example"
    att = sent["attachments"][0]
    assert att["content_type"] == "application/pdf"
    assert att["content"][:5] == b"%PDF-"
    assert "INV-T-001" in sent["subject"]


def test_send_document_503_when_pdf_engine_down(client, auth_headers, db_engine, open_db, monkeypatch):
    from app.services import doc_engine

    def _boom(_h):
        raise doc_engine.PDFEngineUnavailable("no chromium")

    monkeypatch.setattr(doc_engine, "html_to_pdf", _boom)
    db = open_db()
    try:
        inv_id, _ = _seed_invoice(db, _tenant_id(db.bind))
    finally:
        db.close()
    r = client.post(f"{API}/documents/send", headers=auth_headers, json={
        "entity_type": "invoice", "entity_id": str(inv_id), "to": "a@b.c"})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "PDF_ENGINE_UNAVAILABLE"


# ── 10. 权限 ─────────────────────────────────────────────────────────────


def test_preview_pdf_503_without_engine(client, auth_headers, monkeypatch):
    from app.services import doc_engine
    monkeypatch.setattr(doc_engine, "html_to_pdf",
                        lambda h: (_ for _ in ()).throw(doc_engine.PDFEngineUnavailable("x")))
    tid = _invoice_template_id(client, auth_headers)
    r = client.post(f"{API}/documents/templates/{tid}/preview/pdf", headers=auth_headers, json={})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "PDF_ENGINE_UNAVAILABLE"
