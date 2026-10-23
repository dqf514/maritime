"use client";

// 平台设置 — 上传策略（文件类型 + 大小上限）。
// ConfigFlag 平台级存储，platform_admin 可调；各上传口（证书/品牌/Excel/导入）统一遵循。

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { apiGet, apiPut } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type Policy = { kind: string; max_bytes: number; exts: string[] };
type Settings = { kinds: Record<string, Policy> };

const KIND_ORDER = ["document", "image", "data"];

function mb(bytes: number): string {
  return String(Math.round((bytes / (1024 * 1024)) * 100) / 100);
}

export default function PlatformSettingsPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);

  async function load() {
    try {
      const s = (await apiGet("/api/v1/platform/upload-settings")) as Settings;
      setSettings(s);
      setDraft(s);
    } catch {
      toast.error(t("page.settings.admin_required", "Platform admin required"));
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useListHotkeys(() => undefined);

  function patch(kind: string, patchObj: Partial<Policy>) {
    setDraft((d) =>
      d ? { ...d, kinds: { ...d.kinds, [kind]: { ...d.kinds[kind], ...patchObj } } } : d,
    );
  }

  async function save(e?: FormEvent) {
    e?.preventDefault();
    if (!draft) return;
    setSaving(true);
    try {
      const payload = {
        kinds: Object.fromEntries(
          KIND_ORDER.filter((k) => draft.kinds[k]).map((k) => [
            k,
            {
              max_bytes: Math.round(Number(draft.kinds[k].max_bytes) * 1024 * 1024),
              exts: draft.kinds[k].exts,
            },
          ]),
        ),
      };
      await apiPut("/api/v1/platform/upload-settings", payload);
      toast.success(t("page.settings.saved", "Upload policy saved"));
      await load();
    } catch (ex: any) {
      toast.error(ex?.message || t("common.failed", "Failed"));
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
      {!draft ? (
        <div className="panel">
          <p className="muted">{t("common.loading", "加载中…")}</p>
        </div>
      ) : (
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
                          onChange={(e) => patch(k, { max_bytes: Number(e.target.value) })}
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
      )}
    </AppShell>
  );
}
