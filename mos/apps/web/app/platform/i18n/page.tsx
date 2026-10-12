"use client";

import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { SavedViews } from "@/components/SavedViews";
import { Toolbar } from "@/components/Toolbar";
import { RecordModal } from "@/components/RecordModal";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { apiGet, apiPut } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

function PlatformI18nPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const { query, setQuery } = useListQuery();
  const locale = query.locale || "zh-CN";
  const q = query.q ?? "";
  const [overview, setOverview] = useState<any>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [terms, setTerms] = useState<any[]>([]);
  const [editKey, setEditKey] = useState("");
  const [editText, setEditText] = useState("");

  async function load() {
    setOverview(await apiGet("/api/v1/platform/i18n/overview"));
    setMessages(await apiGet(`/api/v1/platform/i18n/messages?locale=${encodeURIComponent(locale)}`));
    const data = await apiGet(`/api/v1/platform/i18n/terminology?q=${encodeURIComponent(q)}`);
    setTerms(data.items || []);
  }

  useEffect(() => {
    load().catch(() => toast.error(t("i18n.platform_admin_required", "Platform admin required")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale, q]);

  async function saveMessage(e: FormEvent) {
    e.preventDefault();
    await apiPut("/api/v1/platform/i18n/messages", { msg_key: editKey, locale, text: editText, namespace: "app" });
    toast.success(t("i18n.message_updated", "Message updated"));
    setEditKey("");
    await load();
  }

  type I18nRow = Record<string, unknown>;

  const messageColumns = useMemo<ColumnDef<I18nRow>[]>(
    () => [
      {
        key: "key",
        title: t("common.key", "Key"),
        width: 220,
        value: (r) => r.key,
        render: (v) => <code>{String(v)}</code>,
      },
      {
        key: "text",
        title: t("i18n.text", "Text"),
        value: (r) => r.text,
      },
      {
        key: "actions",
        title: "",
        width: 90,
        render: (_v, row) => (
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              setEditKey(String(row.key));
              setEditText(String(row.text));
            }}
          >
            {t("common.edit", "Edit")}
          </button>
        ),
      },
    ],
    [t],
  );

  const termColumns = useMemo<ColumnDef<I18nRow>[]>(
    () => [
      {
        key: "term_key",
        title: t("common.key", "Key"),
        width: 200,
        value: (r) => r.term_key,
        render: (v) => <code>{String(v)}</code>,
      },
      { key: "en", title: "EN", value: (r) => r.en },
      { key: "zh_cn", title: "zh-CN", value: (r) => r.zh_cn },
      { key: "category", title: t("common.category", "Category"), value: (r) => r.category },
    ],
    [t],
  );

  const filterCount = (q ? 1 : 0) + (locale !== "zh-CN" ? 1 : 0);

  return (
    <AppShell>
      <PageHeader
        title={t("i18n.platform_title", "Platform languages & terminology")}
        subtitle={t("i18n.platform_sub", "Global language packs (en / zh-CN) and maritime terminology catalog. Tenants may override labels; secrets stay out of this plane.")}
        breadcrumb={[{ label: t("page.platform.title", "Platform"), href: "/platform" }, { label: t("i18n.platform_title", "Platform languages & terminology") }]}
        actions={<SavedViews storageKey="platform_i18n" onApply={(qs) => router.replace(`${pathname}${qs}`)} />}
      />

      <div className="kpi-row">
        <div className="kpi-card">
          <span>{t("i18n.ui_keys", "UI keys")}</span>
          <strong>{overview?.ui_message_keys ?? "—"}</strong>
        </div>
        <div className="kpi-card">
          <span>{t("i18n.catalog_count", "Catalog terms")}</span>
          <strong>
            {overview?.terminology_terms ?? "—"}
            <small> / {overview?.target_terminology ?? 500}</small>
          </strong>
        </div>
        <div className="kpi-card">
          <span>{t("i18n.languages", "Languages")}</span>
          <strong>{overview?.languages?.length ?? "—"}</strong>
        </div>
      </div>

      <Toolbar
        filterCount={filterCount}
        onClearFilters={() => setQuery({ q: null, locale: null }, { resetPage: true })}
        right={
          <>
            <select
              className="input input-sm"
              value={locale}
              onChange={(e) => setQuery({ locale: e.target.value === "zh-CN" ? null : e.target.value }, { resetPage: true })}
              aria-label={t("i18n.locale", "Locale")}
            >
              <option value="en">en</option>
              <option value="zh-CN">zh-CN</option>
            </select>
            <input
              className="input input-sm"
              value={q}
              onChange={(e) => setQuery({ q: e.target.value || null }, { resetPage: true })}
              placeholder={t("i18n.search", "Search terms")}
              aria-label={t("i18n.search", "Search terms")}
            />
          </>
        }
      >
        <button type="button" className="btn btn-sm" onClick={() => load().catch(() => undefined)} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
      </Toolbar>

      <div className="panel">
        <h2>{t("i18n.languages", "Languages")}</h2>
        <ul className="compact-list">
          {(overview?.languages || []).map((l: any) => (
            <li key={l.code}>
              <strong>{l.native_name}</strong> ({l.code}) {l.enabled ? `· ${t("common.enabled", "enabled")}` : `· ${t("common.disabled", "disabled")}`}
              {l.is_default ? ` · ${t("common.default", "default")}` : ""}
            </li>
          ))}
        </ul>
      </div>

      <div className="panel">
        <h2>{t("i18n.ui_messages", "UI messages")}</h2>
        <DataGrid
          columns={messageColumns}
          data={messages.slice(0, 50)}
          rowKey={(r) => String(r.key)}
          storageKey="platform_i18n_messages"
          emptyText={t("common.empty", "No records")}
        />
        <RecordModal
          open={Boolean(editKey)}
          title={`${t("common.edit", "Edit")} ${editKey} (${locale})`}
          onClose={() => setEditKey("")}
          onSave={(e) => saveMessage(e).catch(() => toast.error(t("common.failed", "Failed")))}
          canDelete={false}
        >
          <label>
            {t("i18n.text", "Text")}
            <input value={editText} onChange={(e) => setEditText(e.target.value)} required />
          </label>
        </RecordModal>
      </div>

      <div className="panel">
        <h2>{t("i18n.terms", "Terminology")}</h2>
        <DataGrid
          columns={termColumns}
          data={terms.slice(0, 60)}
          rowKey={(r) => String(r.term_key)}
          storageKey="platform_i18n_terms"
          emptyText={t("common.empty", "No records")}
        />
      </div>
    </AppShell>
  );
}

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <PlatformI18nPage />
    </Suspense>
  );
}
