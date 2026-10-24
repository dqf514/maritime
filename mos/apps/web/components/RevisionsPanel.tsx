"use client";

// Revisions 修订史侧栏（IMOS workspace panel 同款）。
// 数据源：GET /api/v1/meta/revisions?entity_type=&entity_id=

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { formatInTz } from "@/lib/datetime";
import { useI18n } from "@/lib/i18n";
import { msgOf } from "@/lib/errors";

type Revision = {
  id: string;
  action: string;
  actor_user_id: string | null;
  detail: Record<string, unknown>;
  ip: string | null;
  created_at: string | null;
};

export function RevisionsPanel({ entityType, entityId }: { entityType: string; entityId: string }) {
  const { t, locale } = useI18n();
  const [rows, setRows] = useState<Revision[] | null>(null);
  // P1-4：修订记录取不到时不能显示"尚无变更记录" —— 那是**没取到**。
  // 错误按实体打标：换实体时旧错误自动失效（不必在 effect 里 setState 清空）。
  const [err, setErr] = useState<{ key: string; msg: string } | null>(null);
  const errKey = `${entityType}:${entityId}`;
  const loadError = err && err.key === errKey ? err.msg : "";

  useEffect(() => {
    let alive = true;
    setRows(null);
    apiGet(`/api/v1/meta/revisions?entity_type=${encodeURIComponent(entityType)}&entity_id=${encodeURIComponent(entityId)}`)
      .then((res) => {
        if (alive) setRows(((res as { items?: Revision[] }).items ?? []) as Revision[]);
      })
      .catch((ex) => {
        if (!alive) return;
        setRows([]);
        setErr({
          key: `${entityType}:${entityId}`,
          msg: msgOf(ex, t("revisions.load_fail", "Could not load the revision history.")),
        });
      });
    return () => {
      alive = false;
    };
  }, [entityType, entityId, t]);

  return (
    <div className="panel revisions-panel">
      <div className="panel-header">{t("revisions.title", "Revisions")}</div>
      <div className="panel-body">
        {rows === null ? (
          <span className="muted">{t("common.loading", "Loading…")}</span>
        ) : loadError ? (
          <span className="field-error" role="alert">
            {loadError}
          </span>
        ) : rows.length === 0 ? (
          <span className="muted">{t("revisions.empty", "No changes recorded yet")}</span>
        ) : (
          <ol className="revisions-list">
            {rows.map((r) => (
              <li key={r.id}>
                <div className="revisions-line">
                  <strong>{r.action}</strong>
                  <span className="muted">{r.created_at ? formatInTz(r.created_at, null, undefined, locale) : ""}</span>
                </div>
                {Array.isArray(r.detail?.fields) ? (
                  <div className="muted revisions-fields">
                    {t("revisions.fields", "fields")}: {(r.detail.fields as string[]).join(", ")}
                  </div>
                ) : r.detail?.from && r.detail?.to ? (
                  <div className="muted revisions-fields">
                    {String(r.detail.from)} → {String(r.detail.to)}
                  </div>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
