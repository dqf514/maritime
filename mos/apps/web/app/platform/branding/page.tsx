"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ImageCropModal, type CropKind } from "@/components/ImageCropModal";
import { apiGet, apiPost, apiPut, apiUpload } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Branding = {
  product_name: string;
  tagline: string;
  logo_url: string;
  icon_url: string;
  favicon_url: string;
  primary_color: string;
  hero_title: string;
  hero_subtitle: string;
};

const MAX_UPLOAD_BYTES = 2.5 * 1024 * 1024;
const OK_TYPES = ["image/png", "image/jpeg", "image/webp"];

export default function PlatformBrandingPage() {
  const { t } = useI18n();
  const [form, setForm] = useState<Branding | null>(null);
  const [msg, setMsg] = useState("");
  const [uploading, setUploading] = useState<string | null>(null);
  const [crop, setCrop] = useState<{ kind: CropKind; file: File } | null>(null);
  const [cropErr, setCropErr] = useState("");

  useEffect(() => {
    apiGet("/api/v1/platform/branding")
      .then(setForm)
      .catch(() => setMsg(t("page.branding.admin_required", "需要平台管理员")));
  }, [t]);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    try {
      await apiPut("/api/v1/platform/branding", form);
      setMsg(t("page.branding.updated", "产品品牌已更新 — 门户、登录与顶栏会随之生效。"));
    } catch {
      setMsg(t("common.failed", "保存失败"));
    }
  }

  async function reset() {
    try {
      setForm(await apiPost("/api/v1/platform/branding/reset"));
      setMsg(t("page.branding.reset_done", "已恢复 MariOS 默认品牌。"));
    } catch {
      setMsg(t("page.branding.reset_fail", "重置失败"));
    }
  }

  function pickFile(kind: CropKind, file: File | null) {
    if (!file) return;
    setMsg("");
    if (!OK_TYPES.includes(file.type)) {
      setMsg(t("page.branding.bad_type", "仅支持 png / jpg / webp 图片"));
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setMsg(t("page.branding.too_large", "文件超过 2.5MB，请压缩后再传"));
      return;
    }
    setCropErr("");
    setCrop({ kind, file });
  }

  async function confirmUpload(blob: Blob) {
    if (!crop) return;
    const { kind } = crop;
    setUploading(kind);
    setCropErr("");
    try {
      const fd = new FormData();
      fd.append("file", blob, `${kind}.png`);
      setForm(await apiUpload(`/api/v1/platform/branding/upload?kind=${kind}`, fd));
      setMsg(t("page.branding.uploaded", "已上传 {kind}", { kind }));
      setCrop(null);
    } catch (err: any) {
      setCropErr(t("page.branding.upload_fail", "上传失败：{err}", { err: String(err?.message || err) }));
    } finally {
      setUploading(null);
    }
  }

  if (!form) {
    return (
      <AppShell>
        <p>{msg || t("common.loading", "加载中…")}</p>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.branding.title", "产品品牌")}</h1>
      <p className="page-sub">
        {t("page.branding.sub", "管理公共门户 Logo / 图标 / 文案。图片直接上传，可裁剪。")}
      </p>
      {msg ? <p className="flash">{msg}</p> : null}

      <div className="brand-preview panel">
        <div className="brand-preview-row" style={{ display: "flex", gap: "1.25rem", alignItems: "center", flexWrap: "wrap" }}>
          <img src={form.icon_url} alt="icon" width={64} height={64} />
          <img src={form.logo_url} alt="logo" style={{ maxHeight: 64, maxWidth: 280 }} />
        </div>
      </div>

      <div className="panel">
        <h2 style={{ marginTop: 0 }}>{t("page.branding.upload_title", "上传素材")}</h2>
        <p className="muted">{t("page.branding.upload_hint", "支持 png / jpg / webp，单文件不超过 2.5MB；上传前可拖动裁剪。")}</p>
        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          {(
            [
              ["logo", t("page.branding.logo", "Logo")],
              ["icon", t("page.branding.icon", "图标")],
              ["favicon", t("page.branding.favicon", "Favicon")],
            ] as const
          ).map(([kind, label]) => (
            <label key={kind} className="btn btn-ghost" style={{ cursor: "pointer" }}>
              {uploading === kind ? "…" : `${t("page.branding.upload", "上传")} ${label}`}
              <input
                type="file"
                accept=".png,.jpg,.jpeg,.webp"
                hidden
                disabled={Boolean(uploading)}
                onChange={(e) => {
                  pickFile(kind, e.target.files?.[0] || null);
                  e.target.value = "";
                }}
              />
            </label>
          ))}
        </div>
      </div>

      <form className="panel" onSubmit={save}>
        <h2 style={{ marginTop: 0 }}>{t("page.branding.fields", "文案与链接")}</h2>
        <div className="kv-grid">
          {(
            [
              "product_name",
              "tagline",
              "primary_color",
              "hero_title",
              "hero_subtitle",
            ] as const
          ).map((k) => (
            <label key={k} style={k.includes("hero") || k === "tagline" ? { gridColumn: "1 / -1" } : undefined}>
              {k.replaceAll("_", " ")}
              {k === "hero_subtitle" ? (
                <textarea
                  value={form[k]}
                  rows={3}
                  onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                  style={{ width: "100%", marginTop: "0.25rem" }}
                />
              ) : (
                <input value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
              )}
            </label>
          ))}
        </div>
        <div style={{ display: "flex", gap: "0.75rem", marginTop: "1rem" }}>
          <button className="btn btn-primary" type="submit">
            {t("page.branding.save", "保存品牌")}
          </button>
          <button className="btn" type="button" onClick={reset}>
            {t("page.branding.reset", "恢复默认")}
          </button>
        </div>
      </form>

      <ImageCropModal
        open={Boolean(crop)}
        kind={crop?.kind || "logo"}
        file={crop?.file || null}
        busy={Boolean(uploading)}
        error={cropErr}
        onCancel={() => {
          if (uploading) return;
          setCrop(null);
          setCropErr("");
        }}
        onConfirm={confirmUpload}
      />
    </AppShell>
  );
}
