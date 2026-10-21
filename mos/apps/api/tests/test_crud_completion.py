"""CRUD 补齐回归：运营子实体（port call / SOF / noon / off-hire）的 PATCH + DELETE。

背景：这些实体此前只能新增（ADD-ONLY），本批补齐编辑/软删端点与
「按挂靠港存活过滤」的列表语义。全站其余资源的补齐沿用同一范式。
"""

from datetime import datetime, timedelta, timezone

T0 = datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc)


def _mk_voyage(client, h, voyage_no="CRUD-1"):
    v = client.post("/api/v1/voyages", headers=h, json={"voyage_no": voyage_no})
    assert v.status_code == 200, v.text
    return v.json()


def _mk_port_call(client, h, voyage_id, seq=1):
    pc = client.post("/api/v1/port-calls", headers=h, json={"voyage_id": voyage_id, "seq": seq, "purpose": "load"})
    assert pc.status_code == 200, pc.text
    return pc.json()


# ── Port calls ──────────────────────────────────────────────


def test_port_call_patch_partial_update(client, auth_headers):
    v = _mk_voyage(client, auth_headers, "CRUD-PC-PATCH")
    pc = _mk_port_call(client, auth_headers, v["id"])
    r = client.patch(
        f"/api/v1/port-calls/{pc['id']}",
        headers=auth_headers,
        json={"seq": 7, "purpose": "discharge", "eta": "2026-04-02T10:00:00Z", "agent": "Acme Agents"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["seq"] == 7
    assert body["purpose"] == "discharge"
    assert body["agent"] == "Acme Agents"
    assert body["eta"].startswith("2026-04-02T10:00")
    # 未传字段不动
    assert body["etd"] == pc["etd"]


def test_port_call_patch_function_code_normalized(client, auth_headers):
    v = _mk_voyage(client, auth_headers, "CRUD-PC-FN")
    pc = _mk_port_call(client, auth_headers, v["id"])
    r = client.patch(f"/api/v1/port-calls/{pc['id']}", headers=auth_headers, json={"function_code": "l"})
    assert r.status_code == 200, r.text
    assert r.json()["function_code"] == "L"


def test_port_call_delete_hides_and_404s(client, auth_headers):
    v = _mk_voyage(client, auth_headers, "CRUD-PC-DEL")
    pc = _mk_port_call(client, auth_headers, v["id"])
    r = client.delete(f"/api/v1/port-calls/{pc['id']}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # 列表隐藏
    rows = client.get(f"/api/v1/port-calls?voyage_id={v['id']}", headers=auth_headers).json()
    assert all(x["id"] != pc["id"] for x in rows)
    # 再删 404
    assert client.delete(f"/api/v1/port-calls/{pc['id']}", headers=auth_headers).status_code == 404
    # 编辑 404
    assert client.patch(f"/api/v1/port-calls/{pc['id']}", headers=auth_headers, json={"seq": 2}).status_code == 404


def test_port_call_soft_delete_restorable(client, auth_headers):
    v = _mk_voyage(client, auth_headers, "CRUD-PC-RESTORE")
    pc = _mk_port_call(client, auth_headers, v["id"])
    assert client.delete(f"/api/v1/port-calls/{pc['id']}", headers=auth_headers).status_code == 200
    rb = client.get("/api/v1/recycle-bin", headers=auth_headers)
    assert rb.status_code == 200
    hit = [x for x in rb.json() if x["entity_type"] == "port_call" and x["entity_id"] == pc["id"]]
    assert hit, "port_call delete should land in recycle bin"
    rs = client.post(f"/api/v1/recycle-bin/{hit[0]['id']}/restore", headers=auth_headers)
    assert rs.status_code == 200, rs.text
    rows = client.get(f"/api/v1/port-calls?voyage_id={v['id']}", headers=auth_headers).json()
    assert any(x["id"] == pc["id"] for x in rows), "restored port call should be listed again"


def test_deleted_port_call_sof_events_hidden(client, auth_headers):
    """挂靠港软删后，其 SOF 事件随之隐藏；恢复挂靠港后重新可见。"""
    v = _mk_voyage(client, auth_headers, "CRUD-SOF-HIDE")
    pc = _mk_port_call(client, auth_headers, v["id"])
    sof = client.post(
        "/api/v1/sof-events",
        headers=auth_headers,
        json={"port_call_id": pc["id"], "event_code": "NOR", "event_at": T0.isoformat()},
    )
    assert sof.status_code == 200
    assert client.delete(f"/api/v1/port-calls/{pc['id']}", headers=auth_headers).status_code == 200
    # 按航次与按挂靠港查询都不再暴露
    by_voy = client.get(f"/api/v1/sof-events?voyage_id={v['id']}", headers=auth_headers).json()
    assert all(x["id"] != sof.json()["id"] for x in by_voy)
    by_pc = client.get(f"/api/v1/sof-events?port_call_id={pc['id']}", headers=auth_headers).json()
    assert all(x["id"] != sof.json()["id"] for x in by_pc)
    # sof-summary 404
    assert client.get(f"/api/v1/port-calls/{pc['id']}/sof-summary", headers=auth_headers).status_code == 404


# ── SOF events ──────────────────────────────────────────────


def test_sof_event_patch_time_and_derived_sync(client, auth_headers):
    v = _mk_voyage(client, auth_headers, "CRUD-SOF-PATCH")
    pc = _mk_port_call(client, auth_headers, v["id"])
    nor = client.post(
        "/api/v1/sof-events",
        headers=auth_headers,
        json={"port_call_id": pc["id"], "event_code": "NOR", "event_at": T0.isoformat()},
    ).json()
    r = client.patch(
        f"/api/v1/sof-events/{nor['id']}",
        headers=auth_headers,
        json={"event_at": (T0 + timedelta(hours=1)).isoformat(), "remarks": "bumped"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["event_at"].startswith("2026-04-01T09:00")
    assert r.json()["remarks"] == "bumped"
    # 派生字段同步：pc.nor_at / ata 跟随 NOR 新时间
    row = client.get(f"/api/v1/port-calls?voyage_id={v['id']}", headers=auth_headers).json()[0]
    assert row["nor_at"].startswith("2026-04-01T09:00")
    assert row["ata"].startswith("2026-04-01T09:00")


def test_sof_event_patch_sequence_violation(client, auth_headers):
    v = _mk_voyage(client, auth_headers, "CRUD-SOF-SEQ")
    pc = _mk_port_call(client, auth_headers, v["id"])
    nor = client.post(
        "/api/v1/sof-events",
        headers=auth_headers,
        json={"port_call_id": pc["id"], "event_code": "NOR", "event_at": T0.isoformat()},
    ).json()
    com = client.post(
        "/api/v1/sof-events",
        headers=auth_headers,
        json={"port_call_id": pc["id"], "event_code": "COMMENCED", "event_at": (T0 + timedelta(hours=5)).isoformat()},
    ).json()
    # 把 COMMENCED 改早于 NOR → 422
    r = client.patch(
        f"/api/v1/sof-events/{com['id']}",
        headers=auth_headers,
        json={"event_at": (T0 - timedelta(hours=1)).isoformat()},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "SOF_SEQUENCE_VIOLATION"
    # 把 NOR 改晚于 COMMENCED → 422
    r = client.patch(
        f"/api/v1/sof-events/{nor['id']}",
        headers=auth_headers,
        json={"event_at": (T0 + timedelta(hours=6)).isoformat()},
    )
    assert r.status_code == 422
    # 自身排除：同一时刻允许（并列最早）
    r = client.patch(f"/api/v1/sof-events/{nor['id']}", headers=auth_headers, json={"event_at": T0.isoformat()})
    assert r.status_code == 200


def test_sof_event_delete_hidden(client, auth_headers):
    v = _mk_voyage(client, auth_headers, "CRUD-SOF-DEL")
    pc = _mk_port_call(client, auth_headers, v["id"])
    sof = client.post(
        "/api/v1/sof-events",
        headers=auth_headers,
        json={"port_call_id": pc["id"], "event_code": "NOR", "event_at": T0.isoformat()},
    ).json()
    assert client.delete(f"/api/v1/sof-events/{sof['id']}", headers=auth_headers).status_code == 200
    rows = client.get(f"/api/v1/sof-events?port_call_id={pc['id']}", headers=auth_headers).json()
    assert all(x["id"] != sof["id"] for x in rows)
    # 软删后的 NOR 不再参与时序校验：晚于它的非豁免事件可录入
    r = client.post(
        "/api/v1/sof-events",
        headers=auth_headers,
        json={"port_call_id": pc["id"], "event_code": "COMMENCED", "event_at": T0.isoformat()},
    )
    assert r.status_code == 200


# ── Noon reports ────────────────────────────────────────────


def _mk_noon(client, h, voyage_id, **over):
    payload = {"voyage_id": voyage_id, "report_at": T0.isoformat(), "speed": 12.0, "remarks": "ok"}
    payload.update(over)
    r = client.post("/api/v1/noon-reports", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_noon_list_get_patch_delete(client, auth_headers):
    v = _mk_voyage(client, auth_headers, "CRUD-NOON")
    noon = _mk_noon(client, auth_headers, v["id"], speed=11.0)
    nid = noon["id"]

    lst = client.get(f"/api/v1/noon-reports?voyage_id={v['id']}", headers=auth_headers)
    assert lst.status_code == 200, lst.text
    rows = [x for x in lst.json() if x["id"] == nid]
    assert len(rows) == 1
    assert rows[0]["speed"] == 11.0
    assert rows[0]["stage"]  # 推导阶段随列表返回

    g = client.get(f"/api/v1/noon-reports/{nid}", headers=auth_headers)
    assert g.status_code == 200
    assert g.json()["remarks"] == "ok"

    p = client.patch(f"/api/v1/noon-reports/{nid}", headers=auth_headers, json={"speed": 13.5, "remarks": "edited"})
    assert p.status_code == 200, p.text
    assert p.json()["speed"] == 13.5
    assert p.json()["remarks"] == "edited"

    assert client.delete(f"/api/v1/noon-reports/{nid}", headers=auth_headers).status_code == 200
    rows = client.get(f"/api/v1/noon-reports?voyage_id={v['id']}", headers=auth_headers).json()
    assert all(x["id"] != nid for x in rows)
    assert client.get(f"/api/v1/noon-reports/{nid}", headers=auth_headers).status_code == 404


def test_noon_eta_deviation_recomputed_on_patch(client, auth_headers):
    v = _mk_voyage(client, auth_headers, "CRUD-NOON-DEV")
    pc = _mk_port_call(client, auth_headers, v["id"])
    # 给挂靠港 ETA，便于偏差计算
    client.patch(
        f"/api/v1/port-calls/{pc['id']}", headers=auth_headers, json={"eta": "2026-04-03T00:00:00Z"}
    )
    noon = _mk_noon(client, auth_headers, v["id"])
    p = client.patch(
        f"/api/v1/noon-reports/{noon['id']}",
        headers=auth_headers,
        json={"eta_next": "2026-04-04T00:00:00Z"},
    )
    assert p.status_code == 200, p.text
    # 24h 偏差
    assert abs(p.json()["eta_deviation_hours"] - 24.0) < 0.01


# ── Off-hire ────────────────────────────────────────────────


def test_off_hire_patch_and_closed_delete_409(client, auth_headers):
    v = _mk_voyage(client, auth_headers, "CRUD-OH")
    oh = client.post(
        f"/api/v1/voyages/{v['id']}/off-hire",
        headers=auth_headers,
        json={"start_at": T0.isoformat(), "reason": "breakdown", "deduct_hire": True},
    )
    assert oh.status_code == 200, oh.text
    ohid = oh.json()["id"]

    p = client.patch(
        f"/api/v1/off-hire/{ohid}",
        headers=auth_headers,
        json={"end_at": (T0 + timedelta(days=2)).isoformat(), "reason": "main engine breakdown"},
    )
    assert p.status_code == 200, p.text
    assert p.json()["deducted_days"] == 2.0
    assert p.json()["reason"] == "main engine breakdown"

    # end_at 早于 start_at → 422
    bad = client.patch(
        f"/api/v1/off-hire/{ohid}", headers=auth_headers, json={"end_at": (T0 - timedelta(hours=1)).isoformat()}
    )
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "INVALID_OFFHIRE_WINDOW"

    # 关闭后不可删
    cl = client.post(f"/api/v1/off-hire/{ohid}/close", headers=auth_headers, json={})
    assert cl.status_code == 200
    assert cl.json()["status"] == "closed"
    d = client.delete(f"/api/v1/off-hire/{ohid}", headers=auth_headers)
    assert d.status_code == 409
    assert d.json()["detail"]["code"] == "OFFHIRE_CLOSED"

    # 列表仍可见且排除 status=deleted
    rows = client.get(f"/api/v1/voyages/{v['id']}/off-hire", headers=auth_headers).json()
    assert any(x["id"] == ohid for x in rows)


def test_off_hire_open_delete(client, auth_headers):
    v = _mk_voyage(client, auth_headers, "CRUD-OH-DEL")
    oh = client.post(
        f"/api/v1/voyages/{v['id']}/off-hire",
        headers=auth_headers,
        json={"start_at": T0.isoformat(), "reason": "adjust", "deduct_hire": False},
    ).json()
    assert client.delete(f"/api/v1/off-hire/{oh['id']}", headers=auth_headers).status_code == 200
    rows = client.get(f"/api/v1/voyages/{v['id']}/off-hire", headers=auth_headers).json()
    assert all(x["id"] != oh["id"] for x in rows)
    # 已删事件 404
    assert client.patch(f"/api/v1/off-hire/{oh['id']}", headers=auth_headers, json={"reason": "x"}).status_code == 404
