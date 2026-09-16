"""Task system: CRUD, lifecycle, permissions, notifications, tenant isolation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.isolation_helpers import create_tenant, login

API = "/api/v1"
TECH = "tech@demo.marios"
MGMT = "mgmt@demo.marios"
FIN = "finance@demo.marios"


def _create(client, h, **overrides):
    payload = {"title": "Test task", **overrides}
    r = client.post(f"{API}/tasks", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _user_id(client, h, email: str) -> str:
    r = client.get(f"{API}/tasks/assignees", headers=h)
    assert r.status_code == 200, r.text
    return next(u["id"] for u in r.json() if u["email"] == email)


def test_create_and_my_tasks(client, auth_headers):
    h = auth_headers
    due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    task = _create(client, h, description="check certs", priority="high", due_at=due)
    assert task["status"] == "todo"
    assert task["priority"] == "high"
    assert task["source"] == "manual"
    assert task["creator"] is not None

    mine = client.get(f"{API}/tasks/my", headers=h)
    assert mine.status_code == 200, mine.text
    ids = [t["id"] for t in mine.json()]
    assert task["id"] in ids

    # done tasks hidden unless include_done
    client.post(f"{API}/tasks/{task['id']}/complete", headers=h)
    mine = client.get(f"{API}/tasks/my", headers=h).json()
    assert task["id"] not in [t["id"] for t in mine]
    mine_all = client.get(f"{API}/tasks/my", headers=h, params={"include_done": True}).json()
    assert task["id"] in [t["id"] for t in mine_all]


def test_assign_generates_notification(client, auth_headers):
    h = auth_headers
    tech_id = _user_id(client, h, TECH)
    task = _create(client, h, title="Review bunker stems", assignee_user_id=tech_id)
    assert task["assignee"]["email"] == TECH

    tech_h = login(client, TECH)
    notifs = client.get(f"{API}/notifications", headers=tech_h)
    assert notifs.status_code == 200, notifs.text
    hit = [n for n in notifs.json() if n["title"] == "Review bunker stems" and n["href"] == "/tasks"]
    assert hit, "assignee should receive a notification"
    assert hit[0]["read_at"] is None

    # task shows up in assignee's my-list
    mine = client.get(f"{API}/tasks/my", headers=tech_h).json()
    assert task["id"] in [t["id"] for t in mine]


def test_complete_and_reopen(client, auth_headers):
    h = auth_headers
    task = _create(client, h)
    done = client.post(f"{API}/tasks/{task['id']}/complete", headers=h)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done"
    assert done.json()["completed_at"] is not None

    reopened = client.post(f"{API}/tasks/{task['id']}/reopen", headers=h)
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "todo"
    assert reopened.json()["completed_at"] is None


def test_patch_permissions(client, auth_headers):
    h = auth_headers
    task = _create(client, h)

    # unrelated non-admin user cannot edit
    fin_h = login(client, FIN)
    r = client.patch(f"{API}/tasks/{task['id']}", headers=fin_h, json={"title": "hijacked"})
    assert r.status_code == 403, r.text

    # creator can edit
    r = client.patch(f"{API}/tasks/{task['id']}", headers=h, json={"title": "Updated title", "status": "in_progress"})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Updated title"
    assert r.json()["status"] == "in_progress"

    # invalid enum values rejected
    r = client.patch(f"{API}/tasks/{task['id']}", headers=h, json={"priority": "whenever"})
    assert r.status_code == 400, r.text


def test_manage_view_role_gate(client, auth_headers):
    h = auth_headers
    _create(client, h, title="Manage view probe")
    mgmt_h = login(client, MGMT)
    r = client.get(f"{API}/tasks", headers=mgmt_h)
    assert r.status_code == 200, r.text
    assert any(t["title"] == "Manage view probe" for t in r.json())

    fin_h = login(client, FIN)
    r = client.get(f"{API}/tasks", headers=fin_h)
    assert r.status_code == 403, r.text


def test_cross_tenant_isolation(client, auth_headers):
    h = auth_headers
    task = _create(client, h, title="Demo-only task")
    _, other_admin = create_tenant(client, code="othtask", name="Other Tasks Co", admin_email="other-tasks@example.com")

    assert client.patch(f"{API}/tasks/{task['id']}", headers=other_admin, json={"title": "x"}).status_code == 404
    assert client.post(f"{API}/tasks/{task['id']}/complete", headers=other_admin).status_code == 404
    mine = client.get(f"{API}/tasks/my", headers=other_admin).json()
    assert task["id"] not in [t["id"] for t in mine]


def test_invalid_assignee_rejected(client, auth_headers):
    _, other_admin = create_tenant(client, code="othasg", name="Other Asg Co", admin_email="other-asg@example.com")
    foreign_id = _user_id(client, other_admin, "other-asg@example.com")
    r = client.post(f"{API}/tasks", headers=auth_headers, json={"title": "bad", "assignee_user_id": foreign_id})
    assert r.status_code == 400, r.text


def test_assignees_endpoint_lists_active_users(client, auth_headers):
    r = client.get(f"{API}/tasks/assignees", headers=auth_headers)
    assert r.status_code == 200, r.text
    emails = [u["email"] for u in r.json()]
    assert "admin@demo.marios" in emails
    assert TECH in emails
    for u in r.json():
        assert set(u.keys()) == {"id", "email", "full_name"}


def test_notifications_read_all(client, auth_headers):
    h = auth_headers
    tech_id = _user_id(client, h, TECH)
    _create(client, h, title="Read-all probe", assignee_user_id=tech_id)
    tech_h = login(client, TECH)

    r = client.post(f"{API}/notifications/read-all", headers=tech_h)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    notifs = client.get(f"{API}/notifications", headers=tech_h).json()
    assert all(n["read_at"] is not None for n in notifs)
