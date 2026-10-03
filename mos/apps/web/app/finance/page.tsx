"use client";

// 3.6 拆分完成：finance 工作台为薄壳，各标签为自取数面板
// （components/finance/*Panel），单据编辑在详情页（U2）。

import { Suspense } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageGuide } from "@/components/PageGuide";
import { PageHeader } from "@/components/PageHeader";
import { SavedViews } from "@/components/SavedViews";
import { AccrualsPanel } from "@/components/finance/AccrualsPanel";
import { ClaimsPanel } from "@/components/finance/ClaimsPanel";
import { InvoicesPanel } from "@/components/finance/InvoicesPanel";
import { LaytimePanel } from "@/components/finance/LaytimePanel";
import { PdaPanel } from "@/components/finance/PdaPanel";
import { PnlPanel } from "@/components/finance/PnlPanel";
import { RiskLimitPanel } from "@/components/finance/RiskLimitPanel";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";

type Tab = "invoices" | "laytime" | "pnl" | "claims" | "accruals" | "pda" | "risk";
const TAB_IDS: readonly string[] = ["invoices", "laytime", "pnl", "claims", "accruals", "pda", "risk"];

function FinanceHubPage() {
  const { t } = useI18n();
  const router = useRouter();
  // U1 列表协议：tab/page/limit 进 URL，视图可分享、后退不丢状态
  const { query, setQuery } = useListQuery();
  const tab: Tab = TAB_IDS.includes(query.tab ?? "") ? (query.tab as Tab) : "invoices";
  const setTab = (id: Tab) => setQuery({ tab: id === "invoices" ? null : id, page: null });

  const tabs: Array<{ id: Tab; label: string }> = [
    { id: "invoices", label: t("page.finance.invoices", "Invoices") },
    { id: "laytime", label: t("page.finance.laytime", "Laytime") },
    { id: "pnl", label: t("page.finance.pnl", "Dynamic P&L") },
    { id: "claims", label: t("page.finance.claims", "Claims") },
    { id: "accruals", label: t("page.finance.accruals", "Voyage accruals") },
    { id: "pda", label: t("page.finance.pda", "Port PDA/FDA") },
    { id: "risk", label: t("page.finance.risk", "Risk limits") },
  ];

  return (
    <AppShell>
      <PageHeader
        title={t("page.finance.title", "Finance / laytime / P&L")}
        subtitle={t("page.finance.sub", "Invoices, laytime, claims, accruals and PDA/FDA. Open a row to edit or delete.")}
        actions={
          <>
            <PageGuide pageKey="finance" />
            <SavedViews storageKey="finance" onApply={(q) => router.replace(`/finance${q}`)} />
            <Link href="/settings/recycle" className="btn btn-ghost">
              {t("nav.recycle", "Recycle bin")}
            </Link>
          </>
        }
      />

      <div className="desk-tabs">
        {tabs.map((tb) => (
          <button
            key={tb.id}
            type="button"
            className={`desk-tab${tab === tb.id ? " active" : ""}`}
            onClick={() => setTab(tb.id)}
          >
            {tb.label}
          </button>
        ))}
      </div>

      {tab === "invoices" ? <InvoicesPanel /> : null}
      {tab === "laytime" ? <LaytimePanel /> : null}
      {tab === "pnl" ? <PnlPanel /> : null}
      {tab === "claims" ? <ClaimsPanel /> : null}
      {tab === "accruals" ? <AccrualsPanel /> : null}
      {tab === "pda" ? <PdaPanel /> : null}
      {tab === "risk" ? <RiskLimitPanel /> : null}
    </AppShell>
  );
}

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <FinanceHubPage />
    </Suspense>
  );
}
