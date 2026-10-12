"use client";

import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { SavedViews } from "@/components/SavedViews";
import { Toolbar } from "@/components/Toolbar";
import { RecordModal } from "@/components/RecordModal";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiGet, apiPut } from "@/lib/api";
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
  const { query, setQuery } = useListQuery();
  const q = query.q ?? "";
  const [settings, setSettings] = useState<any>(null);
  const [terms, setTerms] = useState<TermRow[]>([]);
  const [editKey, setEditKey] = useState("");
  const [editLabel, setEditLabel] = useState("");

  async function loadSettings() {
    setSettings(await apiGet("/api/v1/admin/i18n/settings"));
  }

  async function loadTerms() {
    const data = await apiGet(`/api/v1/admin/i18n/terminology?q=${encodeURIComponent(q)}`);
    setTerms(data.items || []);
  }

  useEffect(() => {
    loadSettings().catch(() => toast.error(t("i18n.admin_required", "Tenant admin required")));
  }, [t]);

  useEffect(() => {
    loadTerms().catch(() => toast.error(t("common.failed", "Failed")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

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
                  {c}
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
        <button type="button" className="btn btn-sm" onClick={() => Promise.all([loadSettings(), loadTerms()]).catch(() => undefined)} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
      </Toolbar>
      <div className="panel">
        <h2>{t("i18n.terms", "Terminology")}</h2>
        <DataGrid<TermRow>
          columns={columns}
          data={terms.slice(0, 40)}
          rowKey={(r, i) => String(r.key ?? i)}
          storageKey="admin_i18n_terms"
          emptyText={t("common.empty", "No records")}
          showFooter={false}
        />
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
