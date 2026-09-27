"use client";

// U4 结构化单据模板：公司抬头 + 单据标题/编号 + 打印样式。
// 浏览器打印（window.print）即得 PDF；打印 CSS 已隐藏导航/工具条。

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

type Company = { name?: string; address?: string | null; phone?: string | null; email?: string | null };

export function PrintDoc({
  title,
  no,
  meta,
  children,
}: {
  title: string;
  no?: string | null;
  meta?: string | null;
  children: React.ReactNode;
}) {
  const [company, setCompany] = useState<Company | null>(null);

  useEffect(() => {
    apiGet("/api/v1/masterdata/companies")
      .then((rows: Company[]) => setCompany(Array.isArray(rows) && rows.length ? rows[0] : null))
      .catch(() => setCompany(null));
  }, []);

  return (
    <div className="print-doc">
      <header className="print-doc-head">
        <div className="print-doc-company">
          <strong>{company?.name || "MariOS"}</strong>
          {company?.address ? <div className="muted">{company.address}</div> : null}
          <div className="muted">
            {[company?.phone, company?.email].filter(Boolean).join(" · ")}
          </div>
        </div>
        <div className="print-doc-title">
          <h2 style={{ margin: 0 }}>{title}</h2>
          {no ? <div className="muted">{no}</div> : null}
          {meta ? <div className="muted">{meta}</div> : null}
        </div>
      </header>
      <div className="print-doc-body">{children}</div>
    </div>
  );
}
