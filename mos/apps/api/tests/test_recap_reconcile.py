"""D3 recap 双向对账：邮件解析字段 vs 租约字段差异。"""

from __future__ import annotations


def _charter(client, h, **fields):
    parties = client.get("/api/v1/masterdata/counterparties", headers=h).json()
    parties = parties["items"] if isinstance(parties, dict) else parties
    return client.post(
        "/api/v1/charters",
        headers=h,
        json={"charter_type": "voyage", "counterparty_id": parties[0]["id"], **fields},
    ).json()


def test_recap_reconcile_match_and_diff(client, auth_headers):
    h = auth_headers
    charter = _charter(client, h, freight_rate=22.5, demurrage_rate=18000, cp_form="GENCON")

    # 一致 → match
    ok = client.post(
        "/api/v1/email-intelligence/recap-reconcile",
        headers=h,
        json={"charter_id": charter["id"], "recap": {"freight_rate": 22.5, "demurrage_rate": 18000.0, "cp_form": "gencon"}},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["match"] is True
    assert body["matched_fields"] == 3

    # 运价不一致 → 差异清单
    diff = client.post(
        "/api/v1/email-intelligence/recap-reconcile",
        headers=h,
        json={"charter_id": charter["id"], "recap": {"freight_rate": 25.0, "cp_form": "NYPE"}},
    ).json()
    assert diff["match"] is False
    fields = {d["field"]: d for d in diff["field_diffs"]}
    assert fields["freight_rate"]["recap_value"] == 25.0
    assert fields["freight_rate"]["charter_value"] == 22.5
    assert fields["freight_rate"]["delta"] == 2.5
    assert fields["cp_form"]["recap_value"] == "NYPE"


def test_recap_reconcile_requires_recap(client, auth_headers):
    h = auth_headers
    charter = _charter(client, h)
    r = client.post("/api/v1/email-intelligence/recap-reconcile", headers=h, json={"charter_id": charter["id"]})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "RECAP_REQUIRED"
