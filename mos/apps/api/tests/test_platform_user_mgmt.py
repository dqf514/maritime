"""平台管理员的租户用户管理 + 平台 SMTP 配置。

覆盖商务交付需求：
- 平台管理员对任意租户用户的增删改（含租户管理员）/ 密码重置
- 创建账户 / 重置密码自动发邮件（OutboundMailLog，body 预览脱敏不落明文密码）
- 最后一个 active tenant_admin 的删除/停用/降级守卫（409）
- 平台可配置 SMTP（host/port/SSL 类型/用户名/密码，密码加密存储、掩码下发）
- SMTP 发送失败 fallback_console 不阻断业务
"""

from __future__ import annotations

from tests.isolation_helpers import create_tenant, platform_login

API = "/api/v1"


def _mail_logs(client, hp) -> list[dict]:
    r = client.get(f"{API}/platform/identity/mail-logs", headers=hp)
    assert r.status_code == 200, r.text
    return r.json()


# ── 1. 平台用户 CRUD + 登录 ──


def test_platform_user_crud_and_login(client, auth_headers):
    hp = platform_login(client)
    tid, _hb = create_tenant(client, code="pu-t1", name="Platform Users", admin_email="Admin@PuT1.example.com")

    # 角色目录随租户克隆
    roles = client.get(f"{API}/platform/tenants/{tid}/roles", headers=hp)
    assert roles.status_code == 200, roles.text
    codes = {r["code"] for r in roles.json()}
    assert {"tenant_admin", "viewer"} <= codes

    # 创建（不带密码 → 服务端生成临时密码并邮件下发）
    rc = client.post(
        f"{API}/platform/tenants/{tid}/users",
        headers=hp,
        json={
            "email": "Ops.Manager@PuT1.example.com",
            "full_name": "Ops Manager",
            "role_codes": ["tenant_admin", "viewer"],
            "send_email": True,
        },
    )
    assert rc.status_code == 200, rc.text
    body = rc.json()
    uid = body["id"]
    temp_pw = body["temp_password"]
    assert temp_pw and len(temp_pw) >= 8
    assert body["emailed"] is True
    assert "tenant_admin" in body["roles"]

    # 列表可见
    lst = client.get(f"{API}/platform/tenants/{tid}/users", headers=hp)
    assert lst.status_code == 200, lst.text
    hit = next(u for u in lst.json() if u["id"] == uid)
    assert hit["email"] == "ops.manager@put1.example.com"
    assert "tenant_admin" in hit["roles"]

    # 新用户可用临时密码登录
    lg = client.post(
        f"{API}/auth/login",
        json={"email": "ops.manager@put1.example.com", "password": temp_pw, "tenant_code": "pu-t1"},
    )
    assert lg.status_code == 200, lg.text

    # 改名 + 降级状态
    up = client.patch(
        f"{API}/platform/tenants/{tid}/users/{uid}",
        headers=hp,
        json={"full_name": "Ops Manager II", "role_codes": ["viewer"]},
    )
    assert up.status_code == 200, up.text
    assert up.json()["full_name"] == "Ops Manager II"
    assert up.json()["roles"] == ["viewer"]

    # 删除（软删）
    dl = client.delete(f"{API}/platform/tenants/{tid}/users/{uid}", headers=hp)
    assert dl.status_code == 200, dl.text
    lst2 = client.get(f"{API}/platform/tenants/{tid}/users", headers=hp)
    assert all(u["id"] != uid for u in lst2.json())

    # 邮件审计：account_created 的预览已脱敏（不落明文密码）
    logs = [
        m
        for m in _mail_logs(client, hp)
        if m["purpose"] == "account_created" and m["to_email"] == "ops.manager@put1.example.com"
    ]
    assert logs, "account_created mail should be logged"
    assert temp_pw not in (logs[0]["body_preview"] or "")
    assert "temporary password:" in (logs[0]["body_preview"] or "").lower()

    # 守卫：重复邮箱 / platform_admin 角色
    dup = client.post(
        f"{API}/platform/tenants/{tid}/users",
        headers=hp,
        json={"email": "dup@put1.example.com", "full_name": "Dup", "password": "Passw0rd1!", "role_codes": ["viewer"]},
    )
    assert dup.status_code == 200, dup.text
    dup2 = client.post(
        f"{API}/platform/tenants/{tid}/users",
        headers=hp,
        json={"email": "dup@put1.example.com", "full_name": "Dup", "password": "Passw0rd1!", "role_codes": ["viewer"]},
    )
    assert dup2.status_code == 409
    bad = client.post(
        f"{API}/platform/tenants/{tid}/users",
        headers=hp,
        json={"email": "evil@put1.example.com", "full_name": "Evil", "password": "Passw0rd1!", "role_codes": ["platform_admin"]},
    )
    assert bad.status_code == 403


# ── 2. 密码重置：旧会话失效 + 邮件发送 ──


def test_platform_reset_password_rotates_and_mails(client, auth_headers):
    hp = platform_login(client)
    tid, _hb = create_tenant(client, code="pu-t2", name="Reset Target", admin_email="Admin@PuT2.example.com")
    rc = client.post(
        f"{API}/platform/tenants/{tid}/users",
        headers=hp,
        json={"email": "keeper@put2.example.com", "full_name": "Keeper", "password": "OldPass123!", "role_codes": ["viewer"], "send_email": False},
    )
    assert rc.status_code == 200, rc.text
    uid = rc.json()["id"]

    lg = client.post(
        f"{API}/auth/login",
        json={"email": "keeper@put2.example.com", "password": "OldPass123!", "tenant_code": "pu-t2"},
    )
    assert lg.status_code == 200, lg.text
    old_token = lg.json()["access_token"]
    old_h = {"Authorization": f"Bearer {old_token}"}
    assert client.get(f"{API}/shell/bootstrap", headers=old_h).status_code == 200

    # 重置 → 返回一次性临时密码并发邮件
    rs = client.post(
        f"{API}/platform/tenants/{tid}/users/{uid}/reset-password",
        headers=hp,
        json={"send_email": True},
    )
    assert rs.status_code == 200, rs.text
    temp_pw = rs.json()["temp_password"]
    assert temp_pw and rs.json()["emailed"] is True
    assert rs.json()["sessions_invalidated"] is True

    # 旧会话立即失效（pwv 校验）
    assert client.get(f"{API}/shell/bootstrap", headers=old_h).status_code == 401
    # 旧密码不可登录，新密码可以
    assert client.post(
        f"{API}/auth/login",
        json={"email": "keeper@put2.example.com", "password": "OldPass123!", "tenant_code": "pu-t2"},
    ).status_code == 401
    assert client.post(
        f"{API}/auth/login",
        json={"email": "keeper@put2.example.com", "password": temp_pw, "tenant_code": "pu-t2"},
    ).status_code == 200

    # 邮件审计：password_reset 预览脱敏
    logs = [m for m in _mail_logs(client, hp) if m["purpose"] == "password_reset"]
    assert logs
    preview = logs[0]["body_preview"] or ""
    assert temp_pw not in preview
    assert "temporary password:" in preview.lower()


# ── 3. 最后一个 tenant_admin 守卫 ──


def test_last_tenant_admin_guards(client, auth_headers):
    hp = platform_login(client)
    tid, _hb = create_tenant(client, code="pu-t3", name="Last Admin", admin_email="Admin@PuT3.example.com")
    users = client.get(f"{API}/platform/tenants/{tid}/users", headers=hp).json()
    admin = next(u for u in users if "tenant_admin" in u["roles"] and u["status"] == "active")

    # 禁删
    dl = client.delete(f"{API}/platform/tenants/{tid}/users/{admin['id']}", headers=hp)
    assert dl.status_code == 409
    assert dl.json()["detail"]["code"] == "LAST_TENANT_ADMIN"
    # 禁停用
    st = client.patch(
        f"{API}/platform/tenants/{tid}/users/{admin['id']}",
        headers=hp,
        json={"status": "disabled"},
    )
    assert st.status_code == 409
    # 禁降级（移除 tenant_admin）
    demote = client.patch(
        f"{API}/platform/tenants/{tid}/users/{admin['id']}",
        headers=hp,
        json={"role_codes": ["viewer"]},
    )
    assert demote.status_code == 409

    # 补一个管理员后可删
    rc = client.post(
        f"{API}/platform/tenants/{tid}/users",
        headers=hp,
        json={"email": "second.admin@put3.example.com", "full_name": "Second Admin", "password": "Second123!", "role_codes": ["tenant_admin"]},
    )
    assert rc.status_code == 200, rc.text
    dl2 = client.delete(f"{API}/platform/tenants/{tid}/users/{admin['id']}", headers=hp)
    assert dl2.status_code == 200, dl2.text


# ── 4. 权限与作用域 ──


def test_platform_user_endpoints_access_control(client, auth_headers):
    hp = platform_login(client)
    tid, hb = create_tenant(client, code="pu-t4", name="Access Ctrl", admin_email="Admin@PuT4.example.com")

    # tenant_admin 不能碰平台端点
    assert client.get(f"{API}/platform/tenants/{tid}/users", headers=hb).status_code == 403
    assert client.get(f"{API}/platform/identity", headers=hb).status_code == 403
    # sys 租户不可管理（404）
    boot = client.get(f"{API}/shell/bootstrap", headers=hp).json()
    sys_tid = boot["tenant"]["id"]
    assert client.get(f"{API}/platform/tenants/{sys_tid}/users", headers=hp).status_code == 404
    # 未知租户 404
    assert (
        client.get(f"{API}/platform/tenants/00000000-0000-0000-0000-000000000099/users", headers=hp).status_code
        == 404
    )


# ── 5. 平台 SMTP 配置 ──


def test_smtp_settings_roundtrip(client):
    hp = platform_login(client)
    g0 = client.get(f"{API}/platform/identity", headers=hp)
    assert g0.status_code == 200, g0.text
    assert g0.json()["smtp_password_set"] is False

    put = client.put(
        f"{API}/platform/identity",
        headers=hp,
        json={
            "email_channel": "smtp",
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "smtp_security": "ssl",
            "smtp_username": "mailer@example.com",
            "smtp_password": "s3cret-relay-pass",
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["smtp_host"] == "smtp.example.com"
    assert body["smtp_port"] == 465
    assert body["smtp_security"] == "ssl"
    assert body["smtp_password_set"] is True
    # 明文密码永不出现在响应里
    assert "smtp_password" not in body
    assert "s3cret-relay-pass" not in str(body)

    # 单独清空密码（"" → clear），其余字段保持
    put2 = client.put(f"{API}/platform/identity", headers=hp, json={"smtp_password": ""})
    assert put2.status_code == 200, put2.text
    assert put2.json()["smtp_password_set"] is False
    assert put2.json()["smtp_host"] == "smtp.example.com"

    # 非法加密方式 / 端口
    assert (
        client.put(f"{API}/platform/identity", headers=hp, json={"smtp_security": "tls"}).status_code == 400
    )
    assert client.put(f"{API}/platform/identity", headers=hp, json={"smtp_port": 70000}).status_code == 422


def test_smtp_test_success_and_fallback(client, monkeypatch):
    hp = platform_login(client)
    client.put(
        f"{API}/platform/identity",
        headers=hp,
        json={"email_channel": "smtp", "smtp_host": "smtp.example.com", "smtp_security": "starttls"},
    )

    # 成功路径
    monkeypatch.setattr(
        "app.services.identity._smtp_send",
        lambda plat, to, subj, body: {"host": "smtp.example.com", "port": 587, "security": "starttls", "latency_ms": 5},
    )
    ok = client.post(f"{API}/platform/identity/smtp-test", headers=hp, json={})
    assert ok.status_code == 200, ok.text
    assert ok.json()["ok"] is True
    assert ok.json()["status"] == "sent"

    # 失败路径 → fallback_console，不抛 500
    def _boom(plat, to, subj, body):
        raise OSError("connection refused")

    monkeypatch.setattr("app.services.identity._smtp_send", _boom)
    fail = client.post(f"{API}/platform/identity/smtp-test", headers=hp, json={})
    assert fail.status_code == 200, fail.text
    assert fail.json()["ok"] is False
    assert fail.json()["status"] == "fallback_console"
    assert "connection refused" in fail.json()["message"]


def test_smtp_channel_used_for_account_mail(client, monkeypatch):
    """email_channel=smtp 时，平台创建用户的邮件走 SMTP 分支。"""
    hp = platform_login(client)
    tid, _hb = create_tenant(client, code="pu-t5", name="SMTP Mail", admin_email="Admin@PuT5.example.com")
    client.put(
        f"{API}/platform/identity",
        headers=hp,
        json={"email_channel": "smtp", "smtp_host": "smtp.example.com", "smtp_security": "ssl", "smtp_port": 465},
    )
    seen = {}

    def _fake_send(plat, to, subj, body):
        seen["to"] = to
        return {"host": "smtp.example.com", "port": 465, "security": "ssl", "latency_ms": 3}

    monkeypatch.setattr("app.services.identity._smtp_send", _fake_send)
    rc = client.post(
        f"{API}/platform/tenants/{tid}/users",
        headers=hp,
        json={"email": "smtp.user@put5.example.com", "full_name": "SMTP User", "role_codes": ["viewer"], "send_email": True},
    )
    assert rc.status_code == 200, rc.text
    assert seen.get("to") == "smtp.user@put5.example.com"
    logs = [
        m
        for m in _mail_logs(client, hp)
        if m["purpose"] == "account_created" and m["to_email"] == "smtp.user@put5.example.com"
    ]
    assert logs and logs[0]["channel"] == "smtp" and logs[0]["status"] == "sent"
