"use client";

// 平台设置 — 上传策略（文件类型 + 大小上限）。
// ConfigFlag 平台级存储，platform_admin 可调；各上传口（证书/品牌/Excel/导入）统一遵循。

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { StateView } from "@/components/StateView";
import { apiGet, apiPut } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type Policy = { kind: string; max_bytes: number; exts: string[] };
type Settings = { kinds: Record<string, Policy> };
/** 草稿里 max_bytes 允许是原始字符串（避免非法输入被静默转成 0） */
type DraftPolicy = { kind: string; max_bytes: number | string; exts: string[] };
type DraftSettings = { kinds: Record<string, DraftPolicy> };

const KIND_ORDER = ["document", "image", "data"];

function mb(bytes: unknown): string {
  const n = typeof bytes === "number" ? bytes : Number(bytes);
  if (bytes === "" || bytes === null || bytes === undefined || !Number.isFinite(n)) return "";
  return String(Math.round((n / (1024 * 1024)) * 100) / 100);
}

export default function PlatformSettingsPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [draft, setDraft] = useState<DraftSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const s = (await apiGet("/api/v1/platform/upload-settings")) as Settings;
      setSettings(s);
      setDraft(s);
    } catch (ex) {
      setErr(msgOf(ex, t("page.settings.admin_required", "Platform admin required")));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useListHotkeys(() => undefined);

  function patch(kind: string, patchObj: Partial<DraftPolicy>) {
    setDraft((d) =>
      d ? { ...d, kinds: { ...d.kinds, [kind]: { ...d.kinds[kind], ...patchObj } } } : d,
    );
  }

  async function save(e?: FormEvent) {
    e?.preventDefault();
    if (!draft) return;
    setSaving(true);
    try {
      // 数值校验：非法输入中止提交，不把垃圾值静默变成 0
      const kinds: Record<string, { max_bytes: number; exts: string[] }> = {};
      for (const k of KIND_ORDER.filter((k) => draft.kinds[k])) {
        const raw = draft.kinds[k].max_bytes;
        const n = typeof raw === "number" ? raw : Number(String(raw).trim());
        if (!Number.isFinite(n)) {
          toast.error(
            t("page.settings.invalid_max", "{kind} 的大小上限必须是数字。", { kind: kindLabel(k) }),
          );
          setSaving(false);
          return;
        }
        if (n <= 0) {
          toast.error(
            t("page.settings.invalid_max_positive", "{kind} 的大小上限必须大于 0。", { kind: kindLabel(k) }),
          );
          setSaving(false);
          return;
        }
        kinds[k] = { max_bytes: Math.round(n * 1024 * 1024), exts: draft.kinds[k].exts };
      }
      const payload = { kinds };
      await apiPut("/api/v1/platform/upload-settings", payload);
      toast.success(t("page.settings.saved", "Upload policy saved"));
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("common.failed", "Failed")));
    } finally {
      setSaving(false);
    }
  }

  const kindLabel = (k: string) =>
    k === "document"
      ? t("page.settings.kind_document", "文档 / 附件")
      : k === "image"
        ? t("page.settings.kind_image", "图片 / 品牌")
        : t("page.settings.kind_data", "数据 / 导入");

  const kindHint = (k: string) =>
    k === "document"
      ? t("page.settings.hint_document", "证书、迁移 Excel 等通用上传")
      : k === "image"
        ? t("page.settings.hint_image", "Logo、图标（仅栅格图）")
        : t("page.settings.hint_data", "CSV / 文本导入");

  return (
    <AppShell>
      <PageHeader
        title={t("page.settings.title", "Platform settings")}
        subtitle={t("page.settings.sub", "Global upload policy — allowed file types and size limits.")}
        breadcrumb={[
          { label: t("page.platform.title", "Platform"), href: "/platform" },
          { label: t("page.settings.title", "Platform settings") },
        ]}
      />
      <StateView loading={loading} error={err ?? undefined} empty={false} onRetry={() => load()}>
        {draft ? (
        <form onSubmit={save}>
          <Toolbar
            right={
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {saving ? t("common.saving", "保存中…") : t("common.save", "保存")}
              </button>
            }
          />
          <div className="panel">
            <h2 className="panel-title">{t("page.settings.upload_section", "上传策略")}</h2>
            <p className="muted">{t("page.settings.upload_desc", "限制全平台上载文件的类型与大小；各上传入口统一遵循此策略。")}</p>
            <div className="form-panel form-panel-2col">
              {KIND_ORDER.filter((k) => draft.kinds[k]).map((k) => {
                const p = draft.kinds[k];
                return (
                  <section key={k} className="form-section">
                    <div className="form-section-title">{kindLabel(k)}</div>
                    <p className="muted">{kindHint(k)}</p>
                    <div className="form-section-body">
                      <label className="field-row">
                        <span className="field-label">{t("page.settings.col_max", "大小上限 (MB)")}</span>
                        <input
                          type="number"
                          min={0.1}
                          step={0.1}
                          value={mb(p.max_bytes)}
                          onChange={(e) => patch(k, { max_bytes: e.target.value })}
                        />
                      </label>
                      <label className="field-row span-all">
                        <span className="field-label">{t("page.settings.col_exts", "允许扩展名（逗号分隔）")}</span>
                        <input
                          type="text"
                          value={p.exts.join(", ")}
                          onChange={(e) =>
                            patch(k, {
                              exts: e.target.value
                                .split(",")
                                .map((x) => x.trim().toLowerCase())
                                .filter(Boolean),
                            })
                          }
                        />
                      </label>
                    </div>
                  </section>
                );
              })}
            </div>
          </div>
        </form>
        ) : null}
      </StateView>
    </AppShell>
  );
}
