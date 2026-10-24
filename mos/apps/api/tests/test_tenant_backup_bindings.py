"""租户备份必须带走「用户的角色 / 组织归属」（审计 P2-10）。

背景
----
``user_roles`` 与 ``user_org_memberships`` 这两张关联表**没有 ``tenant_id`` 列**
（它们按 ``user_id`` 归属）。而租户备份的取数规则是「扫所有带 ``tenant_id``
的表」—— 这两张表因此被整个漏掉。

后果：恢复之后用户**一个角色都没有** —— 登录进去导航全锁、业务数据全看不到，
而备份报告却显示「恢复完成」。

修复：备份额外带一个 ``user_bindings`` 段（用 email / role_code / org id+code
这类**可移植键**），恢复时按这些键把绑定重新绑回去。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from tests.isolation_helpers import create_tenant, platform_login

API = "/api/v1"


def _session(db_engine):
    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    return Session()


def test_backup_carries_user_roles_and_restore_rebinds(client, db_engine):
    """备份 → 删掉绑定 → 恢复 → 绑定必须回来。"""
    from app.models import Role, UserRole
    from app.models_saas import UserOrgMembership
    from app.services.tenant_backup import dump_tenant, restore_tenant

    platform_login(client)
    tid, hb = create_tenant(
        client, code="bkb-t1", name="Binding Backup", admin_email="Admin@BkbT1.example.com"
    )
    tenant_id = UUID(tid)

    # 一个组织单元 + 一个带两个角色、挂在该组织上的用户
    org = client.post(
        f"{API}/admin/org-units",
        headers=hb,
        json={"code": "OPS", "name": "Ops Dept", "unit_type": "dept"},
    )
    assert org.status_code == 200, org.text
    org_id = org.json()["id"]

    created = client.post(
        f"{API}/admin/users",
        headers=hb,
        json={
            "email": "crew@bkb-t1.example.com",
            "full_name": "Crew One",
            "password": "Demo1234!",
            "role_codes": ["viewer", "chartering"],
            "org_unit_id": org_id,
        },
    )
    assert created.status_code == 200, created.text
    user_id = UUID(created.json()["id"])

    db = _session(db_engine)
    try:
        # ── 备份 ──
        payload = dump_tenant(db, tenant_id, trigger="test")
        bindings = payload.get("user_bindings") or {}
        assert bindings.get("roles"), "备份必须带上用户角色绑定"
        assert bindings.get("org_memberships"), "备份必须带上组织归属"

        role_codes = {b["role_code"] for b in bindings["roles"]}
        assert {"viewer", "chartering"} <= role_codes
        assert all(b["email"] for b in bindings["roles"]), "绑定必须用可移植键（email），不能是裸 UUID"
        assert all(b["org_code"] for b in bindings["org_memberships"])

        # 这两张表没有 tenant_id 列 —— 不可能出现在 tables 段里
        assert "user_roles" not in (payload.get("tables") or {})
        assert "user_org_memberships" not in (payload.get("tables") or {})
        # 但行数必须计入对账口径
        assert payload["row_counts"].get("user_roles", 0) >= 3  # 租户管理员 1 + 船员 2

        # ── 模拟「恢复丢了绑定」：把绑定行删掉 ──
        db.execute(delete(UserRole).where(UserRole.user_id == user_id))
        db.execute(delete(UserOrgMembership).where(UserOrgMembership.user_id == user_id))
        db.commit()
        assert db.scalars(select(UserRole).where(UserRole.user_id == user_id)).all() == []

        # ── 恢复 ──
        result = restore_tenant(db, tenant_id, payload)
        assert result["inserted"].get("user_roles", 0) >= 2, result
        assert result["inserted"].get("user_org_memberships", 0) >= 1, result

        rows = db.scalars(select(UserRole).where(UserRole.user_id == user_id)).all()
        assert len(rows) == 2, "恢复后用户角色必须回来"

        # 角色确实指向本租户的角色（不能串到别的租户）
        codes = set(
            db.scalars(
                select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
            ).all()
        )
        assert {"viewer", "chartering"} <= codes

        mem = db.scalars(select(UserOrgMembership).where(UserOrgMembership.user_id == user_id)).all()
        assert len(mem) == 1
        assert str(mem[0].org_unit_id) == org_id

        # 对账口径必须自洽：备份记了多少、恢复回来多少
        assert not result["mismatched_tables"], result["mismatched_tables"]
    finally:
        db.close()


def test_restore_ignores_bindings_of_another_tenant(client, db_engine):
    """备份里的绑定**不得**把用户挂到别的租户的角色上（越权）。"""
    from app.models import Role, User, UserRole
    from app.services.tenant_backup import dump_tenant, restore_tenant

    platform_login(client)
    tid, _hb = create_tenant(
        client, code="bkb-t2", name="Binding Cross", admin_email="Admin@BkbT2.example.com"
    )
    tenant_id = UUID(tid)

    db = _session(db_engine)
    try:
        payload = dump_tenant(db, tenant_id, trigger="test")
        # 注入一条**外部租户**的角色绑定
        foreign_role = db.scalar(select(Role).where(Role.code == "viewer", Role.tenant_id != tenant_id))
        assert foreign_role is not None
        victim = db.scalar(select(User).where(User.tenant_id == tenant_id))
        payload["user_bindings"]["roles"].append(
            {"email": victim.email, "role_code": "viewer", "role_id": str(foreign_role.id)}
        )

        db.execute(delete(UserRole).where(UserRole.user_id == victim.id))
        db.commit()

        restore_tenant(db, tenant_id, payload)

        rows = db.scalars(select(UserRole).where(UserRole.user_id == victim.id)).all()
        assert all(str(r.role_id) != str(foreign_role.id) for r in rows), "不得挂到外部租户的角色"
    finally:
        db.close()
