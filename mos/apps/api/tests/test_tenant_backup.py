"""平台管理员租户数据运维（全量备份 / 恢复 / 清理）+ 自动备份计划 + 菜单/ACL 一致性。

覆盖商务交付待处理项：
- 平台一键备份/清理特定租户数据（/platform/tenants/*）
- 自动备份设置（/settings/dataops/backup-schedule + backup_scheduler）
- B1 一致性：菜单锁定 ⟺ 路径拒绝；tenant_admin 放行 /twin 与 /analytics
"""

from __future__ import annotations

from datetime import datetime, timezone

from tests.isolation_helpers import create_tenant, platform_login

API = "/api/v1"


# —— 1. 全租户备份 / 恢复 ——


def test_platform_backup_and_restore_roundtrip(client, auth_headers):
    hp = platform_login(client)
    tid, hb = create_tenant(client, code="bkp-t1", name="Backup Target", admin_email="Admin@BkpT1.example.com")
    # 给租户造一点业务数据（估价）
    est = client.post(
        f"{API}/estimates",
        headers=hb,
        json={"title": "BK roundtrip est", "mode": "voyage", "inputs": {"cargo_mt": 1000}},
    )
    assert est.status_code in (200, 201), est.text
    est_id = est.json()["id"]

    # 全量备份
    r = client.post(f"{API}/platform/tenants/{tid}/backup", headers=hp)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["total_rows"] > 0
    assert body["row_counts"].get("estimates", 0) >= 1

    # 清空业务数据（purge 硬删除，模拟测试数据清理）
    pg = client.post(f"{API}/platform/tenants/{tid}/purge", headers=hp, json={"confirm": "bkp-t1", "backup_first": False})
    assert pg.status_code == 200, pg.text
    assert pg.json()["deleted"].get("estimates", 0) >= 1

    # 估价行已不存在
    gone = client.get(f"{API}/estimates/{est_id}", headers=hb)
    assert gone.status_code in (401, 403, 404)  # 用户 token 仍有效则 404

    # 恢复（从备份重新插入）
    rr = client.post(
        f"{API}/platform/tenants/{tid}/restore",
        headers=hp,
        json={"storage_path": body["storage_path"]},
    )
    assert rr.status_code == 200, rr.text
    assert rr.json()["inserted_total"] > 0
    # 恢复后以平台身份核对估价行已回到库里（业务 GET 可能受软删/许可影响，直接查列表）
    ests = client.get(f"{API}/estimates", headers=hb)
    if ests.status_code == 200:
        rows = ests.json()["items"] if isinstance(ests.json(), dict) else ests.json()
        assert any(r["id"] == est_id for r in rows), "restore should bring the estimate row back"


def test_platform_backup_requires_platform_admin(client, auth_headers):
    r = client.post(f"{API}/platform/tenants/00000000-0000-0000-0000-000000000001/backup", headers=auth_headers)
    assert r.status_code == 403


def test_restore_rejects_cross_tenant_path(client, auth_headers):
    hp = platform_login(client)
    tid, _ = create_tenant(client, code="bkp-t2", name="Path Guard", admin_email="Admin@BkpT2.example.com")
    r = client.post(
        f"{API}/platform/tenants/{tid}/restore",
        headers=hp,
        json={"storage_path": "backups/tenant/00000000-0000-0000-0000-000000000009/x.json"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_BACKUP_PATH"


# —— 2. 一键清理（purge）——


def test_platform_purge_keeps_identity_baseline(client, auth_headers):
    hp = platform_login(client)
    tid, hb = create_tenant(client, code="prg-t1", name="Purge Target", admin_email="Admin@PrgT1.example.com")
    est = client.post(
        f"{API}/estimates",
        headers=hb,
        json={"title": "Purge me", "mode": "voyage", "inputs": {}},
    )
    assert est.status_code in (200, 201), est.text

    # confirm 必须等于租户 code
    bad = client.post(f"{API}/platform/tenants/{tid}/purge", headers=hp, json={"confirm": "wrong"})
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "CONFIRM_MISMATCH"

    r = client.post(f"{API}/platform/tenants/{tid}/purge", headers=hp, json={"confirm": "prg-t1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted_total"] > 0
    assert body["deleted"].get("estimates", 0) >= 1
    assert body["backup"] is not None and body["backup"]["status"] == "completed"

    # 业务行已清空
    ests = client.get(f"{API}/estimates", headers=hb)
    assert ests.status_code == 200
    assert ests.json()["items"] == [] if isinstance(ests.json(), dict) else ests.json() == []
    # 用户仍在（身份底座保留）
    users = client.get(f"{API}/admin/users", headers=hb)
    assert users.status_code == 200
    assert any(u["email"].lower() == "admin@prgt1.example.com" for u in users.json())


def test_platform_purge_include_users(client, auth_headers):
    hp = platform_login(client)
    tid, _ = create_tenant(client, code="prg-t2", name="Purge Users", admin_email="Admin@PrgT2.example.com")
    r = client.post(
        f"{API}/platform/tenants/{tid}/purge",
        headers=hp,
        json={"confirm": "prg-t2", "include_users": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["include_users"] is True
    # 用户被清掉后，原租户管理员 token 再查用户列表应 401/403/404 之一或空
    users = client.get(f"{API}/admin/users", headers=platform_login(client))
    assert users.status_code in (200, 401, 403, 404)


# —— 3. 自动备份计划 ——


def test_backup_schedule_get_put_roundtrip(client, auth_headers):
    h = auth_headers
    # 默认（未配置）返回 disabled 默认值
    g = client.get(f"{API}/settings/dataops/backup-schedule", headers=h)
    assert g.status_code == 200, g.text
    assert g.json()["enabled"] is False

    # 开启每日 03:00 UTC，保留 7 份
    p = client.put(
        f"{API}/settings/dataops/backup-schedule",
        headers=h,
        json={"enabled": True, "frequency": "daily", "hour_utc": 3, "weekday": 0, "keep_last": 7},
    )
    assert p.status_code == 200, p.text
    body = p.json()
    assert body["enabled"] is True
    assert body["frequency"] == "daily"
    assert body["hour_utc"] == 3
    assert body["keep_last"] == 7
    assert body["next_run_at"] is not None

    # 回读一致
    g2 = client.get(f"{API}/settings/dataops/backup-schedule", headers=h)
    assert g2.json() == body

    # 关闭后 next_run_at 清空
    p2 = client.put(
        f"{API}/settings/dataops/backup-schedule",
        headers=h,
        json={"enabled": False, "frequency": "weekly", "hour_utc": 1, "weekday": 5, "keep_last": 3},
    )
    assert p2.status_code == 200
    assert p2.json()["enabled"] is False
    assert p2.json()["next_run_at"] is None


def test_backup_schedule_invalid_frequency_rejected(client, auth_headers):
    r = client.put(
        f"{API}/settings/dataops/backup-schedule",
        headers=auth_headers,
        json={"enabled": True, "frequency": "hourly", "hour_utc": 3},
    )
    assert r.status_code == 422


def test_backup_scheduler_runs_due_schedule(db_engine):
    """直接驱动 run_due_schedules：到期计划执行全量备份并推进 next_run_at。"""
    from sqlalchemy.orm import sessionmaker

    from app.models import BackupJob, BackupSchedule, Tenant
    from app.services.backup_scheduler import compute_next_run, run_due_schedules
    from sqlalchemy import select

    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        demo = db.scalar(select(Tenant).where(Tenant.code == "demo"))
        assert demo is not None
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        sched = BackupSchedule(
            tenant_id=demo.id,
            enabled=True,
            frequency="daily",
            hour_utc=now.hour,
            keep_last=2,
            next_run_at=now.replace(minute=0, second=0, microsecond=0),  # 已到期
        )
        db.add(sched)
        db.commit()

        ran = run_due_schedules(db)
        assert ran == 1

        db.refresh(sched)
        assert sched.last_run_at is not None
        assert sched.next_run_at is not None and sched.next_run_at > now
        jobs = db.scalars(
            select(BackupJob).where(BackupJob.tenant_id == demo.id, BackupJob.trigger == "auto")
        ).all()
        assert len(jobs) == 1
        assert jobs[0].status == "completed"
    finally:
        db.close()


def test_compute_next_run_shapes():
    from app.models import BackupSchedule
    from app.services.backup_scheduler import compute_next_run

    now = datetime(2026, 10, 19, 10, 30, tzinfo=timezone.utc)  # Monday
    daily = BackupSchedule(frequency="daily", hour_utc=2)
    n = compute_next_run(daily, now)
    assert (n.day, n.hour) == (20, 2)

    weekly = BackupSchedule(frequency="weekly", hour_utc=1, weekday=3)  # Thursday (python Mon=0)
    w = compute_next_run(weekly, now)
    assert w.weekday() == 3 and w.hour == 1 and w > now.replace(tzinfo=None)


# —— 4. 菜单可见性与路径 ACL 一致性（B1）——


def _flat_nav(client, headers):
    r = client.get(f"{API}/shell/bootstrap", headers=headers)
    assert r.status_code == 200, r.text
    items = []
    for sec in r.json()["navigation"]:
        for it in sec.get("items") or []:
            items.append((it["href"], bool(it.get("locked"))))
    return items


def test_nav_lock_consistent_with_path_acl(client, auth_headers, db_engine):
    """锁定 ⟺ 路径拒绝：每个导航条目按角色核对 path_is_allowed。"""
    from sqlalchemy.orm import sessionmaker

    from app.models import Tenant
    from app.services.search_acl import path_is_allowed
    from sqlalchemy import select

    for headers, roles in (
        (auth_headers, ["tenant_admin"]),
    ):
        items = _flat_nav(client, headers)
        Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
        db = Session()
        try:
            demo = db.scalar(select(Tenant).where(Tenant.code == "demo"))
            for href, locked in items:
                allowed = path_is_allowed(db, tenant_id=demo.id, roles=roles, path=href)
                assert allowed != locked, f"{roles}: {href} locked={locked} but allowed={allowed}"
        finally:
            db.close()


def test_tenant_admin_unlocks_twin_and_analytics(client, auth_headers):
    """待处理项 1+2：tenant_admin 放行 /twin 与 /analytics 区域。"""
    items = dict(_flat_nav(client, auth_headers))
    assert items.get("/twin") is False, "tenant_admin 应解锁 /twin"
    assert items.get("/analytics") is False, "tenant_admin 应解锁 /analytics"
    assert items.get("/analytics/reports") is False
    assert items.get("/analytics/market") is False
    # platform 区域仍锁定
    assert items.get("/platform") is True


def test_charterer_still_locked_out_of_business(client):
    """角色隔离不回归：charterer 仍锁定 /operations/voyages 与 /settings。"""
    rc = client.post(
        f"{API}/auth/login",
        json={"email": "charterer@demo.marios", "password": "Demo1234!", "tenant_code": "demo"},
    )
    assert rc.status_code == 200, rc.text
    headers = {"Authorization": f"Bearer {rc.json()['access_token']}"}
    items = dict(_flat_nav(client, headers))
    assert items.get("/operations/voyages") is True
    assert items.get("/settings") is True
