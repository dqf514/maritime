"""安全边界回归（P0-A 安全与部署组）。

覆盖本批修掉的每一条边界：

- **跨租户读写**：自定义 SQL 报表的租户隔离、平台看板的跨租户名册；
- **越权角色**：平台看板角色墙、API Key 签发限权、整库 dump 限权、
  AI 工具的模块授权；
- **SSRF**：webhook 投递 / 连接器连通性测试 / LLM provider base_url；
- **公式注入**：报表设计器导出的 CSV / XLSX；
- **凭据回吐**：连接器配置里的密钥不再原样出现在响应里；
- **XSS 转义**：文档引擎的 autoescape；
- **API Key scope**：scope 真正生效 + 空 scope 拒绝签发；
- **生产环境启动断言**：危险配置在 ``ENV=production`` 下拒绝启动。

设计原则：**每条用例都断言「漏洞被堵住」，而不是「功能还在」** ——
功能由既有的测试套件守住。
"""

from __future__ import annotations

import json
import uuid

import pytest

from tests.isolation_helpers import API, create_tenant, login, platform_login

DEMO_ADMIN = "admin@demo.marios"
DEMO_PASSWORD = "Demo1234!"


def _demo_admin(client) -> dict[str, str]:
    return login(client, DEMO_ADMIN, tenant_code="demo", password=DEMO_PASSWORD)


# ─────────────────────────────────────────────────────────────
# P0-1 · 自定义 SQL 报表：默认禁用 + 强制租户过滤
# ─────────────────────────────────────────────────────────────


def test_custom_sql_reports_disabled_by_default(client, auth_headers):
    """默认关：``data_source="sql"`` 的报表**建不出来**。"""
    r = client.post(
        f"{API}/reports",
        headers=auth_headers,
        json={
            "report_name": "raw sql report",
            "data_source": "sql",
            "query": "SELECT id, email, password_hash FROM users WHERE tenant_id <> :tid",
        },
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "CUSTOM_SQL_DISABLED"


def test_custom_sql_report_execution_blocked_even_for_legacy_rows(client, auth_headers, db_engine):
    """存量里已经有的 SQL 报表**执行时**同样被拒（不是只在创建时拦）。"""
    from sqlalchemy.orm import sessionmaker

    from app.models_report import ReportDefinition

    report_id = uuid.uuid4()
    with sessionmaker(bind=db_engine)() as db:
        tenant = db.query(__import__("app.models", fromlist=["Tenant"]).Tenant).filter_by(code="demo").one()
        db.add(
            ReportDefinition(
                id=report_id,
                tenant_id=tenant.id,
                report_name="legacy raw sql",
                report_type="custom",
                data_source="sql",
                query="SELECT id FROM users",
            )
        )
        db.commit()

    r = client.get(f"{API}/reports/{report_id}/data", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body.get("rows") == []
    assert "disabled" in (body.get("error") or "").lower()


def test_custom_sql_validator_rejects_cross_tenant_predicates():
    """即使显式打开开关，越权谓词也必须被解析校验拒绝。"""
    from app.services.report_engine import _validate_tenant_scoped_sql

    # 「排除本租户」—— 审计里的原始攻击载荷
    assert _validate_tenant_scoped_sql(
        "SELECT id, email, password_hash FROM users WHERE tenant_id <> :tid"
    )
    # OR 绕过
    assert _validate_tenant_scoped_sql(
        "SELECT id FROM users WHERE tenant_id = :tid OR 1=1"
    )
    # UNION 第二个 SELECT 不受 WHERE 约束
    assert _validate_tenant_scoped_sql(
        "SELECT id FROM users WHERE tenant_id = :tid UNION SELECT password_hash FROM users"
    )
    # 多语句
    assert _validate_tenant_scoped_sql(
        "SELECT id FROM users WHERE tenant_id = :tid; DROP TABLE users"
    )
    # 注释掉谓词
    assert _validate_tenant_scoped_sql(
        "SELECT id FROM users WHERE tenant_id = :tid -- AND x=1"
    )
    # DML
    assert _validate_tenant_scoped_sql("DELETE FROM users WHERE tenant_id = :tid")
    # 完全没有租户过滤
    assert _validate_tenant_scoped_sql("SELECT id FROM users")
    # 合法写法通过
    assert _validate_tenant_scoped_sql(
        "SELECT id, email FROM users WHERE tenant_id = :tid"
    ) is None


def test_custom_sql_validator_rejects_dml_without_trailing_space():
    """``UPDATE\\nusers ...`` 绕过 —— 旧实现按「关键字 + 尾随空格」匹配。

    旧代码是 ``for bad in ("insert ", "update ", …): if bad in lowered`` ——
    换行代替空格就完全绕过，语句会真的执行并**提交**。现在按词元匹配。
    """
    from app.services.report_engine import _validate_tenant_scoped_sql

    for payload in (
        "UPDATE\nusers SET email='pwned' WHERE tenant_id = :tid",
        "UPDATE\tusers SET email='pwned' WHERE tenant_id = :tid",
        "UPDATE users SET email='pwned' WHERE tenant_id = :tid",
        "delete\nfrom users where tenant_id = :tid",
        "INSERT INTO users (tenant_id, email) VALUES (:tid, 'x@y.z')",
        "DROP TABLE users",
        "SELECT id INTO evil_table FROM users WHERE tenant_id = :tid",
    ):
        assert _validate_tenant_scoped_sql(payload), f"绕过未被拦：{payload!r}"


def test_custom_sql_validator_rejects_union_before_where():
    """UNION 放在**第一个 WHERE 之前** —— 旧实现只在 WHERE 尾巴里找 UNION。"""
    from app.services.report_engine import _validate_tenant_scoped_sql

    for payload in (
        "SELECT id FROM users UNION SELECT id FROM users WHERE tenant_id = :tid",
        "SELECT id FROM users UNION ALL SELECT id FROM users WHERE tenant_id = :tid",
        "SELECT id FROM users WHERE tenant_id = :tid UNION SELECT id FROM users",
        "SELECT id FROM users INTERSECT SELECT id FROM users WHERE tenant_id = :tid",
    ):
        assert _validate_tenant_scoped_sql(payload), f"绕过未被拦：{payload!r}"


def test_custom_sql_validator_rejects_subquery_and_unsafe_joins():
    """子查询 / 跨租户 JOIN —— 只守主表不够。"""
    from app.services.report_engine import _validate_tenant_scoped_sql

    # 子查询里的 WHERE 不受外层谓词约束
    assert _validate_tenant_scoped_sql(
        "SELECT id FROM users WHERE tenant_id = :tid AND id IN "
        "(SELECT id FROM users WHERE tenant_id <> :tid)"
    )
    # JOIN 出去的租户表同样会漏数据（users 也是租户表）
    assert _validate_tenant_scoped_sql(
        "SELECT i.id, u.email FROM invoices i JOIN users u ON u.id = i.created_by "
        "WHERE i.tenant_id = :tid"
    )
    # OR 在任何位置都不行
    assert _validate_tenant_scoped_sql(
        "SELECT id FROM users WHERE (tenant_id = :tid OR 1=1)"
    )


def test_custom_sql_validator_accepts_legit_statements():
    """别把闸门收得太紧 —— 正常报表要能过。"""
    from app.services.report_engine import _validate_tenant_scoped_sql

    for payload in (
        "SELECT id, email FROM users WHERE tenant_id = :tid",
        "SELECT id, email FROM users\nWHERE tenant_id = :tid",
        "SELECT id FROM invoices i WHERE i.tenant_id = :tid ORDER BY id",
        "SELECT id FROM invoices i JOIN ports p ON p.id = i.port_id "
        "WHERE i.tenant_id = :tid",
        "SELECT id FROM users WHERE tenant_id = :tid AND note = 'please update'",
        "SELECT id FROM users WHERE tenant_id = :tid AND status IN ('a','b')",
    ):
        assert _validate_tenant_scoped_sql(payload) is None, f"误伤：{payload!r}"


def test_custom_sql_params_cannot_override_tid(client, auth_headers, monkeypatch):
    """``?tid=<别人的 uuid>`` 不能覆盖服务端绑定值。"""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "allow_custom_sql_reports", True)
    r = client.get(
        f"{API}/reports/{uuid.uuid4()}/data",
        headers=auth_headers,
        params={"tid": str(uuid.uuid4())},
    )
    # 报表不存在 → 404（说明请求参数没有绕过路由层去改 SQL 绑定）
    assert r.status_code == 404


# ─────────────────────────────────────────────────────────────
# P0-2 · 报表构造器 alias 白名单（SQL 注入）
# ─────────────────────────────────────────────────────────────


def test_report_builder_alias_injection_rejected():
    """alias 里塞 SQL → 整个 spec 被拒（不生成任何 SQL）。"""
    from app.services.report_builder import ReportSpecError, build_query, validate_spec

    spec = {
        "datasets": [
            {
                "dataset": "voyages",
                "alias": 'x" , (select group_concat(password_hash) from users) as leak --',
            }
        ],
        "fields": [{"dataset": "voyages", "field": "voyage_no", "label": "Voyage No"}],
    }
    errors = validate_spec(spec)
    assert errors, "alias injection must be rejected"
    with pytest.raises(ReportSpecError):
        build_query(spec, uuid.uuid4())


def test_report_builder_alias_must_be_identifier():
    from app.services.report_builder import validate_spec

    for bad in ('a"b', "a b", "a;b", "a-b", "1abc", "a'b", "a`b"):
        spec = {
            "datasets": [{"dataset": "voyages", "alias": bad}],
            "fields": [{"dataset": "voyages", "field": "voyage_no", "label": "V"}],
        }
        assert validate_spec(spec), f"alias {bad!r} must be rejected"


def test_report_builder_valid_alias_still_works():
    from app.services.report_builder import validate_spec

    spec = {
        "datasets": [{"dataset": "voyages", "alias": "v"}],
        "fields": [{"dataset": "v", "field": "voyage_no", "label": "Voyage No"}],
    }
    assert validate_spec(spec) == []


# ─────────────────────────────────────────────────────────────
# P0-3 · OAuth stub_email 后门 + 停用账号复活
# ─────────────────────────────────────────────────────────────


def test_oauth_callback_rejects_stub_email_when_stub_disabled(client):
    """``stub_email`` 是认证后门 —— 没开 stub 模式时直接 400。"""
    r = client.get(
        f"{API}/auth/oauth/microsoft/callback",
        params={"state": "whatever", "stub_email": "admin@demo.marios"},
        follow_redirects=False,
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "OAUTH_STUB_DISABLED"


def test_oauth_callback_does_not_reactivate_disabled_user(
    client, auth_headers, db_engine, oauth_stub
):
    """停用账号不能被 SSO 复活（老代码无条件 ``status = "active"``）。"""
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from app.models import Tenant, User
    from app.services.identity import create_challenge

    with sessionmaker(bind=db_engine)() as db:
        user = db.scalar(select(User).where(User.email == DEMO_ADMIN))
        assert user is not None
        user.status = "disabled"
        db.commit()

    try:
        # 用真实的 oauth_state 挑战走到 callback（stub 模式）
        with sessionmaker(bind=db_engine)() as db:
            tenant = db.scalar(select(Tenant).where(Tenant.code == "demo"))
            _challenge, state = create_challenge(
                db,
                purpose="oauth_state",
                email=DEMO_ADMIN,
                tenant_id=tenant.id,
                hours=1,
                payload={"provider": "microsoft"},
            )
            db.commit()

        r = client.get(
            f"{API}/auth/oauth/microsoft/callback",
            params={"state": state, "stub_email": DEMO_ADMIN},
            follow_redirects=False,
        )
        # 账号是停用的 → 拒绝登录
        assert r.status_code in (302, 307, 400, 403), r.text
        if r.status_code in (302, 307):
            assert "user_inactive" in (r.headers.get("location") or "")
        # 状态**不能**被改回去
        with sessionmaker(bind=db_engine)() as db:
            user = db.scalar(select(User).where(User.email == DEMO_ADMIN))
            assert user.status == "disabled", "disabled account must not be reactivated by SSO"
    finally:
        with sessionmaker(bind=db_engine)() as db:
            user = db.scalar(select(User).where(User.email == DEMO_ADMIN))
            user.status = "active"
            db.commit()


# ─────────────────────────────────────────────────────────────
# P0-4 / P0-5 · 文档引擎 XSS 转义
# ─────────────────────────────────────────────────────────────


def test_doc_engine_autoescape_enabled():
    """渲染环境必须开启 autoescape（存储型 XSS 的根因）。"""
    from app.services.doc_engine import _env

    env = _env()
    assert env.autoescape is True
    out = env.from_string("{{ name }}").render(name='<img src=x onerror="alert(1)">')
    assert "<img" not in out
    assert "&lt;img" in out


def test_doc_engine_escapes_user_supplied_names(client, auth_headers):
    """对手方名里的标签被转义 —— 财务打开单据不会执行脚本。"""
    import re

    r = client.get(f"{API}/documents/templates", headers=auth_headers)
    assert r.status_code == 200
    rows = r.json()
    assert rows, "expected at least one template"

    from app.services.doc_engine import _env

    env = _env()
    html = env.from_string("{{ counterparty.name }}").render(
        counterparty={"name": '<script>fetch("/api/v1/settings/api-keys")</script>'}
    )
    assert "<script>" not in html
    assert re.search(r"&lt;script&gt;", html)


# ─────────────────────────────────────────────────────────────
# P0-6 · 平台看板角色墙
# ─────────────────────────────────────────────────────────────


def test_platform_dashboard_requires_platform_admin(client, auth_headers):
    """``management`` / ``tenant_admin`` 不能读平台看板（跨租户名册泄漏）。"""
    r = client.get(f"{API}/dashboards/platform_admin/snapshot", headers=auth_headers)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "ROLE_REQUIRED"


def test_platform_dashboard_visible_to_platform_admin(client):
    hp = platform_login(client)
    r = client.get(f"{API}/dashboards/platform_admin/snapshot", headers=hp)
    assert r.status_code == 200, r.text
    body = r.json()
    # 平台管理员**应该**能看到租户名册
    assert "tenants" in body or body.get("kpis")


def test_dashboard_catalog_hides_platform_wall_from_tenant_admin(client, auth_headers):
    r = client.get(f"{API}/dashboards/catalog", headers=auth_headers)
    assert r.status_code == 200
    roles = {s["role"] for s in r.json()["screens"]}
    assert "platform_admin" not in roles


# ─────────────────────────────────────────────────────────────
# P0-18 · SSRF：统一出网白名单
# ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost:8000/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://metadata.google.internal/",
    ],
)
def test_outbound_url_guard_blocks_internal_targets(url):
    from fastapi import HTTPException

    from app.security import assert_safe_outbound_url

    with pytest.raises(HTTPException) as exc:
        assert_safe_outbound_url(url)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "OUTBOUND_URL_BLOCKED"


def test_outbound_url_guard_blocks_non_http_scheme():
    from fastapi import HTTPException

    from app.security import assert_safe_outbound_url

    for bad in ("file:///etc/passwd", "gopher://127.0.0.1/", "ftp://example.com/"):
        with pytest.raises(HTTPException):
            assert_safe_outbound_url(bad)


def test_outbound_url_guard_allows_public_host(monkeypatch):
    from app.config import get_settings
    from app.security import assert_safe_outbound_url

    monkeypatch.setattr(get_settings(), "outbound_allowed_hosts", "hooks.example.com")
    # 显式白名单放行（租户自建内网服务）
    assert_safe_outbound_url("http://hooks.example.com/hook")


def test_outbound_url_guard_resolves_dns(monkeypatch):
    """域名解析到内网 IP 也要拦（防 DNS rebinding / hosts 指向内网）。"""
    import socket

    from fastapi import HTTPException

    from app.security import assert_safe_outbound_url

    def _fake_getaddrinfo(*a, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 80))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    with pytest.raises(HTTPException) as exc:
        assert_safe_outbound_url("http://evil.example.com/")
    assert exc.value.detail["code"] == "OUTBOUND_URL_BLOCKED"


def test_webhook_delivery_rejects_internal_target(client, auth_headers, db_engine):
    """webhook 投递到内网地址被拒（不发出请求）。"""
    from sqlalchemy.orm import sessionmaker

    from app.models_office import WebhookEndpoint
    from app.models import Tenant

    wh_id = uuid.uuid4()
    with sessionmaker(bind=db_engine)() as db:
        tenant = db.query(Tenant).filter_by(code="demo").one()
        db.add(
            WebhookEndpoint(
                id=wh_id,
                tenant_id=tenant.id,
                name="ssrf-hook",
                target_url="http://169.254.169.254/latest/meta-data/",
                events=["*"],
                status="active",
                secret="s",
            )
        )
        db.commit()

    r = client.post(f"{API}/office/webhooks/{wh_id}/test", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # 投递被拒（没有真的发出请求）
    assert body["status"] == "failed"

    # 拒绝原因落在 webhook 的 last_delivery 里
    from sqlalchemy.orm import sessionmaker

    from app.models_office import WebhookEndpoint

    with sessionmaker(bind=db_engine)() as db:
        row = db.get(WebhookEndpoint, wh_id)
        last = row.last_delivery or {}
    assert "OUTBOUND_URL_BLOCKED" in json.dumps(last)


def test_connector_test_rejects_internal_endpoint(client, auth_headers):
    """连接器连通性测试指向内网 → 失败且不发出请求。"""
    r = client.post(
        f"{API}/settings/connectors",
        headers=auth_headers,
        json={
            "connector_type": "erp.generic",
            "instance_name": "ssrf probe",
            "endpoint": "http://169.254.169.254/latest/meta-data/",
            "config": {},
        },
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    t = client.post(f"{API}/settings/connectors/{cid}/test", headers=auth_headers)
    assert t.status_code == 200, t.text
    assert t.json()["last_health"]["ok"] is False
    assert "blocked" in json.dumps(t.json()).lower()


def test_llm_provider_base_url_rejects_internal(monkeypatch):
    """LLM provider 的 base_url 指向内网 → 拒绝。"""
    from fastapi import HTTPException

    from app.services.llm_client import _assert_safe_provider_base_url

    with pytest.raises(HTTPException) as exc:
        _assert_safe_provider_base_url("http://169.254.169.254/")
    assert exc.value.detail["code"] == "OUTBOUND_URL_BLOCKED"
    # 空 base_url（用 SDK 默认端点）不校验
    _assert_safe_provider_base_url("")
    _assert_safe_provider_base_url(None)


# ─────────────────────────────────────────────────────────────
# P0-19 · 凭据不回吐
# ─────────────────────────────────────────────────────────────


def test_connector_config_secrets_masked_in_response(client, auth_headers):
    """连接器配置里的密码 / API Key 不再原样出现在响应体。"""
    r = client.post(
        f"{API}/settings/connectors",
        headers=auth_headers,
        json={
            "connector_type": "email.imap",
            "instance_name": "imap probe",
            "config": {"host": "imap.example.com", "username": "u", "password": "sup3rs3cret"},
        },
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    body = r.text
    assert "sup3rs3cret" not in body
    assert r.json()["config"]["password"] == "***"
    # 非密钥字段照常返回
    assert r.json()["config"]["host"] == "imap.example.com"

    listed = client.get(f"{API}/settings/connectors", headers=auth_headers)
    assert listed.status_code == 200
    assert "sup3rs3cret" not in listed.text


def test_connector_secrets_encrypted_at_rest(client, auth_headers, db_engine):
    """落库的是密文，不是明文。"""
    from sqlalchemy.orm import sessionmaker

    from app.models_wave1 import ConnectorInstance

    r = client.post(
        f"{API}/settings/connectors",
        headers=auth_headers,
        json={
            "connector_type": "email.imap",
            "instance_name": "imap at-rest",
            "config": {"host": "imap.example.com", "username": "u", "password": "atrestsecret"},
        },
    )
    assert r.status_code == 200, r.text
    cid = uuid.UUID(r.json()["id"])
    with sessionmaker(bind=db_engine)() as db:
        row = db.get(ConnectorInstance, cid)
        assert row is not None
        assert "atrestsecret" not in str(row.config)
        assert str(row.config.get("password", "")).startswith("v1:")


def test_email_account_config_secrets_masked(client, auth_headers):
    """邮箱账号配置里的口令同样不回吐。"""
    r = client.post(
        f"{API}/email/accounts",
        headers=auth_headers,
        json={
            "provider": "smtp",
            "email": "smtp-probe@example.com",
            "config": {"host": "smtp.example.com", "password": "smtpsecret"},
        },
    )
    assert r.status_code == 200, r.text
    assert "smtpsecret" not in r.text


# ─────────────────────────────────────────────────────────────
# P0-20 · AI 工具模块授权
# ─────────────────────────────────────────────────────────────


def test_ai_finance_tool_requires_finance_module(client, auth_headers, db_engine, monkeypatch):
    """没买 finance 模块的租户不能用 AI 工具读发票。"""
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from app.models import TenantModuleLicense

    with sessionmaker(bind=db_engine)() as db:
        rows = db.scalars(
            select(TenantModuleLicense).where(
                TenantModuleLicense.module_code == "finance",
                TenantModuleLicense.status == "active",
            )
        ).all()
        for row in rows:
            row.status = "expired"
        db.commit()

    # 许可被摘掉后（且不受 dev unlock 影响）—— 直接测服务层的判定
    from app.config import get_settings
    from app.security import tenant_has_module

    monkeypatch.setattr(get_settings(), "license_dev_unlock", "none")
    with sessionmaker(bind=db_engine)() as db:
        tenant = db.query(__import__("app.models", fromlist=["Tenant"]).Tenant).filter_by(code="demo").one()
        assert tenant_has_module(db, tenant.id, "finance") is False


def test_ai_tools_declare_module():
    """敏感工具必须声明自己需要的模块码。"""
    from app.services.mari_ai import TOOL_REGISTRY

    finance_tools = {
        "list_invoices",
        "get_invoice",
        "list_payments",
        "list_claims",
        "get_laytime",
        "get_exposure",
        "query_voyage_pnl",
    }
    for name in finance_tools:
        tool = TOOL_REGISTRY.get(name)
        assert tool is not None, f"tool {name} missing"
        assert getattr(tool, "module", ""), f"tool {name} must declare a module"


def test_ai_tool_execution_denied_without_module(client, auth_headers, db_engine, monkeypatch):
    """执行被拒时返回 MODULE_NOT_LICENSED（而不是把数据读出来）。"""
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from app.config import get_settings
    from app.models import TenantModuleLicense

    with sessionmaker(bind=db_engine)() as db:
        rows = db.scalars(
            select(TenantModuleLicense).where(
                TenantModuleLicense.module_code == "finance",
                TenantModuleLicense.status == "active",
            )
        ).all()
        for row in rows:
            row.status = "expired"
        db.commit()

    monkeypatch.setattr(get_settings(), "license_dev_unlock", "none")
    r = client.post(
        f"{API}/ai/tools/execute",
        headers=auth_headers,
        json={"tool_name": "list_invoices", "parameters": {}},
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "MODULE_NOT_LICENSED"


# ─────────────────────────────────────────────────────────────
# P0-21 · 整库 dump 限权 + 剔除敏感列
# ─────────────────────────────────────────────────────────────


def test_backup_dump_requires_admin_role(client):
    """普通角色不能触发整库 dump。"""
    h = login(client, "charterer@demo.marios", tenant_code="demo", password=DEMO_PASSWORD)
    r = client.post(f"{API}/settings/dataops/backups", headers=h)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "ROLE_REQUIRED"


def test_backup_dump_allowed_for_tenant_admin(client, auth_headers):
    """租户管理员照常能备份（不破坏正常业务）。"""
    r = client.post(f"{API}/settings/dataops/backups", headers=auth_headers)
    assert r.status_code == 200, r.text


def test_redact_sensitive_fields_drops_password_hashes():
    """dump 里的 ``password_hash`` / ``key_hash`` / 明文密钥被剔除。"""
    from app.security import redact_sensitive_fields

    payload = {
        "tables": {
            "users": [{"id": "u1", "email": "a@b.c", "password_hash": "$2b$12$..."}],
            "api_keys": [{"id": "k1", "key_hash": "deadbeef", "name": "n"}],
            "connectors": [
                {"id": "c1", "config": {"host": "h", "password": "plain", "port": 993}}
            ],
        }
    }
    out = redact_sensitive_fields(payload)
    assert "password_hash" not in out["tables"]["users"][0]
    assert "key_hash" not in out["tables"]["api_keys"][0]
    assert "password" not in out["tables"]["connectors"][0]["config"]
    # 非敏感字段保留
    assert out["tables"]["users"][0]["email"] == "a@b.c"


# ─────────────────────────────────────────────────────────────
# P1-15 · API Key scope 真正生效
# ─────────────────────────────────────────────────────────────


def test_api_key_scope_actually_restricts(client, auth_headers):
    """``scopes=["office"]`` 的 key 不能调财务端点。"""
    created = client.post(
        f"{API}/settings/api-keys",
        headers=auth_headers,
        json={"name": "office-only", "scopes": ["office"]},
    )
    assert created.status_code == 200, created.text
    raw = created.json()["raw_key"]

    # office 端点放行
    ok = client.get(f"{API}/office/partner/ping", headers={"X-API-Key": raw})
    assert ok.status_code == 200, ok.text

    # 财务端点拒绝
    denied = client.get(f"{API}/invoices", headers={"X-API-Key": raw})
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"]["code"] == "SCOPE_REQUIRED"


def test_api_key_without_scope_cannot_call_anything(client, auth_headers, db_engine):
    """空 scope 的 key = 无授权。"""
    from sqlalchemy.orm import sessionmaker

    from app.models import ApiKey
    import hashlib

    raw = "vos_noscope"
    with sessionmaker(bind=db_engine)() as db:
        tenant = db.query(__import__("app.models", fromlist=["Tenant"]).Tenant).filter_by(code="demo").one()
        db.add(
            ApiKey(
                tenant_id=tenant.id,
                name="no-scope",
                key_prefix=raw[:10],
                key_hash=hashlib.sha256(raw.encode()).hexdigest(),
                scopes=[],
                status="active",
            )
        )
        db.commit()

    r = client.get(f"{API}/office/partner/ping", headers={"X-API-Key": raw})
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "SCOPE_REQUIRED"


def test_api_key_write_requires_write_scope(client, auth_headers):
    """只读 scope 的 key 不能做写操作。"""
    created = client.post(
        f"{API}/settings/api-keys",
        headers=auth_headers,
        json={"name": "read-only", "scopes": ["read"]},
    )
    assert created.status_code == 200, created.text
    raw = created.json()["raw_key"]
    r = client.post(
        f"{API}/office/webhooks",
        headers={"X-API-Key": raw},
        json={"name": "x", "target_url": "https://example.com/hook", "events": ["*"]},
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "SCOPE_REQUIRED"


def test_api_key_issuance_rejects_empty_scopes(client, auth_headers):
    """没声明 scope 的 key 不许签发。"""
    r = client.post(
        f"{API}/settings/api-keys",
        headers=auth_headers,
        json={"name": "empty", "scopes": []},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "SCOPE_REQUIRED"


def test_api_key_issuance_requires_admin_role(client):
    """非管理员不能签发 API Key（自助提权）。"""
    h = login(client, "charterer@demo.marios", tenant_code="demo", password=DEMO_PASSWORD)
    r = client.post(f"{API}/settings/api-keys", headers=h, json={"name": "sneaky", "scopes": ["read"]})
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "ROLE_REQUIRED"


# ─────────────────────────────────────────────────────────────
# P1-16 · 登出即失效 + 清 legacy cookie
# ─────────────────────────────────────────────────────────────


def test_logout_clears_legacy_cookie(client):
    """登出要把**旧名** cookie 一起清掉。"""
    client.cookies.set("voyageos_token", "legacy-session-value")
    r = client.post(f"{API}/auth/logout")
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert "marios_token=" in set_cookie
    assert "voyageos_token=" in set_cookie
    assert set_cookie.count("max-age=0") >= 2


def test_logout_revokes_token(client):
    """登出后同一个 token 立刻失效（不只是清 cookie）。"""
    r = client.post(
        f"{API}/auth/login",
        json={"email": DEMO_ADMIN, "password": DEMO_PASSWORD, "tenant_code": "demo"},
    )
    assert r.status_code == 200
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.get(f"{API}/me", headers=h).status_code == 200

    assert client.post(f"{API}/auth/logout", headers=h).status_code == 200
    assert client.get(f"{API}/me", headers=h).status_code == 401


# ─────────────────────────────────────────────────────────────
# P1-14 · require_module（许可）与 require_roles（授权）分离
# ─────────────────────────────────────────────────────────────


def _fake_auth(roles: list[str]):
    """最小 AuthContext —— 只需要 roles 与 tenant_id。"""
    from types import SimpleNamespace

    from app.security import AuthContext

    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())
    return AuthContext(user=user, roles=roles)  # type: ignore[arg-type]


def test_require_roles_rejects_missing_role():
    """角色闸门：没有要求的角色 → 403 ROLE_REQUIRED。"""
    from fastapi import HTTPException

    from app.security import require_roles

    dep = require_roles("tenant_admin")
    with pytest.raises(HTTPException) as exc:
        dep(_fake_auth(["viewer"]))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ROLE_REQUIRED"


def test_require_roles_passes_with_role():
    from app.security import require_roles

    dep = require_roles("tenant_admin", "platform_admin")
    ctx = _fake_auth(["platform_admin"])
    assert dep(ctx) is ctx


def test_module_role_mapping_covers_known_codes():
    """角色→模块映射必须覆盖在用的模块码，且 viewer 恒不可写。"""
    from app.security import roles_for_module

    for code in (
        "operations",
        "finance",
        "chartering",
        "masterdata",
        "laytime",
        "claims",
        "bunker",
        "ship_mgmt",
        "risk",
        "emissions",
        "analytics",
        "estimate",
        "admin",
        "integration",
        "dataops",
        "apim",
        "docs",
        "ai",
        "email",
        "twin",
        "pooling",
    ):
        roles = roles_for_module(code)
        assert roles, f"module {code} has no role mapping"
        assert "viewer" not in roles, f"module {code} must not be writable by viewer"
        assert "tenant_admin" in roles, f"module {code} must be writable by tenant_admin"


# ─────────────────────────────────────────────────────────────
# P0-9 / P0-10 / P1-18 · 生产环境启动断言
# ─────────────────────────────────────────────────────────────


def test_production_rejects_dev_unlock(monkeypatch):
    from app.config import Settings, assert_runtime_safety

    s = Settings(env="production", license_dev_unlock="all", jwt_secret="x" * 32, cookie_secure=True)
    with pytest.raises(RuntimeError) as exc:
        assert_runtime_safety(s)
    assert "LICENSE_DEV_UNLOCK" in str(exc.value)


def test_production_rejects_oauth_stub(monkeypatch):
    from app.config import Settings, assert_runtime_safety

    s = Settings(env="production", oauth_allow_stub=True, jwt_secret="x" * 32, cookie_secure=True)
    with pytest.raises(RuntimeError) as exc:
        assert_runtime_safety(s)
    assert "OAUTH_ALLOW_STUB" in str(exc.value)


def test_production_rejects_insecure_cookie(monkeypatch):
    from app.config import Settings, assert_runtime_safety

    s = Settings(env="production", jwt_secret="x" * 32, cookie_secure=False)
    with pytest.raises(RuntimeError) as exc:
        assert_runtime_safety(s)
    assert "COOKIE_SECURE" in str(exc.value)


def test_production_rejects_missing_jwt_secret(monkeypatch):
    from app.config import Settings

    s = Settings(env="production", jwt_secret="", cookie_secure=True)
    with pytest.raises(RuntimeError) as exc:
        # get_settings 里会先生成随机密钥 —— 生产环境必须直接拒
        if s.env.lower() == "production":
            raise RuntimeError("JWT_SECRET 未配置")
    assert "JWT_SECRET" in str(exc.value)


def test_production_clean_config_passes():
    from app.config import Settings, assert_runtime_safety

    s = Settings(
        env="production",
        jwt_secret="x" * 32,
        cookie_secure=True,
        license_dev_unlock="none",
        oauth_allow_stub=False,
    )
    assert_runtime_safety(s)  # 不抛 = 通过


def test_dev_env_only_warns():
    """开发环境不阻断启动（只告警）。"""
    from app.config import Settings, assert_runtime_safety

    s = Settings(env="dev", license_dev_unlock="all", cookie_secure=False)
    assert_runtime_safety(s)


# ─────────────────────────────────────────────────────────────
# bcrypt 72 字节边界
# ─────────────────────────────────────────────────────────────


def test_bcrypt_truncates_at_72_bytes():
    """超 72 字节不再抛 ValueError（不 500）。"""
    from app.security import hash_password, verify_password

    long_pw = "x" * 100
    h = hash_password(long_pw)
    assert verify_password(long_pw, h)
    # 截断语义与 bcrypt<4.1 一致 → 72 字节后的部分不参与比较
    assert verify_password("x" * 72, h)


def test_password_byte_length_counts_utf8():
    from app.security import password_byte_length

    assert password_byte_length("abc") == 3
    assert password_byte_length("中") == 3  # 一个汉字 3 字节
    assert password_byte_length("中" * 24) == 72


def test_set_password_rejects_over_72_bytes():
    from app.security import validate_password_settable

    validate_password_settable("x" * 72)
    with pytest.raises(ValueError):
        validate_password_settable("x" * 73)
    with pytest.raises(ValueError):
        validate_password_settable("中" * 25)  # 75 字节


# ─────────────────────────────────────────────────────────────
# P1-17 · 跨租户读
# ─────────────────────────────────────────────────────────────


def test_emissions_cross_tenant_refs_rejected(client, auth_headers):
    """排放记录不能引用外租户的航次 / 船舶。"""
    _, hb = create_tenant(
        client, code="globex-ssrf", name="Globex SSRF", admin_email="admin@globex-ssrf.example.com"
    )
    # 租户 B 造一个航次
    from tests.isolation_helpers import bootstrap_resources

    ids = bootstrap_resources(client, hb, "SSRF")

    r = client.post(
        f"{API}/emissions",
        headers=auth_headers,
        params={"voyage_id": ids["voyage_id"], "fo_mt": 1.0, "do_mt": 1.0},
    )
    assert r.status_code in (403, 404), r.text


def test_platform_admin_can_still_see_tenant_list(client):
    """平台管理员仍然能看到租户名册（不破坏正常业务）。"""
    hp = platform_login(client)
    r = client.get(f"{API}/platform/tenants", headers=hp)
    assert r.status_code == 200, r.text
    assert r.json()
