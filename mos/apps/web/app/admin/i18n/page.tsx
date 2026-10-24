"use client";

import { RefreshButton } from "@/components/RefreshButton";
import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { SavedViews } from "@/components/SavedViews";
import { StateView } from "@/components/StateView";
import { Toolbar } from "@/components/Toolbar";
import { RecordModal } from "@/components/RecordModal";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiGet, apiPut } from "@/lib/api";
import { msgOf, handled } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

type TermRow = {
  key: string;
  label: string;
  category?: string;
  overridden?: boolean;
};

function TenantI18nPage() {
  const { t, term, reload } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const { query, setQuery, page, limit } = useListQuery();
  const q = query.q ?? "";
  const [settings, setSettings] = useState<any>(null);
  const [terms, setTerms] = useState<TermRow[]>([]);
  const [termsLoading, setTermsLoading] = useState(true);
  const [termsErr, setTermsErr] = useState("");
  const [editKey, setEditKey] = useState("");
  const [editLabel, setEditLabel] = useState("");

  async function loadSettings() {
    setSettings(await apiGet("/api/v1/admin/i18n/settings"));
  }

  async function loadTerms() {
    setTermsLoading(true);
    setTermsErr("");
    try {
      const data = await apiGet(`/api/v1/admin/i18n/terminology?q=${encodeURIComponent(q)}`);
      setTerms(data.items || []);
    } catch (e) {
      // 主列表失败必须走错误态，不能静默变成空术语表（P1-4）。
      setTerms([]);
      setTermsErr(msgOf(e, t("common.failed", "Failed")));
    } finally {
      setTermsLoading(false);
    }
  }

  useEffect(() => {
    loadSettings().catch(() => toast.error(t("i18n.admin_required", "Tenant admin required")));
  }, [t]);

  useEffect(() => {
    loadTerms();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  // 分页（P1-28）：原来硬截断前 40 条且不可见 —— 现在分页 + 「共 N 条」。
  const totalPages = Math.max(1, Math.ceil(terms.length / limit));
  const safePage = Math.min(page, totalPages);
  const pagedTerms = useMemo(
    () => terms.slice((safePage - 1) * limit, safePage * limit),
    [terms, safePage, limit],
  );
  const setPage = (p: number) => setQuery({ page: p > 1 ? p : null });

  async function saveSettings(e: FormEvent) {
    e.preventDefault();
    await apiPut("/api/v1/admin/i18n/settings", settings);
    toast.success(t("common.saved", "Saved"));
    await reload();
    await Promise.all([loadSettings(), loadTerms()]);
  }

  async function saveOverride(e: FormEvent) {
    e.preventDefault();
    await apiPut("/api/v1/admin/i18n/terminology/overrides", {
      term_key: editKey,
      locale: settings?.default_locale || "en",
      label: editLabel,
    });
    toast.success(t("i18n.override_saved", "Override saved"));
    setEditKey("");
    setEditLabel("");
    await loadTerms();
  }

  const columns = useMemo<ColumnDef<TermRow>[]>(
    () => [
      {
        key: "key",
        title: t("common.key", "Key"),
        width: 220,
        value: (r) => r.key,
        render: (v) => <code>{String(v ?? "")}</code>,
      },
      {
        key: "label",
        title: t("common.label", "Label"),
        width: 240,
        value: (r) => r.label,
        render: (v, r) => (
          <>
            {String(v ?? "")}
            {r.overridden ? <span className="pill valid">{t("common.override", "Override")}</span> : null}
          </>
        ),
      },
      {
        key: "category",
        title: t("common.category", "Category"),
        width: 140,
        value: (r) => r.category,
        render: (v) =>
          v ? t(`page.i18n.cat_${String(v).toLowerCase()}`, String(v)) : "",
      },
      {
        key: "actions",
        title: "",
        width: 110,
        align: "right",
        value: () => "",
        render: (_v, r) => (
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              setEditKey(r.key);
              setEditLabel(r.label);
            }}
          >
            {t("common.override", "Override")}
          </button>
        ),
      },
    ],
    [t],
  );

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.admin", "Administration") }]}
        title={t("i18n.page_title", "Languages & terminology")}
        subtitle={`${t(
          "i18n.page_sub",
          "Tenant policy for default UI language and local overrides of maritime terms (e.g. company-preferred)",
        )} ${term("term.tce", "TCE")} ${t("i18n.page_sub_end", "wording).")}`}
        actions={
          <SavedViews storageKey="admin_i18n" onApply={(qs) => router.replace(`${pathname}${qs}`)} />
        }
      />

      {settings ? (
        <form className="panel" onSubmit={(e) => saveSettings(e).catch(() => toast.error(t("common.failed", "Failed")))}>
          <h2>{t("i18n.languages", "Languages")}</h2>
          <label>
            {t("i18n.default_locale", "Default locale")}
            <select
              value={settings.default_locale}
              onChange={(e) => setSettings({ ...settings, default_locale: e.target.value })}
            >
              {(settings.allowed_locales || ["en", "zh-CN"]).map((c: string) => (
                <option key={c} value={c}>
                  {c === "en"
                    ? `${c} — ${t("i18n.locale_en", "English")}`
                    : c === "zh-CN"
                      ? `${c} — ${t("i18n.locale_zh", "Simplified Chinese")}`
                      : c}
                </option>
              ))}
            </select>
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={settings.allow_user_override}
              onChange={(e) => setSettings({ ...settings, allow_user_override: e.target.checked })}
            />
            {t("i18n.allow_user", "Allow users to switch language")}
          </label>
          <button className="btn btn-primary" type="submit">
            {t("common.save", "Save")}
          </button>
        </form>
      ) : null}

      <Toolbar
        filterCount={q ? 1 : 0}
        onClearFilters={() => setQuery({ q: null }, { resetPage: true })}
        right={
          <input
            className="input input-sm"
            value={q}
            onChange={(e) => setQuery({ q: e.target.value || null }, { resetPage: true })}
            placeholder={t("i18n.search", "Search terms")}
            aria-label={t("i18n.search", "Search terms")}
          />
        }
      >
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => Promise.all([loadSettings(), loadTerms()]).catch(handled)} />
      </Toolbar>
      <div className="panel">
        <h2>{t("i18n.terms", "Terminology")}</h2>
        <StateView
          loading={termsLoading}
          error={termsErr || undefined}
          empty={!termsErr && !terms.length}
          emptyText={t("common.empty", "No records")}
          onRetry={loadTerms}
        >
          <DataGrid<TermRow>
            columns={columns}
            data={pagedTerms}
            rowKey={(r, i) => String(r.key ?? i)}
            storageKey="admin_i18n_terms"
            emptyText={t("common.empty", "No records")}
            showFooter={false}
          />
        </StateView>
        {!termsErr ? (
          <div className="dt-pagination">
            <span className="dt-page-info">
              {t("common.page_of", "{from}-{to} of {n}", {
                from: terms.length ? (safePage - 1) * limit + 1 : 0,
                to: Math.min(safePage * limit, terms.length),
                n: terms.length,
              })}
            </span>
            <span className="dt-page-btns">
              <button type="button" onClick={() => setPage(safePage - 1)} disabled={safePage <= 1} aria-label="prev">
                ‹
              </button>
              <button type="button" onClick={() => setPage(safePage + 1)} disabled={safePage >= totalPages} aria-label="next">
                ›
              </button>
            </span>
          </div>
        ) : null}
        <RecordModal
          open={Boolean(editKey)}
          title={`${t("common.override", "Override")} ${editKey}`}
          onClose={() => {
            setEditKey("");
            setEditLabel("");
          }}
          onSave={(e) => saveOverride(e).catch(() => toast.error(t("i18n.override_fail", "Override failed")))}
          canDelete={false}
        >
          <label>
            {t("common.label", "Label")}
            <input value={editLabel} onChange={(e) => setEditLabel(e.target.value)} required />
          </label>
        </RecordModal>
      </div>
    </AppShell>
  );
}

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <TenantI18nPage />
    </Suspense>
  );
}
