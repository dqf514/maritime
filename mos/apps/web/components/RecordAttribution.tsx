"use client";

// 创建人/修改人（时间）—— 详情页头部的归属条。数据源自审计账本 / 持久列。
// 用法：<RecordAttribution entityType="voyage" entityId={id} />

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Attr = {
  created_by_name?: string | null;
  created_at?: string | null;
  updated_by_name?: string | null;
  updated_at?: string | null;
};

function fmt(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function RecordAttribution({ entityType, entityId }: { entityType: string; entityId: string }) {
  const { t } = useI18n();
  const [attr, setAttr] = useState<Attr | null>(null);

  useEffect(() => {
    if (!entityType || !entityId) return;
    apiGet(`/api/v1/meta/attribution?entity_type=${entityType}&entity_id=${entityId}`)
      .then(setAttr)
      .catch(() => setAttr(null));
  }, [entityType, entityId]);

  if (!attr || (!attr.created_by_name && !attr.updated_by_name && !attr.created_at)) return null;

  const bits: string[] = [];
  if (attr.created_by_name || attr.created_at) {
    bits.push(
      `${t("attr.created_by", "创建")} ${attr.created_by_name || "—"}${attr.created_at ? ` · ${fmt(attr.created_at)}` : ""}`,
    );
  }
  if (attr.updated_by_name || attr.updated_at) {
    bits.push(
      `${t("attr.updated_by", "修改")} ${attr.updated_by_name || "—"}${attr.updated_at ? ` · ${fmt(attr.updated_at)}` : ""}`,
    );
  }

  return (
    <span className="record-attribution muted" title={bits.join("  |  ")}>
      {bits.join("  ·  ")}
    </span>
  );
}
