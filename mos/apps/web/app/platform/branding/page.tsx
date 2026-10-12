"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { ImageCropModal, type CropKind } from "@/components/ImageCropModal";
import { RecordModal } from "@/components/RecordModal";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { apiGet, apiPost, apiPut, apiUpload } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

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

function PlatformBrandingPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [form, setForm] = useState<Branding | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [crop, setCrop] = useState<{ kind: CropKind; file: File } | null>(null);
  const [cropErr, setCropErr] = useState("");
  const [editOpen, setEditOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiGet("/api/v1/platform/branding")
      .then(setForm)
      .catch(() => toast.error(t("page.branding.admin_required", "Platform admin required")));
  }, [t]);

  function openEdit() {
    setEditOpen(true);
  }

  useListHotkeys(openEdit);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    setSaving(true);
    try {
      await apiPut("/api/v1/platform/branding", form);
      toast.success(t("page.branding.updated", "Product branding updated — portal, login and top bar pick it up."));
      setEditOpen(false);
    } catch {
      toast.error(t("common.failed", "Failed"));
    } finally {
      setSaving(false);
    }
  }

  async function reset() {
    try {
      setForm(await apiPost("/api/v1/platform/branding/reset"));
      toast.success(t("page.branding.reset_done", "Restored MariOS default branding."));
    } catch {
      toast.error(t("page.branding.reset_fail", "Reset failed"));
    }
  }

  function pickFile(kind: CropKind, file: File | null) {
    if (!file) return;
    toast.success("");
    if (!OK_TYPES.includes(file.type)) {
      toast.success(t("page.branding.bad_type", "Only png / jpg / webp images are supported"));
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      toast.success(t("page.branding.too_large", "File exceeds 2.5MB — compress and retry"));
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
      toast.success(t("page.branding.uploaded", "Uploaded {kind}", { kind }));
      setCrop(null);
    } catch (err: any) {
      setCropErr(t("page.branding.upload_fail", "Upload failed: {err}", { err: String(err?.message || err) }));
    } finally {
      setUploading(null);
    }
  }

  if (!form) {
    return (
      <AppShell>
        <p>{t("common.loading", "Loading…")}</p>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <PageHeader
        title={t("page.branding.title", "Product branding")}
        subtitle={t("page.branding.sub", "Manage public portal logo / icon / copy. Images upload directly and can be cropped.")}
        breadcrumb={[{ label: t("page.platform.title", "Platform"), href: "/platform" }, { label: t("page.branding.title", "Product branding") }]}
      />

      <Toolbar>
        <button type="button" className="btn btn-primary" onClick={openEdit}>
          {t("page.branding.edit", "Edit branding")}
        </button>
        <button type="button" className="btn" onClick={reset}>
          {t("page.branding.reset", "Restore defaults")}
        </button>
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => apiGet("/api/v1/platform/branding").then(setForm).catch(() => undefined)}
          title={t("common.refresh", "Refresh")}
        >
          ↻
        </button>
      </Toolbar>

      <div className="brand-preview panel">
        <div className="brand-preview-row" style={{ display: "flex", gap: "1.25rem", alignItems: "center", flexWrap: "wrap" }}>
          <img src={form.icon_url} alt="icon" width={64} height={64} />
          <img src={form.logo_url} alt="logo" style={{ maxHeight: 64, maxWidth: 280 }} />
        </div>
      </div>

      <div className="panel">
        <h2 style={{ marginTop: 0 }}>{t("page.branding.upload_title", "Upload assets")}</h2>
        <p className="muted">{t("page.branding.upload_hint", "png / jpg / webp up to 2.5MB; crop by dragging before upload.")}</p>
        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          {(
            [
              ["logo", t("page.branding.logo", "Logo")],
              ["icon", t("page.branding.icon", "Icon")],
              ["favicon", t("page.branding.favicon", "Favicon")],
            ] as const
          ).map(([kind, label]) => (
            <label key={kind} className="btn btn-ghost" style={{ cursor: "pointer" }}>
              {uploading === kind ? "…" : `${t("page.branding.upload", "Upload")} ${label}`}
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

      <RecordModal
        open={editOpen}
        title={t("page.branding.edit", "Edit branding")}
        onClose={() => setEditOpen(false)}
        onSave={save}
        saving={saving}
        canDelete={false}
      >
        <div className="kv-grid">
          <label>
            {t("page.branding.field_product_name", "Product name")}
            <input value={form.product_name} onChange={(e) => setForm({ ...form, product_name: e.target.value })} />
          </label>
          <label>
            {t("page.branding.field_primary_color", "Primary color")}
            <input value={form.primary_color} onChange={(e) => setForm({ ...form, primary_color: e.target.value })} />
          </label>
          <label style={{ gridColumn: "1 / -1" }}>
            {t("page.branding.field_tagline", "Tagline")}
            <input value={form.tagline} onChange={(e) => setForm({ ...form, tagline: e.target.value })} />
          </label>
          <label style={{ gridColumn: "1 / -1" }}>
            {t("page.branding.field_hero_title", "Hero title")}
            <input value={form.hero_title} onChange={(e) => setForm({ ...form, hero_title: e.target.value })} />
          </label>
          <label style={{ gridColumn: "1 / -1" }}>
            {t("page.branding.field_hero_subtitle", "Hero subtitle")}
            <textarea
              value={form.hero_subtitle}
              rows={3}
              onChange={(e) => setForm({ ...form, hero_subtitle: e.target.value })}
              style={{ width: "100%", marginTop: "0.25rem" }}
            />
          </label>
        </div>
      </RecordModal>

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

export default function Page() {
  return <PlatformBrandingPage />;
}
