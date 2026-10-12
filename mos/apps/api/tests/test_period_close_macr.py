"""C3-P2 月度计提 MACR / 期间关账护栏。

覆盖：关账期间禁止 GL 过账（新建/过账/冲销/删除 → 409 PERIOD_CLOSED）、
关账/开账生命周期、MACR 过账后禁止删除（→ 409 MACR_LOCKED）、
冲销/重建仍然可用、租户隔离。
"""

from __future__ import annotations

import pytest

from tests.isolation_helpers import create_tenant

API = "/api/v1"

PERIOD = "2026-03"


def _mk_journal(
    client,
    h,
    *,
    period: str = PERIOD,
    journal_type: str = "non_voyage",
    entries: list | None = None,
    description: str = "C3-P2 test",
):
    payload = {
        "period": period,
        "journal_type": journal_type,
        "description": description,
        "entries": entries
        or [
            {"account_code": "1000", "debit": 100, "credit": 0, "reference": "t1"},
            {"account_code": "4000", "debit": 0, "credit": 100, "reference": "t1"},
        ],
    }
    r = client.post(f"{API}/gl/journals", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _mk_accrual(client, h, *, period_ym: str = PERIOD, amount: float = 500.0):
    r = client.post(
        f"{API}/finance/accruals",
        headers=h,
        json={
            "period_ym": period_ym,
            "line_type": "hire",
            "amount": amount,
            "currency": "USD",
            "notes": "C3-P2",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def _post_accrual(client, h, accrual_id: str):
    r = client.post(f"{API}/finance/accruals/{accrual_id}/post", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _close(client, h, period: str = PERIOD):
    return client.post(f"{API}/gl/periods/{period}/close", headers=h)


def _open(client, h, period: str = PERIOD):
    return client.post(f"{API}/gl/periods/{period}/open", headers=h)


def _detail_code(resp) -> str:
    body = resp.json()
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        return str(detail.get("code") or "")
    return str(body.get("code") or "")


# —— 1. 关账后禁止 GL 过账 ————————————————————————————————————


def test_period_close_blocks_gl_postings(client, auth_headers):
    h = auth_headers
    draft = _mk_journal(client, h)
    to_reverse = _mk_journal(client, h, description="to reverse")
    assert client.post(f"{API}/gl/journals/{to_reverse['id']}/post", headers=h).status_code == 200

    closed = _close(client, h)
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"

    # 新建分录
    create = client.post(
        f"{API}/gl/journals",
        headers=h,
        json={
            "period": PERIOD,
            "journal_type": "non_voyage",
            "entries": [
                {"account_code": "1000", "debit": 1, "credit": 0},
                {"account_code": "4000", "debit": 0, "credit": 1},
            ],
        },
    )
    assert create.status_code == 409
    assert _detail_code(create) == "PERIOD_CLOSED"

    # 过账既有草稿
    post = client.post(f"{API}/gl/journals/{draft['id']}/post", headers=h)
    assert post.status_code == 409
    assert _detail_code(post) == "PERIOD_CLOSED"

    # 删除
    delete = client.delete(f"{API}/gl/journals/{draft['id']}", headers=h)
    assert delete.status_code == 409
    assert _detail_code(delete) == "PERIOD_CLOSED"

    # 冲销（生成新分录）也落入该期间
    reverse = client.post(f"{API}/gl/journals/{to_reverse['id']}/reverse", headers=h)
    assert reverse.status_code == 409
    assert _detail_code(reverse) == "PERIOD_CLOSED"


def test_period_close_blocks_macr_mutations(client, auth_headers):
    h = auth_headers
    draft_acc = _mk_accrual(client, h)
    posted_acc = _mk_accrual(client, h, amount=50.0)
    _post_accrual(client, h, posted_acc["id"])

    assert _close(client, h).status_code == 200

    # 关账期间不得删除/冲销计提
    for resp in (
        client.delete(f"{API}/finance/accruals/{draft_acc['id']}", headers=h),
        client.post(f"{API}/finance/accruals/{posted_acc['id']}/reverse", headers=h),
        client.post(f"{API}/finance/accruals/{posted_acc['id']}/rebuild", headers=h, json={}),
    ):
        assert resp.status_code == 409
        assert _detail_code(resp) == "PERIOD_CLOSED"


# —— 2. 关账 / 开账生命周期 ————————————————————————————————————


def test_period_close_open_lifecycle(client, auth_headers):
    h = auth_headers

    # 开账一个从未关账的期间 → 404
    missing = _open(client, h, "2026-04")
    assert missing.status_code == 404
    assert _detail_code(missing) == "PERIOD_NOT_FOUND"

    # 关账前先留一条草稿，用于开账后过账
    draft = _mk_journal(client, h)

    first = _close(client, h)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "closed"
    assert first.json()["closed_at"]

    # 重复关账 → 状态机拒绝
    again = _close(client, h)
    assert again.status_code == 409
    assert _detail_code(again) == "INVALID_STATE"

    # 关账后不得新建
    create = client.post(
        f"{API}/gl/journals",
        headers=h,
        json={
            "period": PERIOD,
            "journal_type": "non_voyage",
            "entries": [
                {"account_code": "1000", "debit": 5, "credit": 0},
                {"account_code": "4000", "debit": 0, "credit": 5},
            ],
        },
    )
    assert create.status_code == 409
    assert _detail_code(create) == "PERIOD_CLOSED"

    # 关账后不得过账既有草稿
    post_closed = client.post(f"{API}/gl/journals/{draft['id']}/post", headers=h)
    assert post_closed.status_code == 409
    assert _detail_code(post_closed) == "PERIOD_CLOSED"

    # 开账 → 可过账
    opened = _open(client, h)
    assert opened.status_code == 200, opened.text
    assert opened.json()["status"] == "open"
    assert opened.json()["closed_at"] is None

    post = client.post(f"{API}/gl/journals/{draft['id']}/post", headers=h)
    assert post.status_code == 200, post.text
    assert post.json()["status"] == "posted"

    # 重复开账 → 状态机拒绝
    again_open = _open(client, h)
    assert again_open.status_code == 409
    assert _detail_code(again_open) == "INVALID_STATE"

    # 再次关账后仍可开账（闭环）
    assert _close(client, h).status_code == 200
    assert _open(client, h).status_code == 200


def test_period_close_rejects_bad_period(client, auth_headers):
    bad = _close(client, auth_headers, "2026-13")
    assert bad.status_code == 422
    assert _detail_code(bad) == "BAD_PERIOD"


# —— 3. MACR 过账后禁止删除 ————————————————————————————————————


def test_macr_delete_blocked_after_post(client, auth_headers):
    h = auth_headers

    # 草稿计提可删
    draft_acc = _mk_accrual(client, h, amount=11.0)
    ok = client.delete(f"{API}/finance/accruals/{draft_acc['id']}", headers=h)
    assert ok.status_code == 200, ok.text

    # 过账计提不可删
    posted_acc = _mk_accrual(client, h, amount=22.0)
    _post_accrual(client, h, posted_acc["id"])
    blocked = client.delete(f"{API}/finance/accruals/{posted_acc['id']}", headers=h)
    assert blocked.status_code == 409
    assert _detail_code(blocked) == "MACR_LOCKED"
    detail = blocked.json()["detail"]
    assert "reverse" in detail["message"] or "rebuild" in detail["message"]

    # 草稿分录可删
    draft_j = _mk_journal(client, h, description="draft del")
    assert client.delete(f"{API}/gl/journals/{draft_j['id']}", headers=h).status_code == 200

    # 已过账分录（月度计提）不可删
    accrual_j = _mk_journal(client, h, journal_type="accrual", description="MACR j")
    assert client.post(f"{API}/gl/journals/{accrual_j['id']}/post", headers=h).status_code == 200
    blocked_j = client.delete(f"{API}/gl/journals/{accrual_j['id']}", headers=h)
    assert blocked_j.status_code == 409
    assert _detail_code(blocked_j) == "MACR_LOCKED"

    # 已冲销的也保留（审计痕迹）
    rev = client.post(f"{API}/gl/journals/{accrual_j['id']}/reverse", headers=h)
    assert rev.status_code == 200, rev.text
    still = client.delete(f"{API}/gl/journals/{accrual_j['id']}", headers=h)
    assert still.status_code == 409
    assert _detail_code(still) == "MACR_LOCKED"


def test_macr_referenced_accrual_not_deletable(client, auth_headers):
    h = auth_headers
    acc = _mk_accrual(client, h, amount=33.0)
    # GL 分录引用该计提 id → 视为 referenced，草稿也不可删
    ref_j = _mk_journal(
        client,
        h,
        journal_type="accrual",
        entries=[
            {"account_code": "1000", "debit": 33, "credit": 0, "reference": f"accrual:{acc['id']}"},
            {"account_code": "4000", "debit": 0, "credit": 33, "reference": f"accrual:{acc['id']}"},
        ],
    )
    assert ref_j["status"] == "draft"
    blocked = client.delete(f"{API}/finance/accruals/{acc['id']}", headers=h)
    assert blocked.status_code == 409
    assert _detail_code(blocked) == "MACR_LOCKED"


# —— 4. 冲销 / 重建仍然可用 ————————————————————————————————————


def test_macr_reverse_rebuild_still_allowed(client, auth_headers):
    h = auth_headers

    # 过账 → 冲销 → 状态 reversed（原件保留）
    acc = _mk_accrual(client, h, amount=70.0)
    _post_accrual(client, h, acc["id"])
    rev = client.post(f"{API}/finance/accruals/{acc['id']}/reverse", headers=h)
    assert rev.status_code == 200, rev.text
    assert rev.json()["status"] == "reversed"

    # 重建：生成替代草稿，原件仍为 reversed
    reb = client.post(
        f"{API}/finance/accruals/{acc['id']}/rebuild",
        headers=h,
        json={"amount": 71.0},
    )
    assert reb.status_code == 200, reb.text
    assert reb.json()["original"]["status"] == "reversed"
    replacement = reb.json()["replacement"]
    assert replacement["status"] == "draft"
    assert replacement["amount"] == pytest.approx(71.0)

    # 替代草稿可再次过账（重建链路畅通）
    _post_accrual(client, h, replacement["id"])

    # 直接 rebuild 一条已过账计提：自动冲销 + 生成替代
    acc2 = _mk_accrual(client, h, amount=80.0)
    _post_accrual(client, h, acc2["id"])
    reb2 = client.post(f"{API}/finance/accruals/{acc2['id']}/rebuild", headers=h, json={})
    assert reb2.status_code == 200, reb2.text
    assert reb2.json()["original"]["status"] == "reversed"
    assert reb2.json()["replacement"]["status"] == "draft"

    # 分录冲销路径仍然可用（MACR journal）
    j = _mk_journal(client, h, journal_type="accrual")
    assert client.post(f"{API}/gl/journals/{j['id']}/post", headers=h).status_code == 200
    rj = client.post(f"{API}/gl/journals/{j['id']}/reverse", headers=h)
    assert rj.status_code == 200, rj.text
    assert rj.json()["original"]["status"] == "reversed"
    assert rj.json()["reversal"]["status"] == "posted"


def test_macr_reverse_rejects_draft(client, auth_headers):
    h = auth_headers
    draft = _mk_accrual(client, h, amount=9.0)
    resp = client.post(f"{API}/finance/accruals/{draft['id']}/reverse", headers=h)
    assert resp.status_code == 409
    assert _detail_code(resp) == "INVALID_STATE"


# —— 5. 租户隔离 ————————————————————————————————————————————————————


def test_macr_period_close_tenant_isolation(client, auth_headers):
    h = auth_headers
    _, hb = create_tenant(
        client, code="macriso", name="MACR Iso", admin_email="admin@macriso.example.com"
    )

    # A 先建好计提/分录，再关账
    acc_a = _mk_accrual(client, h, amount=12.0)
    _post_accrual(client, h, acc_a["id"])
    j_a = _mk_journal(client, h, journal_type="accrual")
    assert client.post(f"{API}/gl/journals/{j_a['id']}/post", headers=h).status_code == 200

    # 租户 A 关账自己的期间
    assert _close(client, h).status_code == 200

    # 租户 B 同名期间不受影响（各自记账）
    j_b = _mk_journal(client, hb)
    post_b = client.post(f"{API}/gl/journals/{j_b['id']}/post", headers=hb)
    assert post_b.status_code == 200, post_b.text

    # B 不能开 A 的期间（B 侧无此行 → 404）
    open_b = _open(client, hb)
    assert open_b.status_code == 404
    assert _detail_code(open_b) == "PERIOD_NOT_FOUND"

    # A 的计提/分录对 B 不可见 → 404
    for resp in (
        client.delete(f"{API}/finance/accruals/{acc_a['id']}", headers=hb),
        client.post(f"{API}/finance/accruals/{acc_a['id']}/reverse", headers=hb),
        client.post(f"{API}/finance/accruals/{acc_a['id']}/rebuild", headers=hb, json={}),
        client.delete(f"{API}/gl/journals/{j_a['id']}", headers=hb),
        client.post(f"{API}/gl/journals/{j_a['id']}/reverse", headers=hb),
    ):
        assert resp.status_code == 404, resp.text

    # A 自己删除已过账计提：期间已关 → PERIOD_CLOSED 优先；再开账后为 MACR_LOCKED
    blocked_closed = client.delete(f"{API}/finance/accruals/{acc_a['id']}", headers=h)
    assert blocked_closed.status_code == 409
    assert _detail_code(blocked_closed) == "PERIOD_CLOSED"

    assert _open(client, h).status_code == 200
    blocked = client.delete(f"{API}/finance/accruals/{acc_a['id']}", headers=h)
    assert blocked.status_code == 409
    assert _detail_code(blocked) == "MACR_LOCKED"
