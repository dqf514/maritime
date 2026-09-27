"""D13 交船/还船检验：on/off-hire survey 记录。"""

from __future__ import annotations


def _make_charter(client, h):
    parties = client.get("/api/v1/masterdata/counterparties", headers=h).json()
    party = parties["items"][0]["id"] if isinstance(parties, dict) else parties[0]["id"]
    return client.post(
        "/api/v1/charters",
        headers=h,
        json={"charter_type": "tct", "counterparty_id": party, "hire_per_day": 12000},
    ).json()


def test_hire_survey_crud(client, auth_headers):
    h = auth_headers
    charter = _make_charter(client, h)

    bad = client.post(
        f"/api/v1/charters/{charter['id']}/surveys",
        headers=h,
        json={"kind": "bogus", "surveyed_at": "2026-01-01T00:00:00Z"},
    )
    assert bad.status_code == 422

    on = client.post(
        f"/api/v1/charters/{charter['id']}/surveys",
        headers=h,
        json={"kind": "on_hire", "surveyed_at": "2026-01-01T00:00:00Z", "bunker_fo": 800.5, "bunker_do": 120.0},
    )
    assert on.status_code == 200, on.text
    off = client.post(
        f"/api/v1/charters/{charter['id']}/surveys",
        headers=h,
        json={"kind": "off_hire", "surveyed_at": "2026-02-01T00:00:00Z", "bunker_fo": 640.0, "notes": "last word"},
    )
    assert off.status_code == 200, off.text

    rows = client.get(f"/api/v1/charters/{charter['id']}/surveys", headers=h).json()["items"]
    assert [r["kind"] for r in rows] == ["on_hire", "off_hire"]
    assert rows[0]["bunker_fo"] == 800.5
    assert rows[1]["notes"] == "last word"
