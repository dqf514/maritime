"use client";

// D1 双币字段（IMOS 开票标准）：Amount + Amount(base) + FX 汇率三联，
// 数值显示紧凑、hover 全精度；base/rate 只读（由后端按 rate_date_basis 计算），
// rate 可在无 baseAmount 时手工录入（编辑发票场景）。

import { useI18n } from "@/lib/i18n";
import { fmt, fmtFull } from "@/lib/fmt";

type Num = number | string | null | undefined;

type Props = {
  amount: Num;
  currency?: string;
  baseAmount?: Num;
  baseCurrency?: string;
  fxRate?: Num;
  rateDate?: string | null;
  /** departure | arrival | invoice | posted */
  rateBasis?: string | null;
  readOnly?: boolean;
  onAmountChange?: (v: string) => void;
  onFxRateChange?: (v: string) => void;
};

function numStr(v: Num): string {
  if (v == null || v === "") return "";
  return typeof v === "number" ? String(v) : v;
}

export function CurrencyField({
  amount,
  currency,
  baseAmount,
  baseCurrency,
  fxRate,
  rateDate,
  rateBasis,
  readOnly,
  onAmountChange,
  onFxRateChange,
}: Props) {
  const { t } = useI18n();
  const amountN = amount == null || amount === "" ? null : Number(amount);
  const baseN = baseAmount == null || baseAmount === "" ? null : Number(baseAmount);
  const rateN = fxRate == null || fxRate === "" ? null : Number(fxRate);

  return (
    <div className="currency-field form-grid">
      <label className="field-row">
        <span className="field-label">
          {t("cur.amount", "Amount")}
          {currency ? <span className="cur-ccy">{currency}</span> : null}
        </span>
        {onAmountChange && !readOnly ? (
          <input
            inputMode="decimal"
            value={numStr(amount)}
            onChange={(e) => onAmountChange(e.target.value)}
            placeholder="0.00"
          />
        ) : (
          <span className="cur-ro" title={amountN != null ? fmtFull(amountN) : undefined}>
            {amountN != null ? fmt(amountN, 2) : "—"}
          </span>
        )}
      </label>

      <label className="field-row">
        <span className="field-label">
          {t("cur.base", "Amount (base)")}
          {baseCurrency ? <span className="cur-ccy">{baseCurrency}</span> : null}
        </span>
        <span className="cur-ro" title={baseN != null ? fmtFull(baseN) : undefined}>
          {baseN != null ? fmt(baseN, 2) : "—"}
        </span>
      </label>

      <label className="field-row">
        <span className="field-label">{t("cur.fx", "FX rate")}</span>
        {onFxRateChange && !readOnly ? (
          <input
            inputMode="decimal"
            value={numStr(fxRate)}
            onChange={(e) => onFxRateChange(e.target.value)}
            placeholder="0.000000"
          />
        ) : (
          <span className="cur-ro" title={rateN != null ? fmtFull(rateN) : undefined}>
            {rateN != null ? fmt(rateN, 6) : "—"}
          </span>
        )}
        <span className="cur-hint">
          {rateBasis
            ? t("cur.rate_basis", "Basis: {b}", {
                b: t(`cur.basis_${rateBasis}`, rateBasis),
              })
            : ""}
          {rateBasis && rateDate ? " · " : ""}
          {rateDate ? t("cur.rate_date", "Rate date: {d}", { d: rateDate.slice(0, 10) }) : ""}
        </span>
      </label>
    </div>
  );
}
