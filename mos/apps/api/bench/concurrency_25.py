"""25 用户并发基准 — 性能 / 冲突 / 并行矛盾操作的全方位压测.

场景设计（对应大型 ERP 的并发验收维度）:

  S1 并发登录            25 用户同时登录 → 登录延迟分布
  S2 混合读取            25 用户 × 2 轮 × 6 个核心读接口 → p50/p95/p99、吞吐
  S3 同资源状态机竞争    25 线程同时推进同一租约 → 恰好 1 个成功、其余 409
  S4 并发重复付款        25 线程同时全额支付同一发票 → 资金零多收
  S5 COA 重复分摊        25 线程同时分摊同一 lifting → 恰好 1 次分摊
  S6 并发删除同一挂靠港   25 线程同时删除 → 恰好 1 个 200、其余 404/409
  S7 并行独立写链路      25 用户各自 估算→计算→克隆 → 写吞吐与锁竞争

用法:
  cd apps/api
  PERF_BASE=http://localhost:8017 ./.venv/Scripts/python.exe bench/concurrency_25.py

退出码: 0 = 全部正确性断言通过; 1 = 有断言失败（性能数字仅记录、不作为门槛）。
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

BASE = os.environ.get("PERF_BASE", "http://localhost:8017").rstrip("/")
API = f"{BASE}/api/v1"
USERS = int(os.environ.get("PERF_USERS", "25"))
OUT = os.environ.get(
    "PERF_OUT", r"D:\AI\Maritime\_guide_work\perf\results_25.json"
)
LOGIN = {"email": "admin@demo.marios", "password": "Demo1234!", "tenant_code": "demo"}
RUN_TAG = str(int(time.time()))  # 跨轮次运行的业务单号防撞（voyage_no 唯一键）

RESULTS: dict = {
    "meta": {
        "base": BASE,
        "users": USERS,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    },
    "scenarios": [],
}
FAILURES: list[str] = []


def pct(vals: list[float], p: float) -> float:
    """最近秩百分位。"""
    if not vals:
        return 0.0
    s = sorted(vals)
    k = min(len(s) - 1, max(0, int(round(p / 100 * len(s) + 0.5)) - 1))
    return round(s[k], 1)


def stats(lat: list[float]) -> dict:
    if not lat:
        return {}
    return {
        "n": len(lat),
        "mean": round(statistics.fmean(lat), 1),
        "p50": pct(lat, 50),
        "p95": pct(lat, 95),
        "p99": pct(lat, 99),
        "max": round(max(lat), 1),
    }


def record(name, *, wall_s, lat=None, per_ep=None, checks=None, notes="", errors=None):
    sc = {
        "name": name,
        "wall_s": round(wall_s, 2),
        "rps": round((lat and len(lat) or 0) / wall_s, 1) if wall_s > 0 else 0,
        "latency_ms": stats(lat or []),
        "per_endpoint": {k: stats(v) for k, v in (per_ep or {}).items()},
        "error_codes": errors or {},
        "checks": checks or [],
        "notes": notes,
    }
    RESULTS["scenarios"].append(sc)
    bad = [c for c in sc["checks"] if not c["pass"]]
    flag = "OK " if not bad else "FAIL"
    print(
        f"[{flag}] {name}: wall={sc['wall_s']}s rps={sc['rps']} "
        f"p50={sc['latency_ms'].get('p50')}ms p95={sc['latency_ms'].get('p95')}ms "
        f"p99={sc['latency_ms'].get('p99')}ms errors={sc['error_codes']}"
    )
    for c in bad:
        FAILURES.append(f"{name} :: {c['name']} — {c['detail']}")
        print(f"      x {c['name']}: {c['detail']}")


def check(name, ok, detail=""):
    return {"name": name, "pass": bool(ok), "detail": detail}


def new_client(timeout=30.0) -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=timeout, trust_env=False)


def do_login(c: httpx.Client) -> str:
    r = c.post(f"{API}/auth/login", json=LOGIN)
    r.raise_for_status()
    return r.json()["access_token"]


def auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def barrier(n: int) -> threading.Barrier:
    return threading.Barrier(n)


# ---------------------------------------------------------------- S1 登录并发

def s1_login_race():
    lat, codes = [], {}
    b = barrier(USERS)

    def one():
        with new_client() as c:
            b.wait(timeout=20)
            t0 = time.perf_counter()
            r = c.post(f"{API}/auth/login", json=LOGIN)
            lat.append((time.perf_counter() - t0) * 1000)
            codes[str(r.status_code)] = codes.get(str(r.status_code), 0) + 1

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=USERS) as ex:
        list(ex.map(lambda _: one(), range(USERS)))
    wall = time.perf_counter() - t0
    record(
        f"S1 并发登录（{USERS} 用户同时登录）",
        wall_s=wall,
        lat=lat,
        errors=codes,
        checks=[check("全部登录200", codes.get("200") == USERS, f"codes={codes}")],
    )


# ---------------------------------------------------------------- S2 混合读取

READ_ENDPOINTS = [
    "/shell/bootstrap",
    "/voyages",
    "/invoices",
    "/finance/aging",
    "/masterdata/vessels",
    "/exceptions/scan",
]


def s2_mixed_reads():
    tokens = []
    with new_client() as c:
        tok = do_login(c)
    per_ep: dict[str, list[float]] = {p: [] for p in READ_ENDPOINTS}
    lat, codes = [], {}
    b = barrier(USERS)

    def one():
        with new_client() as c:
            h = auth(tok)
            b.wait(timeout=30)
            for _ in range(2):
                for path in READ_ENDPOINTS:
                    t0 = time.perf_counter()
                    r = c.get(f"{API}{path}", headers=h)
                    dt = (time.perf_counter() - t0) * 1000
                    lat.append(dt)
                    per_ep[path].append(dt)
                    codes[str(r.status_code)] = codes.get(str(r.status_code), 0) + 1

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=USERS) as ex:
        list(ex.map(lambda _: one(), range(USERS)))
    wall = time.perf_counter() - t0
    non200 = {k: v for k, v in codes.items() if k != "200"}
    record(
        f"S2 混合读取（{USERS} 用户 × 2 轮 × {len(READ_ENDPOINTS)} 接口）",
        wall_s=wall,
        lat=lat,
        per_ep=per_ep,
        errors=codes,
        checks=[
            check("读接口全部200", not non200, f"non-200={non200}"),
        ],
        notes="单线程串行发请求，线程间并发；吞吐=总请求/墙钟。",
    )


def _setup_charter(c: httpx.Client, h: dict) -> str:
    vessels = c.get(f"{API}/masterdata/vessels", headers=h).json()
    vessels = vessels["items"] if isinstance(vessels, dict) else vessels
    r = c.post(
        f"{API}/charters",
        headers=h,
        json={"charter_type": "voyage", "vessel_id": vessels[0]["id"]},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------------------------------------------------------------- S3 状态机竞争

def s3_transition_race():
    with new_client() as c:
        tok = do_login(c)
        h = auth(tok)
        cid = _setup_charter(c, h)

    codes_t1, codes_t2 = {}, {}
    lat = []
    b = barrier(USERS)

    def go(target: str, acc: dict):
        with new_client() as c:
            h = auth(tok)
            b.wait(timeout=20)
            t0 = time.perf_counter()
            r = c.post(f"{API}/charters/{cid}/transition", headers=h, json={"target": target})
            lat.append((time.perf_counter() - t0) * 1000)
            acc[str(r.status_code)] = acc.get(str(r.status_code), 0) + 1

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=USERS) as ex:
        futs = [ex.submit(go, "pending_approval", codes_t1) for _ in range(USERS)]
        [f.result() for f in futs]
    with ThreadPoolExecutor(max_workers=USERS) as ex:
        futs = [ex.submit(go, "active", codes_t2) for _ in range(USERS)]
        [f.result() for f in futs]
    wall = time.perf_counter() - t0

    with new_client() as c:
        h = auth(do_login(c))
        st = c.get(f"{API}/charters/{cid}", headers=h).json().get("status")

    record(
        f"S3 同一租约状态机竞争（两阶段 × {USERS} 线程）",
        wall_s=wall,
        lat=lat,
        errors={"pending:" + str(k): v for k, v in codes_t1.items()}
        | {"active:" + str(k): v for k, v in codes_t2.items()},
        checks=[
            check("pending 阶段恰 1 个200", codes_t1.get("200") == 1, f"codes={codes_t1}"),
            check("pending 其余全409", sum(v for k, v in codes_t1.items() if k == "409") == USERS - 1, f"codes={codes_t1}"),
            check("active 阶段恰 1 个200", codes_t2.get("200") == 1, f"codes={codes_t2}"),
            check("active 其余全409", sum(v for k, v in codes_t2.items() if k == "409") == USERS - 1, f"codes={codes_t2}"),
            check("最终状态=active", st == "active", f"status={st}"),
        ],
    )


# ---------------------------------------------------------------- S4 重复付款

def s4_payment_race():
    with new_client() as c:
        tok = do_login(c)
        h = auth(tok)
        party = c.get(f"{API}/masterdata/counterparties", headers=h).json()
        party = party["items"] if isinstance(party, dict) else party
        r = c.post(
            f"{API}/invoices",
            headers=h,
            json={"invoice_type": "freight", "amount": 7777, "counterparty_id": party[0]["id"]},
        )
        assert r.status_code == 200, r.text
        iid = r.json()["id"]
        c.post(f"{API}/invoices/{iid}/transition?target=pending_approval", headers=h)
        c.post(f"{API}/invoices/{iid}/transition?target=issued", headers=h)

    codes, lat = {}, []
    b = barrier(USERS)

    def one():
        with new_client() as c:
            h = auth(tok)
            b.wait(timeout=20)
            t0 = time.perf_counter()
            r = c.post(
                f"{API}/invoices/{iid}/payments?amount=7777&reference=PERF-RACE",
                headers=h,
            )
            lat.append((time.perf_counter() - t0) * 1000)
            codes[str(r.status_code)] = codes.get(str(r.status_code), 0) + 1

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=USERS) as ex:
        list(ex.map(lambda _: one(), range(USERS)))
    wall = time.perf_counter() - t0

    with new_client() as c:
        h = auth(do_login(c))
        pays = c.get(f"{API}/invoices/{iid}/payments", headers=h).json()
        pays = pays["items"] if isinstance(pays, dict) else pays
        paid_sum = round(sum(float(p.get("amount") or 0) for p in pays), 2)

    record(
        f"S4 并发重复付款（{USERS} 线程同时全额支付同一发票）",
        wall_s=wall,
        lat=lat,
        errors=codes,
        checks=[
            check("恰 1 笔支付成功", codes.get("200") == 1, f"codes={codes}"),
            check("其余被拒(4xx)", sum(v for k, v in codes.items() if k.startswith("4")) == USERS - 1, f"codes={codes}"),
            check("收款合计 = 发票金额(零多收)", paid_sum == 7777.0, f"paid_sum={paid_sum}"),
            check("支付记录恰 1 条", len(pays) == 1, f"rows={len(pays)}"),
        ],
        notes="资金安全：并发双花必须被余额/状态校验挡住。",
    )


# ---------------------------------------------------------------- S5 COA 分摊

def s5_coa_allocate_race():
    with new_client() as c:
        tok = do_login(c)
        h = auth(tok)
        vessels = c.get(f"{API}/masterdata/vessels", headers=h).json()
        vessels = vessels["items"] if isinstance(vessels, dict) else vessels
        vid = vessels[0]["id"]

        ch = c.post(f"{API}/charters", headers=h, json={"charter_type": "coa", "cargo_qty": 10000.0})
        assert ch.status_code == 200, ch.text
        coa_cid = ch.json()["id"]
        coa = c.post(
            f"{API}/coa/contracts",
            headers=h,
            json={
                "charter_id": coa_cid,
                "total_qty": 10000.0,
                "qty_unit": "mt",
                "period_from": "2026-01-01",
                "period_to": "2026-12-31",
                "rate_basis": "per_mt",
                "rate": 24.0,
            },
        )
        assert coa.status_code == 201, coa.text
        coa_id = coa.json()["id"]
        it = c.post(f"{API}/coa/contracts/{coa_id}/itineraries", headers=h, json={"seq": 1, "qty": 10000.0})
        assert it.status_code == 201, it.text

        # 关联航次
        ch2 = c.post(f"{API}/charters", headers=h, json={"charter_type": "voyage", "vessel_id": vid})
        voy = c.post(
            f"{API}/voyages",
            headers=h,
            json={"voyage_no": f"PERF-COA-{RUN_TAG}", "vessel_id": vid, "charter_id": ch2.json()["id"]},
        )
        assert voy.status_code == 200, voy.text
        voyage_id = voy.json()["id"]

        lift = c.post(
            f"{API}/charters/{coa_cid}/liftings",
            headers=h,
            params={"period_label": "2026-Q1", "planned_qty": 10000.0},
        )
        assert lift.status_code in (200, 201), lift.text
        lid = lift.json()["id"]
        c.post(
            f"{API}/coa-liftings/{lid}/nominate",
            headers=h,
            json={"laycan_from": "2026-05-01T00:00:00Z", "laycan_to": "2026-05-15T00:00:00Z"},
        )
        c.post(f"{API}/coa-liftings/{lid}/fix", headers=h, json={"voyage_id": voyage_id})
        c.post(f"{API}/coa-liftings/{lid}/complete", headers=h, json={"actual_qty": 10000.0})

    codes, lat = {}, []
    b = barrier(USERS)

    def one():
        with new_client() as c:
            h = auth(tok)
            b.wait(timeout=20)
            t0 = time.perf_counter()
            r = c.post(
                f"{API}/coa/{coa_id}/allocate",
                headers=h,
                json={"lifting_id": lid, "itinerary_seq": 1},
            )
            lat.append((time.perf_counter() - t0) * 1000)
            codes[str(r.status_code)] = codes.get(str(r.status_code), 0) + 1

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=USERS) as ex:
        list(ex.map(lambda _: one(), range(USERS)))
    wall = time.perf_counter() - t0

    with new_client() as c:
        h = auth(do_login(c))
        alloc = c.get(f"{API}/coa/{coa_id}/allocation", headers=h).json()

    record(
        f"S5 COA 并发分摊（{USERS} 线程分摊同一 lifting→行程1）",
        wall_s=wall,
        lat=lat,
        errors=codes,
        checks=[
            check("恰 1 次分摊成功", codes.get("200") == 1, f"codes={codes}"),
            check("其余被拒(422/409)", sum(v for k, v in codes.items() if k in ("422", "409")) == USERS - 1, f"codes={codes}"),
            check("分摊守恒 remaining=0", float(alloc.get("remaining_qty", -1)) == 0, f"alloc={alloc}"),
        ],
    )


# ---------------------------------------------------------------- S6 并发删除

def s6_delete_race():
    with new_client() as c:
        tok = do_login(c)
        h = auth(tok)
        vessels = c.get(f"{API}/masterdata/vessels", headers=h).json()
        vessels = vessels["items"] if isinstance(vessels, dict) else vessels
        vid = vessels[0]["id"]
        ch = c.post(f"{API}/charters", headers=h, json={"charter_type": "voyage", "vessel_id": vid})
        voy = c.post(
            f"{API}/voyages",
            headers=h,
            json={"voyage_no": f"PERF-DEL-{RUN_TAG}", "vessel_id": vid, "charter_id": ch.json()["id"]},
        )
        ports = c.get(f"{API}/masterdata/ports", headers=h).json()
        ports = ports["items"] if isinstance(ports, dict) else ports
        pc = c.post(
            f"{API}/port-calls",
            headers=h,
            json={"voyage_id": voy.json()["id"], "port_id": ports[0]["id"], "seq": 1, "purpose": "load"},
        )
        assert pc.status_code == 200, pc.text
        pc_id = pc.json()["id"]

    codes, lat = {}, []
    b = barrier(USERS)

    def one():
        with new_client() as c:
            h = auth(tok)
            b.wait(timeout=20)
            t0 = time.perf_counter()
            r = c.delete(f"{API}/port-calls/{pc_id}", headers=h)
            lat.append((time.perf_counter() - t0) * 1000)
            codes[str(r.status_code)] = codes.get(str(r.status_code), 0) + 1

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=USERS) as ex:
        list(ex.map(lambda _: one(), range(USERS)))
    wall = time.perf_counter() - t0

    record(
        f"S6 并发删除同一挂靠港（{USERS} 线程）",
        wall_s=wall,
        lat=lat,
        errors=codes,
        checks=[
            check("恰 1 个200", codes.get("200") == 1, f"codes={codes}"),
            check("其余404/409", sum(v for k, v in codes.items() if k in ("404", "409")) == USERS - 1, f"codes={codes}"),
        ],
        notes="软删除 + 回收站语义：重复删除必须幂等受控。",
    )


# ---------------------------------------------------------------- S7 并行写链路

def s7_parallel_writes():
    with new_client() as c:
        tok = do_login(c)
        h = auth(tok)
        vessels = c.get(f"{API}/masterdata/vessels", headers=h).json()
        vessels = vessels["items"] if isinstance(vessels, dict) else vessels
        parties = c.get(f"{API}/masterdata/counterparties", headers=h).json()
        parties = parties["items"] if isinstance(parties, dict) else parties
        vid, pid = vessels[0]["id"], parties[0]["id"]

    lat_create, lat_calc = [], []
    codes = {"create": {}, "calc": {}}
    ok_chains = [0]
    lock = threading.Lock()
    b = barrier(USERS)

    def one(i: int):
        with new_client() as c:
            h = auth(tok)
            b.wait(timeout=30)
            r = c.post(
                f"{API}/estimates",
                headers=h,
                json={
                    "title": f"PERF-PAR-{i:02d}",
                    "vessel_id": vid,
                    "counterparty_id": pid,
                    "inputs": {"cargo_qty": 50000, "freight_rate": 12, "sea_days": 10, "port_days": 3},
                },
            )
            dt1 = r.elapsed.total_seconds() * 1000
            lat_create.append(dt1)
            with lock:
                codes["create"][str(r.status_code)] = codes["create"].get(str(r.status_code), 0) + 1
            if r.status_code != 200:
                return
            eid = r.json()["id"]
            r2 = c.post(f"{API}/estimates/{eid}/calculate", headers=h)
            lat_calc.append(r2.elapsed.total_seconds() * 1000)
            with lock:
                codes["calc"][str(r2.status_code)] = codes["calc"].get(str(r2.status_code), 0) + 1
            if r2.status_code == 200:
                with lock:
                    ok_chains[0] += 1

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=USERS) as ex:
        list(ex.map(one, range(USERS)))
    wall = time.perf_counter() - t0

    non200_create = {k: v for k, v in codes["create"].items() if k != "200"}
    non200_calc = {k: v for k, v in codes["calc"].items() if k != "200"}
    record(
        f"S7 并行独立写链路（{USERS} 用户各自 估算创建→TCE计算）",
        wall_s=wall,
        lat=lat_create + lat_calc,
        per_ep={"POST /estimates": lat_create, "POST estimates/{id}/calculate": lat_calc},
        errors={"create:" + str(k): v for k, v in codes["create"].items()}
        | {"calc:" + str(k): v for k, v in codes["calc"].items()},
        checks=[
            check(f"{USERS} 条链路全部成功", ok_chains[0] == USERS, f"ok={ok_chains[0]}/{USERS}"),
            check("创建无错误码", not non200_create, f"{non200_create}"),
            check("计算无错误码", not non200_calc, f"{non200_calc}"),
        ],
        notes="并行写考验 SQLite 写串行化与事务持锁；错误率与延迟即写竞争的直接体现。",
    )


# ---------------------------------------------------------------- main

def main():
    print(f"== 25-user concurrency bench @ {BASE} (users={USERS}) ==")
    with new_client() as c:
        tok = do_login(c)  # 预检
    print("login preflight ok")

    t_all = time.perf_counter()
    s1_login_race()
    s2_mixed_reads()
    s3_transition_race()
    s4_payment_race()
    s5_coa_allocate_race()
    s6_delete_race()
    s7_parallel_writes()
    RESULTS["meta"]["total_wall_s"] = round(time.perf_counter() - t_all, 1)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=1)
    print(f"\nresults → {OUT}")
    if FAILURES:
        print(f"== {len(FAILURES)} CORRECTNESS FAILURE(S) ==")
        for x in FAILURES:
            print(" ✗", x)
        sys.exit(1)
    print("== ALL CORRECTNESS CHECKS PASSED ==")


if __name__ == "__main__":
    main()
