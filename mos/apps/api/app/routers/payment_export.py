"""Payment batch bank-instruction exports — MT103-style text + ISO 20022 pain.001.001.03.

Best-effort human-readable bank files derived from payment batches:

- ``GET /payments/batches/{batch_id}/export?format=mt103``
  SWIFT-like field blocks (``:20:``/``:32A:``/``:50K:``/``:59:``/…). This is a
  readability aid for operators and banks that accept hand-checked files —
  it is **not** a full MT103 compliance engine (no network validation,
  no checksum blocks, no BIC registry lookup).
- ``GET /payments/batches/{batch_id}/export?format=pain001``
  ISO 20022 ``pain.001.001.03`` customer credit transfer init message.
  One ``<CdtTrfTxInf>`` per payment. Creditor/debtor bank details come from
  ``bank_accounts`` (own account = payer; counterparty account = payee),
  falling back to counterparty name / ``swift_code``.

All text going into the XML is escaped via :func:`xml.sax.saxutils.escape`;
output is deterministic for the same DB rows (timestamps derived from
``batch_date``, payments ordered by id).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Tenant
from app.models_domain import Invoice, Payment, PaymentBatch
from app.models_finance_ext import BankAccount
from app.models_wave1 import Counterparty
from app.security import AuthContext, require_module
from app.services.tenant_guard import scoped_get

router = APIRouter()

EXPORT_FORMATS = ("mt103", "pain001")
# bank_charge_mode → SWIFT :71A: / pain.001 ChrgBr
_CHARGE_SWIFT = {"shared": "SHA", "sender": "OUR", "receiver": "BEN"}
_CHARGE_PAIN = {"shared": "SHAR", "sender": "DEBT", "receiver": "CRED"}
_PAIN_NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"


# —— helpers ————————————————————————————————————————————————————————


def _amt(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _money_dot(value: Any) -> str:
    """ISO-style amount with '.' decimal separator, exactly 2 places."""
    return f"{_amt(value):.2f}"


def _money_swift(value: Any) -> str:
    """SWIFT amount with ',' decimal separator, exactly 2 places."""
    return f"{_amt(value):.2f}".replace(".", ",")


def _safe_filename_part(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", raw or "batch").strip("_") or "batch"


def _txt(value: Any, limit: int = 140) -> str:
    """Collapse newlines / trim — keep plain-text fields single-line."""
    return " ".join(str(value or "").split())[:limit]


def _swift_party_block(acct: str, name: str, address: str | None = None) -> list[str]:
    lines = [f"/{_txt(acct, 34)}", _txt(name, 34)]
    if address:
        lines.append(_txt(address, 34))
    return lines


def _own_bank_account(db: Session, tenant_id: UUID) -> BankAccount | None:
    """Payer account: own bank account (no counterparty link), default first."""
    rows = db.scalars(
        select(BankAccount)
        .where(BankAccount.tenant_id == tenant_id, BankAccount.counterparty_id.is_(None))
        .order_by(BankAccount.is_default.desc(), BankAccount.created_at.asc())
    ).all()
    return rows[0] if rows else None


def _creditor_bank_account(db: Session, tenant_id: UUID, counterparty_id: UUID | None) -> BankAccount | None:
    if counterparty_id is None:
        return None
    rows = db.scalars(
        select(BankAccount)
        .where(BankAccount.tenant_id == tenant_id, BankAccount.counterparty_id == counterparty_id)
        .order_by(BankAccount.is_default.desc(), BankAccount.created_at.asc())
    ).all()
    return rows[0] if rows else None


def _account_id_xml(acct: BankAccount | None) -> str:
    if acct is not None and acct.iban:
        return f"<Id><IBAN>{escape(acct.iban)}</IBAN></Id>"
    number = acct.account_number if acct is not None else None
    if number:
        return f"<Id><Othr><Id>{escape(number)}</Id></Othr></Id>"
    return "<Id><Othr><Id>N/A</Id></Othr></Id>"


def _bic_of(acct: BankAccount | None, fallback: str | None = None) -> str | None:
    if acct is not None and acct.swift_code:
        return acct.swift_code
    return fallback


class _Txn:
    """One exportable credit transfer (payment + invoice + party context)."""

    __slots__ = (
        "payment",
        "invoice",
        "counterparty",
        "creditor_acct",
        "end_to_end",
        "remittance",
        "amount",
        "currency",
    )

    def __init__(
        self,
        payment: Payment,
        invoice: Invoice | None,
        counterparty: Counterparty | None,
        creditor_acct: BankAccount | None,
    ) -> None:
        self.payment = payment
        self.invoice = invoice
        self.counterparty = counterparty
        self.creditor_acct = creditor_acct
        inv_no = invoice.invoice_no if invoice is not None else str(payment.invoice_id)
        self.end_to_end = _txt(payment.reference or inv_no, 35)
        self.remittance = _txt(f"{inv_no} {payment.reference or ''}".strip(), 140)
        self.amount = _amt(payment.amount)
        self.currency = (payment.currency or (invoice.currency if invoice else "USD") or "USD").upper()


def _load_txns(db: Session, tenant_id: UUID, batch_id: UUID) -> tuple[PaymentBatch, list[_Txn]]:
    batch = scoped_get(db, PaymentBatch, batch_id, tenant_id)
    if batch is None:
        raise HTTPException(404, detail={"code": "BATCH_NOT_FOUND", "message": str(batch_id)})
    payments = db.scalars(
        select(Payment)
        .where(Payment.tenant_id == tenant_id, Payment.batch_id == batch.id)
        .order_by(Payment.id.asc())
    ).all()
    txns: list[_Txn] = []
    for pay in payments:
        inv = scoped_get(db, Invoice, pay.invoice_id, tenant_id)
        cp = scoped_get(db, Counterparty, inv.counterparty_id, tenant_id) if inv and inv.counterparty_id else None
        creditor = _creditor_bank_account(db, tenant_id, inv.counterparty_id if inv else None)
        txns.append(_Txn(pay, inv, cp, creditor))
    return batch, txns


def _load_debtor(db: Session, tenant_id: UUID) -> tuple[Tenant | None, BankAccount | None]:
    # Tenant rows are keyed by their own id (no tenant_id column) — the caller's
    # auth.tenant_id already scopes this lookup to their own tenant row.
    tenant = db.get(Tenant, tenant_id)
    return tenant, _own_bank_account(db, tenant_id)


# —— MT103-style plain text ————————————————————————————————————————


def render_mt103(batch: PaymentBatch, txns: list[_Txn], tenant: Tenant | None, debtor: BankAccount | None) -> str:
    """Best-effort human-readable MT103-style text, one message per payment."""
    debtor_name = debtor.account_name if debtor else (tenant.name if tenant else "ORDERING CUSTOMER")
    debtor_acct = debtor.account_number if debtor else ""
    debtor_bic = _bic_of(debtor) or "BANKBEBB"
    value_date = batch.batch_date.strftime("%y%m%d")
    iso_date = batch.batch_date.isoformat()
    mode = batch.bank_charge_mode or "shared"
    charge = _CHARGE_SWIFT[mode] if mode in _CHARGE_SWIFT else "SHA"
    chunks: list[str] = []
    for idx, txn in enumerate(txns, start=1):
        ref = _txt(f"{batch.batch_number}-{idx}", 16)
        creditor = txn.creditor_acct
        creditor_name = creditor.account_name if creditor else (txn.counterparty.name if txn.counterparty else "BENEFICIARY")
        creditor_acct = creditor.account_number if creditor else ""
        creditor_bic = _bic_of(creditor, txn.counterparty.swift_code if txn.counterparty else None) or "BANKBEBB"
        cp_address = txn.counterparty.address if txn.counterparty else None
        lines = [
            "{1:F01MARIOSXXX0000000000}{2:I103" + debtor_bic[:8] + "XXXXN}{4:",
            f":20:{ref}",
            ":23B:CRED",
            f":32A:{value_date}{txn.currency}{_money_swift(txn.amount)}",
            ":50K:",
            *_swift_party_block(debtor_acct, debtor_name),
            f":52A:{debtor_bic[:8]}",
            f":57A:{creditor_bic[:8]}",
            ":59:",
            *_swift_party_block(creditor_acct, creditor_name, cp_address),
            f":70:{txn.remittance}",
            f":71A:{charge}",
            f":72:/INS/PAYMENT BATCH {batch.batch_number} {iso_date}",
            "-}",
        ]
        chunks.append("\n".join(lines))
    header = (
        f"{{1:F01MARIOSXXX0000000000}}{{2:I103{debtor_bic[:8]}XXXXN}}{{4:\n"
        f":20:{_txt(batch.batch_number, 16)}\n"
        f":32A:{value_date}{(batch.currency or 'USD').upper()}{_money_swift(batch.total_amount)}\n"
        f":72:/BNF/BATCH EXPORT {batch.batch_number} {iso_date} MTX{len(txns)}\n"
        "-}\n"
    )
    body = "\n\n".join(chunks)
    return (
        "MariOS MT103-style payment instruction (best-effort human-readable; "
        "not a full SWIFT compliance engine)\n"
        f"Batch: {batch.batch_number}  Date: {iso_date}  Currency: {batch.currency}  "
        f"Total: {_money_dot(batch.total_amount)}  Payments: {len(txns)}\n\n"
        f"{header}\n{body}\n"
    )


# —— ISO 20022 pain.001.001.03 ————————————————————————————————————————


def render_pain001(batch: PaymentBatch, txns: list[_Txn], tenant: Tenant | None, debtor: BankAccount | None) -> str:
    """Deterministic pain.001.001.03 XML; every free-text value is escaped."""
    msg_id = _txt(batch.batch_number, 35) or str(batch.id)
    cre_dt = f"{batch.batch_date.isoformat()}T00:00:00"
    req_date = batch.batch_date.isoformat()
    nb = str(len(txns))
    ctrl_sum = _money_dot(sum((t.amount for t in txns), Decimal("0")))
    debtor_name = debtor.account_name if debtor else (tenant.name if tenant else "ORDERING CUSTOMER")
    debtor_bic = _bic_of(debtor)
    debtor_addr = None
    debtor_xml = f"<Dbtr><Nm>{escape(_txt(debtor_name))}</Nm>"
    if debtor_addr:
        debtor_xml += f"<PstlAdr><AdrLine>{escape(_txt(debtor_addr))}</AdrLine></PstlAdr>"
    debtor_xml += "</Dbtr>"
    mode = batch.bank_charge_mode or "shared"
    chrg = _CHARGE_PAIN[mode] if mode in _CHARGE_PAIN else "SHAR"

    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<Document xmlns="{_PAIN_NS}">',
        "<CstmrCdtTrfInitn>",
        "<GrpHdr>",
        f"<MsgId>{escape(msg_id)}</MsgId>",
        f"<CreDtTm>{cre_dt}</CreDtTm>",
        f"<NbOfTxs>{nb}</NbOfTxs>",
        f"<CtrlSum>{ctrl_sum}</CtrlSum>",
        f"<InitgPty><Nm>{escape(_txt(tenant.name if tenant else debtor_name))}</Nm></InitgPty>",
        "</GrpHdr>",
        "<PmtInf>",
        f"<PmtInfId>{escape(msg_id)}</PmtInfId>",
        "<PmtMtd>TRF</PmtMtd>",
        "<BtchBookg>true</BtchBookg>",
        f"<NbOfTxs>{nb}</NbOfTxs>",
        f"<CtrlSum>{ctrl_sum}</CtrlSum>",
        f"<ReqdExctnDt>{req_date}</ReqdExctnDt>",
        debtor_xml,
        f"<DbtrAcct>{_account_id_xml(debtor)}</DbtrAcct>",
    ]
    if debtor_bic:
        parts.append(f"<DbtrAgt><FinInstnId><BIC>{escape(debtor_bic)}</BIC></FinInstnId></DbtrAgt>")
    else:
        parts.append("<DbtrAgt><FinInstnId><Othr><Id>N/A</Id></Othr></FinInstnId></DbtrAgt>")
    parts.append(f"<ChrgBr>{chrg}</ChrgBr>")

    for txn in txns:
        creditor = txn.creditor_acct
        cp = txn.counterparty
        c_name = creditor.account_name if creditor else (cp.name if cp else "BENEFICIARY")
        c_bic = _bic_of(creditor, cp.swift_code if cp else None)
        parts.append("<CdtTrfTxInf>")
        parts.append(
            "<PmtId>"
            f"<InstrId>{escape(_txt(f'{msg_id}-{txn.payment.id}', 35))}</InstrId>"
            f"<EndToEndId>{escape(txn.end_to_end)}</EndToEndId>"
            "</PmtId>"
        )
        parts.append(f'<Amt><InstdAmt Ccy="{escape(txn.currency)}">{_money_dot(txn.amount)}</InstdAmt></Amt>')
        if c_bic:
            parts.append(f"<CdtrAgt><FinInstnId><BIC>{escape(c_bic)}</BIC></FinInstnId></CdtrAgt>")
        parts.append(f"<Cdtr><Nm>{escape(_txt(c_name))}</Nm></Cdtr>")
        parts.append(f"<CdtrAcct>{_account_id_xml(creditor)}</CdtrAcct>")
        parts.append(f"<RmtInf><Ustrd>{escape(txn.remittance)}</Ustrd></RmtInf>")
        parts.append("</CdtTrfTxInf>")

    parts.extend(["</PmtInf>", "</CstmrCdtTrfInitn>", "</Document>"])
    return "\n".join(parts) + "\n"


# —— route ————————————————————————————————————————————————————————


@router.get("/payments/batches/{batch_id}/export")
def export_payment_batch(
    batch_id: UUID,
    format: str = Query("pain001", description="mt103 | pain001"),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """Export a payment batch as an MT103-style text file or pain.001.001.03 XML.

    Tenant-scoped: a batch belonging to another tenant is indistinguishable
    from a missing batch (404).
    """
    fmt = (format or "").strip().lower()
    if fmt not in EXPORT_FORMATS:
        raise HTTPException(
            422,
            detail={
                "code": "EXPORT_FORMAT_UNSUPPORTED",
                "format": format,
                "supported": list(EXPORT_FORMATS),
            },
        )
    batch, txns = _load_txns(db, auth.tenant_id, batch_id)
    tenant, debtor = _load_debtor(db, auth.tenant_id)

    stamp = date.today().strftime("%Y%m%d")
    entity = _safe_filename_part(f"payment_batch_{batch.batch_number}")
    if fmt == "mt103":
        content = render_mt103(batch, txns, tenant, debtor)
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{entity}_{stamp}.mt103.txt"'},
        )
    content = render_pain001(batch, txns, tenant, debtor)
    return Response(
        content=content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{entity}_{stamp}.pain001.xml"'},
    )
