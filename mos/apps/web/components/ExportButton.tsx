"use client";

import { API_BASE } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Props = { entity: string; label?: string };

export function ExportButton({ entity, label }: Props) {
  const { t, locale } = useI18n();
  const lang = locale.startsWith("zh") ? "zh" : "en";
  return (
    <a className="btn btn-ghost btn-sm" href={`${API_BASE}/api/v1/export/${entity}.csv?lang=${lang}`} download>
      {label || t("export.button", "导出 Excel")}
    </a>
  );
}
