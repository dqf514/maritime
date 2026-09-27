"""D5 航速油耗保证索赔：好天气评估 + 失速/超耗金样。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.performance_engine import compute_performance


def test_performance_engine_gold():
    """金样手工推演：
    保证 13.0 kn（about 0.5）/ 25 mt/天（容差 5%），好天气风力 ≤ 4。
    D1: speed 12.0, wind 3 → shortfall = 13-0.5-12 = 0.5kn → 0.5/13*24 ≈ 0.92h
    D2: wind 7 → 不评估
    D3: speed 12.8 (≥12.5 通过), cons 27 > 25*1.05=26.25 → 超耗 2.0 mt
    索赔费率 8000/天，油价 600/mt：
    lost_days = round(0.92/24,2) = 0.04 → 0.04*8000 = 320
    amount = 320 + 2.0*600 = 1520
    """
    r = compute_performance(
        {
            "warranty_speed_kn": 13.0,
            "about_kn": 0.5,
            "warranty_consumption_mt_day": 25.0,
            "good_weather_max_wind_bf": 4,
            "claim_rate_per_day": 8000,
            "fuel_price_per_mt": 600,
            "days": [
                {"date": "2026-01-05", "speed_kn": 12.0, "cons_mt_day": 25.0, "wind_bf": 3, "sea_state": "slight"},
                {"date": "2026-01-06", "speed_kn": 11.0, "cons_mt_day": 30.0, "wind_bf": 7, "sea_state": "rough"},
                {"date": "2026-01-07", "speed_kn": 12.8, "cons_mt_day": 27.0, "wind_bf": 2, "sea_state": "smooth"},
            ],
        }
    )
    assert r["good_weather_days"] == 2
    assert r["total_days"] == 3
    assert r["lost_time_hours"] == 0.92
    assert r["lost_time_days"] == 0.04
    assert r["excess_consumption_mt"] == 2.0
    assert r["amount"] == 1520.0
    # 坏天气行标注且不计
    assert r["days"][1]["good_weather"] is False
    assert "lost_hours" not in r["days"][1]


def test_performance_within_tolerance_no_claim():
    r = compute_performance(
        {
            "warranty_speed_kn": 13.0,
            "about_kn": 0.5,
            "warranty_consumption_mt_day": 25.0,
            "days": [{"date": "2026-01-05", "speed_kn": 12.5, "cons_mt_day": 26.0, "wind_bf": 3, "sea_state": "slight"}],
        }
    )
    assert r["lost_time_days"] == 0.0
    assert r["excess_consumption_mt"] == 0.0
    assert r["amount"] == 0.0


def test_performance_endpoint_from_noon_reports(client, auth_headers, db_engine):
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from app.models_domain import NoonReport, Voyage

    h = auth_headers
    voyages = client.get("/api/v1/voyages", headers=h).json()
    voyages = voyages["items"] if isinstance(voyages, dict) else voyages
    vid = voyages[0]["id"]

    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as s:
        tid = s.get(Voyage, __import__("uuid").UUID(vid)).tenant_id
        base = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
        for i, (speed, rob, wind) in enumerate([(11.0, 500.0, 3), (11.2, 470.0, 3), (11.0, 440.0, 8)]):
            s.add(
                NoonReport(
                    tenant_id=tid,
                    voyage_id=__import__("uuid").UUID(vid),
                    report_at=base + timedelta(days=i),
                    speed=speed,
                    rob_fo=rob,
                    wind_bf=wind,
                    sea_state="slight" if wind < 5 else "rough",
                )
            )
        s.commit()

    r = client.get(
        f"/api/v1/voyages/{vid}/performance-claim?warranty_speed_kn=13&claim_rate_per_day=8000&fuel_price_per_mt=600&warranty_consumption_mt_day=25",
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["voyage_id"] == vid
    # 种子数据可能在同一航次有其他午报，只断言本次插入的三天
    days = [d for d in body["days"] if str(d["date"]).startswith("2026-01")]
    assert len(days) == 3
    # 第二天 ROB 500→470 = 30mt/天 超耗 5mt（25*1.05=26.25）；风力 3 好天气
    day2 = days[1]
    assert day2["cons_mt_day"] == 30.0
    assert day2.get("cons_excess_mt") == 5.0
    # 第三天风力 8 → 坏天气不评估
    assert days[2]["good_weather"] is False
