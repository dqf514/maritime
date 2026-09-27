# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

MariOS (MOS) — a shipping commercial voyage-management platform (航运商业操作系统) for owners, charterers, operators, and ship managers. Estimate/TCE → chartering → voyage execution → laytime/claims → bunker → finance/GL, plus AI hub, M365 integration, and fleet digital twin. Modular monolith, multi-tenant, module-licensed.

This directory (`mos/`) is a subdirectory of the GitHub repo `github.com/dqf514/maritime`; git commands run against the parent repo. Docs and code comments are mixed Chinese/English — match surrounding style. UI language defaults to English with full i18n.

Demo login: `admin@demo.marios` / `Demo1234!` / tenant `demo`.

## Commands

All commands assume Windows PowerShell paths from DEVELOPMENT.md; adjust for your shell.

### API (FastAPI, `apps/api`)

```powershell
cd apps/api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r requirements.txt
$env:LICENSE_DEV_UNLOCK="all"          # unlocks all modules in dev — required for most dev/test work
uvicorn app.main:app --reload --port 8000
```

### Web (Next.js, `apps/web`)

```powershell
cd apps/web
npm install
$env:NEXT_PUBLIC_API_BASE="http://localhost:8000"
npm run dev        # also: npm run build / npm run start / npm run lint
```

### Tests (必跑 — run before considering any change done)

```powershell
cd apps/api
$env:LICENSE_DEV_UNLOCK="all"
.\.venv\Scripts\python.exe -m pytest -q
```

Single test: `python -m pytest tests/test_full_chain.py::test_calc_engines_unit -q` (standard pytest node-id selection).

The suite is an end-to-end chain: login → estimate/TCE gold → CP state machine → voyage/noon/SOF → laytime/claims/PDA → bunker ROB → invoices/payments/GL → market/emissions/reports → pooling/risk/berth/portal → Twin L4 → SelfCheck gold, plus sanctions-blocking and tenant-isolation cases.

Gold fixtures live in `fixtures/calc/tce` and `fixtures/calc/laytime` — shared source of truth for both pytest and the in-app SelfCheck (`apps/api/checks/registry.py`). Keep them in sync.

### Deploy

`deploy/compose/docker-compose.yml` (Postgres + Redis + MinIO + API + Web). The API build context **must be `mos/` root** (fixtures are at `mos/fixtures`, SelfCheck depends on this layout). Do not mount `docs/ddl.sql` for DB init — it has drifted from the models; empty DBs are created by `create_all` at API startup.

## Architecture

### Layout

- `apps/api` — FastAPI backend (the bulk of the system)
- `apps/web` — Next.js frontend
- `fixtures/calc` — calculation gold fixtures (TCE, laytime)
- `deploy/compose` — Docker Compose deployment
- `docs/` — customer-facing docs; `docs/README.md` points to the dev SSOT ("DDS V2.1", referenced but not present in the tree). Keep internal planning out of customer-visible docs.

### Backend (`apps/api/app`)

Layering: **routers** (`routers/*.py`, all mounted under `/api/v1`) → **services** (`services/*.py`, domain engines and platform infrastructure) → **models** (`models*.py`, split by domain: `models_domain`, `models_ops`, `models_gl`, `models_identity`, `models_saas`, `models_office`, …) + Pydantic schemas (`schemas*.py`).

Adding a new `models_*.py` module requires importing it in **both** `app/main.py` and `tests/conftest.py` (metadata registration is import-driven).

Key cross-cutting pieces:

- **Multi-tenancy**: there is NO database-level isolation. Every route hand-writes `tenant_id ==` filters. `services/tenant_guard.py` (`scoped_get` / `scoped_query`) is the convention wrapper — use it for new code; it also applies soft-delete filtering. Soft delete has two conventions (see `services/recycle.py`): `deleted_at` timestamp column, or `status = "deleted"`. `services/tenant_datastore.py` is a future hook for per-tenant engines (currently always primary).
- **State machines**: `services/state_machine.py` — `transition()` raises 409 `INVALID_STATE` for illegal moves; per-entity tables (`CHARTER_TRANSITIONS`, `VOYAGE_TRANSITIONS`, `INVOICE_TRANSITIONS`, …). Finance workflows (e.g. credit-note/red-flush 红冲) are implemented at the router layer alongside these transitions.
- **Calculation engines**: `services/estimate_engine.py` (TCE), `services/laytime_engine.py`, `services/gl_engine.py`, `services/pnl_engine.py`, `services/hire_engine.py`, `services/carbon_calculator.py`, `services/cii.py`. Decimal-based, deterministic — validate against `fixtures/calc`.
- **Auth** (`app/security.py`): dual-track sessions — JWT returned in the body *and* set as HttpOnly cookie `marios_token` (legacy `voyageos_token` still accepted). Bearer/API-key auth also supported. CSRF posture is SameSite=Lax + strict CORS allow_credentials (documented in `security.py` — keep that reasoning intact if you change cookies/CORS). Module licensing via `require_module()` → 403 `MODULE_NOT_LICENSED`; `LICENSE_DEV_UNLOCK=all` bypasses in dev.
- **Startup seeding** (`main.py` lifespan): catalogs always seed (SaaS catalog, i18n, ops catalog, reference catalog); demo tenants/users only when `SEED_DEMO=true`.
- **Schema management**: `Base.metadata.create_all` runs at startup, plus legacy guarded `ALTER TABLE` patches in `main.py` for old SQLite dev DBs. **New schema changes go through Alembic** (`alembic revision --autogenerate`), never new entries in the ALTER patch list. For existing databases run `alembic stamp head` before `alembic upgrade head` (see `alembic/README.md`).
- **Navigation**: role-based, server-driven nav defined in `services/shell_nav.py` (iMOS-style modules: Workbench → Chartering → Operations → Finance → Technical → Analytics → Master data → Administration → Platform), consumed by search ACL and the web AppShell.
- **SelfCheck** (`apps/api/checks/registry.py`): in-app health/calc-gold checks; gold suites must stay green alongside pytest.

Important env vars: `DATABASE_URL`, `JWT_SECRET` (no default in production), `LICENSE_DEV_UNLOCK`, `SEED_DEMO`, `NEXT_PUBLIC_API_BASE`, `RATE_LIMIT_ENABLED`, `COOKIE_SECURE`. All settings in `app/config.py`.

### Frontend (`apps/web`)

Next.js 16 + React 19 + TypeScript. **This is not the Next.js you may know** — `apps/web/AGENTS.md` (regenerated by `next dev`, do not delete that block) instructs reading `node_modules/next/dist/docs/` before writing Next-specific code; `apps/web/CLAUDE.md` redirects to it.

- Route folders under `app/` mirror backend modules (`estimates/`, `charters/`, `operations/`, `finance/`, `twin/`, `platform/`, …).
- `lib/api.ts` — fetch wrapper (`apiGet`/`apiPost`, `NEXT_PUBLIC_API_BASE`); token in localStorage (`marios_token`, with one-time migration from legacy `voyageos_*` keys).
- `lib/i18n.tsx` — client i18n; UI default English, terminology-aware.
- `components/` — shared UI kit (DataTable, RecordModal, StateView, Toast, Skeleton, ErrorBoundary, ThemeProvider/dark mode, LookupSelect, AppShell).
- AppShell renders the nav served by the API (`shell_nav`); keep nav changes server-side rather than hardcoding in the web app.
