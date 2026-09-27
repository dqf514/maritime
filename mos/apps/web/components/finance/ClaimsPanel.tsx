"use client";

// 3.6：Claims 面板（自取数 + 分页，行点击直达索赔详情）。

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { apiList } from "@/lib/api";
import { fmt } from "@/lib/fmt";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";

type Claim = { id: string; claim_no: string; status: string; amount: number; days_to_timebar?: number | null };

export function ClaimsPanel() {
  const { t } = useI18n();
  const router = useRouter();
  const { query, setQuery, page, limit } = useListQuery();
  const [rows, setRows] = useState<Claim[]>([]);
  const [total, setTotal] = useState(0);

  const load = useCallback(async () => {
    const pg = await apiList<Claim>("/api/v1/claims", { limit, offset: (page - 1) * limit });
    setRows(pg.items);
    setTotal(pg.total);
    if (!pg.items.length && pg.total > 0 && page > 1) setQuery({ page: Math.ceil(pg.total / limit) });
  }, [limit, page, setQuery]);

  useEffect(() => {
    load().catch(() => undefined);
  }, [load]);

  const cols: ColumnDef<Claim>[] = [
    { key: "claim_no", title: t("page.finance.no", "编号") },
    { key: "status", title: t("common.status", "Status") },
    { key: "amount", title: t("common.amount", "Amount"), align: "right", render: (v) => fmt(v as number) },
    {
      key: "days_to_timebar",
      title: t("page.finance.days_to_timebar", "Days to time bar"),
      render: (v) => {
        const n = v as number | null | undefined;
        if (n == null) return "—";
        return <span style={n < 14 ? { color: "#dc2626", fontWeight: 600 } : undefined}>{n}</span>;
      },
    },
  ];

  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>{t("page.finance.claims", "Claims")}</h3>
      <DataTable<Claim>
        data={rows}
        columns={cols}
        paginatable
        storageKey="finance.claims"
        total={total}
        page={page}
        onPageChange={(p, l) => setQuery({ page: p > 1 ? p : null, limit: l === 50 ? null : l })}
        emptyText={t("common.empty", "No records")}
        onRowClick={(r) => router.push(`/finance/claims/${r.id}`)}
      />
    </div>
  );
}
