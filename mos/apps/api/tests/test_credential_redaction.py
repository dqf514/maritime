"""P0-19 / P0-21 · 凭据不回吐 + 备份脱敏的回归测试。

覆盖四条链路：

1. AI Hub 供应商（``secret_ref`` / ``config.api_key``）
2. 邮箱账号（``config`` 里的 SMTP 口令）
3. 连接器（``secret_ref`` / ``config`` 里的密码、API Key）
4. 定时备份产物（``backup_scheduler`` 落的 dump 里不能有明文密钥）

断言口径统一：**响应体里不出现原始密钥值；落库的是 ``v1:`` 密文；
备份产物里既没有敏感列名，也没有密钥明文。**
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.models_wave1 import AiProvider, ConnectorInstance, EmailAccount

API = "/api/v1"

# —— 测试用的固定密钥（一旦出现在任何响应/产物里即判定失败）——
RAW_AI_KEY = "sk-raw-ai-key-0123456789"
RAW_CLIENT_SECRET = "client-raw-secret-44556677"
RAW_MAIL_PASSWORD = "smtp-raw-password-987654321"
RAW_CONN_SECRET = "conn-raw-secret-abcdefgh"
RAW_CONN_PASSWORD = "imap-raw-password-112233"


@pytest.fixture()
def db_session(db_engine):
    with sessionmaker(bind=db_engine, autoflush=False, autocommit=False)() as db:
        yield db


def _tenant_id(db) -> uuid.UUID:
    from app.models import Tenant

    return uuid.UUID(str(db.execute(select(Tenant.id).where(Tenant.code == "demo")).scalar()))


def _reload(db, model, ident):
    """重新读一行（结束旧事务，避免读到 API 写入前的快照）。"""
    db.rollback()
    return db.get(model, uuid.UUID(str(ident)))


# ── 1. AI Hub 供应商 ───────────────────────────────────────────


def test_ai_provider_secret_never_echoed(client, auth_headers, db_session):
    """供应商的 API Key 不出现在响应体里，且落库是密文。"""
    r = client.post(
        f"{API}/settings/ai/providers",
        headers=auth_headers,
        json={
            "name": "OpenAI Probe",
            "provider_type": "openai",
            "base_url": "https://api.openai.com/v1",
            "model_default": "gpt-4o-mini",
            # 前端把密钥同时塞在 config.api_key 与 secret_ref 里
            "secret_ref": RAW_AI_KEY,
            "config": {"api_key": RAW_AI_KEY, "client_secret": RAW_CLIENT_SECRET, "temperature": 0.5},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert RAW_AI_KEY not in r.text
    assert RAW_CLIENT_SECRET not in r.text
    # secret_ref 只回显版本前缀，密文本体不外送
    assert body["secret_ref"] == "v1:***"
    # config 里的 api_key 被提升进 secret_ref（不再单独存放），其余密钥键遮掉
    assert "api_key" not in body["config"]
    assert body["config"].get("client_secret") == "***"
    assert body["config"].get("temperature") == 0.5

    row = _reload(db_session, AiProvider, body["id"])
    assert row is not None
    # 落库：secret_ref 加密，config 里不再有明文 api_key
    assert row.secret_ref.startswith("v1:")
    assert RAW_AI_KEY not in str(row.secret_ref)
    assert row.config.get("api_key") is None
    assert RAW_AI_KEY not in str(row.config)

    listed = client.get(f"{API}/settings/ai/providers", headers=auth_headers)
    assert listed.status_code == 200
    assert RAW_AI_KEY not in listed.text


def test_ai_provider_patch_rotates_key_without_leak(client, auth_headers, db_session):
    """轮换密钥（PATCH）同样不回吐明文。"""
    r = client.post(
        f"{API}/settings/ai/providers",
        headers=auth_headers,
        json={"name": "Rotate Probe", "provider_type": "openai", "config": {}},
    )
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    r = client.patch(
        f"{API}/settings/ai/providers/{pid}",
        headers=auth_headers,
        json={"api_key": RAW_AI_KEY, "model_default": "gpt-4o"},
    )
    assert r.status_code == 200, r.text
    assert RAW_AI_KEY not in r.text
    assert r.json()["secret_ref"] == "v1:***"

    row = _reload(db_session, AiProvider, pid)
    assert row.secret_ref.startswith("v1:")
    assert RAW_AI_KEY not in str(row.secret_ref)
    assert row.config.get("api_key") is None


# ── 2. 邮箱账号 ───────────────────────────────────────────────


def test_email_account_password_masked_on_create_patch_and_list(client, auth_headers, db_session):
    """邮箱账号的 SMTP 口令：创建 / 修改 / 列表三处都不能回显。"""
    r = client.post(
        f"{API}/email/accounts",
        headers=auth_headers,
        json={
            "provider": "smtp",
            "email": "redaction-probe@example.com",
            "config": {"host": "smtp.example.com", "password": RAW_MAIL_PASSWORD},
        },
    )
    assert r.status_code == 200, r.text
    assert RAW_MAIL_PASSWORD not in r.text
    assert r.json()["config"]["password"] == "***"
    assert r.json()["config"]["host"] == "smtp.example.com"
    acc_id = r.json()["id"]

    # 落库是密文
    row = _reload(db_session, EmailAccount, acc_id)
    assert row is not None
    assert str(row.config.get("password", "")).startswith("v1:")
    assert RAW_MAIL_PASSWORD not in str(row.config)

    # PATCH —— 这里曾经直接把整块 config 原样回吐
    r = client.patch(
        f"{API}/email/accounts/{acc_id}",
        headers=auth_headers,
        json={"config": {"host": "smtp2.example.com", "password": "rotated-password-777"}},
    )
    assert r.status_code == 200, r.text
    assert "rotated-password-777" not in r.text
    assert r.json()["config"]["password"] == "***"

    listed = client.get(f"{API}/email/accounts", headers=auth_headers)
    assert listed.status_code == 200
    assert RAW_MAIL_PASSWORD not in listed.text
    assert "rotated-password-777" not in listed.text


# ── 3. 连接器 ─────────────────────────────────────────────────


def test_connector_secret_ref_encrypted_at_rest(client, auth_headers, db_session):
    """连接器的 secret_ref / config 密钥：加密落库 + 响应掩码。"""
    r = client.post(
        f"{API}/settings/connectors",
        headers=auth_headers,
        json={
            "connector_type": "email.imap",
            "instance_name": "redaction probe",
            "secret_ref": RAW_CONN_SECRET,
            "config": {"host": "imap.example.com", "password": RAW_CONN_PASSWORD},
        },
    )
    assert r.status_code == 200, r.text
    assert RAW_CONN_SECRET not in r.text
    assert RAW_CONN_PASSWORD not in r.text
    body = r.json()
    assert body["secret_ref"] == "***"
    assert body["config"]["password"] == "***"

    row = _reload(db_session, ConnectorInstance, body["id"])
    assert row is not None
    assert row.secret_ref.startswith("v1:")
    assert RAW_CONN_SECRET not in str(row.secret_ref)
    assert str(row.config.get("password", "")).startswith("v1:")
    assert RAW_CONN_PASSWORD not in str(row.config)


def test_connector_mask_roundtrip_keeps_stored_secret(client, auth_headers, db_session):
    """前端把掩码原样回写时，不能把真密钥冲成 ``***``。"""
    r = client.post(
        f"{API}/settings/connectors",
        headers=auth_headers,
        json={
            "connector_type": "email.imap",
            "instance_name": "roundtrip probe",
            "secret_ref": RAW_CONN_SECRET,
            "config": {},
        },
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    before = _reload(db_session, ConnectorInstance, cid).secret_ref
    assert before.startswith("v1:")

    r = client.patch(
        f"{API}/settings/connectors/{cid}",
        headers=auth_headers,
        json={"secret_ref": r.json()["secret_ref"], "instance_name": "roundtrip probe 2"},
    )
    assert r.status_code == 200, r.text
    after = _reload(db_session, ConnectorInstance, cid).secret_ref
    assert after == before
    assert RAW_CONN_SECRET not in after


# ── 4. 定时备份产物脱敏（P0-21）────────────────────────────────


def test_auto_backup_dump_is_redacted(client, auth_headers, db_session, tmp_path, monkeypatch):
    """自动备份落盘的 dump 里不能有口令哈希 / 密钥明文。"""
    from app.models import BackupSchedule
    from app.services import backup_scheduler

    monkeypatch.setenv("TENANT_BACKUP_ROOT", str(tmp_path))
    monkeypatch.setenv("TENANT_BACKUP_ENCRYPT", "0")  # 明文产物，便于断言内容

    # 先造一条带密钥的业务数据
    r = client.post(
        f"{API}/settings/connectors",
        headers=auth_headers,
        json={
            "connector_type": "email.imap",
            "instance_name": "backup probe",
            "secret_ref": RAW_CONN_SECRET,
            "config": {"password": RAW_CONN_PASSWORD},
        },
    )
    assert r.status_code == 200, r.text

    tenant_id = _tenant_id(db_session)
    db_session.execute(delete(BackupSchedule).where(BackupSchedule.tenant_id == tenant_id))
    db_session.add(
        BackupSchedule(
            tenant_id=tenant_id,
            frequency="daily",
            hour_utc=3,
            enabled=True,
            next_run_at=datetime(2000, 1, 1, 0, 0),
            keep_last=3,
        )
    )
    db_session.commit()

    ran = backup_scheduler.run_due_schedules(db_session)
    assert ran >= 1

    artifacts = list((Path(tmp_path) / "backups" / "tenant").rglob("*.json"))
    assert artifacts, "备份产物没生成"
    text = artifacts[0].read_text(encoding="utf-8")
    payload = json.loads(text)

    # 敏感列整个不落盘
    for table, rows in (payload.get("tables") or {}).items():
        for row in rows:
            assert "password_hash" not in row, table
            assert "secret_ref" not in row, table
    # 密钥明文不落盘
    assert RAW_CONN_SECRET not in text
    assert RAW_CONN_PASSWORD not in text
    assert "password_hash" not in text
    assert "secret_ref" not in text


def test_redact_helper_drops_secret_config_keys():
    """共用脱敏助手本身的行为（与手动备份同源）。"""
    from app.security import redact_sensitive_fields

    payload = {
        "tables": {
            "connector_instances": [
                {
                    "id": "1",
                    "secret_ref": "v1:cipher",
                    "config": {"host": "imap.example.com", "password": "s3cr3t"},
                }
            ]
        }
    }
    out = redact_sensitive_fields(payload)
    row = out["tables"]["connector_instances"][0]
    assert "secret_ref" not in row
    assert "password" not in row["config"]
    assert row["config"]["host"] == "imap.example.com"
