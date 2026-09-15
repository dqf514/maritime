"""Workbench aggregation endpoint: structure, role KPIs, alerts, fault tolerance."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from tests.isolation_helpers import login

API = "/api/v1"
TECH = "tech@demo.voyageos"
OPS = "ops@demo.voyageos"


def _vessel_id(client, h) -> str:
    fleet = client.get(f"{API}/ship/fleet", headers=h)
    assert fleet.status_code == 200, fleet.text
    return fleet.json()["vessels"][0]["vessel_id"]


def test_summary_structure_for_admin(client, auth_headers):
    r = client.get(f"{API}/home/summary", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"tasks", "notifications", "approvals", "alerts", "schedule", "kpis", "exceptions"}
    assert set(body["tasks"].keys()) == {"open", "overdue", "due_today", "items"}
    assert set(body["notifications"].keys()) == {"unread", "items"}
    assert set(body["approvals"].keys()) == {"count", "items"}
    assert set(body["exceptions"].keys()) == {"critical", "warning"}
    assert isinstance(body["alerts"], list)
    assert isinstance(body["schedule"], list)
    assert len(body["kpis"]) >= 1
    assert len(body["kpis"]) <= 6
    keys = {k["key"] for k in body["kpis"]}
    # tenant_admin fallback set
    assert "open_tasks" in keys
    for k in body["kpis"]:
        assert set(k["label"].keys()) == {"en", "zh"}
        assert isinstance(k["value"], str)


def test_summary_technical_role_kpis(client):
    tech_h = login(client, TECH)
    r = client.get(f"{API}/home/summary", headers=tech_h)
    assert r.status_code == 200, r.text
    keys = {k["key"] for k in r.json()["kpis"]}
    assert {"certs_expiring_30d", "open_work_orders", "open_defects"} <= keys


def test_summary_requires_login(client):
    assert client.get(f"{API}/home/summary").status_code == 401


def test_expiring_cert_alert_and_notification_dedup(client, auth_headers):
    h = auth_headers
    vid = _vessel_id(client, h)
    r = client.post(
        f"{API}/ship/certificates",
        headers=h,
        json={
            "vessel_id": vid,
            "cert_code": "HOME-EXP",
            "cert_name": "Home Alert Cert",
            "expires_on": (date.today() + timedelta(days=10)).isoformat(),
        },
    )
    assert r.status_code == 200, r.text

    tech_h = login(client, TECH)
    s1 = client.get(f"{API}/home/summary", headers=tech_h)
    assert s1.status_code == 200, s1.text
    alerts = [a for a in s1.json()["alerts"] if a["kind"] == "ship_cert_expiring" and "Home Alert Cert" in a["title"]]
    assert alerts, "expiring ship cert should surface as alert"
    assert alerts[0]["severity"] == "warning"
    assert alerts[0]["href"] == "/ship"
    assert alerts[0]["due_in_days"] == 10

    # system notification generated for technical-role user
    notifs = client.get(f"{API}/notifications", headers=tech_h).json()
    hits = [n for n in notifs if "Home Alert Cert" in n["title"] and n["href"] == "/ship"]
    assert hits, "summary should lazily create an alert notification"

    # second call must not duplicate the notification (same day dedupe)
    s2 = client.get(f"{API}/home/summary", headers=tech_h)
    assert s2.status_code == 200, s2.text
    notifs2 = client.get(f"{API}/notifications", headers=tech_h).json()
    hits2 = [n for n in notifs2 if "Home Alert Cert" in n["title"] and n["href"] == "/ship"]
    assert len(hits2) == len(hits)


def test_summary_schedule_includes_upcoming_port_call(client, auth_headers):
    h = auth_headers
    voyages = client.get(f"{API}/voyages", headers=h)
    assert voyages.status_code == 200, voyages.text
    voyage_id = voyages.json()[0]["id"]
    eta = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    r = client.post(
        f"{API}/port-calls",
        headers=h,
        json={"voyage_id": voyage_id, "seq": 9, "purpose": "discharge", "eta": eta},
    )
    assert r.status_code == 200, r.text

    s = client.get(f"{API}/home/summary", headers=h)
    assert s.status_code == 200, s.text
    entries = [e for e in s.json()["schedule"] if e["kind"] == "port_call"]
    assert any("discharge" in (e["subtitle"] or "") for e in entries)


def test_summary_viewer_role_does_not_break(client, auth_headers):
    h = auth_headers
    r = client.post(
        f"{API}/admin/users",
        headers=h,
        json={
            "email": "viewer-home@demo.voyageos",
            "full_name": "Home Viewer",
            "password": "Demo1234!",
            "role_codes": ["viewer"],
        },
    )
    assert r.status_code == 200, r.text
    viewer_h = login(client, "viewer-home@demo.voyageos")
    s = client.get(f"{API}/home/summary", headers=viewer_h)
    assert s.status_code == 200, s.text
    body = s.json()
    assert set(body.keys()) == {"tasks", "notifications", "approvals", "alerts", "schedule", "kpis", "exceptions"}
    keys = {k["key"] for k in body["kpis"]}
    assert "open_tasks" in keys
