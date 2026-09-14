"""P0 operations hardening: SOF standard event codes, event sequencing,
derived PortCall timestamps (nor_at/eosp_at/bl_date), port holidays, sof-summary."""

from datetime import datetime, timedelta, timezone

T0 = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)


def _mk_port_call(client, h, voyage_no="P0-OPS-1"):
    v = client.post("/api/v1/voyages", headers=h, json={"voyage_no": voyage_no})
    assert v.status_code == 200, v.text
    pc = client.post("/api/v1/port-calls", headers=h, json={"voyage_id": v.json()["id"], "seq": 1, "purpose": "load"})
    assert pc.status_code == 200, pc.text
    return v.json(), pc.json()


def _sof(client, h, pc_id, code, at):
    return client.post(
        "/api/v1/sof-events",
        headers=h,
        json={"port_call_id": pc_id, "event_code": code, "event_at": at.isoformat()},
    )


def _get_port_call(client, h, voyage_id):
    rows = client.get(f"/api/v1/port-calls?voyage_id={voyage_id}", headers=h).json()
    assert len(rows) == 1
    return rows[0]


def test_sof_invalid_event_code_422(client, auth_headers):
    _, pc = _mk_port_call(client, auth_headers)
    r = _sof(client, auth_headers, pc["id"], "BOGUS", T0)
    assert r.status_code == 422
    body = r.json()
    assert body["detail"]["code"] == "INVALID_SOF_EVENT_CODE"
    allowed = body["detail"]["allowed"]
    for code in ("NOR", "EOSP", "BL_DATE", "COMMENCED", "COMPLETED", "SAILED"):
        assert code in allowed


def test_sof_derived_columns_writeback(client, auth_headers):
    v, pc = _mk_port_call(client, auth_headers)
    assert _sof(client, auth_headers, pc["id"], "NOR", T0).status_code == 200
    assert _sof(client, auth_headers, pc["id"], "EOSP", T0 + timedelta(hours=1)).status_code == 200
    assert _sof(client, auth_headers, pc["id"], "BL_DATE", T0 + timedelta(hours=2)).status_code == 200
    assert _sof(client, auth_headers, pc["id"], "COMPLETED", T0 + timedelta(hours=30)).status_code == 200

    row = _get_port_call(client, auth_headers, v["id"])
    assert row["nor_at"] is not None and row["nor_at"].startswith("2026-03-01T08:00")
    assert row["eosp_at"] is not None and row["eosp_at"].startswith("2026-03-01T09:00")
    assert row["bl_date"] is not None and row["bl_date"].startswith("2026-03-01T10:00")
    assert row["ata"] is not None  # NOR 仍回写 ata（向后兼容）
    assert row["atd"] is not None  # COMPLETED 回写 atd


def test_sof_event_before_nor_rejected(client, auth_headers):
    _, pc = _mk_port_call(client, auth_headers)
    assert _sof(client, auth_headers, pc["id"], "NOR", T0).status_code == 200
    r = _sof(client, auth_headers, pc["id"], "COMMENCED", T0 - timedelta(hours=1))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "SOF_SEQUENCE_VIOLATION"
    # 不早于 NOR 的合法事件仍放行
    assert _sof(client, auth_headers, pc["id"], "COMMENCED", T0 + timedelta(hours=6)).status_code == 200


def test_sof_nor_must_be_earliest(client, auth_headers):
    _, pc = _mk_port_call(client, auth_headers)
    # 尚无 NOR 时先录其他事件不阻断（宽松录入）
    assert _sof(client, auth_headers, pc["id"], "COMMENCED", T0).status_code == 200
    # 但后补的 NOR 不得晚于已有事件
    r = _sof(client, auth_headers, pc["id"], "NOR", T0 + timedelta(hours=1))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "SOF_SEQUENCE_VIOLATION"
    # 与最早事件同时刻的 NOR 允许（"最早事件之一"）
    assert _sof(client, auth_headers, pc["id"], "NOR", T0).status_code == 200


def test_port_holidays_roundtrip(client, auth_headers):
    holidays = ["2026-01-01", "2026-05-01"]
    r = client.post(
        "/api/v1/masterdata/ports",
        headers=auth_headers,
        json={"name": "P0 Test Port", "unlocode": "ZZP0T", "holidays": holidays},
    )
    assert r.status_code == 200, r.text
    assert r.json()["holidays"] == holidays
    port_id = r.json()["id"]

    g = client.get(f"/api/v1/masterdata/ports/{port_id}", headers=auth_headers)
    assert g.status_code == 200
    assert g.json()["holidays"] == holidays

    new_holidays = ["2026-12-25"]
    p = client.patch(
        f"/api/v1/masterdata/ports/{port_id}",
        headers=auth_headers,
        json={"name": "P0 Test Port", "unlocode": "ZZP0T", "holidays": new_holidays},
    )
    assert p.status_code == 200, p.text
    assert p.json()["holidays"] == new_holidays


def test_sof_summary_durations(client, auth_headers):
    _, pc = _mk_port_call(client, auth_headers)
    assert _sof(client, auth_headers, pc["id"], "NOR", T0).status_code == 200
    assert _sof(client, auth_headers, pc["id"], "COMMENCED", T0 + timedelta(hours=6)).status_code == 200
    assert _sof(client, auth_headers, pc["id"], "COMPLETED", T0 + timedelta(hours=30)).status_code == 200

    r = client.get(f"/api/v1/port-calls/{pc['id']}/sof-summary", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["port_call_id"] == pc["id"]
    assert body["timezone"] == "UTC"
    assert [e["code"] for e in body["events"]] == ["NOR", "COMMENCED", "COMPLETED"]
    assert body["waiting_hours"] == 6.0  # NOR → COMMENCED
    assert body["working_hours"] == 24.0  # COMMENCED → COMPLETED


def test_sof_summary_empty_port_call(client, auth_headers):
    _, pc = _mk_port_call(client, auth_headers)
    r = client.get(f"/api/v1/port-calls/{pc['id']}/sof-summary", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["events"] == []
    assert body["working_hours"] is None
    assert body["waiting_hours"] is None
