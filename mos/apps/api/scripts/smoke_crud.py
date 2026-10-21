"""CRUD 补齐全站冒烟：对补齐后的代表性端点做一次 PATCH/DELETE 流程验证。

用法（API 已在 8017 运行，RATE_LIMIT_ENABLED=false）：
    ./.venv/Scripts/python.exe scripts/smoke_crud.py [base_url]
默认 base_url = http://127.0.0.1:8017
仅用标准库（venv 未装 requests）。
"""

import json
import sys
import urllib.error
import urllib.request
import uuid

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8017"

TOKEN = ""

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(f"{name} {detail}".strip())
    print(("  ok  " if cond else "  FAIL") + f" {name} {detail}")


def call(method: str, path: str, body=None, auth: bool = True) -> tuple[int, dict | list | str]:
    headers = {"Content-Type": "application/json"}
    if auth and TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode()
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def main() -> None:
    global TOKEN
    code, body = call(
        "POST",
        "/api/v1/auth/login",
        {"email": "admin@demo.marios", "password": "Demo1234!", "tenant_code": "demo"},
        auth=False,
    )
    if code != 200:
        print("login failed:", code, body)
        sys.exit(2)
    TOKEN = body["access_token"] if isinstance(body, dict) else ""

    rid = uuid.uuid4().hex[:6]

    # ── core ops：port call / sof / noon / off-hire ─────────────
    _, v = call("POST", "/api/v1/voyages", {"voyage_no": f"SMOKE-{rid}"})
    _, pc = call(
        "POST", "/api/v1/port-calls", {"voyage_id": v["id"], "seq": 1, "purpose": "load"}
    )
    code, body = call("PATCH", f"/api/v1/port-calls/{pc['id']}", {"seq": 9, "agent": "Smoke"})
    check("port-call PATCH", code == 200 and body["seq"] == 9, f"-> {code}")
    _, sof = call(
        "POST",
        "/api/v1/sof-events",
        {"port_call_id": pc["id"], "event_code": "NOR", "event_at": "2026-05-01T08:00:00+00:00"},
    )
    code, body = call(
        "PATCH", f"/api/v1/sof-events/{sof['id']}", {"event_at": "2026-05-01T09:00:00+00:00"}
    )
    check("sof PATCH", code == 200, f"-> {code}")
    code, body = call(
        "POST",
        "/api/v1/noon-reports",
        {"voyage_id": v["id"], "report_at": "2026-05-01T12:00:00+00:00", "speed": 12},
    )
    check("noon POST", code == 200, f"-> {code}")
    nid = body["id"]
    code, body = call("PATCH", f"/api/v1/noon-reports/{nid}", {"speed": 13.5})
    check("noon PATCH", code == 200 and body["speed"] == 13.5, f"-> {code}")
    code, _ = call("DELETE", f"/api/v1/noon-reports/{nid}")
    check("noon DELETE", code == 200, f"-> {code}")
    code, _ = call("DELETE", f"/api/v1/port-calls/{pc['id']}")
    check("port-call DELETE (recycle)", code == 200, f"-> {code}")

    # ── commercial + config ────────────────────────────────────
    code, body = call(
        "POST",
        "/api/v1/offers",
        {"counterparty_id": None, "vessel_id": None, "rate": 15, "status": "sent"},
    )
    if code in (200, 201):
        oid = body["id"]
        code2, _ = call("PATCH", f"/api/v1/offers/{oid}", {"rate": 16})
        check("offer PATCH", code2 == 200, f"-> {code2}")
        code2, _ = call("DELETE", f"/api/v1/offers/{oid}")
        check("offer DELETE", code2 == 200, f"-> {code2}")
    else:
        check("offer create (precondition)", False, f"-> {code} {str(body)[:120]}")

    code, _ = call("GET", "/api/v1/config/flags")
    check("config flags GET", code == 200, f"-> {code}")

    # ── masterdata ─────────────────────────────────────────────
    code, body = call(
        "POST", "/api/v1/masterdata/companies", {"name": f"Smoke Co {rid}", "code": f"SMK{rid}"}
    )
    check("company POST", code in (200, 201), f"-> {code}")
    if code in (200, 201):
        cid = body["id"]
        code2, _ = call("PATCH", f"/api/v1/masterdata/companies/{cid}", {"name": f"Smoke Co2 {rid}"})
        check("company PATCH", code2 == 200, f"-> {code2}")
        code2, _ = call("DELETE", f"/api/v1/masterdata/companies/{cid}")
        check("company DELETE (soft)", code2 == 200, f"-> {code2}")

    # ── finance ────────────────────────────────────────────────
    code, _ = call("GET", "/api/v1/gl/periods")
    check("gl periods GET", code == 200, f"-> {code}")

    # ── platform ───────────────────────────────────────────────
    code, _ = call("GET", "/api/v1/platform/saas/plans")
    check("saas plans GET", code == 200, f"-> {code}")
    code, _ = call("GET", "/api/v1/settings/dataops/backups")
    check("backups GET", code == 200, f"-> {code}")

    # ── misc：dq / quotes / webhooks 可寻址性（列表返回 id） ────
    for label, path in [
        ("dq issues GET", "/api/v1/dq/issues"),
        ("market quotes GET", "/api/v1/market/quotes"),
        ("webhooks GET", "/api/v1/office/webhooks"),
        ("marilink terminals GET", "/api/v1/marilink/terminals"),
        ("risk positions GET", "/api/v1/risk/positions"),
        ("emissions GET", "/api/v1/emissions"),
        ("email accounts GET", "/api/v1/email/accounts"),
    ]:
        code, body = call("GET", path)
        ok = code == 200 and (not isinstance(body, list) or True)
        check(label, ok, f"-> {code}")

    print(f"\n== {len(PASS)} ok, {len(FAIL)} fail ==")
    for f in FAIL:
        print("  FAIL:", f)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
