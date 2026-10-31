"""系统动作目录 —— "任务绑定系统动作，动作做完任务自动勾完成"的注册表。

这是一个**代码级**注册表（不是新表）：动作是系统里已经存在的业务事实，
目录只负责描述"有哪些动作可以绑定到任务上、做完怎么判定、什么时候会完成"。

每条动作：

.. code-block:: python

    ActionSpec(
        code="invoice.issue",          # 动作码（写进 tasks.action_code）
        module="finance",              # 归属模块（前端分组 / 模块许可提示）
        entity_type="invoice",         # 判定时按哪个实体类型去查
        label_key="task.action.invoice_issue",   # i18n 文案键
        detector=...,                  # 判定器：(db, tenant_id, entity) -> bool
        event_kinds=("invoice.issued",),  # 触发该动作完成的域事件（即时勾选通道）
        default_role="finance",        # 默认承接角色
        default_weight=Decimal("1"),   # 默认权重（进度加权）
        default_due_days=3,            # 默认时限
        href="/finance/invoices",      # 前端深链
        severity="warn",               # info | warn | critical
    )

**判定器是纯只读函数**，直接复用业务侧已有的判定逻辑 —— 收尾清单的 8 个谓词
抽到了 :mod:`app.services.closeout_checks`，动作目录直接调用它们，
所以"清单说好了"与"任务自动勾掉"永远是同一份真相。

**事件即时通道**：动作登记的 ``event_kinds`` 命中时，域事件处理器立刻勾掉
对应的任务（``services/task_completion.on_domain_event``）。
**判定器兜底通道**：没有发事件的动作（如手工改了单据状态），靠惰性刷新
与定时 tick 跑判定器补上。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import (
    BunkerOrder,
    CharterAmendment,
    Claim,
    CoaLifting,
    Invoice,
    LaytimeCalc,
    PortCall,
    PortDisbursement,
    Voyage,
)
from app.models_ship import ShipCertificate
from app.services.closeout_checks import (
    accruals_state,
    bunker_state,
    claims_state,
    invoices_state,
    laytime_state,
    port_calls_state,
    sof_state,
)

#: 动作的英文名（前端 i18n 键的兜底文案；中文走 UI_MESSAGES_PARITY）
ACTION_LABELS_EN: dict[str, str] = {
    "voyage.closeout.port_calls": "Close out port calls",
    "voyage.closeout.sof": "Close out statement of facts",
    "voyage.closeout.laytime": "Close out laytime calculation",
    "voyage.closeout.claims": "Close out claims",
    "voyage.closeout.invoices": "Close out invoices",
    "voyage.closeout.bunker": "Close out bunker delivery",
    "voyage.closeout.accruals": "Reconcile voyage accruals",
    "voyage.complete": "Complete the voyage",
    "voyage.nor.record": "Record the notice of readiness",
    "invoice.issue": "Issue the invoice",
    "invoice.post_gl": "Post the invoice to the general ledger",
    "invoice.payment.record": "Record the invoice payment",
    "laytime.finalize": "Finalize the laytime calculation",
    "claim.settle": "Settle the claim",
    "pda.close": "Close the port disbursement account",
    "bunker.delivery_reconcile": "Reconcile bunker delivery",
    "charter.amendment_review": "Review the charter amendment",
    "coa.lifting.reconcile": "Reconcile the lifting quantity",
    "cert.renew": "Renew the certificate",
}


# 判定器签名：(db, tenant_id, entity) -> bool
Detector = Callable[[Session, UUID, object], bool]


@dataclass(frozen=True)
class ActionSpec:
    """一条系统动作。"""

    code: str
    module: str
    entity_type: str
    label_key: str
    detector: Detector
    event_kinds: tuple[str, ...] = ()
    default_role: str | None = None
    default_weight: Decimal = Decimal("1")
    default_due_days: int = 3
    href: str = "/tasks"
    severity: str = "warn"
    # 描述该动作"做完"意味着什么（i18n 键，前端在绑定时展示）
    hint_key: str = ""
    # 该动作绑定的任务，其 entity_type 必须与此一致（前端绑定时校验）
    matches: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "module": self.module,
            "entity_type": self.entity_type,
            "label_key": self.label_key,
            "label": ACTION_LABELS_EN.get(self.code, self.code),
            "event_kinds": list(self.event_kinds),
            "default_role": self.default_role,
            "default_weight": float(self.default_weight),
            "default_due_days": self.default_due_days,
            "href": self.href,
            "severity": self.severity,
            "hint_key": self.hint_key,
            "matches": list(self.matches),
        }


# ── 判定器 ────────────────────────────────────────────────────────────────


def _voyage(db: Session, tenant_id: UUID, entity) -> Voyage | None:
    if not isinstance(entity, Voyage):
        entity = db.get(Voyage, getattr(entity, "id", entity))
    if entity is None or entity.tenant_id != tenant_id:
        return None
    return entity


def _det_voyage_port_calls(db: Session, tenant_id: UUID, entity) -> bool:
    v = _voyage(db, tenant_id, entity)
    return bool(v) and port_calls_state(db, tenant_id, v.id)["ok"]


def _det_voyage_sof(db: Session, tenant_id: UUID, entity) -> bool:
    v = _voyage(db, tenant_id, entity)
    return bool(v) and sof_state(db, tenant_id, v.id)["ok"]


def _det_voyage_laytime(db: Session, tenant_id: UUID, entity) -> bool:
    v = _voyage(db, tenant_id, entity)
    return bool(v) and laytime_state(db, tenant_id, v.id)["ok"]


def _det_voyage_claims(db: Session, tenant_id: UUID, entity) -> bool:
    v = _voyage(db, tenant_id, entity)
    return bool(v) and claims_state(db, tenant_id, v.id)["ok"]


def _det_voyage_invoices(db: Session, tenant_id: UUID, entity) -> bool:
    v = _voyage(db, tenant_id, entity)
    return bool(v) and invoices_state(db, tenant_id, v.id)["ok"]


def _det_voyage_bunker(db: Session, tenant_id: UUID, entity) -> bool:
    v = _voyage(db, tenant_id, entity)
    return bool(v) and bunker_state(db, tenant_id, v.id)["ok"]


def _det_voyage_accruals(db: Session, tenant_id: UUID, entity) -> bool:
    v = _voyage(db, tenant_id, entity)
    return bool(v) and accruals_state(db, tenant_id, v.id)["ok"]


def _det_voyage_completed(db: Session, tenant_id: UUID, entity) -> bool:
    v = _voyage(db, tenant_id, entity)
    return bool(v) and v.status == "completed"


def _det_voyage_nor(db: Session, tenant_id: UUID, entity) -> bool:
    v = _voyage(db, tenant_id, entity)
    if not v:
        return False
    return (
        db.scalar(
            select(PortCall.id).where(
                PortCall.tenant_id == tenant_id,
                PortCall.voyage_id == v.id,
                PortCall.nor_at.is_not(None),
                PortCall.deleted_at.is_(None),
            ).limit(1)
        )
        is not None
    )


def _det_invoice_issued(db: Session, tenant_id: UUID, entity) -> bool:
    inv = entity if isinstance(entity, Invoice) else db.get(Invoice, getattr(entity, "id", entity))
    return bool(inv) and inv.tenant_id == tenant_id and inv.status in ("issued", "partially_paid", "paid")


def _det_invoice_gl_posted(db: Session, tenant_id: UUID, entity) -> bool:
    inv = entity if isinstance(entity, Invoice) else db.get(Invoice, getattr(entity, "id", entity))
    return bool(inv) and inv.tenant_id == tenant_id and bool(inv.gl_posted)


def _det_invoice_paid(db: Session, tenant_id: UUID, entity) -> bool:
    inv = entity if isinstance(entity, Invoice) else db.get(Invoice, getattr(entity, "id", entity))
    if not inv or inv.tenant_id != tenant_id:
        return False
    from app.models_domain import Payment

    return (
        db.scalar(
            select(Payment.id).where(Payment.tenant_id == tenant_id, Payment.invoice_id == inv.id).limit(1)
        )
        is not None
    )


def _det_laytime_finalized(db: Session, tenant_id: UUID, entity) -> bool:
    lt = entity if isinstance(entity, LaytimeCalc) else db.get(LaytimeCalc, getattr(entity, "id", entity))
    return bool(lt) and lt.tenant_id == tenant_id and (lt.status == "finalized" or lt.finalized_at is not None)


def _det_claim_settled(db: Session, tenant_id: UUID, entity) -> bool:
    cl = entity if isinstance(entity, Claim) else db.get(Claim, getattr(entity, "id", entity))
    return bool(cl) and cl.tenant_id == tenant_id and cl.status in ("settled", "withdrawn")


def _det_pda_closed(db: Session, tenant_id: UUID, entity) -> bool:
    pda = entity if isinstance(entity, PortDisbursement) else db.get(
        PortDisbursement, getattr(entity, "id", entity)
    )
    return bool(pda) and pda.tenant_id == tenant_id and pda.status == "closed"


def _det_bunker_delivered(db: Session, tenant_id: UUID, entity) -> bool:
    bo = entity if isinstance(entity, BunkerOrder) else db.get(BunkerOrder, getattr(entity, "id", entity))
    return bool(bo) and bo.tenant_id == tenant_id and bo.status == "delivered"


def _det_amendment_approved(db: Session, tenant_id: UUID, entity) -> bool:
    amd = entity if isinstance(entity, CharterAmendment) else db.get(
        CharterAmendment, getattr(entity, "id", entity)
    )
    return bool(amd) and amd.tenant_id == tenant_id and amd.status == "approved"


def _det_lifting_fixed(db: Session, tenant_id: UUID, entity) -> bool:
    lift = entity if isinstance(entity, CoaLifting) else db.get(CoaLifting, getattr(entity, "id", entity))
    return bool(lift) and lift.tenant_id == tenant_id and lift.status in ("fixed", "completed")


def _det_cert_renewed(db: Session, tenant_id: UUID, entity) -> bool:
    """证书已续期（有效期已推后且仍在有效期内）。"""
    cert = entity if isinstance(entity, ShipCertificate) else db.get(
        ShipCertificate, getattr(entity, "id", entity)
    )
    if not cert or cert.tenant_id != tenant_id:
        return False
    from datetime import date

    if cert.expires_on is None:
        return False
    return cert.expires_on >= date.today() and cert.status in ("valid", "expiring")


# ── 动作目录 ──────────────────────────────────────────────────────────────

ACTIONS: tuple[ActionSpec, ...] = (
    # —— 航次收尾（判定与收尾清单同一份真相）——
    ActionSpec(
        code="voyage.closeout.port_calls",
        module="operations",
        entity_type="voyage",
        label_key="task.action.voyage_closeout_port_calls",
        hint_key="task.action.hint.voyage_closeout_port_calls",
        detector=_det_voyage_port_calls,
        event_kinds=(),
        default_role="operations",
        default_due_days=1,
        href="/operations",
        severity="warn",
    ),
    ActionSpec(
        code="voyage.closeout.sof",
        module="operations",
        entity_type="voyage",
        label_key="task.action.voyage_closeout_sof",
        hint_key="task.action.hint.voyage_closeout_sof",
        detector=_det_voyage_sof,
        event_kinds=(),
        default_role="operations",
        default_due_days=1,
        href="/operations",
        severity="warn",
    ),
    ActionSpec(
        code="voyage.closeout.laytime",
        module="operations",
        entity_type="voyage",
        label_key="task.action.voyage_closeout_laytime",
        hint_key="task.action.hint.voyage_closeout_laytime",
        detector=_det_voyage_laytime,
        event_kinds=("laytime.draft_created",),
        default_role="operations",
        default_due_days=3,
        href="/operations",
        severity="warn",
    ),
    ActionSpec(
        code="voyage.closeout.claims",
        module="claims",
        entity_type="voyage",
        label_key="task.action.voyage_closeout_claims",
        hint_key="task.action.hint.voyage_closeout_claims",
        detector=_det_voyage_claims,
        event_kinds=("claim.settled",),
        default_role="claims",
        default_due_days=5,
        href="/claims",
        severity="warn",
    ),
    ActionSpec(
        code="voyage.closeout.invoices",
        module="finance",
        entity_type="voyage",
        label_key="task.action.voyage_closeout_invoices",
        hint_key="task.action.hint.voyage_closeout_invoices",
        detector=_det_voyage_invoices,
        event_kinds=("invoice.issued",),
        default_role="finance",
        default_due_days=3,
        href="/finance/invoices",
        severity="warn",
    ),
    ActionSpec(
        code="voyage.closeout.bunker",
        module="operations",
        entity_type="voyage",
        label_key="task.action.voyage_closeout_bunker",
        hint_key="task.action.hint.voyage_closeout_bunker",
        detector=_det_voyage_bunker,
        event_kinds=("bunker.delivered",),
        default_role="operations",
        default_due_days=2,
        href="/bunker",
        severity="warn",
    ),
    ActionSpec(
        code="voyage.closeout.accruals",
        module="finance",
        entity_type="voyage",
        label_key="task.action.voyage_closeout_accruals",
        hint_key="task.action.hint.voyage_closeout_accruals",
        detector=_det_voyage_accruals,
        event_kinds=(),
        default_role="finance",
        default_due_days=5,
        href="/finance",
        severity="warn",
    ),
    # —— 单据动作 ——
    ActionSpec(
        code="voyage.complete",
        module="operations",
        entity_type="voyage",
        label_key="task.action.voyage_complete",
        hint_key="task.action.hint.voyage_complete",
        detector=_det_voyage_completed,
        event_kinds=("voyage.completed",),
        default_role="operations",
        default_due_days=3,
        href="/operations",
        severity="warn",
    ),
    ActionSpec(
        code="voyage.nor.record",
        module="operations",
        entity_type="voyage",
        label_key="task.action.voyage_nor_record",
        hint_key="task.action.hint.voyage_nor_record",
        detector=_det_voyage_nor,
        event_kinds=("portcall.nor_updated",),
        default_role="operations",
        default_due_days=1,
        href="/operations",
        severity="info",
    ),
    ActionSpec(
        code="invoice.issue",
        module="finance",
        entity_type="invoice",
        label_key="task.action.invoice_issue",
        hint_key="task.action.hint.invoice_issue",
        detector=_det_invoice_issued,
        event_kinds=("invoice.issued",),
        default_role="finance",
        default_due_days=3,
        href="/finance/invoices",
        severity="warn",
    ),
    ActionSpec(
        code="invoice.post_gl",
        module="finance",
        entity_type="invoice",
        label_key="task.action.invoice_post_gl",
        hint_key="task.action.hint.invoice_post_gl",
        detector=_det_invoice_gl_posted,
        event_kinds=(),
        default_role="finance",
        default_due_days=3,
        href="/finance/gl",
        severity="warn",
    ),
    ActionSpec(
        code="invoice.payment.record",
        module="finance",
        entity_type="invoice",
        label_key="task.action.invoice_payment_record",
        hint_key="task.action.hint.invoice_payment_record",
        detector=_det_invoice_paid,
        event_kinds=(),
        default_role="finance",
        default_due_days=5,
        href="/finance/invoices",
        severity="info",
    ),
    ActionSpec(
        code="laytime.finalize",
        module="operations",
        entity_type="laytime",
        label_key="task.action.laytime_finalize",
        hint_key="task.action.hint.laytime_finalize",
        detector=_det_laytime_finalized,
        event_kinds=("laytime.draft_created",),
        default_role="operations",
        default_due_days=3,
        href="/finance/laytimes",
        severity="warn",
    ),
    ActionSpec(
        code="claim.settle",
        module="claims",
        entity_type="claim",
        label_key="task.action.claim_settle",
        hint_key="task.action.hint.claim_settle",
        detector=_det_claim_settled,
        event_kinds=("claim.settled",),
        default_role="claims",
        default_due_days=5,
        href="/claims",
        severity="warn",
    ),
    ActionSpec(
        code="pda.close",
        module="finance",
        entity_type="port_disbursement",
        label_key="task.action.pda_close",
        hint_key="task.action.hint.pda_close",
        detector=_det_pda_closed,
        event_kinds=("pda.closed",),
        default_role="finance",
        default_due_days=3,
        href="/finance",
        severity="warn",
    ),
    ActionSpec(
        code="bunker.delivery_reconcile",
        module="operations",
        entity_type="bunker_order",
        label_key="task.action.bunker_delivery_reconcile",
        hint_key="task.action.hint.bunker_delivery_reconcile",
        detector=_det_bunker_delivered,
        event_kinds=("bunker.delivered",),
        default_role="operations",
        default_due_days=2,
        href="/bunker",
        severity="warn",
    ),
    ActionSpec(
        code="charter.amendment_review",
        module="chartering",
        entity_type="charter_amendment",
        label_key="task.action.charter_amendment_review",
        hint_key="task.action.hint.charter_amendment_review",
        detector=_det_amendment_approved,
        event_kinds=("charter.amendment_approved",),
        default_role="chartering",
        default_due_days=3,
        href="/charters",
        severity="warn",
    ),
    ActionSpec(
        code="coa.lifting.reconcile",
        module="chartering",
        entity_type="coa_lifting",
        label_key="task.action.coa_lifting_reconcile",
        hint_key="task.action.hint.coa_lifting_reconcile",
        detector=_det_lifting_fixed,
        event_kinds=("lifting.fixed", "lifting.completed"),
        default_role="chartering",
        default_due_days=3,
        href="/charters",
        severity="warn",
    ),
    ActionSpec(
        code="cert.renew",
        module="technical",
        entity_type="ship_certificate",
        label_key="task.action.cert_renew",
        hint_key="task.action.hint.cert_renew",
        detector=_det_cert_renewed,
        event_kinds=(),
        default_role="operations",
        default_due_days=30,
        href="/technical",
        severity="warn",
    ),
)

ACTION_BY_CODE: dict[str, ActionSpec] = {a.code: a for a in ACTIONS}


def get_action(code: str | None) -> ActionSpec | None:
    if not code:
        return None
    return ACTION_BY_CODE.get(code)


def catalog_payload() -> list[dict]:
    """给前端的动作目录（按模块分组由前端做）。"""
    return [a.as_dict() for a in ACTIONS]


def actions_for_event(kind: str) -> list[ActionSpec]:
    """登记了该域事件的动作（事件即时通道）。"""
    return [a for a in ACTIONS if kind in a.event_kinds]
