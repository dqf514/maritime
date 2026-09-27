"""D6 NOR 递交条件（条款驱动，向后兼容）+ 条款参数直通 from-sof。

规则（routers/laytimes.laytime_from_sof）：
- 缺省 / WIBON / WCCON / WIPON：NOR 递交即起算，等泊时间计入（历史行为）；
- BERTH_ONLY：靠泊前方为有效 NOR，靠泊前等泊时间不计；
- count_waiting 显式覆盖；
- 租约勾选条款的计算参数（once_on_demurrage 等）直通 laytime 输入。
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import sessionmaker

from app.models_domain import Charter


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _first_vessel_id(client, h):
    return client.get("/api/v1/masterdata/vessels", headers=h).json()[0]["id"]


def _setup_port_call(client, h, db_session, voyage_no, clause_codes=None):
    cp = client.post(
        "/api/v1/charters",
        headers=h,
        json={
            "charter_type": "voyage",
            "vessel_id": _first_vessel_id(client, h),
            "clauses": {"codes": clause_codes or []},
        },
    )
    assert cp.status_code == 200, cp.text
    charter = db_session.get(Charter, UUID(cp.json()["id"]))
    charter.cargo_qty = Decimal("30000")
    charter.load_rate_pd = Decimal("10000")
    charter.demurrage_rate = Decimal("24000")
    charter.laytime_terms = "SHINC"
    db_session.commit()

    voy = client.post("/api/v1/voyages", headers=h, json={"voyage_no": voyage_no, "charter_id": cp.json()["id"]})
    assert voy.status_code == 200, voy.text
    pc = client.post("/api/v1/port-calls", headers=h, json={"voyage_id": voy.json()["id"], "seq": 1, "purpose": "load"})
    assert pc.status_code == 200, pc.text
    pc_id = pc.json()["id"]
    for code, at in (
        ("NOR", "2026-09-01T00:00:00+00:00"),
        ("COMMENCED", "2026-09-01T06:00:00+00:00"),
        ("COMPLETED", "2026-09-04T06:00:00+00:00"),
    ):
        r = client.post("/api/v1/sof-events", headers=h, json={"port_call_id": pc_id, "event_code": code, "event_at": at})
        assert r.status_code == 200, r.text
    return pc_id


def test_default_waiting_counts_backward_compat(client, auth_headers, db_session):
    """缺省（无 NOR 条款）：等泊 6h + 工作 72h = 78h——历史行为保持。"""
    h = auth_headers
    pc_id = _setup_port_call(client, h, db_session, "D6-1")
    body = client.post("/api/v1/laytimes/from-sof", headers=h, json={"port_call_id": pc_id}).json()
    assert body["results"]["used_hours"] == 78.0
    assert body["inputs"]["events"][0]["excluded"] is False


def test_berth_only_clause_excludes_waiting(client, auth_headers, db_session):
    """BERTH_ONLY 条款：靠泊前等泊不计 → used=72h，无滞期。"""
    h = auth_headers
    pc_id = _setup_port_call(client, h, db_session, "D6-2", clause_codes=["NOR_BERTH_ONLY"])
    body = client.post("/api/v1/laytimes/from-sof", headers=h, json={"port_call_id": pc_id}).json()
    assert body["results"]["used_hours"] == 72.0
    assert body["inputs"]["events"][0]["excluded"] is True
    assert body["results"]["result_type"] == "on_time"


def test_wibon_clause_counts_waiting(client, auth_headers, db_session):
    """WIBON 条款显式声明：等泊计入。"""
    h = auth_headers
    pc_id = _setup_port_call(client, h, db_session, "D6-3", clause_codes=["NOR_WIBON"])
    body = client.post("/api/v1/laytimes/from-sof", headers=h, json={"port_call_id": pc_id}).json()
    assert body["results"]["used_hours"] == 78.0


def test_count_waiting_overrides_terms(client, auth_headers, db_session):
    """count_waiting 显式覆盖条款（BERTH_ONLY 条款 + count_waiting=True → 计入）。"""
    h = auth_headers
    pc_id = _setup_port_call(client, h, db_session, "D6-4", clause_codes=["NOR_BERTH_ONLY"])
    body = client.post(
        "/api/v1/laytimes/from-sof",
        headers=h,
        json={"port_call_id": pc_id, "count_waiting": True},
    ).json()
    assert body["results"]["used_hours"] == 78.0
    # 反向：body.nor_terms 覆盖条款 → BERTH_ONLY
    pc_id2 = _setup_port_call(client, h, db_session, "D6-4b", clause_codes=["NOR_WIBON"])
    body2 = client.post(
        "/api/v1/laytimes/from-sof",
        headers=h,
        json={"port_call_id": pc_id2, "nor_terms": "BERTH_ONLY"},
    ).json()
    assert body2["results"]["used_hours"] == 72.0


def test_clause_params_passthrough_once_on_demurrage(client, auth_headers, db_session):
    """条款计算参数直通：DEM_ALWAYS → laytime 输入含 once_on_demurrage。"""
    h = auth_headers
    pc_id = _setup_port_call(client, h, db_session, "D6-5", clause_codes=["DEM_ALWAYS", "NOR_BERTH_ONLY"])
    body = client.post("/api/v1/laytimes/from-sof", headers=h, json={"port_call_id": pc_id}).json()
    assert body["inputs"]["once_on_demurrage"] is True
