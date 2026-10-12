"use client";

// Revisions 修订史侧栏（IMOS workspace panel 同款）。
// 数据源：GET /api/v1/meta/revisions?entity_type=&entity_id=

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Revision = {
  id: string;
  action: string;
  actor_user_id: string | null;
  detail: Record<string, unknown>;
  ip: string | null;
  created_at: string | null;
};

export function RevisionsPanel({ entityType, entityId }: { entityType: string; entityId: string }) {
  const { t } = useI18n();
  const [rows, setRows] = useState<Revision[] | null>(null);

  useEffect(() => {
    let alive = true;
    setRows(null);
    apiGet(`/api/v1/meta/revisions?entity_type=${encodeURIComponent(entityType)}&entity_id=${encodeURIComponent(entityId)}`)
      .then((res) => {
        if (alive) setRows(((res as { items?: Revision[] }).items ?? []) as Revision[]);
      })
      .catch(() => {
        if (alive) setRows([]);
      });
    return () => {
      alive = false;
    };
  }, [entityType, entityId]);

  return (
    <div className="panel revisions-panel">
      <div className="panel-header">{t("revisions.title", "Revisions")}</div>
      <div className="panel-body">
        {rows === null ? (
          <span className="muted">{t("common.loading", "Loading…")}</span>
        ) : rows.length === 0 ? (
          <span className="muted">{t("revisions.empty", "No changes recorded yet")}</span>
        ) : (
          <ol className="revisions-list">
            {rows.map((r) => (
              <li key={r.id}>
                <div className="revisions-line">
                  <strong>{r.action}</strong>
                  <span className="muted">{r.created_at ? new Date(r.created_at).toLocaleString() : ""}</span>
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
