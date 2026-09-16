# MariOS development

GitHub: https://github.com/dqf514/maritime/tree/main/mos

## Quick start (local)

### API

```powershell
cd D:\ai\LMOS\mos\apps\api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r requirements.txt
$env:LICENSE_DEV_UNLOCK="all"
uvicorn app.main:app --reload --port 8000
```

Demo: `admin@demo.marios` / `Demo1234!` / tenant `demo`

### Web

```powershell
cd D:\ai\LMOS\mos\apps\web
npm install
$env:NEXT_PUBLIC_API_BASE="http://localhost:8000"
npm run dev
```

### Full-chain tests (必跑)

```powershell
cd D:\ai\LMOS\mos\apps\api
$env:LICENSE_DEV_UNLOCK="all"
.\.venv\Scripts\python.exe -m pytest -q
```

覆盖：登录 → 估算/TCE 金样 → CP 状态机 → 航次/午报/SOF → Laytime/索赔/PDA → 燃油 ROB → 发票收款/GL → 市场/排放/报表 → 联营池/风险/泊位/门户 → Twin L4 → SelfCheck 金样全绿；另含制裁阻断用例。

金样例：`mos/fixtures/calc/tce`、`mos/fixtures/calc/laytime`（SelfCheck 与 pytest 同源）。

## Waves delivered (0–8 skeleton + closed loops)

| Wave | Scope |
| --- | --- |
| 0 | Shell / Auth / License / SelfCheck / DataOps backup |
| 1 | Masterdata / Email review / AI Hub / Connectors / Excel migrate commit |
| 2 | Estimate (TCE) / Chartering / Scheduling |
| 3 | Operations / PortCall / Noon / SOF / Twin L1–L2 |
| 4 | Laytime / Claims / Port PDA-FDA |
| 5 | Bunker ROB / Invoices / Payments / GL post |
| 6 | Market / DQ / Emissions / Analytics reports |
| 7 | Pooling / Risk / Berth / Portal messages |
| 8 | Twin L4 what-if / SelfCheck gold / domain schema checks |

API version: `0.9.0-full`
