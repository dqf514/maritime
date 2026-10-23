"""系统内置单据模板（HTML/CSS，Jinja2）。

这些是租户开箱即用的默认版式：`ensure_templates()` 首次访问时按租户补种，
原样存进 ``DocumentTemplate.system_body/system_css``，租户改动后随时可
「恢复默认」。

设计原则：
- **正式对外**：公司抬头 + 品牌色分隔线 + 右对齐单据标题/编号；页脚页码由
  PDF 引擎注入，模板不管。
- **可编辑**：正文里不写 Jinja 宏，全部展开成平铺 HTML —— 管理员在编辑器里
  看到的就是最终结构，不需要先学一套宏。
- **取值一律 ``header.get(...)``**：不同单据类型的 header 字段集不同，
  用 `.get()` 保证模板在字段缺失时印空白而不是 500。
- **用字得体**：对外件用词按航运单据惯例（"Bill To"、"Remit to"、
  "Time lost for which demurrage not to be paid"），不写口语。
"""

from __future__ import annotations

# ── 共用片段 ──────────────────────────────────────────────────────────────

_HEAD = """<div class="doc-head">
  <div class="doc-brand">
    {% if company.logo_data %}<img class="doc-logo" src="{{ company.logo_data }}" alt="">{% endif %}
    <div>
      <p class="doc-company-name">{{ company.display_name or company.legal_name }}</p>
      {% if company.address %}<p class="doc-company-meta">{{ company.address }}</p>{% endif %}
      <p class="doc-company-meta">{{ [company.phone, company.email, company.website] | select | join(' · ') }}</p>
      {% if company.tax_no %}<p class="doc-company-meta">Tax / VAT Reg. No. {{ company.tax_no }}</p>{% endif %}
    </div>
  </div>
  <div class="doc-title-block">
    <h1 class="doc-title">{{ doc.title }}</h1>
    <p class="doc-no">{{ doc.no }}</p>
    <p class="doc-no">{{ doc.generated_at[:10] if doc.generated_at else '' }}</p>
  </div>
</div>"""

_PARTY = """<div class="grid-2">
  <div>
    <p class="sect">Bill To</p>
    <dl class="kv">
      <dt>Party</dt><dd>{{ counterparty.name or '—' }}</dd>
      {% if counterparty.attention %}<dt>Attention</dt><dd>{{ counterparty.attention }}</dd>{% endif %}
      {% if counterparty.address %}<dt>Address</dt><dd>{{ counterparty.address }}</dd>{% endif %}
      {% if counterparty.tax_id %}<dt>Tax / VAT No.</dt><dd>{{ counterparty.tax_id }}</dd>{% endif %}
    </dl>
  </div>
  <div>
    <p class="sect">Voyage</p>
    <dl class="kv">
      <dt>Vessel</dt><dd>{{ vessel.name or '—' }}{% if vessel.imo %} (IMO {{ vessel.imo }}){% endif %}</dd>
      <dt>Voyage No.</dt><dd>{{ voyage.voyage_no or '—' }}</dd>
      <dt>Cargo</dt><dd>{{ voyage.cargo or '—' }}</dd>
    </dl>
  </div>
</div>"""

# Qty/Unit/Rate 三列按实际数据决定显隐 —— 一张只有 "Freight 1,850,000" 的发票
# 若还留着三个空列头，版面会显得很空。逐列判断：只要有一行填了就整列显示。
_LINES_TABLE = """{% set ns = namespace(qty=false, unit=false, rate=false) %}
{%- for l in lines -%}
  {%- if l.qty %}{% set ns.qty = true %}{% endif -%}
  {%- if l.unit %}{% set ns.unit = true %}{% endif -%}
  {%- if l.rate %}{% set ns.rate = true %}{% endif -%}
{%- endfor -%}
<table>
  <thead>
    <tr><th>Description</th>{% if ns.qty %}<th class="num">Qty</th>{% endif %}{% if ns.unit %}<th>Unit</th>{% endif %}{% if ns.rate %}<th class="num">Rate</th>{% endif %}<th class="num">Amount</th></tr>
  </thead>
  <tbody>
    {% for l in lines %}
    <tr>
      <td>{{ l.description }}{% if l.note %}<div class="note">{{ l.note }}</div>{% endif %}</td>
      {% if ns.qty %}<td class="num">{{ l.qty | num(2) }}</td>{% endif %}
      {% if ns.unit %}<td>{{ l.unit or '' }}</td>{% endif %}
      {% if ns.rate %}<td class="num">{{ l.rate | num(2) or '' }}</td>{% endif %}
      <td class="num">{{ l.amount | num(2) or '' }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>"""

_BANK = """{% if bank.bank_name %}
<p class="sect">Remit to</p>
<dl class="kv">
  <dt>Beneficiary</dt><dd>{{ bank.account_name or company.legal_name }}</dd>
  <dt>Bank</dt><dd>{{ bank.bank_name }}</dd>
  {% if bank.account_number %}<dt>Account No.</dt><dd>{{ bank.account_number }}</dd>{% endif %}
  {% if bank.swift %}<dt>SWIFT</dt><dd>{{ bank.swift }}</dd>{% endif %}
  {% if bank.iban %}<dt>IBAN</dt><dd>{{ bank.iban }}</dd>{% endif %}
  <dt>Currency</dt><dd>{{ bank.currency or totals.currency or 'USD' }}</dd>
</dl>
{% endif %}"""

_FOOTNOTE = """<p class="note">This document is issued electronically by {{ company.legal_name or company.display_name }}
and is valid without signature unless otherwise stated. Please quote the document reference
{{ doc.no }} on all correspondence.</p>"""

_SIGNATURE_ONE = """<div class="sign">
  <div>
    <div class="sign-line">For and on behalf of<br>{{ company.legal_name or company.display_name }}</div>
  </div>
</div>"""

_SIGNATURE_TWO = """<div class="sign">
  <div>
    <div class="sign-line">For and on behalf of<br>{{ company.legal_name or company.display_name }}</div>
  </div>
  <div>
    <div class="sign-line">For and on behalf of<br>{{ counterparty.name or 'Charterers' }}</div>
  </div>
</div>"""


def _doc(*parts: str) -> str:
    return "\n".join(p for p in parts if p).strip() + "\n"


# ── 单据正文 ──────────────────────────────────────────────────────────────

_INVOICE_BODY = _doc(
    _HEAD,
    _PARTY,
    """<div class="grid-2">
  <div>
    <p class="sect">Details</p>
    <dl class="kv">
      <dt>Invoice type</dt><dd>{{ header.get('invoice_type') or '—' }}</dd>
      <dt>Issue date</dt><dd>{{ header.get('issue_date') or '—' }}</dd>
      <dt>Due date</dt><dd>{{ header.get('due_date') or '—' }}</dd>
    </dl>
  </div>
  <div>
    <p class="sect">Reference</p>
    <dl class="kv">
      <dt>Currency</dt><dd>{{ totals.currency or header.get('currency') or 'USD' }}</dd>
      <dt>Status</dt><dd>{{ header.get('status') or '—' }}</dd>
      <dt>Voyage No.</dt><dd>{{ voyage.voyage_no or '—' }}</dd>
    </dl>
  </div>
</div>""",
    _LINES_TABLE,
    """<table>
  <tbody>
    <tr><td>Subtotal</td><td class="num">{{ (totals.subtotal or 0) | num(2) }}</td></tr>
    {% if totals.tax %}<tr><td>Tax</td><td class="num">{{ totals.tax | num(2) }}</td></tr>{% endif %}
    <tr><td>Total invoice amount</td><td class="num">{{ (totals.total or 0) | num(2) }}</td></tr>
    {% if totals.amount_paid %}<tr><td>Less: paid to date</td><td class="num">{{ totals.amount_paid | num(2) }}</td></tr>{% endif %}
    <tr class="total-row"><td>Balance due ({{ totals.currency or 'USD' }})</td>
        <td class="num">{{ (totals.balance if totals.balance is not none else totals.total) | num(2) }}</td></tr>
  </tbody>
</table>""",
    _BANK,
    _FOOTNOTE,
    _SIGNATURE_ONE,
)

_CREDIT_NOTE_BODY = _doc(
    _HEAD,
    _PARTY,
    """<p class="sect">Credit details</p>
<dl class="kv">
  <dt>Original invoice</dt><dd>{{ header.get('original_invoice_no') or '—' }}</dd>
  <dt>Credit note date</dt><dd>{{ header.get('issue_date') or '—' }}</dd>
  <dt>Reason</dt><dd>{{ header.get('reason') or '—' }}</dd>
  <dt>Status</dt><dd>{{ header.get('status') or '—' }}</dd>
</dl>""",
    _LINES_TABLE,
    """<table><tbody>
  <tr class="total-row"><td>Total credit ({{ totals.currency or 'USD' }})</td>
      <td class="num">{{ (totals.total or 0) | num(2) }}</td></tr>
</tbody></table>""",
    _FOOTNOTE,
    _SIGNATURE_ONE,
)

_LAYTIME_BODY = _doc(
    _HEAD,
    _PARTY,
    """<p class="sect">Laytime particulars</p>
<dl class="kv">
  <dt>Laytime terms</dt><dd>{{ header.get('terms') or '—' }}</dd>
  <dt>Allowed laytime (hrs)</dt><dd>{{ header.get('allowed_hours') if header.get('allowed_hours') is not none else '—' }}</dd>
  <dt>Demurrage rate (per day)</dt><dd>{{ header.get('demurrage_rate') | num(2) or '—' }}</dd>
  <dt>Despatch rate (per day)</dt><dd>{{ header.get('despatch_rate') | num(2) or '—' }}</dd>
</dl>""",
    """{% if ports %}
<p class="sect">Port calls</p>
<table>
  <thead><tr><th>#</th><th>Port</th><th>Function</th><th>NOR</th><th>ATA</th><th>ATD</th><th>Agent</th></tr></thead>
  <tbody>
    {% for p in ports %}
    <tr>
      <td>{{ p.seq }}</td>
      <td>{{ p.port or '—' }}{% if p.unlocode %} ({{ p.unlocode }}){% endif %}</td>
      <td>{{ p.purpose or '' }}</td>
      <td>{{ p.nor_at or '' }}</td>
      <td>{{ p.ata or '' }}</td>
      <td>{{ p.atd or '' }}</td>
      <td>{{ p.agent or '' }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endif %}""",
    """<p class="sect">Statement of time</p>
<table>
  <thead><tr><th>Event</th><th>From</th><th>To</th><th class="num">Gross hrs</th><th class="num">Counted hrs</th><th class="num">Cumulative</th></tr></thead>
  <tbody>
    {% for l in lines %}
    <tr{% if l.excluded %} class="excluded"{% endif %}>
      <td>{{ l.description }}{% if l.excluded %} <em>(excluded)</em>{% endif %}</td>
      <td>{{ l.start or '' }}</td>
      <td>{{ l.end or '' }}</td>
      <td class="num">{{ l.qty if l.qty is not none else '' }}</td>
      <td class="num">{{ l.amount if l.amount is not none else '' }}</td>
      <td class="num">{{ l.cumulative if l.cumulative is not none else '' }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>""",
    """<table><tbody>
  <tr><td>Allowed laytime (hrs)</td><td class="num">{{ totals.allowed_hours if totals.allowed_hours is not none else '—' }}</td></tr>
  <tr><td>Time used (hrs)</td><td class="num">{{ totals.used_hours if totals.used_hours is not none else '—' }}</td></tr>
  <tr><td>Excluded (hrs)</td><td class="num">{{ totals.excluded_hours if totals.excluded_hours is not none else '—' }}</td></tr>
  <tr><td>Balance (hrs)</td><td class="num">{{ totals.balance_hours if totals.balance_hours is not none else '—' }}</td></tr>
  <tr class="total-row"><td>{{ totals.result_label or 'Result' }} ({{ totals.currency or 'USD' }})</td>
      <td class="num">{{ (totals.amount or 0) | num(2) }}</td></tr>
</tbody></table>
{% if warnings %}
<p class="note">Note: {{ warnings | join('; ') }}</p>
{% endif %}""",
    _FOOTNOTE,
    _SIGNATURE_TWO,
)

_HIRE_BODY = _doc(
    _HEAD,
    _PARTY,
    """<p class="sect">Charter particulars</p>
<dl class="kv">
  <dt>Contract type</dt><dd>{{ charter.contract_type or '—' }}</dd>
  <dt>Delivery</dt><dd>{{ charter.delivery_port or '—' }} on {{ charter.delivery_date or '—' }}</dd>
  <dt>Redelivery</dt><dd>{{ charter.redelivery_port or '—' }} on {{ charter.redelivery_date or '—' }}</dd>
  <dt>Hire rate (per day)</dt><dd>{{ charter.hire_rate | num(2) or '—' }}</dd>
  <dt>Payment</dt><dd>{{ (charter.payment_frequency or 'monthly') | replace('_', ' ') | capitalize }}</dd>
</dl>""",
    """<p class="sect">Statement period</p>
<dl class="kv">
  <dt>From</dt><dd>{{ header.get('period_start') or '—' }}</dd>
  <dt>To</dt><dd>{{ header.get('period_end') or '—' }}</dd>
  <dt>Hire days</dt><dd>{{ totals.hire_days if totals.hire_days is not none else '—' }}</dd>
  <dt>Off-hire days</dt><dd>{{ totals.off_hire_days if totals.off_hire_days is not none else '—' }}</dd>
</dl>""",
    _LINES_TABLE,
    """<table><tbody>
  <tr><td>Gross hire</td><td class="num">{{ (totals.gross_hire or 0) | num(2) }}</td></tr>
  <tr><td>Less: off-hire</td><td class="num">{{ (totals.off_hire_deduction or 0) | num(2) }}</td></tr>
  {% if totals.bunker_adjustment %}<tr><td>Bunker adjustment</td><td class="num">{{ totals.bunker_adjustment | num(2) }}</td></tr>{% endif %}
  {% if totals.other_adjustments %}<tr><td>Other adjustments</td><td class="num">{{ totals.other_adjustments | num(2) }}</td></tr>{% endif %}
  <tr class="total-row"><td>Net hire payable ({{ totals.currency or 'USD' }})</td>
      <td class="num">{{ (totals.total or 0) | num(2) }}</td></tr>
</tbody></table>""",
    _BANK,
    _FOOTNOTE,
    _SIGNATURE_TWO,
)

_RECAP_BODY = _doc(
    _HEAD,
    _PARTY,
    """<p class="sect">Fixture summary</p>
<dl class="kv">
  <dt>Charterers</dt><dd>{{ counterparty.name or '—' }}</dd>
  <dt>Vessel</dt><dd>{{ vessel.name or '—' }}{% if vessel.imo %} (IMO {{ vessel.imo }}){% endif %}</dd>
  <dt>Cargo</dt><dd>{{ voyage.cargo or '—' }}{% if header.get('cargo_qty') %} — {{ header.get('cargo_qty') }} MT{% endif %}</dd>
  <dt>Loading port</dt><dd>{{ ports[0].port if ports and ports[0].port else '—' }}</dd>
  <dt>Discharging port</dt><dd>{{ ports[1].port if ports | length > 1 and ports[1].port else '—' }}</dd>
  <dt>Laycan</dt><dd>{{ header.get('laycan_from') or '—' }} to {{ header.get('laycan_to') or '—' }}</dd>
  <dt>CP form</dt><dd>{{ header.get('cp_form') or '—' }}</dd>
  <dt>Laytime terms</dt><dd>{{ header.get('laytime_terms') or '—' }}</dd>
  <dt>Freight</dt>
  <dd>{% if header.get('freight_basis') == 'lumpsum' %}Lump sum {% endif %}{{ header.get('freight_rate') | num(4) or '—' }}{% if header.get('freight_basis') == 'per_mt' %} per metric ton{% endif %} ({{ header.get('currency') or 'USD' }})</dd>
  <dt>Demurrage / Despatch</dt>
  <dd>{{ header.get('demurrage_rate_pd') | num(2) or '—' }} / {{ header.get('despatch_rate_pd') | num(2) or '—' }} per day</dd>
  <dt>Commission</dt><dd>{{ header.get('commission_pct') }}%</dd>
  <dt>Status</dt><dd>{{ header.get('status') or '—' }}</dd>
</dl>""",
    _LINES_TABLE,
    """<table><tbody>
  <tr class="total-row"><td>Total freight ({{ totals.currency or 'USD' }})</td>
      <td class="num">{{ (totals.total or 0) | num(2) }}</td></tr>
</tbody></table>""",
    _FOOTNOTE,
    """<p class="note">Time of the essence of this contract. All terms not expressly stated herein
shall be subject to the governing charterparty form referenced above.</p>""",
    _SIGNATURE_TWO,
)

_ESTIMATE_BODY = _doc(
    _HEAD,
    _PARTY,
    """<p class="sect">Estimate summary</p>
<dl class="kv">
  <dt>Title</dt><dd>{{ header.get('title') or '—' }}</dd>
  <dt>Mode</dt><dd>{{ header.get('mode') or '—' }}</dd>
  <dt>Cargo quantity (MT)</dt><dd>{{ header.get('cargo_qty') if header.get('cargo_qty') is not none else '—' }}</dd>
  <dt>Freight rate</dt><dd>{{ header.get('freight_rate') if header.get('freight_rate') is not none else '—' }}</dd>
  <dt>Bunker price (USD/MT)</dt><dd>{{ header.get('bunker_price') if header.get('bunker_price') is not none else '—' }}</dd>
  <dt>Sea days</dt><dd>{{ header.get('sea_days') if header.get('sea_days') is not none else '—' }}</dd>
  <dt>Port days</dt><dd>{{ header.get('port_days') if header.get('port_days') is not none else '—' }}</dd>
  <dt>Total days</dt><dd>{{ header.get('total_days') if header.get('total_days') is not none else '—' }}</dd>
</dl>""",
    _LINES_TABLE,
    """<table><tbody>
  <tr><td>Total revenue</td><td class="num">{{ (totals.total_revenue or 0) | num(2) }}</td></tr>
  <tr><td>Total cost</td><td class="num">{{ (totals.total_cost or 0) | num(2) }}</td></tr>
  <tr class="total-row"><td>Net result ({{ totals.currency or 'USD' }})</td>
      <td class="num">{{ (totals.total or 0) | num(2) }}</td></tr>
  <tr class="total-row"><td>TCE (per day)</td><td class="num">{{ (totals.tce or 0) | num(2) }}</td></tr>
</tbody></table>""",
    """<p class="note">Estimate is indicative only and subject to final fixtures, actual bunker
consumption and prevailing emissions pricing at the time of the voyage.</p>""",
    _SIGNATURE_ONE,
)

_PDA_BODY = _doc(
    _HEAD,
    _PARTY,
    """<p class="sect">Disbursement particulars</p>
<dl class="kv">
  <dt>Port</dt><dd>{{ header.get('port') or '—' }}</dd>
  <dt>Agent</dt><dd>{{ header.get('agent') or '—' }}</dd>
  <dt>Status</dt><dd>{{ header.get('status') or '—' }}</dd>
  <dt>Currency</dt><dd>{{ totals.currency or header.get('currency') or 'USD' }}</dd>
</dl>""",
    _LINES_TABLE,
    """<table><tbody>
  <tr><td>Proforma (PDA)</td><td class="num">{{ (totals.pda_amount or 0) | num(2) }}</td></tr>
  {% if totals.fda_amount %}<tr><td>Final (FDA)</td><td class="num">{{ totals.fda_amount | num(2) }}</td></tr>{% endif %}
  <tr class="total-row"><td>Total ({{ totals.currency or 'USD' }})</td>
      <td class="num">{{ (totals.total or 0) | num(2) }}</td></tr>
</tbody></table>""",
    _BANK,
    _FOOTNOTE,
    _SIGNATURE_TWO,
)

_CLAIM_BODY = _doc(
    _HEAD,
    _PARTY,
    """<p class="sect">Claim particulars</p>
<dl class="kv">
  <dt>Claim type</dt><dd>{{ header.get('claim_type') or '—' }}{% if header.get('subtype') %} — {{ header.get('subtype') }}{% endif %}</dd>
  <dt>Vessel / Voyage</dt><dd>{{ vessel.name or '—' }} / {{ voyage.voyage_no or '—' }}</dd>
  <dt>Time bar</dt><dd>{{ header.get('time_bar') or '—' }}</dd>
  <dt>Status</dt><dd>{{ header.get('status') or '—' }}</dd>
</dl>""",
    """<p class="sect">Statement of claim</p>
<table>
  <thead><tr><th>Item</th><th class="num">Amount ({{ totals.currency or 'USD' }})</th></tr></thead>
  <tbody>
    {% for l in lines %}
    <tr><td>{{ l.description }}{% if l.note %}<div class="note">{{ l.note }}</div>{% endif %}</td>
        <td class="num">{{ l.amount | num(2) or '' }}</td></tr>
    {% endfor %}
    {% if totals.deductions %}
    <tr><td>Less: deductions</td><td class="num">({{ totals.deductions | num(2) }})</td></tr>
    {% endif %}
    <tr class="total-row"><td>Amount claimed</td>
        <td class="num">{{ (totals.total or 0) | num(2) }}</td></tr>
  </tbody>
</table>""",
    """{% if header.get('notes') %}<p class="note">{{ header.get('notes') }}</p>{% endif %}
<p class="note">This claim is made under and by virtue of the terms of the charterparty
referenced above. We reserve all rights and remedies available to us.</p>""",
    _SIGNATURE_TWO,
)

_SOF_BODY = _doc(
    _HEAD,
    _PARTY,
    """<p class="sect">Port call</p>
<dl class="kv">
  <dt>Port</dt><dd>{{ header.get('port') or '—' }}{% if header.get('unlocode') %} ({{ header.get('unlocode') }}){% endif %}</dd>
  <dt>Function</dt><dd>{{ header.get('purpose') or '—' }}</dd>
  <dt>Agent</dt><dd>{{ header.get('agent') or '—' }}</dd>
  <dt>Timezone</dt><dd>{{ header.get('timezone') or 'UTC' }}</dd>
  <dt>NOR tendered</dt><dd>{{ header.get('nor_at') or '—' }}</dd>
  <dt>ETA / ATA</dt><dd>{{ header.get('eta') or '—' }} / {{ header.get('ata') or '—' }}</dd>
  <dt>ETD / ATD</dt><dd>{{ header.get('etd') or '—' }} / {{ header.get('atd') or '—' }}</dd>
</dl>""",
    """<p class="sect">Facts of call</p>
<table>
  <thead><tr><th>#</th><th>Event</th><th>Time</th><th>Remarks</th></tr></thead>
  <tbody>
    {% for l in lines %}
    <tr><td>{{ loop.index }}</td><td>{{ l.description }}</td><td>{{ l.start or '' }}</td>
        <td>{{ l.note or '' }}</td></tr>
    {% endfor %}
  </tbody>
</table>""",
    _FOOTNOTE,
    _SIGNATURE_TWO,
)

_COA_BODY = _doc(
    _HEAD,
    _PARTY,
    """<p class="sect">Contract particulars</p>
<dl class="kv">
  <dt>Period</dt><dd>{{ header.get('period_from') or '—' }} to {{ header.get('period_to') or '—' }}</dd>
  <dt>Total quantity</dt><dd>{{ header.get('total_qty') if header.get('total_qty') is not none else '—' }} {{ header.get('qty_unit') or 'mt' }}</dd>
  <dt>Rate basis</dt><dd>{{ (header.get('rate_basis') or '—') | replace('_', ' ') }}</dd>
  <dt>Rate</dt><dd>{{ header.get('rate') | num(4) or '—' }} {{ totals.currency or 'USD' }}</dd>
  <dt>Cargo specification</dt><dd>{{ header.get('cargo_spec') or '—' }}</dd>
  <dt>Tolerance / Overage</dt><dd>{{ header.get('tolerance_pct') or 0 }}% / {{ header.get('overage_pct') or 0 }}%</dd>
  <dt>Status</dt><dd>{{ header.get('status') or '—' }}</dd>
</dl>""",
    """<p class="sect">Itinerary</p>
<table>
  <thead><tr><th>#</th><th>Load port</th><th>Discharge port</th><th class="num">Quantity</th><th>Notes</th></tr></thead>
  <tbody>
    {% for l in lines %}
    <tr><td>{{ loop.index }}</td><td>{{ l.description.split(' → ')[0] if ' → ' in l.description else l.description }}</td>
        <td>{{ l.description.split(' → ')[1] if ' → ' in l.description else '—' }}</td>
        <td class="num">{{ l.qty if l.qty is not none else '' }} {{ l.unit or '' }}</td>
        <td>{{ l.note or '' }}</td></tr>
    {% endfor %}
  </tbody>
</table>""",
    _FOOTNOTE,
    _SIGNATURE_TWO,
)

_VI_BODY = _doc(
    _HEAD,
    """<p class="sect">Voyage</p>
<dl class="kv">
  <dt>Voyage No.</dt><dd>{{ header.get('voyage_no') or '—' }}</dd>
  <dt>Vessel</dt><dd>{{ vessel.name or '—' }}{% if vessel.imo %} (IMO {{ vessel.imo }}){% endif %}</dd>
  <dt>Cargo</dt><dd>{{ header.get('cargo') or '—' }}</dd>
  <dt>CP date</dt><dd>{{ header.get('cp_date') or '—' }}</dd>
  <dt>Status</dt><dd>{{ header.get('status') or '—' }}</dd>
</dl>""",
    """<p class="sect">Port call sequence</p>
<table>
  <thead><tr><th>#</th><th>Port</th><th>Function</th><th>ETA</th><th>ETD</th><th>Agent</th></tr></thead>
  <tbody>
    {% for p in ports %}
    <tr><td>{{ p.seq }}</td><td>{{ p.port or '—' }}{% if p.unlocode %} ({{ p.unlocode }}){% endif %}</td>
        <td>{{ p.purpose or '' }}</td><td>{{ p.eta or '' }}</td><td>{{ p.etd or '' }}</td>
        <td>{{ p.agent or '' }}</td></tr>
    {% endfor %}
  </tbody>
</table>""",
    """{% if header.get('notes') %}
<p class="sect">Instructions</p>
<p>{{ header.get('notes') }}</p>
{% endif %}""",
    _FOOTNOTE,
    _SIGNATURE_ONE,
)

_SOA_BODY = _doc(
    _HEAD,
    _PARTY,
    """<p class="sect">Statement as at {{ doc.generated_at[:10] if doc.generated_at else '' }}</p>
<dl class="kv">
  <dt>Account party</dt><dd>{{ counterparty.name or '—' }}</dd>
  <dt>Currency</dt><dd>{{ totals.currency or 'USD' }}</dd>
</dl>""",
    """<table>
  <thead><tr><th>Document</th><th>Issued</th><th>Due</th><th>Status</th><th class="num">Balance</th></tr></thead>
  <tbody>
    {% for l in lines %}
    <tr><td>{{ l.description }}</td><td>{{ l.start or '' }}</td><td>{{ l.end or '' }}</td>
        <td>{{ l.note or '' }}</td>
        <td class="num">{{ l.amount | num(2) or '' }}</td></tr>
    {% endfor %}
    {% if totals.amount_paid %}
    <tr><td colspan="4">Less: payments received</td>
        <td class="num">({{ totals.amount_paid | num(2) }})</td></tr>
    {% endif %}
    <tr class="total-row"><td colspan="4">Balance outstanding ({{ totals.currency or 'USD' }})</td>
        <td class="num">{{ (totals.total or 0) | num(2) }}</td></tr>
  </tbody>
</table>""",
    _BANK,
    _FOOTNOTE,
    _SIGNATURE_ONE,
)

_RA_BODY = _doc(
    _HEAD,
    _PARTY,
    """<p class="sect">Remittance details</p>
<dl class="kv">
  <dt>Batch reference</dt><dd>{{ doc.no }}</dd>
  <dt>Batch date</dt><dd>{{ header.get('value_date') or header.get('batch_date') or '—' }}</dd>
  <dt>Payment status</dt><dd>{{ header.get('status') or '—' }}</dd>
  <dt>Currency</dt><dd>{{ totals.currency or 'USD' }}</dd>
</dl>""",
    _LINES_TABLE,
    """<table><tbody>
  <tr class="total-row"><td>Total remitted ({{ totals.currency or 'USD' }})</td>
      <td class="num">{{ (totals.total or 0) | num(2) }}</td></tr>
</tbody></table>""",
    _BANK,
    _FOOTNOTE,
    _SIGNATURE_ONE,
)

_BDN_BODY = _doc(
    _HEAD,
    _PARTY,
    """<p class="sect">Delivery particulars</p>
<dl class="kv">
  <dt>Grade</dt><dd>{{ header.get('grade') or '—' }}</dd>
  <dt>Quantity delivered</dt><dd>{{ header.get('quantity_mt') if header.get('quantity_mt') is not none else '—' }} MT</dd>
  <dt>Unit price</dt><dd>{{ header.get('price_per_mt') | num(2) or '—' }} {{ totals.currency or 'USD' }}</dd>
  <dt>Delivery date</dt><dd>{{ header.get('delivery_date') or '—' }}</dd>
  <dt>Order status</dt><dd>{{ header.get('status') or '—' }}</dd>
</dl>""",
    _LINES_TABLE,
    """<table><tbody>
  <tr class="total-row"><td>Total ({{ totals.currency or 'USD' }})</td>
      <td class="num">{{ (totals.total or 0) | num(2) }}</td></tr>
</tbody></table>
<p class="note">Quantity is subject to final survey and vessel's tanks ullage measurement.
Density and sulphur content are as declared by the supplier at the time of delivery.</p>""",
    _FOOTNOTE,
    _SIGNATURE_TWO,
)


# ── 注册表（ensure_templates 按此补种） ───────────────────────────────────

_COMMON_CSS = """
/* 单据类型专属微调 —— 覆盖在通用基础版式之后 */
.excluded td { color: #9aa3ad; font-style: italic; }
tbody tr:nth-child(even) td { background: #fbfcfd; }
"""


def _tpl(entity_type: str, name: str, body: str, module: str) -> dict:
    return {"entity_type": entity_type, "name": name, "body": body,
            "css": _COMMON_CSS, "locale": "en", "code": "default"}


SYSTEM_TEMPLATES: list[dict] = [
    _tpl("invoice", "Invoice — standard", _INVOICE_BODY, "finance"),
    _tpl("credit_note", "Credit note", _CREDIT_NOTE_BODY, "finance"),
    _tpl("laytime_statement", "Laytime statement", _LAYTIME_BODY, "laytime"),
    _tpl("hire_statement", "Hire statement", _HIRE_BODY, "chartering"),
    _tpl("charter_recap", "Fixture recap", _RECAP_BODY, "chartering"),
    _tpl("estimate", "Estimate / TCE", _ESTIMATE_BODY, "estimate"),
    _tpl("pda", "Proforma disbursement account", _PDA_BODY, "finance"),
    _tpl("claim", "Statement of claim", _CLAIM_BODY, "laytime"),
    _tpl("sof", "Statement of facts", _SOF_BODY, "operations"),
    _tpl("coa", "Contract of affreightment", _COA_BODY, "chartering"),
    _tpl("voyage_instruction", "Voyage instruction", _VI_BODY, "operations"),
    _tpl("statement_of_account", "Statement of account", _SOA_BODY, "finance"),
    _tpl("remittance_advice", "Remittance advice", _RA_BODY, "finance"),
    _tpl("bdn", "Bunker delivery note", _BDN_BODY, "bunker"),
]
