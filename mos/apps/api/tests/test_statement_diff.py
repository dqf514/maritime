"""D12 结算单对账：我方 vs 对手方差异。"""

from __future__ import annotations


def test_statements_match():
    st = {
        "allowed_hours": 72,
        "used_hours": 84,
        "balance_hours": 12,
        "amount": 12000,
        "events": [{"start": "a", "end": "b", "counted_hours": 84}],
    }
    r = __import__("app.services.statement_diff", fromlist=["diff_statements"]).diff_statements(st, dict(st))
    assert r["match"] is True
    assert r["field_diffs"] == [] and r["event_diffs"] == []


def test_statements_field_and_event_diffs():
    mine = {
        "allowed_hours": 72,
        "used_hours": 84,
        "amount": 12000,
        "events": [
            {"start": "2026-01-01T00:00:00", "end": "2026-01-01T12:00:00", "counted_hours": 12},
            {"start": "2026-01-02T00:00:00", "end": "2026-01-02T12:00:00", "counted_hours": 12},
        ],
    }
    theirs = {
        "allowed_hours": 72,
        "used_hours": 86,  # 差 2 小时
        "amount": 14000,  # 差 2000
        "events": [
            {"start": "2026-01-01T00:00:00", "end": "2026-01-01T12:00:00", "counted_hours": 14},  # 事件差 2h
            # 对手方漏掉第二个事件
        ],
    }
    r = __import__("app.services.statement_diff", fromlist=["diff_statements"]).diff_statements(mine, theirs)
    assert r["match"] is False
    fields = {d["field"]: d for d in r["field_diffs"]}
    assert fields["used_hours"]["delta"] == 2.0
    assert fields["amount"]["delta"] == 2000.0
    issues = {(d["start"], d["issue"]) for d in r["event_diffs"]}
    assert ("2026-01-01T00:00:00", "hours") in issues
    assert ("2026-01-02T00:00:00", "only_mine") in issues


def test_compare_endpoint(client, auth_headers):
    r = client.post(
        "/api/v1/laytimes/compare",
        headers=auth_headers,
        json={
            "my": {"allowed_hours": 24, "used_hours": 30, "amount": 6000, "events": []},
            "their": {"allowed_hours": 24, "used_hours": 36, "amount": 12000, "events": []},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["match"] is False
    assert {d["field"] for d in body["field_diffs"]} == {"used_hours", "amount"}

    bad = client.post("/api/v1/laytimes/compare", headers=auth_headers, json={"their": {}})
    assert bad.status_code == 422
