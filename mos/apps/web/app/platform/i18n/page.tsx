"use client";

import { RefreshButton } from "@/components/RefreshButton";
import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { SavedViews } from "@/components/SavedViews";
import { Toolbar } from "@/components/Toolbar";
import { RecordModal } from "@/components/RecordModal";
import { StateView } from "@/components/StateView";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { apiGet, apiPut } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { toPageNumber } from "@/lib/numbers";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

const PAGE_SIZE = 50;

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
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const ov = await apiGet("/api/v1/platform/i18n/overview");
      setOverview(ov);
      const msgs = await apiGet(`/api/v1/platform/i18n/messages?locale=${encodeURIComponent(locale)}`);
      setMessages(Array.isArray(msgs) ? msgs : []);
      const data = await apiGet(`/api/v1/platform/i18n/terminology?q=${encodeURIComponent(q)}`);
      setTerms(data.items || []);
    } catch (ex) {
      setErr(msgOf(ex, t("i18n.platform_admin_required", "Platform admin required")));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale, q]);

  // ── 分页：后端这两个端点一次性返回全量，客户端分页（总数始终可见，不静默截断）──
  const msgPage = toPageNumber(query.msgpage);
  const termPage = toPageNumber(query.termpage);
  const msgPages = Math.max(1, Math.ceil(messages.length / PAGE_SIZE));
  const termPages = Math.max(1, Math.ceil(terms.length / PAGE_SIZE));
  const msgRows = messages.slice((msgPage - 1) * PAGE_SIZE, msgPage * PAGE_SIZE);
  const termRows = terms.slice((termPage - 1) * PAGE_SIZE, termPage * PAGE_SIZE);


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
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => load()} />
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
        <StateView
          loading={loading}
          error={err ?? undefined}
          empty={!messages.length}
          onRetry={() => load()}
          emptyText={t("common.empty", "No records")}
        >
          <DataGrid
            columns={messageColumns}
            data={msgRows}
            rowKey={(r) => String(r.key)}
            storageKey="platform_i18n_messages"
            emptyText={t("common.empty", "No records")}
          />
          <div className="dt-pager">
            <span className="muted">{t("common.count_total", "共 {n} 条", { n: messages.length })}</span>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              disabled={msgPage <= 1}
              aria-label={t("common.page_prev", "上一页")}
              onClick={() => setQuery({ msgpage: msgPage - 1 })}
            >
              ←
            </button>
            <span className="muted">
              {msgPage} / {msgPages}
            </span>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              disabled={msgPage >= msgPages}
              aria-label={t("common.page_next", "下一页")}
              onClick={() => setQuery({ msgpage: msgPage + 1 })}
            >
              →
            </button>
          </div>
        </StateView>
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
        <StateView
          loading={loading}
          error={err ?? undefined}
          empty={!terms.length}
          onRetry={() => load()}
          emptyText={t("common.empty", "No records")}
        >
          <DataGrid
            columns={termColumns}
            data={termRows}
            rowKey={(r) => String(r.term_key)}
            storageKey="platform_i18n_terms"
            emptyText={t("common.empty", "No records")}
          />
          <div className="dt-pager">
            <span className="muted">{t("common.count_total", "共 {n} 条", { n: terms.length })}</span>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              disabled={termPage <= 1}
              aria-label={t("common.page_prev", "上一页")}
              onClick={() => setQuery({ termpage: termPage - 1 })}
            >
              ←
            </button>
            <span className="muted">
              {termPage} / {termPages}
            </span>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              disabled={termPage >= termPages}
              aria-label={t("common.page_next", "下一页")}
              onClick={() => setQuery({ termpage: termPage + 1 })}
            >
              →
            </button>
          </div>
        </StateView>
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
