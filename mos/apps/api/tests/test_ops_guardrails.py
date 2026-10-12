"""C2 运营护栏：午报审批顺序链 + Tasks & Alerts 可阻断保存。

- out-of-sequence noon → 409 REPORT_SEQUENCE
- in-sequence → 2xx（同阶段允许重复）
- CFGRelaxReportSequence=true → 乱序放行
- blocking 高优先级告警规则 → voyage 写入 409 ALERT_BLOCKED
- 非 blocking / 低档 severity → 只提醒不阻断
- 租户隔离：他租户的规则/航次互不影响
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from tests.isolation_helpers import create_tenant

API = "/api/v1"
T0 = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)


def _mk_voyage(client, h, suffix: str = "") -> dict:
    r = client.post(f"{API}/voyages", headers=h, json={"voyage_no": f"OG-{uuid4().hex[:8]}{suffix}"})
    assert r.status_code == 200, r.text
    return r.json()


def _noon(client, h, voyage_id: str, remarks: str | None = None, offset_hours: int = 0, **extra):
    payload = {
        "voyage_id": voyage_id,
        "report_at": (T0 + timedelta(hours=offset_hours)).isoformat(),
        "remarks": remarks,
    }
    payload.update(extra)
    return client.post(f"{API}/noon-reports", headers=h, json=payload)


def _relax_sequence(client, h, value: bool = True) -> None:
    r = client.post(
        f"{API}/config/flags",
        headers=h,
        json={
            "key": "CFGRelaxReportSequence",
            "value": "true" if value else "false",
            "value_type": "bool",
            "category": "operations",
        },
    )
    assert r.status_code in (200, 201), r.text


def _alert_rule(client, h, *, rule_name: str, cargo_value: str, blocking: bool, priority: str) -> dict:
    r = client.post(
        f"{API}/config/alert-rules",
        headers=h,
        json={
            "rule_name": rule_name,
            "entity_type": "voyage",
            "condition": {"field": "voyage.cargo", "operator": "eq", "value": cargo_value},
            "alert_message": f"cargo {cargo_value} blocked",
            "alert_priority": priority,
            "blocking": blocking,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


# ── Feature 1: Activity Report 审批顺序链 ──────────────────────────────────


def test_noon_out_of_sequence_rejected(client, auth_headers):
    h = auth_headers
    v = _mk_voyage(client, h)
    r1 = _noon(client, h, v["id"], remarks="cargo loading commenced", offset_hours=0)
    assert r1.status_code == 200, r1.text
    assert r1.json()["stage"] == "cargo"

    # arrival 回退（cargo=3 → arrival=1）
    r2 = _noon(client, h, v["id"], remarks="arrival at next port", offset_hours=24)
    assert r2.status_code == 409, r2.text
    detail = r2.json()["detail"]
    assert detail["code"] == "REPORT_SEQUENCE"
    assert detail["previous"] == "cargo"
    assert detail["stage"] == "arrival"


def test_noon_in_sequence_accepted(client, auth_headers):
    h = auth_headers
    v = _mk_voyage(client, h)
    chain = [
        ("vessel arrival at Singapore", "arrival"),
        ("alongside berth, in port", "in_port"),
        ("cargo loading commenced", "cargo"),
        ("bunker stem completed", "bunker"),
        ("vessel departure sailed", "departure"),
        ("statement of facts closed", "sof"),
    ]
    for i, (remarks, expected_stage) in enumerate(chain):
        r = _noon(client, h, v["id"], remarks=remarks, offset_hours=i * 6)
        assert r.status_code == 200, f"step {i} {remarks!r} -> {r.text}"
        assert r.json()["stage"] == expected_stage

    # 同阶段重复允许
    r = _noon(client, h, v["id"], remarks="statement of facts closed", offset_hours=48)
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "sof"


def test_noon_sequence_cycle_reset_after_sof(client, auth_headers):
    """上一挂靠以 sof/departure 收尾后，sea/arrival 可开新一轮。"""
    h = auth_headers
    v = _mk_voyage(client, h)
    assert _noon(client, h, v["id"], remarks="vessel departure sailed", offset_hours=0).status_code == 200
    r = _noon(client, h, v["id"], remarks=None, offset_hours=12, speed=13.5, lat=1.25, lon=103.8)
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "sea"


def test_noon_sequence_relaxed_flag(client, auth_headers):
    h = auth_headers
    v = _mk_voyage(client, h)
    assert _noon(client, h, v["id"], remarks="cargo loading commenced", offset_hours=0).status_code == 200

    _relax_sequence(client, h, True)
    # 乱序（cargo=3 → arrival=1）在开关下放行
    r = _noon(client, h, v["id"], remarks="arrival at next port", offset_hours=24)
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "arrival"

    # 开关恢复后重新强制：departure(5) → cargo(3) 应再次拒绝
    _relax_sequence(client, h, False)
    v2 = _mk_voyage(client, h)
    assert _noon(client, h, v2["id"], remarks="vessel departure sailed", offset_hours=0).status_code == 200
    r2 = _noon(client, h, v2["id"], remarks="cargo loading", offset_hours=6)
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["code"] == "REPORT_SEQUENCE"


def test_noon_sequence_per_voyage_and_tenant_scoped(client, auth_headers):
    """顺序链按航次独立；跨租户 noon 创建 404。"""
    h = auth_headers
    a = _mk_voyage(client, h)
    b = _mk_voyage(client, h)
    assert _noon(client, h, a["id"], remarks="cargo loading", offset_hours=0).status_code == 200
    # B 航次独立开链不受 A 影响
    assert _noon(client, h, b["id"], remarks="vessel arrival at port", offset_hours=0).status_code == 200

    _tid, hb = create_tenant(client, code=f"og-{uuid4().hex[:6]}", name="OG B", admin_email=f"ogb-{uuid4().hex[:6]}@example.com")
    foreign = _mk_voyage(client, hb)
    r = _noon(client, h, foreign["id"], remarks="cargo loading", offset_hours=0)
    assert r.status_code == 404


# ── Feature 2: Tasks & Alerts 可阻断保存 ──────────────────────────────────


def test_voyage_update_blocked_by_alert(client, auth_headers):
    h = auth_headers
    v = _mk_voyage(client, h)
    _alert_rule(
        client, h,
        rule_name="OG Block Cargo",
        cargo_value="BLOCKED_CARGO",
        blocking=True,
        priority="urgent",
    )

    r = client.patch(f"{API}/voyages/{v['id']}", headers=h, json={"cargo": "BLOCKED_CARGO"})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "ALERT_BLOCKED"
    assert "OG Block Cargo" in detail["rules"]

    # 不命中的 cargo 正常保存
    r2 = client.patch(f"{API}/voyages/{v['id']}", headers=h, json={"cargo": "grain"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["cargo"] == "grain"


def test_voyage_create_blocked_by_alert(client, auth_headers):
    h = auth_headers
    _alert_rule(
        client, h,
        rule_name="OG Block Create",
        cargo_value="FORBIDDEN",
        blocking=True,
        priority="high",
    )
    r = client.post(f"{API}/voyages", headers=h, json={"voyage_no": f"OG-{uuid4().hex[:8]}", "cargo": "FORBIDDEN"})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "ALERT_BLOCKED"

    r2 = client.post(f"{API}/voyages", headers=h, json={"voyage_no": f"OG-{uuid4().hex[:8]}", "cargo": "coal"})
    assert r2.status_code == 200, r2.text


def test_voyage_transition_blocked_by_alert(client, auth_headers):
    h = auth_headers
    v = _mk_voyage(client, h)
    # 阻断 in_progress 的规则
    r_rule = client.post(
        f"{API}/config/alert-rules",
        headers=h,
        json={
            "rule_name": "OG Block Start",
            "entity_type": "voyage",
            "condition": {"field": "voyage.status", "operator": "eq", "value": "in_progress"},
            "alert_message": "do not start",
            "alert_priority": "urgent",
            "blocking": True,
        },
    )
    assert r_rule.status_code == 201, r_rule.text

    r = client.post(f"{API}/voyages/{v['id']}/transition", headers=h, json={"target": "in_progress"})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "ALERT_BLOCKED"

    # cancelled 不命中规则，可走
    r2 = client.post(f"{API}/voyages/{v['id']}/transition", headers=h, json={"target": "cancelled"})
    assert r2.status_code == 200, r2.text


def test_voyage_non_blocking_alert_allowed(client, auth_headers):
    """非 blocking 或低档 severity：只评估不阻断。"""
    h = auth_headers
    v = _mk_voyage(client, h)
    # blocking=False + high
    _alert_rule(
        client, h,
        rule_name="OG Warn Only",
        cargo_value="WARN_CARGO",
        blocking=False,
        priority="high",
    )
    # blocking=True + low（非阻断档 severity）
    _alert_rule(
        client, h,
        rule_name="OG Low Blocking",
        cargo_value="WARN_CARGO",
        blocking=True,
        priority="low",
    )

    r = client.patch(f"{API}/voyages/{v['id']}", headers=h, json={"cargo": "WARN_CARGO"})
    assert r.status_code == 200, r.text
    assert r.json()["cargo"] == "WARN_CARGO"


def test_alert_rules_tenant_isolated(client, auth_headers):
    """他租户的 blocking 规则不影响本租户航次写入。"""
    h = auth_headers
    _tid, hb = create_tenant(
        client,
        code=f"og-{uuid4().hex[:6]}",
        name="OG Alert B",
        admin_email=f"ogalert-{uuid4().hex[:6]}@example.com",
    )
    # B 租户的 blocking 规则
    _alert_rule(
        client, hb,
        rule_name="B Only Block",
        cargo_value="CROSS_CARGO",
        blocking=True,
        priority="urgent",
    )
    # A 租户同名 cargo 不受影响
    va = _mk_voyage(client, h)
    r_a = client.patch(f"{API}/voyages/{va['id']}", headers=h, json={"cargo": "CROSS_CARGO"})
    assert r_a.status_code == 200, r_a.text

    # B 租户自己被阻断
    vb = _mk_voyage(client, hb)
    r_b = client.patch(f"{API}/voyages/{vb['id']}", headers=hb, json={"cargo": "CROSS_CARGO"})
    assert r_b.status_code == 409, r_b.text
    assert r_b.json()["detail"]["code"] == "ALERT_BLOCKED"
