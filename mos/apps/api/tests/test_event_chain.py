"""事件驱动全链路：estimate→charter→voyage→SOF/laytime/claim→invoice→PDA→bunker→完成。

验证「系统是驱动力而非记录」：
- 业务节点 emit 域事件 → domain_events 落行；
- 处理器生成分部门跟进任务（source=system）+ 通知；
- 航次完成 → 日程收缩 + TCE 快照 + 收尾清单缺项任务；
- PDA 关闭自动过账（无科目规则 → 降级任务，不静默）；
- COA 超装/短装、修订财务复核、索赔转结算等支线。
"""

from __future__ import annotations

import uuid as _uuidlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker


def _make_vessel(client, h, tag="evt") -> dict:
    r = client.post("/api/v1/masterdata/vessels", headers=h, json={"name": f"{tag} vessel"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _make_party(client, h, name="Event Charterer") -> dict:
    r = client.post(
        "/api/v1/masterdata/counterparties",
        headers=h,
        json={"name": name, "type": "charterer"},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def _events(db, tenant_id, kind=None):
    from app.models_ops import DomainEvent

    q = select(DomainEvent).where(DomainEvent.tenant_id == tenant_id)
    if kind:
        q = q.where(DomainEvent.kind == kind)
    return db.scalars(q).all()


def _tasks(db, tenant_id, title_contains=None):
    from app.models_task import Task

    q = select(Task).where(Task.tenant_id == tenant_id)
    rows = db.scalars(q).all()
    if title_contains:
        rows = [t for t in rows if title_contains in (t.title or "")]
    return rows


# ── 全链路主干 ─────────────────────────────────────────────────────────────


def test_full_chain_event_driven_closeout(client, auth_headers, db_engine):
    h = auth_headers
    Session = sessionmaker(bind=db_engine)

    # tenant id —— 从 demo 用户取
    with Session() as db:
        from app.models import User

        user = db.scalar(select(User).where(User.email == "admin@demo.marios"))
        assert user is not None
        tenant_id = user.tenant_id

    # 1) Estimate → charter（关联 estimate，收尾时算 estimate TCE）
    vessel = _make_vessel(client, h, "chain")
    party = _make_party(client, h, "Chain Charterers")
    ports = client.get("/api/v1/masterdata/ports", headers=h).json()
    ports = ports["items"] if isinstance(ports, dict) else ports
    load_port = ports[0]["id"] if ports else None
    disc_port = ports[1]["id"] if len(ports) > 1 else load_port

    est = client.post(
        "/api/v1/estimates",
        headers=h,
        json={
            "title": "Chain event voyage",
            "vessel_id": vessel["id"],
            "counterparty_id": party["id"],
            "inputs": {
                "cargo_qty": 40000,
                "freight_rate": 17.0,
                "commission_pct": 2.5,
                "sea_days": 20,
                "port_days": 6,
                "bunker_sea_tpd": 25,
                "bunker_port_tpd": 3,
                "bunker_price": 450,
                "port_costs": 60000,
                "cargo": "Coal",
            },
        },
    )
    assert est.status_code == 200, est.text
    est_id = est.json()["id"]
    assert client.post(f"/api/v1/estimates/{est_id}/calculate", headers=h).status_code == 200

    cp = client.post(f"/api/v1/estimates/{est_id}/to-charter", headers=h, json={})
    assert cp.status_code == 200, cp.text
    charter_id = cp.json()["id"]
    client.post(f"/api/v1/charters/{charter_id}/transition", headers=h, json={"target": "pending_approval"})
    act = client.post(f"/api/v1/charters/{charter_id}/transition", headers=h, json={"target": "active"})
    assert act.status_code == 200, act.text

    # 激活自动建航次
    linked = client.get(f"/api/v1/charters/{charter_id}/voyages", headers=h).json()
    assert len(linked) == 1
    voyage_id = linked[0]["id"]

    # 2) 航次执行：port calls + SOF + laytime + claim
    assert client.post(f"/api/v1/voyages/{voyage_id}/transition", headers=h, json={"target": "in_progress"}).status_code == 200
    now = datetime.now(timezone.utc)
    pc1 = client.post(
        "/api/v1/port-calls",
        headers=h,
        json={
            "voyage_id": voyage_id,
            "port_id": load_port,
            "seq": 1,
            "purpose": "load",
            "eta": (now + timedelta(days=2)).isoformat(),
        },
    )
    assert pc1.status_code == 200, pc1.text
    # ata/atd 走 PATCH（PortCallIn 不含实际时刻）
    ata_r = client.patch(
        f"/api/v1/port-calls/{pc1.json()['id']}",
        headers=h,
        json={
            "ata": (now + timedelta(days=2, hours=1)).isoformat(),
            "atd": (now + timedelta(days=4)).isoformat(),
        },
    )
    assert ata_r.status_code == 200, ata_r.text
    for code in ("COMMENCED", "COMPLETED"):
        r = client.post(
            "/api/v1/sof-events",
            headers=h,
            json={
                "port_call_id": pc1.json()["id"],
                "event_code": code,
                "event_at": now.isoformat(),
                "local_tz": "UTC",
            },
        )
        assert r.status_code == 200, r.text

    lt = client.post(
        "/api/v1/laytimes",
        headers=h,
        json={
            "voyage_id": voyage_id,
            "port_call_id": pc1.json()["id"],
            "inputs": {
                "allowed_hours": 48,
                "events": [{"start": "2026-09-01T08:00:00", "end": "2026-09-03T08:00:00", "excluded": False}],
            },
        },
    )
    assert lt.status_code == 200, lt.text
    lt_id = lt.json()["id"]
    assert client.post(f"/api/v1/laytimes/{lt_id}/calculate", headers=h).status_code == 200
    assert client.post(f"/api/v1/laytimes/{lt_id}/finalize", headers=h).status_code == 200

    claim = client.post(
        "/api/v1/claims",
        headers=h,
        json={"voyage_id": voyage_id, "laytime_id": lt_id, "claim_type": "demurrage"},
    )
    assert claim.status_code == 200, claim.text
    claim_id = claim.json()["id"]
    assert (
        client.post(f"/api/v1/claims/{claim_id}/transition?target=settled", headers=h).status_code == 200
    )
    # 索赔和解 → 财务转结算任务
    with Session() as db:
        tasks = _tasks(db, tenant_id, "索赔转结算")
        assert tasks, "claim.settled 应生成财务任务"
        assert tasks[0].source == "system"
        assert tasks[0].assignee_user_id is not None  # finance 角色 → 首个在职用户

    # 3) 发票签发 → 财务过账任务
    inv = client.post(
        "/api/v1/invoices",
        headers=h,
        json={
            "invoice_type": "freight",
            "counterparty_id": party["id"],
            "voyage_id": voyage_id,
            "amount": 680000,
            "due_date": "2026-12-01",
        },
    )
    assert inv.status_code == 200, inv.text
    iid = inv.json()["id"]
    assert client.post(f"/api/v1/invoices/{iid}/transition?target=pending_approval", headers=h).status_code == 200
    assert client.post(f"/api/v1/invoices/{iid}/transition?target=issued", headers=h).status_code == 200
    with Session() as db:
        assert _tasks(db, tenant_id, "过账总账：发票"), "invoice.issued 应生成财务过账任务"

    # 4) PDA 关闭 → 自动过账或降级任务（测试库无科目规则 → 任务，不静默）
    pda = client.post(
        "/api/v1/port-disbursements",
        headers=h,
        json={"voyage_id": voyage_id, "pda_amount": 42000, "lines": {"pilotage": 4000}},
    )
    assert pda.status_code == 200, pda.text
    pid = pda.json()["id"]
    for t in ("submitted", "approved"):
        assert client.post(f"/api/v1/port-disbursements/{pid}/transition?target={t}", headers=h).status_code == 200
    assert (
        client.post(f"/api/v1/port-disbursements/{pid}/transition?target=fda&fda_amount=44000", headers=h).status_code
        == 200
    )
    assert client.post(f"/api/v1/port-disbursements/{pid}/transition?target=closed", headers=h).status_code == 200
    with Session() as db:
        evs = _events(db, tenant_id, "pda.closed")
        assert evs, "pda.closed 事件应落 domain_events"
        # 降级任务或成功通知 —— 测试库通常无 port_disbursement 科目规则
        pda_tasks = _tasks(db, tenant_id, "PDA 待过账")
        assert pda_tasks or evs[0].handler_errors is not None  # 二者至少有痕迹

    # 5) 加油交付（正常交付，无偏差 → 无任务）
    bo = client.post(
        "/api/v1/bunker-orders",
        headers=h,
        json={"voyage_id": voyage_id, "vessel_id": vessel["id"], "fuel_type": "VLSFO", "qty_ordered": 500, "unit_price": 450},
    )
    assert bo.status_code in (200, 201), bo.text
    bid = bo.json()["id"]
    for t in ("inquiry", "ordered"):
        assert client.post(f"/api/v1/bunker-orders/{bid}/transition?target={t}", headers=h).status_code == 200
    dlv = client.post(
        f"/api/v1/bunker-orders/{bid}/transition?target=delivered&qty_delivered=500&bdn_qty=500",
        headers=h,
    )
    assert dlv.status_code == 200, dlv.text
    with Session() as db:
        assert _events(db, tenant_id, "bunker.delivered"), "bunker.delivered 事件应落行"

    # 6) 航次完成 → 收尾链
    # 先放一段比完成时刻晚的日程块，验证收缩
    done_at = now + timedelta(days=25)
    with Session() as db:
        from app.models_domain import ScheduleBlock, Voyage

        voyage = db.get(Voyage, _uuidlib.UUID(voyage_id))
        voyage.completed_at = done_at.replace(tzinfo=None)
        db.add(
            ScheduleBlock(
                tenant_id=tenant_id,
                vessel_id=_uuidlib.UUID(vessel["id"]),
                block_type="voyage",
                title="chain-block",
                start_at=(now + timedelta(days=2)).replace(tzinfo=None),
                end_at=(done_at + timedelta(days=5)).replace(tzinfo=None),
                voyage_id=voyage.id,
            )
        )
        db.commit()

    comp = client.post(f"/api/v1/voyages/{voyage_id}/transition", headers=h, json={"target": "completed"})
    assert comp.status_code == 200, comp.text

    with Session() as db:
        # 域事件落行
        evs = _events(db, tenant_id, "voyage.completed")
        assert any(e.entity_id and str(e.entity_id) == voyage_id for e in evs)
        voyage = db.get(Voyage, _uuidlib.UUID(voyage_id))
        # TCE 快照写入 meta
        snap = (voyage.meta or {}).get("tce_snapshot")
        assert snap is not None, "航次完成应写入 tce_snapshot"
        assert snap.get("estimate_tce") is not None or snap.get("actual_tce") is not None
        # 日程收缩：end_at 不再超过 completed_at
        block = db.scalar(
            select(ScheduleBlock).where(
                ScheduleBlock.tenant_id == tenant_id,
                ScheduleBlock.title == "chain-block",
            )
        )
        assert block is not None
        assert block.end_at <= voyage.completed_at, "完成后的日程块应收缩到 completed_at"

    # closing-check 端点：主干项应齐备
    chk = client.get(f"/api/v1/voyages/{voyage_id}/closing-check", headers=h)
    assert chk.status_code == 200, chk.text
    body = chk.json()
    by_key = {i["key"]: i for i in body["items"]}
    assert by_key["port_calls"]["ok"] is True
    assert by_key["sof"]["ok"] is True
    assert by_key["laytime"]["ok"] is True
    assert by_key["claims"]["ok"] is True  # 已 settled
    assert by_key["invoices"]["ok"] is True  # 已 issued
    assert by_key["bunker"]["ok"] is True  # delivered
    assert "tce" in body and body["tce"].get("estimate_tce") is not None


# ── 收尾缺项 → 自动分派任务 ─────────────────────────────────────────────────


def test_voyage_completion_generates_followup_tasks_for_missing(client, auth_headers, db_engine):
    """裸航次完成（无挂靠港/无发票）→ 收尾缺项生成 ops/finance 任务。"""
    h = auth_headers
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        from app.models import User

        user = db.scalar(select(User).where(User.email == "admin@demo.marios"))
        tenant_id = user.tenant_id

    v = client.post("/api/v1/voyages", headers=h, json={"voyage_no": "V-EVT-BARE"})
    assert v.status_code in (200, 201), v.text
    vid = v.json()["id"]
    assert client.post(f"/api/v1/voyages/{vid}/transition", headers=h, json={"target": "in_progress"}).status_code == 200

    # 先清掉同名任务，避免历史干扰
    with Session() as db:
        from app.models_task import Task

        for t in _tasks(db, tenant_id, "V-EVT-BARE"):
            db.delete(t)
        db.commit()

    assert client.post(f"/api/v1/voyages/{vid}/transition", headers=h, json={"target": "completed"}).status_code == 200

    with Session() as db:
        titles = [t.title for t in _tasks(db, tenant_id, "V-EVT-BARE")]
        assert any("补录挂靠港" in x for x in titles), titles
        assert any("补录 SOF" in x for x in titles), titles
        # 系统任务全部 source=system
        for t in _tasks(db, tenant_id, "V-EVT-BARE"):
            assert t.source == "system"

    # 重开 → 再完成：任务幂等（不重复生成）
    assert client.post(f"/api/v1/voyages/{vid}/transition", headers=h, json={"target": "in_progress"}).status_code == 200
    assert client.post(f"/api/v1/voyages/{vid}/transition", headers=h, json={"target": "completed"}).status_code == 200
    with Session() as db:
        dup = [t for t in _tasks(db, tenant_id, "补录挂靠港 — V-EVT-BARE")]
        assert len(dup) == 1, "ensure_task 应幂等"


# ── 支线：COA 超装 / 修订财务复核 / 破产名单复检 ──────────────────────────────


def test_coa_overlift_generates_alert_and_task(client, auth_headers, db_engine):
    h = auth_headers
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        from app.models import User

        user = db.scalar(select(User).where(User.email == "admin@demo.marios"))
        tenant_id = user.tenant_id

    v = _make_vessel(client, h, "coa-over")
    ch = client.post(
        "/api/v1/charters",
        headers=h,
        json={"charter_type": "coa", "vessel_id": v["id"], "cargo_qty": 30000},
    )
    assert ch.status_code in (200, 201), ch.text
    cid = ch.json()["id"]

    lift = client.post(
        f"/api/v1/charters/{cid}/liftings",
        headers=h,
        params={"period_label": "2026-03", "planned_qty": 32000.0},
    )
    assert lift.status_code in (200, 201), lift.text
    lid = lift.json()["id"]
    client.post(
        f"/api/v1/coa-liftings/{lid}/nominate",
        headers=h,
        json={"laycan_from": "2026-03-01T00:00:00Z", "laycan_to": "2026-03-10T00:00:00Z"},
    )
    fx = client.post(f"/api/v1/coa-liftings/{lid}/fix", headers=h, json={})
    assert fx.status_code == 200, fx.text
    with Session() as db:
        assert _tasks(db, tenant_id, "执行提货航次"), "lifting.fixed 应生成 ops 跟进任务"

    done = client.post(f"/api/v1/coa-liftings/{lid}/complete", headers=h, json={"actual_qty": 32000.0})
    assert done.status_code == 200, done.text
    with Session() as db:
        assert _tasks(db, tenant_id, "COA 超装复核"), "累计超装 102% 应生成商务复核任务"
        from app.models_domain import TwinAlert

        alerts = db.scalars(
            select(TwinAlert).where(TwinAlert.tenant_id == tenant_id, TwinAlert.title.like("%超装%"))
        ).all()
        assert alerts, "超装应生成 TwinAlert"

    # 进度端点：over_lifted 标记
    prog = client.get(f"/api/v1/charters/{cid}/coa-progress", headers=h)
    assert prog.status_code == 200, prog.text
    pj = prog.json()
    assert pj["lifted_qty"] == 32000.0
    assert pj["over_lifted"] is True


def test_amendment_approval_notifies_and_flags_finance(client, auth_headers, db_engine):
    h = auth_headers
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        from app.models import User

        user = db.scalar(select(User).where(User.email == "admin@demo.marios"))
        tenant_id = user.tenant_id

    v = _make_vessel(client, h, "amend")
    party = _make_party(client, h, "Amend Charterers")
    ch = client.post(
        "/api/v1/charters",
        headers=h,
        json={"charter_type": "voyage", "vessel_id": v["id"], "counterparty_id": party["id"], "demurrage_rate": 18000},
    )
    assert ch.status_code in (200, 201), ch.text
    cid = ch.json()["id"]
    client.post(f"/api/v1/charters/{cid}/transition", headers=h, json={"target": "pending_approval"})
    assert client.post(f"/api/v1/charters/{cid}/transition", headers=h, json={"target": "active"}).status_code == 200

    # 关联航次 + 未结发票
    linked = client.get(f"/api/v1/charters/{cid}/voyages", headers=h).json()
    voyage_id = linked[0]["id"] if linked else None
    if voyage_id:
        inv = client.post(
            "/api/v1/invoices",
            headers=h,
            json={
                "invoice_type": "demurrage",
                "counterparty_id": party["id"],
                "voyage_id": voyage_id,
                "amount": 18000,
                "due_date": "2026-12-15",
            },
        )
        assert inv.status_code == 200, inv.text

    amd = client.post(
        f"/api/v1/charters/{cid}/amendments",
        headers=h,
        json={"changes": {"demurrage_rate": 22000}, "reason": "市场调整"},
    )
    assert amd.status_code == 200, amd.text
    ap = client.post(f"/api/v1/charter-amendments/{amd.json()['id']}/approve", headers=h)
    assert ap.status_code == 200, ap.text

    with Session() as db:
        assert _events(db, tenant_id, "charter.amendment_approved"), "修订批准应落域事件"
        if voyage_id:
            assert _tasks(db, tenant_id, "按修订条款复核发票"), "金额条款变更 + 未结发票 → 财务复核任务"


def test_sanctions_recheck_blocks_charter_activation(client, auth_headers):
    """激活时对对手方做实时制裁复检（不只依赖缓存标志）。"""
    h = auth_headers
    party = client.post(
        "/api/v1/masterdata/counterparties",
        headers=h,
        json={"name": "Fresh Blocked Co", "type": "charterer", "sanctions_status": "blocked"},
    )
    assert party.status_code == 200
    v = _make_vessel(client, h, "sanc")
    ch = client.post(
        "/api/v1/charters",
        headers=h,
        json={"charter_type": "voyage", "vessel_id": v["id"], "counterparty_id": party.json()["id"]},
    )
    assert ch.status_code in (200, 201)
    client.post(f"/api/v1/charters/{ch.json()['id']}/transition", headers=h, json={"target": "pending_approval"})
    r = client.post(f"/api/v1/charters/{ch.json()['id']}/transition", headers=h, json={"target": "active"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "SANCTIONS_BLOCKED"


# ── 单元：ensure_task 幂等 / materialize_task_rules / handler 错误留痕 ────────


def test_ensure_task_idempotent_and_handler_errors_captured(db_engine):
    Session = sessionmaker(bind=db_engine)
    from app.models import User
    from app.models_ops import DomainEvent
    from app.services.domain_events import emit, ensure_task, on
    from app.models_task import Task
    from sqlalchemy import select as _sel

    with Session() as db:
        user = db.scalar(_sel(User).where(User.email == "admin@demo.marios"))
        tenant_id = user.tenant_id

        t1 = ensure_task(db, tenant_id, title="幂等任务 A", entity_type="voyage", entity_id=None)
        t2 = ensure_task(db, tenant_id, title="幂等任务 A", entity_type="voyage", entity_id=None)
        assert t1.id == t2.id
        # 带实体时按实体去重
        from uuid import uuid4

        e1 = ensure_task(db, tenant_id, title="幂等任务 B", entity_type="voyage", entity_id=uuid4())
        e2 = ensure_task(db, tenant_id, title="幂等任务 B", entity_type="voyage", entity_id=e1.entity_id)
        assert e1.id == e2.id
        db.rollback()

        # handler 异常 → handler_errors 留痕，不抛出
        @on("test.boom")
        def _boom(db_, ev):
            raise RuntimeError("boom")

        try:
            ev = emit(db, tenant_id, "test.boom", "test", None)
            db.flush()
            assert ev.handler_errors and "boom" in ev.handler_errors[0]
            assert DomainEvent  # noqa: F841
            assert db.scalar(_sel(DomainEvent).where(DomainEvent.kind == "test.boom")) is not None
        finally:
            from app.services import domain_events as de

            de._HANDLERS["test.boom"].remove(_boom)
            db.rollback()


def test_materialize_task_rules_creates_tasks(db_engine):
    """TaskRule dry-run → 物化为真实任务（配置驱动的最后一环）。"""
    Session = sessionmaker(bind=db_engine)
    from app.models import User
    from app.services.alert_engine import create_task_rule
    from app.services.domain_events import materialize_task_rules

    with Session() as db:
        user = db.scalar(select(User).where(User.email == "admin@demo.marios"))
        tenant_id = user.tenant_id
        create_task_rule(
            db,
            tenant_id,
            rule_name="evt-test-rule",
            trigger_entity_type="voyage",
            trigger_condition={"field": "voyage.status", "operator": "eq", "value": "completed"},
            task_title="规则生成任务 — V-RULE",
            assign_to_role="operations",
            due_days_offset=2,
        )
        db.flush()
        created = materialize_task_rules(
            db,
            tenant_id,
            "voyage",
            {"voyage": {"voyage_no": "V-RULE-1", "status": "completed"}},
            entity_id=None,
        )
        assert created, "条件命中的规则应生成任务"
        assert any("V-RULE" in t.title for t in created)
        assert all(t.source == "system" for t in created)
        db.rollback()
