"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { formatInTz } from "@/lib/datetime";
import { useI18n } from "@/lib/i18n";

type RelatedMail = {
  id: string;
  subject: string | null;
  from_email: string | null;
  sent_at: string | null;
  parse_status: string;
  email_type: string | null;
  body_preview: string;
};

/**
 * 关联邮件侧栏 — 邮件贯穿工作流的通用附属面板。
 *
 * 传入业务实体的关键词（航次号 / 船名 / 对手方等），从租户邮箱里拉取主题或
 * 正文命中的邮件，以可折叠面板嵌在任意业务页面（航次、租约、装港…）。
 * 邮箱未连接 / 无命中时安静降级为空列表，不打扰主流程。
 * 样式见 styles/layout.css 的 .mail-aside 段。
 */
export function MailAside({
  keywords,
  title,
  top = 8,
  defaultOpen = true,
}: {
  keywords: (string | null | undefined)[];
  title?: string;
  top?: number;
  defaultOpen?: boolean;
}) {
  const { t, locale } = useI18n();
  const [items, setItems] = useState<RelatedMail[]>([]);
  const q = keywords.filter(Boolean).join(",");

  useEffect(() => {
    if (!q) {
      setItems([]);
      return;
    }
    let alive = true;
    apiGet(`/api/v1/email/related?q=${encodeURIComponent(q)}&top=${top}`)
      .then((rows) => {
        if (alive) setItems(rows);
      })
      .catch(() => {
        if (alive) setItems([]);
      });
    return () => {
      alive = false;
    };
  }, [q, top]);

  return (
    <details className="panel mail-aside" open={defaultOpen}>
      <summary>
        <strong>{title || t("mailaside.title", "相关邮件")}</strong>
        <span className="badge">{items.length}</span>
        <span className="mail-aside-hint">
          {t("mailaside.hint", "按航次号 / 船名 / 对手方自动匹配收件箱")}
        </span>
      </summary>
      {items.length ? (
        <ul>
          {items.map((m) => (
            <li key={m.id}>
              <div className="mail-aside-head">
                <strong>{m.subject || t("page.email.no_subject", "(no subject)")}</strong>
                {m.email_type ? <span className="badge badge-info">{m.email_type}</span> : null}
                {m.parse_status === "review" ? (
                  <span className="badge badge-warn">{t("page.email.status_review", "review")}</span>
                ) : null}
              </div>
              <div className="mail-aside-meta">
                {m.from_email || "—"}
                {m.sent_at ? ` · ${formatInTz(m.sent_at, null, undefined, locale)}` : ""}
              </div>
              {m.body_preview ? (
                <div className="mail-aside-body">{m.body_preview.slice(0, 220)}</div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mail-aside-empty">
          {q ? t("mailaside.empty", "收件箱里暂无匹配邮件。") : t("mailaside.no_keywords", "无可用匹配关键词。")}
        </p>
      )}
    </details>
  );
}
