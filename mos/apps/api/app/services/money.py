"""金额口径单一真源（WP-1 · P0-B2/B4/B5/B6/B7）。

**为什么有这个模块**：同一张发票的"总额/未收"在系统里有五套算法：

- 单笔收款 :func:`app.services.finance_workflow.record_payment` → ``amount + tax − paid``
- 付款批次 :func:`app.services.payment_batch.create_batch` → ``amount − paid``（**漏税**）
- 账龄     :func:`app.routers.invoices.aging` → ``amount + tax − paid``
- 客户授信 :func:`app.services.counterparty_credit` → ``amount + tax − paid``
- CSV 导出 :func:`app.routers.exports` → 只导 ``amount``（**漏税**）

批次那条会把有税发票少付一笔税，CSV 那条让客户对不上账。这里把口径收拢到
一个模块，所有链路都从这里取数：**总额 = 金额 + 税**，**未收 = 总额 − 已收**。

红冲（credit note）在 P0-B2 之后是**一张负数 Invoice 行**，所以"未收"天然相抵，
不需要在每条链路上再减一次红冲 —— 减两次才是错的。

所有金额一律 ``Decimal`` + **显式** ``ROUND_HALF_UP``。裸 ``.quantize()`` 用的是
默认的 HALF_EVEN（银行家舍入），和系统里其余 60 处显式写法不一致，会让 0.005
在两条链路上算出两个结果 —— 本模块禁止裸 quantize。
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

#: 分（0.01）—— 与数据库 ``Numeric(18, 2)`` 对齐。
CENT = Decimal("0.01")
ZERO = Decimal("0")

#: 计入实际损益的发票状态（草稿/审批中/作废/已删都不算）。
REVENUE_STATUSES: tuple[str, ...] = ("issued", "partially_paid", "paid")
#: 计入未收账龄的发票状态。
OPEN_STATUSES: tuple[str, ...] = ("issued", "partially_paid")

#: 规范发票类型 → 损益行（见 ``app.services.pnl`` 的 P&L 行映射）。
#: PDA/FDA/BKR 故意**不**映射 —— 这些成本来自 PDA/油订单，再计一次会双算。
REVENUE_SIDE_TYPES: frozenset[str] = frozenset({"FRT", "TCIP", "TCOB", "DEM"})
PAYABLE_SIDE_TYPES: frozenset[str] = frozenset({"PDA", "FDA", "BKR", "XEXP"})

#: 缺汇率时的错误码 —— **fail closed** 的统一口径（外币单据没有汇率不许落库）。
FX_RATE_NOT_FOUND = "FX_RATE_NOT_FOUND"

#: 汇兑差异（``XDIFF``）—— 审计 P1-B15：以前它**两边都不属于**，
#: 于是 ``is_revenue_side`` 落到"未知类型按收入侧"的兜底分支，
#: ``gl_engine._is_revenue_type`` 却落到成本侧分支 —— 两边判定不一致，
#: 业务规则选出来的科目被静默丢弃（分录按默认 AR/收入入账）。
#:
#: 现在显式归类：汇兑差异是**重估**（gain 为正、loss 为负，金额带符号），
#: 走收入侧口径 —— 正数是汇兑收益、负数是汇兑损失，两者都体现在损益里。
#: 想要独立的"汇兑损益"科目，租户可以在 BusinessRule 里配。
EXCHANGE_DIFFERENCE_TYPES: frozenset[str] = frozenset({"XDIFF"})


def money(value) -> Decimal:
    """任意数值 → 两位小数 Decimal（ROUND_HALF_UP）。

    ``None`` → 0。接受 ``Decimal``/``int``/``float``/``str``。
    """
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def dec(value) -> Decimal:
    """转 Decimal 但**不**做分位舍入（用于比率、天数这类非金额量）。"""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places: int = 2) -> Decimal:
    """显式 ROUND_HALF_UP 量化 —— 取代 Python 内建 ``round()``。

    内建 ``round()`` 走的是**银行家舍入**（``.5`` 往偶数靠），与本系统
    统一的「四舍五入」口径不一致：金额上就是 1 分钱的差，比率/吨位这类
    非金额量上也会和单据、报表对不上。所有出口都走这个函数。

    ``places`` = 小数位数（2 = 分）。
    """
    if value is None:
        return ZERO
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def allocate_by_weight(total, weights) -> list[Decimal]:
    """按权重把 ``total`` 分成若干份，**分位之和精确等于 total**。

    逐份四舍五入会差分：3 船平分 1,000,000.00 各得 333,333.33，
    Σ = 999,999.99 —— 少一分钱，池期结算对不上（审计 P2-B1）。

    这里用「最大余数法」：先按精确比例取整分（截断），余下的分/减分给
    小数部分最大的那几份。**结果之和恒等于 total**（差 0 是硬保证）。
    """
    total = money(total)
    w = [dec(x) for x in weights]
    if not w:
        return []
    tw = sum(w, ZERO)
    if tw <= 0:
        # 没有权重（全是 0 分）→ 平均分给每一份，而不是全给最后一份
        w = [Decimal("1")] * len(w)
        tw = Decimal(str(len(w)))

    total_cents = int((total * 100).to_integral_value())
    raw = [Decimal(total_cents) * x / tw for x in w]
    # 截断到分（ROUND_DOWN 对负数是朝零截断，与「先取整再补余数」一致）
    base = [int(r.to_integral_value(rounding=ROUND_DOWN)) for r in raw]
    remainder = total_cents - sum(base)

    if remainder:
        # 小数部分大的优先（remainder 为负时反序，等价于减 1 分）
        frac = [r - Decimal(b) for r, b in zip(raw, base)]
        order = sorted(range(len(w)), key=lambda i: (-frac[i], i))
        step = 1 if remainder > 0 else -1
        for k in range(abs(remainder)):
            base[order[k % len(order)]] += step
    return [money(Decimal(c) / Decimal(100)) for c in base]


# —— 汇率（FX）————————————————————————————————————————————————

class FxRateUnavailable(Exception):
    """取不到 原币→本币 的汇率。

    **fail closed 的信号**：调用方必须拒绝这笔单据（或把结论标成"无法评估"），
    绝不能按 1:1 记账 —— 外币金额按本币直接入账是**错的钱**。
    """

    def __init__(self, currency: str, base_currency: str, message: str | None = None):
        self.currency = currency
        self.base_currency = base_currency
        super().__init__(
            message
            or f"No FX rate {currency}→{base_currency} available; supply fx_rate explicitly"
        )


def require_fx_rate(
    db,
    tenant_id,
    currency: str,
    base_currency: str,
    *,
    invoice_type: str | None = None,
    context_date=None,
) -> Decimal:
    """取 原币→本币 汇率；**取不到就抛** :class:`FxRateUnavailable`。

    - 本币（``currency == base_currency``）→ 汇率恒为 1（单币种租户没有汇率行）。
    - 外币 → 走 :func:`app.services.fx_date_rules.resolve_fx_rate`（取价日规则
      的唯一真源：给了 ``context_date`` 就取该日期当时有效的汇率）。

    与 ``app.routers.invoices.create_invoice`` 用的是同一个取价口径，只是这里
    把"取不到"表达成异常，让**每个**外币入口都必须显式处理 fail-closed 分支。
    """
    cur = (currency or "").upper()
    base = (base_currency or "").upper()
    if not cur or cur == base:
        return Decimal("1")
    from app.services.fx_date_rules import resolve_fx_rate

    rate = resolve_fx_rate(
        db,
        tenant_id,
        cur,
        base,
        invoice_type=invoice_type,
        context_date=context_date,
    )
    if rate is None or Decimal(str(rate)) <= 0:
        raise FxRateUnavailable(cur, base)
    return Decimal(str(rate))


def to_base_amount(amount, fx_rate) -> Decimal:
    """原币金额按汇率折成本位币（基准金额口径的一半：金额 × 汇率）。"""
    return money(money(amount) * dec(fx_rate))


# —— 发票口径 ————————————————————————————————————————————————

def invoice_amount(inv) -> Decimal:
    """发票金额（税前）。"""
    return money(getattr(inv, "amount", None) or 0)


def invoice_tax(inv) -> Decimal:
    """发票税额。"""
    return money(getattr(inv, "tax_amount", None) or 0)


def invoice_gross(inv) -> Decimal:
    """发票总额 = 金额 + 税。**唯一**的"这张发票值多少钱"口径。"""
    return money(invoice_amount(inv) + invoice_tax(inv))


def invoice_paid(inv) -> Decimal:
    """已收金额。"""
    return money(getattr(inv, "paid_amount", None) or 0)


def invoice_open(inv) -> Decimal:
    """未收金额 = 总额 − 已收。

    红冲发票本身金额为负，所以它的未收是负数 —— 与原发票相加天然相抵。
    """
    return money(invoice_gross(inv) - invoice_paid(inv))


def invoice_rate(inv) -> Decimal | None:
    """发票上的汇率（原币 → 本位币），没有则 None。"""
    rate = getattr(inv, "fx_rate", None)
    if rate is None:
        return None
    try:
        d = Decimal(str(rate))
    except Exception:  # noqa: BLE001 — 脏数据不应让整页崩掉
        return None
    return d if d > 0 else None


def invoice_base_gross(inv) -> Decimal:
    """本本位币总额 = 本位币税前金额 + 本位币税额。

    **与 :func:`invoice_base_amount` 共用同一条基准金额口径**（P1-B10）：

    - 有 ``base_amount`` → 用它（它存的就是税前金额的本位币值）；
    - 没有 ``base_amount`` 但有 ``fx_rate`` → 原币金额 × 汇率；
    - 两者都没有 → 原币金额（单币种租户）。

    以前这里直接 ``(金额 + 税) × 汇率``，而税前口径（``invoice_base_amount``）
    漏掉了汇率 —— 同一张外币发票在损益（P&L 走税前）和总账（GL 走含税）里
    给出两个不同的本币数，账实不符。现在两者都由同一段代码推导。
    """
    return money(invoice_base_amount(inv) + invoice_base_tax(inv))


def invoice_base_tax(inv) -> Decimal:
    """本位币税额（按发票汇率折算；没有汇率则按原币）。"""
    tax = invoice_tax(inv)
    rate = invoice_rate(inv)
    if tax and rate:
        return money(tax * rate)
    return tax


def invoice_base_paid(inv) -> Decimal:
    """本币已收金额（按发票汇率折算）。"""
    paid = invoice_paid(inv)
    rate = invoice_rate(inv)
    if rate and paid:
        return money(paid * rate)
    return paid


def invoice_base_open(inv) -> Decimal:
    """本币未收金额。"""
    return money(invoice_base_gross(inv) - invoice_base_paid(inv))


def invoice_base_amount(inv) -> Decimal:
    """本位币**税前**金额 —— 损益口径的收入（增值税是负债，不进收入）。

    **基准金额口径（P1-B10，SSOT）**：

    1. 发票上存了 ``base_amount`` → 用它（它就是税前金额的本位币值）；
    2. 没存 ``base_amount`` 但有 ``fx_rate`` → ``金额 × 汇率``；
    3. 两者都没有 → 原币金额（单币种租户，本币单据）。

    第 2 条以前是漏的：外币发票没有 ``base_amount`` 时这里原样返回原币金额，
    于是损益（P&L）按原币记账、总账（GL 走 ``invoice_base_gross``）按本币
    记账 —— 同一张票两个数。:func:`invoice_base_gross` 现在按同一条规则推导，
    两个口径必然一致。
    """
    base = getattr(inv, "base_amount", None)
    if base is not None:
        return money(base)
    rate = invoice_rate(inv)
    amount = invoice_amount(inv)
    if rate:
        return money(amount * rate)
    return amount


def invoice_gross_before_commission(inv, address_pct=None) -> Decimal:
    """扣佣金**之前**的金额（本位币）。

    净额发票（``commission_basis="net"``）的金额里已经扣掉了地址佣金，
    要算佣金基数就得回到扣佣之前的毛额：

    1. ``meta.hire.gross_amount`` 快照优先（最准）；
    2. 没有快照时按 ``净额 ÷ (1 − 地址佣金率)`` 反推（与
       ``services.commission._commission_base`` 同一算法）；
    3. 都没有就退回发票金额本身。

    ``address_pct`` 是百分数（``2.5`` = 2.5%），由调用方从租约传入。
    """
    if invoice_commission_basis(inv) != "net":
        return invoice_base_amount(inv)
    meta = getattr(inv, "meta", None)
    if isinstance(meta, dict):
        hire = meta.get("hire")
        if isinstance(hire, dict) and hire.get("gross_amount") is not None:
            return invoice_to_base(inv, hire["gross_amount"])
    net = invoice_base_amount(inv)
    pct = dec(address_pct)
    if pct > 0 and pct < Decimal("100"):
        return money(net / (Decimal("1") - pct / Decimal("100")))
    return net


def invoice_to_base(inv, amount) -> Decimal:
    """把原币金额按发票上的汇率折成本位币。

    优先用 ``fx_rate``；没有汇率但有 ``base_amount`` 时按金额比例折算
    （老数据里外币发票可能存了 base_amount 却没存 fx_rate）；都没有就原样返回。

    注意与 :func:`invoice_base_amount` 的分工：那个函数算的是**发票自身的**
    本位币金额（口径 = 存的 base_amount，否则 金额 × 汇率）；本函数算的是
    **任意一个**原币金额的本位币值，所以这里优先用汇率（比按 base_amount
    反推的比例更精确）。
    """
    amt = money(amount)
    rate = invoice_rate(inv)
    if rate:
        return money(amt * rate)
    base = getattr(inv, "base_amount", None)
    orig = invoice_amount(inv)
    if base is not None and orig:
        return money(Decimal(str(base)) * amt / orig)
    return amt


def invoice_type_code(inv) -> str:
    """发票类型 → 规范码（``FRT``/``TCIP``/…）；无法识别时返回原值大写。

    历史行可能存了任意自由文本，这里**不抛异常**，只是拿不到规范码。
    """
    raw = str(getattr(inv, "invoice_type", "") or "").strip()
    if not raw:
        return ""
    from app.services.invoice_types import normalize_invoice_type

    try:
        return normalize_invoice_type(raw)
    except ValueError:
        return raw.upper()


def is_credit_note(inv) -> bool:
    """是否是红冲单据（负数发票行）。"""
    return invoice_type_code(inv) == "XREV"


def invoice_commission_basis(inv) -> str:
    """发票金额是否**已扣**佣金：``"net"`` | ``"gross"``。

    优先读 ``Invoice.commission_basis``（net|gross）；老数据没有这个字段时
    从 ``meta.hire`` 快照推断（``hire_schedule`` 生成的租金发票一直是净额）。
    都没有则按 ``"gross"``（历史 P&L 行为：佣金另算一行成本）。

    **为什么重要**：地址佣金按航运惯例是从租金/运费里**扣**的，发票金额是净额。
    如果 P&L 再按同一笔收入算一次佣金成本，就是重复计佣（P1-B1）。
    """
    raw = str(getattr(inv, "commission_basis", "") or "").strip().lower()
    if raw in {"net", "gross"}:
        return raw
    meta = getattr(inv, "meta", None)
    if isinstance(meta, dict):
        hire = meta.get("hire")
        if isinstance(hire, dict) and "gross_amount" in hire and "address_comm_amount" in hire:
            return "net"
    return "gross"


def invoice_commission_deducted(inv) -> Decimal:
    """已经从发票金额里扣掉的佣金金额（net 口径；gross 口径恒为 0）。"""
    if invoice_commission_basis(inv) != "net":
        return ZERO
    meta = getattr(inv, "meta", None)
    if isinstance(meta, dict):
        hire = meta.get("hire")
        if isinstance(hire, dict) and hire.get("address_comm_amount") is not None:
            return money(hire["address_comm_amount"])
    return ZERO


def is_revenue_side_code(code: str) -> bool:
    """按**规范发票类型码**判定收入侧 / 成本侧（SSOT）。

    ``gl_engine`` 也走这里 —— 以前两处各写一份判定，口径漂移过一次
    （``XDIFF`` 在 ``is_revenue_side`` 走"未知→收入"、在
    ``_is_revenue_type`` 走"非收入"，业务规则选出的科目被静默丢弃）。
    """
    code = (code or "").strip().upper()
    if code in PAYABLE_SIDE_TYPES:
        return False
    if code in REVENUE_SIDE_TYPES or code in EXCHANGE_DIFFERENCE_TYPES:
        return True
    return True  # 未知类型按收入侧处理（历史行为）


def is_revenue_side(inv) -> bool:
    """收入侧（应收）还是成本侧（应付）。未知类型按收入侧处理（历史行为）。"""
    return is_revenue_side_code(invoice_type_code(inv))


def counts_as_revenue(inv) -> bool:
    """该发票是否计入实际收入/损益（已签发且未作废未删除）。"""
    return str(getattr(inv, "status", "") or "") in REVENUE_STATUSES


def counts_as_open(inv) -> bool:
    """该发票是否计入未收账龄。"""
    return str(getattr(inv, "status", "") or "") in OPEN_STATUSES
