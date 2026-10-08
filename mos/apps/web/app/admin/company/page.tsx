"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ImageCropModal } from "@/components/ImageCropModal";
import { PageHeader } from "@/components/PageHeader";
import { apiGet, apiPut, apiUpload } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

const MAX_LOGO_BYTES = 2.5 * 1024 * 1024;
const OK_TYPES = ["image/png", "image/jpeg", "image/webp"];

type Profile = {
  legal_name: string;
  display_name: string;
  logo_url: string;
  website: string;
  tax_no: string;
  address: string;
  phone: string;
  brand_primary: string;
  brand_secondary?: string;
};

const TEXT_FIELDS: (keyof Profile)[] = [
  "legal_name",
  "display_name",
  "website",
  "tax_no",
  "address",
  "phone",
  "brand_primary",
  "brand_secondary",
];

export default function CompanyBrandPage() {
  const { t } = useI18n();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [form, setForm] = useState<Profile>({
    legal_name: "",
    display_name: "",
    logo_url: "",
    website: "",
    tax_no: "",
    address: "",
    phone: "",
    brand_primary: "#1A9B96",
    brand_secondary: "",
  });
  const [crop, setCrop] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadErr, setUploadErr] = useState("");

  useEffect(() => {
    apiGet("/api/v1/admin/company-profile")
      .then((p) => setForm((f) => ({ ...f, ...p })))
      .catch(() => toast.success(t("page.company.admin_required", "Tenant admin required")));
  }, [t]);

  async function save(e: FormEvent) {
    e.preventDefault();
    await apiPut("/api/v1/admin/company-profile", form);
    toast.success(t("page.company.saved", "Company brand saved — appears in Shell & documents."));
  }

  function pickFile(file: File | null) {
    if (!file) return;
    setUploadErr("");
    if (!OK_TYPES.includes(file.type)) {
      setUploadErr(t("page.company.bad_type", "仅支持 png / jpg / webp 图片"));
      return;
    }
    if (file.size > MAX_LOGO_BYTES) {
      setUploadErr(t("page.company.too_large", "文件超过 2.5MB，请压缩后再传"));
      return;
    }
    setCrop(file);
  }

  async function confirmUpload(blob: Blob) {
    setUploading(true);
    setUploadErr("");
    try {
      const fd = new FormData();
      fd.append("file", blob, "logo.png");
      const out = await apiUpload("/api/v1/admin/company-profile/logo", fd);
      setForm((f) => ({ ...f, logo_url: out.logo_url }));
      toast.success(t("page.company.logo_uploaded", "Logo 已上传，保存后全站生效。"));
      setCrop(null);
    } catch (err: any) {
      setUploadErr(t("page.company.upload_fail", "上传失败：{err}", { err: String(err?.message || err) }));
    } finally {
      setUploading(false);
    }
  }

  return (
    <AppShell>
      <PageHeader
        title={t("page.company.title", "Company & brand")}
        subtitle={t("page.company.sub", "Tenant company profile shown in shell and documents.")}
      />
      <form className="panel" onSubmit={(e) => save(e).catch(() => toast.success(t("common.failed", "Failed")))}>
        {/* ── Logo upload ── */}
        <div className="company-logo-row">
          <div className="company-logo-preview">
            {form.logo_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={form.logo_url} alt="logo" />
            ) : (
              <span className="company-logo-placeholder">?</span>
            )}
          </div>
          <div className="company-logo-actions">
            <span className="company-logo-label">{t("page.company.logo", "logo")}</span>
            <div className="company-logo-btns">
              <label className="btn btn-sm" style={{ cursor: "pointer" }}>
                {uploading ? "…" : form.logo_url ? t("page.company.logo_replace", "更换 Logo") : t("page.company.logo_upload", "上传 Logo")}
                <input
                  ref={fileRef}
                  type="file"
                  accept=".png,.jpg,.jpeg,.webp"
                  hidden
                  disabled={uploading}
                  onChange={(e) => {
                    pickFile(e.target.files?.[0] || null);
                    e.target.value = "";
                  }}
                />
              </label>
              {form.logo_url ? (
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  onClick={() => setForm((f) => ({ ...f, logo_url: "" }))}
                >
                  {t("page.company.logo_remove", "移除")}
                </button>
              ) : null}
            </div>
            <span className="company-logo-hint">
              {t("page.company.logo_hint", "png / jpg / webp，≤ 2.5MB，上传前可裁剪")}
            </span>
            {uploadErr ? <span className="flash-err">{uploadErr}</span> : null}
          </div>
        </div>

        <div className="kv-grid">
          {TEXT_FIELDS.map((k) => (
            <label key={k}>
              {String(k).replaceAll("_", " ")}
              <input
                value={form[k] || ""}
                onChange={(e) => setForm({ ...form, [k]: e.target.value })}
              />
            </label>
          ))}
        </div>
        <button className="btn btn-primary" type="submit" style={{ marginTop: "1rem" }}>
          {t("page.company.save", "Save profile")}
        </button>
      </form>

      <ImageCropModal
        open={Boolean(crop)}
        kind="logo"
        file={crop}
        busy={uploading}
        error={uploadErr}
        onCancel={() => {
          if (uploading) return;
          setCrop(null);
          setUploadErr("");
        }}
        onConfirm={confirmUpload}
      />
    </AppShell>
  );
}
