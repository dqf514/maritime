"use client";

// 单据模板管理 — 租户可编辑 14 种对外单据的 HTML/CSS 版式，实时预览。
//
// 产品语义：模板是租户资产，但**信头不由模板作者维护** —— 公司名/地址/logo/银行
// 统一由后端 build_letterhead 注入，模板只写版式。这样改一次公司档案，
// 所有单据同步更新，不会出现"发票抬头和汇款通知长得不一样"。
//
// 渲染在后端走 Jinja2 沙箱环境（租户模板是不可信输入），预览只是把草稿
// POST 给 /preview 换回完整 HTML 塞进 iframe —— 前端不自己解析 Jinja。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader } from "@/components/PageHeader";
import { Tabs } from "@/components/Tabs";
import { apiGet, apiPost, apiPut, readStorage, TOKEN_STORAGE_KEY } from "@/lib/api";
import { apiError, msgOf, handled } from "@/lib/errors";
import { stripActiveContent } from "@/lib/sanitize";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type DocType = {
  code: string;
  title_en: string;
  title_zh: string;
  has_lines: boolean;
  module: string;
};

type TemplateRow = {
  id: string;
  entity_type: string;
  name: string;
  locale: string;
  version: number;
  enabled: boolean;
  is_system: boolean;
  is_default: boolean;
  edited: boolean;
};

type TemplateDetail = TemplateRow & {
  body: string;
  css: string;
  system_body: string | null;
  system_css: string | null;
  variables: { name: string; desc: string }[];
};

type Catalog = {
  types: DocType[];
  templates: TemplateRow[];
  pdf_available: boolean;
};

type VarHint = { name: string; desc: string };

const LOCALES = ["en", "zh"] as const;

export default function DocTemplatesPage() {
  const { t, locale: uiLocale } = useI18n();
  const toast = useToast();

  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [activeType, setActiveType] = useState<string>("invoice");
  const [locale, setLocale] = useState<string>("en");
  const [detail, setDetail] = useState<TemplateDetail | null>(null);
  const [tab, setTab] = useState<"body" | "css">("body");
  const [body, setBody] = useState("");
  const [css, setCss] = useState("");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [previewHtml, setPreviewHtml] = useState<string>("");
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const [pendingReset, setPendingReset] = useState(false);
  // 目录 / 详情加载失败：显式报错，不静默退化为空
  const [catalogErr, setCatalogErr] = useState<string | null>(null);
  const [detailErr, setDetailErr] = useState<string | null>(null);
  const previewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const frameRef = useRef<HTMLIFrameElement | null>(null);

  const zh = (uiLocale || "en").toLowerCase().startsWith("zh");

  const loadCatalog = useCallback(async () => {
    setCatalogErr(null);
    try {
      const data = (await apiGet("/api/v1/documents/templates")) as Catalog;
      setCatalog(data);
      return data;
    } catch (ex) {
      setCatalogErr(msgOf(ex));
      setCatalog(null);
      throw ex;
    }
  }, []);

  const loadDetail = useCallback(async (entityType: string, loc: string) => {
    setDetailErr(null);
    // 模板按 (entity_type, code, locale) 唯一 —— 先列表定位 id 再取详情
    const list = (await apiGet(
      `/api/v1/documents/templates?entity_type=${encodeURIComponent(entityType)}`,
    )) as Catalog;
    const row =
      list.templates.find((r) => r.locale === loc) ||
      list.templates.find((r) => r.locale.startsWith(loc)) ||
      list.templates[0];
    if (!row) {
      setDetail(null);
      return;
    }
    const full = (await apiGet(`/api/v1/documents/templates/${row.id}`)) as TemplateDetail;
    setDetail(full);
    setBody(full.body || "");
    setCss(full.css || "");
    setDirty(false);
  }, []);

  /** 详情加载失败 → 记录错误（不静默清空） */
  const loadDetailSafe = useCallback(
    async (entityType: string, loc: string) => {
      try {
        await loadDetail(entityType, loc);
      } catch (ex) {
        setDetailErr(msgOf(ex));
        setDetail(null);
      }
    },
    [loadDetail],
  );

  useEffect(() => {
    loadCatalog().catch(handled);
  }, [loadCatalog]);

  useEffect(() => {
    loadDetailSafe(activeType, locale);
  }, [activeType, locale, loadDetailSafe]);

  // 草稿变化 → 防抖 400ms 后请求预览（预览用后端沙箱渲染，前端不解析 Jinja）
  useEffect(() => {
    if (!detail) return;
    if (previewTimer.current) clearTimeout(previewTimer.current);
    previewTimer.current = setTimeout(() => {
      apiPost(`/api/v1/documents/templates/${detail.id}/preview`, {
        body,
        css,
        name: detail.name,
      })
        .then((res: { html?: string }) => {
          setPreviewHtml(res?.html || "");
          setPreviewErr(null);
        })
        .catch((err: unknown) => {
          setPreviewErr(msgOf(err));
          setPreviewHtml("");
        });
    }, 400);
    return () => {
      if (previewTimer.current) clearTimeout(previewTimer.current);
    };
  }, [detail, body, css]);

  const typeTitle = useCallback(
    (code: string) => {
      const spec = catalog?.types.find((x) => x.code === code);
      if (!spec) return code;
      return zh ? spec.title_zh : spec.title_en;
    },
    [catalog, zh],
  );

  const rows = useMemo(() => {
    if (!catalog) return [] as { spec: DocType; tpl?: TemplateRow }[];
    return catalog.types.map((spec) => {
      const tpl =
        catalog.templates.find((r) => r.entity_type === spec.code && r.locale === locale) ||
        catalog.templates.find((r) => r.entity_type === spec.code);
      return { spec, tpl };
    });
  }, [catalog, locale]);

  async function save() {
    if (!detail) return;
    setBusy(true);
    try {
      const res = (await apiPut(`/api/v1/documents/templates/${detail.id}`, {
        body,
        css,
      })) as { version?: number };
      toast.success(
        t("page.templates.saved", "Template saved (v{n})", { n: String(res?.version ?? "") }),
      );
      setDirty(false);
      await loadCatalog();
      await loadDetail(activeType, locale);
    } catch (err) {
      toast.error(t("page.templates.save_fail", "Failed to save: {err}", { err: msgOf(err) }));
    } finally {
      setBusy(false);
    }
  }

  async function resetToDefault() {
    if (!detail) return;
    setPendingReset(true);
  }

  async function doResetToDefault() {
    if (!detail) return;
    setBusy(true);
    try {
      const res = (await apiPost(`/api/v1/documents/templates/${detail.id}/reset`, {})) as {
        body?: string;
        css?: string;
      };
      setBody(res?.body ?? detail.system_body ?? "");
      setCss(res?.css ?? detail.system_css ?? "");
      setDirty(false);
      toast.success(t("page.templates.reset_ok", "Restored built-in layout"));
      await loadCatalog();
    } catch (err) {
      toast.error(t("page.templates.reset_fail", "Failed to restore: {err}", { err: msgOf(err) }));
    } finally {
      setBusy(false);
    }
  }

  /** PDF 预览：必须走 POST。
   *
   * 端点是 `POST /documents/templates/{id}/preview/pdf`（body 里带当前草稿 body/css），
   * 之前这里用的是 <a href> → 浏览器发 GET → 后端 405，点开是一页 JSON 报错；
   * 而且 GET 也带不了草稿，渲染出来的会是**已保存**的旧版式，与左侧 iframe 的草稿预览不一致。
   * 现在同步开窗（避免 await 之后被弹窗拦截），再把返回的 PDF blob 塞进去。
   */
  async function openPdf() {
    if (!detail) return;
    const base = process.env.NEXT_PUBLIC_API_BASE || "";
    const win = window.open("", "_blank");
    setBusy(true);
    try {
      const token = readStorage(TOKEN_STORAGE_KEY);
      const res = await fetch(`${base}/api/v1/documents/templates/${detail.id}/preview/pdf`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ body, css }),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => null);
        // 走统一的 apiError：状态码 → 人话文案（不要把 "HTTP 500" 抛给用户）
        throw apiError("POST", `/api/v1/documents/templates/${detail.id}/preview/pdf`, res.status, j);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      if (win) win.location.href = url;
      else window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) {
      if (win) win.close();
      toast.error(t("page.templates.pdf_failed", "PDF preview failed: {err}", { err: msgOf(err) }));
    } finally {
      setBusy(false);
    }
  }

  /** 在光标处插入变量名 —— 变量速查栏点击即用，省得手抄字段名 */
  function insertVariable(name: string) {
    const plain = name.split(" ")[0];
    if (tab === "body") {
      setBody((prev) => `${prev}${prev.endsWith("\n") || prev === "" ? "" : "\n"}{{ ${plain} }}\n`);
    } else {
      setCss((prev) => `${prev}${prev.endsWith("\n") || prev === "" ? "" : "\n"}/* ${plain} */\n`);
    }
    setDirty(true);
  }

  function onTabKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // 代码编辑器：Tab 插两个空格而不是跳焦点（Shift+Tab 仍跳出）
    if (e.key !== "Tab" || e.shiftKey) return;
    e.preventDefault();
    const el = e.currentTarget;
    const { selectionStart: s, selectionEnd: en, value } = el;
    const next = `${value.slice(0, s)}  ${value.slice(en)}`;
    if (tab === "body") setBody(next);
    else setCss(next);
    setDirty(true);
    requestAnimationFrame(() => {
      el.selectionStart = el.selectionEnd = s + 2;
    });
  }

  const vars: VarHint[] = detail?.variables ?? [];
  const bodyEdited = detail ? body !== (detail.body || "") : false;
  const cssEdited = detail ? css !== (detail.css || "") : false;

  return (
    <AppShell>
      <PageHeader
        title={t("page.templates.title", "Document templates")}
        subtitle={t(
          "page.templates.subtitle",
          "Edit the layout of outbound documents. Company letterhead, logo and bank details are injected automatically.",
        )}
        actions={
          <>
            <select
              className="input"
              value={locale}
              onChange={(e) => setLocale(e.target.value)}
              aria-label={t("page.templates.locale", "Language")}
            >
              {LOCALES.map((l) => (
                <option key={l} value={l}>
                  {l === "zh" ? t("page.templates.locale_zh", "中文") : "English"}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn btn-sm"
              onClick={resetToDefault}
              disabled={!detail || !detail.is_system || busy}
              title={
                detail?.is_system
                  ? undefined
                  : t("page.templates.reset_disabled", "Custom templates cannot be reset")
              }
            >
              {t("page.templates.reset", "Restore default")}
            </button>
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={save}
              disabled={!detail || busy}
            >
              {dirty || bodyEdited || cssEdited
                ? t("page.templates.save", "Save")
                : t("page.templates.saved_label", "Saved")}
            </button>
          </>
        }
      />

      {catalogErr ? (
        <div className="error">
          {catalogErr}{" "}
          <button type="button" className="btn btn-sm" onClick={() => loadCatalog().catch(handled)}>
            {t("common.retry", "重试")}
          </button>
        </div>
      ) : null}

      <div className="tpl-layout">
        {/* 左：单据类型 */}
        <nav className="tpl-types" aria-label={t("page.templates.types", "Document types")}>
          <div className="tpl-types-head">
            {t("page.templates.types", "Document types")}
          </div>
          <div className="tpl-types-body">
            {rows.map(({ spec, tpl }) => (
              <button
                key={spec.code}
                type="button"
                className={`tpl-type${spec.code === activeType ? " active" : ""}`}
                onClick={() => setActiveType(spec.code)}
              >
                <span className="tpl-type-label">{typeTitle(spec.code)}</span>
                {tpl?.edited ? (
                  <span
                    className="tpl-dot"
                    title={t("page.templates.edited_hint", "Modified from the built-in layout")}
                  />
                ) : null}
              </button>
            ))}
          </div>
        </nav>

        {/* 中：代码编辑 */}
        <section className="tpl-editor">
          {detailErr ? <p className="text-danger">{detailErr}</p> : null}
          <Tabs
            variant="pill"
            items={[
              { key: "body", label: "HTML" },
              { key: "css", label: "CSS" },
            ]}
            value={tab}
            onChange={(k) => setTab(k as "body" | "css")}
          />
          <textarea
            className="tpl-code"
            spellCheck={false}
            value={tab === "body" ? body : css}
            onKeyDown={onTabKey}
            onChange={(e) => {
              if (tab === "body") setBody(e.target.value);
              else setCss(e.target.value);
              setDirty(true);
            }}
            aria-label={
              tab === "body"
                ? t("page.templates.body_label", "Template HTML")
                : t("page.templates.css_label", "Template CSS")
            }
          />
          <div className="tpl-editor-foot">
            <span>
              {t("page.templates.version", "Version")} {detail?.version ?? "—"}
            </span>
            {bodyEdited || cssEdited ? (
              <span className="tpl-dot" title={t("page.templates.unsaved", "Unsaved changes")} />
            ) : null}
            <span className="spacer" />
            {detail && !detail.is_system ? (
              <span>{t("page.templates.custom_note", "Custom template — no built-in default")}</span>
            ) : null}
          </div>
        </section>

        {/* 右：预览 + 变量速查 */}
        <aside className="tpl-side">
          <div className="tpl-preview">
            <div className="tpl-preview-head">
              <span>{t("page.templates.preview", "Preview")}</span>
              <span className="spacer" />
              {catalog?.pdf_available ? (
                <button
                  className="btn btn-sm"
                  type="button"
                  onClick={() => void openPdf()}
                  disabled={!detail || busy}
                >
                  {t("page.templates.pdf", "PDF")}
                </button>
              ) : (
                <span title={t("page.templates.pdf_missing", "Install Chromium to enable PDF")}>
                  {t("page.templates.pdf_off", "PDF unavailable")}
                </span>
              )}
            </div>
            {previewErr ? (
              <div className="tpl-empty">{previewErr}</div>
            ) : previewHtml ? (
              <iframe
                ref={frameRef}
                className="tpl-frame"
                title={t("page.templates.preview_title", "Template preview")}
                // P0-5：srcDoc 里的 HTML 来自租户可编辑的模板 + 用户可编辑的主数据，
                // 没有 sandbox 时是存储型 XSS 的同源执行入口（可读 cookie / 打 API）。
                // sandbox="" = 完全隔离：不脚本、不表单、不同源、不顶层导航。
                sandbox=""
                referrerPolicy="no-referrer"
                // 预览 HTML 由后端沙箱渲染后返回；前端再剥一层可执行内容兜底。
                srcDoc={stripActiveContent(previewHtml)}
              />
            ) : (
              <div className="tpl-empty">
                {t("page.templates.preview_loading", "Rendering preview…")}
              </div>
            )}
          </div>

          <div className="tpl-vars">
            <div className="tpl-vars-head">
              {t("page.templates.variables", "Available variables")}
            </div>
            <div className="tpl-vars-body">
              {vars.map((v) => (
                <div
                  key={v.name}
                  className="tpl-var"
                  role="button"
                  tabIndex={0}
                  onClick={() => insertVariable(v.name)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      insertVariable(v.name);
                    }
                  }}
                  title={t("page.templates.insert_hint", "Click to insert")}
                >
                  <span className="tpl-var-name">{v.name}</span>
                  <span className="tpl-var-desc">{v.desc}</span>
                </div>
              ))}
              {!vars.length ? (
                <div className="tpl-empty">
                  {t("page.templates.variables_none", "No variables documented")}
                </div>
              ) : null}
            </div>
          </div>

          <p className="tpl-note">
            {t(
              "page.templates.letterhead_note",
              "Company name, logo, address and bank details come from Administration → Company profile — do not hardcode them here.",
            )}
          </p>
        </aside>
      </div>
      <ConfirmDialog
        open={pendingReset}
        title={t("common.confirm", "Confirm")}
        message={t(
          "page.templates.reset_confirm",
          "Restore the built-in layout for this template? Your current layout will be replaced.",
        )}
        danger
        confirmLabel={t("common.confirm", "Confirm")}
        onConfirm={() => {
          setPendingReset(false);
          void doResetToDefault();
        }}
        onCancel={() => setPendingReset(false)}
      />
    </AppShell>
  );
}
