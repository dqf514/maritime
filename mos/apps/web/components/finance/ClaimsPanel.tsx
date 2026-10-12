"use client";

// 3.6：Claims 面板（自取数 + 分页，行点击直达索赔详情）。
// R4：行右键菜单（Open / Copy id / Export）+ Num 数值列。

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { Num } from "@/components/Num";
import { apiList } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";

type Claim = { id: string; claim_no: string; status: string; amount: number; days_to_timebar?: number | null; updated_at?: string | null };

export function ClaimsPanel() {
  const { t } = useI18n();
  const router = useRouter();
  const { setQuery, page, limit } = useListQuery();
  const [rows, setRows] = useState<Claim[]>([]);
  const [total, setTotal] = useState(0);
  const ctx = useContextMenu<Claim>();

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
    {
      key: "amount",
      title: t("common.amount", "Amount"),
      align: "right",
      value: (r) => r.amount,
      render: (v) => <Num v={v as number} digits={2} />,
    },
    {
      key: "days_to_timebar",
      title: t("page.finance.days_to_timebar", "Days to time bar"),
      value: (r) => r.days_to_timebar ?? null,
      render: (v) => {
        const n = v as number | null | undefined;
        if (n == null) return "—";
        return <span style={n < 14 ? { color: "#dc2626", fontWeight: 600 } : undefined}>{n}</span>;
      },
    },
    {
      key: "updated_at",
      title: t("list.last_modified", "Last modified"),
      width: 135,
      value: (r) => r.updated_at ?? null,
      render: (v) => (v ? String(v).replace("T", " ").slice(0, 16) : "—"),
    },
  ];

  const menuItems = (row: Claim): ContextMenuItem[] => [
    { key: "open", label: t("common.open", "Open"), onClick: () => router.push(`/finance/claims/${row.id}`) },
    { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(row.id) },
    {
      key: "export",
      label: t("common.export_csv", "Export CSV"),
      onClick: () =>
        downloadCsv(
          "claims",
          ["id", "claim_no", "status", "amount", "days_to_timebar"],
          [[row.id, row.claim_no, row.status, row.amount, row.days_to_timebar ?? ""]],
        ),
    },
  ];

  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>{t("page.finance.claims", "Claims")}</h3>
      <DataGrid<Claim>
        data={rows}
        columns={cols}
        rowKey={(r) => r.id}
        storageKey="finance.claims"
        emptyText={t("common.empty", "No records")}
        onRowClick={(r) => router.push(`/finance/claims/${r.id}`)}
        onRowContextMenu={(row, _i, e) => ctx.open(row)(e)}
      />
      <div className="desk-toolbar">
        <button
          className="btn btn-sm btn-ghost"
          type="button"
          disabled={page <= 1}
          onClick={() => setQuery({ page: page > 2 ? page - 1 : null }, { resetPage: false })}
        >
          ←
        </button>
        <span className="muted">
          {page} / {Math.max(1, Math.ceil(total / limit))}
        </span>
        <button
          className="btn btn-sm btn-ghost"
          type="button"
          disabled={page * limit >= total}
          onClick={() => setQuery({ page: page + 1 }, { resetPage: false })}
        >
          →
        </button>
      </div>
      <ContextMenu controller={ctx} items={menuItems} />
    </div>
  );
}
