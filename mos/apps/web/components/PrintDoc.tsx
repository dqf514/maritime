"use client";

// U4 结构化单据模板：公司抬头 + 单据标题/编号 + 打印样式。
//
// 信头来源是 /api/v1/documents/letterhead（TenantCompanyProfile + 内联 logo），
// 不是 /masterdata/companies —— 后者只有公司名/币种/税号，地址电话永远是空的，
// logo 更用不上，管理页维护的那套抬头等于白做。

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Company = {
  display_name?: string | null;
  legal_name?: string | null;
  address?: string | null;
  phone?: string | null;
  email?: string | null;
  website?: string | null;
  tax_no?: string | null;
  logo_data?: string | null;
  brand_primary?: string | null;
};

type Letterhead = { company?: Company | null };

export function PrintDoc({
  title,
  no,
  meta,
  entityType,
  entityId,
  children,
}: {
  title: string;
  no?: string | null;
  meta?: string | null;
  /** 传了就能出服务端 PDF（比浏览器打印更正式：固定 A4 + 页码 + 可归档） */
  entityType?: string | null;
  entityId?: string | null;
  children: React.ReactNode;
}) {
  const { t } = useI18n();
  const [company, setCompany] = useState<Company | null>(null);

  useEffect(() => {
    apiGet("/api/v1/documents/letterhead")
      .then((data: Letterhead) => setCompany(data?.company || null))
      .catch(() => setCompany(null));
  }, []);

  const name = company?.display_name || company?.legal_name || "MariOS";
  const contactLine = [company?.phone, company?.email, company?.website]
    .filter(Boolean)
    .join(" · ");

  const pdfHref =
    entityType && entityId
      ? `${process.env.NEXT_PUBLIC_API_BASE || ""}/api/v1/documents/render/${entityType}/${entityId}?format=pdf`
      : null;

  return (
    <div className="print-doc">
      <header className="print-doc-head">
        <div className="print-doc-company">
          {company?.logo_data ? (
            // eslint-disable-next-line @next/next/no-img-element -- logo 是运行时上传的 data URI，无法走 next/image 域名白名单
            <img src={company.logo_data} alt="" className="print-doc-logo" />
          ) : null}
          <strong>{name}</strong>
          {company?.address ? <div className="muted">{company.address}</div> : null}
          {contactLine ? <div className="muted">{contactLine}</div> : null}
          {company?.tax_no ? (
            <div className="muted">{t("print.tax_no", "Tax / VAT Reg. No. {no}", { no: company.tax_no })}</div>
          ) : null}
        </div>
        <div className="print-doc-title">
          <h2 className="print-doc-h2">{title}</h2>
          {no ? <div className="muted">{no}</div> : null}
          {meta ? <div className="muted">{meta}</div> : null}
          {pdfHref ? (
            <a className="btn btn-sm no-print" href={pdfHref} target="_blank" rel="noreferrer">
              {t("print.export_pdf", "Export PDF")}
            </a>
          ) : null}
        </div>
      </header>
      <div className="print-doc-body">{children}</div>
    </div>
  );
}
