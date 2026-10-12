"""SWIFT / Payment Batch export tests (C3-P2).

MT103-style plain text + ISO 20022 pain.001.001.03 XML over payment batches.
Covers: expected fields, XML parse + values, cross-tenant 404, escaping of
hostile counterparty names, unsupported format → 422, deterministic output.

运行：
    LICENSE_DEV_UNLOCK=all python -m pytest tests/test_payment_export.py -q
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from uuid import uuid4

API = "/api/v1"
PAIN_NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"


def _create_invoice(client, h, amount=3000.0, currency="USD", counterparty_id=None):
    payload = {"amount": amount, "currency": currency}
    if counterparty_id:
        payload["counterparty_id"] = counterparty_id
    r = client.post(f"{API}/invoices", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _issue(client, h, iid):
    assert client.post(f"{API}/invoices/{iid}/transition?target=pending_approval", headers=h).status_code == 200
    assert client.post(f"{API}/invoices/{iid}/transition?target=issued", headers=h).status_code == 200


def _create_batch(client, h, invoice_ids, bank_charge_mode="shared"):
    r = client.post(
        f"{API}/payments/batches",
        headers=h,
        json={"invoice_ids": invoice_ids, "bank_charge_mode": bank_charge_mode},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _mk_batch_with_payments(client, h, amounts=(3000.0, 2000.0), counterparty_id=None):
    inv_ids = []
    for amt in amounts:
        inv = _create_invoice(client, h, amount=amt, counterparty_id=counterparty_id)
        _issue(client, h, inv["id"])
        inv_ids.append(inv["id"])
    return _create_batch(client, h, inv_ids), inv_ids


def _own_bank(client, h):
    return client.post(
        f"{API}/payments/bank-accounts",
        headers=h,
        json={
            "bank_name": "Own Bank NV",
            "account_name": "MariOS Demo Shipping",
            "account_number": "111222333",
            "swift_code": "OWNBBEBB",
            "iban": "BE62510007547061",
            "currency": "USD",
            "is_default": True,
        },
    ).json()


def _cp_bank(client, h, counterparty_id, account_name="Acme Chartering"):
    return client.post(
        f"{API}/payments/bank-accounts",
        headers=h,
        json={
            "bank_name": "Creditor Bank",
            "account_name": account_name,
            "account_number": "999888777",
            "swift_code": "CREDDEFF",
            "iban": "DE89370400440532013000",
            "currency": "USD",
            "is_default": True,
            "counterparty_id": counterparty_id,
        },
    ).json()


# —— 1. MT103-style plain text ————————————————————————————————————————


def test_mt103_export_contains_expected_fields(client, auth_headers):
    h = auth_headers
    _own_bank(client, h)
    cp = client.post(
        f"{API}/masterdata/counterparties",
        headers=h,
        json={"name": f"CP MT103 {uuid4().hex[:6]}", "type": "charterer"},
    ).json()
    _cp_bank(client, h, cp["id"])
    batch, inv_ids = _mk_batch_with_payments(client, h, amounts=(3000.0,), counterparty_id=cp["id"])

    r = client.get(f"{API}/payments/batches/{batch['id']}/export?format=mt103", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain")
    assert "attachment" in r.headers["content-disposition"]
    assert ".mt103" in r.headers["content-disposition"]
    assert batch["batch_number"] in r.headers["content-disposition"]

    body = r.text
    # SWIFT field blocks (best-effort human-readable)
    assert ":20:" in body
    assert ":23B:CRED" in body
    assert ":32A:" in body
    assert ":50K:" in body
    assert ":59:" in body
    assert ":70:" in body
    assert ":71A:" in body
    assert batch["batch_number"] in body
    # amounts use SWIFT comma decimal; 3000.00 → 3000,00
    assert "USD3000,00" in body
    # party bank details
    assert "OWNBBEBB" in body
    assert "CREDDEFF" in body
    assert "111222333" in body
    assert "999888777" in body
    assert "Acme Chartering" in body
    # disclaimer: not a compliance engine
    assert "not a full SWIFT compliance engine" in body


# —— 2. pain.001.001.03 XML ————————————————————————————————————————————


def test_pain001_export_parses_and_expected_values(client, auth_headers):
    h = auth_headers
    _own_bank(client, h)
    cp = client.post(
        f"{API}/masterdata/counterparties",
        headers=h,
        json={"name": f"CP PAIN {uuid4().hex[:6]}", "type": "charterer"},
    ).json()
    _cp_bank(client, h, cp["id"])
    batch, _ = _mk_batch_with_payments(client, h, amounts=(3000.0, 2000.0), counterparty_id=cp["id"])

    r = client.get(f"{API}/payments/batches/{batch['id']}/export?format=pain001", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/xml")
    assert "attachment" in r.headers["content-disposition"]
    assert ".pain001.xml" in r.headers["content-disposition"]
    assert batch["batch_number"] in r.headers["content-disposition"]

    root = ET.fromstring(r.text)
    assert root.tag == f"{{{PAIN_NS}}}Document"
    grp = root.find(f"{{{PAIN_NS}}}CstmrCdtTrfInitn/{{{PAIN_NS}}}GrpHdr")
    assert grp is not None
    assert grp.findtext(f"{{{PAIN_NS}}}MsgId") == batch["batch_number"]
    assert grp.findtext(f"{{{PAIN_NS}}}NbOfTxs") == "2"
    assert float(grp.findtext(f"{{{PAIN_NS}}}CtrlSum")) == 5000.0

    pmt = root.find(f"{{{PAIN_NS}}}CstmrCdtTrfInitn/{{{PAIN_NS}}}PmtInf")
    assert pmt is not None
    assert pmt.findtext(f"{{{PAIN_NS}}}PmtMtd") == "TRF"
    assert pmt.findtext(f"{{{PAIN_NS}}}ChrgBr") == "SHAR"
    # debtor = own bank account
    dbtr = pmt.find(f"{{{PAIN_NS}}}Dbtr")
    assert dbtr is not None and dbtr.findtext(f"{{{PAIN_NS}}}Nm") == "MariOS Demo Shipping"
    dbtr_iban = pmt.findtext(f"{{{PAIN_NS}}}DbtrAcct/{{{PAIN_NS}}}Id/{{{PAIN_NS}}}IBAN")
    assert dbtr_iban == "BE62510007547061"
    dbtr_bic = pmt.findtext(f"{{{PAIN_NS}}}DbtrAgt/{{{PAIN_NS}}}FinInstnId/{{{PAIN_NS}}}BIC")
    assert dbtr_bic == "OWNBBEBB"

    txs = root.findall(f".//{{{PAIN_NS}}}CdtTrfTxInf")
    assert len(txs) == 2
    total = 0.0
    for tx in txs:
        amt_el = tx.find(f"{{{PAIN_NS}}}Amt/{{{PAIN_NS}}}InstdAmt")
        assert amt_el is not None
        assert amt_el.get("Ccy") == "USD"
        total += float(amt_el.text)
        assert tx.find(f"{{{PAIN_NS}}}PmtId/{{{PAIN_NS}}}EndToEndId") is not None
        assert tx.findtext(f"{{{PAIN_NS}}}Cdtr/{{{PAIN_NS}}}Nm") is not None
        assert tx.find(f"{{{PAIN_NS}}}RmtInf/{{{PAIN_NS}}}Ustrd") is not None
    assert total == 5000.0
    # creditor bank details from bank_accounts
    c_bic = txs[0].findtext(f"{{{PAIN_NS}}}CdtrAgt/{{{PAIN_NS}}}FinInstnId/{{{PAIN_NS}}}BIC")
    assert c_bic == "CREDDEFF"
    c_iban = txs[0].findtext(f"{{{PAIN_NS}}}CdtrAcct/{{{PAIN_NS}}}Id/{{{PAIN_NS}}}IBAN")
    assert c_iban == "DE89370400440532013000"


# —— 3. Cross-tenant → 404 ————————————————————————————————————————————


def test_cross_tenant_batch_export_404(client, auth_headers):
    from tests.isolation_helpers import create_tenant

    h = auth_headers
    _, hb = create_tenant(
        client, code=f"payx{uuid4().hex[:4]}", name="PayExport Co", admin_email="admin@payexport.example.com"
    )
    inv = _create_invoice(client, hb, amount=1500.0)
    _issue(client, hb, inv["id"])
    batch_b = _create_batch(client, hb, [inv["id"]])

    for fmt in ("mt103", "pain001"):
        r = client.get(f"{API}/payments/batches/{batch_b['id']}/export?format={fmt}", headers=h)
        assert r.status_code == 404, f"{fmt} leaked cross-tenant batch: {r.status_code} {r.text}"
        detail = r.json().get("detail")
        assert detail["code"] == "BATCH_NOT_FOUND"

    # and a random id is also 404
    assert client.get(f"{API}/payments/batches/{uuid4()}/export?format=mt103", headers=h).status_code == 404


# —— 4. Unescaped input safety ——————————————————————————————————————————


def test_pain001_escapes_counterparty_special_chars(client, auth_headers):
    h = auth_headers
    hostile = 'A&B <C> "D" \'E\''
    cp = client.post(
        f"{API}/masterdata/counterparties",
        headers=h,
        json={"name": hostile, "type": "charterer"},
    ).json()
    assert cp["name"] == hostile
    _cp_bank(client, h, cp["id"], account_name=hostile)
    batch, _ = _mk_batch_with_payments(client, h, amounts=(1234.5,), counterparty_id=cp["id"])

    r = client.get(f"{API}/payments/batches/{batch['id']}/export?format=pain001", headers=h)
    assert r.status_code == 200, r.text
    # parses cleanly (would fail if raw & < > were injected unescaped)
    root = ET.fromstring(r.text)
    tx = root.find(f".//{{{PAIN_NS}}}CdtTrfTxInf")
    assert tx is not None
    cdtr_name = tx.findtext(f"{{{PAIN_NS}}}Cdtr/{{{PAIN_NS}}}Nm")
    assert cdtr_name == hostile
    # raw ampersand must not appear outside entities
    assert "A&B" not in r.text
    assert "A&amp;B" in r.text
    assert "&lt;C&gt;" in r.text
    # angle brackets from the name must not create extra elements
    assert root.find(f".//{{{PAIN_NS}}}C") is None

    # MT103 is plain text — name is included verbatim on one line
    r2 = client.get(f"{API}/payments/batches/{batch['id']}/export?format=mt103", headers=h)
    assert r2.status_code == 200
    assert hostile in r2.text


# —— 5. Unsupported format → 422 ————————————————————————————————————————


def test_unsupported_format_422(client, auth_headers):
    h = auth_headers
    batch, _ = _mk_batch_with_payments(client, h, amounts=(100.0,))
    for bad in ("swift999", "pain.001.001.09", "csv", ""):
        r = client.get(f"{API}/payments/batches/{batch['id']}/export?format={bad}", headers=h)
        assert r.status_code == 422, f"format={bad!r} → {r.status_code}"
        assert r.json()["detail"]["code"] == "EXPORT_FORMAT_UNSUPPORTED"


# —— 6. Deterministic output ————————————————————————————————————————————


def test_pain001_deterministic_same_bytes(client, auth_headers):
    h = auth_headers
    batch, _ = _mk_batch_with_payments(client, h, amounts=(500.0, 250.0))
    a = client.get(f"{API}/payments/batches/{batch['id']}/export?format=pain001", headers=h)
    b = client.get(f"{API}/payments/batches/{batch['id']}/export?format=pain001", headers=h)
    assert a.status_code == 200 and b.status_code == 200
    assert a.content == b.content
