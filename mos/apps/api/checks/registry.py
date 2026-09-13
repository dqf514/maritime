"""SelfCheck registry — platform + calc gold suites."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.estimate_engine import compute_estimate
from app.services.laytime_engine import compute_laytime


@dataclass
class CheckResult:
    check_id: str
    severity: str
    status: str  # pass | warn | fail
    message: str
    details: dict | None = None


CheckFn = Callable[[Session], CheckResult]

REGISTRY: list[tuple[str, str, CheckFn]] = []


def check(check_id: str, severity: str = "blocker"):
    def deco(fn: CheckFn):
        REGISTRY.append((check_id, severity, fn))
        return fn

    return deco


def _fixtures_root() -> Path:
    # mos/apps/api/checks/registry.py -> mos/fixtures
    return Path(__file__).resolve().parents[3] / "fixtures"


@check("infra.db_ping", "blocker")
def check_db(db: Session) -> CheckResult:
    db.execute(text("SELECT 1"))
    return CheckResult("infra.db_ping", "blocker", "pass", "Database reachable")


@check("sec.dev_unlock_off", "blocker")
def check_dev_unlock(_db: Session) -> CheckResult:
    settings = get_settings()
    env = os.getenv("APP_ENV", "dev")
    if env == "prod" and settings.license_dev_unlock == "all":
        return CheckResult(
            "sec.dev_unlock_off",
            "blocker",
            "fail",
            "LICENSE_DEV_UNLOCK must be off in production",
        )
    return CheckResult("sec.dev_unlock_off", "blocker", "pass", f"LICENSE_DEV_UNLOCK ok for env={env}")


@check("platform.seed_tenant", "warn")
def check_seed(db: Session) -> CheckResult:
    n = db.execute(text("SELECT count(*) FROM tenants")).scalar_one()
    if n < 1:
        return CheckResult("platform.seed_tenant", "warn", "fail", "No tenants found")
    return CheckResult("platform.seed_tenant", "warn", "pass", f"{n} tenant(s) present")


@check("dataops.backup_table", "warn")
def check_backup_table(db: Session) -> CheckResult:
    _ = db
    try:
        db.execute(text("SELECT count(*) FROM backup_jobs"))
        return CheckResult("dataops.backup_table", "warn", "pass", "backup_jobs present")
    except Exception as exc:  # noqa: BLE001
        return CheckResult("dataops.backup_table", "warn", "fail", f"backup_jobs missing: {exc}")


@check("calc.tce_gold", "blocker")
def check_tce_gold(_db: Session) -> CheckResult:
    _ = _db
    root = _fixtures_root() / "calc" / "tce"
    if not root.exists():
        return CheckResult("calc.tce_gold", "blocker", "fail", f"Missing fixtures at {root}")
    failed = []
    for path in sorted(root.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out = compute_estimate(data["inputs"])
        for k, expected in data["expect"].items():
            actual = out.get(k)
            if abs(float(actual) - float(expected)) > 0.02:
                failed.append(f"{path.name}:{k} expected {expected} got {actual}")
    if failed:
        return CheckResult("calc.tce_gold", "blocker", "fail", "TCE gold mismatches", {"failed": failed})
    return CheckResult("calc.tce_gold", "blocker", "pass", "TCE gold suite passed")


@check("calc.laytime_gold", "blocker")
def check_laytime_gold(_db: Session) -> CheckResult:
    _ = _db
    root = _fixtures_root() / "calc" / "laytime"
    if not root.exists():
        return CheckResult("calc.laytime_gold", "blocker", "fail", f"Missing fixtures at {root}")
    failed = []
    for path in sorted(root.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out = compute_laytime(data["inputs"])
        for k, expected in data["expect"].items():
            actual = out.get(k)
            if isinstance(expected, str):
                if actual != expected:
                    failed.append(f"{path.name}:{k} expected {expected} got {actual}")
            elif abs(float(actual) - float(expected)) > 0.02:
                failed.append(f"{path.name}:{k} expected {expected} got {actual}")
    if failed:
        return CheckResult("calc.laytime_gold", "blocker", "fail", "Laytime gold mismatches", {"failed": failed})
    return CheckResult("calc.laytime_gold", "blocker", "pass", "Laytime gold suite passed")


@check("schema.domain_tables", "warn")
def check_domain_tables(db: Session) -> CheckResult:
    for table in ("estimates", "charters", "voyages", "invoices", "laytime_calcs"):
        try:
            db.execute(text(f"SELECT count(*) FROM {table}"))
        except Exception as exc:  # noqa: BLE001
            return CheckResult("schema.domain_tables", "warn", "fail", f"{table}: {exc}")
    return CheckResult("schema.domain_tables", "warn", "pass", "Domain tables present")


def run_all_checks(db: Session) -> list[CheckResult]:
    results: list[CheckResult] = []
    for check_id, severity, fn in REGISTRY:
        try:
            results.append(fn(db))
        except Exception as exc:  # noqa: BLE001
            results.append(
                CheckResult(check_id, severity, "fail", f"Check crashed: {exc}", {"error": str(exc)})
            )
    return results


def score_results(results: list[CheckResult]) -> int:
    if not results:
        return 0
    ok = sum(1 for r in results if r.status == "pass")
    return int(100 * ok / len(results))
